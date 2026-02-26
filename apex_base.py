import os
import re
import time
import logging
from threading import Thread
from fastapi import FastAPI
from web3 import Web3
import telebot

# --- LOGGING SETUP ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# --- 1. CONFIGURATIE MET VALIDATIE ---
def load_config():
    """Load and validate environment variables.
    
    Note: OWNER_WALLET is auto-derived from OWNER_SECRET_KEY,
    so you don't need to set it as an environment variable.
    """
    # Support both OWNER_WALLET_ADDRESS and OWNER_WALLET for flexibility
    # But if neither is set, we'll derive it from the private key
    owner_wallet = os.getenv("OWNER_WALLET_ADDRESS") or os.getenv("OWNER_WALLET")
    
    config = {
        "RPC_URL": os.getenv("BASE_RPC_URL"),
        "PRIVATE_KEY": os.getenv("OWNER_SECRET_KEY"),
        "OWNER_WALLET": owner_wallet,
        "TG_TOKEN": os.getenv("TELEGRAM_BOT_TOKEN"),
        "OWNER_ID": os.getenv("OWNER_ID"),
        "ROUTER": "0xcF77a3Ba9A5CA399B7c97c74d54e5b1Beb874E43",
    }
    
    # Valideer critical vars (OWNER_WALLET is optional, we derive it from private key)
    required = ["RPC_URL", "PRIVATE_KEY"]
    missing = [k for k in required if not config[k]]
    
    if missing:
        logger.error(f"❌ Missing required env vars: {missing}")
        raise ValueError(f"Missing: {missing}")
    
    # Converteer OWNER_ID naar int (alleen als ingesteld)
    if config["OWNER_ID"]:
        try:
            config["OWNER_ID"] = int(config["OWNER_ID"])
        except ValueError:
            logger.error("❌ OWNER_ID must be a number")
            raise
    
    return config

CONFIG = load_config()

# --- 2. HEX-FILTER ---
def clean_private_key(key):
    """Verwijdert alles wat geen hexadecimaal teken is."""
    if not key:
        return None
    key = key.lower().strip()
    if key.startswith("0x"):
        key = key[2:]
    cleaned = re.sub(r'[^0-9a-f]', '', key)
    if len(cleaned) != 64:
        logger.error(f"❌ Invalid private key length: {len(cleaned)} (expected 64)")
        return None
    return "0x" + cleaned

# --- 3. WEB3 INITIALISATIE ---
def init_web3():
    """Initialize Web3 with error handling."""
    try:
        w3 = Web3(Web3.HTTPProvider(CONFIG["RPC_URL"]))
        
        # Test verbinding
        if not w3.is_connected():
            logger.error("❌ Cannot connect to RPC")
            return None, None
        
        logger.info(f"✅ Connected to Base RPC (Chain ID: {w3.eth.chain_id})")
        
        # Laad account
        safe_key = clean_private_key(CONFIG["PRIVATE_KEY"])
        if not safe_key:
            logger.error("❌ Invalid private key format")
            return w3, None
        
        account = w3.eth.account.from_key(safe_key)
        balance = w3.from_wei(w3.eth.get_balance(account.address), 'ether')
        
        logger.info(f"✅ Wallet loaded: {account.address}")
        logger.info(f"💰 Balance: {balance:.5f} ETH")
        
        # Store derived address in CONFIG for convenience
        CONFIG["OWNER_WALLET"] = account.address
        
        return w3, account
        
    except Exception as e:
        logger.error(f"❌ Web3 init failed: {e}")
        return None, None

w3, account = init_web3()

# --- 4. TELEGRAM BOT INITIALISATIE ---
def init_telegram():
    """Initialize Telegram bot with error handling."""
    if not CONFIG.get("TG_TOKEN"):
        logger.warning("⚠️ No Telegram token - bot disabled")
        return None
    
    if not CONFIG.get("OWNER_ID"):
        logger.warning("⚠️ No OWNER_ID set - Telegram commands disabled for security")
        return None
    
    try:
        bot = telebot.TeleBot(CONFIG["TG_TOKEN"])
        # Test de verbinding
        bot.get_me()
        logger.info("✅ Telegram bot connected")
        return bot
    except Exception as e:
        logger.error(f"❌ Telegram init failed: {e}")
        return None

bot = init_telegram()

# --- 5. ELITE SNIPER & MONITOR LOGICA ---
def sniper_loop():
    """Scant op Smart Money en Aerodrome liquiditeit."""
    logger.info("🕵️ Synthora Sentinel: Jacht op Alpha is geopend...")
    
    while True:
        try:
            # Hier de jacht-logica
            # TODO: Implement sniper logic
            pass
        except Exception as e:
            logger.error(f"Sniper loop error: {e}")
        
        time.sleep(15)

def monitor_positions():
    """Bewaakt winsten en voert 2x Take Profit uit."""
    logger.info("📊 Position monitor started")
    
    while True:
        try:
            # Hier de bewakings-logica
            # TODO: Implement monitoring logic
            pass
        except Exception as e:
            logger.error(f"Monitor loop error: {e}")
        
        time.sleep(30)

# --- 6. TELEGRAM COMMANDS ---
if bot and CONFIG.get("OWNER_ID"):
    @bot.message_handler(commands=['start', 'status'])
    def status_report(message):
        if message.from_user.id != CONFIG["OWNER_ID"]:
            logger.warning(f"Unauthorized access attempt from {message.from_user.id}")
            return
        
        try:
            balance = w3.from_wei(w3.eth.get_balance(account.address), 'ether') if account else 0
            chain_id = w3.eth.chain_id if w3 else "disconnected"
            
            msg = (
                "🏙️ **SYNTHORA SOVEREIGN ENGINE**\n\n"
                f"● **Status:** {'✅ Operational' if account else '❌ Wallet Error'}\n"
                f"● **Chain:** Base (ID: {chain_id})\n"
                f"● **Balans:** `{balance:.5f} ETH`\n"
                f"● **Wallet:** `{account.address[:8]}...{account.address[-6:]}`"
            )
            bot.reply_to(message, msg, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Status command error: {e}")
            bot.reply_to(message, f"❌ Error: {str(e)}")

    @bot.message_handler(commands=['withdraw'])
    def withdraw_cmd(message):
        if message.from_user.id != CONFIG["OWNER_ID"]:
            return
        bot.reply_to(message, "💰 Architect, opname protocol gestart...")
        # TODO: Implement withdrawal logic

# --- 7. TELEGRAM POLLING THREAD ---
def run_telegram():
    """Run telegram bot polling with auto-restart."""
    if not bot:
        logger.warning("⚠️ Telegram bot not initialized - skipping polling")
        return
    
    logger.info("🤖 Starting Telegram polling...")
    
    while True:
        try:
            bot.polling(none_stop=True, timeout=60)
        except Exception as e:
            logger.error(f"Telegram polling error: {e}")
            time.sleep(10)

# --- 8. FASTAPI APP ---
app = FastAPI(title="Synthora Elite")

@app.get("/")
def health():
    """Health check endpoint."""
    return {
        "status": "Synthora Elite Live",
        "wallet": account.address if account else "error",
        "connected": w3.is_connected() if w3 else False,
        "telegram": bot is not None
    }

@app.get("/balance")
def get_balance():
    """Get wallet balance."""
    if not account or not w3:
        return {"error": "Wallet not initialized"}
    
    try:
        balance = w3.from_wei(w3.eth.get_balance(account.address), 'ether')
        return {
            "address": account.address,
            "balance_eth": float(balance),
            "chain_id": w3.eth.chain_id
        }
    except Exception as e:
        return {"error": str(e)}

# --- 9. STARTUP ---
def start_background_threads():
    """Start all background threads."""
    logger.info("🚀 Starting background threads...")
    
    # Start Telegram bot
    if bot:
        Thread(target=run_telegram, daemon=True, name="TelegramBot").start()
    
    # Start sniper
    Thread(target=sniper_loop, daemon=True, name="Sniper").start()
    
    # Start monitor
    Thread(target=monitor_positions, daemon=True, name="Monitor").start()
    
    logger.info("✅ All threads started")

# --- 10. MAIN ENTRY POINT ---
if __name__ == "__main__":
    import uvicorn
    
    # Start background threads
    start_background_threads()
    
    # Start FastAPI server
    port = int(os.getenv("PORT", 8000))
    logger.info(f"🌐 Starting FastAPI on port {port}")
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info"
    )
