# --- 1. BOVENAAN: IMPORTS ---
import logging
import os
import asyncio
import threading
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel
from web3 import Web3
from eth_account import Account
import uvicorn
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# --- CONFIGURATIE ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Synthora")

BASE_RPC_URL = "https://mainnet.base.org"
w3 = Web3(Web3.HTTPProvider(BASE_RPC_URL))

# Keys ophalen uit Render Environment Variables
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
OWNER_ID = int(os.environ.get("OWNER_ID", 0))
session_key_hex = os.environ.get("ARCHITECT_SESSION_KEY")

if session_key_hex:
    architect_account = Account.from_key(session_key_hex)
else:
    logger.warning("Geen Session Key gevonden. /skyline zal geen balans tonen.")
    architect_account = None

# --- 2. DE BOT COMMANDO'S ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commando: /start"""
    if update.effective_user.id == OWNER_ID:
        await update.message.reply_text("🏗️ **De Architect is online.**\nDe Skyline van Base is stabiel. Gebruik /skyline voor een on-chain scan.")
    else:
        await update.message.reply_text("Toegang geweigerd.")

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commando: /status"""
    if update.effective_user.id == OWNER_ID:
        block = w3.eth.block_number
        await update.message.reply_text(f"📊 **Synthora Status Rapport**\n• Netwerk: Base Mainnet\n• Huidig Block: {block}\n• Status: Operationeel")

async def skyline_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commando: /skyline - De Architect analyseert de horizon"""
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("Onbevoegde toegang geweigerd.")
        return

    await update.message.reply_chat_action("typing")
    
    try:
        # 1. Netwerk data ophalen
        gas_price_gwei = w3.from_wei(w3.eth.gas_price, 'gwei')
        block_number = w3.eth.block_number
        
        # 2. Balans ophalen van je 'brandstof'
        balance_eth = 0
        if architect_account:
            balance_wei = w3.eth.get_balance(architect_account.address)
            balance_eth = w3.from_wei(balance_wei, 'ether')

        # 3. Rapport opstellen
        rapport = (
            "🏙️ **Synthora Skyline Report**\n"
            "───────────────────\n"
            f"🌐 **Netwerk:** Base Mainnet\n"
            f"📦 **Block:** `{block_number}`\n"
            f"⛽ **Gas Prijs:** `{gas_price_gwei:.4f} Gwei`\n"
            "───────────────────\n"
            f"💳 **Agent Wallet:** `{balance_eth:.5f} ETH`\n\n"
            "Status: *De skyline is helder. Sensoren op 100%.*"
        )
        
        await update.message.reply_text(rapport, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Skyline Scan fout: {e}")
        await update.message.reply_text("⚠️ De Skyline is momenteel gehuld in mist.")

# --- 3. DE BOT RUNNER (v22.6) ---

async def run_telegram_bot():
    if not TELEGRAM_TOKEN:
        logger.error("Geen TELEGRAM_BOT_TOKEN gevonden!")
        return
    
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    # Handlers registreren
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("skyline", skyline_command))
    
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    
    logger.info("[SYSTEM] Synthora Bot is actief en luistert.")
    while True:
        await asyncio.sleep(3600)

# --- 4. API ENDPOINTS ---

app = FastAPI(title="De Architect - Command Center")

@app.get("/")
async def health_check():
    return {"status": "online", "agent": "Synthora", "location": "Base Skyline"}

# --- 5. STARTUP ---

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(run_telegram_bot())

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
    
