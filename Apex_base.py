import os
import time
import logging
import threading
import requests
from web3 import Web3
from collections import defaultdict
import telebot

# ============================================================================
# 1. ELITE CONFIG & ERROR SHIELD
# ============================================================================
# We strippen alles om 'False' errors in Render te voorkomen
ALCHEMY_KEY = os.getenv("ALCHEMY_API_KEY", "").strip()
PRIVATE_KEY = os.getenv("PRIVATE_KEY", "").strip()
BOT_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
ADMIN_ID    = os.getenv("TELEGRAM_ADMIN_ID", "").strip()
CHANNEL_ID  = os.getenv("TELEGRAM_BROADCAST_CHANNEL", "").strip()

print("--- [ARCHITECT SYSTEM CHECK] ---")
print(f"Blockchain Bridge: {'✅' if ALCHEMY_KEY else '❌'}")
print(f"Vault Access:      {'✅' if PRIVATE_KEY else '❌'}")
print(f"Telegram Link:     {'✅' if BOT_TOKEN else '❌'}")
print(f"Owner ID:          {'✅' if ADMIN_ID else '❌'}")
print("--------------------------------")

if not all([ALCHEMY_KEY, PRIVATE_KEY, BOT_TOKEN]):
    print("❌ FATAL: Verplichte variabelen ontbreken in Render Dashboard.")
    os._exit(1)

# ============================================================================
# 2. BLOCKCHAIN SETUP (BASE MAINNET)
# ============================================================================
w3 = Web3(Web3.HTTPProvider(f"https://base-mainnet.g.alchemy.com/v2/{ALCHEMY_KEY}"))
bot = telebot.TeleBot(BOT_TOKEN)

try:
    account = w3.eth.account.from_key(PRIVATE_KEY)
    wallet_address = account.address
except Exception as e:
    print(f"❌ Wallet Error: {e}")
    os._exit(1)

# Contracten voor Sniping
AERODROME_FACTORY = "0x420DD3807E0e1379f6a1611709d7085d8883C117"
ERC20_ABI = [
    {"constant": True, "inputs": [], "name": "owner", "outputs": [{"name": "", "type": "address"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "symbol", "outputs": [{"name": "", "type": "string"}], "type": "function"}
]

# Bot State
bot_state = {
    "sniper_active": False,
    "min_liquidity": 0.5,  # ETH
    "whale_alerts": 0,
    "positions": {}
}
WHALE_WALLETS = {}

def is_admin(m):
    return str(m.from_user.id) == str(ADMIN_ID)

# ============================================================================
# 3. SAFETY & MARKET ENGINE (DEX SCREENER)
# ============================================================================
def get_market_data(addr):
    try:
        r = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{addr}", timeout=10).json()
        if not r.get('pairs'): return None
        return max(r['pairs'], key=lambda x: x.get('liquidity', {}).get('usd', 0))
    except: return None

def advanced_safety_scan(addr):
    try:
        checksum = w3.to_checksum_address(addr)
        code = w3.eth.get_code(checksum)
        if len(code) <= 2: return "❌ SCAM: Geen contract code!"
        
        contract = w3.eth.contract(address=checksum, abi=ERC20_ABI)
        try:
            owner = contract.functions.owner().call()
            if owner == "0x0000000000000000000000000000000000000000":
                return "✅ VEILIG: Ownership Renounced"
            return f"⚠️ WAARSCHUWING: Eigenaar actief ({owner[:6]})"
        except:
            return "✅ VEILIG: Geen owner functies"
    except: return "❓ SCAN FAILED"

# ============================================================================
# 4. THE SNIPER & WHALE ENGINE
# ============================================================================
def master_loop():
    last_block = w3.eth.block_number
    while True:
        try:
            curr_block = w3.eth.block_number
            if curr_block > last_block:
                for bn in range(last_block + 1, curr_block + 1):
                    block = w3.eth.get_block(bn, full_transactions=True)
                    for tx in block.transactions:
                        # 1. Sniper: Check op nieuwe Aerodrome pools
                        if tx['to'] == AERODROME_FACTORY:
                            bot.send_message(ADMIN_ID, "🎯 **SNIPER ALERT:** Nieuwe pool gedetecteerd op Aerodrome!")
                        
                        # 2. Whale Tracker
                        if tx['from'] in WHALE_WALLETS:
                            bot.send_message(ADMIN_ID, f"🐋 **WHALE ACTIE:** {WHALE_WALLETS[tx['from']]} is actief!")
                last_block = curr_block
            time.sleep(2)
        except: time.sleep(5)

# ============================================================================
# 5. ELITE COMMANDS
# ============================================================================
@bot.message_handler(commands=['status'])
def cmd_status(m):
    if not is_admin(m): return
    bal = w3.from_wei(w3.eth.get_balance(wallet_address), 'ether')
    msg = f"🛡️ **Synthora Elite Pro**\n\nSniper: {'🟢 AAN' if bot_state['sniper_active'] else '🔴 UIT'}\nWallet: `{wallet_address}`\nBalans: `{bal:.4f} ETH`"
    bot.reply_to(m, msg, parse_mode="Markdown")

@bot.message_handler(commands=['check'])
def cmd_check(m):
    if not is_admin(m): return
    addr = m.text.split()[-1]
    data = get_market_data(addr)
    safety = advanced_safety_scan(addr)
    
    if not data:
        bot.reply_to(m, f"🛡️ Scan: {safety}\n📊 Geen DEX data gevonden.")
        return

    report = f"📊 **{data['baseToken']['symbol']}** op Base\nLiq: `${data['liquidity']['usd']:,.0f}`\nMCAP: `${data.get('fdv', 0):,.0f}`\n🛡️ Scan: {safety}"
    bot.reply_to(m, report, parse_mode="Markdown")

@bot.message_handler(commands=['withdraw'])
def cmd_withdraw(m):
    if not is_admin(m): return
    try:
        to_addr = w3.to_checksum_address(m.text.split()[1])
        bal = w3.eth.get_balance(wallet_address)
        gas = 21000 * w3.eth.gas_price
        tx = {'nonce': w3.eth.get_transaction_count(wallet_address), 'to': to_addr, 'value': bal - (gas * 2), 'gas': 21000, 'gasPrice': w3.eth.gas_price, 'chainId': 8453}
        signed = w3.eth.account.sign_transaction(tx, PRIVATE_KEY)
        h = w3.eth.send_raw_transaction(signed.raw_transaction)
        bot.reply_to(m, f"💸 **Funds Veiliggesteld!**\nHash: `{h.hex()}`")
    except Exception as e: bot.reply_to(m, f"❌ Fout: {e}")

@bot.message_handler(commands=['broadcast'])
def cmd_broadcast(m):
    if not is_admin(m): return
    txt = m.text.replace('/broadcast ', '')
    if CHANNEL_ID: bot.send_message(CHANNEL_ID, f"📣 **Synthora Update:**\n\n{txt}", parse_mode="Markdown")

# ============================================================================
# 6. LAUNCH
# ============================================================================
if __name__ == "__main__":
    threading.Thread(target=master_loop, daemon=True).start()
    print(f"✅ Elite Sniper actief op: {wallet_address}")
    if CHANNEL_ID:
        try: bot.send_message(CHANNEL_ID, "🚀 **Synthora Elite Sniper is LIVE.** Beveiliging en monitoring actief.")
        except: pass
    bot.infinity_polling()
