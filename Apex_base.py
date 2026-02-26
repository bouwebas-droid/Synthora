import os
import time
import threading
import requests
from web3 import Web3
import telebot

# ============================================================================
# 1. ELITE CONFIG MET JOUW SPECIFIEKE KEY
# ============================================================================
ALCHEMY_KEY = os.getenv("ALCHEMY_API_KEY", "").strip()
# Hier gebruiken we nu jouw specifieke naam:
SESSION_KEY = os.getenv("ARCHITECT_SESSION_KEY", "").strip() 
BOT_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
ADMIN_ID    = os.getenv("TELEGRAM_ADMIN_ID", "").strip()

print("--- [ARCHITECT SYSTEM CHECK] ---")
print(f"Blockchain Bridge: {'✅' if ALCHEMY_KEY else '❌'}")
print(f"Vault Access:      {'✅' if SESSION_KEY else '❌'}")
print(f"Telegram Link:     {'✅' if BOT_TOKEN else '❌'}")
print("--------------------------------")

if not all([ALCHEMY_KEY, SESSION_KEY, BOT_TOKEN]):
    print("❌ FATAL: Verplichte variabelen ontbreken. Controleer ARCHITECT_SESSION_KEY in Render!")
    os._exit(1)

# ============================================================================
# 2. BLOCKCHAIN & SNIPER SETUP
# ============================================================================
w3 = Web3(Web3.HTTPProvider(f"https://base-mainnet.g.alchemy.com/v2/{ALCHEMY_KEY}"))
bot = telebot.TeleBot(BOT_TOKEN)

try:
    # We gebruiken de session key om de wallet te laden
    account = w3.eth.account.from_key(SESSION_KEY)
    wallet_address = account.address
except Exception as e:
    print(f"❌ Wallet Error: {e}")
    os._exit(1)

# Sniper Doelen
AERODROME_FACTORY = "0x420DD3807E0e1379f6a1611709d7085d8883C117"

def is_admin(m):
    return str(m.from_user.id) == str(ADMIN_ID)

# ============================================================================
# 3. ELITE COMMANDS (SNIPER, STATUS, WITHDRAW)
# ============================================================================
@bot.message_handler(commands=['status'])
def cmd_status(m):
    if not is_admin(m): return
    bal = w3.from_wei(w3.eth.get_balance(wallet_address), 'ether')
    msg = f"🛡️ **Synthora Elite Online**\n\n💰 Balans: `{bal:.4f} ETH`\n🏛️ Wallet: `{wallet_address}`"
    bot.reply_to(m, msg, parse_mode="Markdown")

@bot.message_handler(commands=['check'])
def cmd_check(m):
    if not is_admin(m): return
    try:
        addr = m.text.split()[-1]
        r = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{addr}").json()
        if not r.get('pairs'):
            bot.reply_to(m, "📊 Geen DEX data gevonden.")
            return
        data = max(r['pairs'], key=lambda x: x.get('liquidity', {}).get('usd', 0))
        report = f"📊 **{data['baseToken']['symbol']}**\nLiq: `${data['liquidity']['usd']:,.0f}`\nMCAP: `${data.get('fdv', 0):,.0f}`"
        bot.reply_to(m, report, parse_mode="Markdown")
    except: bot.reply_to(m, "Gebruik: `/check [adres]`")

@bot.message_handler(commands=['withdraw'])
def cmd_withdraw(m):
    if not is_admin(m): return
    try:
        to_addr = w3.to_checksum_address(m.text.split()[1])
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
        signed = w3.eth.account.sign_transaction(tx, SESSION_KEY)
        h = w3.eth.send_raw_transaction(signed.raw_transaction)
        bot.reply_to(m, f"💸 **Funds Veiliggesteld!**\nHash: `{h.hex()}`")
    except Exception as e: bot.reply_to(m, f"❌ Fout: {e}")

# ============================================================================
# 4. MONITORING LOOP
# ============================================================================
def monitor():
    last_block = w3.eth.block_number
    while True:
        try:
            curr = w3.eth.block_number
            if curr > last_block:
                block = w3.eth.get_block(curr, full_transactions=True)
                for tx in block.transactions:
                    if tx['to'] == AERODROME_FACTORY:
                        bot.send_message(ADMIN_ID, "🎯 **SNIPER ALERT:** Nieuwe Aerodrome pool gedetecteerd!")
                last_block = curr
            time.sleep(2)
        except: time.sleep(5)

if __name__ == "__main__":
    threading.Thread(target=monitor, daemon=True).start()
    print(f"✅ Elite Sniper actief op: {wallet_address}")
    bot.infinity_polling()
    
