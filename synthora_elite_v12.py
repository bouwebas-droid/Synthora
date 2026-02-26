"""
SYNTHORA ELITE V12 - SIGNAL SERVICE READY
Broadcast channel support for signal service monetization
"""

import os
import re
import time
import logging
from threading import Thread
from typing import Optional, Tuple

from fastapi import FastAPI
from web3 import Web3
import telebot

# ============================================================================
# LOGGING
# ============================================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================================
# CONFIGURATION
# ============================================================================
def load_config():
    config = {
        "RPC_URL": os.getenv("BASE_RPC_URL"),
        "PRIVATE_KEY": os.getenv("OWNER_SECRET_KEY"),
        "TG_TOKEN": os.getenv("TELEGRAM_BOT_TOKEN"),
        "OWNER_ID": os.getenv("OWNER_ID"),
        "BROADCAST_CHANNEL_ID": os.getenv("BROADCAST_CHANNEL_ID"),  # Optional: for signal service
        
        # Aerodrome V2 on Base
        "AERODROME_FACTORY": "0x420DD381b31aEf6683db6B902084cB0FFECe40Da",
        "AERODROME_ROUTER": "0xcF77a3Ba9A5CA399B7c97c74d54e5b1Beb874E43",
        "WETH": "0x4200000000000000000000000000000000000006",
        
        # Trading parameters
        "BUY_AMOUNT_ETH": float(os.getenv("BUY_AMOUNT_ETH", "0.01")),
        "MIN_LIQUIDITY_ETH": float(os.getenv("MIN_LIQUIDITY_ETH", "5.0")),
        "MAX_SLIPPAGE": int(os.getenv("MAX_SLIPPAGE", "10")),
        "TAKE_PROFIT_MULTIPLIER": float(os.getenv("TAKE_PROFIT_X", "2.0")),
        "SELL_PERCENTAGE": float(os.getenv("SELL_PERCENTAGE", "50")),
    }
    
    required = ["RPC_URL", "PRIVATE_KEY"]
    missing = [k for k in required if not config[k]]
    
    if missing:
        logger.error(f"❌ Missing: {missing}")
        raise ValueError(f"Missing: {missing}")
    
    if config["OWNER_ID"]:
        try:
            config["OWNER_ID"] = int(config["OWNER_ID"])
        except ValueError:
            logger.error("❌ OWNER_ID must be a number")
            raise
    
    return config

CONFIG = load_config()

# ============================================================================
# PRIVATE KEY CLEANING
# ============================================================================
def clean_private_key(key: str) -> Optional[str]:
    if not key:
        return None
    
    key = key.strip().replace(" ", "").replace("\n", "").replace("\r", "")
    
    if key.lower().startswith("0x"):
        key = key[2:]
    
    cleaned = re.sub(r'[^0-9a-fA-F]', '', key)
    
    if len(cleaned) != 64:
        logger.error(f"❌ Invalid private key length: {len(cleaned)} (expected 64)")
        return None
    
    return "0x" + cleaned.lower()

# ============================================================================
# WEB3 INITIALIZATION
# ============================================================================
def init_web3():
    try:
        w3 = Web3(Web3.HTTPProvider(CONFIG["RPC_URL"]))
        
        if not w3.is_connected():
            logger.error("❌ Cannot connect to Base RPC")
            return None, None
        
        logger.info(f"✅ Connected to Base RPC (Chain ID: {w3.eth.chain_id})")
        
        safe_key = clean_private_key(CONFIG["PRIVATE_KEY"])
        if not safe_key:
            logger.error("❌ Invalid private key format")
            return w3, None
        
        account = w3.eth.account.from_key(safe_key)
        balance = w3.from_wei(w3.eth.get_balance(account.address), 'ether')
        
        logger.info(f"✅ Synthora Architect loaded: {account.address}")
        logger.info(f"💰 Balance: {balance:.5f} ETH")
        
        return w3, account
        
    except Exception as e:
        logger.error(f"❌ Web3 init failed: {e}")
        return None, None

w3, account = init_web3()

# ============================================================================
# TELEGRAM INITIALIZATION
# ============================================================================
def init_telegram():
    """Initialize Telegram bot and broadcast channel."""
    if not CONFIG.get("TG_TOKEN"):
        logger.warning("⚠️  Telegram disabled (missing token)")
        return None, None
    
    try:
        bot = telebot.TeleBot(CONFIG["TG_TOKEN"])
        bot.get_me()
        logger.info("✅ Telegram bot connected")
        
        # Check if broadcast channel configured
        broadcast_id = CONFIG.get("BROADCAST_CHANNEL_ID")
        if broadcast_id:
            try:
                # Test if bot can post to channel
                broadcast_id = int(broadcast_id)
                bot.send_message(broadcast_id, "🤖 Synthora Elite V12 - Broadcast active")
                logger.info(f"✅ Broadcast channel connected: {broadcast_id}")
                return bot, broadcast_id
            except Exception as e:
                logger.warning(f"⚠️  Broadcast channel error: {e}")
                return bot, None
        else:
            logger.info("ℹ️  No broadcast channel configured (optional)")
            return bot, None
            
    except Exception as e:
        logger.error(f"❌ Telegram init failed: {e}")
        return None, None

bot, broadcast_channel = init_telegram()

# ============================================================================
# CONTRACT ABIs
# ============================================================================
# Aerodrome V2 Factory - PoolCreated event (3 indexed parameters!)
FACTORY_ABI = [
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "token0", "type": "address"},
            {"indexed": True, "name": "token1", "type": "address"},
            {"indexed": True, "name": "stable", "type": "bool"},
            {"indexed": False, "name": "pool", "type": "address"},
            {"indexed": False, "name": "", "type": "uint256"}
        ],
        "name": "PoolCreated",
        "type": "event"
    }
]

PAIR_ABI = [
    {
        "constant": True,
        "inputs": [],
        "name": "getReserves",
        "outputs": [
            {"name": "reserve0", "type": "uint112"},
            {"name": "reserve1", "type": "uint112"},
            {"name": "blockTimestampLast", "type": "uint32"}
        ],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [],
        "name": "token0",
        "outputs": [{"name": "", "type": "address"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [],
        "name": "token1",
        "outputs": [{"name": "", "type": "address"}],
        "type": "function"
    }
]

ERC20_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function"
    },
    {
        "constant": False,
        "inputs": [
            {"name": "_spender", "type": "address"},
            {"name": "_value", "type": "uint256"}
        ],
        "name": "approve",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [
            {"name": "_owner", "type": "address"},
            {"name": "_spender", "type": "address"}
        ],
        "name": "allowance",
        "outputs": [{"name": "", "type": "uint256"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [],
        "name": "symbol",
        "outputs": [{"name": "", "type": "string"}],
        "type": "function"
    }
]

ROUTER_ABI = [
    {
        "inputs": [
            {"name": "amountIn", "type": "uint256"},
            {"name": "amountOutMin", "type": "uint256"},
            {"name": "routes", "type": "tuple[]", "components": [
                {"name": "from", "type": "address"},
                {"name": "to", "type": "address"},
                {"name": "stable", "type": "bool"},
                {"name": "factory", "type": "address"}
            ]},
            {"name": "to", "type": "address"},
            {"name": "deadline", "type": "uint256"}
        ],
        "name": "swapExactETHForTokens",
        "outputs": [{"name": "amounts", "type": "uint256[]"}],
        "stateMutability": "payable",
        "type": "function"
    },
    {
        "inputs": [
            {"name": "amountIn", "type": "uint256"},
            {"name": "amountOutMin", "type": "uint256"},
            {"name": "routes", "type": "tuple[]", "components": [
                {"name": "from", "type": "address"},
                {"name": "to", "type": "address"},
                {"name": "stable", "type": "bool"},
                {"name": "factory", "type": "address"}
            ]},
            {"name": "to", "type": "address"},
            {"name": "deadline", "type": "uint256"}
        ],
        "name": "swapExactTokensForETH",
        "outputs": [{"name": "amounts", "type": "uint256[]"}],
        "stateMutability": "nonpayable",
        "type": "function"
    }
]

# ============================================================================
# POSITION TRACKING
# ============================================================================
positions = {}

# ============================================================================
# SECURITY CHECKS
# ============================================================================
def check_liquidity(pair_address: str) -> Tuple[bool, float]:
    try:
        pair_contract = w3.eth.contract(
            address=Web3.to_checksum_address(pair_address),
            abi=PAIR_ABI
        )
        
        token0 = pair_contract.functions.token0().call()
        token1 = pair_contract.functions.token1().call()
        reserves = pair_contract.functions.getReserves().call()
        
        if token0.lower() == CONFIG["WETH"].lower():
            weth_reserve = reserves[0]
        elif token1.lower() == CONFIG["WETH"].lower():
            weth_reserve = reserves[1]
        else:
            logger.warning(f"⚠️  Pool doesn't contain WETH")
            return False, 0.0
        
        weth_amount = float(w3.from_wei(weth_reserve, 'ether'))
        
        if weth_amount < CONFIG["MIN_LIQUIDITY_ETH"]:
            logger.info(f"❌ Insufficient liquidity: {weth_amount:.2f} ETH")
            return False, weth_amount
        
        logger.info(f"✅ Liquidity check passed: {weth_amount:.2f} ETH")
        return True, weth_amount
        
    except Exception as e:
        logger.error(f"❌ Liquidity check failed: {e}")
        return False, 0.0

def check_honeypot(token_address: str) -> bool:
    try:
        token_contract = w3.eth.contract(
            address=Web3.to_checksum_address(token_address),
            abi=ERC20_ABI
        )
        
        try:
            symbol = token_contract.functions.symbol().call()
            decimals = token_contract.functions.decimals().call()
            logger.info(f"🔍 Token: {symbol}, Decimals: {decimals}")
            return True
        except:
            logger.warning("⚠️  Cannot read token info - possible honeypot")
            return False
        
    except Exception as e:
        logger.error(f"❌ Honeypot check failed: {e}")
        return False

# ============================================================================
# TRADING FUNCTIONS
# ============================================================================
def execute_buy(token_address: str, pair_address: str) -> bool:
    if not account or not w3:
        logger.error("❌ Cannot trade - wallet not initialized")
        return False
    
    try:
        router_contract = w3.eth.contract(
            address=Web3.to_checksum_address(CONFIG["AERODROME_ROUTER"]),
            abi=ROUTER_ABI
        )
        
        amount_in = w3.to_wei(CONFIG["BUY_AMOUNT_ETH"], 'ether')
        deadline = int(time.time()) + 300
        
        route = [{
            "from": Web3.to_checksum_address(CONFIG["WETH"]),
            "to": Web3.to_checksum_address(token_address),
            "stable": False,
            "factory": Web3.to_checksum_address(CONFIG["AERODROME_FACTORY"])
        }]
        
        tx = router_contract.functions.swapExactETHForTokens(
            amount_in,
            0,
            route,
            account.address,
            deadline
        ).build_transaction({
            'from': account.address,
            'value': amount_in,
            'gas': 500000,
            'gasPrice': w3.eth.gas_price,
            'nonce': w3.eth.get_transaction_count(account.address)
        })
        
        signed_tx = account.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        
        logger.info(f"💸 BUY TX sent: {tx_hash.hex()}")
        
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        
        if receipt['status'] == 1:
            logger.info(f"✅ BUY successful!")
            
            token_contract = w3.eth.contract(
                address=Web3.to_checksum_address(token_address),
                abi=ERC20_ABI
            )
            balance = token_contract.functions.balanceOf(account.address).call()
            
            positions[token_address.lower()] = {
                "buy_price": CONFIG["BUY_AMOUNT_ETH"],
                "amount": balance,
                "timestamp": int(time.time()),
                "pair": pair_address
            }
            
            if bot:
                try:
                    symbol = token_contract.functions.symbol().call()
                    
                    # Private message to owner
                    if CONFIG.get("OWNER_ID"):
                        private_msg = (
                            f"🎯 **SNIPED!**\n\n"
                            f"Token: `{symbol}`\n"
                            f"Amount: `{CONFIG['BUY_AMOUNT_ETH']} ETH`\n"
                            f"TX: `{tx_hash.hex()[:10]}...`"
                        )
                        bot.send_message(CONFIG["OWNER_ID"], private_msg, parse_mode="Markdown")
                    
                    # Public broadcast to channel
                    if broadcast_channel:
                        public_msg = (
                            f"🎯 **NEW SNIPE**\n\n"
                            f"**Token:** `{symbol}`\n"
                            f"**Pair:** [{pair_address[:6]}...{pair_address[-4:]}](https://basescan.org/address/{pair_address})\n"
                            f"**Contract:** [{token_address[:6]}...{token_address[-4:]}](https://basescan.org/token/{token_address})\n"
                            f"**Amount:** {CONFIG['BUY_AMOUNT_ETH']} ETH\n"
                            f"**TX:** [View](https://basescan.org/tx/{tx_hash.hex()})\n\n"
                            f"✅ Liquidity check passed\n"
                            f"✅ Honeypot check passed\n\n"
                            f"⚡️ *Synthora Elite - Base/Aerodrome*"
                        )
                        bot.send_message(broadcast_channel, public_msg, parse_mode="Markdown", disable_web_page_preview=True)
                except Exception as e:
                    logger.error(f"Telegram notification error: {e}")
            
            return True
        else:
            logger.error("❌ BUY transaction failed")
            return False
            
    except Exception as e:
        logger.error(f"❌ Buy execution failed: {e}")
        return False

def execute_sell(token_address: str, percentage: float = 100) -> bool:
    if not account or not w3:
        return False
    
    try:
        token_contract = w3.eth.contract(
            address=Web3.to_checksum_address(token_address),
            abi=ERC20_ABI
        )
        balance = token_contract.functions.balanceOf(account.address).call()
        
        if balance == 0:
            return False
        
        sell_amount = int(balance * (percentage / 100))
        
        router_contract = w3.eth.contract(
            address=Web3.to_checksum_address(CONFIG["AERODROME_ROUTER"]),
            abi=ROUTER_ABI
        )
        
        allowance = token_contract.functions.allowance(
            account.address,
            CONFIG["AERODROME_ROUTER"]
        ).call()
        
        if allowance < sell_amount:
            logger.info("📝 Approving router...")
            approve_tx = token_contract.functions.approve(
                Web3.to_checksum_address(CONFIG["AERODROME_ROUTER"]),
                2**256 - 1
            ).build_transaction({
                'from': account.address,
                'gas': 100000,
                'gasPrice': w3.eth.gas_price,
                'nonce': w3.eth.get_transaction_count(account.address)
            })
            
            signed_approve = account.sign_transaction(approve_tx)
            approve_hash = w3.eth.send_raw_transaction(signed_approve.raw_transaction)
            w3.eth.wait_for_transaction_receipt(approve_hash)
            logger.info("✅ Approval successful")
        
        route = [{
            "from": Web3.to_checksum_address(token_address),
            "to": Web3.to_checksum_address(CONFIG["WETH"]),
            "stable": False,
            "factory": Web3.to_checksum_address(CONFIG["AERODROME_FACTORY"])
        }]
        
        deadline = int(time.time()) + 300
        
        sell_tx = router_contract.functions.swapExactTokensForETH(
            sell_amount,
            0,
            route,
            account.address,
            deadline
        ).build_transaction({
            'from': account.address,
            'gas': 500000,
            'gasPrice': w3.eth.gas_price,
            'nonce': w3.eth.get_transaction_count(account.address)
        })
        
        signed_sell = account.sign_transaction(sell_tx)
        sell_hash = w3.eth.send_raw_transaction(signed_sell.raw_transaction)
        
        logger.info(f"💰 SELL TX sent: {sell_hash.hex()}")
        
        receipt = w3.eth.wait_for_transaction_receipt(sell_hash, timeout=120)
        
        if receipt['status'] == 1:
            logger.info(f"✅ SELL successful ({percentage}%)!")
            
            if bot:
                try:
                    symbol = token_contract.functions.symbol().call()
                    
                    # Private message to owner
                    if CONFIG.get("OWNER_ID"):
                        private_msg = (
                            f"💰 **PROFIT TAKEN!**\n\n"
                            f"Token: `{symbol}`\n"
                            f"Sold: `{percentage}%`\n"
                            f"TX: `{sell_hash.hex()[:10]}...`"
                        )
                        bot.send_message(CONFIG["OWNER_ID"], private_msg, parse_mode="Markdown")
                    
                    # Public broadcast to channel
                    if broadcast_channel:
                        public_msg = (
                            f"💰 **TAKE PROFIT**\n\n"
                            f"**Token:** `{symbol}`\n"
                            f"**Sold:** {percentage}%\n"
                            f"**Target:** {CONFIG['TAKE_PROFIT_MULTIPLIER']}x achieved ✅\n"
                            f"**TX:** [View](https://basescan.org/tx/{sell_hash.hex()})\n\n"
                            f"⚡️ *Synthora Elite - Automated profit taking*"
                        )
                        bot.send_message(broadcast_channel, public_msg, parse_mode="Markdown", disable_web_page_preview=True)
                except Exception as e:
                    logger.error(f"Telegram notification error: {e}")
            
            return True
        else:
            logger.error("❌ SELL transaction failed")
            return False
            
    except Exception as e:
        logger.error(f"❌ Sell execution failed: {e}")
        return False

# ============================================================================
# SNIPER LOOP - WITH RATE LIMITING AND HEARTBEAT
# ============================================================================
def sniper_loop():
    if not w3:
        logger.error("❌ Cannot start sniper - no Web3 connection")
        return
    
    logger.info("🕵️  Synthora Sentinel: Jacht op Alpha is geopend...")
    
    try:
        factory_contract = w3.eth.contract(
            address=Web3.to_checksum_address(CONFIG["AERODROME_FACTORY"]),
            abi=FACTORY_ABI
        )
        
        last_block = w3.eth.block_number
        logger.info(f"📊 Starting from block: {last_block}")
        
        scan_count = 0  # Track scans for heartbeat
        
        while True:
            try:
                current_block = w3.eth.block_number
                
                if current_block > last_block:
                    # CRITICAL: Scan only 1 block at a time to avoid RPC errors
                    try:
                        events = factory_contract.events.PoolCreated.get_logs(
                            fromBlock=last_block + 1,
                            toBlock=last_block + 1
                        )
                        
                        for event in events:
                            token0 = event['args']['token0']
                            token1 = event['args']['token1']
                            pool = event['args']['pool']
                            
                            logger.info(f"🆕 New pool detected: {pool}")
                            
                            # Identify target token (not WETH)
                            if token0.lower() == CONFIG["WETH"].lower():
                                target_token = token1
                            elif token1.lower() == CONFIG["WETH"].lower():
                                target_token = token0
                            else:
                                logger.info("   ⏭️  Skipping - no WETH pair")
                                continue
                            
                            logger.info(f"🔍 Analyzing token: {target_token}")
                            
                            # Security checks
                            liq_ok, liq_amount = check_liquidity(pool)
                            if not liq_ok:
                                continue
                            
                            if not check_honeypot(target_token):
                                logger.warning("⚠️  Honeypot check failed - SKIPPING")
                                continue
                            
                            # Execute buy
                            logger.info("🎯 All checks passed - EXECUTING BUY")
                            execute_buy(target_token, pool)
                    
                    except Exception as e:
                        logger.error(f"❌ Event scan error: {e}")
                    
                    last_block += 1
                
                # Heartbeat: Log every 6 scans (30 seconds)
                scan_count += 1
                if scan_count % 6 == 0:
                    logger.info(f"💓 Heartbeat: Scanning block {current_block}, no new pools")
                
                # CRITICAL: 5 second rate limiting to avoid RPC errors
                time.sleep(5)
                
            except Exception as e:
                logger.error(f"❌ Sniper loop error: {e}")
                time.sleep(10)
                
    except Exception as e:
        logger.error(f"❌ Fatal sniper error: {e}")

# ============================================================================
# PROFIT MONITOR
# ============================================================================
def monitor_positions():
    logger.info("📊 Position monitor started")
    
    while True:
        try:
            if not positions or not w3:
                time.sleep(30)
                continue
            
            for token_address, position in list(positions.items()):
                try:
                    token_contract = w3.eth.contract(
                        address=Web3.to_checksum_address(token_address),
                        abi=ERC20_ABI
                    )
                    current_balance = token_contract.functions.balanceOf(account.address).call()
                    
                    if current_balance == 0:
                        del positions[token_address]
                        continue
                    
                    pair_contract = w3.eth.contract(
                        address=Web3.to_checksum_address(position['pair']),
                        abi=PAIR_ABI
                    )
                    
                    token0 = pair_contract.functions.token0().call()
                    reserves = pair_contract.functions.getReserves().call()
                    
                    if token0.lower() == CONFIG["WETH"].lower():
                        weth_reserve = reserves[0]
                        token_reserve = reserves[1]
                    else:
                        weth_reserve = reserves[1]
                        token_reserve = reserves[0]
                    
                    if token_reserve == 0:
                        continue
                    
                    price_per_token = float(w3.from_wei(weth_reserve, 'ether')) / float(w3.from_wei(token_reserve, 'ether'))
                    current_value = price_per_token * float(w3.from_wei(current_balance, 'ether'))
                    
                    multiplier = current_value / position['buy_price']
                    
                    if multiplier >= CONFIG["TAKE_PROFIT_MULTIPLIER"]:
                        logger.info(f"🚀 {multiplier:.2f}x PROFIT! Taking {CONFIG['SELL_PERCENTAGE']}%")
                        execute_sell(token_address, CONFIG["SELL_PERCENTAGE"])
                        position['amount'] = int(current_balance * (1 - CONFIG["SELL_PERCENTAGE"]/100))
                    
                except Exception as e:
                    logger.error(f"❌ Position monitor error: {e}")
            
            time.sleep(30)
            
        except Exception as e:
            logger.error(f"❌ Monitor loop error: {e}")
            time.sleep(30)

# ============================================================================
# TELEGRAM COMMANDS - FIXED
# ============================================================================
if bot and CONFIG.get("OWNER_ID"):
    @bot.message_handler(commands=['start', 'status'])
    def status_report(message):
        if message.from_user.id != CONFIG["OWNER_ID"]:
            return
        
        try:
            balance = w3.from_wei(w3.eth.get_balance(account.address), 'ether') if account else 0
            
            msg = (
                "🏙️ **SYNTHORA ELITE V12**\n\n"
                f"● **Status:** {'✅ Operational' if account else '❌ Wallet Error'}\n"
                f"● **Chain:** Base (ID: 8453)\n"
                f"● **Balans:** `{balance:.5f} ETH`\n"
                f"● **Wallet:** `{account.address[:8]}...{account.address[-6:]}`\n"
                f"● **Positions:** {len(positions)}\n"
                f"● **Buy Amount:** `{CONFIG['BUY_AMOUNT_ETH']} ETH`\n"
                f"● **Broadcast:** {'✅ Active' if broadcast_channel else '❌ Disabled'}"
            )
            bot.send_message(message.chat.id, msg, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Status command error: {e}")
            try:
                bot.send_message(message.chat.id, f"❌ Error: {str(e)}")
            except:
                pass
    
    @bot.message_handler(commands=['positions'])
    def show_positions(message):
        if message.from_user.id != CONFIG["OWNER_ID"]:
            return
        
        if not positions:
            bot.send_message(message.chat.id, "📊 No active positions")
            return
        
        try:
            msg = "📊 **ACTIVE POSITIONS:**\n\n"
            for token_addr, pos in positions.items():
                token_contract = w3.eth.contract(
                    address=Web3.to_checksum_address(token_addr),
                    abi=ERC20_ABI
                )
                symbol = token_contract.functions.symbol().call()
                balance = token_contract.functions.balanceOf(account.address).call()
                
                msg += f"**{symbol}**\n"
                msg += f"  Buy: `{pos['buy_price']} ETH`\n"
                msg += f"  Balance: `{w3.from_wei(balance, 'ether'):.4f}`\n\n"
            
            bot.send_message(message.chat.id, msg, parse_mode="Markdown")
        except Exception as e:
            try:
                bot.send_message(message.chat.id, f"❌ Error: {str(e)}")
            except:
                pass

# ============================================================================
# TELEGRAM POLLING
# ============================================================================
def run_telegram():
    if not bot:
        logger.warning("⚠️  Telegram bot not initialized - skipping polling")
        return
    
    logger.info("🤖 Starting Telegram polling...")
    
    while True:
        try:
            bot.polling(none_stop=True, timeout=60)
        except Exception as e:
            logger.error(f"Telegram polling error: {e}")
            time.sleep(10)

# ============================================================================
# FASTAPI APP
# ============================================================================
app = FastAPI(title="Synthora Elite V12")

@app.on_event("startup")
async def startup_event():
    """CRITICAL: Start background threads when FastAPI starts."""
    start_background_threads()

@app.get("/")
def health():
    return {
        "status": "Synthora Elite V12 Live",
        "wallet": account.address if account else "error",
        "connected": w3.is_connected() if w3 else False,
        "positions": len(positions),
        "telegram": bot is not None,
        "broadcast": broadcast_channel is not None
    }

@app.get("/balance")
def get_balance():
    if not account or not w3:
        return {"error": "Wallet not initialized"}
    
    try:
        balance = w3.from_wei(w3.eth.get_balance(account.address), 'ether')
        return {
            "address": account.address,
            "balance_eth": float(balance),
            "chain_id": w3.eth.chain_id,
            "positions": len(positions)
        }
    except Exception as e:
        return {"error": str(e)}

@app.get("/positions")
def get_positions():
    return {"positions": positions}

# ============================================================================
# BACKGROUND THREADS STARTUP
# ============================================================================
def start_background_threads():
    logger.info("🚀 Starting Synthora Elite threads...")
    
    # Start Telegram bot polling
    if bot:
        telegram_thread = Thread(target=run_telegram, daemon=True, name="TelegramBot")
        telegram_thread.start()
        logger.info("   ✅ Telegram thread started")
    
    # Start sniper loop
    if account and w3:
        sniper_thread = Thread(target=sniper_loop, daemon=True, name="Sniper")
        sniper_thread.start()
        logger.info("   ✅ Sniper thread started")
        
        # Start position monitor
        monitor_thread = Thread(target=monitor_positions, daemon=True, name="Monitor")
        monitor_thread.start()
        logger.info("   ✅ Monitor thread started")
    else:
        logger.error("   ❌ Cannot start trading threads - wallet not initialized")
    
    logger.info("✅ All threads started")

# ============================================================================
# MAIN ENTRY POINT
# ============================================================================
if __name__ == "__main__":
    import uvicorn
    
    start_background_threads()
    
    port = int(os.getenv("PORT", 8000))
    logger.info(f"🌐 Starting FastAPI on port {port}")
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info"
    )
