# -*- coding: utf-8 -*-
import logging, os, asyncio, time, json, aiohttp, io
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime
from web3 import Web3, AsyncWeb3
from web3.providers import AsyncHTTPProvider
from eth_account import Account
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from fastapi import FastAPI
import uvicorn

# --- LOGGER & CONFIG ---
logging.basicConfig(format="%(asctime)s [SYNTHORA] %(message)s", level=logging.INFO)
logger = logging.getLogger("Synthora")
app = FastAPI()

AERODROME_ROUTER = "0xcF77a3Ba9A5CA399B7c97c74d54e5b1Beb874E43"
AERODROME_FACTORY = "0x420DD381b31aEf6683db6B902084cB0FFECe40Da"
WETH = Web3.to_checksum_address("0x4200000000000000000000000000000000000006")
POOL_TOPIC = "0x2128d88d14c80cb081c1252a5acff7a264671bf199ce226b53788fb26065005e"
MAX_UINT256 = 2**256 - 1

STATE_FILE = "synthora_v5_state.json"
config = {
    "active": False, "snipe_eth": 0.015, "max_positions": 10,
    "take_profit_pct": 45.0, "hard_stop_pct": 20.0,
    "min_liquidity_eth": 1.0, "gas_multiplier": 1.25, "balance_guard": 0.005
}
positions, blacklist = {}, set()
stats = {"trades": 0, "wins": 0, "losses": 0, "total_pnl": 0.0, "pnl_history": [], "started": time.time()}

raw_key = os.environ.get("ARCHITECT_SESSION_KEY", "").strip().replace('"', "")
signer = Account.from_key(raw_key)
aw3 = AsyncWeb3(AsyncHTTPProvider(os.environ.get("BASE_RPC_URL", "https://mainnet.base.org")))
OWNER_ID = int(os.environ.get("OWNER_ID", 0))
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

# --- UTILS ---
def save_state():
    try:
        data = {"positions": positions, "stats": stats, "config": config, "blacklist": list(blacklist)}
        with open(STATE_FILE, "w") as f: json.dump(data, f, indent=4)
    except: pass

def load_state():
    global positions, stats, config, blacklist
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                d = json.load(f)
                positions.update(d.get("positions", {}))
                stats.update(d.get("stats", {}))
                config.update(d.get("config", {}))
                for item in d.get("blacklist", []): blacklist.add(item)
        except: pass

async def notify(msg):
    if OWNER_ID:
        try: await tg_app.bot.send_message(chat_id=OWNER_ID, text=msg, parse_mode="Markdown")
        except: pass

# --- TRADING ACTIONS ---
async def execute_approve(token_address):
    try:
        token_contract = aw3.eth.contract(address=token_address, abi=json.loads('[{"inputs":[{"name":"spender","type":"address"},{"name":"amount","type":"uint256"}],"name":"approve","outputs":[{"name":"","type":"bool"}],"stateMutability":"nonpayable","type":"function"}]'))
        nonce = await aw3.eth.get_transaction_count(signer.address)
        tx = await token_contract.functions.approve(AERODROME_ROUTER, MAX_UINT256).build_transaction({
            'from': signer.address, 'nonce': nonce, 'gas': 100000, 'chainId': 8453,
            'maxFeePerGas': await aw3.eth.gas_price, 'maxPriorityFeePerGas': Web3.to_wei(1, 'gwei')
        })
        signed = aw3.eth.account.sign_transaction(tx, raw_key)
        await aw3.eth.send_raw_transaction(signed.rawTransaction)
        logger.info(f"🔓 Approved: {token_address}")
    except Exception as e: logger.error(f"Approve error: {e}")

async def execute_buy(token_address):
    token_address = Web3.to_checksum_address(token_address)
    if token_address in positions or token_address in blacklist: return
    
    router = aw3.eth.contract(address=AERODROME_ROUTER, abi=json.loads('[{"inputs":[{"name":"amountOutMin","type":"uint256"},{"name":"routes","type":"tuple[]","components":[{"name":"from","type":"address"},{"name":"to","type":"address"},{"name":"stable","type":"bool"},{"name":"factory","type":"address"}]},{"name":"to","type":"address"},{"name":"deadline","type":"uint256"}],"name":"swapExactETHForTokens","outputs":[{"name":"amounts","type":"uint256[]"}],"stateMutability":"payable","type":"function"}]'))
    routes = [{"from": WETH, "to": token_address, "stable": False, "factory": AERODROME_FACTORY}]
    
    try:
        nonce = await aw3.eth.get_transaction_count(signer.address)
        tx = await router.functions.swapExactETHForTokens(0, routes, signer.address, int(time.time()) + 60).build_transaction({
            'from': signer.address, 'value': Web3.to_wei(config["snipe_eth"], 'ether'),
            'nonce': nonce, 'gas': 350000, 'chainId': 8453,
            'maxFeePerGas': await aw3.eth.gas_price, 'maxPriorityFeePerGas': Web3.to_wei(1, 'gwei')
        })
        signed = aw3.eth.account.sign_transaction(tx, raw_key)
        tx_hash = await aw3.eth.send_raw_transaction(signed.rawTransaction)
        
        await aw3.eth.wait_for_transaction_receipt(tx_hash)
        positions[token_address] = {"entry_eth": config["snipe_eth"], "time": time.time()}
        asyncio.create_task(execute_approve(token_address))
        await notify(f"🚀 **SNIPE!** Gekocht: `{token_address[:12]}`")
        save_state()
    except Exception as e: logger.error(f"Buy error: {e}")

# --- SCANNER (WATERDICHT) ---
async def scan_loop():
    logger.info("📡 Scanner op de uitkijk...")
    try:
        last_block = await aw3.eth.block_number
    except:
        last_block = 0

    while True:
        if not config["active"]:
            await asyncio.sleep(2)
            continue
            
        try:
            curr_block = await aw3.eth.block_number
            if curr_block > last_block:
                for b in range(last_block + 1, curr_block + 1):
                    #logger.info(f"🔍 Scan blok {b}") # Haal weg voor minder ruis
                    logs = await aw3.eth.get_logs({
                        "fromBlock": b, "toBlock": b, 
                        "address": AERODROME_FACTORY, 
                        "topics": [POOL_TOPIC]
                    })
                    for log in logs:
                        t0 = Web3.to_checksum_address("0x" + log["topics"][1][-40:])
                        t1 = Web3.to_checksum_address("0x" + log["topics"][2][-40:])
                        token = t1 if t0 == WETH else t0
                        if len(positions) < config["max_positions"]:
                            asyncio.create_task(execute_buy(token))
                last_block = curr_block
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.error(f"Scanner glitch: {e}")
            await asyncio.sleep(2)

# --- TELEGRAM ---
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    config["active"] = True
    save_state()
    await update.message.reply_text("🎯 **HUNTING MODE: ON.** Ik scan nu de blokken.")

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    msg = f"📊 **Status:** `{'HUNTING' if config['active'] else 'STANDBY'}`\nSnipe: `{config['snipe_eth']} ETH`"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def cmd_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    bal = await aw3.eth.get_balance(signer.address)
    await update.message.reply_text(f"💳 Balans: `{Web3.from_wei(bal, 'ether'):.4f} ETH`")

# --- STARTUP ---
@app.on_event("startup")
async def startup():
    global tg_app
    load_state()
    tg_app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    tg_app.add_handler(CommandHandler("start", cmd_start))
    tg_app.add_handler(CommandHandler("status", cmd_status))
    tg_app.add_handler(CommandHandler("wallet", cmd_wallet))
    
    await tg_app.initialize()
    await tg_app.start()
    await tg_app.updater.start_polling()
    
    asyncio.create_task(scan_loop())
    logger.info("🤜 Synthora V5.1 is online.")

@app.get("/")
async def health(): return {"status": "ok"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
                    
