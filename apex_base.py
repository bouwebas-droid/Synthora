# -*- coding: utf-8 -*-
# =============================================================
#  SYNTHORA ELITE SNIPER v3 - FINAL
#  Base Mainnet | Aerodrome | Async
# =============================================================
import logging, os, asyncio, time, json
import aiohttp
from web3 import Web3
from web3 import AsyncWeb3
from web3.providers import AsyncHTTPProvider
from eth_account import Account
from eth_abi import decode as abi_decode
from telegram.ext import ApplicationBuilder, CommandHandler
from fastapi import FastAPI
import uvicorn

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
logger = logging.getLogger("synthora")
app    = FastAPI()

# Middleware import - compatibel met alle versies
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
logger.info("web3 versie: %s", _web3_module.__version__)

# =============================================================
#  CONFIG
# =============================================================
BASE_RPC_URL   = os.environ.get("BASE_RPC_URL", "https://base-mainnet.g.alchemy.com/v2/Hw_dzgvYV1VJDryEav9WO")
BASE_WS_URL    = os.environ.get("BASE_WS_URL",  "wss://base-mainnet.g.alchemy.com/v2/Hw_dzgvYV1VJDryEav9WO")
BASE_CHAIN_ID  = 8453

AERODROME_ROUTER  = "0xcF77a3Ba9A5CA399B7c97c74d54e5b1Beb874E43"
AERODROME_FACTORY = "0x420DD381b31aEf6683db6B902084cB0FFECe40Da"
WETH              = "0x4200000000000000000000000000000000000006USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"  # Base USDC
ADD_LIQ_SELECTORS = {"0xe8e33700", "0xf91b3f5e"}

# PoolCreated(address,address,bool,address,uint256) topic
POOL_CREATED_TOPIC = "0x2128d88d14c80cb081c1252a5acff7a264671bf199ce226b53788fb26065005e"

config = {
    "active":               False,
    "snipe_eth":            0.01,
    "take_profit_pct":      75,
    "trailing_stop_pct":    12,
    "hard_stop_pct":        30,
    "min_profit_to_trail":  15,
    "slippage_bps":         500,
    "min_liquidity_eth":    0.5,
    "max_positions":        8,
    "reinvest":             True,
    "reinvest_pct":         40,
    "gas_multiplier":       2.0,
    "max_gas_gwei":         10.0,
    "honeypot_check":       True,
    "buy_timeout":          20,
    "monitor_interval":     1.5,
    "max_token_age_blocks": 2,
}

positions  = {}
blacklist  = set()
seen_pools = set()
seen_txs   = set()

stats = {
    "trades": 0, "wins": 0, "losses": 0,
    "total_pnl": 0.0, "best_trade": 0.0, "worst_trade": 0.0,
    "honeypots_blocked": 0, "started": time.time(),
}

# =============================================================
#  WALLET
# =============================================================
raw_key = os.environ.get("ARCHITECT_SESSION_KEY", "")
try:
    signer = Account.from_key(raw_key.strip().replace('"', "").replace("'", ""))
    logger.info("Wallet: %s", signer.address)
except Exception as e:
    raise SystemExit("KEY ERROR: " + str(e))

OWNER_ID       = int(os.environ.get("OWNER_ID", 0))
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
tg_bot         = None

# =============================================================
#  WEB3 INIT
# =============================================================
w3s = Web3(Web3.HTTPProvider(BASE_RPC_URL, request_kwargs={"timeout": 10}))
aw3 = AsyncWeb3(AsyncHTTPProvider(BASE_RPC_URL))

if HAS_POA:
    try:
        w3s.middleware_onion.inject(geth_poa_middleware, layer=0)
    except Exception:
        pass

try:
    _chain = w3s.eth.chain_id
    if _chain != BASE_CHAIN_ID:
        raise SystemExit("VERKEERDE CHAIN: " + str(_chain))
    logger.info("Base Mainnet OK chain_id=%s", BASE_CHAIN_ID)
except SystemExit:
    raise
except Exception as e:
    logger.warning("Chain check fout (RPC): %s", e)

# =============================================================
#  ABI's
# =============================================================
ROUTER_ABI = [
    {"inputs":[{"name":"amountOutMin","type":"uint256"},
               {"name":"routes","type":"tuple[]","components":[
                   {"name":"from","type":"address"},{"name":"to","type":"address"},
                   {"name":"stable","type":"bool"},{"name":"factory","type":"address"}]},
               {"name":"to","type":"address"},{"name":"deadline","type":"uint256"}],
     "name":"swapExactETHForTokens","outputs":[{"name":"amounts","type":"uint256[]"}],
     "stateMutability":"payable","type":"function"},
    {"inputs":[{"name":"amountIn","type":"uint256"},
               {"name":"routes","type":"tuple[]","components":[
                   {"name":"from","type":"address"},{"name":"to","type":"address"},
                   {"name":"stable","type":"bool"},{"name":"factory","type":"address"}]}],
     "name":"getAmountsOut","outputs":[{"name":"amounts","type":"uint256[]"}],
     "stateMutability":"view","type":"function"},
    {"inputs":[{"name":"amountIn","type":"uint256"},
               {"name":"amountOutMin","type":"uint256"},
               {"name":"routes","type":"tuple[]","components":[
                   {"name":"from","type":"address"},{"name":"to","type":"address"},
                   {"name":"stable","type":"bool"},{"name":"factory","type":"address"}]},
               {"name":"to","type":"address"},{"name":"deadline","type":"uint256"}],
     "name":"swapExactTokensForETH","outputs":[{"name":"amounts","type":"uint256[]"}],
     "stateMutability":"nonpayable","type":"function"},
]

ERC20_ABI = [
    {"inputs":[{"name":"spender","type":"address"},{"name":"amount","type":"uint256"}],
     "name":"approve","outputs":[{"name":"","type":"bool"}],
     "stateMutability":"nonpayable","type":"function"},
    {"inputs":[{"name":"account","type":"address"}],
     "name":"balanceOf","outputs":[{"name":"","type":"uint256"}],
     "stateMutability":"view","type":"function"},
]

POOL_ABI = [
    {"inputs":[],"name":"getReserves",
     "outputs":[{"name":"_reserve0","type":"uint256"},{"name":"_reserve1","type":"uint256"},
                {"name":"_blockTimestampLast","type":"uint32"}],
     "stateMutability":"view","type":"function"},
    {"inputs":[],"name":"token0","outputs":[{"name":"","type":"address"}],
     "stateMutability":"view","type":"function"},
    {"inputs":[],"name":"token1","outputs":[{"name":"","type":"address"}],
     "stateMutability":"view","type":"function"},
]

# =============================================================
#  DIRECTE RPC CALL - omzeilt web3 get_logs volledig
# =============================================================
MAX_BLOCK_RANGE = 9  # Alchemy Free tier max is 10 blocks per request

async def rpc_get_logs(from_block: int, to_block, address: str, topic: str) -> list:
    """Directe eth_getLogs call via aiohttp. Splitst automatisch bij te grote ranges."""
    if to_block == "latest":
        # Haal huidig block op voor range check
        try:
            async with aiohttp.ClientSession() as session:
                blk_payload = {"jsonrpc":"2.0","id":0,"method":"eth_blockNumber","params":[]}
                async with session.post(BASE_RPC_URL, json=blk_payload, timeout=aiohttp.ClientTimeout(total=5)) as r:
                    d = await r.json()
                    to_block = int(d["result"], 16)
        except Exception:
            to_block = from_block + 100  # fallback

    from_block = int(from_block)
    to_block   = int(to_block)

    # Splits in chunks van max 1999 blocks
    all_logs = []
    chunk_start = from_block
    while chunk_start <= to_block:
        chunk_end = min(chunk_start + MAX_BLOCK_RANGE, to_block)
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_getLogs",
            "params": [{
                "address":   address,
                "fromBlock": hex(chunk_start),
                "toBlock":   hex(chunk_end),
                "topics":    [topic],
            }]
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(BASE_RPC_URL, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    data = await resp.json()
                    if "error" in data:
                        logger.warning("eth_getLogs fout (blok %s-%s): %s", chunk_start, chunk_end, data["error"])
                    else:
                        all_logs.extend(data.get("result", []))
        except Exception as e:
            logger.warning("eth_getLogs request fout: %s", e)
        chunk_start = chunk_end + 1

    return all_logs

def parse_pool_log(log: dict):
    """Parseer een PoolCreated log."""
    try:
        topics = log.get("topics", [])
        if len(topics) < 3:
            return None, None, None
        t0 = Web3.to_checksum_address("0x" + topics[1][-40:])
        t1 = Web3.to_checksum_address("0x" + topics[2][-40:])
        data = log.get("data", "0x")
        if data.startswith("0x"):
            data = data[2:]
        # data layout: stable(32 bytes) + pool(32 bytes) + length(32 bytes)
        # pool adres = bytes 32-64 = chars 64-128, adres = laatste 40 chars
        if len(data) >= 128:
            pool = Web3.to_checksum_address("0x" + data[88:128])
        else:
            pool = Web3.to_checksum_address("0x" + data[-40:])
        return t0, t1, pool
    except Exception as e:
        logger.warning("Log parse fout: %s", e)
        return None, None, None

# =============================================================
#  HELPERS
# =============================================================
MAX_RETRIES = 5

async def rpc_retry(fn, *args, **kwargs):
    for attempt in range(MAX_RETRIES):
        try:
            return await fn(*args, **kwargs)
        except Exception as e:
            err = str(e).lower()
            if "429" in err or "rate limit" in err or "too many" in err:
                wait = 0.5 * (2 ** attempt)
                logger.warning("Rate limit %.1fs", wait)
                await asyncio.sleep(wait)
                continue
            raise
    raise Exception("RPC mislukt na " + str(MAX_RETRIES) + " pogingen")

async def notify(msg: str):
    if tg_bot and OWNER_ID:
        try:
            await tg_bot.bot.send_message(chat_id=OWNER_ID, text=msg, parse_mode="Markdown")
        except Exception as e:
            logger.warning("Telegram fout: %s", e)

def to_wei(amount, unit="ether"):
    return w3s.to_wei(amount, unit)

def from_wei(amount, unit="ether"):
    return w3s.from_wei(amount, unit)

def checksum(addr):
    return Web3.to_checksum_address(addr)

# =============================================================
#  GAS
# =============================================================
async def get_gas_params():
    block    = await rpc_retry(aw3.eth.get_block, "latest")
    base_fee = block["baseFeePerGas"]
    priority = min(int(base_fee * config["gas_multiplier"]), to_wei(config["max_gas_gwei"], "gwei"))
    return {"maxPriorityFeePerGas": priority, "maxFeePerGas": base_fee * 2 + priority}

# =============================================================
#  TRANSACTIE
# =============================================================
async def send_tx(tx: dict) -> str:
    tx["nonce"]   = await rpc_retry(aw3.eth.get_transaction_count, signer.address, "pending")
    tx["chainId"] = BASE_CHAIN_ID
    tx["from"]    = signer.address
    tx.update(await get_gas_params())
    if "gas" not in tx:
        try:
            tx["gas"] = int(await rpc_retry(aw3.eth.estimate_gas, tx) * 1.3)
        except Exception:
            tx["gas"] = 500000
    signed  = signer.sign_transaction(tx)
    raw     = getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction", None)
    tx_hash = await rpc_retry(aw3.eth.send_raw_transaction, raw)
    return tx_hash.hex() if hasattr(tx_hash, "hex") else str(tx_hash)

# =============================================================
#  HONEYPOT CHECK
# =============================================================
async def is_honeypot(token: str) -> bool:
    if not config["honeypot_check"]:
        return False
    try:
        router   = aw3.eth.contract(address=AERODROME_ROUTER, abi=ROUTER_ABI)
        r_buy    = [{"from": WETH, "to": token, "stable": False, "factory": AERODROME_FACTORY}]
        r_sell   = [{"from": token, "to": WETH, "stable": False, "factory": AERODROME_FACTORY}]
        test_wei = to_wei(0.001)
        buy_out  = await rpc_retry(router.functions.getAmountsOut(test_wei, r_buy).call)
        tokens   = buy_out[-1]
        if tokens == 0:
            stats["honeypots_blocked"] += 1
            return True
        sell_out = await rpc_retry(router.functions.getAmountsOut(tokens, r_sell).call)
        tax      = (1 - sell_out[-1] / test_wei) * 100
        if tax > 20:
            stats["honeypots_blocked"] += 1
            return True
        return False
    except Exception:
        stats["honeypots_blocked"] += 1
        return True

# =============================================================
#  LIQUIDITEIT
# =============================================================
async def check_liquidity(pool: str) -> float:
    try:
        c         = aw3.eth.contract(address=pool, abi=POOL_ABI)
        r0, r1, _ = await rpc_retry(c.functions.getReserves().call)
        t0        = await rpc_retry(c.functions.token0().call)
        weth_res  = r0 if t0.lower() == WETH.lower() else r1
        return float(from_wei(weth_res))
    except Exception:
        return 0.0

# =============================================================
#  SAFETY CHECK
# =============================================================
async def is_safe(token: str, pool: str, created_block: int = 0) -> bool:
    try:
        if created_block > 0:
            current = await aw3.eth.block_number
            if current - created_block > config["max_token_age_blocks"]:
                return False
        code = await rpc_retry(aw3.eth.get_code, token)
        if len(code) < 500:
            return False
        liq, honeypot = await asyncio.gather(check_liquidity(pool), is_honeypot(token))
        if liq < config["min_liquidity_eth"]:
            return False
        if honeypot:
            return False
        logger.info("Safe: %s liq=%.3f ETH", token[:10], liq)
        return True
    except Exception as e:
        logger.warning("Safety fout: %s", e)
        return False

# =============================================================
#  KOPEN
# =============================================================
async def buy_token(token: str, pool: str, created_block: int = 0) -> bool:
    if token in positions or token in blacklist:
        return False
    if len(positions) >= config["max_positions"]:
        return False
    balance    = await rpc_retry(aw3.eth.get_balance, signer.address)
    amount_eth = config["snipe_eth"]
    amount_wei = to_wei(amount_eth)
    if balance < amount_wei:
        await notify("*Onvoldoende saldo!*")
        return False
    router = aw3.eth.contract(address=AERODROME_ROUTER, abi=ROUTER_ABI)
    route  = [{"from": WETH, "to": token, "stable": False, "factory": AERODROME_FACTORY}]
    try:
        out       = await rpc_retry(router.functions.getAmountsOut(amount_wei, route).call)
        min_out   = out[-1] * (10000 - config["slippage_bps"]) // 10000
        deadline  = int(time.time()) + config["buy_timeout"]
        call_data = router.encode_abi("swapExactETHForTokens", args=[min_out, route, signer.address, deadline])
        tx_hash   = await send_tx({"to": AERODROME_ROUTER, "value": amount_wei, "data": call_data})
        receipt   = await rpc_retry(aw3.eth.wait_for_transaction_receipt, tx_hash, timeout=config["buy_timeout"])
        if receipt["status"] != 1:
            raise Exception("Tx gefaald")
        token_c   = aw3.eth.contract(address=token, abi=ERC20_ABI)
        token_bal = await rpc_retry(token_c.functions.balanceOf(signer.address).call)
        positions[token] = {
            "entry_eth":    amount_eth,
            "token_amount": token_bal,
            "buy_tx":       tx_hash,
            "timestamp":    time.time(),
            "peak_eth":     amount_eth,
            "pool":         pool,
        }
        NL = chr(10)
        await notify("*SNIPE RAAK!*" + NL + "Token: " + token + NL + "Betaald: " + str(amount_eth) + " ETH" + NL + "Tx: https://basescan.org/tx/" + tx_hash)
        logger.info("Koop OK: %s", token[:12])
        return True
    except Exception as e:
        logger.error("Koop mislukt %s: %s", token[:10], e)
        blacklist.add(token)
        return False

# =============================================================
#  VERKOPEN
# =============================================================
async def sell_token(token: str, reden: str):
    if token not in positions:
        return
    pos          = positions[token]
    token_amount = pos["token_amount"]
    router       = aw3.eth.contract(address=AERODROME_ROUTER, abi=ROUTER_ABI)
    route        = [{"from": token, "to": WETH, "stable": False, "factory": AERODROME_FACTORY}]
    try:
        token_c      = aw3.eth.contract(address=token, abi=ERC20_ABI)
        approve_data = token_c.encode_abi("approve", args=[AERODROME_ROUTER, token_amount])
        approve_hash = await send_tx({"to": token, "value": 0, "data": approve_data})
        await rpc_retry(aw3.eth.wait_for_transaction_receipt, approve_hash, timeout=20)
        out          = await rpc_retry(router.functions.getAmountsOut(token_amount, route).call)
        expected_eth = out[-1]
        min_eth      = expected_eth * (10000 - config["slippage_bps"]) // 10000
        sell_data    = router.encode_abi("swapExactTokensForETH", args=[token_amount, min_eth, route, signer.address, int(time.time()) + 20])
        tx_hash      = await send_tx({"to": AERODROME_ROUTER, "value": 0, "data": sell_data})
        receipt      = await rpc_retry(aw3.eth.wait_for_transaction_receipt, tx_hash, timeout=20)
        if receipt["status"] != 1:
            raise Exception("Verkoop gefaald")
        received = float(from_wei(expected_eth))
        invested = pos["entry_eth"]
        pnl_eth  = received - invested
        pnl_pct  = (pnl_eth / invested) * 100
        stats["trades"]    += 1
        stats["total_pnl"] += pnl_eth
        if pnl_pct >= 0:
            stats["wins"] += 1
            stats["best_trade"] = max(stats["best_trade"], pnl_pct)
        else:
            stats["losses"] += 1
            stats["worst_trade"] = min(stats["worst_trade"], pnl_pct)
        if config["reinvest"] and pnl_eth > 0:
            config["snipe_eth"] = round(config["snipe_eth"] + pnl_eth * config["reinvest_pct"] / 100, 6)
        del positions[token]
        NL   = chr(10)
        sign = "WIN" if pnl_pct >= 0 else "LOSS"
        await notify("*" + sign + " POSITIE GESLOTEN*" + NL + "Reden: " + reden + NL + "PnL: " + str(round(pnl_pct, 1)) + "% (" + str(round(pnl_eth, 5)) + " ETH)" + NL + "Tx: https://basescan.org/tx/" + tx_hash)
        logger.info("Verkoop OK: %s %+.1f%%", token[:10], pnl_pct)
    except Exception as e:
        logger.error("Verkoop mislukt %s: %s", token[:10], e)
        await notify("*Verkoop mislukt* " + token[:12] + chr(10) + str(e))

# =============================================================
#  PROCESS TOKEN
# =============================================================
async def process_new_token(token: str, pool: str, created_block: int):
    if token in blacklist or token in positions or token in seen_pools:
        return
    seen_pools.add(token)
    if await is_safe(token, pool, created_block):
        await buy_token(token, pool, created_block)
    else:
        blacklist.add(token)

# =============================================================
#  BLOCK SCANNER - directe RPC, geen web3 get_logs
# =============================================================
async def scan_new_pools():
    logger.info("Block scanner gestart")
    last_block = await aw3.eth.block_number
    while True:
        await asyncio.sleep(2)
        if not config["active"]:
            continue
        try:
            current = await aw3.eth.block_number
            if current <= last_block:
                continue
            logger.info("Scan blok %s -> %s", last_block + 1, current)
            logs = await rpc_get_logs(last_block + 1, current, AERODROME_FACTORY, POOL_CREATED_TOPIC)
            if logs:
                logger.info("Pools gevonden: %s", len(logs))
            if logs:
                tasks = []
                for log in logs:
                    t0, t1, pool = parse_pool_log(log)
                    if not t0 or not pool:
                        continue
                    blk = int(log.get("blockNumber", hex(current)), 16) if isinstance(log.get("blockNumber"), str) else log.get("blockNumber", current)
                    if t1.lower() == WETH.lower():
                        tasks.append(process_new_token(t0, pool, blk))
                    elif t0.lower() == WETH.lower():
                        tasks.append(process_new_token(t1, pool, blk))
                if tasks:
                    await asyncio.gather(*tasks)
            last_block = current
        except Exception as e:
            logger.error("Block scanner fout: %s", e)
            await asyncio.sleep(3)

# =============================================================
#  POSITIE MONITOR
# =============================================================
async def monitor_positions():
    while True:
        await asyncio.sleep(config["monitor_interval"])
        if not positions:
            continue
        for token, pos in list(positions.items()):
            try:
                router   = aw3.eth.contract(address=AERODROME_ROUTER, abi=ROUTER_ABI)
                route    = [{"from": token, "to": WETH, "stable": False, "factory": AERODROME_FACTORY}]
                out      = await rpc_retry(router.functions.getAmountsOut(pos["token_amount"], route).call)
                current  = float(from_wei(out[-1]))
                invested = pos["entry_eth"]
                pnl_pct  = ((current - invested) / invested) * 100
                if current > pos["peak_eth"]:
                    positions[token]["peak_eth"] = current
                peak        = positions[token]["peak_eth"]
                drop        = ((peak - current) / peak) * 100 if peak > 0 else 0
                peak_profit = ((peak - invested) / invested) * 100
                if pnl_pct >= config["take_profit_pct"]:
                    await sell_token(token, "Take Profit +" + str(round(pnl_pct, 1)) + "%")
                elif peak_profit >= config["min_profit_to_trail"] and drop >= config["trailing_stop_pct"]:
                    await sell_token(token, "Trailing Stop")
                elif pnl_pct <= -config["hard_stop_pct"]:
                    await sell_token(token, "Hard Stop " + str(round(pnl_pct, 1)) + "%")
            except Exception as e:
                logger.warning("Monitor fout %s: %s", token[:10], e)

# =============================================================
#  TELEGRAM COMMANDO'S
# =============================================================
async def cmd_start(update, context):
    if update.effective_user.id != OWNER_ID:
        return
    config["active"] = True
    NL = chr(10)
    await update.message.reply_text("*Synthora Elite v3 ACTIEF*" + NL + "Block scanner: aan" + NL + "Honeypot check: aan" + NL + "Auto-reinvest: aan" + NL + "Chain: Base Mainnet", parse_mode="Markdown")

async def cmd_stop(update, context):
    if update.effective_user.id != OWNER_ID:
        return
    config["active"] = False
    await update.message.reply_text("*Sniper gestopt*" + chr(10) + "Posities worden nog gemonitord.", parse_mode="Markdown")

async def cmd_status(update, context):
    if update.effective_user.id != OWNER_ID:
        return
    balance  = float(from_wei(w3s.eth.get_balance(signer.address)))
    status   = "ACTIEF" if config["active"] else "GESTOPT"
    NL       = chr(10)
    pos_lines = []
    for t, p in positions.items():
        try:
            router = w3s.eth.contract(address=AERODROME_ROUTER, abi=ROUTER_ABI)
            route  = [{"from": t, "to": WETH, "stable": False, "factory": AERODROME_FACTORY}]
            out    = router.functions.getAmountsOut(p["token_amount"], route).call()
            curr   = float(from_wei(out[-1]))
            pnl    = ((curr - p["entry_eth"]) / p["entry_eth"]) * 100
            pos_lines.append(t[:12] + " " + ("+" if pnl >= 0 else "") + str(round(pnl, 1)) + "%")
        except Exception:
            pos_lines.append(t[:12] + " ?%")
    pos_txt = NL.join(pos_lines) if pos_lines else "Geen posities"
    await update.message.reply_text("*Status*" + NL + NL + status + " | " + str(round(balance, 5)) + " ETH" + NL + "Posities: " + str(len(positions)) + "/" + str(int(config["max_positions"])) + NL + NL + pos_txt + NL + NL + "Snipe: " + str(config["snipe_eth"]) + " ETH | TP: +" + str(int(config["take_profit_pct"])) + "%" + NL + "Trail: -" + str(int(config["trailing_stop_pct"])) + "% | Stop: -" + str(int(config["hard_stop_pct"])) + "%", parse_mode="Markdown")

async def cmd_stats(update, context):
    if update.effective_user.id != OWNER_ID:
        return
    uptime  = (time.time() - stats["started"]) / 3600
    winrate = (stats["wins"] / stats["trades"] * 100) if stats["trades"] > 0 else 0
    balance = float(from_wei(w3s.eth.get_balance(signer.address)))
    NL      = chr(10)
    await update.message.reply_text("*Statistieken*" + NL + NL + "Uptime: " + str(round(uptime, 1)) + "u" + NL + "Trades: " + str(stats["trades"]) + " | Winrate: " + str(round(winrate, 1)) + "%" + NL + "PnL: " + str(round(stats["total_pnl"], 5)) + " ETH" + NL + "Best: +" + str(round(stats["best_trade"], 1)) + "% | Worst: " + str(round(stats["worst_trade"], 1)) + "%" + NL + "Honeypots: " + str(stats["honeypots_blocked"]) + NL + "Saldo: " + str(round(balance, 5)) + " ETH", parse_mode="Markdown")

async def cmd_set(update, context):
    if update.effective_user.id != OWNER_ID:
        return
    if len(context.args) < 2:
        NL = chr(10)
        await update.message.reply_text("*Instellingen:*" + NL + "eth | tp | trail | hardstop | mintrail" + NL + "minliq | slippage | maxpos | gas | maxgas" + NL + "reinvestpct | maxage | monitor" + NL + "reinvest | honeypot (1/0)", parse_mode="Markdown")
        return
    num_map = {"eth": "snipe_eth", "tp": "take_profit_pct", "trail": "trailing_stop_pct", "hardstop": "hard_stop_pct", "mintrail": "min_profit_to_trail", "minliq": "min_liquidity_eth", "slippage": "slippage_bps", "maxpos": "max_positions", "gas": "gas_multiplier", "maxgas": "max_gas_gwei", "reinvestpct": "reinvest_pct", "maxage": "max_token_age_blocks", "monitor": "monitor_interval"}
    bool_map = {"reinvest": "reinvest", "honeypot": "honeypot_check"}
    key = context.args[0].lower()
    val = context.args[1]
    if key in num_map:
        config[num_map[key]] = float(val)
        await update.message.reply_text("OK: " + key + " = " + val)
    elif key in bool_map:
        config[bool_map[key]] = bool(int(val))
        await update.message.reply_text("OK: " + key + " = " + ("aan" if config[bool_map[key]] else "uit"))
    else:
        await update.message.reply_text("Onbekende instelling: " + key)

async def cmd_buy(update, context):
    if update.effective_user.id != OWNER_ID:
        return
    if not context.args:
        await update.message.reply_text("Gebruik: /buy <token_adres>")
        return
    token = checksum(context.args[0])
    msg   = await update.message.reply_text("Kopen...")
    try:
        logs = await rpc_get_logs(w3s.eth.block_number - 100000, "latest", AERODROME_FACTORY, POOL_CREATED_TOPIC)
        pool = None
        for log in logs:
            t0, t1, pool_found = parse_pool_log(log)
            if not t0:
                continue
            if token.lower() in [t0.lower(), t1.lower()]:
                pool = pool_found
                break
        if not pool:
            await msg.edit_text("Pool niet gevonden.")
            return
        ok = await buy_token(token, pool)
        if not ok:
            await msg.edit_text("Koop mislukt.")
    except Exception as e:
        await msg.edit_text("Fout: " + str(e))

async def cmd_sell(update, context):
    if update.effective_user.id != OWNER_ID:
        return
    if not context.args:
        await update.message.reply_text("Gebruik: /sell <token_adres>")
        return
    token = checksum(context.args[0])
    if token not in positions:
        await update.message.reply_text("Geen open positie.")
        return
    await sell_token(token, "Handmatig")

async def cmd_closeall(update, context):
    if update.effective_user.id != OWNER_ID:
        return
    if not positions:
        await update.message.reply_text("Geen posities.")
        return
    await update.message.reply_text("Sluiten: " + str(len(positions)) + " posities...")
    await asyncio.gather(*[sell_token(t, "Alles sluiten") for t in list(positions.keys())])

async def cmd_skyline(update, context):
    if update.effective_user.id != OWNER_ID:
        return
    balance = float(from_wei(w3s.eth.get_balance(signer.address)))
    NL      = chr(10)
    await update.message.reply_text("*Skyline*" + NL + NL + "Wallet: " + signer.address + NL + "Saldo: " + str(round(balance, 6)) + " ETH" + NL + "Block: " + str(w3s.eth.block_number) + NL + "Chain: Base Mainnet", parse_mode="Markdown")

# =============================================================
#  BOT START
# =============================================================
# Base official bridge contract op Ethereum mainnet
BASE_BRIDGE_CONTRACT = "0x3154Cf16ccdb4C6d922629664174b904d80F2C35"
ETH_RPC_URL = os.environ.get("EVM_RPC_URL", "https://eth.llamarpc.com")

async def cmd_bridge(update, context):
    if update.effective_user.id != OWNER_ID:
        return
    if not context.args:
        await update.message.reply_text("Gebruik: /bridge <bedrag_eth>" + chr(10) + "Bridget ETH van Ethereum naar Base")
        return
    try:
        amount_eth = float(context.args[0])
    except Exception:
        await update.message.reply_text("Fout: /bridge 0.01")
        return
    msg = await update.message.reply_text("Bridge starten...")
    try:
        # Maak een web3 verbinding met Ethereum mainnet
        w3_eth = Web3(Web3.HTTPProvider(ETH_RPC_URL, request_kwargs={"timeout": 10}))
        aw3_eth = AsyncWeb3(AsyncHTTPProvider(ETH_RPC_URL))

        amount_wei = to_wei(amount_eth)
        balance    = w3_eth.eth.get_balance(signer.address)

        if balance < amount_wei:
            await msg.edit_text("Onvoldoende ETH op Ethereum mainnet." + chr(10) + "Saldo: " + str(round(float(from_wei(balance)), 6)) + " ETH")
            return

        # Base bridge: stuur ETH naar bridge contract op Ethereum
        # Het bridge contract stuurt het automatisch door naar Base
        nonce     = w3_eth.eth.get_transaction_count(signer.address, "pending")
        gas_price = int(w3_eth.eth.gas_price * 1.2)

        tx = {
            "to":       Web3.to_checksum_address(BASE_BRIDGE_CONTRACT),
            "value":    amount_wei,
            "gas":      200000,
            "gasPrice": gas_price,
            "nonce":    nonce,
            "chainId":  1,  # Ethereum mainnet
            "data":     "0x",
        }

        signed  = signer.sign_transaction(tx)
        raw     = getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction", None)
        tx_hash = w3_eth.eth.send_raw_transaction(raw)
        tx_hex  = tx_hash.hex() if hasattr(tx_hash, "hex") else str(tx_hash)

        await msg.edit_text(
            "*Bridge gestart!*" + chr(10) +
            str(amount_eth) + " ETH van Ethereum → Base" + chr(10) +
            "Duurt ~10-15 minuten" + chr(10) +
            "Tx: https://etherscan.io/tx/" + tx_hex,
            parse_mode="Markdown"
        )
        logger.info("Bridge: %.6f ETH naar Base, tx=%s", amount_eth, tx_hex)
    except Exception as e:
        await msg.edit_text("Bridge fout: " + str(e))
        logger.error("Bridge fout: %s", e)

async def cmd_withdraw(update, context):
    if update.effective_user.id != OWNER_ID:
        return
    if not context.args:
        await update.message.reply_text("Gebruik: /withdraw <bedrag_eth> <naar_adres>")
        return
    try:
        amount_eth = float(context.args[0])
        to_addr    = Web3.to_checksum_address(context.args[1])
    except Exception:
        await update.message.reply_text("Fout: /withdraw 0.01 0xJOUWADRES")
        return
    msg = await update.message.reply_text("Versturen...")
    try:
        amount_wei = to_wei(amount_eth)
        balance    = await rpc_retry(aw3.eth.get_balance, signer.address)
        if balance < amount_wei:
            await msg.edit_text("Onvoldoende saldo. Huidig: " + str(round(float(from_wei(balance)), 6)) + " ETH")
            return
        gas_params = await get_gas_params()
        tx = {
            "to":    to_addr,
            "value": amount_wei,
            "gas":   21000,
            "chainId": BASE_CHAIN_ID,
        }
        tx.update(gas_params)
        tx_hash = await send_tx(tx)
        await msg.edit_text("*Verstuurd!*" + chr(10) + str(amount_eth) + " ETH naar " + to_addr + chr(10) + "Tx: https://basescan.org/tx/" + tx_hash, parse_mode="Markdown")
        logger.info("Withdraw: %.6f ETH naar %s", amount_eth, to_addr)
    except Exception as e:
        await msg.edit_text("Fout: " + str(e))

async def run_bot():
    global tg_bot
    await asyncio.sleep(2)
    tg_bot = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    for cmd, fn in [("start", cmd_start), ("stop", cmd_stop), ("status", cmd_status), ("stats", cmd_stats), ("set", cmd_set), ("buy", cmd_buy), ("sell", cmd_sell), ("closeall", cmd_closeall), ("skyline", cmd_skyline), ("bridge", cmd_bridge), ("withdraw", cmd_withdraw)]:
        tg_bot.add_handler(CommandHandler(cmd, fn))
    await tg_bot.initialize()
    await tg_bot.start()
    await tg_bot.updater.start_polling()
    logger.info("Telegram bot actief")

# =============================================================
#  FASTAPI
# =============================================================
@app.on_event("startup")
async def startup():
    asyncio.create_task(run_bot())
    asyncio.create_task(scan_new_pools())
    asyncio.create_task(monitor_positions())

@app.get("/")
async def health():
    balance = float(from_wei(w3s.eth.get_balance(signer.address)))
    return {"status": "online", "active": config["active"], "positions": len(positions), "pnl_eth": round(stats["total_pnl"], 6), "balance": round(balance, 6), "wallet": signer.address}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
