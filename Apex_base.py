import os
import time
import threading
import requests
import logging
from web3 import Web3
import telebot

# Probeer OpenAI te laden, maar voorkom crash als de module nog mist tijdens testen
try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

# ============================================================================
# 1. CORE CONFIG & SECURITY
# ============================================================================
ALCHEMY_KEY = os.getenv("ALCHEMY_API_KEY", "").strip()
SESSION_KEY = os.getenv("ARCHITECT_SESSION_KEY", "").strip() 
BOT_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
ADMIN_ID    = os.getenv("TELEGRAM_ADMIN_ID", "").strip()
CHANNEL_ID  = os.getenv("TELEGRAM_BROADCAST_CHANNEL", "").strip()
AI_KEY      = os.getenv("OPENAI_API_KEY", "").strip()

# Sniper & Safety Config
config = {
    "snipe_amount": 0.002, 
    "take_profit": 2.0,    # 2x winst
    "stop_loss": 0.9,      # -10% verlies (strakke beveiliging)
    "auto_snipe": False,
    "active_positions": {} 
}

# Logger setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SynthoraElite")

# Web3 Setup
w3 = Web3(Web3.HTTPProvider(f"https://base-mainnet.g.alchemy.com/v2/{ALCHEMY_KEY}"))
bot = telebot.TeleBot(BOT_TOKEN)
client = OpenAI(api_key=AI_KEY) if (OpenAI and AI_KEY) else None

try:
    account = w3.eth.account.from_key(SESSION_KEY)
    wallet_address = account.address
except Exception as e:
    logger.error(f"Vault Error: {e}")
    os._exit(1)

def is_admin(m):
    return str(m.from_user.id) == str(ADMIN_ID)

# ============================================================================
# 2. AI INTERACTION (OPENAI)
# ============================================================================
def get_ai_response(user_text):
    if not client: return "⚠️ OpenAI API niet actief of module mist in build."
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "Je bent de Synthora AI Agent, een elite blockchain architect. Wees kort, technisch en loyaal."},
                {"role": "user", "content": user_text}
            ]
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"❌ AI Error: {str(e)}"

# ============================================================================
# 3. COMMANDS & CHAT
# ============================================================================
@bot.message_handler(commands=['status'])
def cmd_status(m):
    if not is_admin(m): return
    bal = w3.from_wei(w3.eth.get_balance(wallet_address), 'ether')
    msg = f"🏙️ **Synthora Elite V12**\n\n💰 Balans: `{bal:.4f} ETH`"
    bot.reply_to(m, msg, parse_mode="Markdown")

@bot.message_handler(func=lambda m: True)
def handle_all_messages(m):
    if not is_admin(m): return
    if m.text.startswith('/'): return
    
    bot.send_chat_action(m.chat.id, 'typing')
    ai_reply = get_ai_response(m.text)
    bot.reply_to(m, ai_reply)

# ============================================================================
# 4. LAUNCH
# ============================================================================
if __name__ == "__main__":
    bot.remove_webhook()
    time.sleep(1)
    logger.info(f"✅ Synthora Elite + OpenAI gestart op {wallet_address}")
    
    while True:
        try:
            bot.polling(none_stop=True, interval=0, timeout=20)
        except:
            time.sleep(5)
            
