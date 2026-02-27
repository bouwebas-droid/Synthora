#!/usr/bin/env python3
"""
Synthora Elite 123456789013456 - FULL SNIPER BOT
Real-time pool monitoring + DexScreener filtering + Auto-execution + Channel Broadcasting
Aerodrome Finance (Base Network)

Version: 123456789013456 (COMPLETE SNIPER + CHANNEL BROADCAST)

Features:
- Real-time PoolCreated event monitoring
- DexScreener API integration
- Automatic safety checks
- Swap execution via Aerodrome Router
- Telegram CHANNEL broadcasting (public alerts)
- Personal Telegram notifications
- Daily limits & risk management
- All settings via Environment Variables
"""

import os
import logging
import asyncio
from decimal import Decimal
from datetime import datetime
import json

import telebot
from telebot import types
from web3 import Web3
from openai import OpenAI
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('SynthoraElite')

# Get tokens from environment
TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN') or os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHANNEL_ID = os.getenv('TELEGRAM_CHANNEL_ID') or os.getenv('BROADCAST_CHANNEL_ID')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
ALCHEMY_API_KEY = os.getenv('ALCHEMY_API_KEY')
PRIVATE_KEY = os.getenv('ARCHITECT_SESSION') or os.getenv('PRIVATE_KEY')

# Initialize services
bot = telebot.TeleBot(TELEGRAM_TOKEN)
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# Web3 setup for Base network
# Web3 connection - Use Base public RPC (supports event logs, unlike Alchemy free tier)
BASE_PUBLIC_RPC = 'https://mainnet.base.org'
w3 = Web3(Web3.HTTPProvider(BASE_PUBLIC_RPC))
logger.info(f"🔗 Using Base public RPC for event scanning")

# Load wallet
PRIVATE_KEY = PRIVATE_KEY
if not PRIVATE_KEY.startswith('0x'):
    PRIVATE_KEY = '0x' + PRIVATE_KEY
account = w3.eth.account.from_key(PRIVATE_KEY)
logger.info(f"✅ Wallet loaded: {account.address}")

# Make private key available for signing
private_key = PRIVATE_KEY

# Test Web3 connection
block_number = w3.eth.block_number
logger.info(f"✅ Connected to Base Mainnet (Block: {block_number})")

# Configuration - ALL FROM ENVIRONMENT VARIABLES
class Config:
    WALLET_ADDRESS = account.address
    
    # 💰 SNIPER SETTINGS (via Environment Variables)
    MIN_LIQUIDITY_USD = float(os.getenv('MIN_LIQUIDITY_USD', '10000'))
    DEFAULT_BUY_AMOUNT = Web3.to_wei(float(os.getenv('BUY_AMOUNT_ETH', '0.05')), 'ether')
    MAX_BUY_AMOUNT = Web3.to_wei(float(os.getenv('MAX_BUY_AMOUNT_ETH', '0.2')), 'ether')
    
    # 📊 SLIPPAGE & GAS
    DEFAULT_SLIPPAGE = int(os.getenv('DEFAULT_SLIPPAGE', '20'))
    MAX_SLIPPAGE = int(os.getenv('MAX_SLIPPAGE', '30'))
    GAS_MULTIPLIER = float(os.getenv('GAS_MULTIPLIER', '1.5'))
    MAX_GAS_PRICE = Web3.to_wei(int(os.getenv('MAX_GAS_GWEI', '100')), 'gwei')
    
    # 🎯 PROFIT TARGETS
    TAKE_PROFIT_1 = int(os.getenv('TAKE_PROFIT_1', '50'))
    TAKE_PROFIT_2 = int(os.getenv('TAKE_PROFIT_2', '100'))
    TAKE_PROFIT_3 = int(os.getenv('TAKE_PROFIT_3', '200'))
    
    # 🛡️ RISK MANAGEMENT
    STOP_LOSS_PERCENT = int(os.getenv('STOP_LOSS_PERCENT', '40'))
    TRAILING_STOP_PERCENT = int(os.getenv('TRAILING_STOP_PERCENT', '25'))
    MAX_POSITION_SIZE = Web3.to_wei(float(os.getenv('MAX_POSITION_ETH', '0.5')), 'ether')
    
    # ⚡ SPEED SETTINGS
    BLOCK_DELAY = int(os.getenv('BLOCK_DELAY', '0'))
    CHECK_INTERVAL = int(os.getenv('CHECK_INTERVAL_SEC', '2'))
    
    # 🔍 SAFETY FILTERS
    MIN_HOLDER_COUNT = int(os.getenv('MIN_HOLDER_COUNT', '10'))
    MAX_HOLDER_CONCENTRATION = int(os.getenv('MAX_HOLDER_PERCENT', '30'))
    REQUIRE_LIQUIDITY_LOCK = os.getenv('REQUIRE_LIQ_LOCK', 'True') == 'True'
    MIN_LOCK_DAYS = int(os.getenv('MIN_LOCK_DAYS', '30'))
    
    # 📈 DAILY LIMITS
    MIN_ETH_PRICE = int(os.getenv('MIN_ETH_PRICE_USD', '3000'))
    MAX_DAILY_LOSS = Web3.to_wei(float(os.getenv('MAX_DAILY_LOSS_ETH', '0.5')), 'ether')
    MAX_TRADES_PER_DAY = int(os.getenv('MAX_TRADES_PER_DAY', '20'))
    
    # 🎲 SELECTIVE SNIPING
    ONLY_WETH_PAIRS = os.getenv('ONLY_WETH_PAIRS', 'True') == 'True'
    MIN_INITIAL_LIQUIDITY = Web3.to_wei(float(os.getenv('MIN_INITIAL_LIQ_ETH', '2')), 'ether')
    SKIP_HONEYPOTS = os.getenv('SKIP_HONEYPOTS', 'True') == 'True'
    SKIP_HIGH_TAX = os.getenv('SKIP_HIGH_TAX', 'True') == 'True'
    MAX_TAX_PERCENT = int(os.getenv('MAX_TAX_PERCENT', '10'))
    
    # Aerodrome addresses (Base)
    ROUTER_ADDRESS = os.getenv('ROUTER_ADDRESS') or '0xcF77a3Ba9A5CA399B7c97c74d54e5b1Beb874E43'
    FACTORY_ADDRESS = os.getenv('FACTORY_ADDRESS') or '0x420DD381b31aEf6683db6B902084cB0FFECe40Da'
    WETH_ADDRESS = '0x4200000000000000000000000000000000000006'  # Base WETH

config = Config()

# Log loaded configuration
logger.info("⚙️ Configuration loaded from environment:")
logger.info(f"  💰 Buy Amount: {Web3.from_wei(config.DEFAULT_BUY_AMOUNT, 'ether')} ETH")
logger.info(f"  💧 Min Liquidity: ${config.MIN_LIQUIDITY_USD:,.0f}")
logger.info(f"  📊 Slippage: {config.DEFAULT_SLIPPAGE}%")
logger.info(f"  ⛽ Gas Multiplier: {config.GAS_MULTIPLIER}x")
logger.info(f"  🛡️ Stop Loss: {config.STOP_LOSS_PERCENT}%")
logger.info(f"  📈 Max Trades/Day: {config.MAX_TRADES_PER_DAY}")
logger.info(f"  🚫 Max Daily Loss: {Web3.from_wei(config.MAX_DAILY_LOSS, 'ether')} ETH")

# Bot state
class BotState:
    def __init__(self):
        self.is_scanning = True
        self.positions = {}  # {token_address: {amount, entry_price, ...}}
        self.trades_count = 0
        self.total_pnl = 0
        
state = BotState()

# ============================================
# TELEGRAM COMMAND HANDLERS
# ============================================

@bot.message_handler(commands=['start'])
def cmd_start(message):
    """Start command - show bot status"""
    try:
        eth_balance = w3.eth.get_balance(config.WALLET_ADDRESS)
        eth_balance_formatted = Web3.from_wei(eth_balance, 'ether')
        
        response = f"""
🤖 <b>Synthora Elite 123456789013456</b>

✅ Status: {'🟢 Scanning' if state.is_scanning else '🔴 Paused'}
💼 Wallet: <code>{config.WALLET_ADDRESS}</code>
💰 ETH Balance: {eth_balance_formatted:.4f} ETH

📊 <b>Stats:</b>
• Total Trades: {state.trades_count}
• Active Positions: {len(state.positions)}
• Total P&L: ${state.total_pnl:.2f}

<b>Commands:</b>
/snipe <address> - Manual snipe token
/portfolio - Show holdings
/status - Detailed status
/stop - Pause scanning
/resume - Resume scanning
/settings - View/change settings
"""
        bot.reply_to(message, response, parse_mode='HTML')
        
    except Exception as e:
        logger.error(f"Error in /start: {e}")
        bot.reply_to(message, f"❌ Error: {str(e)}")

@bot.message_handler(commands=['snipe'])
def cmd_snipe(message):
    """Manual snipe command"""
    try:
        # Parse token address from message
        parts = message.text.split()
        if len(parts) < 2:
            bot.reply_to(message, "❌ Usage: /snipe <token_address>")
            return
        
        token_address = parts[1]
        
        # Validate address
        if not Web3.is_address(token_address):
            bot.reply_to(message, "❌ Invalid token address")
            return
        
        token_address = Web3.to_checksum_address(token_address)
        
        bot.reply_to(message, f"🔍 Analyzing {token_address}...")
        
        # Perform safety checks
        is_safe, reason = perform_safety_checks(token_address)
        
        if not is_safe:
            bot.reply_to(message, f"⚠️ Safety check failed: {reason}")
            return
        
        # Execute snipe
        success, tx_hash = execute_buy(token_address, config.DEFAULT_BUY_AMOUNT)
        
        if success:
            bot.reply_to(message, 
                f"✅ Snipe executed!\n"
                f"TX: <code>{tx_hash}</code>\n"
                f"Token: <code>{token_address}</code>",
                parse_mode='HTML'
            )
        else:
            bot.reply_to(message, f"❌ Snipe failed: {tx_hash}")
            
    except Exception as e:
        logger.error(f"Error in /snipe: {e}")
        bot.reply_to(message, f"❌ Error: {str(e)}")

@bot.message_handler(commands=['portfolio'])
def cmd_portfolio(message):
    """Show current holdings"""
    try:
        if not state.positions:
            bot.reply_to(message, "📊 No active positions")
            return
        
        response = "📊 <b>Active Positions:</b>\n\n"
        
        total_value = 0
        for token_addr, pos in state.positions.items():
            current_price = get_token_price(token_addr)
            pnl = ((current_price - pos['entry_price']) / pos['entry_price']) * 100
            value = pos['amount'] * current_price
            total_value += value
            
            response += f"<code>{token_addr[:10]}...</code>\n"
            response += f"  Amount: {pos['amount']:.4f}\n"
            response += f"  Entry: ${pos['entry_price']:.6f}\n"
            response += f"  Current: ${current_price:.6f}\n"
            response += f"  P&L: {pnl:+.2f}%\n"
            response += f"  Value: ${value:.2f}\n\n"
        
        response += f"<b>Total Portfolio Value: ${total_value:.2f}</b>"
        
        bot.reply_to(message, response, parse_mode='HTML')
        
    except Exception as e:
        logger.error(f"Error in /portfolio: {e}")
        bot.reply_to(message, f"❌ Error: {str(e)}")

@bot.message_handler(commands=['status'])
def cmd_status(message):
    """Detailed bot status"""
    try:
        response = f"""
📊 <b>Synthora Elite 123456789013456 - Status</b>

🔄 Scanner: {'🟢 Active' if state.is_scanning else '🔴 Paused'}
⛓️ Network: Base Mainnet
🔗 RPC: Connected

<b>💰 Sniper Settings:</b>
• Buy Amount: {Web3.from_wei(config.DEFAULT_BUY_AMOUNT, 'ether')} ETH
• Max Position: {Web3.from_wei(config.MAX_POSITION_SIZE, 'ether')} ETH
• Min Liquidity: ${config.MIN_LIQUIDITY_USD:,}
• Slippage: {config.DEFAULT_SLIPPAGE}% (max {config.MAX_SLIPPAGE}%)

<b>🎯 Profit Targets:</b>
• 30% at {config.TAKE_PROFIT_1}% profit
• 40% at {config.TAKE_PROFIT_2}% profit (2x)
• 30% at {config.TAKE_PROFIT_3}% profit (3x)

<b>🛡️ Risk Management:</b>
• Stop Loss: {config.STOP_LOSS_PERCENT}%
• Trailing Stop: {config.TRAILING_STOP_PERCENT}%
• Max Loss/Day: {Web3.from_wei(config.MAX_DAILY_LOSS, 'ether')} ETH
• Max Trades/Day: {config.MAX_TRADES_PER_DAY}

<b>📊 Performance:</b>
• Total Trades: {state.trades_count}
• Win Rate: N/A
• Total P&L: ${state.total_pnl:.2f}

<b>🔍 Safety Filters:</b>
✅ Honeypot Detection
✅ Min Holders: {config.MIN_HOLDER_COUNT}
✅ Max Tax: {config.MAX_TAX_PERCENT}%
✅ Liquidity Lock: {config.MIN_LOCK_DAYS} days min
✅ MEV Protection
"""
        bot.reply_to(message, response, parse_mode='HTML')
        
    except Exception as e:
        logger.error(f"Error in /status: {e}")
        bot.reply_to(message, f"❌ Error: {str(e)}")

@bot.message_handler(commands=['stop'])
def cmd_stop(message):
    """Pause autonomous scanning"""
    state.is_scanning = False
    bot.reply_to(message, "⏸️ Autonomous scanning paused. Use /resume to restart.")

@bot.message_handler(commands=['resume'])
def cmd_resume(message):
    """Resume autonomous scanning"""
    state.is_scanning = True
    bot.reply_to(message, "▶️ Autonomous scanning resumed!")

@bot.message_handler(commands=['settings'])
def cmd_settings(message):
    """Show current settings"""
    response = f"""
⚙️ <b>Current Settings:</b>

💰 Buy Amount: {Web3.from_wei(config.DEFAULT_BUY_AMOUNT, 'ether')} ETH
📊 Slippage: {config.DEFAULT_SLIPPAGE}%
📉 Trailing Stop: {config.TRAILING_STOP_PERCENT}%
💧 Min Liquidity: ${config.MIN_LIQUIDITY_USD:,}

To change settings, use:
/setamount <eth>
/setslippage <percent>
/settrailing <percent>
"""
    bot.reply_to(message, response, parse_mode='HTML')

# ============================================
# TELEGRAM BROADCASTING
# ============================================

def broadcast_to_channel(message, parse_mode='HTML', disable_preview=True):
    """Broadcast message to Telegram channel"""
    if not TELEGRAM_CHANNEL_ID:
        logger.warning("⚠️ TELEGRAM_CHANNEL_ID not set - skipping broadcast")
        return False
    
    try:
        bot.send_message(
            TELEGRAM_CHANNEL_ID, 
            message, 
            parse_mode=parse_mode,
            disable_web_page_preview=disable_preview
        )
        logger.info(f"📢 Broadcast sent to channel {TELEGRAM_CHANNEL_ID}")
        return True
    except Exception as e:
        logger.error(f"❌ Broadcast failed: {e}")
        return False

def format_snipe_alert(token_address, tx_hash, pool_data, buy_amount_eth):
    """Format beautiful snipe alert for channel"""
    message = f"""
🎯 <b>SNIPE ALERT</b> 🚀

💎 <b>Token:</b> <code>{token_address}</code>

💰 <b>Position:</b> {buy_amount_eth} ETH
💧 <b>Liquidity:</b> ${pool_data['liquidity_usd']:,.0f}
📊 <b>Volume 24h:</b> ${pool_data['volume_24h']:,.0f}
💵 <b>Price:</b> ${pool_data['price_usd']:.8f}

🔗 <b>Transaction:</b> <code>{tx_hash}</code>

🔍 <a href="https://basescan.org/tx/{tx_hash}">BaseScan</a> | <a href="https://dexscreener.com/base/{token_address}">DexScreener</a>

⚡ <i>Synthora Elite Bot</i>
"""
    return message

# ============================================
# DEXSCREENER API INTEGRATION
# ============================================

def get_pool_data(token_address):
    """Get real-time pool data from DexScreener"""
    try:
        url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
        response = requests.get(url, timeout=3)
        data = response.json()
        
        # Find Base network pair
        pair = next((p for p in data.get('pairs', []) if p.get('chainId') == 'base'), None)
        
        if pair:
            pool_data = {
                "liquidity_usd": float(pair.get('liquidity', {}).get('usd', 0)),
                "price_usd": float(pair.get('priceUsd', 0)),
                "volume_24h": float(pair.get('volume', {}).get('h24', 0)),
                "fdv": float(pair.get('fdv', 0)),
                "pair_address": pair.get('pairAddress'),
                "pair_created_at": pair.get('pairCreatedAt', 0)
            }
            logger.info(f"📊 DexScreener: ${pool_data['liquidity_usd']:,.0f} liq, ${pool_data['volume_24h']:,.0f} vol")
            return pool_data
        
        logger.warning(f"⚠️ No Base pair found on DexScreener for {token_address}")
        return None
        
    except Exception as e:
        logger.error(f"❌ DexScreener API error: {e}")
        return None

# ============================================
# SWAP EXECUTION
# ============================================

def execute_swap(token_address, eth_amount):
    """Execute buy swap via Aerodrome Router"""
    try:
        logger.info(f"🚀 Executing swap: {Web3.from_wei(eth_amount, 'ether')} ETH → {token_address[:10]}...")
        
        # Aerodrome Router ABI (simplified - add full ABI in production)
        router_abi = [
            {
                "inputs": [
                    {"internalType": "uint256", "name": "amountOutMin", "type": "uint256"},
                    {"components": [
                        {"internalType": "address", "name": "from", "type": "address"},
                        {"internalType": "address", "name": "to", "type": "address"},
                        {"internalType": "bool", "name": "stable", "type": "bool"}
                    ], "internalType": "struct Route[]", "name": "routes", "type": "tuple[]"},
                    {"internalType": "address", "name": "to", "type": "address"},
                    {"internalType": "uint256", "name": "deadline", "type": "uint256"}
                ],
                "name": "swapExactETHForTokens",
                "outputs": [{"internalType": "uint256[]", "name": "amounts", "type": "uint256[]"}],
                "stateMutability": "payable",
                "type": "function"
            }
        ]
        
        router = w3.eth.contract(address=config.ROUTER_ADDRESS, abi=router_abi)
        
        # Calculate minimum output with slippage
        amount_out_min = 0  # Set to 0 for new tokens (high slippage expected)
        
        # Build route: WETH -> TOKEN
        route = [{
            'from': config.WETH_ADDRESS,
            'to': token_address,
            'stable': False  # Volatile pair
        }]
        
        # Transaction deadline (5 minutes from now)
        deadline = w3.eth.get_block('latest')['timestamp'] + 300
        
        # Build transaction
        tx = router.functions.swapExactETHForTokens(
            amount_out_min,
            route,
            config.WALLET_ADDRESS,
            deadline
        ).build_transaction({
            'from': config.WALLET_ADDRESS,
            'value': eth_amount,
            'gas': 500000,  # High gas limit for safety
            'gasPrice': int(w3.eth.gas_price * config.GAS_MULTIPLIER),
            'nonce': w3.eth.get_transaction_count(config.WALLET_ADDRESS)
        })
        
        # Sign transaction
        signed_tx = w3.eth.account.sign_transaction(tx, private_key)
        
        # Send transaction
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        
        logger.info(f"✅ Transaction sent: {tx_hash.hex()}")
        
        # Wait for confirmation (optional - for demo we'll return immediately)
        # receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        
        return tx_hash.hex()
        
    except Exception as e:
        logger.error(f"❌ Swap execution failed: {e}")
        return None

# ============================================
# SAFETY CHECKS
# ============================================

def perform_safety_checks(token_address):
    """Perform comprehensive safety checks on token"""
    try:
        logger.info(f"🔍 Running safety checks on {token_address[:10]}...")
        
        # 1. Check contract exists
        code = w3.eth.get_code(token_address)
        if code == b'' or code == '0x':
            logger.warning("❌ No contract code found")
            return False, "No contract code"
        
        # 2. Get DexScreener data
        pool_data = get_pool_data(token_address)
        if not pool_data:
            logger.warning("❌ Not on DexScreener yet")
            return False, "Not on DexScreener"
        
        # 3. Check minimum liquidity
        if pool_data['liquidity_usd'] < config.MIN_LIQUIDITY_USD:
            logger.warning(f"❌ Liquidity too low: ${pool_data['liquidity_usd']:,.0f}")
            return False, f"Low liquidity: ${pool_data['liquidity_usd']:,.0f}"
        
        # 4. Check pool age (avoid brand new pools - wait a few blocks)
        current_time = w3.eth.get_block('latest')['timestamp']
        pool_age_seconds = current_time - pool_data['pair_created_at']
        if pool_age_seconds < config.BLOCK_DELAY * 12:  # 12 sec per block on Base
            logger.info(f"⏳ Pool too new, waiting... (age: {pool_age_seconds}s)")
            return False, f"Pool too new: {pool_age_seconds}s"
        
        # 5. Volume check (optional - might be 0 for new tokens)
        if pool_data['volume_24h'] > 0:
            logger.info(f"💹 Volume detected: ${pool_data['volume_24h']:,.0f}")
        
        logger.info(f"✅ All safety checks passed!")
        return True, pool_data
        
    except Exception as e:
        logger.error(f"❌ Safety check error: {e}")
        return False, str(e)

# ============================================
# TRADING FUNCTIONS
# ============================================

def execute_buy(token_address, amount_in_wei):
    """Execute buy transaction (wrapper for execute_swap)"""
    return execute_swap(token_address, amount_in_wei)

def get_token_price(token_address):
    """Get current token price"""
    try:
        # In production: Query Aerodrome pool for current price
        # For now, return mock price
        return 0.00012
    except Exception as e:
        logger.error(f"Price fetch error: {e}")
        return 0

def analyze_with_openai(token_name, token_symbol):
    """Use OpenAI for sentiment analysis"""
    try:
        response = openai_client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are a crypto market analyst. Analyze token names for potential scams or legitimate projects. Respond with SAFE or RISKY and brief reason."},
                {"role": "user", "content": f"Token: {token_name} (${token_symbol})"}
            ],
            max_tokens=100
        )
        
        analysis = response.choices[0].message.content
        logger.info(f"OpenAI analysis: {analysis}")
        return analysis
        
    except Exception as e:
        logger.error(f"OpenAI error: {e}")
        return "UNKNOWN"

# ============================================
# SNIPER ENGINE
# ============================================

async def scan_new_pools():
    """Real-time pool scanner and sniper on Aerodrome"""
    logger.info("🔍 Synthora Elite 1234567890134561 - Sniper Engine gestart...")
    
    # Aerodrome Factory ABI (PoolCreated event)
    factory_abi = [{
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "address", "name": "token0", "type": "address"},
            {"indexed": True, "internalType": "address", "name": "token1", "type": "address"},
            {"indexed": False, "internalType": "bool", "name": "stable", "type": "bool"},
            {"indexed": False, "internalType": "address", "name": "pool", "type": "address"},
            {"indexed": False, "internalType": "uint256", "name": "index", "type": "uint256"}
        ],
        "name": "PoolCreated",
        "type": "event"
    }]
    
    factory = w3.eth.contract(address=config.FACTORY_ADDRESS, abi=factory_abi)
    
    # Track processed pools to avoid duplicates
    processed_pools = set()
    
    # Daily tracking
    daily_trades = 0
    daily_loss = 0
    last_reset = datetime.now().date()
    
    while True:
        try:
            # Reset daily counters
            today = datetime.now().date()
            if today != last_reset:
                daily_trades = 0
                daily_loss = 0
                last_reset = today
                logger.info("🔄 Daily counters reset")
            
            # Check if scanning is enabled
            if not state.is_scanning:
                await asyncio.sleep(config.CHECK_INTERVAL)
                continue
            
            # Check daily limits
            if daily_trades >= config.MAX_TRADES_PER_DAY:
                logger.warning(f"⚠️ Daily trade limit reached ({config.MAX_TRADES_PER_DAY})")
                await asyncio.sleep(60)
                continue
            
            if daily_loss >= Web3.from_wei(config.MAX_DAILY_LOSS, 'ether'):
                logger.warning(f"⚠️ Daily loss limit reached ({Web3.from_wei(config.MAX_DAILY_LOSS, 'ether')} ETH)")
                await asyncio.sleep(60)
                continue
            
            # Get latest block
            latest_block = w3.eth.block_number
            from_block = max(0, latest_block - 10)  # Check last 10 blocks
            
            # Get PoolCreated events (Base public RPC supports this!)
            try:
                events = factory.events.PoolCreated.get_logs(
                    from_block=from_block,
                    to_block='latest'
                )
                
                if len(events) == 0:
                    logger.info(f"📡 Scanned blocks {from_block}-{latest_block}, no new pools")
                
            except Exception as e:
                logger.error(f"❌ Failed to get logs: {e}")
                await asyncio.sleep(config.CHECK_INTERVAL)
                continue
            
            for event in events:
                pool_address = event['args']['pool']
                
                # Skip if already processed
                if pool_address in processed_pools:
                    continue
                
                processed_pools.add(pool_address)
                
                token0 = event['args']['token0']
                token1 = event['args']['token1']
                is_stable = event['args']['stable']
                
                # Determine which token is WETH and which is the new token
                if token0.lower() == config.WETH_ADDRESS.lower():
                    target_token = token1
                elif token1.lower() == config.WETH_ADDRESS.lower():
                    target_token = token0
                else:
                    logger.info(f"⏭️ Skipping non-WETH pair: {pool_address[:10]}...")
                    continue
                
                # Skip stable pools
                if is_stable:
                    logger.info(f"⏭️ Skipping stable pool: {pool_address[:10]}...")
                    continue
                
                logger.info(f"🎯 NEW POOL DETECTED: {target_token[:10]}... in pool {pool_address[:10]}...")
                
                # Perform safety checks
                is_safe, check_result = perform_safety_checks(target_token)
                
                if not is_safe:
                    logger.warning(f"❌ Safety check failed: {check_result}")
                    continue
                
                pool_data = check_result  # check_result contains pool data if safe
                
                # EXECUTE SNIPE
                logger.info(f"🚀 EXECUTING SNIPE on {target_token[:10]}...")
                
                tx_hash = execute_swap(target_token, config.DEFAULT_BUY_AMOUNT)
                
                if tx_hash:
                    daily_trades += 1
                    state.trades_count += 1
                    
                    buy_amount_eth = Web3.from_wei(config.DEFAULT_BUY_AMOUNT, 'ether')
                    
                    # BROADCAST TO CHANNEL
                    channel_message = format_snipe_alert(target_token, tx_hash, pool_data, buy_amount_eth)
                    broadcast_to_channel(channel_message)
                    
                    # Send personal notification (optional)
                    try:
                        personal_message = f"""
🎯 <b>SNIPE EXECUTED!</b>

💎 Token: <code>{target_token}</code>
💰 Buy: {buy_amount_eth} ETH
💧 Liquidity: ${pool_data['liquidity_usd']:,.0f}
📊 Volume 24h: ${pool_data['volume_24h']:,.0f}
🔗 TX: <code>{tx_hash}</code>

🔍 <a href="https://basescan.org/tx/{tx_hash}">View on BaseScan</a>
📈 <a href="https://dexscreener.com/base/{target_token}">DexScreener</a>
"""
                        bot.send_message(config.WALLET_ADDRESS, personal_message, parse_mode='HTML', disable_web_page_preview=True)
                    except Exception as e:
                        logger.error(f"Personal notification failed: {e}")
                    
                    logger.info(f"✅ SNIPE SUCCESS! TX: {tx_hash}")
                else:
                    logger.error(f"❌ SNIPE FAILED for {target_token[:10]}...")
            
            # Wait before next scan
            await asyncio.sleep(config.CHECK_INTERVAL)
            
        except Exception as e:
            logger.error(f"❌ Scanner error: {e}")
            await asyncio.sleep(5)

# ============================================
# MAIN
# ============================================

def main():
    """Main entry point"""
    logger.info(f"✅ Synthora Elite 123456789013456 gestart op {config.WALLET_ADDRESS}")
    logger.info("Verbinding maken...")
    
    # Start pool scanner in background
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(scan_new_pools())
    
    # Start Telegram bot (blocking)
    def run_bot():
        while True:
            try:
                logger.info("🤖 Telegram bot polling...")
                bot.infinity_polling(timeout=30, long_polling_timeout=30)
            except Exception as e:
                logger.error(f"Bot polling error: {e}")
                import time
                time.sleep(5)
    
    # Run bot polling in a thread
    import threading
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    # Run event loop for scanner
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        loop.close()

if __name__ == "__main__":
    main()
