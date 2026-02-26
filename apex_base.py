import os
import re
import time
import logging
from threading import Thread
from fastapi import FastAPI
from web3 import Web3
import telebot

# --- 1. CONFIGURATIE & LOGGER ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("SynthoraArchitect")

CONFIG = {
    "RPC_URL": os.getenv("BASE_RPC_URL"),
    "PRIVATE_KEY": os.getenv("OWNER_SECRET_KEY"),
    "OWNER_WALLET": os.getenv("OWNER_WALLET_ADDRESS"),
    "TG_TOKEN": os.getenv("TELEGRAM_BOT_TOKEN"),
    "OWNER_ID": int(os.getenv("OWNER_ID", 0)),
    "ROUTER_ADDRESS": "0xcF77a3Ba9A5CA399B7c97c74d54e5b1Beb874E43", # Aerodrome Router
    "WETH": "0x4200000000000000000000000000000000000006",
    "BUY_AMOUNT_ETH": 0.01, # Test met kleine bedragen!
    "SLIPPAGE": 10, # 10%
}

# --- 2. HULPFUNCTIES & ACCOUNT INITIALISATIE ---
def clean_key(key):
    if not key: return None
    cleaned = re.sub(r'[\s\'"]', '', key)
    if not cleaned.startswith("0x") and len(cleaned) == 64:
        cleaned = "0x" + cleaned
    return cleaned

w3 = Web3(Web3.HTTPProvider(CONFIG["RPC_URL"]))
safe_key = clean_key(CONFIG["PRIVATE_KEY"])
account = w3.eth.account.from_key(safe_key) if safe_key else None
bot = telebot.TeleBot(CONFIG["TG_TOKEN"]) if CONFIG["TG_TOKEN"] else None

# --- 3. AERODROME EXECUTION MODULE (The Swap Engine) ---
def execute_swap(token_in, token_out, amount_in, is_buy=True):
    """Voert een swap uit op Aerodrome."""
    try:
        router_abi = '[{"inputs":[{"internalType":"uint256","name":"amountIn","type":"uint256"},{"internalType":"uint256","name":"amountOutMin","type":"uint256"},{"components":[{"internalType":"address","name":"from","type":"address"},{"internalType":"address","name":"to","type":"address"},{"internalType":"bool","name":"stable","type":"bool"},{"internalType":"address","name":"factory","type":"address"}],"internalType":"struct IRouter.Route[]","name":"routes","type":"tuple[]"},{"internalType":"address","name":"to","type":"address"},{"internalType":"uint256","name":"deadline","type":"uint256"}],"name":"swapExactETHForTokens","outputs":[{"internalType":"uint256[]","name":"amounts","type":"uint256[]"}],"stateMutability":"payable","type":"function"}]'
        router = w3.eth.contract(address=CONFIG["ROUTER_ADDRESS"], abi=router_abi)
        
        # Route instellen (Aerodrome gebruikt specifieke route structs)
        routes = [{"from": token_in, "to": token_out, "stable": False, "factory": "0x420DD3807E0e10467D2260F03A008B2089404200"}]
        
        deadline = int(time.time()) + 600
        nonce = w3.eth.get_transaction_count(account.address)
        
        # Voor een 'Buy' gebruiken we swapExactETHForTokens
        tx = router.functions.swapExactETHForTokens(
            0, # In een productie-omgeving bereken je hier amountOutMin
            routes,
            account.address,
            deadline
        ).build_transaction({
            'from': account.address,
            'value': amount_in,
            'gas': 250000,
            'gasPrice': w3.eth.gas_price,
            'nonce': nonce,
            'chainId': 8453
        })

        signed_tx = w3.eth.account.sign_transaction(tx, safe_key)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
        logger.info(f"🎯 Trade uitgevoerd: {tx_hash.hex()}")
        return tx_hash.hex()
    except Exception as e:
        logger.error(f"❌ Swap Fout: {e}")
        return None

# --- 4. ACHTERGROND PROCESSEN ---
def sniper_loop():
    logger.info("🕵️ Sniper Engine actief: Wachten op Alpha signalen...")
    while True:
        # Hier komt de logica die execute_swap aanroept bij een match
        time.sleep(20)

def monitor_positions():
    logger.info("📈 Profit Sentinel actief: Bewaken van posities...")
    while True:
        # Check koers en verkoop 50% bij 2x winst
        time.sleep(30)

# --- 5. WEB SERVER & TELEGRAM ---
app = FastAPI()

@app.get("/")
def health():
    return {"status": "Synthora Master Engine Online", "wallet": account.address if account else "error"}

def run_bot():
    logger.info("🤖 Telegram Interface gestart.")
    while True:
        try:
            bot.polling(none_stop=True, timeout=60)
        except Exception:
            time.sleep(10)

if __name__ == "__main__":
    if bot:
        Thread(target=run_bot, daemon=True).start()
    Thread(target=sniper_loop, daemon=True).start()
    Thread(target=monitor_positions, daemon=True).start()
    
