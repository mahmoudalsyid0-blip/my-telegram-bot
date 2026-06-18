import os
from threading import Thread
from http.server import SimpleHTTPRequestHandler, HTTPServer
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ضع التوكن الخاص بك هنا
TOKEN = "8713359340:AAFaFaHP1xwO99P5DmTp7MSEyFHE3kyY4-M"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("أهلاً بك! أنا البوت الخاص بك، كيف يمكنني مساعدتك؟")

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(update.message.text)

# سيرفر وهمي لإبقاء البوت يعمل على المنصات المجانية
def run_dummy_server():
    port = int(os.environ.get("PORT", 8000))
    server = HTTPServer(('0.0.0.0', port), SimpleHTTPRequestHandler)
    server.serve_forever()

if __name__ == "__main__":
    # تشغيل السيرفر الوهمي في الخلفية
    Thread(target=run_dummy_server, daemon=True).start()
    
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))
    
    print("البوت يعمل الآن بنجاح على السيرفر...")
    app.run_polling()