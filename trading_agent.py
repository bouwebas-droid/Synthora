import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welkom! Ik ben je trading bot.\n\n"
        "Beschikbare commando's:\n"
        "/start — Dit bericht\n"
        "/status — Bot status\n"
        "/analyse — Voorbeeld analyse\n"
    )

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Bot is actief en draait op Render.")

async def analyse(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📊 Analyse gestart...")

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Je zei: {update.message.text}")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Exception:", exc_info=context.error)

if __name__ == '__main__':
    TOKEN = os.environ.get("TELEGRAM_TOKEN")

    if not TOKEN:
        logger.error("❌ TELEGRAM_TOKEN niet gevonden!")
        exit(1)

    logger.info("✅ Token gevonden, bot wordt gestart...")
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('status', status))
    app.add_handler(CommandHandler('analyse', analyse))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))
    app.add_error_handler(error_handler)
    logger.info("🤖 Bot draait nu!")
    app.run_polling(drop_pending_updates=True)

        
    
        

