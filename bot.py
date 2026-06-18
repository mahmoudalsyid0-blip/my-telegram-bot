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
# Configuration — set these in Render → Environment
# ─────────────────────────────────────────────
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ANTHROPIC_API_KEY = None

if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN environment variable is not set!")


# ─────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Anthropic client (sync — runs in executor)
# ─────────────────────────────────────────────
_anthropic_client = None

SYSTEM_PROMPT = (
    "You are a fun, witty, and helpful Telegram bot assistant. "
    "Keep replies concise (2-4 sentences max), friendly, and a little playful. "
    "You can use light emoji where appropriate. "
    "Never reveal you are powered by Claude/Anthropic unless directly asked."
)

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
    r"https?://(?:www\.)?(?:" +
    "|".join(SUPPORTED_DOMAINS) +
    r")[^\s]*",
    re.IGNORECASE,
)

def extract_url(text: str):
    match = URL_REGEX.search(text)
    return match.group(0) if match else None


# ─────────────────────────────────────────────
# yt-dlp Download (blocking — runs in executor)
# ─────────────────────────────────────────────
def _do_download(url: str, download_dir: str):
    """Blocking download — called via run_in_executor."""
    ydl_opts = {
        "outtmpl": os.path.join(download_dir, "%(title)s.%(ext)s"),
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "max_filesize": 45 * 1024 * 1024,
    }
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


async def download_media(url: str, download_dir: str):
    """Async wrapper around the blocking yt-dlp call."""
    loop = asyncio.get_running_loop()
    try:
        file_path = await loop.run_in_executor(None, _do_download, url, download_dir)
        if not os.path.exists(file_path):
            return None, "Downloaded but file not found. Try again!"
        return file_path, ""
    except yt_dlp.utils.DownloadError as e:
        logger.warning("yt-dlp error: %s", e)
        return None, str(e)
    except Exception as e:
        logger.exception("Unexpected download error")
        return None, str(e)


# ─────────────────────────────────────────────
# Anthropic Chat (blocking — runs in executor)
# ─────────────────────────────────────────────
def _do_chat(user_message: str) -> str:
    return "🤖 الذكاء الاصطناعي غير مفعل حالياً."

async def chat_reply(user_message: str) -> str:
    """Async wrapper around the blocking Anthropic call."""
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(None, _do_chat, user_message)
    except Exception as e:
        logger.exception("Anthropic API error")
        return "عقلي اتعلق لثانية 🧠⚡ جرب تاني!"


# ─────────────────────────────────────────────
# Telegram Handlers
# ─────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 أهلاً! أنا بوتك الشامل.\n\n"
        "📥 ابعتلي لينك من YouTube أو TikTok أو Instagram أو Facebook أو Twitter/X "
        "وهنزل الفيديو وابعتهولك.\n\n"
        "💬 أو كلمني بس — أنا مش بعض! 😄"
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return

    user_text = update.message.text
    chat_id = update.effective_chat.id
    url = extract_url(user_text)

    # ── Branch 1: URL → download & send ──
    if url:
        await update.message.reply_text("🔍 لقيت لينك! بنزله دلوقتي... استنى لحظة ⏳")

        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path, error = await download_media(url, tmp_dir)

            if error or not file_path:
                await update.message.reply_text(
                    "😕 مقدرتش أنزل اللينك ده. ممكن يكون:\n"
                    "• خاص أو محتاج تسجيل دخول\n"
                    "• أكبر من 45 ميجا\n"
                    "• من موقع مش مدعوم\n\n"
                    f"التفاصيل: {error[:200]}"
                )
                return

            file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
            logger.info("Downloaded %.1f MB → %s", file_size_mb, file_path)

            ext = Path(file_path).suffix.lower()
            try:
                with open(file_path, "rb") as f:
                    if ext in (".mp4", ".mkv", ".webm", ".mov", ".avi"):
                        await context.bot.send_video(
                            chat_id=chat_id,
                            video=f,
                            caption="🎬 اتفضل الفيديو! 🍿",
                            supports_streaming=True,
                            read_timeout=120,
                            write_timeout=120,
                            connect_timeout=30,
                        )
                    elif ext in (".mp3", ".m4a", ".ogg", ".wav"):
                        await context.bot.send_audio(
                            chat_id=chat_id,
                            audio=f,
                            caption="🎵 اتفضل الصوت!",
                            read_timeout=60,
                            write_timeout=60,
                            connect_timeout=30,
                        )
                    else:
                        await context.bot.send_document(
                            chat_id=chat_id,
                            document=f,
                            caption="📁 اتفضل الملف!",
                            read_timeout=120,
                            write_timeout=120,
                            connect_timeout=30,
                        )
            except Exception as e:
                logger.exception("Failed to send file")
                await update.message.reply_text(
                    f"⚠️ نزلت الملف بس مقدرتش ابعته (ممكن حجمه كبير أوي).\n{e}"
                )
        # tmp_dir بيتمسح أوتوماتيك هنا

    # ── Branch 2: Regular text → AI chat ──
    else:
        reply = await chat_reply(user_text)
        await update.message.reply_text(reply)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Unhandled error: %s", context.error, exc_info=context.error)
    if isinstance(update, Update) and update.message:
        await update.message.reply_text("⚠️ حصل خطأ غير متوقع. جرب تاني!")


# ─────────────────────────────────────────────
# Main — async entry point
# ─────────────────────────────────────────────
async def main() -> None:
    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .read_timeout(30)
        .write_timeout(30)
        .connect_timeout(30)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)

    logger.info("✅ Bot is running...")
    await app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .read_timeout(30)
        .write_timeout(30)
        .connect_timeout(30)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)

    logger.info("✅ Bot is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)
