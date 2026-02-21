import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from openai import OpenAI
from dotenv import load_dotenv

# 1. Setup
load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_KEY = os.getenv("OPENAI_API_KEY")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

client = OpenAI(api_key=OPENAI_KEY)
logging.basicConfig(level=logging.INFO)

# 2. AI Chat Functie
async def ai_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Je bent Synthora, de AI Architect op Base. Je bent serieus, technisch en mysterieus."},
                {"role": "user", "content": update.message.text}
            ]
        )
        await update.message.reply_text(response.choices[0].message.content)
    except Exception as e:
        logging.error(f"Fout: {e}")
        await update.message.reply_text("Neurale interface onderbroken. Probeer het over een moment weer.")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🛡️ **Synthora Core Online.** Wachtend op instructies, Architect.")

# 3. De Motor (Aangepast voor Render stabiliteit)
if __name__ == '__main__':
    if not TOKEN:
        print("FOUT: Geen TELEGRAM_TOKEN gevonden!")
    else:
        app = ApplicationBuilder().token(TOKEN).build()
        
        app.add_handler(CommandHandler('start', start))
        app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), ai_chat))
        
        print("Synthora start op...")
        app.run_polling(drop_pending_updates=True)
        

