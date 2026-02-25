# -*- coding: utf-8 -*-
# =============================================================
#  SYNTHORA V8.4 - THE ARCHITECT'S FINAL CHOICE (2026)
#  Base Mainnet | Sniper | Full Automation | Withdraw Enabled
# =============================================================
import logging, os, asyncio, time, json
from web3 import Web3, AsyncWeb3
from web3.providers import AsyncHTTPProvider
from eth_account import Account
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from fastapi import FastAPI
import uvicorn

# --- LOGGING & APP ---
logging.basicConfig(format="%(asctime)s [SYSTEM] %(message)s", level=logging.INFO)
logger = logging.getLogger("Synthora")
app = FastAPI()

# --- CONSTANTEN ---
AERODROME_ROUTER = "0xcF77a3Ba9A5CA399B7c97c74d54e5b1Beb874E43"
AERODROME_FACTORY = "0x420DD381b31aEf6683db6B902084cB0FFECe40Da"
WETH = Web3.to_checksum_address("0x4200000000000000000000000000000000000006")
POOL_TOPIC = "0x2128d88d14c80cb081c1252a5acff7a264671bf199ce226b53788fb26065005e"
TARGET_WALLET = "0xaf2c5d0063c236c95bef05ece7079f818efbbf38"

# --- WALLET VALIDATIE ---
raw_key = os.environ.get("ARCHITECT_SESSION_KEY", "").strip().replace('"', "")
signer = Account.from_key(raw_key)
BOT_ADDRESS = signer.address

if BOT_ADDRESS.lower() != TARGET_WALLET.lower():
    logger.error(f"⚠️ WAARSCHUWING: Bot draait op {BOT_ADDRESS} in plaats van {TARGET_WALLET}")
else:
    logger.info(f"🎯 CORRECTE WALLET GEKOPPELD: {BOT_ADDRESS}")

# --- VERBINDING ---
aw3 = AsyncWeb3(AsyncHTTPProvider(os.environ.get("BASE_RPC_URL", "https://mainnet.base.org")))
OWNER_ID = int(os.environ.get("OWNER_ID", 0))
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
config = {"active": False, "snipe_eth": 0.015, "min_liquidity_eth": 1.0, "balance_guard": 0.005}

# --- FUNCTIES ---

async def notify(msg):
    if OWNER_ID:
        try: await tg_app.bot.send_message(chat_id=OWNER_ID, text=msg, parse_mode="Markdown")
        except: pass

async def execute_buy(token_address, liq):
    try:
        # Check eigen balans
        bal_wei = await aw3.eth.get_balance(BOT_ADDRESS)
        if bal_wei < Web3.to_wei(config["snipe_eth"] + config["balance_guard"], 'ether'):
            await notify(f"⚠️ **SALDO TE LAAG**\nNodig: `{config['snipe_eth'] + config['balance_guard']} ETH`\nBeschikbaar: `{Web3.from_wei(bal_wei, 'ether'):.4f} ETH`")
            return

        router = aw3.eth.contract(address=AERODROME_ROUTER, abi=[{"inputs":[{"name":"amountOutMin","type":"uint256"},{"name":"routes","type":"tuple[]","components":[{"name":"from","type":"address"},{"name":"to","type":"address"},{"name":"stable","type":"bool"},{"name":"factory","type":"address"}]},{"name":"to","type":"address"},{"name":"deadline","type":"uint256"}],"name":"swapExactETHForTokens","outputs":[{"name":"amounts","type":"uint256[]"}],"stateMutability":"payable","type":"function"}])
        routes = [{"from": WETH, "to": token_address, "stable": False, "factory": AERODROME_FACTORY}]
        
        tx = await router.functions.swapExactETHForTokens(0, routes, BOT_ADDRESS, int(time.time()) + 60).build_transaction({
            'from': BOT_ADDRESS, 'value': Web3.to_wei(config["snipe_eth"], 'ether'),
            'nonce': await aw3.eth.get_transaction_count(BOT_ADDRESS), 'gas': 350000, 'chainId': 8453,
            'maxFeePerGas': await aw3.eth.gas_price, 'maxPriorityFeePerGas': Web3.to_wei(1, 'gwei')
        })
        signed = aw3.eth.account.sign_transaction(tx, raw_key)
        tx_hash = await aw3.eth.send_raw_transaction(signed.rawTransaction)
        await notify(f"🚀 **SNIPE VERSTUURD!**\nToken: `{token_address[:12]}`\n[Basescan](https://basescan.org/tx/{tx_hash.hex()})")
    except Exception as e: logger.error(f"Buy error: {e}")

async def scan_loop():
    last_block = await aw3.eth.block_number
    while True:
        if not config["active"]: await asyncio.sleep(2); continue
        try:
            curr_block = await aw3.eth.block_number
            if curr_block > last_block:
                for b in range(last_block + 1, curr_block + 1):
                    logger.info(f"🔍 Scan Blok {b} | Wallet: {BOT_ADDRESS[:10]}")
                    logs = await aw3.eth.get_logs({"fromBlock": b, "toBlock": b, "address": AERODROME_FACTORY, "topics": [POOL_TOPIC]})
                    for log in logs:
                        pool_addr = Web3.to_checksum_address("0x" + log["data"][-40:])
                        token = Web3.to_checksum_address("0x" + log["topics"][2][-40:] if Web3.to_checksum_address("0x" + log["topics"][1][-40:]) == WETH else "0x" + log["topics"][1][-40:])
                        liq = float(Web3.from_wei(await aw3.eth.get_balance(pool_addr), 'ether'))
                        if liq >= config["min_liquidity_eth"]:
                            asyncio.create_task(execute_buy(token, liq))
                last_block = curr_block
            await asyncio.sleep(0.5)
        except: await asyncio.sleep(2)

# --- COMMANDS ---

async def cmd_withdraw(u, c):
    if u.effective_user.id != OWNER_ID: return
    try:
        dest = Web3.to_checksum_address(c.args[0])
        bal = await aw3.eth.get_balance(BOT_ADDRESS)
        gas = (await aw3.eth.gas_price) * 21000
        tx = {'nonce': await aw3.eth.get_transaction_count(BOT_ADDRESS), 'to': dest, 'value': bal - gas, 'gas': 21000, 'gasPrice': await aw3.eth.gas_price, 'chainId': 8453}
        signed = aw3.eth.account.sign_transaction(tx, raw_key)
        h = await aw3.eth.send_raw_transaction(signed.rawTransaction)
        await u.message.reply_text(f"💰 Leeggehaald naar MetaMask!\n[Basescan](https://basescan.org/tx/{h.hex()})")
    except Exception as e: await u.message.reply_text(f"Fout: {e}")

async def cmd_start(u, c):
    if u.effective_user.id != OWNER_ID: return
    config["active"] = True
    await u.message.reply_text(f"🎯 **HUNTING MODE: AAN.**\nGebruikte Wallet: `{BOT_ADDRESS}`")

# --- STARTUP ---
@app.on_event("startup")
async def startup():
    global tg_app
    tg_app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    tg_app.add_handler(CommandHandler("start", cmd_start))
    tg_app.add_handler(CommandHandler("wallet", cmd_start))
    tg_app.add_handler(CommandHandler("withdraw", cmd_withdraw))
    await tg_app.initialize(); await tg_app.start(); await tg_app.updater.start_polling()
    asyncio.create_task(scan_loop())
    logger.info(f"🤜 Synthora V8.4 Live op {BOT_ADDRESS}")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
        
