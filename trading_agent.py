import os
import logging
import asyncio
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# --- LOGGING ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welkom! Ik ben SYNTHORA.\n"
        "Ik ben je AI Agent op Base.\n\n"
        "/start — Dit bericht\n"
        "/status — Bot status\n"
    )

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Hier kun je later checken of je CDP/Coinbase wallet geladen is
    await update.message.reply_text("✅ SYNTHORA is actief en verbonden met Base.")

async def handle_ai_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # TODO: Hier koppelen we straks je OpenAI + AgentKit logica
    user_text = update.message.text
    await update.message.reply_text(f"SYNTHORA denkt na over: {user_text}...")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("fout in bot:", exc_info=context.error)

# --- MAIN LOOP (Gecorrigeerd voor Render) ---
async def main():
    # LET OP: In je screenshot gebruik je TELEGRAM_BOT_TOKEN, niet TELEGRAM_TOKEN
    TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") 
    
    if not TOKEN:
        logger.error("❌ TELEGRAM_BOT_TOKEN niet gevonden in Environment Variables!")
        return

    # Bouw de applicatie
    app = ApplicationBuilder().token(TOKEN).build()

    # Handlers toevoegen
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('status', status))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_ai_message))
    app.add_error_handler(error_handler)

    # De asynchrone manier van opstarten om 'never awaited' warnings te voorkomen
    await app.initialize()
    await app.start()
    
    logger.info("🤖 SYNTHORA is live!")
    
    # Start polling handmatig
    await app.updater.start_polling(drop_pending_updates=True)

    # Houdt de loop levend op Render
    stop_event = asyncio.Event()
    await stop_event.wait()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot wordt afgesloten...")
        
