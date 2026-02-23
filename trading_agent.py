import logging
import os
import asyncio
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel
from web3 import Web3
from eth_account import Account
import uvicorn
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# --- 1. CONFIGURATIE ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Synthora")

BASE_RPC_URL = "https://mainnet.base.org"
w3 = Web3(Web3.HTTPProvider(BASE_RPC_URL))

# Haal keys op uit Environment Variables (Render Dashboard)
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
OWNER_ID = int(os.environ.get("OWNER_ID", 0)) 
OWNER_SECRET = os.environ.get("OWNER_SECRET_KEY", "geheim")

# --- 2. TELEGRAM COMMANDS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reageert op /start"""
    if update.effective_user.id == OWNER_ID:
        await update.message.reply_text("🏗️ **De Architect is online.**\nDe Skyline van Base is stabiel. Gebruik /status voor een rapport.")
    else:
        await update.message.reply_text("Toegang geweigerd. U bent niet geautoriseerd om Synthora aan te sturen.")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reageert op /status"""
    if update.effective_user.id == OWNER_ID:
        block = w3.eth.block_number
        await update.message.reply_text(f"📊 **Synthora Status**\nNetwerk: Base Mainnet\nLaatste Block: {block}\nStatus: Operationeel")

# --- 3. DE BOT RUNNER ---
async def run_telegram_bot():
    if not TELEGRAM_TOKEN:
        logger.error("Geen TELEGRAM_BOT_TOKEN gevonden!")
        return

    # Bouw de applicatie (versie 22.6 compatibel)
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    # Voeg de commando's toe
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status))
    
    await application.initialize()
    await application.start_polling()
    logger.info("Telegram Bot is gestart met Polling.")
    
    while True:
        await asyncio.sleep(3600)

# --- 4. FASTAPI (Voor Render Health Checks) ---
app = FastAPI(title="Synthora Command Center")

@app.get("/")
async def health_check():
    return {"status": "online", "agent": "Synthora", "network": "Base"}

# --- 5. DE OPSTART-MOTOR ---
@app.on_event("startup")
async def startup_event():
    # Start de bot in de achtergrond zonder de server te blokkeren
    asyncio.create_task(run_telegram_bot())

if __name__ == "__main__":
    # Render gebruikt poort 10000
    port = int(os.environ.get("PORT", 10000))
    logger.info(f"Start server op poort {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
    
