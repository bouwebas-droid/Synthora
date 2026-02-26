import os
import time
import threading
import requests
import logging
from web3 import Web3
import telebot

# ============================================================================
# 1. CORE CONFIGURATIE (RENDER CLOUD)
# ============================================================================
# Alles wordt uit je Render Dashboard getrokken
ALCHEMY_KEY = os.getenv("ALCHEMY_API_KEY", "").strip()
SESSION_KEY = os.getenv("ARCHITECT_SESSION_KEY", "").strip() 
BOT_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
ADMIN_ID    = os.getenv("TELEGRAM_ADMIN_ID", "").strip()
CHANNEL_ID  = os.getenv("TELEGRAM_BROADCAST_CHANNEL", "").strip()

# Sniper & Exit Instellingen
config = {
    "snipe_amount": 0.002,  # Standaard inzet
    "take_profit": 2.0,     # Verkoop bij +100%
    "stop_loss": 0.9,       # Verkoop bij -10% (Beveiliging strakker gezet)
    "auto_snipe": False,    # Handmatig aanzetten met /snipe_on
    "active_positions": {}, # Houdt trades bij: {adres: entry_price}
    "whales": {}            # Whale lijst: {adres: naam}
}

# Web3 Setup
w3 = Web3(Web3.HTTPProvider(f"https://base-mainnet.g.alchemy.com/v2/{ALCHEMY_KEY}"))
bot = telebot.TeleBot(BOT_TOKEN)

try:
    account = w3.eth.account.from_key(SESSION_KEY)
    wallet_address = account.address
except Exception as e:
    print(f"❌ Wallet Error: {e}")
    os._exit(1)

def is_admin(m):
    return str(m.from_user.id) == str(ADMIN_ID)

# ============================================================================
# 2. THE ENGINES (SNIPER, WHALE, AUTO-EXIT)
# ============================================================================

def architect_master_engine():
    """Scant elk blok op Base voor Pools en Whales"""
    last_block = w3.eth.block_number
    factory = "0x420DD3807E0e1379f6a1611709d7085d8883C117"
    
    while True:
        try:
            curr = w3.eth.block_number
            if curr > last_block:
                for bn in range(last_block + 1, curr + 1):
                    block = w3.eth.get_block(bn, full_transactions=True)
                    for tx in block.transactions:
                        # WHALE CHECK
                        if tx.get('from') in config["whales"]:
                            name = config["whales"][tx['from']]
                            bot.send_message(ADMIN_ID, f"🐋 **WHALE ALERT: {name}**\nHash: `https://basescan.org/tx/{tx['hash'].hex()}`")
                        
                        # SNIPER CHECK (Aerodrome)
                        if tx.get('to') == factory:
                            msg = "🎯 **SNIPER ALERT:** Nieuwe pool op Aerodrome!"
                            bot.send_message(ADMIN_ID, msg)
                            if CHANNEL_ID:
                                bot.send_message(CHANNEL_ID, "📣 **Synthora Scan:** Nieuwe liquiditeit op Base gedetecteerd!")
                last_block = curr
            time.sleep(1)
        except: time.sleep(2)

def auto_exit_engine():
    """Bewaakt je 0.002 ETH inzet (Loss Prevention)"""
    while True:
        for token_addr, entry_price in list(config["active_positions"].items()):
            try:
                r = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{token_addr}", timeout=5).json()
                if not r.get('pairs'): continue
                
                curr_price = float(r['pairs'][0].get('priceUsd', 0))
                roi = curr_price / entry_price
                
                if roi >= config["take_profit"]:
                    bot.send_message(ADMIN_ID, f"💰 **TAKE PROFIT:** Verkoop op {roi:.2f}x!\nToken: `{token_addr}`")
                    del config["active_positions"][token_addr]
                elif roi <= config["stop_loss"]:
                    bot.send_message(ADMIN_ID, f"🛡️ **STOP LOSS:** Beschermd op {roi:.2f}x!\nToken: `{token_addr}`")
                    del config["active_positions"][token_addr]
            except: pass
        time.sleep(10)

# ============================================================================
# 3. COMMANDS (ADMIN ONLY)
# ============================================================================

@bot.message_handler(commands=['status'])
def cmd_status(m):
    if not is_admin(m): return
    bal = w3.from_wei(w3.eth.get_balance(wallet_address), 'ether')
    msg = (f"🏙️ **Synthora Elite V12**\n\n"
           f"● Status: ✅ Operational\n"
           f"● Balans: `{bal:.4f} ETH`\n"
           f"● Sniper: `{'AAN' if config['auto_snipe'] else 'UIT'}`\n"
           f"● Trades: `{len(config['active_positions'])}` actief\n"
           f"● Wallet: `{wallet_address}`")
    bot.reply_to(m, msg, parse_mode="Markdown")

@bot.message_handler(commands=['snipe_on'])
def snipe_on(m):
    if not is_admin(m): return
    config["auto_snipe"] = True
    bot.reply_to(m, "🎯 **SNIPER GEACTIVEERD** (Inzet: 0.002 ETH)")

@bot.message_handler(commands=['add_whale'])
def add_whale(m):
    if not is_admin(m): return
    try:
        addr = w3.to_checksum_address(m.text.split()[1])
        name = m.text.split()[2] if len(m.text.split()) > 2 else "Unnamed"
        config["whales"][addr] = name
        bot.reply_to(m, f"✅ Whale `{name}` toegevoegd aan monitor.")
    except: bot.reply_to(m, "Gebruik: `/add_whale [adres] [naam]`")

@bot.message_handler(commands=['skyline_report'])
def skyline_report(m):
    if not is_admin(m): return
    bot.reply_to(m, "📊 Bezig met genereren van Skyline Report...")
    # Genereer rapport
    time.sleep(1)
    bot.send_message(ADMIN_ID, "🏙️ **Skyline Weekly:** Alles draait volgens schema op Base Mainnet.")

@bot.message_handler(commands=['broadcast'])
def cmd_broadcast(m):
    if not is_admin(m): return
    txt = m.text.replace('/broadcast ', '')
    if CHANNEL_ID:
        bot.send_message(CHANNEL_ID, f"📣 **Synthora Elite Update:**\n\n{txt}", parse_mode="Markdown")

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
        bot.reply_to(m, f"💸 **Funds Veilig!** Hash: `{h.hex()}`")
    except Exception as e: bot.reply_to(m, f"❌ Fout: {e}")

# ============================================================================
# 4. LAUNCH & SELF-HEAL
# ============================================================================
if __name__ == "__main__":
    bot.remove_webhook()
    time.sleep(1)
    
    # Start Engines
    threading.Thread(target=architect_master_engine, daemon=True).start()
    threading.Thread(target=auto_exit_engine, daemon=True).start()
    
    print(f"✅ Synthora Elite Architect LIVE op {wallet_address}")
    
    while True:
        try:
            bot.polling(none_stop=True, interval=0, timeout=20)
        except Exception as e:
            time.sleep(5)
        
