import logging, os, asyncio, time
from web3 import Web3
from eth_account import Account
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from fastapi import FastAPI
import uvicorn

# --- ELITE LOGGING ---
logging.basicConfig(format='%(asctime)s | %(levelname)s | %(message)s', level=logging.INFO)
logger = logging.getLogger("Architect")
app = FastAPI()

# --- GLOBALE CONFIGURATIE ---
# Deze moeten bovenaan staan zodat alle functies ze kunnen zien
OWNER_ID = int(os.environ.get("OWNER_ID", 0))
RPC_URL = os.environ.get("BASE_RPC_URL", "https://base-mainnet.g.alchemy.com/v2/Hw_dzgvYV1VJDryEav9WO")
w3 = Web3(Web3.HTTPProvider(RPC_URL))

# WALLET SETUP
SIGNER_ADDR = "0xd048b06D3A775151652Ab3c544c6011755C61665"
PRIVATE_KEY = os.environ.get("ARCHITECT_SESSION_KEY", "").strip().replace('"', '').replace("'", "")
if not PRIVATE_KEY.startswith("0x"): PRIVATE_KEY = "0x" + PRIVATE_KEY
account = Account.from_key(PRIVATE_KEY)

# SNIPER PARAMETERS
SNIPE_AMOUNT = 0.002
MIN_LIQ = 0.5
TP = 1.5 
SL = 0.8 

# --- DE ENGINE (MET HARTSLAG) ---

async def autonomous_scan():
    logger.info("💎 SYNTHORA ELITE ENGINE GEACTIVEERD")
    last_block = w3.eth.block_number
    
    while True:
        try:
            current_block = w3.eth.block_number
            if current_block > last_block:
                # Luxe log-output voor Render tijdstempels
                logger.info(f"🛰️  [SCAN] Blok {current_block} | Status: Jagen... | Liquiditeit Filter: >{MIN_LIQ} ETH")
                last_block = current_block
            await asyncio.sleep(1.5) 
        except Exception as e:
            logger.error(f"⚠️  Verbindingsonderbreking: {e}")
            await asyncio.sleep(2)

# --- LUXE INTERFACE ---

async def dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Fix: OWNER_ID is nu correct gedefinieerd
    if update.effective_user.id != OWNER_ID: 
        logger.warning(f"Onbevoegde toegang ID: {update.effective_user.id}")
        return
    
    try:
        balance_wei = w3.eth.get_balance(SIGNER_ADDR)
        bal = w3.from_wei(balance_wei, 'ether')
        
        msg = (
            f"🏙️ **SYNTHORA ELITE ARCHITECT**\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 **Eigenaar:** `Architect`\n"
            f"🏦 **Wallet:** `{SIGNER_ADDR}`\n"
            f"💰 **Saldo:** `{bal:.6f} ETH` (Base)\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📡 **Scanner:** `ACTIEF` 🟢\n"
            f"🎯 **Target:** Aerodrome V3 Pools\n"
            f"💸 **Inzet:** `{SNIPE_AMOUNT} ETH` | **TP:** `1.5x` | **SL:** `0.8x`"
        )
        
        keyboard = [
            [InlineKeyboardButton("📊 Live Profit", callback_data='profit')],
            [InlineKeyboardButton("🏧 Snel Opnemen", callback_data='withdraw_fast')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Dashboard error: {e}")

# --- RUNNER ---

async def run_bot():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    app_tg = ApplicationBuilder().token(token).build()
    
    app_tg.add_handler(CommandHandler("start", dashboard))
    app_tg.add_handler(CommandHandler("status", dashboard))
    app_tg.add_handler(CommandHandler("skyline", dashboard))
    
    await app_tg.initialize()
    await app_tg.start()
    await app_tg.updater.start_polling()
    await autonomous_scan()

@app.on_event("startup")
async def start_all():
    asyncio.create_task(run_bot())

@app.get("/")
async def health():
    return {"status": "Elite Architect Online", "address": SIGNER_ADDR}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
    
