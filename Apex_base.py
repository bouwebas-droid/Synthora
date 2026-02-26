import os
import time
import threading
import requests
import logging
from web3 import Web3
import telebot
from openai import OpenAI

# ============================================================================
# 1. CORE CONFIG & OPENAI LINK
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

w3 = Web3(Web3.HTTPProvider(f"https://base-mainnet.g.alchemy.com/v2/{ALCHEMY_KEY}"))
bot = telebot.TeleBot(BOT_TOKEN)
client = OpenAI(api_key=AI_KEY) if AI_KEY else None

try:
    account = w3.eth.account.from_key(SESSION_KEY)
    wallet_address = account.address
except Exception as e:
    os._exit(1)

def is_admin(m):
    return str(m.from_user.id) == str(ADMIN_ID)

# ============================================================================
# 2. AI INTERACTION ENGINE (OPENAI)
# ============================================================================
def get_ai_response(user_text):
    """Laat OpenAI reageren als de Architect"""
    if not client: return "⚠️ OpenAI API Key niet ingesteld in Render."
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "Je bent de Synthora AI Agent, een elite blockchain architect voor project Chillzilla. Je bent serieus, technisch en loyaal aan de eigenaar."},
                {"role": "user", "content": user_text}
            ]
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"❌ AI Error: {str(e)}"

# ============================================================================
# 3. ENGINES (SNIPER & AUTO-EXIT)
# ============================================================================
def sniper_loop():
    last_block = w3.eth.block_number
    factory_addr = "0x420DD3807E0e1379f6a1611709d7085d8883C117"
    while True:
        try:
            curr = w3.eth.block_number
            if curr > last_block:
                block = w3.eth.get_block(curr, full_transactions=True)
                for tx in block.transactions:
                    if tx.get('to') == factory_addr:
                        bot.send_message(ADMIN_ID, "🎯 **POOL DETECTED** op Aerodrome!")
                        if CHANNEL_ID:
                            bot.send_message(CHANNEL_ID, "📣 **Synthora Scan:** Nieuwe pool gevonden op Base!")
                last_block = curr
            time.sleep(1)
        except: time.sleep(2)

# ============================================================================
# 4. COMMANDS & AI CHAT
# ============================================================================
@bot.message_handler(commands=['status'])
def cmd_status(m):
    if not is_admin(m): return
    bal = w3.from_wei(w3.eth.get_balance(wallet_address), 'ether')
    msg = f"🏙️ **Synthora Elite V12**\n\n💰 Balans: `{bal:.4f} ETH`\n🛡️ Sniper: {'🟢 AAN' if config['auto_snipe'] else '🔴 UIT'}"
    bot.reply_to(m, msg, parse_mode="Markdown")

@bot.message_handler(func=lambda m: True)
def handle_all_messages(m):
    """Reageert op commando's OF gebruikt OpenAI voor normale tekst"""
    if not is_admin(m): return
    
    if m.text.startswith('/'):
        # Hier kun je andere commando's toevoegen
        return 

    # Geen commando? Gebruik OpenAI
    bot.send_chat_action(m.chat.id, 'typing')
    ai_reply = get_ai_response(m.text)
    bot.reply_to(m, ai_reply)

# ============================================================================
# 5. LAUNCH & SELF-HEAL
# ============================================================================
if __name__ == "__main__":
    bot.remove_webhook()
    time.sleep(1)
    
    threading.Thread(target=sniper_loop, daemon=True).start()
    
    print(f"✅ Synthora Elite + OpenAI Live op {wallet_address}")
    
    while True:
        try:
            bot.polling(none_stop=True, interval=0, timeout=20)
        except:
            time.sleep(5)
            
