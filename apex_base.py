# -*- coding: utf-8 -*-
import logging, os, asyncio, time
from web3 import Web3, AsyncWeb3
from web3.providers import AsyncHTTPProvider
from eth_account import Account
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from fastapi import FastAPI
import uvicorn

# --- LOGGER ---
logging.basicConfig(format="%(asctime)s [SYSTEM] %(message)s", level=logging.INFO)
logger = logging.getLogger("Synthora")
app = FastAPI()

# --- CONFIG ---
TARGET_WALLET = "0xaF2C5d0063C236C95BEF05ecE7079f818EFBBF38"
AERODROME_FACTORY = "0x420DD381b31aEf6683db6B902084cB0FFECe40Da"
POOL_TOPIC = "0x2128d88d14c80cb081c1252a5acff7a264671bf199ce226b53788fb26065005e"

# --- WALLET & RPC ---
raw_key = os.environ.get("ARCHITECT_SESSION_KEY", "").strip().replace('"', "")
signer = Account.from_key(raw_key)
BOT_ADDRESS = signer.address

# Gebruik een publieke RPC als Alchemy blijft weigeren (Bad Request)
RPC_URL = os.environ.get("BASE_RPC_URL", "https://mainnet.base.org").strip().replace('"', "")
aw3 = AsyncWeb3(AsyncHTTPProvider(RPC_URL))

OWNER_ID = int(os.environ.get("OWNER_ID", 0))
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

# --- VEILIGHEIDS-CHECK ---
def is_valid_addr(addr):
    """Filtert 0x0 en andere troep eruit."""
    if not addr or addr == "0x" + "0" * 40: return False
    return Web3.is_address(addr)

# --- COMMANDS ---
async def cmd_rescue(u: Update, c: ContextTypes.DEFAULT_TYPE):
    """Stuurt ALLES van de bot naar het opgegeven adres."""
    if u.effective_user.id != OWNER_ID: return
    try:
        if not c.args:
            return await u.message.reply_text("❌ Gebruik: `/rescue <jouw_metamask_adres>`")
        
        dest = Web3.to_checksum_address(c.args[0])
        bal = await aw3.eth.get_balance(BOT_ADDRESS)
        gas_price = await aw3.eth.gas_price
        cost = gas_price * 21000
        amount = bal - cost

        if amount <= 0:
            return await u.message.reply_text(f"❌ Geen ETH op {BOT_ADDRESS}")

        tx = {'nonce': await aw3.eth.get_transaction_count(BOT_ADDRESS), 'to': dest, 'value': amount, 'gas': 21000, 'gasPrice': gas_price, 'chainId': 8453}
        signed = aw3.eth.account.sign_transaction(tx, raw_key)
        h = await aw3.eth.send_raw_transaction(signed.rawTransaction)
        await u.message.reply_text(f"✅ GELD ONDERWEG!\nCheck: https://basescan.org/tx/{h.hex()}")
    except Exception as e: await u.message.reply_text(f"🆘 Fout: {e}")

async def cmd_wallet(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if u.effective_user.id != OWNER_ID: return
    bal = Web3.from_wei(await aw3.eth.get_balance(BOT_ADDRESS), 'ether')
    await u.message.reply_text(f"💳 **Balans:** `{bal:.6f} ETH` op `{BOT_ADDRESS}`")

# --- SCANNER (STREEP DOOR DE FOUTEN) ---
async def scan_loop():
    logger.info(f"🛰️ Scanner actief op: {BOT_ADDRESS}")
    last_block = await aw3.eth.block_number
    while True:
        try:
            curr_block = await aw3.eth.block_number
            if curr_block > last_block:
                # We scannen slechts 1 blok tegelijk om Alchemy 400 errors te voorkomen
                logs = await aw3.eth.get_logs({"fromBlock": curr_block, "toBlock": curr_block, "address": AERODROME_FACTORY, "topics": [POOL_TOPIC]})
                for log in logs:
                    # Hier logica... we doen nu even niets anders dan stabiel blijven
                    pass
                last_block = curr_block
            await asyncio.sleep(1)
        except Exception as e:
            logger.error(f"⚠️ Scan skip: {e}")
            await asyncio.sleep(2)

# --- STARTUP ---
@app.on_event("startup")
async def startup():
    global tg_app
    tg_app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    tg_app.add_handler(CommandHandler("rescue", cmd_rescue))
    tg_app.add_handler(CommandHandler("wallet", cmd_wallet))
    tg_app.add_handler(CommandHandler("withdraw", cmd_rescue))
    await tg_app.initialize(); await tg_app.start(); await tg_app.updater.start_polling()
    asyncio.create_task(scan_loop())
    logger.info("🤜 Synthora V15 Live.")

@app.get("/")
async def health(): return {"wallet": BOT_ADDRESS}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
    
