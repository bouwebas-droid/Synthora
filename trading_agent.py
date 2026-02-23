# --- 1. DE FUNDERING: IMPORTS ---
import logging
import os
import asyncio
import time
from fastapi import FastAPI
import uvicorn
from web3 import Web3
from eth_account import Account
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from langchain_openai import ChatOpenAI

# --- CONFIGURATIE ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Synthora")

BASE_RPC_URL = "https://mainnet.base.org"
w3 = Web3(Web3.HTTPProvider(BASE_RPC_URL))

# Adressen voor Trading op Base
AERODROME_ROUTER = "0xcF77a3Ba9A5CA399B7c97c74d54e5b1Beb874E43"
WETH_ADDRESS = "0x4200000000000000000000000000000000000006"
GAS_LIMIT_GWEI = 0.05  # Jouw Gas Guard limiet

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
OWNER_ID = int(os.environ.get("OWNER_ID", 0))

# Architect Wallet laden
private_key = os.environ.get("ARCHITECT_SESSION_KEY")
architect_account = Account.from_key(private_key) if private_key else None
llm = ChatOpenAI(model="gpt-4o", api_key=OPENAI_API_KEY)

# Minimale ABI voor Aerodrome Swap
ROUTER_ABI = [
    {"inputs":[{"name":"amountOutMin","type":"uint256"},{"name":"routes","type":"tuple[]","components":[{"name":"from","type":"address"},{"name":"to","type":"address"},{"name":"stable","type":"bool"},{"name":"factory","type":"address"}]},{"name":"to","type":"address"},{"name":"deadline","type":"uint256"}],"name":"swapExactETHForTokens","outputs":[{"name":"amounts","type":"uint256[]"}],"stateMutability":"payable","type":"function"}
]

# --- 2. DE TRADE ENGINE & SNIPER LOGICA ---

async def execute_trade(token_to_buy, amount_eth):
    """Voert een on-chain swap uit met Gas Guard."""
    current_gas = w3.from_wei(w3.eth.gas_price, 'gwei')
    if current_gas > GAS_LIMIT_GWEI:
        raise Exception(f"Gas te hoog: {current_gas:.4f} Gwei (Limiet: {GAS_LIMIT_GWEI})")

    amount_wei = w3.to_wei(amount_eth, 'ether')
    router = w3.eth.contract(address=AERODROME_ROUTER, abi=ROUTER_ABI)
    
    route = [{"from": WETH_ADDRESS, "to": w3.to_checksum_address(token_to_buy), "stable": False, "factory": "0x4200000000000000000000000000000000000001"}]
    
    nonce = w3.eth.get_transaction_count(architect_account.address)
    tx = router.functions.swapExactETHForTokens(
        0, 
        route,
        architect_account.address,
        int(time.time()) + 600
    ).build_transaction({
        'from': architect_account.address,
        'value': amount_wei,
        'gas': 250000,
        'gasPrice': w3.eth.gas_price,
        'nonce': nonce,
        'chainId': 8453
    })

    signed_tx = w3.eth.account.sign_transaction(tx, private_key)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
    return w3.to_hex(tx_hash)

async def sniper_loop(update, token_addr, amount):
    """Blijft scannen tot de gas-prijs gunstig is voor de snipe."""
    while True:
        try:
            current_gas = w3.from_wei(w3.eth.gas_price, 'gwei')
            if current_gas <= GAS_LIMIT_GWEI:
                tx_hash = await execute_trade(token_addr, amount)
                await update.message.reply_text(f"🔥 **TARGET SNIPED!**\nHash: `{tx_hash}`\n[Basescan](https://basescan.org/tx/{tx_hash})", parse_mode='Markdown')
                break
            await asyncio.sleep(5)  # Scan elke 5 seconden
        except Exception as e:
            logger.error(f"Sniper loop error: {e}")
            await asyncio.sleep(10)

# --- 3. COMMAND CENTER (SECRET COMMANDS) ---

async def snipe_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Secret Command: /snipe [token_adres] [bedrag_eth]"""
    if update.effective_user.id != OWNER_ID: return
    
    try:
        token_addr = context.args[0]
        amount = float(context.args[1])
        await update.message.reply_text(f"🎯 **Sniper Modus Actief.**\nDe Architect schaduwt `{token_addr[:10]}...` en slaat toe zodra gas ≤ {GAS_LIMIT_GWEI} Gwei.")
        asyncio.create_task(sniper_loop(update, token_addr, amount))
    except Exception as e:
        await update.message.reply_text(f"❌ **Sniper Setup Mislukt:** {str(e)}")

async def trade_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Directe executie: /trade [token_adres] [bedrag_eth]"""
    if update.effective_user.id != OWNER_ID: return
    try:
        tx_hash = await execute_trade(context.args[0], float(context.args[1]))
        await update.message.reply_text(f"✅ **Trade verzonden!**\nHash: `{tx_hash}`", parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"❌ **Trade afgebroken:** {str(e)}")

async def skyline_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """AI Status Rapportage"""
    if update.effective_user.id != OWNER_ID: return
    gas = w3.from_wei(w3.eth.gas_price, 'gwei')
    bal = w3.from_wei(w3.eth.get_balance(architect_account.address), 'ether')
    res = llm.invoke(f"Schrijf een vlijmscherp on-chain rapport. Gas: {gas:.4f}, Balans: {bal:.4f} ETH.")
    await update.message.reply_text(f"🏙️ **Skyline Status**\n\n{res.content}\n\n⛽ Gas: `{gas:.4f}` | 💳 Vault: `{bal:.4f} ETH`", parse_mode='Markdown')

# --- 4. DE RUNNER ---
async def run_bot():
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler("snipe", snipe_command))
    application.add_handler(CommandHandler("trade", trade_command))
    application.add_handler(CommandHandler("skyline", skyline_command))
    application.add_handler(CommandHandler("start", lambda u, c: u.message.reply_text("Architect Online.")))
    
    await application.initialize()
    await application.start()
    await application.updater.start_polling(drop_pending_updates=True)
    while True: await asyncio.sleep(3600)

app = FastAPI()
@app.on_event("startup")
async def startup(): asyncio.create_task(run_bot())

@app.get("/")
async def health(): return {"status": "active"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
