import os
import time
import threading
import requests
import logging
from web3 import Web3
import telebot
from openai import OpenAI

# ============================================================================
# 1. EXACTE MATCH MET JOUW RENDER DASHBOARD
# ============================================================================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SynthoraElite")

# We gebruiken hier de namen uit jouw screenshot
ALCHEMY_KEY = os.getenv("ALCHEMY_API_KEY", "").strip()
SESSION_KEY = os.getenv("OWNER_SECRET_KEY", "").strip()  # Aangepast naar jouw screenshot
BOT_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
ADMIN_ID    = os.getenv("OWNER_ID", "").strip()          # Aangepast naar jouw screenshot
AI_KEY      = os.getenv("OPENAI_API_KEY", "").strip()
CHANNEL_ID  = os.getenv("TELEGRAM_BROADCAST_CHANNEL", "").strip()

# Config parameters uit jouw dashboard
config = {
    "snipe_amount": 0.002,
    "take_profit": float(os.getenv("TAKE_PROFIT_V", 2.0)),
    "stop_loss": 0.9,
    "auto_snipe": False,
    "active_positions": {}
}

w3 = Web3(Web3.HTTPProvider(f"https://base-mainnet.g.alchemy.com/v2/{ALCHEMY_KEY}"))
bot = telebot.TeleBot(BOT_TOKEN)
ai_client = OpenAI(api_key=AI_KEY) if AI_KEY else None

try:
    account = w3.eth.account.from_key(SESSION_KEY)
    wallet_address = account.address
except Exception as e:
    logger.error(f"❌ Koppelingsfout: Check je OWNER_SECRET_KEY")
    os._exit(1)

def is_admin(m):
    return str(m.from_user.id) == str(ADMIN_ID)

# ============================================================================
# 2. AI BREIN & KANAAL VERBINDING
# ============================================================================
def get_ai_response(user_text):
    if not ai_client: return "AI-module niet gekoppeld."
    try:
        response = ai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "Je bent de Synthora AI Architect voor Chillzilla. Je bent loyaal en technisch."},
                {"role": "user", "content": user_text}
            ]
        )
        return response.choices[0].message.content
    except Exception as e: return f"AI Error: {e}"

# ============================================================================
# 3. ONVERWOESTBARE LOOP & SYSTEMEN
# ============================================================================
def sniper_engine():
    """Blijft altijd scannen op Base"""
    last_block = w3.eth.block_number
    factory = "0x420DD3807E0e1379f6a1611709d7085d8883C117"
    while True:
        try:
            curr = w3.eth.block_number
            if curr > last_block:
                block = w3.eth.get_block(curr, full_transactions=True)
                for tx in block.transactions:
                    if tx.get('to') == factory:
                        bot.send_message(ADMIN_ID, "🎯 **SNIPER:** Nieuwe pool op Aerodrome!")
                        if CHANNEL_ID:
                            bot.send_message(CHANNEL_ID, "📣 **Synthora Alert:** Nieuwe liquiditeit gevonden!")
                last_block = curr
            time.sleep(1)
        except: time.sleep(2)

@bot.message_handler(commands=['status'])
def cmd_status(m):
    if not is_admin(m): return
    bal = w3.from_wei(w3.eth.get_balance(wallet_address), 'ether')
    msg = (f"🏙️ **SYNTHORA ELITE V12**\n\n"
           f"● Status: ✅ Online\n"
           f"● Balans: `{bal:.4f} ETH`\n"
           f"● Wallet: `{wallet_address}`\n"
           f"● Sniper: 0.002 ETH")
    bot.reply_to(m, msg, parse_mode="Markdown")

@bot.message_handler(func=lambda m: True)
def handle_chat(m):
    if not is_admin(m): return
    if m.text.startswith('/'): return
    bot.send_chat_action(m.chat.id, 'typing')
    bot.reply_to(m, get_ai_response(m.text))

def run_bot():
    while True:
        try:
            bot.remove_webhook()
            logger.info("Verbinding maken...")
            bot.polling(none_stop=True, interval=0, timeout=20)
        except Exception as e:
            logger.error(f"Loop error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    threading.Thread(target=sniper_engine, daemon=True).start()
    logger.info(f"✅ Architect geladen op {wallet_address}")
    run_bot()
    
