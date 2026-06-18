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
BOT_TOKEN = "8713359340:AAFaFaHP1xwO99P5DmTp7MSEyFHE3kyY4-M"
ANTHROPIC_API_KEY = "YOUR_ANTHROPIC_API_KEY_HERE"

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
    match = URL_REGEX.search(text)
    return match.group(0) if match else None


# ─────────────────────────────────────────────
# yt-dlp Download Helper
# ─────────────────────────────────────────────
async def download_media(url: str, download_dir: str) -> tuple[str | None, str]:
    ydl_opts = {
        "outtmpl": os.path.join(download_dir, "%(title)s.%(ext)s"),
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "max_filesize": 45 * 1024 * 1024,
    }

    # تم التعديل هنا لضمان استقرار التشغيل
    loop = asyncio.get_running_loop()

    def _download():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if "entries" in info:
                info = info["entries"][0]
            filename = ydl.prepare_filename(info)
            base = os.path.splitext(filename)[0]
            for ext in ("mp4", "mkv", "webm", "mp3", "m4a"):
                candidate = f"{base}.{ext}"
                if os.path.exists(candidate):
                    return candidate
            return filename

    try:
        file_path = await loop.run_in_executor(None, _download)
        if not os.path.exists(file_path):
            return None, "File was downloaded but I couldn't locate it."
        return file_path, ""
    except Exception as e:
        logger.exception("Download error")
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
    # تم التعديل هنا لضمان استقرار التشغيل
    loop = asyncio.get_running_loop()

    def _call():
        response = _anthropic_client.messages.create(
            model="claude-3-sonnet-20240229", # تأكد من اسم الموديل الصحيح
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
        "📥 Send me a link... or just chat with me! 😄",
        parse_mode="Markdown",
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_text = update.message.text or ""
    chat_id = update.effective_chat.id
    url = extract_url(user_text)

    if url:
        await update.message.reply_text("🔍 Downloading... ⏳")
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path, error = await download_media(url, tmp_dir)
            if error or not file_path:
                await update.message.reply_text(f"😕 Error: {error[:100]}")
                return
            try:
                await context.bot.send_video(chat_id=chat_id, video=open(file_path, "rb"))
            except Exception as e:
                await update.message.reply_text("⚠️ Could not send file.")
    else:
        reply = await chat_reply(user_text)
        await update.message.reply_text(reply)

# ─────────────────────────────────────────────
# Main Entry Point
# ─────────────────────────────────────────────
def main() -> None:
    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot is running…")
    app.run_polling()

if __name__ == "__main__":
    main()