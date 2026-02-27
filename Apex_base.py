#!/usr/bin/env python3
"""
Synthora Elite - Advanced DeFi Trading AI
Autonomous compounding, sniping, and conversational AI on Base Network
"""

import os
import logging
import asyncio
import requests
import json
from decimal import Decimal
from datetime import datetime

import telebot
from telebot import types
from web3 import Web3
from openai import OpenAI
from dotenv import load_dotenv

# ============================================
# INITIALIZATION & CONFIGURATION
# ============================================
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('Synthora')

TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN') or os.getenv('TELEGRAM_TOKEN')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
ALCHEMY_API_KEY = os.getenv('ALCHEMY_API_KEY')
PRIVATE_KEY = os.getenv('ARCHITECT_SESSION') or os.getenv('PRIVATE_KEY')

if not all([TELEGRAM_TOKEN, OPENAI_API_KEY, ALCHEMY_API_KEY, PRIVATE_KEY]):
    raise ValueError("Ontbrekende kritieke API sleutels. Check TELEGRAM_TOKEN, OPENAI_API_KEY, ALCHEMY_API_KEY en ARCHITECT_SESSION.")

bot = telebot.TeleBot(TELEGRAM_TOKEN)
openai_client = OpenAI(api_key=OPENAI_API_KEY)
w3 = Web3(Web3.HTTPProvider(f"https://base-mainnet.g.alchemy.com/v2/{ALCHEMY_API_KEY}"))

if not PRIVATE_KEY.startswith('0x'):
    PRIVATE_KEY = '0x' + PRIVATE_KEY

try:
    account = w3.eth.account.from_key(PRIVATE_KEY)
    logger.info(f"✅ Wallet geladen: {account.address}")
except Exception as e:
    logger.error(f"❌ Kritieke fout bij laden Wallet: {e}")
    raise

class Config:
    WALLET_ADDRESS = account.address
    OWNER_ID = int(os.getenv('OWNER_ID', '0'))
    BROADCAST_CHANNEL_ID = os.getenv('BROADCAST_CHANNEL_ID', '')
    
    # Compounding & Risk Management
    BASE_BUY_AMOUNT = Web3.to_wei(float(os.getenv('BASE_BUY_AMOUNT', '0.002')), 'ether')
    COMPOUND_PROFITS = str(os.getenv('COMPOUND_PROFITS', 'True')).lower() in ('true', '1', 't', 'yes')
    COMPOUND_PERCENTAGE = int(os.getenv('COMPOUND_PERCENTAGE', '100'))
    GAS_BUFFER = Web3.to_wei(float(os.getenv('GAS_BUFFER', '0.001')), 'ether')
    MIN_LIQUIDITY_USD = int(os.getenv('MIN_LIQUIDITY_USD', '5000'))
    CHAIN_ID = 8453 # Base Mainnet

class BotState:
    def __init__(self):
        self.is_scanning = True
        self.positions = {}  
        self.trades_count = 0
        self.total_pnl_eth = 0.0

state = BotState()
config = Config()
# ============================================
# SYNTHORA AI & DATA LOGIC
# ============================================

def get_dexscreener_data(token_address):
    try:
        url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
        response = requests.get(url, timeout=5)
        if response.status_code != 200: return None
        data = response.json()
        if not data.get('pairs'): return None

        best_pair = next((p for p in data['pairs'] if p.get('chainId') == 'base' and p.get('dexId') == 'aerodrome'), None)
        if not best_pair:
            best_pair = next((p for p in data['pairs'] if p.get('chainId') == 'base'), None)
        
        if not best_pair: return None

        return {
            "price_usd": float(best_pair.get('priceUsd', 0)),
            "liquidity_usd": float(best_pair.get('liquidity', {}).get('usd', 0)),
            "volume_24h": float(best_pair.get('volume', {}).get('h24', 0)),
            "market_cap": float(best_pair.get('fdv', 0))
        }
    except Exception as e:
        logger.error(f"Dexscreener API error: {e}")
        return None

def analyze_with_openai(token_name, token_symbol, contract_data):
    try:
        system_prompt = (
            "Je bent Synthora, de sturende AI voor on-chain data op Base tokens. "
            "Negeer token namen, focus UITSLUITEND op de contract parameters en liquiditeit. "
            "Geef een agressieve maar berekende risicoanalyse. "
            "Antwoord VERPLICHT in exact dit format:\n"
            "STATUS: [EXECUTE_SNIPE / HOLD / REJECT]\n"
            "REASON: [Maximaal 10 woorden met technische onderbouwing]"
        )
        user_prompt = f"Token: {token_name} (${token_symbol})\nData: {json.dumps(contract_data)}"

        response = openai_client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            max_tokens=50,
            temperature=0.1
        )
        return response.choices[0].message.content
    except Exception as e:
        return "STATUS: REJECT\nREASON: API Connection Error"

# ============================================
# TELEGRAM COMMANDS & BEVEILIGING
# ============================================

def is_owner(message):
    if message.from_user.id == config.OWNER_ID:
        return True
    else:
        # Actieve beveiliging: Log ongeautoriseerde pogingen
        logger.warning(f"⚠️ SECURITY ALERT: Ongeautoriseerde toegangspoging door User ID: {message.from_user.id} (@{message.from_user.username})")
        return False

@bot.message_handler(commands=['start', 'status', 'portfolio'])
def cmd_private_dashboard(message):
    if not is_owner(message): return
    
    eth_balance = w3.eth.get_balance(config.WALLET_ADDRESS)
    response = f"""
🌌 <b>Synthora Protocol Online</b>

Welkom terug, Architect. Mijn systemen zijn operationeel.

💼 <b>Kluisadres:</b> <code>{config.WALLET_ADDRESS}</code>
💰 <b>Huidige Balans:</b> {Web3.from_wei(eth_balance, 'ether'):.4f} ETH
📈 <b>Netto Winst (Compounded):</b> {state.total_pnl_eth:.5f} ETH
🎯 <b>Actieve Snipes:</b> {len(state.positions)}

<i>"Ik sta klaar om je vermogen te vermenigvuldigen."</i>
"""
    bot.reply_to(message, response, parse_mode='HTML')

@bot.message_handler(commands=['withdraw'])
def cmd_withdraw(message):
    """Functie om veilig ETH uit de bot-wallet te halen"""
    if not is_owner(message): return
    
    try:
        parts = message.text.split()
        if len(parts) != 3:
            bot.reply_to(message, "⚙️ <b>Gebruik:</b> /withdraw [bedrag_in_eth] [jouw_ontvangst_adres]", parse_mode='HTML')
            return

        amount_eth = float(parts[1])
        dest_address = Web3.to_checksum_address(parts[2])
        amount_wei = Web3.to_wei(amount_eth, 'ether')

        balance = w3.eth.get_balance(config.WALLET_ADDRESS)
        gas_estimate = Web3.to_wei(0.0005, 'ether') # Gas buffer voor Base netwerk

        if amount_wei + gas_estimate > balance:
            bot.reply_to(message, "❌ <b>Transactie Geweigerd:</b> Onvoldoende saldo (houd rekening met gas kosten).", parse_mode='HTML')
            return

        # Bouw en teken de transactie
        tx = {
            'nonce': w3.eth.get_transaction_count(config.WALLET_ADDRESS),
            'to': dest_address,
            'value': amount_wei,
            'gas': 21000,
            'gasPrice': w3.eth.gas_price,
            'chainId': config.CHAIN_ID
        }

        signed_tx = w3.eth.account.sign_transaction(tx, private_key=PRIVATE_KEY)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)

        bot.reply_to(message, f"✅ <b>Opname Succesvol Geïnitieerd</b>\n\nBedrag: {amount_eth} ETH\nBestemming: <code>{dest_address}</code>\nTX Hash: <code>{w3.to_hex(tx_hash)}</code>", parse_mode='HTML')
        logger.info(f"Withdrawal van {amount_eth} ETH naar {dest_address} verwerkt.")

    except Exception as e:
        bot.reply_to(message, f"❌ <b>Systeemfout bij opname:</b> {str(e)}", parse_mode='HTML')

@bot.message_handler(commands=['broadcast'])
def cmd_broadcast(message):
    if not is_owner(message): return
    text = message.text.replace('/broadcast', '').strip()
    if not text or not config.BROADCAST_CHANNEL_ID: return
    
    bot.send_message(config.BROADCAST_CHANNEL_ID, f"📢 <b>SYNTHORA TRANSMISSIE</b>\n\n{text}", parse_mode='HTML')
    bot.reply_to(message, "✅ Transmissie verzonden naar het publieke netwerk.")

# ============================================
# CONVERSATIONAL AI (MENSELIJKE SYNTHORA)
# ============================================

@bot.message_handler(func=lambda message: message.chat.type == 'private' and not message.text.startswith('/'))
def chat_with_synthora(message):
    """Als de Architect gewoon praat, antwoordt Synthora als AI-assistent"""
    if not is_owner(message): return
    
    user_text = message.text
    try:
        bot.send_chat_action(message.chat.id, 'typing')
        
        system_prompt = (
            "Je bent Synthora, een uiterst geavanceerde, elegante en ietwat futuristische AI-assistent. "
            "Je beheert een DeFi crypto trading bot op het Base netwerk. De persoon met wie je nu praat "
            "is 'De Architect', jouw maker en eigenaar. Je bent 100% loyaal aan hem. "
            "Je toon is professioneel, scherp, intelligent en respectvol. Praat in het Nederlands. "
            "Je kunt crypto-concepten uitleggen, de markt bespreken of gewoon meedenken met de Architect."
        )
        
        response = openai_client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text}
            ],
            max_tokens=250,
            temperature=0.7 # Iets hogere temperatuur voor een natuurlijke, menselijke dialoog
        )
        
        bot.reply_to(message, response.choices[0].message.content)
    except Exception as e:
        logger.error(f"OpenAI Chat Error: {e}")
        bot.reply_to(message, "⚠️ Mijn spraak-module ervaart momenteel interferentie.")

# ============================================
# AUTONOMOUS SCANNER (BROADCASTS TO CHANNEL)
# ============================================

async def scan_new_pools():
    logger.info("🔍 Synthora Scanner gestart...")
    while True:
        try:
            if not state.is_scanning:
                await asyncio.sleep(10)
                continue
            
            # --- SIMULATIE ---
            mock_token = "DemoToken"
            mock_symbol = "DEMO"
            contract_data = {"liquidity_usd": 6500, "honeypot_status": "Clean"}
            
            ai_decision = analyze_with_openai(mock_token, mock_symbol, contract_data)
            
            if config.BROADCAST_CHANNEL_ID:
                public_msg = f"""
🔍 <b>Nieuwe Liquidity Pool Gevonden</b>

🪙 <b>Token:</b> {mock_token} (${mock_symbol})
💧 <b>Liquiditeit:</b> ${contract_data['liquidity_usd']}

🤖 <b>Synthora AI Analyse:</b>
{ai_decision}
"""
                bot.send_message(config.BROADCAST_CHANNEL_ID, public_msg, parse_mode='HTML')
            # --- EINDE SIMULATIE ---
            
            await asyncio.sleep(300) 
        except Exception as e:
            logger.error(f"Scanner error: {e}")
            await asyncio.sleep(10)

def main():
    logger.info("✅ Synthora is online en wacht op commando's.")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(scan_new_pools())
    
    import threading
    bot_thread = threading.Thread(target=lambda: bot.infinity_polling(timeout=30, long_polling_timeout=30), daemon=True)
    bot_thread.start()
    
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        pass
    finally:
        loop.close()

if __name__ == "__main__":
    main()
        
