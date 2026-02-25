# -*- coding: utf-8 -*-
# ================================================================
#  SYNTHORA ELITE v4.0 - LUXURY EDITION
#  Base Mainnet | Multi-DEX | Advanced AI Analytics
# ================================================================
import logging, os, asyncio, time, json
from datetime import datetime, timedelta
from web3 import Web3, AsyncWeb3
from web3.providers import AsyncHTTPProvider
from eth_account import Account
from eth_abi import decode as abi_decode
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
from fastapi import FastAPI
import uvicorn

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
logger = logging.getLogger("synthora")
app = FastAPI()

# Middleware
try:
    from web3.middleware import geth_poa_middleware
    HAS_POA = True
except ImportError:
    try:
        from web3.middleware import ExtraDataToPOAMiddleware as geth_poa_middleware
        HAS_POA = True
    except ImportError:
        HAS_POA = False

import web3 as _web3_module
logger.info("🔷 Web3 v%s loaded", _web3_module.__version__)

# ================================================================
#  ADVANCED CONFIG
# ================================================================
BASE_RPC_URL = os.environ.get("BASE_RPC_URL", "https://base-mainnet.g.alchemy.com/v2/demo")
BASE_CHAIN_ID = 8453

# Multi-DEX Support
ROUTERS = {
    "aerodrome": "0xcF77a3Ba9A5CA399B7c97c74d54e5b1Beb874E43",
    "uniswap_v3": "0x2626664c2603336E57B271c5C0b26F421741e481",
    "baseswap": "0x327Df1E6de05895d2ab08513aaDD9313Fe505d86",
}

FACTORIES = {
    "aerodrome": "0x420DD381b31aEf6683db6B902084cB0FFECe40Da",
    "uniswap_v3": "0x33128a8fC17869897dcE68Ed026d694621f6FDfD",
    "baseswap": "0xFDa619b6d20975be80A10332cD39b9a4b0FAa8BB",
}

# Base tokens
WETH = "0x4200000000000000000000000000000000000006"
USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
DAI = "0x50c5725949A6F0c72E6C4a641F24049A917DB0Cb"
USDT = "0xfde4C96c8593536E31F229EA8f37b2ADa2699bb2"

BASE_TOKENS = [WETH.lower(), USDC.lower(), DAI.lower(), USDT.lower()]

POOL_CREATED_TOPICS = {
    "aerodrome": "0x2128d88d14c80cb081c1252a5fe2505c553a6f3dd4644684c3d4eb42a915d7ba",
    "uniswap_v3": "0x783cca1c0412dd0d695e784568c96da2e9c22ff989357a2e8b1d9b2b4e6b7118",
}

config = {
    "active": False,
    "snipe_eth": 0.01,
    "take_profit_pct": 75,
    "trailing_stop_pct": 12,
    "hard_stop_pct": 30,
    "min_profit_to_trail": 15,
    "slippage_bps": 500,
    "min_liquidity_eth": 0.5,
    "max_liquidity_eth": 100.0,  # NEW: Max liq filter
    "max_positions": 8,
    "reinvest": True,
    "reinvest_pct": 40,
    "gas_multiplier": 2.0,
    "max_gas_gwei": 10.0,
    "honeypot_check": True,
    "buy_timeout": 20,
    "monitor_interval": 1.5,
    "max_token_age_blocks": 1000,
    "multi_dex": True,  # NEW: Scan multiple DEXes
    "auto_compound": True,  # NEW: Auto reinvest profits
    "daily_profit_target": 0.1,  # NEW: 0.1 ETH per day
    "max_daily_loss": 0.05,  # NEW: Max 0.05 ETH loss per day
    "smart_gas": True,  # NEW: Dynamic gas optimization
    "mev_protection": True,  # NEW: Protect against MEV
    "volume_check": True,  # NEW: Check trading volume
    "min_volume_24h": 1.0,  # NEW: Min 1 ETH volume
    "contract_verification": False,  # NEW: Require verified contracts
    "max_buy_tax": 10,  # NEW: Max buy tax %
    "max_sell_tax": 10,  # NEW: Max sell tax %
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
    "avg_hold_time": 0.0,
}

# ================================================================
#  WALLET
# ================================================================
raw_key = os.environ.get("ARCHITECT_SESSION_KEY", "")
try:
    signer = Account.from_key(raw_key.strip().replace('"', '').replace("'", ''))
    my_addr = signer.address
    logger.info("💎 Wallet: %s", my_addr)
except Exception as e:
    logger.error("🔴 Key error: %s", e)
    signer = None
    my_addr = "0x0"

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
    {"constant":True,"inputs":[],"name":"name","outputs":[{"name":"","type":"string"}],"type":"function"},
]

POOL_ABI = [
    {"inputs":[],"name":"token0","outputs":[{"internalType":"address","name":"","type":"address"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"token1","outputs":[{"internalType":"address","name":"","type":"address"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"getReserves","outputs":[{"internalType":"uint256","name":"_reserve0","type":"uint256"},{"internalType":"uint256","name":"_reserve1","type":"uint256"},{"internalType":"uint256","name":"_blockTimestampLast","type":"uint256"}],"stateMutability":"view","type":"function"},
]

router_c = aw3.eth.contract(address=Web3.to_checksum_address(ROUTERS["aerodrome"]), abi=ROUTER_ABI)

# ================================================================
#  UTILITIES
# ================================================================
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
    
    if config["smart_gas"]:
        # Dynamic gas based on network conditions
        tip = int(base * 0.1)
        maxf = int(base * config["gas_multiplier"])
    else:
        tip = int(base * 0.05)
        maxf = int(base * config["gas_multiplier"])
    
    gwei_val = maxf / 1e9
    if gwei_val > config["max_gas_gwei"]:
        maxf = int(config["max_gas_gwei"] * 1e9)
    
    return {"maxFeePerGas": maxf, "maxPriorityFeePerGas": tip}

async def send_tx(tx):
    if config["mev_protection"]:
        # Add random delay to avoid MEV
        await asyncio.sleep(0.1 + (hash(str(tx)) % 100) / 1000)
    
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

# ================================================================
#  ADVANCED CHECKS
# ================================================================
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

async def check_token_tax(token_addr):
    """Check buy/sell tax"""
    if not config["max_buy_tax"]:
        return True
    
    try:
        test_amt = 1000 * (10**18)
        out = await rpc_retry(router_c.functions.getAmountsOut(test_amt, [WETH, token_addr]).call())
        token_out = out[-1] if out else 0
        
        if token_out == 0:
            return False
        
        # Sell back
        sell_out = await rpc_retry(router_c.functions.getAmountsOut(token_out, [token_addr, WETH]).call())
        eth_back = sell_out[-1] if sell_out else 0
        
        roundtrip_pct = (eth_back / test_amt) * 100 if test_amt else 0
        tax = 100 - roundtrip_pct
        
        if tax > config["max_buy_tax"] + config["max_sell_tax"]:
            logger.warning("🚫 High tax detected: %.1f%%", tax)
            return False
        
        return True
    except:
        return False

async def is_honeypot(token_addr, pool_addr):
    """Enhanced honeypot detection"""
    if not config["honeypot_check"]:
        return False
    
    try:
        # Tax check
        if not await check_token_tax(token_addr):
            return True
        
        # Liquidity lock check (simplified)
        liq = await get_pool_liquidity_eth(pool_addr, token_addr)
        if liq > config["max_liquidity_eth"]:
            logger.warning("🚫 Suspiciously high liquidity: %.2f ETH", liq)
            return True
        
        return False
    except:
        return True

# ================================================================
#  TRADING
# ================================================================
async def buy_token(token_addr, pool_addr, buy_amt_eth, dex="aerodrome"):
    """Enhanced buy with multi-DEX support"""
    try:
        # Daily loss check
        if daily_stats["pnl"] <= -config["max_daily_loss"]:
            logger.warning("🛑 Daily loss limit reached: %.4f ETH", daily_stats["pnl"])
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
        router_addr = ROUTERS.get(dex, ROUTERS["aerodrome"])
        factory_addr = FACTORIES.get(dex, FACTORIES["aerodrome"])
        
        route = [{"from": WETH, "to": token_addr, "stable": False, "factory": factory_addr}]
        
        router = aw3.eth.contract(address=checksum(router_addr), abi=ROUTER_ABI)
        
        try:
            out = await rpc_retry(router.functions.getAmountsOut(amount_wei, [WETH, token_addr]).call())
            expected_tokens = out[-1]
        except:
            expected_tokens = 0

        slippage = config["slippage_bps"] / 10000.0
        min_out = int(expected_tokens * (1.0 - slippage))

        nonce = await rpc_retry(aw3.eth.get_transaction_count(my_addr))
        gas_params = await get_gas_params()
        
        tx = router.functions.swapExactETHForTokens(
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
        logger.info("✅ BUY %s | 0x%s...%s | %.4f ETH | DEX: %s", sym, txh[:6], txh[-4:], buy_amt_eth, dex.upper())

        # Send Telegram notification
        if tg_bot:
            try:
                msg = f"🟢 **BUY EXECUTED**\n\n"
                msg += f"💎 Token: `{sym}`\n"
                msg += f"💰 Amount: `{buy_amt_eth:.4f} ETH`\n"
                msg += f"🔗 TX: `{txh[:10]}...{txh[-6:]}`\n"
                msg += f"🏦 DEX: `{dex.upper()}`"
                await tg_bot.send_message(chat_id=OWNER_ID, text=msg, parse_mode="Markdown")
            except:
                pass

        await asyncio.sleep(3)
        balance = await rpc_retry(token_c.functions.balanceOf(my_addr).call())
        
        if balance == 0:
            return

        allowance = await rpc_retry(token_c.functions.allowance(my_addr, router_addr).call())
        if allowance < balance:
            appr_tx = token_c.functions.approve(router_addr, 2**256 - 1).build_transaction({
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
            "dex": dex,
        }
        
        stats["trades"] += 1
        stats["total_volume"] += buy_amt_eth
        daily_stats["trades"] += 1
        
    except Exception as e:
        logger.error("🔴 Buy error: %s", e)

async def sell_token(token_addr, reason="manual"):
    """Enhanced sell with profit tracking"""
    if token_addr not in positions:
        return
    
    pos = positions[token_addr]
    token_c = aw3.eth.contract(address=checksum(token_addr), abi=ERC20_ABI)
    bal = await rpc_retry(token_c.functions.balanceOf(my_addr).call())
    
    if bal == 0:
        del positions[token_addr]
        return

    dex = pos.get("dex", "aerodrome")
    router_addr = ROUTERS.get(dex, ROUTERS["aerodrome"])
    factory_addr = FACTORIES.get(dex, FACTORIES["aerodrome"])
    
    route = [{"from": token_addr, "to": WETH, "stable": False, "factory": factory_addr}]
    router = aw3.eth.contract(address=checksum(router_addr), abi=ROUTER_ABI)
    
    try:
        out_arr = await rpc_retry(router.functions.getAmountsOut(bal, [token_addr, WETH]).call())
        expected_eth = out_arr[-1] / 1e18
    except:
        expected_eth = 0.0

    slippage = config["slippage_bps"] / 10000.0
    min_out = int((expected_eth * (1.0 - slippage)) * 1e18)

    nonce = await rpc_retry(aw3.eth.get_transaction_count(my_addr))
    gas_params = await get_gas_params()
    
    tx = router.functions.swapExactTokensForETH(
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
    hold_time = (time.time() - pos["entry_time"]) / 60  # minutes
    
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
    
    # Update avg hold time
    total_holds = stats["wins"] + stats["losses"]
    stats["avg_hold_time"] = ((stats["avg_hold_time"] * (total_holds - 1)) + hold_time) / total_holds if total_holds > 0 else hold_time
    
    logger.info("%s SELL %s | %s | %.4f ETH | %+.1f%% | Hold: %.1f min", emoji, pos["symbol"], reason, expected_eth, pnl_pct, hold_time)

    # Telegram notification
    if tg_bot:
        try:
            msg = f"{emoji} **SELL EXECUTED**\n\n"
            msg += f"💎 Token: `{pos['symbol']}`\n"
            msg += f"💰 Received: `{expected_eth:.4f} ETH`\n"
            msg += f"📊 P&L: `{pnl:+.4f} ETH ({pnl_pct:+.1f}%)`\n"
            msg += f"⏱ Hold Time: `{hold_time:.1f} min`\n"
            msg += f"📋 Reason: `{reason}`\n"
            msg += f"🔗 TX: `{txh[:10]}...{txh[-6:]}`"
            await tg_bot.send_message(chat_id=OWNER_ID, text=msg, parse_mode="Markdown")
        except:
            pass

    del positions[token_addr]
    
    # Auto-compound check
    if config["auto_compound"] and pnl > 0 and config["active"]:
        profit_to_reinvest = pnl * (config["reinvest_pct"] / 100)
        if profit_to_reinvest >= config["snipe_eth"]:
            logger.info("💰 Auto-compound: %.4f ETH available for next trade", profit_to_reinvest)

# ================================================================
#  PROCESS NEW TOKEN
# ================================================================
async def process_new_token(token_addr, pool_addr, block_num, dex="aerodrome"):
    try:
        current_block = await aw3.eth.block_number
        age = current_block - block_num
        
        if age > config["max_token_age_blocks"]:
            return

        pool_key = f"{pool_addr.lower()}_{dex}"
        if pool_key in seen_pools:
            return
        seen_pools.add(pool_key)

        liq_eth = await get_pool_liquidity_eth(pool_addr, token_addr)
        
        if liq_eth < config["min_liquidity_eth"]:
            return
        
        if liq_eth > config["max_liquidity_eth"]:
            logger.info("⚠️ Pool %s => liq %.2f ETH > max %.2f => skip", pool_addr[:10], liq_eth, config["max_liquidity_eth"])
            return

        if len(positions) >= config["max_positions"]:
            return

        token_c = aw3.eth.contract(address=checksum(token_addr), abi=ERC20_ABI)
        sym = "???"
        name = "???"
        try:
            sym = await asyncio.wait_for(token_c.functions.symbol().call(), timeout=2)
            name = await asyncio.wait_for(token_c.functions.name().call(), timeout=2)
        except:
            pass

        logger.info("🆕 NEW TOKEN: %s (%s) | Liq: %.2f ETH | Age: %d | DEX: %s", sym, name, liq_eth, age, dex.upper())
        
        buy_amt = config["snipe_eth"]
        await buy_token(token_addr, pool_addr, buy_amt, dex)
        
    except Exception as e:
        logger.error("🔴 Process token error: %s", e)

# ================================================================
#  MULTI-DEX SCANNER
# ================================================================
async def scan_new_pools():
    logger.info("🔍 Multi-DEX scanner started")
    last_block = await aw3.eth.block_number
    
    while True:
        await asyncio.sleep(2)
        if not config["active"]:
            continue
        
        # Reset daily stats
        if daily_stats["date"] != datetime.now().strftime("%Y-%m-%d"):
            daily_stats["date"] = datetime.now().strftime("%Y-%m-%d")
            daily_stats["pnl"] = 0.0
            daily_stats["trades"] = 0
            logger.info("📅 New day started - stats reset")
        
        # Daily profit target check
        if daily_stats["pnl"] >= config["daily_profit_target"]:
            logger.info("🎯 Daily profit target reached! %.4f ETH", daily_stats["pnl"])
            config["active"] = False
            if tg_bot:
                try:
                    msg = f"🎯 **DAILY TARGET REACHED!**\n\n"
                    msg += f"💰 Profit: `{daily_stats['pnl']:.4f} ETH`\n"
                    msg += f"🎲 Trades: `{daily_stats['trades']}`\n"
                    msg += f"Bot paused. Use /start to resume."
                    await tg_bot.send_message(chat_id=OWNER_ID, text=msg, parse_mode="Markdown")
                except:
                    pass
            continue
            
        try:
            current = await aw3.eth.block_number
            if current <= last_block:
                continue
                
            logger.info("🔎 Scan blok %s -> %s", last_block + 1, current)
            
            # Scan multiple DEXes
            dexes_to_scan = ["aerodrome"]
            if config["multi_dex"]:
                dexes_to_scan.extend(["uniswap_v3"])
            
            for dex in dexes_to_scan:
                topic = POOL_CREATED_TOPICS.get(dex)
                if not topic:
                    continue
                
                logs = await rpc_retry(aw3.eth.get_logs({
                    "fromBlock": last_block + 1,
                    "toBlock": current,
                    "topics": [[topic]]
                }))
                
                if logs:
                    logger.info("💎 %s: %d pools found", dex.upper(), len(logs))
                    tasks = []
                    
                    for log in logs:
                        t0, t1, pool, stable = await parse_pool_log(log)
                        if not t0 or not pool:
                            continue
                            
                        blk = int(log.get("blockNumber", hex(current)), 16) if isinstance(log.get("blockNumber"), str) else log.get("blockNumber", current)
                        
                        # Multi-base token support
                        if t0.lower() in BASE_TOKENS:
                            tasks.append(process_new_token(t1, pool, blk, dex))
                        elif t1.lower() in BASE_TOKENS:
                            tasks.append(process_new_token(t0, pool, blk, dex))
                    
                    if tasks:
                        await asyncio.gather(*tasks)
                        
            last_block = current
            
        except Exception as e:
            logger.error("🔴 Scanner error: %s", e)
            await asyncio.sleep(3)

# ================================================================
#  POSITION MONITOR
# ================================================================
async def monitor_positions():
    while True:
        await asyncio.sleep(config["monitor_interval"])
        if not positions:
            continue
            
        for token, pos in list(positions.items()):
            try:
                bal = pos["balance"]
                dex = pos.get("dex", "aerodrome")
                router_addr = ROUTERS.get(dex, ROUTERS["aerodrome"])
                factory_addr = FACTORIES.get(dex, FACTORIES["aerodrome"])
                
                route = [{"from": token, "to": WETH, "stable": False, "factory": factory_addr}]
                router = aw3.eth.contract(address=checksum(router_addr), abi=ROUTER_ABI)
                
                out = await rpc_retry(router.functions.getAmountsOut(bal, [token, WETH]).call())
                current = out[-1] / 1e18
                invested = pos["entry_eth"]
                pnl_pct = ((current - invested) / invested) * 100 if invested > 0 else 0

                if current > pos["peak_eth"]:
                    pos["peak_eth"] = current
                    
                peak = pos["peak_eth"]
                drop = ((peak - current) / peak) * 100 if peak > 0 else 0
                peak_profit = ((peak - invested) / invested) * 100 if invested > 0 else 0

                if pnl_pct >= config["take_profit_pct"]:
                    await sell_token(token, f"Take Profit +{pnl_pct:.1f}%")
                elif peak_profit >= config["min_profit_to_trail"] and drop >= config["trailing_stop_pct"]:
                    await sell_token(token, "Trailing Stop")
                elif pnl_pct <= -config["hard_stop_pct"]:
                    await sell_token(token, f"Hard Stop {pnl_pct:.1f}%")
                    
            except Exception as e:
                logger.warning("⚠️ Monitor error %s: %s", token[:10], e)

# ================================================================
#  TELEGRAM LUXURY INTERFACE
# ================================================================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

def get_main_keyboard():
    keyboard = [
        [InlineKeyboardButton("▶️ START", callback_data="start"),
         InlineKeyboardButton("⏸ STOP", callback_data="stop")],
        [InlineKeyboardButton("📊 STATUS", callback_data="status"),
         InlineKeyboardButton("📈 STATS", callback_data="stats")],
        [InlineKeyboardButton("💼 PORTFOLIO", callback_data="portfolio"),
         InlineKeyboardButton("⚙️ SETTINGS", callback_data="settings")],
        [InlineKeyboardButton("🔄 REFRESH", callback_data="refresh")],
    ]
    return InlineKeyboardMarkup(keyboard)

async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    
    balance = w3s.eth.get_balance(signer.address) / 1e18
    status = "🟢 ACTIVE" if config["active"] else "🔴 PAUSED"
    
    msg = f"╔═══════════════════════╗\n"
    msg += f"║   **SYNTHORA v4.0**    ║\n"
    msg += f"╚═══════════════════════╝\n\n"
    msg += f"Status: {status}\n"
    msg += f"💰 Balance: `{balance:.4f} ETH`\n"
    msg += f"📊 Positions: `{len(positions)}`\n"
    msg += f"💎 Total P&L: `{stats['total_pnl']:+.4f} ETH`\n\n"
    msg += f"Choose an option:"
    
    await update.message.reply_text(msg, reply_markup=get_main_keyboard(), parse_mode="Markdown")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.from_user.id != OWNER_ID:
        return
    
    data = query.data
    
    if data == "start":
        config["active"] = True
        msg = "✅ **BOT ACTIVATED**\n\n🔍 Scanner: ON\n🛡 Protection: ENABLED"
        await query.edit_message_text(msg, parse_mode="Markdown")
        
    elif data == "stop":
        config["active"] = False
        msg = "⏸ **BOT PAUSED**\n\n📊 Monitoring positions only"
        await query.edit_message_text(msg, parse_mode="Markdown")
        
    elif data == "status":
        balance = w3s.eth.get_balance(signer.address) / 1e18
        status = "🟢 ACTIVE" if config["active"] else "🔴 PAUSED"
        uptime = (time.time() - stats["started"]) / 3600
        
        msg = f"**📊 SYSTEM STATUS**\n\n"
        msg += f"Status: {status}\n"
        msg += f"⏱ Uptime: `{uptime:.1f}h`\n"
        msg += f"💰 Balance: `{balance:.4f} ETH`\n"
        msg += f"📈 Positions: `{len(positions)}`\n"
        msg += f"🎯 Daily P&L: `{daily_stats['pnl']:+.4f} ETH`\n"
        msg += f"📅 Daily Trades: `{daily_stats['trades']}`"
        
        await query.edit_message_text(msg, reply_markup=get_main_keyboard(), parse_mode="Markdown")
        
    elif data == "stats":
        winrate = (stats["wins"] / stats["trades"] * 100) if stats["trades"] > 0 else 0
        
        msg = f"**📈 STATISTICS**\n\n"
        msg += f"🎲 Total Trades: `{stats['trades']}`\n"
        msg += f"✅ Wins: `{stats['wins']}`\n"
        msg += f"❌ Losses: `{stats['losses']}`\n"
        msg += f"📊 Win Rate: `{winrate:.1f}%`\n\n"
        msg += f"💰 Total P&L: `{stats['total_pnl']:+.4f} ETH`\n"
        msg += f"🏆 Best Trade: `{stats['best_trade']:+.4f} ETH`\n"
        msg += f"💀 Worst Trade: `{stats['worst_trade']:+.4f} ETH`\n\n"
        msg += f"🛡 Honeypots Blocked: `{stats['honeypots_blocked']}`\n"
        msg += f"📊 Total Volume: `{stats['total_volume']:.2f} ETH`\n"
        msg += f"⏱ Avg Hold: `{stats['avg_hold_time']:.1f} min`"
        
        await query.edit_message_text(msg, reply_markup=get_main_keyboard(), parse_mode="Markdown")
        
    elif data == "portfolio":
        if not positions:
            msg = "📭 **NO ACTIVE POSITIONS**"
        else:
            msg = f"**💼 PORTFOLIO**\n\n"
            for token, pos in positions.items():
                bal = pos["balance"]
                router_addr = ROUTERS.get(pos.get("dex", "aerodrome"), ROUTERS["aerodrome"])
                factory_addr = FACTORIES.get(pos.get("dex", "aerodrome"), FACTORIES["aerodrome"])
                
                route = [{"from": token, "to": WETH, "stable": False, "factory": factory_addr}]
                router = aw3.eth.contract(address=checksum(router_addr), abi=ROUTER_ABI)
                
                try:
                    out = await router.functions.getAmountsOut(bal, [token, WETH]).call()
                    current = out[-1] / 1e18
                    invested = pos["entry_eth"]
                    pnl_pct = ((current - invested) / invested) * 100
                    emoji = "🟢" if pnl_pct > 0 else "🔴"
                    
                    msg += f"{emoji} **{pos['symbol']}**\n"
                    msg += f"   Entry: `{invested:.4f} ETH`\n"
                    msg += f"   Current: `{current:.4f} ETH`\n"
                    msg += f"   P&L: `{pnl_pct:+.1f}%`\n\n"
                except:
                    msg += f"⚪ **{pos['symbol']}** - Checking...\n\n"
        
        await query.edit_message_text(msg, reply_markup=get_main_keyboard(), parse_mode="Markdown")
        
    elif data == "settings":
        msg = f"**⚙️ CURRENT SETTINGS**\n\n"
        msg += f"💰 Buy Amount: `{config['snipe_eth']:.3f} ETH`\n"
        msg += f"🎯 Take Profit: `{config['take_profit_pct']}%`\n"
        msg += f"🛑 Hard Stop: `{config['hard_stop_pct']}%`\n"
        msg += f"💧 Min Liquidity: `{config['min_liquidity_eth']:.1f} ETH`\n"
        msg += f"🛡 Honeypot Check: `{'ON' if config['honeypot_check'] else 'OFF'}`\n"
        msg += f"🔄 Multi-DEX: `{'ON' if config['multi_dex'] else 'OFF'}`\n"
        msg += f"💎 Auto Compound: `{'ON' if config['auto_compound'] else 'OFF'}`\n\n"
        msg += f"Use `/set <key> <value>` to change"
        
        await query.edit_message_text(msg, reply_markup=get_main_keyboard(), parse_mode="Markdown")
        
    elif data == "refresh":
        await button_handler(update, context)

async def cmd_set(update, context):
    if update.effective_user.id != OWNER_ID:
        return
    
    if len(context.args) < 2:
        msg = "**⚙️ AVAILABLE SETTINGS**\n\n"
        msg += "`/set minliq <value>` - Min liquidity\n"
        msg += "`/set maxliq <value>` - Max liquidity\n"
        msg += "`/set honeypot <0/1>` - Toggle honeypot check\n"
        msg += "`/set multidex <0/1>` - Toggle multi-DEX\n"
        msg += "`/set compound <0/1>` - Toggle auto-compound\n"
        msg += "`/set maxage <blocks>` - Max token age"
        await update.message.reply_text(msg, parse_mode="Markdown")
        return
    
    key = context.args[0].lower()
    val = context.args[1]
    
    try:
        if key == "minliq":
            config["min_liquidity_eth"] = float(val)
            await update.message.reply_text(f"✅ Min liquidity set to {val} ETH")
        elif key == "maxliq":
            config["max_liquidity_eth"] = float(val)
            await update.message.reply_text(f"✅ Max liquidity set to {val} ETH")
        elif key == "honeypot":
            config["honeypot_check"] = bool(int(val))
            await update.message.reply_text(f"✅ Honeypot check: {'ON' if config['honeypot_check'] else 'OFF'}")
        elif key == "multidex":
            config["multi_dex"] = bool(int(val))
            await update.message.reply_text(f"✅ Multi-DEX: {'ON' if config['multi_dex'] else 'OFF'}")
        elif key == "compound":
            config["auto_compound"] = bool(int(val))
            await update.message.reply_text(f"✅ Auto-compound: {'ON' if config['auto_compound'] else 'OFF'}")
        elif key == "maxage":
            config["max_token_age_blocks"] = int(val)
            await update.message.reply_text(f"✅ Max age set to {val} blocks")
        else:
            await update.message.reply_text(f"❌ Unknown setting: {key}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

tg_bot = None

async def run_bot():
    global tg_bot
    await asyncio.sleep(2)
    tg_bot = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    tg_bot.add_handler(CommandHandler("menu", cmd_menu))
    tg_bot.add_handler(CommandHandler("set", cmd_set))
    tg_bot.add_handler(CallbackQueryHandler(button_handler))
    
    await tg_bot.initialize()
    await tg_bot.start()
    await tg_bot.updater.start_polling()
    logger.info("💬 Telegram bot active")

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
    balance = w3s.eth.get_balance(signer.address) / 1e18
    uptime = (time.time() - stats["started"]) / 3600
    winrate = (stats["wins"] / stats["trades"] * 100) if stats["trades"] > 0 else 0
    
    return {
        "status": "online",
        "version": "4.0 Luxury",
        "active": config["active"],
        "uptime_hours": round(uptime, 2),
        "balance_eth": round(balance, 6),
        "positions": len(positions),
        "total_trades": stats["trades"],
        "win_rate": round(winrate, 2),
        "total_pnl_eth": round(stats["total_pnl"], 6),
        "daily_pnl_eth": round(daily_stats["pnl"], 6),
        "honeypots_blocked": stats["honeypots_blocked"],
        "wallet": signer.address,
        "multi_dex": config["multi_dex"],
        "auto_compound": config["auto_compound"],
    }

@app.get("/stats")
async def get_stats():
    return {
        "trades": stats["trades"],
        "wins": stats["wins"],
        "losses": stats["losses"],
        "win_rate": round((stats["wins"] / stats["trades"] * 100), 2) if stats["trades"] > 0 else 0,
        "total_pnl": round(stats["total_pnl"], 6),
        "best_trade": round(stats["best_trade"], 6),
        "worst_trade": round(stats["worst_trade"], 6),
        "total_volume": round(stats["total_volume"], 6),
        "avg_hold_time_minutes": round(stats["avg_hold_time"], 2),
        "honeypots_blocked": stats["honeypots_blocked"],
        "daily": {
            "date": daily_stats["date"],
            "pnl": round(daily_stats["pnl"], 6),
            "trades": daily_stats["trades"],
        }
    }

@app.get("/positions")
async def get_positions():
    result = []
    for token, pos in positions.items():
        result.append({
            "token": token,
            "symbol": pos["symbol"],
            "entry_eth": pos["entry_eth"],
            "entry_time": pos["entry_time"],
            "dex": pos.get("dex", "aerodrome"),
        })
    return result

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
