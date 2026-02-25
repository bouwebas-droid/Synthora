# -*- coding: utf-8 -*-
import logging, os, asyncio, time, json
from web3 import Web3, AsyncWeb3
from web3.providers import AsyncHTTPProvider
from eth_account import Account
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from fastapi import FastAPI
import uvicorn

# --- LOGGING ---
logging.basicConfig(format="%(asctime)s [ARCHITECT] %(message)s", level=logging.INFO)
logger = logging.getLogger("Synthora")
app = FastAPI()

# --- CONSTANTEN ---
EXPECTED_WALLET = "0xaF2C5d0063C236C95BEF05ecE7079f818EFBBF38"
AERODROME_FACTORY = "0x420DD381b31aEf6683db6B902084cB0FFECe40Da"
AERODROME_ROUTER = "0xcF77a3Ba9A5CA399B7c97c74d54e5b1Beb874E43"
WETH = Web3.to_checksum_address("0x4200000000000000000000000000000000000006")
POOL_TOPIC = "0x2128d88d14c80cb081c1252a5acff7a264671bf199ce226b53788fb26065005e"

# --- WALLET VALIDATIE ---
raw_key = os.environ.get("ARCHITECT_SESSION_KEY", "").strip().replace('"', "")
signer = Account.from_key(raw_key)
BOT_ADDRESS = signer.address

if BOT_ADDRESS.lower() != EXPECTED_WALLET.lower():
    logger.critical(f"❌ WALLET MISMATCH! Sleutel hoort bij {BOT_ADDRESS}, maar we verwachten {EXPECTED_WALLET}")
else:
    logger.info(f"✅ IDENTITEIT BEVESTIGD: Trading via {BOT_ADDRESS}")

# RPC Setup
RPC_URL = os.environ.get("BASE_RPC_URL", "https://mainnet.base.org").strip().replace('"', "")
aw3 = AsyncWeb3(AsyncHTTPProvider(RPC_URL))
OWNER_ID = int(os.environ.get("OWNER_ID", 0))
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

# --- CONFIG ---
config = {"active": False, "snipe_eth": 0.015, "min_liquidity_eth": 1.0}

# --- VEILIGE ADRES PARSER ---
def parse_addr(hex_val):
    """Voorkomt de 'InvalidAddress 0x0' error door data te valideren."""
    try:
        if not hex_val: return None
        h = hex_val.hex() if isinstance(hex_val, bytes) else str(hex_val)
        addr = "0x" + h[-40:]
        if addr == "0x0000000000000000000000000000000000000000": return None
        return Web3.to_checksum_address(addr)
    except: return None

# --- ACTIES ---
async def execute_buy(token_address):
    try:
        bal = await aw3.eth.get_balance(BOT_ADDRESS)
        if bal < Web3.to_wei(0.018, 'ether'): # Snipe + Gas reserve
            logger.warning("❌ Saldo te laag op bot wallet.")
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
        logger.info(f"🚀 Snipe uitgevoerd: {tx_hash.hex()}")
    except Exception as e: logger.error(f"Fout: {e}")

# --- SCANNER ---
async def scan_loop():
    last_block = await aw3.eth.block_number
    while True:
        if not config["active"]: await asyncio.sleep(2); continue
        try:
            curr_block = await aw3.eth.block_number
            if curr_block > last_block:
                for b in range(last_block + 1, curr_block + 1):
                    logger.info(f"🔍 Blok {b} | Wallet: {BOT_ADDRESS[:8]}")
                    logs = await aw3.eth.get_logs({"fromBlock": b, "toBlock": b, "address": AERODROME_FACTORY, "topics": [POOL_TOPIC]})
                    for log in logs:
                        t1, t2, pool = parse_addr(log["topics"][1]), parse_addr(log["topics"][2]), parse_addr(log["data"])
                        if not t1 or not t2 or not pool: continue
                        
                        token = t2 if t1 == WETH else t1
                        liq = float(Web3.from_wei(await aw3.eth.get_balance(pool), 'ether'))
                        if liq >= config["min_liquidity_eth"]:
                            asyncio.create_task(execute_buy(token))
                last_block = curr_block
            await asyncio.sleep(0.5)
        except: await asyncio.sleep(2)

# --- COMMANDS ---
async def cmd_wallet(u, c):
    if u.effective_user.id != OWNER_ID: return
    bal = Web3.from_wei(await aw3.eth.get_balance(BOT_ADDRESS), 'ether')
    await u.message.reply_text(f"💳 **Bot ({BOT_ADDRESS[:8]})**\nBalans: `{bal:.6f} ETH`")

async def cmd_withdraw(u, c):
    if u.effective_user.id != OWNER_ID: return
    try:
        dest = Web3.to_checksum_address(c.args[0])
        bal = await aw3.eth.get_balance(BOT_ADDRESS)
        gas = (await aw3.eth.gas_price) * 21000
        tx = {'nonce': await aw3.eth.get_transaction_count(BOT_ADDRESS), 'to': dest, 'value': bal - gas, 'gas': 21000, 'gasPrice': await aw3.eth.gas_price, 'chainId': 8453}
        signed = aw3.eth.account.sign_transaction(tx, raw_key)
        h = await aw3.eth.send_raw_transaction(signed.rawTransaction)
        await u.message.reply_text(f"💰 Winst overgezet naar MetaMask!")
    except Exception as e: await u.message.reply_text(f"Fout: {e}")

# --- STARTUP ---
@app.on_event("startup")
async def startup():
    global tg_app
    tg_app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    tg_app.add_handler(CommandHandler("start", lambda u,c: config.update({"active": True})))
    tg_app.add_handler(CommandHandler("wallet", cmd_wallet))
    tg_app.add_handler(CommandHandler("withdraw", cmd_withdraw))
    await tg_app.initialize(); await tg_app.start(); await tg_app.updater.start_polling()
    asyncio.create_task(scan_loop())

@app.get("/")
async def health(): return {"bot_active_on": BOT_ADDRESS}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
    
