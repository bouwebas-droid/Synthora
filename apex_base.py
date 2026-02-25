# -*- coding: utf-8 -*-
# =============================================================
#  SYNTHORA V4.7 - FINAL AUTOMATOR
#  Base Mainnet | Aerodrome | Auto-Blacklist | Full Execution
# =============================================================
import logging, os, asyncio, time, json, aiohttp, io
from web3 import Web3, AsyncWeb3
from web3.providers import AsyncHTTPProvider
from eth_account import Account
from telegram.ext import ApplicationBuilder, CommandHandler
from fastapi import FastAPI, responses
import uvicorn

# --- LOGGER & CONFIG ---
logging.basicConfig(format="%(asctime)s [SYSTEM] %(message)s", level=logging.INFO)
logger = logging.getLogger("Synthora")
app = FastAPI()

# Contracten & Adressen
AERODROME_ROUTER = "0xcF77a3Ba9A5CA399B7c97c74d54e5b1Beb874E43"
AERODROME_FACTORY = "0x420DD381b31aEf6683db6B902084cB0FFECe40Da"
WETH = Web3.to_checksum_address("0x4200000000000000000000000000000000000006")
POOL_TOPIC = "0x2128d88d14c80cb081c1252a5acff7a264671bf199ce226b53788fb26065005e"
MAX_UINT256 = 2**256 - 1

# ABI's
ROUTER_ABI = json.loads('[{"inputs":[{"name":"amountOutMin","type":"uint256"},{"name":"routes","type":"tuple[]","components":[{"name":"from","type":"address"},{"name":"to","type":"address"},{"name":"stable","type":"bool"},{"name":"factory","type":"address"}]},{"name":"to","type":"address"},{"name":"deadline","type":"uint256"}],"name":"swapExactETHForTokens","outputs":[{"name":"amounts","type":"uint256[]"}],"stateMutability":"payable","type":"function"},{"inputs":[{"name":"amountIn","type":"uint256"},{"name":"amountOutMin","type":"uint256"},{"name":"routes","type":"tuple[]","components":[{"name":"from","type":"address"},{"name":"to","type":"address"},{"name":"stable","type":"bool"},{"name":"factory","type":"address"}]},{"name":"to","type":"address"},{"name":"deadline","type":"uint256"}],"name":"swapExactTokensForETH","outputs":[{"name":"amounts","type":"uint256[]"}],"stateMutability":"nonpayable","type":"function"},{"inputs":[{"name":"amountIn","type":"uint256"},{"name":"routes","type":"tuple[]","components":[{"name":"from","type":"address"},{"name":"to","type":"address"},{"name":"stable","type":"bool"},{"name":"factory","type":"address"}]}],"name":"getAmountsOut","outputs":[{"name":"amounts","type":"uint256[]"}],"stateMutability":"view","type":"function"}]')
ERC20_ABI = json.loads('[{"inputs":[{"name":"spender","type":"address"},{"name":"amount","type":"uint256"}],"name":"approve","outputs":[{"name":"","type":"bool"}],"stateMutability":"nonpayable","type":"function"},{"inputs":[{"name":"account","type":"address"}],"name":"balanceOf","outputs":[{"name":"","type":"uint256"}],"stateMutability":"view","type":"function"}]')

# State Management
STATE_FILE = "synthora_v4_state.json"
config = {
    "active": False, "snipe_eth": 0.015, "max_positions": 10,
    "take_profit_pct": 45.0, "hard_stop_pct": 20.0,
    "min_liquidity_eth": 1.0, "slippage_bps": 300, "balance_guard": 0.005
}
positions, blacklist = {}, set()
stats = {"trades": 0, "wins": 0, "losses": 0, "total_pnl": 0.0}

# Wallet & Web3 Connection
raw_key = os.environ.get("ARCHITECT_SESSION_KEY", "").strip().replace('"', "")
signer = Account.from_key(raw_key)
aw3 = AsyncWeb3(AsyncHTTPProvider(os.environ.get("BASE_RPC_URL")))
OWNER_ID = int(os.environ.get("OWNER_ID", 0))
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
tg_app = None

# --- CORE UTILITIES ---

def save_state():
    try:
        data = {"positions": positions, "stats": stats, "config": config, "blacklist": list(blacklist)}
        with open(STATE_FILE, "w") as f:
            json.dump(data, f, indent=4)
    except Exception as e: logger.error(f"State save error: {e}")

async def notify(msg):
    if tg_app and OWNER_ID:
        try: await tg_app.bot.send_message(chat_id=OWNER_ID, text=msg, parse_mode="Markdown")
        except: pass

# --- AUTO-BLACKLIST LOGIC ---

async def monitor_liquidity_health(token_address, delay=300):
    """Controleert na X seconden of de liquiditeit nog aanwezig is."""
    await asyncio.sleep(delay)
    try:
        router = aw3.eth.contract(address=AERODROME_ROUTER, abi=ROUTER_ABI)
        routes = [{"from": WETH, "to": token_address, "stable": False, "factory": AERODROME_FACTORY}]
        # Test met een kleine hoeveelheid om liquiditeit te verifiëren
        amounts = await router.functions.getAmountsOut(Web3.to_wei(0.001, 'ether'), routes).call()
        
        if amounts[-1] <= 0:
            blacklist.add(token_address)
            logger.warning(f"🚫 Token {token_address} geblacklist: Geen liquiditeit gevonden na 5 min.")
            await notify(f"🚫 **Auto-Blacklist:** `{token_address[:12]}` verwijderd wegens gebrek aan liquiditeit.")
            save_state()
    except Exception:
        blacklist.add(token_address)
        save_state()

# --- TRADING ACTIONS ---

async def execute_approve(token_address):
    try:
        token_contract = aw3.eth.contract(address=token_address, abi=ERC20_ABI)
        nonce = await aw3.eth.get_transaction_count(signer.address)
        tx = await token_contract.functions.approve(AERODROME_ROUTER, MAX_UINT256).build_transaction({
            'from': signer.address, 'nonce': nonce, 'gas': 100000, 
            'maxFeePerGas': await aw3.eth.gas_price, 'maxPriorityFeePerGas': Web3.to_wei(1, 'gwei'), 'chainId': 8453
        })
        signed = aw3.eth.account.sign_transaction(tx, raw_key)
        await aw3.eth.send_raw_transaction(signed.rawTransaction)
        logger.info(f"🔓 Approval geslaagd voor {token_address[:10]}")
    except Exception as e: logger.error(f"Approve error: {e}")

async def execute_sell(token_address, reason):
    if token_address not in positions: return
    try:
        token_contract = aw3.eth.contract(address=token_address, abi=ERC20_ABI)
        bal = await token_contract.functions.balanceOf(signer.address).call()
        if bal == 0: return

        router = aw3.eth.contract(address=AERODROME_ROUTER, abi=ROUTER_ABI)
        routes = [{"from": token_address, "to": WETH, "stable": False, "factory": AERODROME_FACTORY}]
        
        nonce = await aw3.eth.get_transaction_count(signer.address)
        tx = await router.functions.swapExactTokensForETH(
            bal, 0, routes, signer.address, int(time.time()) + 60
        ).build_transaction({
            'from': signer.address, 'nonce': nonce, 'gas': 250000, 'chainId': 8453,
            'maxFeePerGas': await aw3.eth.gas_price, 'maxPriorityFeePerGas': Web3.to_wei(1, 'gwei')
        })
        signed = aw3.eth.account.sign_transaction(tx, raw_key)
        tx_hash = await aw3.eth.send_raw_transaction(signed.rawTransaction)
        
        await notify(f"💰 **Verkoop Uitgevoerd**\nToken: `{token_address[:12]}`\nReden: `{reason}`")
        del positions[token_address]
        stats["trades"] += 1
        save_state()
    except Exception as e: logger.error(f"Sell error: {e}")

async def execute_buy(token_address):
    token_address = Web3.to_checksum_address(token_address)
    if token_address in positions or token_address in blacklist: return
    
    router = aw3.eth.contract(address=AERODROME_ROUTER, abi=ROUTER_ABI)
    routes = [{"from": WETH, "to": token_address, "stable": False, "factory": AERODROME_FACTORY}]
    
    try:
        nonce = await aw3.eth.get_transaction_count(signer.address)
        tx = await router.functions.swapExactETHForTokens(
            0, routes, signer.address, int(time.time()) + 60
        ).build_transaction({
            'from': signer.address, 'value': Web3.to_wei(config["snipe_eth"], 'ether'),
            'nonce': nonce, 'gas': 300000, 'chainId': 8453,
            'maxFeePerGas': await aw3.eth.gas_price, 'maxPriorityFeePerGas': Web3.to_wei(1, 'gwei')
        })
        signed = aw3.eth.account.sign_transaction(tx, raw_key)
        tx_hash = await aw3.eth.send_raw_transaction(signed.rawTransaction)
        
        receipt = await aw3.eth.wait_for_transaction_receipt(tx_hash)
        if receipt.status == 1:
            token_contract = aw3.eth.contract(address=token_address, abi=ERC20_ABI)
            bal = await token_contract.functions.balanceOf(signer.address).call()
            positions[token_address] = {"entry_eth": config["snipe_eth"], "token_amount": bal, "time": time.time()}
            
            # Start achtergrondtaken
            asyncio.create_task(execute_approve(token_address))
            asyncio.create_task(monitor_liquidity_health(token_address))
            
            await notify(f"🚀 **Snipe Succesvol**\nToken: `{token_address[:12]}`\nMonitoring gestart.")
            save_state()
    except Exception as e: logger.error(f"Buy error: {e}")

# --- MONITORING LOOPS ---

async def monitor_loop():
    router = aw3.eth.contract(address=AERODROME_ROUTER, abi=ROUTER_ABI)
    while True:
        for addr, pos in list(positions.items()):
            try:
                routes = [{"from": addr, "to": WETH, "stable": False, "factory": AERODROME_FACTORY}]
                amounts = await router.functions.getAmountsOut(pos['token_amount'], routes).call()
                current_eth = float(Web3.from_wei(amounts[-1], 'ether'))
                pnl = (current_eth - pos['entry_eth']) / pos['entry_eth'] * 100

                if pnl >= config["take_profit_pct"]: await execute_sell(addr, f"Take Profit ({pnl:.1f}%)")
                elif pnl <= -config["hard_stop_pct"]: await execute_sell(addr, f"Hard Stop ({pnl:.1f}%)")
            except: continue
        await asyncio.sleep(5)

async def scan_loop():
    last_block = await aw3.eth.block_number
    while True:
        if not config["active"]: await asyncio.sleep(2); continue
        try:
            curr_block = await aw3.eth.block_number
            if curr_block > last_block:
                for b in range(last_block + 1, curr_block + 1):
                    logs = await aw3.eth.get_logs({"fromBlock": b, "toBlock": b, "address": AERODROME_FACTORY, "topics": [POOL_TOPIC]})
                    for log in logs:
                        t0 = Web3.to_checksum_address("0x" + log["topics"][1][-40:])
                        t1 = Web3.to_checksum_address("0x" + log["topics"][2][-40:])
                        token = t1 if t0 == WETH else t0
                        if len(positions) < config["max_positions"]:
                            asyncio.create_task(execute_buy(token))
                last_block = curr_block
            await asyncio.sleep(1)
        except: await asyncio.sleep(2)

# --- BOOTSTRAP ---

@app.on_event("startup")
async def startup():
    global tg_app
    tg_app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    tg_app.add_handler(CommandHandler("start", lambda u, c: setattr(config, 'active', True)))
    tg_app.add_handler(CommandHandler("wallet", lambda u, c: asyncio.create_task(u.message.reply_text(f"Balans: {Web3.from_wei(aw3.eth.get_balance(signer.address), 'ether')} ETH"))))
    
    await tg_app.initialize()
    await tg_app.start()
    await tg_app.updater.start_polling()
    
    asyncio.create_task(monitor_loop())
    asyncio.create_task(scan_loop())
    logger.info("Systeem V4.7 operationeel.")

@app.get("/")
async def health(): return {"status": "ok"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
        
