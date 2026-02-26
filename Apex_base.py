import os
import time
import logging
import threading
import requests
from web3 import Web3
import telebot

# ============================================================================
# DEBUGGING & CONFIG (DEEL 1)
# ============================================================================
# We laden ze in en strippen onzichtbare tekens
A_KEY = os.getenv("ALCHEMY_API_KEY", "").strip()
P_KEY = os.getenv("PRIVATE_KEY", "").strip()
T_BOT = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
T_ADM = os.getenv("TELEGRAM_ADMIN_ID", "").strip()
T_CHN = os.getenv("TELEGRAM_BROADCAST_CHANNEL", "").strip()

# Laat in de logs zien wat er mist (ZONDER de waarde te printen voor veiligheid)
print("--- ENVIRONMENT CHECK ---")
print(f"ALCHEMY_API_KEY gevonden: {bool(A_KEY)}")
print(f"PRIVATE_KEY gevonden: {bool(P_KEY)}")
print(f"TELEGRAM_BOT_TOKEN gevonden: {bool(T_BOT)}")
print(f"TELEGRAM_ADMIN_ID gevonden: {bool(T_ADM)}")
print("-------------------------")

if not all([A_KEY, P_KEY, T_BOT]):
    missing = []
    if not A_KEY: missing.append("ALCHEMY_API_KEY")
    if not P_KEY: missing.append("PRIVATE_KEY")
    if not T_BOT: missing.append("TELEGRAM_BOT_TOKEN")
    print(f"❌ STOP: De volgende variabelen ontbreken in Render: {', '.join(missing)}")
    exit(1)

# ============================================================================
# DE REST VAN HET SCRIPT (DEEL 2)
# ============================================================================
BASE_RPC = f"https://base-mainnet.g.alchemy.com/v2/{A_KEY}"
w3 = Web3(Web3.HTTPProvider(BASE_RPC))

try:
    account = w3.eth.account.from_key(P_KEY)
    wallet_address = account.address
except Exception as e:
    print(f"❌ Wallet fout: {e}")
    exit(1)

bot = telebot.TeleBot(T_BOT)

def is_admin(message):
    return str(message.from_user.id) == str(T_ADM)

@bot.message_handler(commands=['status'])
def status(message):
    if not is_admin(message): return
    bal = w3.from_wei(w3.eth.get_balance(wallet_address), 'ether')
    bot.reply_to(message, f"🟢 **Synthora Online**\nWallet: `{wallet_address}`\nBalans: `{bal:.4f} ETH`", parse_mode="Markdown")

@bot.message_handler(commands=['withdraw'])
def withdraw(message):
    if not is_admin(message): return
    try:
        parts = message.text.split()
        to_addr = w3.to_checksum_address(parts[1])
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
        signed = w3.eth.account.sign_transaction(tx, P_KEY)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        bot.reply_to(message, f"💸 Withdraw verzonden!\nHash: `{tx_hash.hex()}`")
    except Exception as e:
        bot.reply_to(message, f"❌ Fout: {e}")

if __name__ == "__main__":
    print(f"✅ Bot start op adres: {wallet_address}")
    if T_CHN:
        try: bot.send_message(T_CHN, "🚀 **Synthora Elite is ONLINE.**")
        except: pass
    bot.infinity_polling()
    
