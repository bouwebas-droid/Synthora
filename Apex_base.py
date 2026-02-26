import os
import time
import logging
import threading
import requests
from web3 import Web3
from collections import defaultdict
import telebot

# ============================================================================
# 1. CONFIGURATIE & VEILIGHEID (STRIP FOUTEN)
# ============================================================================
ALCHEMY_API_KEY = os.getenv("ALCHEMY_API_KEY", "").strip()
PRIVATE_KEY = os.getenv("PRIVATE_KEY", "").strip()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_ADMIN_ID = os.getenv("TELEGRAM_ADMIN_ID", "").strip()
TELEGRAM_BROADCAST_CHANNEL = os.getenv("TELEGRAM_BROADCAST_CHANNEL", "").strip()

# Stop als essentiele zaken missen
if not all([ALCHEMY_API_KEY, PRIVATE_KEY, TELEGRAM_BOT_TOKEN]):
    print("❌ CRITICAL: Missing Environment Variables in Render!")
    exit(1)

# ============================================================================
# 2. WEB3 & WALLET SETUP
# ============================================================================
BASE_RPC = f"https://base-mainnet.g.alchemy.com/v2/{ALCHEMY_API_KEY}"
w3 = Web3(Web3.HTTPProvider(BASE_RPC))

if not w3.is_connected():
    w3 = Web3(Web3.HTTPProvider("https://mainnet.base.org"))

account = w3.eth.account.from_key(PRIVATE_KEY)
wallet_address = account.address

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
logger = logging.getLogger("synthora")
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

# State
WHALE_WALLETS = {} 
bot_state = {"running": True, "auto_snipe": False}

def is_admin(message):
    return str(message.from_user.id) == str(TELEGRAM_ADMIN_ID)

# ============================================================================
# 3. DEX SCREENER & SAFETY ENGINE
# ============================================================================
def get_dex_data(token_addr):
    try:
        res = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{token_addr}", timeout=10).json()
        if not res.get('pairs'): return None
        return max(res['pairs'], key=lambda x: x.get('liquidity', {}).get('usd', 0))
    except: return None

def check_contract_safety(token_addr):
    try:
        code = w3.eth.get_code(w3.to_checksum_address(token_addr))
        if len(code) <= 2: return False, "Geen contract code (Scam)"
        return True, "Code aanwezig"
    except Exception as e: return False, str(e)

# ============================================================================
# 4. TELEGRAM COMMANDS
# ============================================================================

@bot.message_handler(commands=['status'])
def status(message):
    if not is_admin(message): return
    bal = w3.from_wei(w3.eth.get_balance(wallet_address), 'ether')
    bot.reply_to(message, f"🟢 **Synthora Online**\n\nWallet: `{wallet_address}`\nBalans: `{bal:.4f} ETH`", parse_mode="Markdown")

@bot.message_handler(commands=['check'])
def check(message):
    if not is_admin(message): return
    addr = message.text.split()[-1]
    data = get_dex_data(addr)
    safe, reason = check_contract_safety(addr)
    
    if not data:
        bot.reply_to(message, f"🛡️ Safety: {reason}\n📊 Geen DEX data gevonden.")
        return

    report = f"📊 **{data['baseToken']['symbol']}**\nLiq: `${data['liquidity']['usd']:,.0f}`\nMCAP: `${data.get('fdv', 0):,.0f}`\n\n🛡️ Safety: {reason}"
    bot.reply_to(message, report, parse_mode="Markdown")

@bot.message_handler(commands=['broadcast'])
def broadcast(message):
    if not is_admin(message): return
    txt = message.text.replace('/broadcast ', '')
    if TELEGRAM_BROADCAST_CHANNEL:
        bot.send_message(TELEGRAM_BROADCAST_CHANNEL, f"📣 **Synthora Update:**\n\n{txt}", parse_mode="Markdown")

@bot.message_handler(commands=['withdraw'])
def withdraw(message):
    if not is_admin(message): return
    try:
        to_addr = w3.to_checksum_address(message.text.split()[1])
        bal = w3.eth.get_balance(wallet_address)
        gas = 21000 * w3.eth.gas_price
        
        tx = {
            'nonce': w3.eth.get_transaction_count(wallet_address),
            'to': to_addr,
            'value': bal - (gas * 2),
            'gas': 21000,
            'gasPrice': w3.eth.gas_price,
            'chainId': 8453
        }
        signed = w3.eth.account.sign_transaction(tx, PRIVATE_KEY)
        hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        bot.reply_to(message, f"💸 Verzonden! Hash: `{hash.hex()}`")
    except Exception as e: bot.reply_to(message, f"❌ Fout: {e}")

# ============================================================================
# 5. STARTUP
# ============================================================================
if __name__ == "__main__":
    logger.info(f"✅ Bot gestart op {wallet_address}")
    if TELEGRAM_BROADCAST_CHANNEL:
        try: bot.send_message(TELEGRAM_BROADCAST_CHANNEL, "🚀 **Synthora Elite is ONLINE.** Bescherming en DEX-scanner actief.")
        except: pass
    bot.infinity_polling()
    
