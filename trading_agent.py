import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# Logging aanzetten zodat Render ons vertelt wat er mis is
logging.basicConfig(level=logging.INFO)

TOKEN = os.environ.get("TELEGRAM_TOKEN")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Ik leef. Eindelijk.")

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Je zei: {update.message.text}")

if __name__ == '__main__':
    if not TOKEN:
        print("FOUT: Geen TELEGRAM_TOKEN gevonden in Render!")
    else:
        app = ApplicationBuilder().token(TOKEN).build()
        app.add_handler(CommandHandler('start', start))
        app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), echo))
        print("Bot start nu op...")
        app.run_polling()
        
    
        

