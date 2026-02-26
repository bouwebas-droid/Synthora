import os
import time
import threading
import requests
import logging
from web3 import Web3
import telebot

# ============================================================================
# 1. ARCHITECT CORE CONFIG
# ============================================================================
ALCHEMY_KEY = os.getenv("ALCHEMY_API_KEY", "").strip()
SESSION_KEY = os.getenv("ARCHITECT_SESSION_KEY", "").strip() 
BOT_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
ADMIN_ID    = os.getenv("TELEGRAM_ADMIN_ID", "").strip()
CHANNEL_ID  = os.getenv("TELEGRAM_BROADCAST_CHANNEL", "").strip()

# Trading & Security Config
config = {
    "snipe_amount": 0.002, 
    "take_profit": 2.0,    # +100%
    "stop_loss": 0.8,      # -20%
    "auto_snipe": False,
    "active_positions": {} 
}

# Logger setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SynthoraElite")

# ============================================================================
# 2. WEB3 & TELEGRAM INITIALISATIE
# ============================================================================
def get_w3():
    return Web3(Web3.HTTPProvider(f"https://base-mainnet.g.alchemy.com/v2/{ALCHEMY_KEY}"))

w3 = get_w3()
bot = telebot.TeleBot(BOT_TOKEN)

try:
    account = w3.eth.account.from_key(SESSION_KEY)
    wallet_address = account.address
except Exception as e:
    logger.error(f"Vault Error: {e}")
    os._exit(1)

def is_admin(m):
    return str(m.from_user.id) == str(ADMIN_ID)

# ============================================================================
# 3. ELITE ENGINES (SNIPER, MONITOR, SELF-HEAL)
# ============================================================================

def self_healing_engine():
    """Controleert elke 60 seconden of de bot nog leeft"""
    while True:
        try:
            if not w3.is_connected():
                logger.warning("Base connection lost. Re-healing...")
                globals()['w3'] = get_w3()
            time.sleep(60)
        except Exception as e:
            logger.error(f"Heal Engine Error: {e}")

def auto_exit_monitor():
    """Bewaakt je 0.002 ETH inzet (Stop Loss / Take Profit)"""
    while True:
        for token_addr, entry_price in list(config["active_positions"].items()):
            try:
                r = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{token_addr}", timeout=5).json()
                pairs = r.get('pairs', [])
                if not pairs: continue
                
                curr_price = float(pairs[0].get('priceUsd', 0))
                roi = curr_price / entry_price
                
                if roi >= config["take_profit"]:
                    bot.send_message(ADMIN_ID, f"💰 **TAKE PROFIT (2x):** `{token_addr}`")
                    del config["active_positions"][token_addr]
                elif roi <= config["stop_loss"]:
                    bot.send_message(ADMIN_ID, f"🛡️ **STOP LOSS (-20%):** `{token_addr}`")
                    del config["active_positions"][token_addr]
            except: pass
        time.sleep(15)

def sniper_engine():
    """Scant op nieuwe Aerodrome pools"""
    last_block = w3.eth.block_number
    factory_addr = "0x420DD3807E0e1379f6a1611709d7085d8883C117"
    while True:
        try:
            curr = w3.eth.block_number
            if curr > last_block:
                block = w3.eth.get_block(curr, full_transactions=True)
                for tx in block.transactions:
                    if tx.get('to') == factory_addr:
                        msg = "🎯 **NEW POOL:** Gedetecteerd op Aerodrome (Base)."
                        bot.send_message(ADMIN_ID, msg)
                        if CHANNEL_ID:
                            bot.send_message(CHANNEL_ID, "📣 **Synthora Scan:** Nieuwe liquiditeit op Base!")
                last_block = curr
            time.sleep(1)
        except: time.sleep(2)

# ============================================================================
# 4. COMMANDS
# ============================================================================

@bot.message_handler(commands=['status'])
def cmd_status(m):
    if not is_admin(m): return
    bal = w3.from_wei(w3.eth.get_balance(wallet_address), 'ether')
    msg = (f"🏙️ **Architect Dashboard**\n\n"
           f"💰 Balans: `{bal:.4f} ETH`\n"
           f"🛡️ Sniper: {'🟢 AAN' if config['auto_snipe'] else '🔴 UIT'}\n"
           f"📦 Monitor: `{len(config['active_positions'])}` posities")
    bot.reply_to(m, msg, parse_mode="Markdown")

@bot.message_handler(commands=['withdraw'])
def cmd_withdraw(m):
    if not is_admin(m): return
    try:
        target = w3.to_checksum_address(m.text.split()[1])
        bal = w3.eth.get_balance(wallet_address)
        gas = 21000 * w3.eth.gas_price
        tx = {'nonce': w3.eth.get_transaction_count(wallet_address), 'to': target, 'value': bal - (gas * 2), 'gas': 21000, 'gasPrice': w3.eth.gas_price, 'chainId': 8453}
        signed = w3.eth.account.sign_transaction(tx, SESSION_KEY)
        h = w3.eth.send_raw_transaction(signed.raw_transaction)
        bot.reply_to(m, f"💸 **Funds Veilig!** Hash: `{h.hex()}`")
    except Exception as e: bot.reply_to(m, f"❌ Fout: {e}")

@bot.message_handler(commands=['broadcast'])
def cmd_broadcast(m):
    if not is_admin(m): return
    txt = m.text.replace('/broadcast ', '')
    if CHANNEL_ID:
        bot.send_message(CHANNEL_ID, f"📣 **Synthora Elite Update:**\n\n{txt}", parse_mode="Markdown")

# ============================================================================
# 5. LAUNCH
# ============================================================================
if __name__ == "__main__":
    # Clean start
    bot.remove_webhook()
    time.sleep(1)
    
    # Start all threads
    threading.Thread(target=self_healing_engine, daemon=True).start()
    threading.Thread(target=sniper_engine, daemon=True).start()
    threading.Thread(target=auto_exit_monitor, daemon=True).start()
    
    logger.info(f"✅ Synthora Elite Architect gestart op {wallet_address}")
    
    # Infinity polling met error handling
    while True:
        try:
            bot.polling(none_stop=True, interval=0, timeout=20)
        except Exception as e:
            logger.error(f"Polling crash: {e}")
            time.sleep(5)
    
