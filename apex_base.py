import logging, os, asyncio, time, httpx
from web3 import Web3
from eth_account import Account
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler
from fastapi import FastAPI
import uvicorn

# --- 1. LOGGING EN SETUP ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger("Synthora")
app = FastAPI()

# --- 2. CONFIGURATIE ---
# Gebruik de Alchemy URL uit je dashboard
RPC_URL = os.environ.get("BASE_RPC_URL", "https://base-mainnet.g.alchemy.com/v2/Hw_dzgvYV1VJDryEav9WO")
w3 = Web3(Web3.HTTPProvider(RPC_URL))

# Signer laden vanaf de Private Key in Render
raw_key = os.environ.get("ARCHITECT_SESSION_KEY", "").strip().replace('"', '').replace("'", "")
if not raw_key.startswith("0x"): raw_key = "0x" + raw_key
signer = Account.from_key(raw_key)

OWNER_ID = int(os.environ.get("OWNER_ID", 0))
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

# Belangrijke adressen voor Base
AERODROME_ROUTER = "0xcF77a3Ba9A5CA399B7c97c74d54e5b1Beb874E43"
WETH = "0x4200000000000000000000000000000000000006"

# --- 3. CORE FUNCTIES ---

async def get_balance(address):
    balance = w3.eth.get_balance(address)
    return w3.from_wei(balance, 'ether')

# --- 4. TELEGRAM COMMANDS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    
    bal = await get_balance(signer.address)
    msg = (
        f"🤜 **Synthora V16 Live**\n\n"
        f"🛰️ **Signer:** `{signer.address}`\n"
        f"💰 **Saldo:** `{bal:.6f} ETH` (Base)\n\n"
        f"Gebruik `/skyline` voor een rapport of `/withdraw [adres] [bedrag]` om ETH te verplaatsen."
    )
    await update.message.reply_text(msg, parse_mode='Markdown')

async def skyline_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    bal = await get_balance(signer.address)
    await update.message.reply_text(f"🏙️ **Skyline Report**\n\nAdres: `{signer.address}`\nSaldo: `{bal:.6f} ETH`", parse_mode='Markdown')

async def withdraw_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """De fix voor de 'SignedTransaction' object has no attribute 'rawTransaction'"""
    if update.effective_user.id != OWNER_ID: return
    
    if len(context.args) < 2:
        await update.message.reply_text("❌ Gebruik: `/withdraw [adres] [hoeveelheid]`")
        return

    msg = await update.message.reply_text("🏧 **Opname initialiseren...**")
    try:
        to_address = w3.to_checksum_address(context.args[0])
        amount = float(context.args[1].replace(',', '.'))
        value_wei = w3.to_wei(amount, 'ether')

        gas_price = w3.eth.gas_price
        nonce = w3.eth.get_transaction_count(signer.address)

        tx = {
            'nonce': nonce,
            'to': to_address,
            'value': value_wei,
            'gas': 21000,
            'gasPrice': int(gas_price * 1.2),
            'chainId': 8453
        }

        # Ondertekenen
        signed_tx = w3.eth.account.sign_transaction(tx, signer.key)

        # DE FIX: Checken op rawTransaction of raw_transaction
        raw_data = getattr(signed_tx, 'rawTransaction', getattr(signed_tx, 'raw_transaction', None))
        
        if raw_data is None:
            raise Exception("Interne fout: kon geen transactie data genereren.")

        # Verzenden naar het netwerk
        tx_hash = w3.eth.send_raw_transaction(raw_data)
        
        await msg.edit_text(f"🚀 **Verzonden naar Base!**\n\nDe ETH is onderweg.\nHash: `0x{tx_hash.hex()}`")
    except Exception as e:
        logger.error(f"Withdraw Error: {e}")
        await msg.edit_text(f"⚠️ **Fout:** `{str(e)}`")

# --- 5. RUNNER EN SCHEDULER ---

async def run_bot():
    app_tg = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    # Handlers
    app_tg.add_handler(CommandHandler("start", start))
    app_tg.add_handler(CommandHandler("skyline", skyline_report))
    app_tg.add_handler(CommandHandler("withdraw", withdraw_command))
    
    logger.info("🤜 Synthora Bot Gestart")
    await app_tg.initialize()
    await app_tg.start()
    await app_tg.updater.start_polling()
    
    # Scanner simulatie (begint altijd bij latest om 400 errors te voorkomen)
    while True:
        try:
            current_block = w3.eth.block_number
            # logger.info(f"🔎 Scanning block: {current_block}")
            await asyncio.sleep(12) # Wacht op volgend Base blok
        except Exception as e:
            logger.error(f"Scanner error: {e}")
            await asyncio.sleep(5)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(run_bot())

@app.get("/")
async def health():
    return {"status": "Synthora V16 Online", "signer": signer.address}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
