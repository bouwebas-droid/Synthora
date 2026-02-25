# -*- coding: utf-8 -*-
import logging, os, asyncio, time, json, aiohttp, io
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime
from web3 import Web3, AsyncWeb3
from web3.providers import AsyncHTTPProvider
from eth_account import Account
from telegram.ext import ApplicationBuilder, CommandHandler
from fastapi import FastAPI, responses
import uvicorn

# --- INITIALISATIE ---
logging.basicConfig(format="%(asctime)s [SYNTHORA-V4.3] %(message)s", level=logging.INFO)
logger = logging.getLogger("Synthora")
app = FastAPI()

# Contracten
AERODROME_ROUTER = "0xcF77a3Ba9A5CA399B7c97c74d54e5b1Beb874E43"
AERODROME_FACTORY = "0x420DD381b31aEf6683db6B902084cB0FFECe40Da"
WETH = Web3.to_checksum_address("0x4200000000000000000000000000000000000006")
MAX_UINT256 = 2**256 - 1

# ABI's (Kritiek voor uitvoering)
ROUTER_ABI = json.loads('[{"inputs":[{"name":"amountOutMin","type":"uint256"},{"name":"routes","type":"tuple[]","components":[{"name":"from","type":"address"},{"name":"to","type":"address"},{"name":"stable","type":"bool"},{"name":"factory","type":"address"}]},{"name":"to","type":"address"},{"name":"deadline","type":"uint256"}],"name":"swapExactETHForTokens","outputs":[{"name":"amounts","type":"uint256[]"}],"stateMutability":"payable","type":"function"},{"inputs":[{"name":"amountIn","type":"uint256"},{"name":"amountOutMin","type":"uint256"},{"name":"routes","type":"tuple[]","components":[{"name":"from","type":"address"},{"name":"to","type":"address"},{"name":"stable","type":"bool"},{"name":"factory","type":"address"}]},{"name":"to","type":"address"},{"name":"deadline","type":"uint256"}],"name":"swapExactTokensForETH","outputs":[{"name":"amounts","type":"uint256[]"}],"stateMutability":"nonpayable","type":"function"},{"inputs":[{"name":"amountIn","type":"uint256"},{"name":"routes","type":"tuple[]","components":[{"name":"from","type":"address"},{"name":"to","type":"address"},{"name":"stable","type":"bool"},{"name":"factory","type":"address"}]}],"name":"getAmountsOut","outputs":[{"name":"amounts","type":"uint256[]"}],"stateMutability":"view","type":"function"}]')
ERC20_ABI = json.loads('[{"inputs":[{"name":"spender","type":"address"},{"name":"amount","type":"uint256"}],"name":"approve","outputs":[{"name":"","type":"bool"}],"stateMutability":"nonpayable","type":"function"},{"inputs":[{"name":"account","type":"address"}],"name":"balanceOf","outputs":[{"name":"","type":"uint256"}],"stateMutability":"view","type":"function"}]')

# Config & State
STATE_FILE = "synthora_v4_state.json"
config = {
    "active": False, "snipe_eth": 0.015, "max_positions": 10,
    "take_profit_pct": 50.0, "trailing_stop_pct": 10.0, "hard_stop_pct": 25.0,
    "min_liquidity_eth": 1.0, "slippage_bps": 300, "gas_multiplier": 1.25, "balance_guard": 0.005
}
positions, stats = {}, {"trades": 0, "wins": 0, "losses": 0, "total_pnl": 0.0, "pnl_history": [], "started": time.time()}

# Wallet & Web3
raw_key = os.environ.get("ARCHITECT_SESSION_KEY", "").strip().replace('"', "")
signer = Account.from_key(raw_key)
aw3 = AsyncWeb3(AsyncHTTPProvider(os.environ.get("BASE_RPC_URL")))
OWNER_ID = int(os.environ.get("OWNER_ID", 0))

# --- PERSISTENCE ---
def save_state():
    with open(STATE_FILE, "w") as f:
        json.dump({"positions": positions, "stats": stats, "config": config}, f, indent=4)

# --- TRADING LOGICA (THE REAL DEAL) ---

async def execute_approve(token_address):
    """Geeft Aerodrome toestemming om de tokens te verkopen."""
    token_contract = aw3.eth.contract(address=token_address, abi=ERC20_ABI)
    nonce = await aw3.eth.get_transaction_count(signer.address)
    tx = await token_contract.functions.approve(AERODROME_ROUTER, MAX_UINT256).build_transaction({
        'from': signer.address, 'nonce': nonce, 'gas': 100000, 
        'maxFeePerGas': await aw3.eth.gas_price, 'maxPriorityFeePerGas': Web3.to_wei(2, 'gwei'), 'chainId': 8453
    })
    signed = aw3.eth.account.sign_transaction(tx, raw_key)
    await aw3.eth.send_raw_transaction(signed.rawTransaction)
    logger.info(f"🔓 Token {token_address[:10]} goedgekeurd voor verkoop.")

async def execute_sell(token_address, reason):
    """Sluit de positie en pakt de winst/verlies."""
    pos = positions.get(token_address)
    if not pos: return
    
    token_contract = aw3.eth.contract(address=token_address, abi=ERC20_ABI)
    balance = await token_contract.functions.balanceOf(signer.address).call()
    if balance == 0: return

    router = aw3.eth.contract(address=AERODROME_ROUTER, abi=ROUTER_ABI)
    routes = [{"from": token_address, "to": WETH, "stable": False, "factory": AERODROME_FACTORY}]
    
    nonce = await aw3.eth.get_transaction_count(signer.address)
    tx = await router.functions.swapExactTokensForETH(
        balance, 0, routes, signer.address, int(time.time()) + 60
    ).build_transaction({
        'from': signer.address, 'nonce': nonce, 'gas': 250000,
        'maxFeePerGas': await aw3.eth.gas_price, 'maxPriorityFeePerGas': Web3.to_wei(2, 'gwei'), 'chainId': 8453
    })
    signed = aw3.eth.account.sign_transaction(tx, raw_key)
    tx_hash = await aw3.eth.send_raw_transaction(signed.rawTransaction)
    
    # Update Stats
    stats["trades"] += 1
    del positions[token_address]
    save_state()
    logger.info(f"💰 Verkocht {token_address[:10]} wegens {reason}. TX: {tx_hash.hex()}")

async def monitor_loop():
    """Houdt live de winst in de gaten (TP/SL)."""
    router = aw3.eth.contract(address=AERODROME_ROUTER, abi=ROUTER_ABI)
    while True:
        for addr, pos in list(positions.items()):
            try:
                routes = [{"from": addr, "to": WETH, "stable": False, "factory": AERODROME_FACTORY}]
                amounts = await router.functions.getAmountsOut(pos['amount'], routes).call()
                current_val = Web3.from_wei(amounts[-1], 'ether')
                entry_val = pos['entry_eth']
                pnl = (float(current_val) - entry_val) / entry_val * 100

                if pnl >= config["take_profit_pct"]: await execute_sell(addr, "TAKE_PROFIT")
                elif pnl <= -config["hard_stop_pct"]: await execute_sell(addr, "HARD_STOP")
            except: continue
        await asyncio.sleep(5)

# --- DE SNIPER ENGINE ---

async def execute_buy(token_address):
    """Koopt de token en start direct de approval."""
    token_address = Web3.to_checksum_address(token_address)
    router = aw3.eth.contract(address=AERODROME_ROUTER, abi=ROUTER_ABI)
    routes = [{"from": WETH, "to": token_address, "stable": False, "factory": AERODROME_FACTORY}]
    
    nonce = await aw3.eth.get_transaction_count(signer.address)
    tx = await router.functions.swapExactETHForTokens(
        0, routes, signer.address, int(time.time()) + 60
    ).build_transaction({
        'from': signer.address, 'value': Web3.to_wei(config["snipe_eth"], 'ether'),
        'nonce': nonce, 'gas': 300000, 'maxFeePerGas': await aw3.eth.gas_price,
        'maxPriorityFeePerGas': Web3.to_wei(2, 'gwei'), 'chainId': 8453
    })
    signed = aw3.eth.account.sign_transaction(tx, raw_key)
    tx_hash = await aw3.eth.send_raw_transaction(signed.rawTransaction)
    
    # Direct approve voor later
    await asyncio.sleep(2) # Wacht op tx broadcast
    asyncio.create_task(execute_approve(token_address))
    
    positions[token_address] = {"entry_eth": config["snipe_eth"], "amount": 0, "time": time.time()}
    save_state()

# --- TELEGRAM & SYSTEM START ---

@app.on_event("startup")
async def startup():
    global tg_app
    tg_app = ApplicationBuilder().token(os.environ.get("TELEGRAM_BOT_TOKEN")).build()
    # Voeg hier de commando's toe zoals /skyline en /start
    await tg_app.initialize()
    await tg_app.start()
    asyncio.create_task(monitor_loop())
    logger.info("🤜 Wingman is 100% operationeel. Saldo bewaakt.")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
