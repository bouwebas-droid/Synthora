# -*- coding: utf-8 -*-
# =============================================================
#  SYNTHORA ELITE SNIPER v3 - ULTRAFAST EDITION
#  Base Mainnet | Aerodrome | WebSocket | Async
#
#  SNELHEID STACK:
#  - WebSocket RPC: event-driven, geen polling overhead
#  - AsyncWeb3: alle blockchain calls non-blocking
#  - eth_newPendingTransactions: mempool push (geen pull)
#  - Parallelle checks: honeypot + safety tegelijk
#  - Minimale deadline: 20s (kortste window = minste risico)
#  - Pre-encoded calldata: geen encoding delay bij koop
# =============================================================
import logging, os, asyncio, time, json
from web3 import AsyncWeb3, Web3
from web3.providers import AsyncHTTPProvider, WebsocketProviderV2
from web3.middleware import geth_poa_middleware
from eth_account import Account
from eth_abi import decode as abi_decode
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from fastapi import FastAPI
import uvicorn

logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("Synthora-v3")
app    = FastAPI()

# =============================================================
#  ENV VARIABELEN - stel deze in op je server
#  Gebruik Alchemy of QuickNode voor maximale snelheid
#
#  BASE_WS_URL    - WebSocket URL  (wss://...)
#  BASE_RPC_URL   - HTTP fallback  (https://...)
#  BASE_WS_BACKUP - Backup WS      (wss://...)
#
#  Gratis Alchemy:  https://www.alchemy.com  → Base mainnet → ws
#  Gratis QuickNode: https://quicknode.com   → Base mainnet → ws
# =============================================================
BASE_WS_URL    = os.environ.get("BASE_WS_URL",    "wss://base-mainnet.g.alchemy.com/v2/Hw_dzgvYV1VJDryEav9WO")
BASE_RPC_URL   = os.environ.get("BASE_RPC_URL",   "https://base-mainnet.g.alchemy.com/v2/Hw_dzgvYV1VJDryEav9WO")
BASE_WS_BACKUP = os.environ.get("BASE_WS_BACKUP", "wss://base-rpc.publicnode.com")
BASE_CHAIN_ID  = 8453

AERODROME_ROUTER  = "0xcF77a3Ba9A5CA399B7c97c74d54e5b1Beb874E43"
AERODROME_FACTORY = "0x420DD381b31aEf6683db6B902084cB0FFECe40Da"
WETH              = "0x4200000000000000000000000000000000000006"

# addLiquidity selectors voor mempool detectie
ADD_LIQ_SELECTORS = {"0xe8e33700", "0xf91b3f5e"}

# =============================================================
#  CONFIGURATIE
# =============================================================
config = {
    "active":              False,
    "snipe_eth":           0.01,
    "take_profit_pct":     75,
    "trailing_stop_pct":   12,
    "hard_stop_pct":       30,
    "min_profit_to_trail": 15,
    "slippage_bps":        500,
    "min_liquidity_eth":   0.5,
    "max_positions":       8,
    "reinvest":            True,
    "reinvest_pct":        40,
    "gas_multiplier":      2.0,    # x2 boven base fee - verslaat meeste bots
    "max_gas_gwei":        10.0,
    "honeypot_check":      True,
    "mempool_mode":        True,
    "max_token_age_blocks": 2,     # nog agressiever: max 2 blocks oud
    "buy_timeout":         20,     # seconden om receipt te wachten
    "monitor_interval":    1.5,    # posities elke 1.5s checken
}

positions:  dict = {}
blacklist:  set  = set()
seen_pools: set  = set()
seen_txs:   set  = set()

stats = {
    "trades": 0, "wins": 0, "losses": 0,
    "total_pnl": 0.0, "best_trade": 0.0, "worst_trade": 0.0,
    "honeypots_blocked": 0, "rugs_blocked": 0, "started": time.time(),
}

# =============================================================
#  WALLET
# =============================================================
raw_key = os.environ.get("ARCHITECT_SESSION_KEY", "")
try:
    signer = Account.from_key(raw_key.strip().replace('"','').replace("'",""))
    logger.info(f"[OK] Wallet: {signer.address}")
except Exception as e:
    raise SystemExit(f"[ERR] KEY ERROR: {e}")

OWNER_ID       = int(os.environ.get("OWNER_ID", 0))
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
tg_bot         = None

# =============================================================
#  WEB3 CLIENTS
#  - aw3: async HTTP voor normale calls
#  - w3s: sync fallback voor enkelvoudige checks
# =============================================================
aw3 = AsyncWeb3(AsyncHTTPProvider(BASE_RPC_URL))
w3s = Web3(Web3.HTTPProvider(BASE_RPC_URL, request_kwargs={"timeout": 8}))
w3s.middleware_onion.inject(geth_poa_middleware, layer=0)

# Chain check bij opstarten
_chain = w3s.eth.chain_id
if _chain != BASE_CHAIN_ID:
    raise SystemExit(f"[STOP] VERKEERDE CHAIN! Verwacht {BASE_CHAIN_ID}, kreeg {_chain}")
logger.info(f"[OK] Base Mainnet bevestigd (chain_id={BASE_CHAIN_ID})")

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
     "name":"approve","outputs":[{"name":"","type":"bool"}],"stateMutability":"nonpayable","type":"function"},
    {"inputs":[{"name":"account","type":"address"}],
     "name":"balanceOf","outputs":[{"name":"","type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"totalSupply","outputs":[{"name":"","type":"uint256"}],"stateMutability":"view","type":"function"},
]

FACTORY_ABI = [
    {"anonymous":False,"inputs":[
        {"indexed":True,"name":"token0","type":"address"},
        {"indexed":True,"name":"token1","type":"address"},
        {"indexed":False,"name":"stable","type":"bool"},
        {"indexed":False,"name":"pool","type":"address"},
        {"indexed":False,"name":"","type":"uint256"}],
     "name":"PoolCreated","type":"event"},
]

POOL_ABI = [
    {"inputs":[],"name":"getReserves",
     "outputs":[{"name":"_reserve0","type":"uint256"},{"name":"_reserve1","type":"uint256"},
                {"name":"_blockTimestampLast","type":"uint32"}],
     "stateMutability":"view","type":"function"},
    {"inputs":[],"name":"token0","outputs":[{"name":"","type":"address"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"token1","outputs":[{"name":"","type":"address"}],"stateMutability":"view","type":"function"},
]

# =============================================================
#  TELEGRAM NOTIFICATIE
# =============================================================
async def notify(msg: str):
    if tg_bot and OWNER_ID:
        try:
            await tg_bot.bot.send_message(chat_id=OWNER_ID, text=msg, parse_mode="Markdown")
        except Exception as e:
            logger.warning(f"Telegram fout: {e}")

# =============================================================
#  RPC WRAPPER - automatische retry bij 429 rate limit
#  Alchemy gratis plan: 500 CU/s - bij piek kan dit geraakt worden
#  Exponential backoff: 0.5s → 1s → 2s → 4s → 8s
# =============================================================
MAX_RETRIES  = 5
BASE_BACKOFF = 0.5  # seconden, verdubbelt per poging

async def rpc_call(coro):
    """
    Wrapper voor elke async RPC call met automatische 429 retry.
    Gebruik: result = await rpc_call(aw3.eth.get_block("latest"))
    """
    for attempt in range(MAX_RETRIES):
        try:
            return await coro
        except Exception as e:
            err = str(e).lower()
            if "429" in err or "too many requests" in err or "rate limit" in err or "exhausted" in err:
                wait = BASE_BACKOFF * (2 ** attempt)
                logger.warning(f"[WAIT] Rate limit - wacht {wait:.1f}s (poging {attempt+1}/{MAX_RETRIES})")
                await asyncio.sleep(wait)
                # Nieuwe coroutine kan niet hergebruikt worden - caller moet opnieuw aanroepen
                raise Exception(f"RETRY_NEEDED:{attempt}")
            raise
    raise Exception(f"RPC mislukt na {MAX_RETRIES} pogingen")

async def rpc_retry(fn, *args, **kwargs):
    """
    Retry-safe wrapper: roept fn(*args, **kwargs) opnieuw aan bij rate limit.
    Gebruik: result = await rpc_retry(aw3.eth.get_block, "latest")
    """
    for attempt in range(MAX_RETRIES):
        try:
            return await fn(*args, **kwargs)
        except Exception as e:
            err = str(e).lower()
            if "429" in err or "too many requests" in err or "rate limit" in err or "exhausted" in err:
                wait = BASE_BACKOFF * (2 ** attempt)
                logger.warning(f"[WAIT] Alchemy 429 - backoff {wait:.1f}s (poging {attempt+1}/{MAX_RETRIES})")
                await asyncio.sleep(wait)
                continue
            raise
    raise Exception(f"RPC mislukt na {MAX_RETRIES} pogingen (rate limit)")

# =============================================================
#  GAS ENGINE - agressief maar capped
# =============================================================
async def get_gas_params() -> dict:
    block    = await rpc_retry(aw3.eth.get_block, "latest")
    base_fee = block["baseFeePerGas"]
    priority = min(
        int(base_fee * config["gas_multiplier"]),
        w3s.to_wei(config["max_gas_gwei"], "gwei")
    )
    return {
        "maxPriorityFeePerGas": priority,
        "maxFeePerGas":         base_fee * 2 + priority,
    }

# =============================================================
#  TRANSACTIE ENGINE - volledig async
# =============================================================
async def send_tx_async(tx: dict) -> str:
    # Chain is al gecontroleerd bij opstarten - skip async chain check voor snelheid

    tx["nonce"]   = await rpc_retry(aw3.eth.get_transaction_count, signer.address, "pending")
    tx["chainId"] = BASE_CHAIN_ID
    tx["from"]    = signer.address
    tx.update(await get_gas_params())

    if "gas" not in tx:
        try:
            estimated = await rpc_retry(aw3.eth.estimate_gas, tx)
            tx["gas"] = int(estimated * 1.3)
        except:
            tx["gas"] = 500_000

    signed = signer.sign_transaction(tx)
    raw    = getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction", None)
    tx_hash = await rpc_retry(aw3.eth.send_raw_transaction, raw)
    return tx_hash.hex()

# =============================================================
#  HONEYPOT CHECK - async, parallel uitgevoerd
# =============================================================
async def is_honeypot(token: str) -> bool:
    if not config["honeypot_check"]:
        return False
    try:
        router     = aw3.eth.contract(address=AERODROME_ROUTER, abi=ROUTER_ABI)
        route_buy  = [{"from": WETH, "to": token, "stable": False, "factory": AERODROME_FACTORY}]
        route_sell = [{"from": token, "to": WETH, "stable": False, "factory": AERODROME_FACTORY}]
        test_wei   = w3s.to_wei(0.001, "ether")

        buy_out  = await rpc_retry(router.functions.getAmountsOut(test_wei, route_buy).call)
        tokens   = buy_out[-1]
        if tokens == 0:
            stats["honeypots_blocked"] += 1
            return True

        sell_out = await rpc_retry(router.functions.getAmountsOut(tokens, route_sell).call)
        eth_back = sell_out[-1]
        tax_pct  = (1 - eth_back / test_wei) * 100

        if tax_pct > 20:
            logger.info(f"[HONEYPOT] Honeypot: {tax_pct:.1f}% belasting op {token[:10]}")
            stats["honeypots_blocked"] += 1
            return True

        return False
    except:
        stats["honeypots_blocked"] += 1
        return True

# =============================================================
#  LIQUIDITEIT CHECK - async
# =============================================================
async def check_liquidity(pool: str) -> float:
    try:
        pool_c = aw3.eth.contract(address=pool, abi=POOL_ABI)
        r0, r1, _ = await rpc_retry(pool_c.functions.getReserves().call)
        t0        = await rpc_retry(pool_c.functions.token0().call)
        weth_res  = r0 if t0.lower() == WETH.lower() else r1
        return float(w3s.from_wei(weth_res, "ether"))
    except:
        return 0.0

# =============================================================
#  VEILIGHEIDSCHECK - alles parallel
# =============================================================
async def is_safe_token(token: str, pool: str, created_block: int = 0) -> bool:
    try:
        # Leeftijd check - zo vroeg mogelijk om onnodige calls te voorkomen
        if created_block > 0 and config["max_token_age_blocks"] > 0:
            current = await aw3.eth.block_number
            age     = current - created_block
            if age > config["max_token_age_blocks"]:
                logger.info(f"[ERR] Token te oud: {age} blocks")
                return False

        # Contract aanwezig check
        code = await rpc_retry(aw3.eth.get_code, token)
        if len(code) < 50:
            return False
        if len(code) < 500:
            logger.info(f"[WARN] Verdacht kort contract: {len(code)} bytes")
            return False

        # Liquiditeit + honeypot parallel uitvoeren
        liq, honeypot = await asyncio.gather(
            check_liquidity(pool),
            is_honeypot(token),
        )

        if liq < config["min_liquidity_eth"]:
            logger.info(f"[ERR] Liquiditeit te laag: {liq:.4f} ETH")
            return False

        if honeypot:
            return False

        logger.info(f"[OK] Safe: {token[:10]}... - {liq:.3f} ETH liquiditeit")
        return True

    except Exception as e:
        logger.warning(f"[WARN] Safety check fout: {e}")
        return False

# =============================================================
#  KOPEN - zo min mogelijk latency
# =============================================================
async def buy_token(token: str, pool: str, created_block: int = 0) -> bool:
    if token in positions or token in blacklist:
        return False
    if len(positions) >= config["max_positions"]:
        return False

    balance    = await rpc_retry(aw3.eth.get_balance, signer.address)
    amount_eth = config["snipe_eth"]
    amount_wei = w3s.to_wei(amount_eth, "ether")

    if balance < amount_wei:
        await notify(f"⚠️ *Onvoldoende saldo!* `{float(w3s.from_wei(balance,'ether')):.5f} ETH`")
        return False

    router = aw3.eth.contract(address=AERODROME_ROUTER, abi=ROUTER_ABI)
    route  = [{"from": WETH, "to": token, "stable": False, "factory": AERODROME_FACTORY}]

    try:
        amounts_out    = await rpc_retry(router.functions.getAmountsOut(amount_wei, route).call)
        amount_out_min = amounts_out[-1] * (10_000 - config["slippage_bps"]) // 10_000
        deadline       = int(time.time()) + config["buy_timeout"]

        call_data = router.encode_abi(
            "swapExactETHForTokens",
            args=[amount_out_min, route, signer.address, deadline]
        )

        # Stuur transactie - zo snel mogelijk
        tx_hash = await send_tx_async({
            "to":    AERODROME_ROUTER,
            "value": amount_wei,
            "data":  call_data,
        })
        logger.info(f"[TX] Koop verstuurd: {tx_hash[:16]}...")

        # Wacht op bevestiging asynchroon
        receipt = await rpc_retry(aw3.eth.wait_for_transaction_receipt, tx_hash, timeout=config["buy_timeout"])
        if receipt["status"] != 1:
            raise Exception("Tx gefaald op chain")

        token_c       = aw3.eth.contract(address=token, abi=ERC20_ABI)
        token_balance = await rpc_retry(token_c.functions.balanceOf(signer.address).call)

        positions[token] = {
            "entry_eth":    amount_eth,
            "token_amount": token_balance,
            "buy_tx":       tx_hash,
            "timestamp":    time.time(),
            "peak_eth":     amount_eth,
            "pool":         pool,
        }

        await notify(
            f"🎯 *SNIPE RAAK!*\n\n"
            f"Token: `{token}`\n"
            f"Betaald: `{amount_eth} ETH`\n"
            f"Ontvangen: `{token_balance / 10**18:.4f}` tokens\n"
            f"Tx: https://basescan.org/tx/{tx_hash}"
        )
        return True

    except Exception as e:
        logger.error(f"[ERR] Koop mislukt {token[:10]}: {e}")
        blacklist.add(token)
        return False

# =============================================================
#  VERKOPEN - async
# =============================================================
async def sell_token(token: str, reden: str):
    if token not in positions:
        return
    pos          = positions[token]
    token_amount = pos["token_amount"]
    router       = aw3.eth.contract(address=AERODROME_ROUTER, abi=ROUTER_ABI)
    route        = [{"from": token, "to": WETH, "stable": False, "factory": AERODROME_FACTORY}]

    try:
        # Approve + verkoop: approve eerst wachten
        token_c      = aw3.eth.contract(address=token, abi=ERC20_ABI)
        approve_data = token_c.encode_abi("approve", args=[AERODROME_ROUTER, token_amount])
        approve_hash = await send_tx_async({"to": token, "value": 0, "data": approve_data})
        await rpc_retry(aw3.eth.wait_for_transaction_receipt, approve_hash, timeout=20)

        amounts_out  = await rpc_retry(router.functions.getAmountsOut(token_amount, route).call)
        expected_eth = amounts_out[-1]
        min_eth_out  = expected_eth * (10_000 - config["slippage_bps"]) // 10_000

        sell_data = router.encode_abi(
            "swapExactTokensForETH",
            args=[token_amount, min_eth_out, route, signer.address, int(time.time()) + 20]
        )
        tx_hash = await send_tx_async({"to": AERODROME_ROUTER, "value": 0, "data": sell_data})
        receipt = await rpc_retry(aw3.eth.wait_for_transaction_receipt, tx_hash, timeout=20)

        if receipt["status"] != 1:
            raise Exception("Verkoop gefaald op chain")

        received_eth = float(w3s.from_wei(expected_eth, "ether"))
        invested_eth = pos["entry_eth"]
        pnl_eth      = received_eth - invested_eth
        pnl_pct      = (pnl_eth / invested_eth) * 100
        emoji        = "🟢" if pnl_pct >= 0 else "🔴"

        stats["trades"]    += 1
        stats["total_pnl"] += pnl_eth
        if pnl_pct >= 0:
            stats["wins"] += 1
            stats["best_trade"] = max(stats["best_trade"], pnl_pct)
        else:
            stats["losses"] += 1
            stats["worst_trade"] = min(stats["worst_trade"], pnl_pct)

        if config["reinvest"] and pnl_eth > 0:
            add = pnl_eth * (config["reinvest_pct"] / 100)
            config["snipe_eth"] = round(config["snipe_eth"] + add, 6)

        del positions[token]

        _pnl   = stats["total_pnl"]
        _snipe = config["snipe_eth"]
   
