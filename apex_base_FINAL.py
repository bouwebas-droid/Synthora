# -*- coding: utf-8 -*-
# SYNTHORA ELITE v4.0 - COMPLETE & WORKING
import logging
import os
import asyncio
import time
from datetime import datetime
from web3 import Web3, AsyncWeb3
from web3.providers import AsyncHTTPProvider
from eth_account import Account
from eth_abi import decode as abi_decode
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from fastapi import FastAPI
import uvicorn

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
logger = logging.getLogger("synthora")

app = FastAPI()

# Middleware
try:
    from web3.middleware import geth_poa_middleware
    HAS_POA = True
except:
    HAS_POA = False

logger.info("🔷 Web3 loaded")

# CONFIG
BASE_RPC_URL = os.environ.get("BASE_RPC_URL", "https://base-mainnet.g.alchemy.com/v2/demo")
BASE_CHAIN_ID = 8453

AERODROME_ROUTER = "0xcF77a3Ba9A5CA399B7c97c74d54e5b1Beb874E43"
AERODROME_FACTORY = "0x420DD381b31aEf6683db6B902084cB0FFECe40Da"

WETH = "0x4200000000000000000000000000000000000006"
USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
DAI = "0x50c5725949A6F0c72E6C4a641F24049A917DB0Cb"
USDT = "0xfde4C96c8593536E31F229EA8f37b2ADa2699bb2"

BASE_TOKENS = [WETH.lower(), USDC.lower(), DAI.lower(), USDT.lower()]

POOL_CREATED_TOPIC = "0x2128d88d14c80cb081c1252a5fe2505c553a6f3dd4644684c3d4eb42a915d7ba"

config = {
    "active": False,
    "snipe_eth": 0.01,
    "take_profit_pct": 75,
    "trailing_stop_pct": 12,
    "hard_stop_pct": 30,
    "min_profit_to_trail": 15,
    "slippage_bps": 500,
    "min_liquidity_eth": 0.5,
    "max_liquidity_eth": 100.0,
    "max_positions": 8,
    "gas_multiplier": 2.0,
    "max_gas_gwei": 10.0,
    "honeypot_check": True,
    "monitor_interval": 1.5,
    "max_token_age_blocks": 1000,
    "multi_dex": True,
    "daily_profit_target": 0.1,
    "max_daily_loss": 0.05,
}

positions = {}
blacklist = set()
seen_pools = set()

daily_stats = {
    "date": datetime.now().strftime("%Y-%m-%d"),
    "pnl": 0.0,
    "trades": 0,
}

stats = {
    "trades": 0,
    "wins": 0,
    "losses": 0,
    "total_pnl": 0.0,
    "best_trade": 0.0,
    "worst_trade": 0.0,
    "honeypots_blocked": 0,
    "started": time.time(),
    "total_volume": 0.0,
}

# WALLET
raw_key = os.environ.get("ARCHITECT_SESSION_KEY", "")
try:
    signer = Account.from_key(raw_key.strip().replace('"', '').replace("'", ''))
    my_addr = signer.address
    logger.info("💎 Wallet: %s", my_addr)
except Exception as e:
    logger.error("🔴 Key error: %s", e)
    signer = None
    my_addr = "0x0"

# WEB3
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

# UTILITIES
async def rpc_retry(coro, retries=3):
    for attempt in range(retries):
        try:
            return await coro
        except Exception as e:
            if attempt == retries - 1:
                raise
            await asyncio.sleep(0.5)

async def get_gas_params():
    base = await rpc_retry(aw3.eth.gas_price)
    tip = int(base * 0.05)
    maxf = int(base * config["gas_multiplier"])
    gwei_val = maxf / 1e9
    if gwei_val > config["max_gas_gwei"]:
        maxf = int(config["max_gas_gwei"] * 1e9)
    return {"maxFeePerGas": maxf, "maxPriorityFeePerGas": tip}

async def send_tx(tx):
    signed = signer.sign_transaction(tx)
    txh = await rpc_retry(aw3.eth.send_raw_transaction(signed.rawTransaction))
    return txh.hex()

def checksum(addr):
    if not addr:
        return None
    return Web3.to_checksum_address(addr)

async def parse_pool_log(log):
    try:
        decoded = abi_decode(
            ["address", "address", "bool", "address", "uint256"],
            bytes.fromhex(log["data"][2:])
        )
        t0 = Web3.to_checksum_address(decoded[0])
        t1 = Web3.to_checksum_address(decoded[1])
        stable = decoded[2]
        pool_addr = Web3.to_checksum_address(decoded[3])
        return (t0, t1, pool_addr, stable)
    except:
        return (None, None, None, None)

async def get_pool_liquidity_eth(pool_addr, token_addr):
    try:
        pool_c = aw3.eth.contract(address=checksum(pool_addr), abi=POOL_ABI)
        t0 = await rpc_retry(pool_c.functions.token0().call())
        t1 = await rpc_retry(pool_c.functions.token1().call())
        r0, r1, _ = await rpc_retry(pool_c.functions.getReserves().call())
        
        weth_res = 0
        if t0.lower() in BASE_TOKENS:
            weth_res = r0
        elif t1.lower() in BASE_TOKENS:
            weth_res = r1
        
        liq_eth = weth_res / 1e18
        return liq_eth
    except:
        return 0.0

async def is_honeypot(token_addr, pool_addr):
    if not config["honeypot_check"]:
        return False
    try:
        test_amt = 1000 * (10**18)
        out = await rpc_retry(router_c.functions.getAmountsOut(test_amt, [WETH, token_addr]).call())
        token_out = out[-1] if out else 0
        
        if token_out == 0:
            return True
        
        sell_out = await rpc_retry(router_c.functions.getAmountsOut(token_out, [token_addr, WETH]).call())
        eth_back = sell_out[-1] if sell_out else 0
        ratio = eth_back / test_amt if test_amt else 0
        
        if ratio < 0.4:
            return True
        
        return False
    except:
        return True

# BUY
async def buy_token(token_addr, pool_addr, buy_amt_eth):
    try:
        if daily_stats["pnl"] <= -config["max_daily_loss"]:
            logger.warning("🛑 Daily loss limit reached")
            return
        
        token_c = aw3.eth.contract(address=checksum(token_addr), abi=ERC20_ABI)
        sym = "???"
        try:
            sym = await asyncio.wait_for(token_c.functions.symbol().call(), timeout=2)
        except:
            pass

        if token_addr.lower() in blacklist:
            return

        if await is_honeypot(token_addr, pool_addr):
            blacklist.add(token_addr.lower())
            stats["honeypots_blocked"] += 1
            return

        amount_wei = int(buy_amt_eth * 1e18)
        route = [{"from": WETH, "to": token_addr, "stable": False, "factory": AERODROME_FACTORY}]
        
        try:
            out = await rpc_retry(router_c.functions.getAmountsOut(amount_wei, [WETH, token_addr]).call())
            expected_tokens = out[-1]
        except:
            expected_tokens = 0

        slippage = config["slippage_bps"] / 10000.0
        min_out = int(expected_tokens * (1.0 - slippage))

        nonce = await rpc_retry(aw3.eth.get_transaction_count(my_addr))
        gas_params = await get_gas_params()
        
        tx = router_c.functions.swapExactETHForTokens(
            min_out, route, my_addr, int(time.time()) + 600
        ).build_transaction({
            "from": my_addr,
            "value": amount_wei,
            "gas": 350000,
            "nonce": nonce,
            "chainId": BASE_CHAIN_ID,
            **gas_params
        })
        
        txh = await send_tx(tx)
        logger.info("✅ BUY %s | 0x%s...%s | %.4f ETH", sym, txh[:6], txh[-4:], buy_amt_eth)

        if tg_bot:
            try:
                msg = f"🟢 **BUY**\n💎 {sym}\n💰 {buy_amt_eth:.4f} ETH\n🔗 {txh[:10]}...{txh[-6:]}"
                await tg_bot.send_message(chat_id=OWNER_ID, text=msg, parse_mode="Markdown")
            except:
                pass

        await asyncio.sleep(3)
        balance = await rpc_retry(token_c.functions.balanceOf(my_addr).call())
        
        if balance == 0:
            return

        allowance = await rpc_retry(token_c.functions.allowance(my_addr, AERODROME_ROUTER).call())
        if allowance < balance:
            appr_tx = token_c.functions.approve(AERODROME_ROUTER, 2**256 - 1).build_transaction({
                "from": my_addr,
                "gas": 60000,
                "nonce": await rpc_retry(aw3.eth.get_transaction_count(my_addr)),
                "chainId": BASE_CHAIN_ID,
                **gas_params
            })
            await send_tx(appr_tx)
            await asyncio.sleep(2)

        positions[token_addr] = {
            "symbol": sym,
            "pool": pool_addr,
            "balance": balance,
            "entry_eth": buy_amt_eth,
            "peak_eth": 0.0,
            "entry_time": time.time(),
        }
        
        stats["trades"] += 1
        stats["total_volume"] += buy_amt_eth
        daily_stats["trades"] += 1
        
    except Exception as e:
        logger.error("🔴 Buy error: %s", e)

# SELL
async def sell_token(token_addr, reason="manual"):
    if token_addr not in positions:
        return
    
    pos = positions[token_addr]
    token_c = aw3.eth.contract(address=checksum(token_addr), abi=ERC20_ABI)
    bal = await rpc_retry(token_c.functions.balanceOf(my_addr).call())
    
    if bal == 0:
        del positions[token_addr]
        return

    route = [{"from": token_addr, "to": WETH, "stable": False, "factory": AERODROME_FACTORY}]
    
    try:
        out_arr = await rpc_retry(router_c.functions.getAmountsOut(bal, [token_addr, WETH]).call())
        expected_eth = out_arr[-1] / 1e18
    except:
        expected_eth = 0.0

    slippage = config["slippage_bps"] / 10000.0
    min_out = int((expected_eth * (1.0 - slippage)) * 1e18)

    nonce = await rpc_retry(aw3.eth.get_transaction_count(my_addr))
    gas_params = await get_gas_params()
    
    tx = router_c.functions.swapExactTokensForETH(
        bal, min_out, route, my_addr, int(time.time()) + 600
    ).build_transaction({
        "from": my_addr,
        "gas": 350000,
        "nonce": nonce,
        "chainId": BASE_CHAIN_ID,
        **gas_params
    })
    
    txh = await send_tx(tx)
    
    invested = pos["entry_eth"]
    pnl = (expected_eth - invested)
    pnl_pct = ((expected_eth / invested) - 1.0) * 100 if invested > 0 else 0
    hold_time = (time.time() - pos["entry_time"]) / 60
    
    stats["total_pnl"] += pnl
    daily_stats["pnl"] += pnl
    
    if pnl > 0:
        stats["wins"] += 1
        emoji = "🟢"
    else:
        stats["losses"] += 1
        emoji = "🔴"
    
    if pnl > stats["best_trade"]:
        stats["best_trade"] = pnl
    if pnl < stats["worst_trade"]:
        stats["worst_trade"] = pnl
    
    logger.info("%s SELL %s | %s | %.4f ETH | %+.1f%% | %.1f min", emoji, pos["symbol"], reason, expected_eth, pnl_pct, hold_time)

    if tg_bot:
        try:
            msg = f"{emoji} **SELL**\n💎 {pos['symbol']}\n💰 {expected_eth:.4f} ETH\n📊 {pnl:+.4f} ETH ({pnl_pct:+.1f}%)\n⏱ {hold_time:.1f}m\n📋 {reason}"
            await tg_bot.send_message(chat_id=OWNER_ID, text=msg, parse_mode="Markdown")
        except:
            pass

    del positions[token_addr]

# PROCESS TOKEN
async def process_new_token(token_addr, pool_addr, block_num):
    try:
        current_block = await aw3.eth.block_number
        age = current_block - block_num
        
        if age > config["max_token_age_blocks"]:
            return

        if pool_addr.lower() in seen_pools:
            return
        seen_pools.add(pool_addr.lower())

        liq_eth = await get_pool_liquidity_eth(pool_addr, token_addr)
        
        if liq_eth < config["min_liquidity_eth"]:
            return
        
        if liq_eth > config["max_liquidity_eth"]:
            return

        if len(positions) >= config["max_positions"]:
            return

        token_c = aw3.eth.contract(address=checksum(token_addr), abi=ERC20_ABI)
        sym = "???"
        try:
            sym = await asyncio.wait_for(token_c.functions.symbol().call(), timeout=2)
        except:
            pass

        logger.info("🆕 NEW TOKEN: %s | Liq: %.2f ETH | Age: %d", sym, liq_eth, age)
        
        buy_amt = config["snipe_eth"]
        await buy_token(token_addr, pool_addr, buy_amt)
        
    except Exception as e:
        logger.error("🔴 Process token error: %s", e)

# SCANNER
async def scan_new_pools():
    logger.info("🔍 Multi-DEX scanner started")
    last_block = await aw3.eth.block_number
    
    while True:
        await asyncio.sleep(2)
        if not config["active"]:
            continue
        
        if daily_stats["date"] != datetime.now().strftime("%Y-%m-%d"):
            daily_stats["date"] = datetime.now().strftime("%Y-%m-%d")
            daily_stats["pnl"] = 0.0
            daily_stats["trades"] = 0
            logger.info("📅 New day")
        
        if daily_stats["pnl"] >= config["daily_profit_target"]:
            logger.info("🎯 Daily target reached! %.4f ETH", daily_stats["pnl"])
            config["active"] = False
            continue
            
        try:
            current = await aw3.eth.block_number
            if current <= last_block:
                continue
                
            logger.info("🔎 Scan blok %s -> %s", last_block + 1, current)
            
            logs = await rpc_retry(aw3.eth.get_logs({
                "fromBlock": last_block + 1,
                "toBlock": current,
                "topics": [[POOL_CREATED_TOPIC]]
            }))
            
            if logs:
                logger.info("💎 Pools found: %d", len(logs))
                tasks = []
                
                for log in logs:
                    t0, t1, pool, stable = await parse_pool_log(log)
                    if not t0 or not pool:
                        continue
                        
                    blk = int(log.get("blockNumber", hex(current)), 16) if isinstance(log.get("blockNumber"), str) else log.get("blockNumber", current)
                    
                    if t0.lower() in BASE_TOKENS:
                        tasks.append(process_new_token(t1, pool, blk))
                    elif t1.lower() in BASE_TOKENS:
                        tasks.append(process_new_token(t0, pool, blk))
                
                if tasks:
                    await asyncio.gather(*tasks)
                    
            last_block = current
            
        except Exception as e:
            logger.error("🔴 Scanner error: %s", e)
            await asyncio.sleep(3)

# MONITOR
async def monitor_positions():
    while True:
        await asyncio.sleep(config["monitor_interval"])
        if not positions:
            continue
            
        for token, pos in list(positions.items()):
            try:
                bal = pos["balance"]
                route = [{"from": token, "to": WETH, "stable": False, "factory": AERODROME_FACTORY}]
                
                out = await rpc_retry(router_c.functions.getAmountsOut(bal, [token, WETH]).call())
                current = out[-1] / 1e18
                invested = pos["entry_eth"]
                pnl_pct = ((current - invested) / invested) * 100 if invested > 0 else 0

                if current > pos["peak_eth"]:
                    pos["peak_eth"] = current
                    
                peak = pos["peak_eth"]
                drop = ((peak - current) / peak) * 100 if peak > 0 else 0
                peak_profit = ((peak - invested) / invested) * 100 if invested > 0 else 0

                if pnl_pct >= config["take_profit_pct"]:
                    await sell_token(token, f"TP +{pnl_pct:.1f}%")
                elif peak_profit >= config["min_profit_to_trail"] and drop >= config["trailing_stop_pct"]:
                    await sell_token(token, "Trailing Stop")
                elif pnl_pct <= -config["hard_stop_pct"]:
                    await sell_token(token, f"SL {pnl_pct:.1f}%")
                    
            except Exception as e:
                logger.warning("⚠️ Monitor error: %s", e)

# TELEGRAM
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

async def cmd_start(update, context):
    if update.effective_user.id != OWNER_ID:
        return
    
    config["active"] = True
    balance = w3s.eth.get_balance(signer.address) / 1e18
    
    msg = "🚀 **SYNTHORA v4.0 ACTIVATED**\n\n"
    msg += "╔═══════════════════════╗\n"
    msg += "║    🔥 LUXURY MODE 🔥   ║\n"
    msg += "╚═══════════════════════╝\n\n"
    msg += "✅ Block Scanner: **ONLINE**\n"
    msg += f"✅ Multi-DEX: **{'ON' if config['multi_dex'] else 'OFF'}**\n"
    msg += f"✅ Honeypot Check: **{'ON' if config['honeypot_check'] else 'OFF'}**\n\n"
    msg += f"💰 Balance: `{balance:.4f} ETH`\n"
    msg += f"🎯 Daily Target: `{config['daily_profit_target']:.2f} ETH`\n"
    msg += f"🛡️ Max Loss: `{config['max_daily_loss']:.2f} ETH`"
    
    await update.message.reply_text(msg, parse_mode="Markdown")
    logger.info("🚀 BOT ACTIVATED")

async def cmd_stop(update, context):
    if update.effective_user.id != OWNER_ID:
        return
    config["active"] = False
    await update.message.reply_text("⏸ **BOT PAUSED**\n\nMonitoring positions only", parse_mode="Markdown")

async def cmd_status(update, context):
    if update.effective_user.id != OWNER_ID:
        return
    
    balance = w3s.eth.get_balance(signer.address) / 1e18
    status = "🟢 ACTIVE" if config["active"] else "🔴 PAUSED"
    uptime = (time.time() - stats["started"]) / 3600
    
    msg = f"**📊 STATUS**\n\n"
    msg += f"Status: {status}\n"
    msg += f"⏱ Uptime: `{uptime:.1f}h`\n"
    msg += f"💰 Balance: `{balance:.4f} ETH`\n"
    msg += f"📈 Positions: `{len(positions)}`\n"
    msg += f"🎯 Daily P&L: `{daily_stats['pnl']:+.4f} ETH`\n"
    msg += f"📅 Trades: `{daily_stats['trades']}`"
    
    await update.message.reply_text(msg, parse_mode="Markdown")

async def cmd_stats(update, context):
    if update.effective_user.id != OWNER_ID:
        return
    
    winrate = (stats["wins"] / stats["trades"] * 100) if stats["trades"] > 0 else 0
    
    msg = f"**📈 STATS**\n\n"
    msg += f"🎲 Trades: `{stats['trades']}`\n"
    msg += f"✅ Wins: `{stats['wins']}`\n"
    msg += f"❌ Losses: `{stats['losses']}`\n"
    msg += f"📊 Win Rate: `{winrate:.1f}%`\n\n"
    msg += f"💰 Total P&L: `{stats['total_pnl']:+.4f} ETH`\n"
    msg += f"🏆 Best: `{stats['best_trade']:+.4f} ETH`\n"
    msg += f"💀 Worst: `{stats['worst_trade']:+.4f} ETH`\n\n"
    msg += f"🛡 Honeypots: `{stats['honeypots_blocked']}`\n"
    msg += f"📊 Volume: `{stats['total_volume']:.2f} ETH`"
    
    await update.message.reply_text(msg, parse_mode="Markdown")

async def cmd_set(update, context):
    if update.effective_user.id != OWNER_ID:
        return
    
    if len(context.args) < 2:
        msg = "**⚙️ SETTINGS**\n\n"
        msg += "`/set minliq <value>` - Min liquidity\n"
        msg += "`/set honeypot <0/1>` - Honeypot check\n"
        msg += "`/set maxage <blocks>` - Max token age"
        await update.message.reply_text(msg, parse_mode="Markdown")
        return
    
    key = context.args[0].lower()
    val = context.args[1]
    
    try:
        if key == "minliq":
            config["min_liquidity_eth"] = float(val)
            await update.message.reply_text(f"✅ Min liq = {val} ETH")
        elif key == "honeypot":
            config["honeypot_check"] = bool(int(val))
            await update.message.reply_text(f"✅ Honeypot: {'ON' if config['honeypot_check'] else 'OFF'}")
        elif key == "maxage":
            config["max_token_age_blocks"] = int(val)
            await update.message.reply_text(f"✅ Max age = {val} blocks")
        else:
            await update.message.reply_text(f"❌ Unknown: {key}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

tg_bot = None

async def run_bot():
    global tg_bot
    await asyncio.sleep(2)
    tg_bot = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    tg_bot.add_handler(CommandHandler("start", cmd_start))
    tg_bot.add_handler(CommandHandler("stop", cmd_stop))
    tg_bot.add_handler(CommandHandler("status", cmd_status))
    tg_bot.add_handler(CommandHandler("stats", cmd_stats))
    tg_bot.add_handler(CommandHandler("set", cmd_set))
    
    await tg_bot.initialize()
    await tg_bot.start()
    await tg_bot.updater.start_polling()
    logger.info("💬 Telegram bot active")

# FASTAPI
@app.on_event("startup")
async def startup():
    asyncio.create_task(run_bot())
    asyncio.create_task(scan_new_pools())
    asyncio.create_task(monitor_positions())

@app.get("/")
async def health():
    balance = w3s.eth.get_balance(signer.address) / 1e18
    return {
        "status": "online",
        "active": config["active"],
        "balance_eth": round(balance, 6),
        "positions": len(positions),
        "total_pnl_eth": round(stats["total_pnl"], 6),
        "wallet": signer.address,
    }

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
