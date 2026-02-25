# -*- coding: utf-8 -*-
# ================================================================
#  ELITE TRADER v2.0 - Dual Wallet Edition
#  Trading: 0xaF2C5d0063C236C95BEF05ecE7079f818EFBBF38 (CDP)
#  Profits: 0xd048b06D3A775151652Ab3c544c6011755C61665 (MetaMask)
# ================================================================
import logging
import os
import asyncio
import time
from datetime import datetime
from web3 import Web3, AsyncWeb3
from web3.providers import AsyncHTTPProvider
from eth_account import Account
from eth_abi import decode as abi_decode
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
from fastapi import FastAPI
import uvicorn

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
logger = logging.getLogger("elite")

app = FastAPI()

try:
    from web3.middleware import geth_poa_middleware
    HAS_POA = True
except:
    HAS_POA = False

logger.info("💎 ELITE TRADER LOADING...")

# ================================================================
#  CONFIG
# ================================================================
BASE_RPC_URL = os.environ.get("BASE_RPC_URL", "https://base-mainnet.g.alchemy.com/v2/demo")
BASE_CHAIN_ID = 8453

AERODROME_ROUTER = "0xcF77a3Ba9A5CA399B7c97c74d54e5b1Beb874E43"
AERODROME_FACTORY = "0x420DD381b31aEf6683db6B902084cB0FFECe40Da"

WETH = "0x4200000000000000000000000000000000000006"
USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
DAI = "0x50c5725949A6F0c72E6C4a641F24049A917DB0Cb"
BASE_TOKENS = [WETH.lower(), USDC.lower(), DAI.lower()]

POOL_CREATED_TOPIC = "0x2128d88d14c80cb081c1252a5fe2505c553a6f3dd4644684c3d4eb42a915d7ba"

# WALLET ADDRESSES
TRADING_WALLET = "0xaF2C5d0063C236C95BEF05ecE7079f818EFBBF38"  # CDP wallet
METAMASK_WALLET = "0xd048b06D3A775151652Ab3c544c6011755C61665"  # Your MetaMask

config = {
    "active": False,
    "snipe_eth": 0.015,
    "take_profit_pct": 50,
    "trailing_stop_pct": 8,
    "hard_stop_pct": 25,
    "min_profit_to_trail": 12,
    "slippage_bps": 800,
    "min_liquidity_eth": 0.2,
    "max_liquidity_eth": 30.0,
    "max_token_age_blocks": 500,
    "honeypot_check": True,
    "max_positions": 6,
    "monitor_interval": 1.0,
    "daily_profit_target": 0.15,
    "max_daily_loss": 0.04,
    "max_daily_trades": 25,
    "min_balance_keep": 0.05,
}

positions = {}
blacklist = set()
seen_pools = set()

daily_stats = {"date": datetime.now().strftime("%Y-%m-%d"), "pnl": 0.0, "trades": 0, "withdrawn": 0.0}
stats = {"trades": 0, "wins": 0, "losses": 0, "total_pnl": 0.0, "best_trade": 0.0, "worst_trade": 0.0, "honeypots_blocked": 0, "started": time.time(), "total_volume": 0.0, "total_withdrawn": 0.0}

# ================================================================
#  WALLET SETUP - CDP WALLET
# ================================================================
def load_cdp_wallet():
    """Load CDP wallet from secret file or environment"""
    try:
        # Try secret file first
        secret_path = "/etc/secrets/CDP_WALLET_SECI"
        if os.path.exists(secret_path):
            with open(secret_path, 'r') as f:
                seed = f.read().strip()
            logger.info("✅ Loaded from secret file")
        else:
            # Fallback to environment
            seed = os.environ.get("ARCHITECT_SESSION_KEY", "")
            logger.info("✅ Loaded from environment")
        
        # Clean the key
        seed = seed.strip().replace('"', '').replace("'", '').replace('\n', '').replace(' ', '')
        
        if not seed or len(seed) < 64:
            logger.error("🔴 Private key too short or empty!")
            return None
        
        # Initialize wallet
        account = Account.from_key(seed)
        
        # Verify correct wallet
        if account.address.lower() == TRADING_WALLET.lower():
            logger.info("💎 Trading Wallet: %s ✅", account.address)
            logger.info("💸 Profits go to: %s", METAMASK_WALLET)
            return account
        else:
            logger.warning("⚠️ Wallet mismatch! Got: %s | Expected: %s", account.address, TRADING_WALLET)
            logger.info("💸 Profits will still go to: %s", METAMASK_WALLET)
            return account
            
    except Exception as e:
        logger.error("🔴 CDP Wallet error: %s", e)
        return None

signer = load_cdp_wallet()
my_addr = signer.address if signer else "0x0"

# ================================================================
#  WEB3
# ================================================================
aw3 = AsyncWeb3(AsyncHTTPProvider(BASE_RPC_URL))
if HAS_POA:
    aw3.middleware_onion.inject(geth_poa_middleware, layer=0)

w3s = Web3(Web3.HTTPProvider(BASE_RPC_URL))
if HAS_POA:
    w3s.middleware_onion.inject(geth_poa_middleware, layer=0)

ROUTER_ABI = [
    {"inputs":[{"internalType":"uint256","name":"amountIn","type":"uint256"},{"internalType":"address[]","name":"path","type":"address[]"}],"name":"getAmountsOut","outputs":[{"internalType":"uint256[]","name":"amounts","type":"uint256[]"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"internalType":"uint256","name":"amountOutMin","type":"uint256"},{"components":[{"internalType":"address","name":"from","type":"address"},{"internalType":"address","name":"to","type":"address"},{"internalType":"bool","name":"stable","type":"bool"},{"internalType":"address","name":"factory","type":"address"}],"internalType":"struct Router.Route[]","name":"routes","type":"tuple[]"},{"internalType":"address","name":"to","type":"address"},{"internalType":"uint256","name":"deadline","type":"uint256"}],"name":"swapExactETHForTokens","outputs":[{"internalType":"uint256[]","name":"amounts","type":"uint256[]"}],"stateMutability":"payable","type":"function"},
    {"inputs":[{"internalType":"uint256","name":"amountIn","type":"uint256"},{"internalType":"uint256","name":"amountOutMin","type":"uint256"},{"components":[{"internalType":"address","name":"from","type":"address"},{"internalType":"address","name":"to","type":"address"},{"internalType":"bool","name":"stable","type":"bool"},{"internalType":"address","name":"factory","type":"address"}],"internalType":"struct Router.Route[]","name":"routes","type":"tuple[]"},{"internalType":"address","name":"to","type":"address"},{"internalType":"uint256","name":"deadline","type":"uint256"}],"name":"swapExactTokensForETH","outputs":[{"internalType":"uint256[]","name":"amounts","type":"uint256[]"}],"stateMutability":"nonpayable","type":"function"},
]

ERC20_ABI = [
    {"constant":True,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"type":"function"},
    {"constant":False,"inputs":[{"name":"_spender","type":"address"},{"name":"_value","type":"uint256"}],"name":"approve","outputs":[{"name":"","type":"bool"}],"type":"function"},
    {"constant":True,"inputs":[{"name":"_owner","type":"address"},{"name":"_spender","type":"address"}],"name":"allowance","outputs":[{"name":"","type":"uint256"}],"type":"function"},
    {"constant":True,"inputs":[],"name":"decimals","outputs":[{"name":"","type":"uint8"}],"type":"function"},
    {"constant":True,"inputs":[],"name":"symbol","outputs":[{"name":"","type":"string"}],"type":"function"},
]

POOL_ABI = [
    {"inputs":[],"name":"token0","outputs":[{"internalType":"address","name":"","type":"address"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"token1","outputs":[{"internalType":"address","name":"","type":"address"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"getReserves","outputs":[{"internalType":"uint256","name":"_reserve0","type":"uint256"},{"internalType":"uint256","name":"_reserve1","type":"uint256"},{"internalType":"uint256","name":"_blockTimestampLast","type":"uint256"}],"stateMutability":"view","type":"function"},
]

router_c = aw3.eth.contract(address=Web3.to_checksum_address(AERODROME_ROUTER), abi=ROUTER_ABI)

# ================================================================
#  UTILITIES
# ================================================================
async def get_gas_params():
    try:
        base = await aw3.eth.gas_price
        tip = int(base * 0.1)
        maxf = int(base * 2.5)
        return {"maxFeePerGas": maxf, "maxPriorityFeePerGas": tip}
    except:
        return {"maxFeePerGas": int(5e9), "maxPriorityFeePerGas": int(1e9)}

async def send_tx(tx):
    signed = signer.sign_transaction(tx)
    txh = await aw3.eth.send_raw_transaction(signed.rawTransaction)
    return txh.hex()

def checksum(addr):
    return Web3.to_checksum_address(addr) if addr else None

async def parse_pool_log(log):
    try:
        decoded = abi_decode(["address", "address", "bool", "address", "uint256"], bytes.fromhex(log["data"][2:]))
        return (Web3.to_checksum_address(decoded[0]), Web3.to_checksum_address(decoded[1]), Web3.to_checksum_address(decoded[3]), decoded[2])
    except:
        return (None, None, None, None)

async def get_pool_liquidity_eth(pool_addr):
    try:
        pool_c = aw3.eth.contract(address=checksum(pool_addr), abi=POOL_ABI)
        t0, t1 = await pool_c.functions.token0().call(), await pool_c.functions.token1().call()
        r0, r1, _ = await pool_c.functions.getReserves().call()
        weth_res = r0 if t0.lower() in BASE_TOKENS else (r1 if t1.lower() in BASE_TOKENS else 0)
        return weth_res / 1e18
    except:
        return 0.0

async def is_honeypot(token_addr):
    if not config["honeypot_check"]:
        return False
    try:
        test_amt = 1000 * (10**18)
        out = await router_c.functions.getAmountsOut(test_amt, [WETH, token_addr]).call()
        token_out = out[-1] if out else 0
        if token_out == 0:
            return True
        sell_out = await router_c.functions.getAmountsOut(token_out, [token_addr, WETH]).call()
        eth_back = sell_out[-1] if sell_out else 0
        return (eth_back / test_amt if test_amt else 0) < 0.3
    except:
        return True

# ================================================================
#  WITHDRAW TO METAMASK
# ================================================================
async def withdraw_to_metamask(amount_eth):
    """Withdraw profits to MetaMask wallet"""
    try:
        balance = await aw3.eth.get_balance(my_addr)
        balance_eth = balance / 1e18
        available = balance_eth - config["min_balance_keep"]
        
        if available <= 0:
            return {"success": False, "error": f"Need {config['min_balance_keep']} ETH for gas"}
        
        if amount_eth > available:
            return {"success": False, "error": f"Max: {available:.4f} ETH"}
        
        amount_wei = int(amount_eth * 1e18)
        nonce = await aw3.eth.get_transaction_count(my_addr)
        gas_params = await get_gas_params()
        
        tx = {
            "to": checksum(METAMASK_WALLET),
            "value": amount_wei,
            "gas": 21000,
            "nonce": nonce,
            "chainId": BASE_CHAIN_ID,
            **gas_params
        }
        
        txh = await send_tx(tx)
        stats["total_withdrawn"] += amount_eth
        daily_stats["withdrawn"] += amount_eth
        
        logger.info("💸 WITHDRAW %.4f ETH → MetaMask | TX: %s", amount_eth, txh[:10])
        return {"success": True, "amount": amount_eth, "tx_hash": txh, "to": METAMASK_WALLET}
    except Exception as e:
        logger.error("🔴 Withdraw: %s", e)
        return {"success": False, "error": str(e)}

# ================================================================
#  TRADING
# ================================================================
async def buy_token(token_addr, pool_addr, buy_amt_eth):
    try:
        if daily_stats["pnl"] <= -config["max_daily_loss"] or daily_stats["trades"] >= config["max_daily_trades"]:
            return
        
        token_c = aw3.eth.contract(address=checksum(token_addr), abi=ERC20_ABI)
        try:
            sym = await asyncio.wait_for(token_c.functions.symbol().call(), timeout=2)
        except:
            sym = "???"

        if token_addr.lower() in blacklist or await is_honeypot(token_addr):
            blacklist.add(token_addr.lower())
            stats["honeypots_blocked"] += 1
            return

        amount_wei = int(buy_amt_eth * 1e18)
        route = [{"from": WETH, "to": token_addr, "stable": False, "factory": AERODROME_FACTORY}]
        
        try:
            out = await router_c.functions.getAmountsOut(amount_wei, [WETH, token_addr]).call()
            expected_tokens = out[-1]
        except:
            expected_tokens = 0

        min_out = int(expected_tokens * (1.0 - config["slippage_bps"] / 10000.0))
        nonce = await aw3.eth.get_transaction_count(my_addr)
        gas_params = await get_gas_params()
        
        tx = router_c.functions.swapExactETHForTokens(min_out, route, my_addr, int(time.time()) + 600).build_transaction({
            "from": my_addr, "value": amount_wei, "gas": 400000, "nonce": nonce, "chainId": BASE_CHAIN_ID, **gas_params
        })
        
        txh = await send_tx(tx)
        logger.info("✅ BUY %s | %s... | %.4f ETH", sym, txh[:8], buy_amt_eth)

        if tg_bot:
            try:
                await tg_bot.send_message(chat_id=OWNER_ID, text=f"🟢 **BUY**\n💎 {sym}\n💰 {buy_amt_eth:.4f} ETH", parse_mode="Markdown")
            except:
                pass

        await asyncio.sleep(3)
        balance = await token_c.functions.balanceOf(my_addr).call()
        if balance == 0:
            return

        allowance = await token_c.functions.allowance(my_addr, AERODROME_ROUTER).call()
        if allowance < balance:
            appr_tx = token_c.functions.approve(AERODROME_ROUTER, 2**256 - 1).build_transaction({
                "from": my_addr, "gas": 80000, "nonce": await aw3.eth.get_transaction_count(my_addr), "chainId": BASE_CHAIN_ID, **(await get_gas_params())
            })
            await send_tx(appr_tx)
            await asyncio.sleep(2)

        positions[token_addr] = {"symbol": sym, "pool": pool_addr, "balance": balance, "entry_eth": buy_amt_eth, "peak_eth": 0.0, "entry_time": time.time()}
        stats["trades"] += 1
        stats["total_volume"] += buy_amt_eth
        daily_stats["trades"] += 1
    except Exception as e:
        logger.error("🔴 Buy: %s", e)

async def sell_token(token_addr, reason="manual"):
    if token_addr not in positions:
        return
    pos = positions[token_addr]
    try:
        token_c = aw3.eth.contract(address=checksum(token_addr), abi=ERC20_ABI)
        bal = await token_c.functions.balanceOf(my_addr).call()
        if bal == 0:
            del positions[token_addr]
            return

        route = [{"from": token_addr, "to": WETH, "stable": False, "factory": AERODROME_FACTORY}]
        out_arr = await router_c.functions.getAmountsOut(bal, [token_addr, WETH]).call()
        expected_eth = out_arr[-1] / 1e18
        min_out = int((expected_eth * (1.0 - config["slippage_bps"] / 10000.0)) * 1e18)

        nonce = await aw3.eth.get_transaction_count(my_addr)
        tx = router_c.functions.swapExactTokensForETH(bal, min_out, route, my_addr, int(time.time()) + 600).build_transaction({
            "from": my_addr, "gas": 400000, "nonce": nonce, "chainId": BASE_CHAIN_ID, **(await get_gas_params())
        })
        
        txh = await send_tx(tx)
        pnl = expected_eth - pos["entry_eth"]
        pnl_pct = ((expected_eth / pos["entry_eth"]) - 1.0) * 100 if pos["entry_eth"] > 0 else 0
        hold_time = (time.time() - pos["entry_time"]) / 60
        
        stats["total_pnl"] += pnl
        daily_stats["pnl"] += pnl
        stats["wins" if pnl > 0 else "losses"] += 1
        if pnl > stats["best_trade"]:
            stats["best_trade"] = pnl
        if pnl < stats["worst_trade"]:
            stats["worst_trade"] = pnl
        
        emoji = "🟢" if pnl > 0 else "🔴"
        logger.info("%s SELL %s | %s | %.4f ETH | %+.1f%% | %.1fm", emoji, pos["symbol"], reason, expected_eth, pnl_pct, hold_time)

        if tg_bot:
            try:
                await tg_bot.send_message(chat_id=OWNER_ID, text=f"{emoji} **SELL**\n💎 {pos['symbol']}\n💰 {expected_eth:.4f} ETH\n📊 {pnl:+.4f} ETH ({pnl_pct:+.1f}%)\n⏱ {hold_time:.1f}m", parse_mode="Markdown")
            except:
                pass

        del positions[token_addr]
    except Exception as e:
        logger.error("🔴 Sell: %s", e)
        if token_addr in positions:
            del positions[token_addr]

async def process_new_token(token_addr, pool_addr, block_num):
    try:
        current_block = await aw3.eth.block_number
        age = current_block - block_num
        if age > config["max_token_age_blocks"] or pool_addr.lower() in seen_pools or len(positions) >= config["max_positions"]:
            return
        seen_pools.add(pool_addr.lower())

        liq_eth = await get_pool_liquidity_eth(pool_addr)
        if liq_eth < config["min_liquidity_eth"] or liq_eth > config["max_liquidity_eth"]:
            return

        token_c = aw3.eth.contract(address=checksum(token_addr), abi=ERC20_ABI)
        try:
            sym = await asyncio.wait_for(token_c.functions.symbol().call(), timeout=2)
        except:
            sym = "???"

        logger.info("🎯 %s | Liq: %.2f ETH | Age: %d", sym, liq_eth, age)
        await buy_token(token_addr, pool_addr, config["snipe_eth"])
    except Exception as e:
        logger.error("🔴 Process: %s", e)

# ================================================================
#  SCANNER & MONITOR
# ================================================================
async def scan_new_pools():
    logger.info("🔍 SCANNER STARTED")
    last_block = await aw3.eth.block_number
    
    while True:
        await asyncio.sleep(1.5)
        if not config["active"]:
            continue
        
        if daily_stats["date"] != datetime.now().strftime("%Y-%m-%d"):
            daily_stats.update({"date": datetime.now().strftime("%Y-%m-%d"), "pnl": 0.0, "trades": 0, "withdrawn": 0.0})
        
        if daily_stats["pnl"] >= config["daily_profit_target"]:
            config["active"] = False
            logger.info("🎯 TARGET! %.4f ETH", daily_stats["pnl"])
            continue
            
        try:
            current = await aw3.eth.block_number
            if current <= last_block:
                continue
                
            logger.info("🔎 Scan %d -> %d", last_block + 1, current)
            logs = await aw3.eth.get_logs({"fromBlock": last_block + 1, "toBlock": current, "topics": [[POOL_CREATED_TOPIC]]})
            
            if logs:
                logger.info("💎 %d pools", len(logs))
                tasks = []
                for log in logs:
                    t0, t1, pool, stable = await parse_pool_log(log)
                    if not t0 or not pool:
                        continue
                    blk = log.get("blockNumber", current)
                    if isinstance(blk, str):
                        blk = int(blk, 16)
                    if t0.lower() in BASE_TOKENS:
                        tasks.append(process_new_token(t1, pool, blk))
                    elif t1.lower() in BASE_TOKENS:
                        tasks.append(process_new_token(t0, pool, blk))
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
            last_block = current
        except Exception as e:
            logger.error("🔴 Scanner: %s", e)
            await asyncio.sleep(3)

async def monitor_positions():
    logger.info("👁️ MONITOR STARTED")
    while True:
        await asyncio.sleep(config["monitor_interval"])
        if not positions:
            continue
        for token, pos in list(positions.items()):
            try:
                bal = pos["balance"]
                route = [{"from": token, "to": WETH, "stable": False, "factory": AERODROME_FACTORY}]
                out = await router_c.functions.getAmountsOut(bal, [token, WETH]).call()
                current_eth = out[-1] / 1e18
                invested = pos["entry_eth"]
                pnl_pct = ((current_eth / invested) - 1.0) * 100 if invested > 0 else 0

                if current_eth > pos["peak_eth"]:
                    pos["peak_eth"] = current_eth
                peak = pos["peak_eth"]
                drop = ((peak - current_eth) / peak) * 100 if peak > 0 else 0
                peak_profit = ((peak / invested) - 1.0) * 100 if invested > 0 else 0

                if pnl_pct >= config["take_profit_pct"]:
                    await sell_token(token, f"TP +{pnl_pct:.1f}%")
                elif peak_profit >= config["min_profit_to_trail"] and drop >= config["trailing_stop_pct"]:
                    await sell_token(token, "Trail")
                elif pnl_pct <= -config["hard_stop_pct"]:
                    await sell_token(token, f"SL {pnl_pct:.1f}%")
            except Exception as e:
                logger.warning("⚠️ Monitor: %s", e)

# ================================================================
#  TELEGRAM
# ================================================================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

def get_main_keyboard():
    keyboard = [
        [InlineKeyboardButton("▶️ START", callback_data="start"), InlineKeyboardButton("⏸ STOP", callback_data="stop")],
        [InlineKeyboardButton("💰 STATUS", callback_data="status"), InlineKeyboardButton("📈 STATS", callback_data="stats")],
        [InlineKeyboardButton("💸 WITHDRAW", callback_data="withdraw"), InlineKeyboardButton("⚙️ SETTINGS", callback_data="settings")],
    ]
    return InlineKeyboardMarkup(keyboard)

async def cmd_start(update, context):
    if update.effective_user.id != OWNER_ID:
        return
    config["active"] = True
    balance = w3s.eth.get_balance(my_addr) / 1e18
    msg = f"🚀 **ELITE TRADER**\n\n"
    msg += f"💎 CDP: `{my_addr[:10]}...`\n"
    msg += f"💸 MetaMask: `{METAMASK_WALLET[:10]}...`\n\n"
    msg += f"💰 Balance: `{balance:.4f} ETH`\n"
    msg += f"🎯 Target: `{config['daily_profit_target']:.2f} ETH/day`\n\n"
    msg += f"✅ ACTIVE"
    await update.message.reply_text(msg, reply_markup=get_main_keyboard(), parse_mode="Markdown")
    logger.info("🚀 ACTIVATED")

async def cmd_menu(update, context):
    if update.effective_user.id != OWNER_ID:
        return
    balance = w3s.eth.get_balance(my_addr) / 1e18
    status = "🟢 ACTIVE" if config["active"] else "🔴 PAUSED"
    msg = f"**{status}**\n\n💰 Balance: `{balance:.4f} ETH`\n📈 Positions: `{len(positions)}`"
    await update.message.reply_text(msg, reply_markup=get_main_keyboard(), parse_mode="Markdown")

async def cmd_withdraw(update, context):
    if update.effective_user.id != OWNER_ID:
        return
    
    if len(context.args) < 1:
        balance = w3s.eth.get_balance(my_addr) / 1e18
        available = balance - config["min_balance_keep"]
        msg = f"**💸 WITHDRAW**\n\n"
        msg += f"💰 Balance: `{balance:.4f} ETH`\n"
        msg += f"✅ Available: `{available:.4f} ETH`\n"
        msg += f"📤 To: `{METAMASK_WALLET[:10]}...`\n\n"
        msg += f"Usage: `/withdraw <amount>`\n"
        msg += f"Example: `/withdraw 0.05`"
        await update.message.reply_text(msg, parse_mode="Markdown")
        return
    
    try:
        amount = float(context.args[0])
        if amount <= 0:
            await update.message.reply_text("❌ Amount must be > 0")
            return
        
        await update.message.reply_text(f"⏳ Withdrawing {amount:.4f} ETH...")
        result = await withdraw_to_metamask(amount)
        
        if result["success"]:
            msg = f"✅ **SUCCESS**\n\n"
            msg += f"💸 {result['amount']:.4f} ETH\n"
            msg += f"📤 To: `{result['to'][:10]}...`\n"
            msg += f"🔗 TX: `{result['tx_hash'][:12]}...`\n\n"
            msg += f"[BaseScan](https://basescan.org/tx/{result['tx_hash']})"
            await update.message.reply_text(msg, parse_mode="Markdown")
        else:
            await update.message.reply_text(f"❌ {result['error']}")
    except ValueError:
        await update.message.reply_text("❌ Invalid amount")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

async def button_handler(update, context):
    query = update.callback_query
    await query.answer()
    
    if query.from_user.id != OWNER_ID:
        return
    
    data = query.data
    
    if data == "start":
        config["active"] = True
        await query.edit_message_text("✅ **ACTIVATED**", parse_mode="Markdown")
    elif data == "stop":
        config["active"] = False
        await query.edit_message_text("⏸ **PAUSED**", parse_mode="Markdown")
    elif data == "status":
        balance = w3s.eth.get_balance(my_addr) / 1e18
        status = "🟢 ACTIVE" if config["active"] else "🔴 PAUSED"
        winrate = (stats["wins"] / stats["trades"] * 100) if stats["trades"] > 0 else 0
        msg = f"**{status}**\n\n💰 `{balance:.4f} ETH`\n📈 Pos: `{len(positions)}`\n\n"
        msg += f"💎 Daily: `{daily_stats['pnl']:+.4f} ETH`\n💸 Withdrawn: `{stats['total_withdrawn']:.4f} ETH`"
        await query.edit_message_text(msg, reply_markup=get_main_keyboard(), parse_mode="Markdown")
    elif data == "stats":
        winrate = (stats["wins"] / stats["trades"] * 100) if stats["trades"] > 0 else 0
        msg = f"**📈 STATS**\n\n🎲 Trades: `{stats['trades']}`\n✅ Wins: `{stats['wins']}`\n📊 WR: `{winrate:.1f}%`\n\n💰 P&L: `{stats['total_pnl']:+.4f} ETH`"
        await query.edit_message_text(msg, reply_markup=get_main_keyboard(), parse_mode="Markdown")
    elif data == "withdraw":
        balance = w3s.eth.get_balance(my_addr) / 1e18
        available = balance - config["min_balance_keep"]
        msg = f"**💸 WITHDRAW**\n\n✅ Available: `{available:.4f} ETH`\n\nUse: `/withdraw <amount>`"
        await query.edit_message_text(msg, reply_markup=get_main_keyboard(), parse_mode="Markdown")
    elif data == "settings":
        msg = f"**⚙️ SETTINGS**\n\n💰 Snipe: `{config['snipe_eth']:.3f} ETH`\n🎯 TP: `+{config['take_profit_pct']}%`"
        await query.edit_message_text(msg, reply_markup=get_main_keyboard(), parse_mode="Markdown")

async def cmd_set(update, context):
    if update.effective_user.id != OWNER_ID:
        return
    
    if len(context.args) < 2:
        msg = "**⚙️ SET**\n\n`/set minliq <val>`\n`/set snipe <val>`\n`/set tp <val>`\n`/set sl <val>`"
        await update.message.reply_text(msg, parse_mode="Markdown")
        return
    
    key, val = context.args[0].lower(), context.args[1]
    try:
        if key == "minliq":
            config["min_liquidity_eth"] = float(val)
            await update.message.reply_text(f"✅ Min liq: {val} ETH")
        elif key == "snipe":
            config["snipe_eth"] = float(val)
            await update.message.reply_text(f"✅ Snipe: {val} ETH")
        elif key == "tp":
            config["take_profit_pct"] = int(val)
            await update.message.reply_text(f"✅ TP: {val}%")
        elif key == "sl":
            config["hard_stop_pct"] = int(val)
            await update.message.reply_text(f"✅ SL: {val}%")
    except:
        await update.message.reply_text("❌ Error")

tg_bot = None

async def run_bot():
    global tg_bot
    await asyncio.sleep(2)
    tg_bot = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    tg_bot.add_handler(CommandHandler("start", cmd_start))
    tg_bot.add_handler(CommandHandler("menu", cmd_menu))
    tg_bot.add_handler(CommandHandler("withdraw", cmd_withdraw))
    tg_bot.add_handler(CommandHandler("set", cmd_set))
    tg_bot.add_handler(CallbackQueryHandler(button_handler))
    
    await tg_bot.initialize()
    await tg_bot.start()
    await tg_bot.updater.start_polling()
    logger.info("💬 Telegram active")

# ================================================================
#  FASTAPI
# ================================================================
@app.on_event("startup")
async def startup():
    asyncio.create_task(run_bot())
    asyncio.create_task(scan_new_pools())
    asyncio.create_task(monitor_positions())

@app.get("/")
async def health():
    balance = w3s.eth.get_balance(my_addr) / 1e18
    winrate = (stats["wins"] / stats["trades"] * 100) if stats["trades"] > 0 else 0
    return {
        "status": "🎯 ELITE TRADER v2.0",
        "active": config["active"],
        "trading_wallet": my_addr,
        "metamask_wallet": METAMASK_WALLET,
        "balance": round(balance, 6),
        "positions": len(positions),
        "daily_pnl": round(daily_stats["pnl"], 6),
        "total_pnl": round(stats["total_pnl"], 6),
        "total_withdrawn": round(stats["total_withdrawn"], 6),
        "win_rate": round(winrate, 2),
        "trades": stats["trades"],
    }

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
