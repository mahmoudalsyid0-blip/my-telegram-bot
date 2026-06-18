import os
import re
import logging
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

# ───────── CONFIG ─────────
BOT_TOKEN = os.environ.get("BOT_TOKEN")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")  # https://your-app.onrender.com

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing!")
if not WEBHOOK_URL:
    raise RuntimeError("WEBHOOK_URL is missing!")

# ───────── LOGGING ─────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ───────── URL DETECTION ─────────
URL_REGEX = re.compile(r"https?://\S+")

def extract_url(text: str):
    match = URL_REGEX.search(text)
    return match.group(0) if match else None

# ───────── DOWNLOAD ─────────
def download_media(url: str, download_dir: str):
    ydl_opts = {
        "outtmpl": os.path.join(download_dir, "%(title)s.%(ext)s"),
        "format": "bestvideo+bestaudio/best",
        "noplaylist": True,
        "quiet": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)
        return filename

# ───────── HANDLERS ─────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 أهلاً بيك!\nابعتلي لينك وأنا هنزلهولك 🎬"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    url = extract_url(text)

    if not url:
        await update.message.reply_text("ابعت لينك بس 👍")
        return

    await update.message.reply_text("⏳ جاري التحميل...")

    with tempfile.TemporaryDirectory() as tmp:
        try:
            file_path = download_media(url, tmp)

            with open(file_path, "rb") as f:
                await update.message.reply_video(video=f)

        except Exception as e:
            logger.exception(e)
            await update.message.reply_text("❌ حصل خطأ أثناء التحميل")

# ───────── MAIN ─────────
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)

    logger.info("Bot is running…")

    app.run_polling()
    

if __name__ == "__main__":
    main()
