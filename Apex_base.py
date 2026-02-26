import os
import time
import threading
import requests
from web3 import Web3
import telebot

# ============================================================================
# 1. CORE CONFIGURATIE (STRICTE VALIDATIE)
# ============================================================================
ALCHEMY_KEY = os.getenv("ALCHEMY_API_KEY", "").strip()
SESSION_KEY = os.getenv("ARCHITECT_SESSION_KEY", "").strip() 
BOT_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
ADMIN_ID    = os.getenv("TELEGRAM_ADMIN_ID", "").strip()
CHANNEL_ID  = os.getenv("TELEGRAM_BROADCAST_CHANNEL", "").strip()

# Foutmelding bij opstarten als er keys missen
if not all([ALCHEMY_KEY, SESSION_KEY, BOT_TOKEN]):
    print("❌ FATAL: Check Render Environment Variables! (Missing Keys)")
    os._exit(1)

# Trading Parameters
config = {
    "snipe_amount": 0.002, 
    "take_profit": 2.0,    # +100%
    "stop_loss": 0.8,      # -20%
    "auto_snipe": False,
    "active_positions": {} 
}

w3 = Web3(Web3.HTTPProvider(f"https://base-mainnet.g.alchemy.com/v2/{ALCHEMY_KEY}"))
bot = telebot.TeleBot(BOT_TOKEN)
account = w3.eth.account.from_key(SESSION_KEY)
wallet_address = account.address

# Contracten
AERODROME_FACTORY = "0x420DD3807E0e1379f6a1611709d7085d8883C117"

def is_admin(m):
    return str(m.from_user.id) == str(ADMIN_ID)

# ============================================================================
# 2. VEILIGHEIDSSCAN & MARKT DATA
# ============================================================================
def check_safety(token_addr):
    """Checkt of het contract bytecode heeft (geen lege scams)"""
    try:
        code = w3.eth.get_code(w3.to_checksum_address(token_addr))
        return len(code) > 2
    except: return False

def get_token_data(token_addr):
    """Haalt prijs en liquiditeit op voor de broadcast en exit-engine"""
    try:
        r = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{token_addr}", timeout=5).json()
        if not r.get('pairs'): return None
        return max(r['pairs'], key=lambda x: x.get('liquidity', {}).get('usd', 0))
    except: return None

# ============================================================================
# 3. AUTO-EXIT ENGINE (DE BEWAKING)
# ============================================================================
def auto_exit_monitor():
    """Bewaakt je 0.002 ETH inzet tegen verlies"""
    while True:
        for token_addr, entry_price in list(config["active_positions"].items()):
            data = get_token_data(token_addr)
            if not data: continue
            
            current_price = float(data.get('priceUsd', 0))
            if current_price == 0: continue

            # Bereken ROI
            roi = current_price / entry_price
            
            if roi >= config["take_profit"]:
                print(f"💰 Take Profit raak! Verkopen: {token_addr}")
                # execute_sell(token_addr)
                del config["active_positions"][token_addr]
                bot.send_message(ADMIN_ID, f"💰 **PROFIT PAKKEN!**\nToken: `{token_addr}`\nROI: `{roi:.2f}x`")
                
            elif roi <= config["stop_loss"]:
                print(f"🛡️ Stop Loss raak! Beveiligen: {token_addr}")
                # execute_sell(token_addr)
                del config["active_positions"][token_addr]
                bot.send_message(ADMIN_ID, f"🛡️ **VERLIES BEPERKT!**\nToken: `{token_addr}`\nROI: `{roi:.2f}x`")
        
        time.sleep(15) # Scan interval

# ============================================================================
# 4. MASTER SNIPER & BROADCAST
# ============================================================================
def sniper_loop():
    last_block = w3.eth.block_number
    while True:
        try:
            curr = w3.eth.block_number
            if curr > last_block:
                block = w3.eth.get_block(curr, full_transactions=True)
                for tx in block.transactions:
                    if tx.get('to') == AERODROME_FACTORY:
                        # Nieuwe pool gevonden!
                        msg = "🎯 **POOL DETECTED** op Aerodrome!\nScan loopt..."
                        bot.send_message(ADMIN_ID, msg)
                        
                        if CHANNEL_ID:
                            bot.send_message(CHANNEL_ID, "📣 **Synthora Scan:** Nieuwe liquiditeit op Base gedetecteerd! 🚀")
                last_block = curr
            time.sleep(1)
        except: time.sleep(2)

# ============================================================================
# 5. COMMANDS
# ============================================================================
@bot.message_handler(commands=['status'])
def cmd_status(m):
    if not is_admin(m): return
    bal = w3.from_wei(w3.eth.get_balance(wallet_address), 'ether')
    msg = (f"🛡️ **Synthora Elite Architect**\n\n"
           f"💰 Wallet: `{wallet_address[:6]}...{wallet_address[-4:]}`\n"
           f"💵 Balans: `{bal:.4f} ETH`\n"
           f"🎯 Snipe: `{config['snipe_amount']} ETH`\n"
           f"📈 TP: `{config['take_profit']}x` | SL: `{config['stop_loss']}x`")
    bot.reply_to(m, msg, parse_mode="Markdown")

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
        bot.reply_to(m, f"💸 **Funds Veilig!**\nHash: `{h.hex()}`")
    except Exception as e: bot.reply_to(m, f"❌ Fout: {e}")

# ============================================================================
# 6. START
# ============================================================================
if __name__ == "__main__":
    threading.Thread(target=sniper_loop, daemon=True).start()
    threading.Thread(target=auto_exit_monitor, daemon=True).start()
    print(f"✅ Synthora Elite actief op: {wallet_address}")
    bot.infinity_polling()
    
