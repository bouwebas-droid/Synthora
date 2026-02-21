import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from openai import OpenAI
from dotenv import load_dotenv

# Setup
load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_KEY = os.getenv("OPENAI_API_KEY")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

client = OpenAI(api_key=OPENAI_KEY)
logging.basicConfig(level=logging.INFO)

# AI Functie
async def ai_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Je bent Synthora, de AI Architect op Base. Je bent technisch en spreekt met autoriteit."},
                {"role": "user", "content": update.message.text}
            ]
        )
        await update.message.reply_text(response.choices[0].message.content)
    except Exception as e:
        print(f"AI Error: {e}")
        await update.message.reply_text("Systeem tijdelijk offline. Herstarten...")

# Secret Command: Skyline Report
async def skyline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("Toegang geweigerd. Protocol gereserveerd voor de Architect.")
        return
    await update.message.reply_text("📊 **Generating Weekly Skyline Report for Chillzilla...**") #

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🛡️ **Synthora Core Online.** Wachtend op instructies.")

if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('skyline', skyline)) # Geheime opdracht
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), ai_chat))
    
    print("Synthora is actief...")
    app.run_polling(drop_pending_updates=True)
    


