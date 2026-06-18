import os
import re
import logging
import asyncio
import tempfile
from pathlib import Path

import yt_dlp
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
import anthropic

# ─────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────
BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN_HERE"         # ← Replace with your BotFather token
ANTHROPIC_API_KEY = "YOUR_ANTHROPIC_API_KEY_HERE"  # ← Replace with your Anthropic key (for chat)

# ─────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# URL Detection
# ─────────────────────────────────────────────
SUPPORTED_DOMAINS = [
    r"youtube\.com", r"youtu\.be",
    r"tiktok\.com",
    r"facebook\.com", r"fb\.watch",
    r"instagram\.com",
    r"twitter\.com", r"x\.com",
    r"vimeo\.com",
    r"reddit\.com",
    r"twitch\.tv",
]

URL_REGEX = re.compile(
    r"https?://(?:www\.)?" + r"|https?://(?:www\.)?".join(SUPPORTED_DOMAINS) +
    r"[^\s]*",
    re.IGNORECASE,
)

def extract_url(text: str) -> str | None:
    """Return the first supported URL found in text, or None."""
    match = URL_REGEX.search(text)
    return match.group(0) if match else None


# ─────────────────────────────────────────────
# yt-dlp Download Helper
# ─────────────────────────────────────────────
async def download_media(url: str, download_dir: str) -> tuple[str | None, str]:
    """
    Download media from a URL using yt-dlp.
    Returns (file_path, error_message). One of them will be None/empty.
    """
    ydl_opts = {
        "outtmpl": os.path.join(download_dir, "%(title)s.%(ext)s"),
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        # Cap file size at ~45 MB to stay under Telegram's 50 MB limit
        "max_filesize": 45 * 1024 * 1024,
    }

    loop = asyncio.get_event_loop()

    def _download():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            # Find the downloaded file
            if "entries" in info:          # playlist fallback (shouldn't happen)
                info = info["entries"][0]
            filename = ydl.prepare_filename(info)
            # yt-dlp might change the extension after merging
            base = os.path.splitext(filename)[0]
            for ext in ("mp4", "mkv", "webm", "mp3", "m4a"):
                candidate = f"{base}.{ext}"
                if os.path.exists(candidate):
                    return candidate
            return filename  # best guess

    try:
        file_path = await loop.run_in_executor(None, _download)
        if not os.path.exists(file_path):
            return None, "File was downloaded but I couldn't locate it. Try again!"
        return file_path, ""
    except yt_dlp.utils.DownloadError as e:
        logger.warning("yt-dlp DownloadError: %s", e)
        return None, str(e)
    except Exception as e:
        logger.exception("Unexpected download error")
        return None, str(e)


# ─────────────────────────────────────────────
# Anthropic Chat Helper
# ─────────────────────────────────────────────
_anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

SYSTEM_PROMPT = (
    "You are a fun, witty, and helpful Telegram bot assistant. "
    "Keep replies concise (2–4 sentences max), friendly, and a little playful. "
    "You can use light emoji where appropriate. "
    "If the user seems bored, suggest something interesting. "
    "Never reveal you are powered by Claude/Anthropic unless directly asked."
)

async def chat_reply(user_message: str) -> str:
    """Get a smart, playful reply from Claude for non-URL messages."""
    loop = asyncio.get_event_loop()

    def _call():
        response = _anthropic_client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=300,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        return response.content[0].text

    try:
        return await loop.run_in_executor(None, _call)
    except Exception as e:
        logger.exception("Anthropic API error")
        return "Hmm, my brain glitched for a second 🧠⚡ Try again in a moment!"


# ─────────────────────────────────────────────
# Handlers
# ─────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 Hey there! I'm your all-in-one bot.\n\n"
        "📥 **Send me a link** from YouTube, TikTok, Instagram, Facebook, Twitter/X "
        "and I'll download the video and send it back to you.\n\n"
        "💬 Or just **chat with me** — I don't bite! 😄",
        parse_mode="Markdown",
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_text = update.message.text or ""
    chat_id = update.effective_chat.id

    url = extract_url(user_text)

    # ── Branch 1: URL detected → download & send ──
    if url:
        await update.message.reply_text(
            "🔍 Link detected! Downloading your media... this may take a moment ⏳"
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path, error = await download_media(url, tmp_dir)

            if error or not file_path:
                friendly_error = (
                    "😕 Couldn't download that link. It might be:\n"
                    "• Private or age-restricted\n"
                    "• Too large (> 45 MB)\n"
                    "• From an unsupported platform\n\n"
                    f"Technical detail: `{error[:200]}`"
                )
                await update.message.reply_text(friendly_error, parse_mode="Markdown")
                return

            file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
            logger.info("Downloaded %.1f MB → %s", file_size_mb, file_path)

            try:
                ext = Path(file_path).suffix.lower()
                if ext in (".mp4", ".mkv", ".webm", ".mov", ".avi"):
                    await context.bot.send_video(
                        chat_id=chat_id,
                        video=open(file_path, "rb"),
                        caption="🎬 Here's your video! Enjoy 🍿",
                        supports_streaming=True,
                        read_timeout=120,
                        write_timeout=120,
                    )
                elif ext in (".mp3", ".m4a", ".ogg", ".wav"):
                    await context.bot.send_audio(
                        chat_id=chat_id,
                        audio=open(file_path, "rb"),
                        caption="🎵 Your audio file!",
                        read_timeout=60,
                        write_timeout=60,
                    )
                else:
                    await context.bot.send_document(
                        chat_id=chat_id,
                        document=open(file_path, "rb"),
                        caption="📁 Here's your file!",
                        read_timeout=120,
                        write_timeout=120,
                    )
            except Exception as e:
                logger.exception("Failed to send file")
                await update.message.reply_text(
                    f"⚠️ I downloaded the file but couldn't send it (maybe it's still too large for Telegram).\n`{e}`",
                    parse_mode="Markdown",
                )
            # ── Auto-cleanup: file is deleted automatically when `tmp_dir` exits ──

    # ── Branch 2: Regular text → smart AI chat ──
    else:
        reply = await chat_reply(user_text)
        await update.message.reply_text(reply)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Unhandled exception: %s", context.error, exc_info=context.error)
    if isinstance(update, Update) and update.message:
        await update.message.reply_text(
            "⚠️ Something unexpected happened on my end. Please try again!"
        )


# ─────────────────────────────────────────────
# Main Entry Point
# ─────────────────────────────────────────────
def main() -> None:
    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .read_timeout(30)
        .write_timeout(30)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)

    logger.info("Bot is running… Press Ctrl+C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
