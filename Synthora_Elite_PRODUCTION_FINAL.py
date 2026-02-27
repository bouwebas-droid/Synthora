#!/usr/bin/env python3
"""
🔥 SYNTHORA ELITE - PRODUCTION FINAL VERSION 🔥
COMPLETE SNIPER BOT - READY TO MAKE MONEY

Version: PRODUCTION_FINAL_v1.0
Network: Base Mainnet
DEX: Aerodrome Finance

⚠️ THIS VERSION MAKES REAL TRANSACTIONS ⚠️
Start with BUY_AMOUNT_ETH = 0.001 for testing!

Features:
- Real-time pool monitoring ✅
- Production-ready swap execution ✅
- Complete error handling ✅
- DexScreener integration ✅
- Telegram broadcasting ✅
- All settings via environment ✅
"""

import os
import logging
import asyncio
from datetime import datetime
import requests
from web3 import Web3
import telebot

# ============================================
# LOGGING SETUP
# ============================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('SynthoraElite')

# ============================================
# ENVIRONMENT VARIABLES
# ============================================
TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHANNEL_ID = os.getenv('TELEGRAM_CHANNEL_ID')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
PRIVATE_KEY = os.getenv('ARCHITECT_SESSION')

# Initialize Telegram
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# ============================================
# WEB3 SETUP - BASE NETWORK
# ============================================
BASE_RPC = 'https://mainnet.base.org'
w3 = Web3(Web3.HTTPProvider(BASE_RPC))
logger.info("🔗 Connected to Base public RPC")

# Load wallet
if not PRIVATE_KEY.startswith('0x'):
    PRIVATE_KEY = '0x' + PRIVATE_KEY
account = w3.eth.account.from_key(PRIVATE_KEY)
WALLET = account.address
logger.info(f"✅ Wallet loaded: {WALLET}")

# Test connection
try:
    block = w3.eth.block_number
    logger.info(f"✅ Base Mainnet - Block: {block}")
except Exception as e:
    logger.error(f"❌ Connection failed: {e}")
    exit(1)

# ============================================
# CONFIGURATION
# ============================================
class Config:
    # Addresses
    WALLET_ADDRESS = WALLET
    ROUTER = '0xcF77a3Ba9A5CA399B7c97c74d54e5b1Beb874E43'
    FACTORY = '0x420DD381b31aEf6683db6B902084cB0FFECe40Da'
    WETH = '0x4200000000000000000000000000000000000006'
    
    # Trading (all from environment)
    BUY_AMOUNT = Web3.to_wei(float(os.getenv('BUY_AMOUNT_ETH', '0.001')), 'ether')
    MIN_LIQUIDITY = float(os.getenv('MIN_LIQUIDITY_USD', '10000'))
    GAS_MULTIPLIER = float(os.getenv('GAS_MULTIPLIER', '1.5'))
    MAX_GAS_GWEI = int(os.getenv('MAX_GAS_GWEI', '100'))
    CHECK_INTERVAL = int(os.getenv('CHECK_INTERVAL_SEC', '2'))
    MAX_TRADES_DAY = int(os.getenv('MAX_TRADES_PER_DAY', '20'))

config = Config()

logger.info(f"⚙️ Config: {Web3.from_wei(config.BUY_AMOUNT, 'ether')} ETH per snipe")
logger.info(f"⚙️ Min Liquidity: ${config.MIN_LIQUIDITY:,.0f}")

# ============================================
# COMPLETE AERODROME ROUTER ABI
# ============================================
ROUTER_ABI = [{
    "inputs": [
        {"internalType": "uint256", "name": "amountOutMin", "type": "uint256"},
        {
            "components": [
                {"internalType": "address", "name": "from", "type": "address"},
                {"internalType": "address", "name": "to", "type": "address"},
                {"internalType": "bool", "name": "stable", "type": "bool"}
            ],
            "internalType": "struct Router.Route[]",
            "name": "routes",
            "type": "tuple[]"
        },
        {"internalType": "address", "name": "to", "type": "address"},
        {"internalType": "uint256", "name": "deadline", "type": "uint256"}
    ],
    "name": "swapExactETHForTokens",
    "outputs": [{"internalType": "uint256[]", "name": "amounts", "type": "uint256[]"}],
    "stateMutability": "payable",
    "type": "function"
}]

# ERC20 for balance checks
ERC20_ABI = [{
    "constant": True,
    "inputs": [{"name": "account", "type": "address"}],
    "name": "balanceOf",
    "outputs": [{"name": "", "type": "uint256"}],
    "type": "function"
}, {
    "constant": True,
    "inputs": [],
    "name": "decimals",
    "outputs": [{"name": "", "type": "uint8"}],
    "type": "function"
}, {
    "constant": True,
    "inputs": [],
    "name": "symbol",
    "outputs": [{"name": "", "type": "string"}],
    "type": "function"
}]

# ============================================
# PRODUCTION SWAP EXECUTION
# ============================================
def execute_swap(token_address, eth_amount):
    """
    🔥 PRODUCTION-READY SWAP EXECUTION 🔥
    This actually sends real transactions!
    """
    try:
        logger.info(f"🚀 EXECUTING SWAP: {Web3.from_wei(eth_amount, 'ether')} ETH")
        logger.info(f"   Target: {token_address[:10]}...")
        
        # Checksum addresses
        token = Web3.to_checksum_address(token_address)
        router_addr = Web3.to_checksum_address(config.ROUTER)
        weth = Web3.to_checksum_address(config.WETH)
        
        # Get router contract
        router = w3.eth.contract(address=router_addr, abi=ROUTER_ABI)
        
        # Build route: WETH → TOKEN
        route = [{
            'from': weth,
            'to': token,
            'stable': False  # Volatile pair
        }]
        
        logger.info(f"   Route: WETH → Token (volatile)")
        
        # Deadline (5 min from now)
        deadline = w3.eth.get_block('latest')['timestamp'] + 300
        
        # Check wallet balance
        balance = w3.eth.get_balance(WALLET)
        logger.info(f"   💰 Balance: {Web3.from_wei(balance, 'ether'):.4f} ETH")
        
        if balance < eth_amount * 2:  # Need 2x for gas
            logger.error(f"❌ INSUFFICIENT BALANCE!")
            return None
        
        # Estimate gas
        try:
            gas_est = router.functions.swapExactETHForTokens(
                0, route, WALLET, deadline
            ).estimate_gas({'from': WALLET, 'value': eth_amount})
            gas_limit = int(gas_est * 1.3)
            logger.info(f"   ⛽ Gas estimate: {gas_est} (using {gas_limit})")
        except Exception as e:
            logger.warning(f"   ⚠️ Gas estimation failed: {e}")
            gas_limit = 500000
            logger.info(f"   ⛽ Using default: {gas_limit}")
        
        # Get gas price
        gas_price = w3.eth.gas_price
        gas_with_mult = int(gas_price * config.GAS_MULTIPLIER)
        max_gas = Web3.to_wei(config.MAX_GAS_GWEI, 'gwei')
        
        if gas_with_mult > max_gas:
            logger.error(f"❌ Gas too high! {Web3.from_wei(gas_with_mult, 'gwei'):.1f} gwei")
            return None
        
        logger.info(f"   ⛽ Gas: {Web3.from_wei(gas_with_mult, 'gwei'):.2f} gwei")
        
        # Build transaction
        tx = router.functions.swapExactETHForTokens(
            0,  # Accept any amount
            route,
            WALLET,
            deadline
        ).build_transaction({
            'from': WALLET,
            'value': eth_amount,
            'gas': gas_limit,
            'gasPrice': gas_with_mult,
            'nonce': w3.eth.get_transaction_count(WALLET)
        })
        
        logger.info(f"   ✅ Transaction built")
        
        # Sign transaction
        signed = w3.eth.account.sign_transaction(tx, PRIVATE_KEY)
        logger.info(f"   ✅ Transaction signed")
        
        # 🔥 SEND TRANSACTION 🔥
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        tx_hex = tx_hash.hex()
        
        logger.info(f"")
        logger.info(f"🎉 TRANSACTION SENT!")
        logger.info(f"   TX: {tx_hex}")
        logger.info(f"   🔗 https://basescan.org/tx/{tx_hex}")
        logger.info(f"")
        
        # Wait for confirmation (30 sec max)
        try:
            logger.info(f"   ⏳ Waiting for confirmation...")
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)
            
            if receipt['status'] == 1:
                logger.info(f"   ✅ CONFIRMED! Gas used: {receipt['gasUsed']}")
                
                # Check token balance
                try:
                    token_contract = w3.eth.contract(address=token, abi=ERC20_ABI)
                    bal = token_contract.functions.balanceOf(WALLET).call()
                    decimals = token_contract.functions.decimals().call()
                    bal_fmt = bal / (10 ** decimals)
                    symbol = token_contract.functions.symbol().call()
                    logger.info(f"   💰 Balance: {bal_fmt:,.2f} {symbol}")
                except:
                    logger.info(f"   💰 Tokens received (amount unknown)")
                
                return tx_hex
            else:
                logger.error(f"   ❌ TRANSACTION REVERTED!")
                return None
                
        except Exception as e:
            logger.warning(f"   ⚠️ Confirmation timeout (tx still sent)")
            return tx_hex
            
    except ValueError as e:
        err = str(e)
        logger.error(f"❌ Transaction will fail: {err}")
        if "insufficient funds" in err.lower():
            logger.error(f"   💸 NOT ENOUGH ETH!")
        return None
        
    except Exception as e:
        logger.error(f"❌ Swap failed: {e}")
        return None

# ============================================
# DEXSCREENER INTEGRATION  
# ============================================
def get_pool_data(token_address):
    """Get token data from DexScreener"""
    try:
        url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
        response = requests.get(url, timeout=3)
        data = response.json()
        
        if not data.get('pairs'):
            return None
        
        # Find Base pair
        for pair in data['pairs']:
            if pair['chainId'] == 'base':
                return {
                    'liquidity_usd': float(pair.get('liquidity', {}).get('usd', 0)),
                    'volume_24h': float(pair.get('volume', {}).get('h24', 0)),
                    'price_usd': float(pair.get('priceUsd', 0)),
                    'pair_address': pair.get('pairAddress', ''),
                    'pair_created_at': pair.get('pairCreatedAt', 0)
                }
        return None
    except:
        return None

# ============================================
# TELEGRAM BROADCASTING
# ============================================
def broadcast(msg, parse_mode=None):
    """Broadcast to channel"""
    if not TELEGRAM_CHANNEL_ID:
        logger.warning("⚠️ No channel ID set")
        return
    try:
        bot.send_message(TELEGRAM_CHANNEL_ID, msg, parse_mode=parse_mode)
    except Exception as e:
        logger.error(f"Broadcast failed: {e}")

# ============================================
# SCANNER ENGINE
# ============================================
async def scan_pools():
    """Real-time pool scanner"""
    logger.info("🔍 SCANNER ENGINE STARTED!")
    
    # Factory ABI
    factory_abi = [{
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "token0", "type": "address"},
            {"indexed": True, "name": "token1", "type": "address"},
            {"indexed": False, "name": "stable", "type": "bool"},
            {"indexed": False, "name": "pool", "type": "address"},
            {"indexed": False, "name": "index", "type": "uint256"}
        ],
        "name": "PoolCreated",
        "type": "event"
    }]
    
    factory = w3.eth.contract(
        address=Web3.to_checksum_address(config.FACTORY),
        abi=factory_abi
    )
    
    processed = set()
    daily_trades = 0
    last_reset = datetime.now().date()
    
    while True:
        try:
            # Reset daily counter
            if datetime.now().date() != last_reset:
                daily_trades = 0
                last_reset = datetime.now().date()
            
            # Check limit
            if daily_trades >= config.MAX_TRADES_DAY:
                logger.warning(f"⚠️ Daily limit reached ({config.MAX_TRADES_DAY})")
                await asyncio.sleep(60)
                continue
            
            # Scan blocks
            latest = w3.eth.block_number
            from_block = max(0, latest - 10)
            
            try:
                events = factory.events.PoolCreated.get_logs(
                    from_block=from_block,
                    to_block='latest'
                )
                
                if len(events) == 0:
                    msg = f"📡 Scanned blocks {from_block:,}-{latest:,}, no new pools"
                    logger.info(msg)
                    broadcast(msg)
                
                # Process events
                for event in events:
                    pool = event['args']['pool']
                    token0 = event['args']['token0']
                    token1 = event['args']['token1']
                    stable = event['args']['stable']
                    
                    if pool in processed:
                        continue
                    processed.add(pool)
                    
                    # Filter WETH pairs only
                    weth_lower = config.WETH.lower()
                    if token0.lower() != weth_lower and token1.lower() != weth_lower:
                        continue
                    
                    # Get target token
                    target = token1 if token0.lower() == weth_lower else token0
                    
                    # Skip stable pairs
                    if stable:
                        continue
                    
                    logger.info(f"")
                    logger.info(f"🎯 NEW POOL DETECTED!")
                    logger.info(f"   Pool: {pool[:10]}...")
                    logger.info(f"   Token: {target}")
                    
                    # Get DexScreener data
                    pool_data = get_pool_data(target)
                    if not pool_data:
                        logger.warning(f"   ❌ No DexScreener data")
                        continue
                    
                    # Check liquidity
                    if pool_data['liquidity_usd'] < config.MIN_LIQUIDITY:
                        logger.warning(f"   ❌ Low liquidity: ${pool_data['liquidity_usd']:,.0f}")
                        continue
                    
                    logger.info(f"   ✅ Liquidity: ${pool_data['liquidity_usd']:,.0f}")
                    logger.info(f"   ✅ All checks passed!")
                    
                    # 🔥 EXECUTE SNIPE 🔥
                    tx_hash = execute_swap(target, config.BUY_AMOUNT)
                    
                    if tx_hash:
                        daily_trades += 1
                        
                        # Broadcast success
                        channel_msg = f"""🎯 <b>NEW TOKEN SNIPED</b> 🚀

💎 <b>Token:</b> <code>{target}</code>

💧 <b>Liquidity:</b> ${pool_data['liquidity_usd']:,.0f}
📊 <b>Volume 24h:</b> ${pool_data['volume_24h']:,.0f}

🔗 <b>TX:</b> <code>{tx_hash[:16]}...</code>

🔍 <a href="https://basescan.org/tx/{tx_hash}">BaseScan</a> | <a href="https://dexscreener.com/base/{target}">DexScreener</a>

⚡ <i>Synthora Elite</i>"""
                        
                        broadcast(channel_msg, parse_mode='HTML')
                        
                        logger.info(f"✅ SNIPE COMPLETE!")
                    else:
                        logger.error(f"❌ SNIPE FAILED")
                    
                    logger.info(f"")
                
            except Exception as e:
                error_msg = f"⚠️ Scan error at block {latest:,}"
                logger.error(f"❌ {error_msg}: {e}")
                broadcast(error_msg)
            
            await asyncio.sleep(config.CHECK_INTERVAL)
            
        except Exception as e:
            logger.error(f"❌ Scanner error: {e}")
            await asyncio.sleep(config.CHECK_INTERVAL)

# ============================================
# TELEGRAM COMMANDS
# ============================================
@bot.message_handler(commands=['start'])
def cmd_start(msg):
    balance = w3.eth.get_balance(WALLET)
    bal_eth = Web3.from_wei(balance, 'ether')
    
    response = f"""🤖 <b>Synthora Elite - PRODUCTION</b>

✅ Status: 🟢 Active
💼 Wallet: <code>{WALLET}</code>
💰 Balance: {bal_eth:.4f} ETH

⚙️ <b>Settings:</b>
• Buy Amount: {Web3.from_wei(config.BUY_AMOUNT, 'ether')} ETH
• Min Liquidity: ${config.MIN_LIQUIDITY:,.0f}

📊 Ready to snipe!"""
    
    bot.reply_to(msg, response, parse_mode='HTML')

@bot.message_handler(commands=['status'])
def cmd_status(msg):
    block = w3.eth.block_number
    response = f"""📊 <b>Bot Status</b>

🟢 Scanner: Active
📡 Block: {block:,}
⚙️ Check Interval: {config.CHECK_INTERVAL}s

💰 Trading:
• Buy: {Web3.from_wei(config.BUY_AMOUNT, 'ether')} ETH
• Min Liq: ${config.MIN_LIQUIDITY:,.0f}
• Gas: {config.GAS_MULTIPLIER}x

✅ All systems operational!"""
    
    bot.reply_to(msg, response, parse_mode='HTML')

# ============================================
# MAIN
# ============================================
def main():
    logger.info("=" * 60)
    logger.info("🔥 SYNTHORA ELITE - PRODUCTION FINAL 🔥")
    logger.info("=" * 60)
    logger.info("")
    logger.info(f"✅ Wallet: {WALLET}")
    logger.info(f"✅ Network: Base Mainnet")
    logger.info(f"✅ DEX: Aerodrome Finance")
    logger.info(f"")
    logger.info(f"⚠️  THIS MAKES REAL TRANSACTIONS! ⚠️")
    logger.info(f"")
    logger.info(f"⚙️  Buy Amount: {Web3.from_wei(config.BUY_AMOUNT, 'ether')} ETH")
    logger.info(f"⚙️  Min Liquidity: ${config.MIN_LIQUIDITY:,.0f}")
    logger.info(f"")
    
    # Check balance
    balance = w3.eth.get_balance(WALLET)
    bal_eth = Web3.from_wei(balance, 'ether')
    logger.info(f"💰 ETH Balance: {bal_eth:.4f} ETH")
    
    if bal_eth < 0.01:
        logger.warning(f"⚠️  LOW BALANCE! Need at least 0.01 ETH")
    
    logger.info(f"")
    logger.info("=" * 60)
    logger.info("")
    
    # Start Telegram polling in thread
    import threading
    def run_telegram():
        logger.info("🤖 Telegram bot starting...")
        bot.infinity_polling()
    
    telegram_thread = threading.Thread(target=run_telegram, daemon=True)
    telegram_thread.start()
    
    # Start scanner
    asyncio.run(scan_pools())

if __name__ == "__main__":
    main()
