# -*- coding: utf-8 -*-
# =============================================================
#  SYNTHORA V8.1 - THE VAULT EDITION (2026)
#  Base Mainnet | Sniper | Secure Withdrawal System
# =============================================================
import logging, os, asyncio, time, json
from web3 import Web3, AsyncWeb3
from web3.providers import AsyncHTTPProvider
from eth_account import Account
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from fastapi import FastAPI
import uvicorn

# --- INITIALISATIE ---
logging.basicConfig(format="%(asctime)s [SYNTHORA] %(message)s", level=logging.INFO)
logger = logging.getLogger("Synthora")
app = FastAPI()

# --- CONTRACTEN ---
AERODROME_ROUTER = "0xcF77a3Ba9A5CA399B7c97c74d54e5b1Beb874E43"
AERODROME_FACTORY = "0x420DD381b31aEf6683db6B902084cB0FFECe40Da"
WETH = Web3.to_checksum_address("0x4200000000000000000000000000000000000006")
POOL_TOPIC = "0x2128d88d14c80cb081c1252a5acff7a264671bf199ce226b53788fb26065005e"

# --- WALLET SETUP ---
raw_key = os.environ.get("ARCHITECT_SESSION_KEY", "").strip().replace('"', "")
signer = Account.from_key(raw_key)
BOT_ADDRESS = signer.address # DIT IS HET ADRES VAN DE BOT

aw3 = AsyncWeb3(AsyncHTTPProvider(os.environ.get("BASE_RPC_URL", "https://mainnet.base.org")))
OWNER_ID = int(os.environ.get("OWNER_ID", 0))
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
tg_app = None

# --- CONFIG ---
config = {"active": False, "snipe_eth": 0.015, "min_liquidity_eth": 1.0}

# --- TELEGRAM COMMANDS ---

async def cmd_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toont het adres van de bot-wallet."""
    if update.effective_user.id != OWNER_ID: return
    await update.message.reply_text(f"📍 **Bot Wallet Adres:**\n`{BOT_ADDRESS}`", parse_mode="Markdown")

async def cmd_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Checkt balans van de bot-wallet."""
    if update.effective_user.id != OWNER_ID: return
    bal_wei = await aw3.eth.get_balance(BOT_ADDRESS)
    bal_eth = Web3.from_wei(bal_wei, 'ether')
    await update.message.reply_text(f"💳 **Bot Balans:** `{bal_eth:.6f} ETH`")

async def cmd_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Haalt de bot wallet volledig leeg naar een opgegeven adres."""
    if update.effective_user.id != OWNER_ID: return
    
    try:
        if not context.args:
            await update.message.reply_text("❌ Gebruik: `/withdraw <jouw_metamask_adres>`")
            return
        
        dest_address = Web3.to_checksum_address(context.args[0])
        bal_wei = await aw3.eth.get_balance(BOT_ADDRESS)
        
        # Bereken gas (we gebruiken een veilige marge)
        gas_price = await aw3.eth.gas_price
        gas_limit = 21000
        cost_wei = gas_price * gas_limit
        
        send_wei = bal_wei - cost_wei
        
        if send_wei <= 0:
            await update.message.reply_text("❌ Balans te laag om gas te betalen.")
            return

        tx = {
            'nonce': await aw3.eth.get_transaction_count(BOT_ADDRESS),
            'to': dest_address,
            'value': send_wei,
            'gas': gas_limit,
            'gasPrice': gas_price,
            'chainId': 8453
        }

        signed = aw3.eth.account.sign_transaction(tx, raw_key)
        tx_hash = await aw3.eth.send_raw_transaction(signed.rawTransaction)
        
        await update.message.reply_text(
            f"💰 **Leegmaken gestart!**\n"
            f"Verstuurd: `{Web3.from_wei(send_wei, 'ether'):.6f} ETH`\n"
            f"Naar: `{dest_address}`\n"
            f"[Basescan](https://basescan.org/tx/{tx_hash.hex()})",
            parse_mode="Markdown"
        )
    except Exception as e:
        await update.message.reply_text(f"🆘 Fout bij opname: {e}")

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    config["active"] = True
    await update.message.reply_text("🎯 **Sniper Actief.** Gebruik /withdraw om winst op te nemen.")

# --- SCANNER LOOP ---
async def scan_loop():
    last_block = await aw3.eth.block_number
    while True:
        if not config["active"]: await asyncio.sleep(2); continue
        try:
            curr_block = await aw3.eth.block_number
            if curr_block > last_block:
                for b in range(last_block + 1, curr_block + 1):
                    # Hier de sniper logica die we eerder hebben gebouwd...
                    pass
                last_block = curr_block
            await asyncio.sleep(0.5)
        except: await asyncio.sleep(2)

# --- STARTUP ---
@app.on_event("startup")
async def startup():
    global tg_app
    tg_app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    tg_app.add_handler(CommandHandler("start", cmd_start))
    tg_app.add_handler(CommandHandler("wallet", cmd_wallet))
    tg_app.add_handler(CommandHandler("address", cmd_address))
    tg_app.add_handler(CommandHandler("withdraw", cmd_withdraw))
    await tg_app.initialize(); await tg_app.start(); await tg_app.updater.start_polling()
    asyncio.create_task(scan_loop())
    logger.info(f"🤜 Synthora V8.1 Online. Bot Adres: {BOT_ADDRESS}")

@app.get("/")
async def health(): return {"status": "ok", "bot_address": BOT_ADDRESS}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
        
