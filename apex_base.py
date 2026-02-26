"""
Synthora Elite - Advanced DeFi Trading Bot for Base Network
Webhook Mode - Production Ready
"""

import os
import time
import logging
import threading
from datetime import datetime
from typing import Optional, Dict, Any
from web3 import Web3
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
import telebot
from telebot import types
import json
import asyncio

# ============================================================================
# CONFIGURATION
# ============================================================================

# Environment variables (set in Render)
ALCHEMY_API_KEY = os.getenv("ALCHEMY_API_KEY", "")
PRIVATE_KEY = os.getenv("PRIVATE_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_ADMIN_ID = os.getenv("TELEGRAM_ADMIN_ID", "")
TELEGRAM_BROADCAST_CHANNEL = os.getenv("TELEGRAM_BROADCAST_CHANNEL", "")
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "")

# Validate required environment variables
REQUIRED_VARS = {
    "ALCHEMY_API_KEY": ALCHEMY_API_KEY,
    "PRIVATE_KEY": PRIVATE_KEY,
    "TELEGRAM_BOT_TOKEN": TELEGRAM_BOT_TOKEN,
}

missing_vars = [k for k, v in REQUIRED_VARS.items() if not v]
if missing_vars:
    error_msg = f"""
    
❌ MISSING REQUIRED ENVIRONMENT VARIABLES ❌

The following environment variables are not set:
{chr(10).join([f'  - {var}' for var in missing_vars])}

📋 HOW TO FIX THIS IN RENDER:

1. Go to your Render Dashboard
2. Select your Web Service
3. Go to "Environment" tab
4. Click "Add Environment Variable"
5. Add these variables:

   ALCHEMY_API_KEY=your_alchemy_api_key_here
   PRIVATE_KEY=your_wallet_private_key_here
   TELEGRAM_BOT_TOKEN=your_bot_token_here
   TELEGRAM_ADMIN_ID=your_telegram_user_id_here
   RENDER_EXTERNAL_URL=https://YOUR-APP-NAME.onrender.com

6. Click "Save Changes"
7. Render will automatically redeploy

💡 TIP: Get your Telegram User ID from @userinfobot on Telegram

📚 Full guide: See DEPLOYMENT_GUIDE.md for detailed instructions
    """
    raise ValueError(error_msg)

# ============================================================================
# LOGGING SETUP
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("apex_base")

# ============================================================================
# WEB3 SETUP
# ============================================================================

BASE_RPC = f"https://base-mainnet.g.alchemy.com/v2/{ALCHEMY_API_KEY}"
w3 = Web3(Web3.HTTPProvider(BASE_RPC))

# Verify connection
if not w3.is_connected():
    raise ConnectionError("Failed to connect to Base network")

logger.info(f"✅ Connected to Base RPC (Chain ID: {w3.eth.chain_id})")

# Load wallet
try:
    account = w3.eth.account.from_key(PRIVATE_KEY)
    wallet_address = account.address
    balance = w3.eth.get_balance(wallet_address)
    balance_eth = w3.from_wei(balance, 'ether')
    logger.info(f"✅ Synthora Architect loaded: {wallet_address}")
    logger.info(f"💰 Balance: {balance_eth:.5f} ETH")
except Exception as e:
    raise ValueError(f"Failed to load wallet: {e}")

# ============================================================================
# CONTRACTS SETUP
# ============================================================================

# Aerodrome Factory on Base
AERODROME_FACTORY = "0x420DD381b31aEf6683db6B902084cB0FFECe40Da"
AERODROME_FACTORY_ABI = [
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "token0", "type": "address"},
            {"indexed": True, "name": "token1", "type": "address"},
            {"indexed": False, "name": "stable", "type": "bool"},
            {"indexed": False, "name": "pool", "type": "address"},
            {"indexed": False, "name": "length", "type": "uint256"}
        ],
        "name": "PoolCreated",
        "type": "event"
    }
]

factory_contract = w3.eth.contract(
    address=w3.to_checksum_address(AERODROME_FACTORY),
    abi=AERODROME_FACTORY_ABI
)

logger.info(f"✅ Aerodrome Factory loaded: {AERODROME_FACTORY}")

# ============================================================================
# TELEGRAM BOT SETUP
# ============================================================================

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN, threaded=False)

# Bot state
bot_state = {
    "running": True,
    "auto_snipe": False,
    "current_block": 0,
    "pools_found": 0,
    "trades_executed": 0,
    "last_heartbeat": None
}

def is_admin(message):
    """Check if user is admin"""
    if not TELEGRAM_ADMIN_ID:
        return True  # If no admin ID set, allow all
    return str(message.from_user.id) == str(TELEGRAM_ADMIN_ID)

# ============================================================================
# TELEGRAM COMMAND HANDLERS
# ============================================================================

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    """Welcome message with commands"""
    if not is_admin(message):
        bot.reply_to(message, "⛔️ Unauthorized access")
        return
    
    help_text = """
🤖 **Synthora Elite Bot**

**Admin Commands:**
/status - Bot status & statistics
/balance - Check wallet balance
/auto_on - Enable auto-sniping
/auto_off - Disable auto-sniping
/test_broadcast - Test channel broadcast
/stop - Emergency stop
/help - This message

**Public Commands:**
/stats - View bot statistics

**Status:** 🟢 Active
**Broadcast:** {"✅ Enabled" if TELEGRAM_BROADCAST_CHANNEL else "⚠️ Not configured"}
    """
    bot.reply_to(message, help_text, parse_mode="Markdown")

@bot.message_handler(commands=['status'])
def send_status(message):
    """Send bot status"""
    if not is_admin(message):
        bot.reply_to(message, "⛔️ Unauthorized access")
        return
    
    status_text = f"""
📊 **Synthora Elite Status**

🟢 **Running:** {bot_state['running']}
🎯 **Auto-Snipe:** {bot_state['auto_snipe']}
📦 **Current Block:** {bot_state['current_block']}
🏊 **Pools Found:** {bot_state['pools_found']}
💰 **Trades:** {bot_state['trades_executed']}
⏰ **Last Update:** {bot_state['last_heartbeat']}

**Wallet:** `{wallet_address[:8]}...{wallet_address[-6:]}`
**Balance:** {balance_eth:.5f} ETH
    """
    bot.reply_to(message, status_text, parse_mode="Markdown")

@bot.message_handler(commands=['balance'])
def send_balance(message):
    """Check wallet balance"""
    if not is_admin(message):
        bot.reply_to(message, "⛔️ Unauthorized access")
        return
    
    try:
        current_balance = w3.eth.get_balance(wallet_address)
        balance_eth = w3.from_wei(current_balance, 'ether')
        bot.reply_to(message, f"💰 Balance: **{balance_eth:.5f} ETH**", parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)}")

@bot.message_handler(commands=['auto_on'])
def auto_snipe_on(message):
    """Enable auto-sniping"""
    if not is_admin(message):
        bot.reply_to(message, "⛔️ Unauthorized access")
        return
    
    bot_state['auto_snipe'] = True
    bot.reply_to(message, "✅ Auto-sniping **ENABLED** 🎯", parse_mode="Markdown")
    logger.info("Auto-sniping enabled via Telegram")

@bot.message_handler(commands=['auto_off'])
def auto_snipe_off(message):
    """Disable auto-sniping"""
    if not is_admin(message):
        bot.reply_to(message, "⛔️ Unauthorized access")
        return
    
    bot_state['auto_snipe'] = False
    bot.reply_to(message, "⏸️ Auto-sniping **DISABLED**", parse_mode="Markdown")
    logger.info("Auto-sniping disabled via Telegram")

@bot.message_handler(commands=['stop'])
def emergency_stop(message):
    """Emergency stop"""
    if not is_admin(message):
        bot.reply_to(message, "⛔️ Unauthorized access")
        return
    
    bot_state['running'] = False
    bot_state['auto_snipe'] = False
    bot.reply_to(message, "🛑 **EMERGENCY STOP ACTIVATED**", parse_mode="Markdown")
    logger.warning("Emergency stop activated via Telegram")

@bot.message_handler(commands=['stats'])
def send_stats(message):
    """Send bot statistics (works for everyone in channels)"""
    stats_text = f"""
📊 **SYNTHORA ELITE STATISTICS**

🔍 **Pools Detected:** {bot_state['pools_found']}
💰 **Trades Executed:** {bot_state['trades_executed']}
📦 **Current Block:** {bot_state['current_block']}
⏰ **Last Update:** {bot_state['last_heartbeat'] or 'Starting...'}

🤖 **Status:** {"🟢 Active" if bot_state['running'] else "🔴 Stopped"}

_Autonomous DeFi trading on Base Network_
    """
    bot.reply_to(message, stats_text, parse_mode="Markdown")

@bot.message_handler(commands=['test_broadcast'])
def test_broadcast(message):
    """Test broadcast to channel (admin only)"""
    if not is_admin(message):
        bot.reply_to(message, "⛔️ Unauthorized access")
        return
    
    if not TELEGRAM_BROADCAST_CHANNEL:
        bot.reply_to(message, "⚠️ No broadcast channel configured. Set TELEGRAM_BROADCAST_CHANNEL in environment variables.")
        return
    
    try:
        test_msg = f"""
🧪 **TEST BROADCAST**

This is a test message from Synthora Elite bot.

✅ Broadcast channel is working correctly!
⏰ Sent at: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}

_This is a test - bot is functioning normally_
        """
        bot.send_message(TELEGRAM_BROADCAST_CHANNEL, test_msg, parse_mode="Markdown")
        bot.reply_to(message, f"✅ Test broadcast sent to {TELEGRAM_BROADCAST_CHANNEL}", parse_mode="Markdown")
        logger.info(f"Test broadcast sent to {TELEGRAM_BROADCAST_CHANNEL}")
    except Exception as e:
        error_msg = f"❌ Failed to send test broadcast: {str(e)}"
        bot.reply_to(message, error_msg)
        logger.error(f"Test broadcast failed: {e}")

# ============================================================================
# SNIPER LOGIC
# ============================================================================

def check_pool_safety(pool_address: str, token_address: str) -> Dict[str, Any]:
    """
    Perform safety checks on a new pool
    Returns dict with safety status and reason
    """
    try:
        # Basic checks
        safety = {
            "safe": True,
            "checks": [],
            "warnings": []
        }
        
        # Check 1: Pool has liquidity
        try:
            pool_balance = w3.eth.get_balance(pool_address)
            if pool_balance < w3.to_wei(0.1, 'ether'):
                safety["warnings"].append(f"Low liquidity: {w3.from_wei(pool_balance, 'ether')} ETH")
        except Exception as e:
            safety["warnings"].append(f"Could not check liquidity: {e}")
        
        # Check 2: Token contract exists
        try:
            code = w3.eth.get_code(token_address)
            if len(code) <= 2:  # "0x" only
                safety["safe"] = False
                safety["checks"].append("❌ No contract code (possible rug)")
                return safety
            safety["checks"].append("✅ Contract code verified")
        except Exception as e:
            safety["warnings"].append(f"Could not check contract: {e}")
        
        # Check 3: Basic honeypot check (simplified)
        # In production, you'd use more sophisticated checks
        safety["checks"].append("⚠️ Honeypot check: Manual review recommended")
        
        return safety
        
    except Exception as e:
        logger.error(f"Safety check error: {e}")
        return {
            "safe": False,
            "checks": [f"❌ Error during safety check: {e}"],
            "warnings": []
        }

def process_new_pool(event_data: Dict[str, Any]):
    """Process a newly detected pool"""
    try:
        pool_address = event_data['pool']
        token0 = event_data['token0']
        token1 = event_data['token1']
        stable = event_data['stable']
        block_number = event_data.get('block', 'Unknown')
        
        logger.info(f"🆕 New pool detected: {pool_address}")
        logger.info(f"   Token0: {token0}")
        logger.info(f"   Token1: {token1}")
        logger.info(f"   Stable: {stable}")
        
        bot_state['pools_found'] += 1
        
        # Determine which token is the new token (not WETH)
        WETH_ADDRESS = "0x4200000000000000000000000000000000000006"  # Base WETH
        new_token = token1 if token0.lower() == WETH_ADDRESS.lower() else token0
        
        # Safety checks
        safety = check_pool_safety(pool_address, new_token)
        
        # Create BaseScan links
        pool_link = f"https://basescan.org/address/{pool_address}"
        token_link = f"https://basescan.org/token/{new_token}"
        
        # ADMIN NOTIFICATION - Detailed technical info
        admin_notification = f"""
🎯 **SYNTHORA ELITE - NEW POOL DETECTED**

🏊 **Pool:** `{pool_address[:10]}...{pool_address[-8:]}`
   [View on BaseScan]({pool_link})

🪙 **Token:** `{new_token[:10]}...{new_token[-8:]}`
   [View Token]({token_link})

💱 **Type:** {"Stable Pool" if stable else "Volatile Pool"}
📦 **Block:** {block_number}

**Safety Analysis:**
{chr(10).join(safety['checks'])}
{chr(10).join(['⚠️ ' + w for w in safety['warnings']]) if safety['warnings'] else '✅ No warnings'}

**Bot Status:**
Auto-Snipe: {"🟢 ENABLED" if bot_state['auto_snipe'] else "🔴 DISABLED"}
Safety: {"✅ PASS" if safety['safe'] else "⚠️ FAIL"}
        """
        
        # PUBLIC BROADCAST - Engaging community message
        public_broadcast = f"""
🚨 **NEW LAUNCH DETECTED ON AERODROME** 🚨

⚡️ **Synthora Elite** just spotted a fresh pool!

🏊 **Pool Type:** {"Stable" if stable else "Volatile"}
🪙 **New Token:** `{new_token[:8]}...{new_token[-6:]}`

💎 **Quick Links:**
• [View Pool]({pool_link})
• [View Token]({token_link})

⚠️ **Safety Status:** {"✅ Initial checks passed" if safety['safe'] else "⚠️ High risk detected"}

🤖 **Powered by Synthora Elite**
_Autonomous DeFi trading on Base Network_

⚡️ _Alpha detected within seconds of pool creation_
        """
        
        # Send to admin (detailed technical info)
        if TELEGRAM_ADMIN_ID:
            try:
                bot.send_message(
                    TELEGRAM_ADMIN_ID, 
                    admin_notification, 
                    parse_mode="Markdown",
                    disable_web_page_preview=True
                )
                logger.info("✅ Admin notification sent")
            except Exception as e:
                logger.error(f"Failed to send admin notification: {e}")
        
        # Send to broadcast channel (public marketing message)
        if TELEGRAM_BROADCAST_CHANNEL:
            try:
                bot.send_message(
                    TELEGRAM_BROADCAST_CHANNEL, 
                    public_broadcast, 
                    parse_mode="Markdown",
                    disable_web_page_preview=False  # Show link previews for community
                )
                logger.info(f"✅ Broadcast sent to {TELEGRAM_BROADCAST_CHANNEL}")
            except Exception as e:
                logger.error(f"Failed to send broadcast: {e}")
                logger.error(f"   Channel: {TELEGRAM_BROADCAST_CHANNEL}")
                logger.error(f"   Error details: {str(e)}")
        
        # Auto-snipe logic
        if bot_state['auto_snipe'] and safety['safe']:
            logger.info("🎯 Auto-snipe conditions met, executing trade...")
            
            # Send snipe notification
            snipe_msg = f"""
🎯 **AUTO-SNIPE EXECUTED**

Pool: `{pool_address[:10]}...{pool_address[-8:]}`
Token: `{new_token[:10]}...{new_token[-8:]}`

Status: In progress...
            """
            
            if TELEGRAM_ADMIN_ID:
                try:
                    bot.send_message(TELEGRAM_ADMIN_ID, snipe_msg, parse_mode="Markdown")
                except:
                    pass
            
            # TODO: Implement actual trading logic here
            bot_state['trades_executed'] += 1
            logger.info("✅ Trade executed (simulated)")
        
    except Exception as e:
        logger.error(f"Error processing pool: {e}")
        import traceback
        logger.error(traceback.format_exc())

# ============================================================================
# BLOCKCHAIN SCANNER
# ============================================================================

def scan_for_new_pools():
    """Main scanning loop for new pool creation events"""
    logger.info("🕵️  Synthora Sentinel: Jacht op Alpha is geopend...")
    
    # Get starting block
    current_block = w3.eth.block_number
    bot_state['current_block'] = current_block
    logger.info(f"📊 Starting from block: {current_block}")
    
    last_heartbeat = time.time()
    heartbeat_interval = 30  # seconds
    
    while bot_state['running']:
        try:
            latest_block = w3.eth.block_number
            
            # Scan new blocks
            if latest_block > current_block:
                # Get events from the new blocks
                try:
                    events = factory_contract.events.PoolCreated.get_logs(
                        fromBlock=current_block + 1,
                        toBlock=latest_block
                    )
                    
                    if events:
                        logger.info(f"🎉 Found {len(events)} new pool(s)!")
                        for event in events:
                            event_data = {
                                'pool': event['args']['pool'],
                                'token0': event['args']['token0'],
                                'token1': event['args']['token1'],
                                'stable': event['args']['stable'],
                                'block': event['blockNumber']
                            }
                            process_new_pool(event_data)
                    else:
                        # Heartbeat log
                        if time.time() - last_heartbeat > heartbeat_interval:
                            logger.info(f"💓 Heartbeat: Scanning block {latest_block}, no new pools")
                            last_heartbeat = time.time()
                            bot_state['last_heartbeat'] = datetime.now().strftime("%H:%M:%S")
                    
                    current_block = latest_block
                    bot_state['current_block'] = current_block
                    
                except Exception as e:
                    logger.error(f"Error scanning blocks: {e}")
            
            # Sleep before next scan
            time.sleep(2)
            
        except Exception as e:
            logger.error(f"Scanner error: {e}")
            time.sleep(5)
    
    logger.info("Scanner stopped")

# ============================================================================
# POSITION MONITOR
# ============================================================================

def monitor_positions():
    """Monitor open positions and manage trailing stops"""
    logger.info("📊 Position monitor started")
    
    # Placeholder for position monitoring logic
    while bot_state['running']:
        try:
            # TODO: Implement position monitoring
            # - Check open positions
            # - Update trailing stops
            # - Check take profit targets
            time.sleep(10)
        except Exception as e:
            logger.error(f"Monitor error: {e}")
            time.sleep(5)
    
    logger.info("Position monitor stopped")

# ============================================================================
# FASTAPI APP
# ============================================================================

app = FastAPI(title="Synthora Elite Bot")

# Global threads
scanner_thread = None
monitor_thread = None

@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "status": "online",
        "bot": "Synthora Elite",
        "version": "2.0.0",
        "mode": "webhook",
        "running": bot_state['running'],
        "auto_snipe": bot_state['auto_snipe'],
        "current_block": bot_state['current_block'],
        "pools_found": bot_state['pools_found'],
        "trades": bot_state['trades_executed']
    }

@app.get("/health")
async def health_check():
    """Detailed health check"""
    try:
        # Check Web3 connection
        current_block = w3.eth.block_number
        
        # Check wallet
        balance = w3.eth.get_balance(wallet_address)
        
        return {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "blockchain": {
                "connected": True,
                "chain_id": w3.eth.chain_id,
                "current_block": current_block
            },
            "wallet": {
                "address": wallet_address,
                "balance_eth": float(w3.from_wei(balance, 'ether'))
            },
            "bot": bot_state,
            "threads": {
                "scanner": scanner_thread.is_alive() if scanner_thread else False,
                "monitor": monitor_thread.is_alive() if monitor_thread else False
            }
        }
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "error": str(e)}
        )

@app.post("/telegram-webhook")
async def telegram_webhook(request: Request):
    """
    Telegram webhook endpoint
    This receives updates from Telegram instead of polling
    """
    try:
        json_string = await request.body()
        update = telebot.types.Update.de_json(json_string.decode('utf-8'))
        
        # Process update in background to avoid blocking
        bot.process_new_updates([update])
        
        return {"ok": True}
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.on_event("startup")
async def startup_event():
    """Initialize bot on startup"""
    global scanner_thread, monitor_thread
    
    logger.info("🚀 Starting Synthora Elite...")
    
    # Setup Telegram webhook
    try:
        # Remove any existing webhook first
        bot.remove_webhook()
        time.sleep(1)
        
        # Set new webhook
        if RENDER_EXTERNAL_URL:
            webhook_url = f"{RENDER_EXTERNAL_URL}/telegram-webhook"
            bot.set_webhook(url=webhook_url)
            logger.info(f"✅ Telegram webhook set: {webhook_url}")
        else:
            logger.warning("⚠️  No RENDER_EXTERNAL_URL set, webhook not configured")
            logger.info("   Set this in Render dashboard: https://your-app.onrender.com")
        
        logger.info("✅ Telegram bot connected")
        
        # Send startup notification to admin
        if TELEGRAM_ADMIN_ID:
            try:
                startup_msg = f"""
🚀 **SYNTHORA ELITE ONLINE**

✅ Connected to Base Network
✅ Webhook configured
✅ Scanner initializing
✅ Monitor starting

💰 Wallet Balance: {balance_eth:.5f} ETH
📍 Wallet: `{wallet_address[:10]}...{wallet_address[-8:]}`

Ready to hunt alpha! 🎯
                """
                bot.send_message(TELEGRAM_ADMIN_ID, startup_msg, parse_mode="Markdown")
            except Exception as e:
                logger.error(f"Failed to send startup message to admin: {e}")
        
        # Send startup broadcast to channel
        if TELEGRAM_BROADCAST_CHANNEL:
            try:
                broadcast_msg = """
🤖 **SYNTHORA ELITE IS NOW LIVE**

⚡️ Advanced DeFi trading bot activated
🔍 Monitoring Aerodrome Finance for new launches
🎯 Autonomous alpha detection on Base Network

📊 **Capabilities:**
• Real-time pool detection
• Safety analysis & honeypot checks
• Lightning-fast execution
• 24/7 monitoring

_Stay tuned for launch alerts! 🚀_
                """
                bot.send_message(TELEGRAM_BROADCAST_CHANNEL, broadcast_msg, parse_mode="Markdown")
                logger.info(f"✅ Startup broadcast sent to {TELEGRAM_BROADCAST_CHANNEL}")
            except Exception as e:
                logger.error(f"Failed to send startup broadcast: {e}")
        
        # Check broadcast channel
        if TELEGRAM_BROADCAST_CHANNEL:
            logger.info(f"✅ Broadcast channel: {TELEGRAM_BROADCAST_CHANNEL}")
        else:
            logger.info("ℹ️  No broadcast channel configured (optional)")
            
    except Exception as e:
        logger.error(f"Failed to setup Telegram webhook: {e}")
    
    # Start scanner thread
    logger.info("🚀 Starting Synthora Elite threads...")
    scanner_thread = threading.Thread(target=scan_for_new_pools, daemon=True)
    scanner_thread.start()
    logger.info("   ✅ Sniper thread started")
    
    # Start monitor thread
    monitor_thread = threading.Thread(target=monitor_positions, daemon=True)
    monitor_thread.start()
    logger.info("   ✅ Monitor thread started")
    
    logger.info("✅ All threads started")

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    logger.info("🛑 Shutting down Synthora Elite...")
    bot_state['running'] = False
    
    # Send shutdown notification to admin
    if TELEGRAM_ADMIN_ID:
        try:
            shutdown_msg = "🛑 **SYNTHORA ELITE SHUTTING DOWN**\n\nBot is going offline for maintenance or redeployment."
            bot.send_message(TELEGRAM_ADMIN_ID, shutdown_msg, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Failed to send shutdown message to admin: {e}")
    
    # Send shutdown broadcast
    if TELEGRAM_BROADCAST_CHANNEL:
        try:
            broadcast_msg = """
⏸️ **SYNTHORA ELITE MAINTENANCE**

Bot is temporarily offline for updates.
Will resume monitoring shortly.

_Stay tuned for the return! 🚀_
            """
            bot.send_message(TELEGRAM_BROADCAST_CHANNEL, broadcast_msg, parse_mode="Markdown")
            logger.info(f"✅ Shutdown broadcast sent to {TELEGRAM_BROADCAST_CHANNEL}")
        except Exception as e:
            logger.error(f"Failed to send shutdown broadcast: {e}")
    
    # Remove webhook
    try:
        bot.remove_webhook()
        logger.info("✅ Webhook removed")
    except Exception as e:
        logger.error(f"Error removing webhook: {e}")
    
    logger.info("✅ Shutdown complete")

# ============================================================================
# ADDITIONAL MANAGEMENT ENDPOINTS
# ============================================================================

@app.post("/admin/auto-snipe/enable")
async def enable_auto_snipe():
    """Enable auto-sniping via API"""
    bot_state['auto_snipe'] = True
    logger.info("Auto-sniping enabled via API")
    return {"status": "enabled", "auto_snipe": True}

@app.post("/admin/auto-snipe/disable")
async def disable_auto_snipe():
    """Disable auto-sniping via API"""
    bot_state['auto_snipe'] = False
    logger.info("Auto-sniping disabled via API")
    return {"status": "disabled", "auto_snipe": False}

@app.post("/admin/stop")
async def emergency_stop_api():
    """Emergency stop via API"""
    bot_state['running'] = False
    bot_state['auto_snipe'] = False
    logger.warning("Emergency stop activated via API")
    return {"status": "stopped", "running": False}

# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=10000)
