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

# ─────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────
import os

# هذا السطر يخبر البوت أن يبحث عن التوكن في "إعدادات السيرفر" (Environment Variables)
BOT_TOKEN = os.getenv("BOT_TOKEN")

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
    r"https?://(?:www\.)?(?:" + r"|".join(SUPPORTED_DOMAINS) + r")[^\s]*",
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

    def _download() -> str:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            # Unwrap playlist fallback (shouldn't happen with noplaylist=True)
            if "entries" in info:
                info = info["entries"][0]
            filename = ydl.prepare_filename(info)
            # yt-dlp may change the extension after merging
            base = os.path.splitext(filename)[0]
            for ext in ("mp4", "mkv", "webm", "mp3", "m4a"):
                candidate = f"{base}.{ext}"
                if os.path.exists(candidate):
                    return candidate
            return filename  # best guess

    try:
        # asyncio.to_thread is the modern replacement for loop.run_in_executor
        # and avoids "no current event loop" errors in Python 3.10+
        file_path = await asyncio.to_thread(_download)
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
# Handlers
# ─────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 Hey there! I'm your media downloader bot.\n\n"
        "📥 *Send me a link* from YouTube, TikTok, Instagram, Facebook, Twitter/X, "
        "Vimeo, Reddit, or Twitch and I'll download it and send it back to you.\n\n"
        "💬 Or type */help* to see this message again.",
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
                    with open(file_path, "rb") as f:
                        await context.bot.send_video(
                            chat_id=chat_id,
                            video=f,
                            caption="🎬 Here's your video! Enjoy 🍿",
                            supports_streaming=True,
                            read_timeout=120,
                            write_timeout=120,
                        )
                elif ext in (".mp3", ".m4a", ".ogg", ".wav"):
                    with open(file_path, "rb") as f:
                        await context.bot.send_audio(
                            chat_id=chat_id,
                            audio=f,
                            caption="🎵 Your audio file!",
                            read_timeout=60,
                            write_timeout=60,
                        )
                else:
                    with open(file_path, "rb") as f:
                        await context.bot.send_document(
                            chat_id=chat_id,
                            document=f,
                            caption="📁 Here's your file!",
                            read_timeout=120,
                            write_timeout=120,
                        )
            except Exception as e:
                logger.exception("Failed to send file")
                await update.message.reply_text(
                    f"⚠️ Downloaded but couldn't send it "
                    f"(likely still too large for Telegram).\n`{e}`",
                    parse_mode="Markdown",
                )
            # tmp_dir is cleaned up automatically when the `with` block exits

    # ── Branch 2: No URL → prompt the user ──
    else:
        await update.message.reply_text(
            "📎 Send me a supported media URL and I'll download it for you!\n\n"
            "Supported platforms: YouTube, TikTok, Instagram, Facebook, "
            "Twitter/X, Vimeo, Reddit, Twitch"
        )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Unhandled exception: %s", context.error, exc_info=context.error)
    if isinstance(update, Update) and update.message:
        await update.message.reply_text(
            "⚠️ Something unexpected happened on my end. Please try again!"
        )


# ─────────────────────────────────────────────
# Main Entry Point  ← KEY: synchronous main() + app.run_polling()
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
    app.add_handler(CommandHandler("help", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)
    app.run_polling(allowed_updates=Update.ALL_TYPES)  # نفسه — لسه صحيح في v22.8

if __name__ == "__main__":
    main()  # لسه بدون asyncio.run()
