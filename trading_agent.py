# --- 1. DE FUNDERING: IMPORTS ---
import logging
import os
import asyncio
from fastapi import FastAPI
import uvicorn
from web3 import Web3
from eth_account import Account
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from langchain_openai import ChatOpenAI

# --- CONFIGURATIE & BEVEILIGING ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Synthora")

BASE_RPC_URL = "https://mainnet.base.org"
w3 = Web3(Web3.HTTPProvider(BASE_RPC_URL))

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
OWNER_ID = int(os.environ.get("OWNER_ID", 0))

# Jouw apart beveiligde wallet laden
private_key = os.environ.get("ARCHITECT_SESSION_KEY")
if private_key:
    architect_account = Account.from_key(private_key)
    logger.info(f"🏗️ Architect geladen op adres: {architect_account.address}")
else:
    architect_account = None
    logger.error("❌ GEEN ARCHITECT_SESSION_KEY GEVONDEN!")

# AI Hersenen initialiseren
llm = ChatOpenAI(model="gpt-4o", api_key=OPENAI_API_KEY)

# --- 2. DE ARCHITECT LOGICA ---



async def generate_skyline_report():
    """Genereert een on-chain analyse van de Skyline."""
    gas_price = w3.from_wei(w3.eth.gas_price, 'gwei')
    block = w3.eth.block_number
    balance = w3.from_wei(w3.eth.get_balance(architect_account.address), 'ether') if architect_account else 0
    
    # AI-interpretatie van de status
    prompt = f"Je bent de Synthora Architect. Status: Block {block}, Gas {gas_price:.2f} Gwei, Wallet {balance:.4f} ETH. Schrijf een kort, krachtig wekelijks rapport over de skyline van Base."
    response = llm.invoke(prompt)
    return response.content

# --- 3. SECRET COMMANDS (OWNER ONLY) ---

async def skyline_report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Secret Command: /skyline_report"""
    if update.effective_user.id != OWNER_ID: return
    
    await update.message.reply_text("📊 **Secret Command geactiveerd: Skyline Report genereren...**")
    report = await generate_skyline_report()
    await update.message.reply_text(f"📝 **WEKELIJKS SKYLINE RAPPORT**\n\n{report}", parse_mode='Markdown')

async def vault_check_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Secret Command: /vault - Directe wallet inspectie"""
    if update.effective_user.id != OWNER_ID: return
    
    bal = w3.from_wei(w3.eth.get_balance(architect_account.address), 'ether') if architect_account else 0
    await update.message.reply_text(f"🔐 **Vault Status**\nAdres: `{architect_account.address}`\nBalans: `{bal:.5f} ETH`", parse_mode='Markdown')

# --- 4. DE RUNNER ---

async def run_telegram_bot():
    if not TELEGRAM_TOKEN: return
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    # Publieke commando's
    application.add_handler(CommandHandler("start", lambda u, c: u.message.reply_text("Synthora Architect Online.")))
    
    # Secret Commands (Alleen zichtbaar/bruikbaar voor jou)
    application.add_handler(CommandHandler("skyline_report", skyline_report_command))
    application.add_handler(CommandHandler("vault", vault_check_command))
    
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    logger.info("🚀 De Architect luistert...")
    while True: await asyncio.sleep(3600)

app = FastAPI()
@app.get("/")
async def health(): return {"status": "live", "agent": "Synthora"}

@app.on_event("startup")
async def startup():
    asyncio.create_task(run_telegram_bot())

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
    
