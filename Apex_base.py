import os
import time
import threading
import requests
from web3 import Web3
from collections import defaultdict
import telebot

# ============================================================================
# 1. ARCHITECT CONFIGURATIE (RENDER STRIP)
# ============================================================================
ALCHEMY_KEY = os.getenv("ALCHEMY_API_KEY", "").strip()
SESSION_KEY = os.getenv("ARCHITECT_SESSION_KEY", "").strip() 
BOT_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
ADMIN_ID    = os.getenv("TELEGRAM_ADMIN_ID", "").strip()
CHANNEL_ID  = os.getenv("TELEGRAM_BROADCAST_CHANNEL", "").strip()

if not all([ALCHEMY_KEY, SESSION_KEY, BOT_TOKEN]):
    print("❌ FATAL: Verplichte variabelen missen in Render!")
    os._exit(1)

# ============================================================================
# 2. BLOCKCHAIN & WALLET SETUP
# ============================================================================
w3 = Web3(Web3.HTTPProvider(f"https://base-mainnet.g.alchemy.com/v2/{ALCHEMY_KEY}"))
bot = telebot.TeleBot(BOT_TOKEN)

try:
    account = w3.eth.account.from_key(SESSION_KEY)
    wallet_address = account.address
except Exception as e:
    print(f"❌ Wallet Error: {e}")
    os._exit(1)

# Sniper & Market Targets
AERODROME_FACTORY = "0x420DD3807E0e1379f6a1611709d7085d8883C117"
WHALE_LIST = {} # Format: {"0xAddress": "Whale Name"}

def is_admin(m):
    return str(m.from_user.id) == str(ADMIN_ID)

# ============================================================================
# 3. THE ELITE MULTI-ENGINE (SNIPER + WHALE MONITOR)
# ============================================================================
def master_engine():
    """Scant elk blok op Base voor nieuwe pools EN whale acties"""
    last_block = w3.eth.block_number
    print(f"🎯 Master Engine gestart op blok {last_block}")
    
    while True:
        try:
            curr = w3.eth.block_number
            if curr > last_block:
                for bn in range(last_block + 1, curr + 1):
                    block = w3.eth.get_block(bn, full_transactions=True)
                    for tx in block.transactions:
                        # --- SNIPER DEEL ---
                        if tx.get('to') == AERODROME_FACTORY:
                            bot.send_message(ADMIN_ID, "🎯 **SNIPER ALERT:** Nieuwe pool op Aerodrome!")
                        
                        # --- WHALE MONITOR DEEL ---
                        sender = tx.get('from')
                        if sender in WHALE_LIST:
                            name = WHALE_LIST[sender]
                            msg = f"🐋 **WHALE ALERT: {name}**\nActie gedetecteerd op Base!\nHash: `https://basescan.org/tx/{tx['hash'].hex()}`"
                            bot.send_message(ADMIN_ID, msg, parse_mode="Markdown")
                            if CHANNEL_ID:
                                try: bot.send_message(CHANNEL_ID, f"📣 **Whale Monitor:** {name} is in beweging!")
                                except: pass
                                
                last_block = curr
            time.sleep(2)
        except Exception as e:
            print(f"Engine lag: {e}")
            time.sleep(5)

# ============================================================================
# 4. COMMANDS (INCLUSIEF WHALE MANAGEMENT)
# ============================================================================

@bot.message_handler(commands=['add_whale'])
def add_whale(m):
    if not is_admin(m): return
    try:
        parts = m.text.split()
        addr = w3.to_checksum_address(parts[1])
        name = parts[2] if len(parts) > 2 else "Unnamed Whale"
        WHALE_LIST[addr] = name
        bot.reply_to(m, f"✅ Whale toegevoegd:\n`{addr}` ({name})", parse_mode="Markdown")
    except:
        bot.reply_to(m, "⚠️ Gebruik: `/add_whale <adres> <naam>`")

@bot.message_handler(commands=['status'])
def cmd_status(m):
    if not is_admin(m): return
    bal = w3.from_wei(w3.eth.get_balance(wallet_address), 'ether')
    msg = (f"🛡️ **Synthora Elite Pro**\n\n"
           f"💰 Balans: `{bal:.4f} ETH`\n"
           f"🐋 Gemonitorde Whales: `{len(WHALE_LIST)}`\n"
           f"📦 Laatste blok: `{w3.eth.block_number}`")
    bot.reply_to(m, msg, parse_mode="Markdown")

@bot.message_handler(commands=['check'])
def cmd_check(m):
    if not is_admin(m): return
    try:
        addr = m.text.split()[-1]
        r = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{addr}").json()
        data = max(r['pairs'], key=lambda x: x.get('liquidity', {}).get('usd', 0))
        report = f"📊 **{data['baseToken']['symbol']}**\n💧 Liq: `${data['liquidity']['usd']:,.0f}`\n💎 MCAP: `${data.get('fdv', 0):,.0f}`"
        bot.reply_to(m, report, parse_mode="Markdown")
    except: bot.reply_to(m, "Gebruik: `/check <adres>`")

@bot.message_handler(commands=['broadcast'])
def cmd_broadcast(m):
    if not is_admin(m): return
    txt = m.text.replace('/broadcast ', '')
    if CHANNEL_ID:
        bot.send_message(CHANNEL_ID, f"📣 **Synthora Update:**\n\n{txt}", parse_mode="Markdown")

@bot.message_handler(commands=['withdraw'])
def cmd_withdraw(m):
    if not is_admin(m): return
    try:
        to_addr = w3.to_checksum_address(m.text.split()[1])
        bal = w3.eth.get_balance(wallet_address)
        gas = 21000 * w3.eth.gas_price
        tx = {'nonce': w3.eth.get_transaction_count(wallet_address), 'to': to_addr, 'value': bal - (gas * 2), 'gas': 21000, 'gasPrice': w3.eth.gas_price, 'chainId': 8453}
        signed = w3.eth.account.sign_transaction(tx, SESSION_KEY)
        h = w3.eth.send_raw_transaction(signed.raw_transaction)
        bot.reply_to(m, f"💸 **Funds verzonden naar:**\n`{to_addr}`")
    except Exception as e: bot.reply_to(m, f"❌ Fout: {e}")

# ============================================================================
# 5. EXECUTION
# ============================================================================
if __name__ == "__main__":
    threading.Thread(target=master_engine, daemon=True).start()
    print(f"✅ Synthora Elite gestart op: {wallet_address}")
    if CHANNEL_ID:
        try: bot.send_message(CHANNEL_ID, "🚀 **Synthora Elite Sniper & Whale Monitor is LIVE.**")
        except: pass
    bot.infinity_polling()
    
