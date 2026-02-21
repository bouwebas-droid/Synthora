import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from openai import OpenAI

# 1. Logging instellen om te zien wat er gebeurt
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# 2. Variabelen direct uit Render halen
TOKEN = os.environ.get("TELEGRAM_TOKEN")
OPENAI_KEY = os.environ.get("OPENAI_API_KEY")

client = OpenAI(api_key=OPENAI_KEY)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Start commando ontvangen!")
    await update.message.reply_text("🛡️ **Synthora Core Online.** De verbinding is eindelijk stabiel, Architect.")

async def ai_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Je bent Synthora, de AI Architect op Base. Serieus en technisch."},
                {"role": "user", "content": update.message.text}
            ]
        )
        await update.message.reply_text(response.choices[0].message.content)
    except Exception as e:
        logger.error(f"Fout: {e}")

if __name__ == '__main__':
    if not TOKEN:
        logger.error("KRITISCH: TELEGRAM_TOKEN niet gevonden!")
    else:
        app = ApplicationBuilder().token(TOKEN).build()
        app.add_handler(CommandHandler('start', start))
        app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), ai_chat))
        
        logger.info("Synthora luistert...")
        app.run_polling(drop_pending_updates=True)
        
    
        

