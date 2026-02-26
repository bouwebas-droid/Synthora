import os
import re
import time
import binascii
from fastapi import FastAPI
from web3 import Web3
from threading import Thread

# --- 1. ROBUUSTE CONFIGURATIE ---
CONFIG = {
    "RPC_URL": os.getenv("RPC_URL", "https://mainnet.base.org"),
    "PRIVATE_KEY": os.getenv("PRIVATE_KEY"),
    "OWNER_WALLET": os.getenv("OWNER_WALLET"),
    "TG_TOKEN": os.getenv("TG_TOKEN"),
    "OWNER_ID": int(os.getenv("OWNER_ID", 0)),
}

w3 = Web3(Web3.HTTPProvider(CONFIG["RPC_URL"]))

def clean_key(key):
    """Schoont de key op van alle rommel (spaties, quotes, etc)."""
    if not key: return None
    cleaned = re.sub(r'[\s\'"]', '', key)
    if not cleaned.startswith("0x"):
        cleaned = "0x" + cleaned
    return cleaned

# Initialiseer Account veilig
try:
    safe_key = clean_key(CONFIG["PRIVATE_KEY"])
    if safe_key:
        account = w3.eth.account.from_key(safe_key)
        print(f"✅ Synthora Architect geladen: {account.address}")
    else:
        print("❌ ACCOUNT ERROR: Geen PRIVATE_KEY gevonden.")
        account = None
except Exception as e:
    print(f"❌ ACCOUNT ERROR: {e}")
    account = None

# --- 2. CORE SNIPER & WITHDRAWAL LOGICA ---
def execute_withdrawal():
    """Stuur alle ETH van de bot naar de eigenaar."""
    if not account: return
    balance = w3.eth.get_balance(account.address)
    gas_price = w3.eth.gas_price
    gas_limit = 21000
    value = balance - (gas_price * gas_limit)
    
    if value > 0:
        tx = {
            'nonce': w3.eth.get_transaction_count(account.address),
            'to': CONFIG["OWNER_WALLET"],
            'value': value,
            'gas': gas_limit,
            'gasPrice': gas_price,
            'chainId': 8453
        }
        signed_tx = w3.eth.account.sign_transaction(tx, safe_key)
        w3.eth.send_raw_transaction(signed_tx.rawTransaction)
        print("💰 Opname succesvol uitgevoerd.")

# --- 3. WEB SERVER VOOR RENDER (KEEP-ALIVE) ---
app = FastAPI()

@app.get("/")
def home():
    status = "Active" if account else "Key Error"
    return {"bot": "Synthora Architect", "status": status, "address": account.address if account else None}

@app.get("/health")
def health():
    return {"status": "healthy"}

# --- 4. BACKGROUND ENGINE ---
def run_sniper_loop():
    """De kern van de Synthora Sniper."""
    print("🕵️ Scannen naar kansen op Base...")
    while True:
        try:
            # Hier voeg je de scan-logica toe voor nieuwe paren op de Factory
            pass
        except Exception as e:
            print(f"⚠️ Loop error: {e}")
        time.sleep(5)

if account:
    Thread(target=run_sniper_loop, daemon=True).start()
