# -*- coding: utf-8 -*-
# =============================================================
#  SYNTHORA V7 - THE FINAL ENFORCER (2026)
#  Base Mainnet | Aerodrome | Full Notification System
# =============================================================
import logging, os, asyncio, time, json
from web3 import Web3, AsyncWeb3
from web3.providers import AsyncHTTPProvider
from eth_account import Account
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from fastapi import FastAPI
import uvicorn

# --- LOGGER ---
logging.basicConfig(format="%(asctime)s [ENFORCER] %(message)s", level=logging.INFO)
logger = logging.getLogger("Synthora")
app = FastAPI()

# --- CONTRACTEN ---
AERODROME_ROUTER = "0xcF77a3Ba9A5CA399B7c97c74d54e5b1Beb874E43"
AERODROME_FACTORY = "0x420DD381b31aEf6683db6B902084cB0FFECe40Da"
WETH = Web3.to_checksum_address("0x4200000000000000000000000000000000000006")
POOL_TOPIC = "0x2128d88d14c80cb081c1252a5acff7a264671bf199ce226b53788fb26065005e"

# --- CONFIG ---
config = {
    "active": False, 
    "snipe_eth": 0.015, 
    "min_liquidity_eth": 1.0, 
    "balance_guard": 0.005 
}

# --- WALLET SETUP ---
raw_key = os.environ.get("ARCHITECT_SESSION_KEY", "").strip().replace('"', "")
signer = Account.from_key(raw_key)
BOT_ADDRESS = signer.address

RPC_URL = os.environ.get("BASE_RPC_URL", "https://mainnet.base.org")
aw3 = AsyncWeb3(AsyncHTTPProvider(RPC_URL))

OWNER_ID = int(os.environ.get("OWNER_ID", 0))
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
tg_app = None

# --- NOTIFICATIE FUNCTIE ---
async def notify_architect(msg):
    """Stuurt direct een bericht naar de Architect in Telegram."""
    if tg_app and OWNER_ID:
        try:
            await tg_app.bot.send_message(chat_id=OWNER_ID, text=msg, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Telegram melding mislukt: {e}")

# --- EXECUTE BUY ---
async def execute_buy(token_address, liq_found):
    try:
        # 1. Check Balans
        bal_wei = await aw3.eth.get_balance(BOT_ADDRESS)
        bal_eth = float(Web3.from_wei(bal_wei, 'ether'))
        
        if bal_eth < (config["snipe_eth"] + config["balance_guard"]):
            await notify_architect(f"⚠️ **SNIPE GEMIST!**\nBalans is te laag: `{bal_eth:.4f} ETH`.\nStuur meer munitie naar `{BOT_ADDRESS}`.")
            return

        # 2. Bouw de Transactie
        router = aw3.eth.contract(address=AERODROME_ROUTER, abi=[{"inputs":[{"name":"amountOutMin","type":"uint256"},{"name":"routes","type":"tuple[]","components":[{"name":"from","type":"address"},{"name":"to","type":"address"},{"name":"stable","type":"bool"},{"name":"factory","type":"address"}]},{"name":"to","type":"address"},{"name":"deadline","type":"uint256"}],"name":"swapExactETHForTokens","outputs":[{"name":"amounts","type":"uint256[]"}],"stateMutability":"payable","type":"function"}])
        routes = [{"from": WETH, "to": token_address, "stable": False, "factory": AERODROME_FACTORY}]
        
        nonce = await aw3.eth.get_transaction_count(BOT_ADDRESS)
        tx = await router.functions.swapExactETHForTokens(0, routes, BOT_ADDRESS, int(time.time()) + 60).build_transaction({
            'from': BOT_ADDRESS, 'value': Web3.to_wei(config["snipe_eth"], 'ether'),
            'nonce': nonce, 'gas': 350000, 'chainId': 8453,
            'maxFeePerGas': await aw3.eth.gas_price, 'maxPriorityFeePerGas': Web3.to_wei(1, 'gwei')
        })

        # 3. Onderteken en Verstuur
        signed = aw3.eth.account.sign_transaction(tx, raw_key)
        tx_hash = await aw3.eth.send_raw_transaction(signed.rawTransaction)
        
        # 4. Meld de poging direct
        await notify_architect(f"⚡ **SNIPE INVOERING...**\nTransactie verstuurd voor `{token_address[:10]}`.\n[Bekijk op Basescan](https://basescan.org/tx/{tx_hash.hex()})")

        # 5. Wacht op bevestiging
        receipt = await aw3.eth.wait_for_transaction_receipt(tx_hash)
        if receipt.status == 1:
            await notify_architect(f"✅ **SNIPE SUCCESVOL!**\nToken: `{token_address}`\nLiquiditeit: `{liq_found:.2f} ETH`\nInzet: `{config['snipe_eth']} ETH`")
        else:
            await notify_architect(f"❌ **SNIPE MISLUKT (Chain Error)**\nTransactie op blockchain geweigerd.")

    except Exception as e:
        logger.error(f"Fout tijdens snipe: {e}")
        await notify_architect(f"🆘 **CRITICAL ERROR**\nFoutmelding: `{str(e)[:100]}`")

# --- SCANNER ---
async def scan_loop():
    logger.info(f"🛰️ Scanner op jacht vanuit: {BOT_ADDRESS}")
    last_block = await aw3.eth.block_number
    
    while True:
        if not config["active"]:
            await asyncio.sleep(2); continue
        try:
            curr_block = await aw3.eth.block_number
            if curr_block > last_block:
                for b in range(last_block + 1, curr_block + 1):
                    logs = await aw3.eth.get_logs({"fromBlock": b, "toBlock": b, "address": AERODROME_FACTORY, "topics": [POOL_TOPIC]})
                    for log in logs:
                        # Extract data
                        pool_addr = Web3.to_checksum_address("0x" + log["data"][-40:])
                        t1 = Web3.to_checksum_address("0x" + log["topics"][1][-40:])
                        t2 = Web3.to_checksum_address("0x" + log["topics"][2][-40:])
                        token_snipe = t2 if t1 == WETH else t1
                        
                        # Liquiditeit check
                        pool_liq_wei = await aw3.eth.get_balance(pool_addr)
                        pool_liq_eth = float(Web3.from_wei(pool_liq_wei, 'ether'))
                        
                        logger.info(f"💎 Pool gevonden: {token_snipe[:10]} | Liq: {pool_liq_eth:.2f} ETH")
                        
                        if pool_liq_eth >= config["min_liquidity_eth"]:
                            asyncio.create_task(execute_buy(token_snipe, pool_liq_eth))
                last_block = curr_block
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.error(f"Scan glitch: {e}"); await asyncio.sleep(2)

# --- TELEGRAM COMMANDS ---
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    config["active"] = True
    await update.message.reply_text("🎯 **HUNTING MODE: AAN.** Je krijgt direct bericht bij een snipe.")

async def cmd_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    bal_wei = await aw3.eth.get_balance(BOT_ADDRESS)
    bal_eth = Web3.from_wei(bal_wei, 'ether')
    await update.message.reply_text(f"💳 **Balans:** `{bal_eth:.4f} ETH` op `{BOT_ADDRESS}`")

# --- STARTUP ---
@app.on_event("startup")
async def startup():
    global tg_app
    tg_app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    tg_app.add_handler(CommandHandler("start", cmd_start))
    tg_app.add_handler(CommandHandler("wallet", cmd_wallet))
    await tg_app.initialize(); await tg_app.start(); await tg_app.updater.start_polling()
    asyncio.create_task(scan_loop())
    logger.info(f"🤜 Synthora V7 is online. Target: {BOT_ADDRESS}")

@app.get("/")
async def health(): return {"status": "ok", "hunting": config["active"]}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
        
