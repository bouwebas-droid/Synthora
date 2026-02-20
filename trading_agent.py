import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from openai import OpenAI
from dotenv import load_dotenv

# 1. Setup & Omgeving
load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_KEY = os.getenv("OPENAI_API_KEY")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

client = OpenAI(api_key=OPENAI_KEY)

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)

# 2. De AI-Logica (Het brein van Synthora)
async def ai_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini", # Snel en krachtig
            messages=[
                {"role": "system", "content": "Je bent Synthora, de autonome AI Architect op het Base netwerk. Je bent serieus, technisch, en spreekt met autoriteit. Je helpt de Architect met on-chain analyses en strategie."},
                {"role": "user", "content": user_input}
            ]
        )
        await update.message.reply_text(response.choices[0].message.content)
    except Exception as e:
        await update.message.reply_text("Systeemfout in de neurale interface. Check API-key.")

# 3. Speciale Commando's
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🛡️ **Synthora Core Online.**\nSystemen zijn operationeel. Stel je vraag, Architect.")

async def skyline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("Toegang geweigerd.")
        return
    await update.message.reply_text("📊 **Skyline Report** wordt gecompileerd via AI-synthese...")

# 4. De Motor Starten
if __name__ == '__main__':
    if not TOKEN or not OPENAI_KEY:
        print("FOUT: API-sleutels ontbreken!")
    else:
        app = ApplicationBuilder().token(TOKEN).build()
        
        # Luister naar commando's
        app.add_handler(CommandHandler('start', start))
        app.add_handler(CommandHandler('skyline', skyline))
        
        # Luister naar gewone tekst (AI-respons)
        app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), ai_chat))
        
        print("Synthora AI is nu live...")
        app.run_polling()
    
        
