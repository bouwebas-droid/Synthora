# -*- coding: utf-8 -*-
# =============================================================
#  SYNTHORA ELITE SNIPER v3
#  Base Mainnet | Aerodrome | WebSocket | Async
# =============================================================
import logging, os, asyncio, time
from web3 import AsyncWeb3, Web3
from web3.providers import AsyncHTTPProvider, WebsocketProviderV2
from web3.middleware import geth_poa_middleware
from eth_account import Account
from eth_abi import decode as abi_decode
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from fastapi import FastAPI
import uvicorn

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger("Synthora-v3")
app    = FastAPI()

BASE_WS_URL    = os.environ.get("BASE_WS_URL",    "wss://base-mainnet.g.alchemy.com/v2/Hw_dzgvYV1VJDryEav9WO")
BASE_RPC_URL   = os.environ.get("BASE_RPC_URL",   "https://base-mainnet.g.alchemy.com/v2/Hw_dzgvYV1VJDryEav9WO")
BASE_WS_BACKUP = os.environ.get("BASE_WS_BACKUP", "wss://base-rpc.publicnode.com")
BASE_CHAIN_ID  = 8453

AERODROME_ROUTER  = "0xcF77a3Ba9A5CA399B7c97c74d54e5b1Beb874E43"
AERODROME_FACTORY = "0x420DD381b31aEf6683db6B902084cB0FFECe40Da"
WETH              = "0x4200000000000000000000000000000000000006"
ADD_LIQ_SELECTORS = {"0xe8e33700", "0xf91b3f5e"}

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
    "mempool_mode":         True,
    "max_token_age_blocks": 2,
    "buy_timeout":          20,
    "monitor_interval":     1.5,
}

positions  = {}
blacklist  = set()
seen_pools = set()
seen_txs   = set()

stats = {
    "trades": 0, "wins": 0, "losses": 0,
    "total_pnl": 0.0, "best_trade": 0.0, "worst_trade": 0.0,
    "honeypots_blocked": 0, "rugs_blocked": 0, "started": time.time(),
}

raw_key = os.environ.get("ARCHITECT_SESSION_KEY", "")
try:
    signer = Account.from_key(raw_key.strip().replace('"', "").replace("'", ""))
    logger.info("[OK] Wallet: %s", signer.address)
except Exception as e:
    raise SystemExit("[ERR] KEY ERROR: " + str(e))

OWNER_ID       = int(os.environ.get("OWNER_ID", 0))
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
tg_bot         = None

aw3 = AsyncWeb3(AsyncHTTPProvider(BASE_RPC_URL))
w3s = Web3(Web3.HTTPProvider(BASE_RPC_URL, request_kwargs={"timeout": 8}))
w3s.middleware_onion.inject(geth_poa_middleware, layer=0)

_chain = w3s.eth.chain_id
if _chain != BASE_CHAIN_ID:
    raise SystemExit("[STOP] Verkeerde chain! Verwacht " + str(BASE_CHAIN_ID) + " kreeg " + str(_chain))
logger.info("[OK] Base Mainnet bevestigd chain_id=%s", BASE_CHAIN_ID)

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

MAX_RETRIES  = 5
BASE_BACKOFF = 0.5

async def rpc_retry(fn, *args, **kwargs):
    for attempt in range(MAX_RETRIES):
        try:
            return await fn(*args, **kwargs)
        except Exception as e:
            err = str(e).lower()
            if "429" in err or "too many requests" in err or "rate limit" in err:
                wait = BASE_BACKOFF * (2 ** attempt)
                logger.warning("[WAIT] Rate limit backoff %.1fs attempt %d/%d", wait, attempt+1, MAX_RETRIES)
                await asyncio.sleep(wait)
                continue
            raise
    raise Exception("RPC failed after " + str(MAX_RETRIES) + " retries")

async def notify(msg):
    if tg_bot and OWNER_ID:
        try:
            await tg_bot.bot.send_message(chat_id=OWNER_ID, text=msg, parse_mode="Markdown")
        except Exception as e:
            logger.warning("[WARN] Telegram fout: %s", e)

async def get_gas_params():
    block    = await rpc_retry(aw3.eth.get_block, "latest")
    base_fee = block["baseFeePerGas"]
    priority = min(int(base_fee * config["gas_multiplier"]), w3s.to_wei(config["max_gas_gwei"], "gwei"))
    return {"maxPriorityFeePerGas": priority, "maxFeePerGas": base_fee * 2 + priority}

async def send_tx_async(tx):
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
    return tx_hash.hex()

async def is_honeypot(token):
    if not config["honeypot_check"]:
        return False
    try:
        router     = aw3.eth.contract(address=AERODROME_ROUTER, abi=ROUTER_ABI)
        route_buy  = [{"from": WETH, "to": token, "stable": False, "factory": AERODROME_FACTORY}]
        route_sell = [{"from": token, "to": WETH, "stable": False, "factory": AERODROME_FACTORY}]
        test_wei   = w3s.to_wei(0.001, "ether")
        buy_out    = await rpc_retry(router.functions.getAmountsOut(test_wei, route_buy).call)
        tokens     = buy_out[-1]
        if tokens == 0:
            stats["honeypots_blocked"] += 1
            return True
        sell_out = await rpc_retry(router.functions.getAmountsOut(tokens, route_sell).call)
        eth_back = sell_out[-1]
        tax_pct  = (1 - eth_back / test_wei) * 100
        if tax_pct > 20:
            logger.info("[HONEYPOT] %.1f%% belasting op %s", tax_pct, token[:10])
            stats["honeypots_blocked"] += 1
            return True
        return False
    except Exception:
        stats["honeypots_blocked"] += 1
        return True

async def check_liquidity(pool):
    try:
        pool_c    = aw3.eth.contract(address=pool, abi=POOL_ABI)
        r0, r1, _ = await rpc_retry(pool_c.functions.getReserves().call)
        t0        = await rpc_retry(pool_c.functions.token0().call)
        weth_res  = r0 if t0.lower() == WETH.lower() else r1
        return float(w3s.from_wei(weth_res, "ether"))
    except Exception:
        return 0.0

async def is_safe_token(token, pool, created_block=0):
    try:
        if created_block > 0 and config["max_token_age_blocks"] > 0:
            current = await aw3.eth.block_number
            age     = current - created_block
            if age > config["max_token_age_blocks"]:
                logger.info("[SKIP] Token te oud: %d blocks", age)
                return False
        code = await rpc_retry(aw3.eth.get_code, token)
        if len(code) < 50:
            return False
        if len(code) < 500:
            logger.info("[WARN] Kort contract: %d bytes", len(code))
            return False
        liq, honeypot = await asyncio.gather(check_liquidity(pool), is_honeypot(token))
        if liq < config["min_liquidity_eth"]:
            logger.info("[SKIP] Liquiditeit te laag: %.4f ETH", liq)
            return False
        if honeypot:
            return False
        logger.info("[OK] Safe token %s - %.3f ETH liq", token[:10], liq)
        return True
    except Exception as e:
        logger.warning("[WARN] Safety check fout: %s", e)
        return False

async def buy_token(token, pool, created_block=0):
    if token in positions or token in blacklist:
        return False
    if len(positions) >= config["max_positions"]:
        return False
    balance    = await rpc_retry(aw3.eth.get_balance, signer.address)
    amount_eth = config["snipe_eth"]
    amount_wei = w3s.to_wei(amount_eth, "ether")
    if balance < amount_wei:
        await notify("*[WARN] Onvoldoende saldo!*\nBeschikbaar: " + str(round(float(w3s.from_wei(balance, "ether")), 5)) + " ETH")
        return False
    router = aw3.eth.contract(address=AERODROME_ROUTER, abi=ROUTER_ABI)
    route  = [{"from": WETH, "to": token, "stable": False, "factory": AERODROME_FACTORY}]
    try:
        amounts_out    = await rpc_retry(router.functions.getAmountsOut(amount_wei, route).call)
        amount_out_min = amounts_out[-1] * (10000 - config["slippage_bps"]) // 10000
        deadline       = int(time.time()) + config["buy_timeout"]
        call_data      = router.encode_abi("swapExactETHForTokens", args=[amount_out_min, route, signer.address, deadline])
        tx_hash        = await send_tx_async({"to": AERODROME_ROUTER, "value": amount_wei, "data": call_data})
        logger.info("[TX] Koop verstuurd: %s", tx_hash[:16])
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
        NL = chr(10)
        await notify(
            "*SNIPE RAAK!*" + NL + NL +
            "Token: " + token + NL +
            "Betaald: " + str(amount_eth) + " ETH" + NL +
            "Ontvangen: " + str(round(token_balance / 10**18, 4)) + " tokens" + NL +
            "Tx: https://basescan.org/tx/" + tx_hash
        )
        return True
    except Exception as e:
        logger.error("[ERR] Koop mislukt %s: %s", token[:10], e)
        blacklist.add(token)
        return False

async def sell_token(token, reden):
    if token not in positions:
        return
    pos          = positions[token]
    token_amount = pos["token_amount"]
    router       = aw3.eth.contract(address=AERODROME_ROUTER, abi=ROUTER_ABI)
    route        = [{"from": token, "to": WETH, "stable": False, "factory": AERODROME_FACTORY}]
    try:
        token_c      = aw3.eth.contract(address=token, abi=ERC20_ABI)
        approve_data = token_c.encode_abi("approve", args=[AERODROME_ROUTER, token_amount])
        approve_hash = await send_tx_async({"to": token, "value": 0, "data": approve_data})
        await rpc_retry(aw3.eth.wait_for_transaction_receipt, approve_hash, timeout=20)
        amounts_out  = await rpc_retry(router.functions.getAmountsOut(token_amount, route).call)
        expected_eth = amounts_out[-1]
        min_eth_out  = expected_eth * (10000 - config["slippage_bps"]) // 10000
        sell_data    = router.encode_abi("swapExactTokensForETH", args=[token_amount, min_eth_out, route, signer.address, int(time.time()) + 20])
        tx_hash      = await send_tx_async({"to": AERODROME_ROUTER, "value": 0, "data": sell_data})
        receipt      = await rpc_retry(aw3.eth.wait_for_transaction_receipt, tx_hash, timeout=20)
        if receipt["status"] != 1:
            raise Exception("Verkoop gefaald op chain")
        received_eth = float(w3s.from_wei(expected_eth, "ether"))
        invested_eth = pos["entry_eth"]
        pnl_eth      = received_eth - invested_eth
        pnl_pct      = (pnl_eth / invested_eth) * 100
        prefix       = "[WIN]" if pnl_pct >= 0 else "[LOSS]"
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
        NL       = chr(10)
        pnl_str  = str(round(pnl_pct, 1))
        eth_str  = str(round(pnl_eth, 5))
        tot_str  = str(round(stats["total_pnl"], 5))
        snip_str = str(round(config["snipe_eth"], 5))
        await notify(
            prefix + " *POSITIE GESLOTEN*" + NL +
            "Reden: " + reden + NL + NL +
            "Token: " + token + NL +
            "PnL: " + pnl_str + "% (" + eth_str + " ETH)" + NL +
            "Sessie PnL: " + tot_str + " ETH" + NL +
            "Snipe bedrag nu: " + snip_str + " ETH" + NL +
            "Tx: https://basescan.org/tx/" + tx_hash
        )
    except Exception as e:
        logger.error("[ERR] Verkoop mislukt %s: %s", token, e)
        await notify("[WARN] *Verkoop mislukt* " + token[:12] + chr(10) + str(e))

async def process_new_token(token, pool, created_block):
    if token in blacklist or token in positions or token in seen_pools:
        return
    seen_pools.add(token)
    safe = await is_safe_token(token, pool, created_block)
    if safe:
        await buy_token(token, pool, created_block)
    else:
        blacklist.add(token)

async def websocket_mempool_scanner():
    logger.info("[WS] Mempool scanner verbinden...")
    while True:
        try:
            async with AsyncWeb3(WebsocketProviderV2(BASE_WS_URL)) as ws3:
                logger.info("[WS] Verbonden - mempool stream actief")
                await notify("[WS] *WebSocket mempool actief*")
                await ws3.eth.subscribe("newPendingTransactions")
                async for response in ws3.socket.process_subscriptions():
                    if not config["active"] or not config["mempool_mode"]:
                        continue
                    tx_hash = response.get("result")
                    if not tx_hash or tx_hash in seen_txs:
                        continue
                    seen_txs.add(tx_hash)
                    if len(seen_txs) > 10000:
                        seen_txs.clear()
                    asyncio.create_task(handle_pending_tx(ws3, tx_hash))
        except Exception as e:
            logger.error("[ERR] WebSocket verbroken: %s", e)
            await asyncio.sleep(3)

async def handle_pending_tx(ws3, tx_hash):
    try:
        tx = await rpc_retry(ws3.eth.get_transaction, tx_hash)
        if not tx:
            return
        to_addr    = tx.get("to", "") or ""
        input_data = tx.get("input", "0x") or "0x"
        if to_addr.lower() != AERODROME_ROUTER.lower():
            return
        if len(input_data) < 10:
            return
        selector = input_data[:10].lower()
        if selector not in ADD_LIQ_SELECTORS:
            return
        logger.info("[MEMPOOL] addLiquidity gevonden: %s", tx_hash[:16])
        try:
            raw     = bytes.fromhex(input_data[10:])
            decoded = abi_decode(
                ["address","address","bool","uint256","uint256","uint256","uint256","address","uint256"], raw
            )
            token_a = AsyncWeb3.to_checksum_address(decoded[0])
            token_b = AsyncWeb3.to_checksum_address(decoded[1])
        except Exception:
            return
        if token_b.lower() == WETH.lower():
            new_token = token_a
        elif token_a.lower() == WETH.lower():
            new_token = token_b
        else:
            return
        if new_token in blacklist or new_token in positions or new_token in seen_pools:
            return
        current_block = await aw3.eth.block_number
        pool_addr = None
        for _ in range(6):
            await asyncio.sleep(0.5)
            try:
                factory = w3s.eth.contract(address=AERODROME_FACTORY, abi=FACTORY_ABI)
                events  = factory.events.PoolCreated.get_logs(fromBlock=current_block - 1, toBlock="latest")
                for ev in events:
                    t0, t1 = ev["args"]["token0"], ev["args"]["token1"]
                    if new_token.lower() in [t0.lower(), t1.lower()]:
                        pool_addr = ev["args"]["pool"]
                        break
                if pool_addr:
                    break
            except Exception:
                pass
        if not pool_addr:
            return
        await notify("[MEMPOOL] *Hit!*" + chr(10) + "Token: " + new_token[:12] + "..." + chr(10) + "Checks uitvoeren...")
        await process_new_token(new_token, pool_addr, current_block)
    except Exception as e:
        logger.debug("[DEBUG] Mempool tx fout: %s", e)

async def scan_new_pools():
    logger.info("[SCAN] Block scanner gestart")
    last_block = await aw3.eth.block_number
    while True:
        await asyncio.sleep(1)
        if not config["active"]:
            continue
        try:
            current_block = await aw3.eth.block_number
            if current_block <= last_block:
                continue
            factory = w3s.eth.contract(address=AERODROME_FACTORY, abi=FACTORY_ABI)
            events  = factory.events.PoolCreated.get_logs(fromBlock=last_block + 1, toBlock=current_block)
            if events:
                tasks = []
                for ev in events:
                    t0, t1 = ev["args"]["token0"], ev["args"]["token1"]
                    pool   = ev["args"]["pool"]
                    block  = ev.get("blockNumber", current_block)
                    if t1.lower() == WETH.lower():
                        token = t0
                    elif t0.lower() == WETH.lower():
                        token = t1
                    else:
                        continue
                    tasks.append(process_new_token(token, pool, block))
                await asyncio.gather(*tasks)
            last_block = current_block
        except Exception as e:
            logger.error("[ERR] Block scanner fout: %s", e)
            await asyncio.sleep(2)

async def monitor_single(token, pos):
    try:
        router      = aw3.eth.contract(address=AERODROME_ROUTER, abi=ROUTER_ABI)
        route       = [{"from": token, "to": WETH, "stable": False, "factory": AERODROME_FACTORY}]
        amounts_out = await rpc_retry(router.functions.getAmountsOut(pos["token_amount"], route).call)
        current_eth = float(w3s.from_wei(amounts_out[-1], "ether"))
        invested    = pos["entry_eth"]
        pnl_pct     = ((current_eth - invested) / invested) * 100
        if current_eth > pos["peak_eth"]:
            positions[token]["peak_eth"] = current_eth
        peak           = positions[token]["peak_eth"]
        drop_from_peak = ((peak - current_eth) / peak) * 100 if peak > 0 else 0
        profit_at_peak = ((peak - invested) / invested) * 100
        logger.info("[POS] %s PnL: %+.1f%% peak: +%.1f%% drop: -%.1f%%", token[:10], pnl_pct, profit_at_peak, drop_from_peak)
        if pnl_pct >= config["take_profit_pct"]:
            await sell_token(token, "Take Profit +" + str(round(pnl_pct, 1)) + "%")
        elif profit_at_peak >= config["min_profit_to_trail"] and drop_from_peak >= config["trailing_stop_pct"]:
            await sell_token(token, "Trailing Stop (piek +" + str(round(profit_at_peak, 1)) + "% nu " + str(round(pnl_pct, 1)) + "%)")
        elif pnl_pct <= -config["hard_stop_pct"]:
            await sell_token(token, "Hard Stop " + str(round(pnl_pct, 1)) + "%")
    except Exception as e:
        logger.warning("[WARN] Monitor %s: %s", token[:10], e)

async def monitor_positions():
    while True:
        await asyncio.sleep(config["monitor_interval"])
        if positions:
            await asyncio.gather(*[monitor_single(t, p) for t, p in list(positions.items())])

async def cmd_start(update, context):
    if update.effective_user.id != OWNER_ID:
        return
    config["active"] = True
    NL = chr(10)
    await update.message.reply_text(
        "*Synthora Elite v3 ACTIEF*" + NL + NL +
        "WebSocket mempool: aan" + NL +
        "Block scanner: aan" + NL +
        "Honeypot check: aan" + NL +
        "Auto-reinvest: aan" + NL +
        "Chain: Base Mainnet",
        parse_mode="Markdown"
    )

async def cmd_stop(update, context):
    if update.effective_user.id != OWNER_ID:
        return
    config["active"] = False
    await update.message.reply_text(
        "*Sniper gestopt*" + chr(10) + "Open posities worden nog gemonitord.",
        parse_mode="Markdown"
    )

async def cmd_status(update, context):
    if update.effective_user.id != OWNER_ID:
        return
    balance  = w3s.from_wei(w3s.eth.get_balance(signer.address), "ether")
    status   = "ACTIEF" if config["active"] else "GESTOPT"
    maxpos   = config["max_positions"]
    snipe    = config["snipe_eth"]
    tp       = config["take_profit_pct"]
    trail    = config["trailing_stop_pct"]
    stop     = config["hard_stop_pct"]
    gas      = config["gas_multiplier"]
    slip     = config["slippage_bps"]
    NL       = chr(10)
    pos_lines = []
    for t, p in positions.items():
        try:
            router = w3s.eth.contract(address=AERODROME_ROUTER, abi=ROUTER_ABI)
            route  = [{"from": t, "to": WETH, "stable": False, "factory": AERODROME_FACTORY}]
            out    = router.functions.getAmountsOut(p["token_amount"], route).call()
            curr   = float(w3s.from_wei(out[-1], "ether"))
            pnl    = ((curr - p["entry_eth"]) / p["entry_eth"]) * 100
            sign   = "+" if pnl >= 0 else ""
            pos_lines.append(t[:12] + "... " + sign + str(round(pnl, 1)) + "%")
        except Exception:
            pos_lines.append(t[:12] + "... ?%")
    pos_txt = NL.join(pos_lines) if pos_lines else "Geen open posities"
    msg = (
        "*Status*" + NL + NL +
        status + " | Saldo: " + str(round(float(balance), 5)) + " ETH" + NL +
        "Posities: " + str(len(positions)) + "/" + str(int(maxpos)) + NL + NL +
        pos_txt + NL + NL +
        "Snipe: " + str(snipe) + " ETH | TP: +" + str(int(tp)) + "%" + NL +
        "Trail: -" + str(int(trail)) + "% | Stop: -" + str(int(stop)) + "%" + NL +
        "Gas: x" + str(gas) + " | Slippage: " + str(int(slip)) + "bps"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def cmd_stats(update, context):
    if update.effective_user.id != OWNER_ID:
        return
    uptime    = (time.time() - stats["started"]) / 3600
    winrate   = (stats["wins"] / stats["trades"] * 100) if stats["trades"] > 0 else 0
    balance   = w3s.from_wei(w3s.eth.get_balance(signer.address), "ether")
    trades    = stats["trades"]
    wins      = stats["wins"]
    losses    = stats["losses"]
    total_pnl = stats["total_pnl"]
    best      = stats["best_trade"]
    worst     = stats["worst_trade"]
    honeypots = stats["honeypots_blocked"]
    rugs      = stats["rugs_blocked"]
    snipe_now = config["snipe_eth"]
    NL = chr(10)
    msg = (
        "*Sessie Statistieken*" + NL + NL +
        "Uptime: " + str(round(uptime, 1)) + "u" + NL +
        "Trades: " + str(trades) + " | Winrate: " + str(round(winrate, 1)) + "%" + NL +
        "Wins: " + str(wins) + " | Losses: " + str(losses) + NL +
        "PnL: " + str(round(total_pnl, 5)) + " ETH" + NL +
        "Best: +" + str(round(best, 1)) + "% | Worst: " + str(round(worst, 1)) + "%" + NL +
        "Honeypots geblokt: " + str(honeypots) + " | Rugs: " + str(rugs) + NL + NL +
        "Snipe bedrag nu: " + str(round(snipe_now, 5)) + " ETH" + NL +
        "Wallet saldo: " + str(round(float(balance), 5)) + " ETH"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def cmd_set(update, context):
    if update.effective_user.id != OWNER_ID:
        return
    if len(context.args) < 2:
        NL = chr(10)
        await update.message.reply_text(
            "*Instellingen:*" + NL +
            "eth | tp | trail | hardstop | mintrail" + NL +
            "minliq | slippage | maxpos | gas | maxgas" + NL +
            "reinvestpct | maxage | monitor" + NL +
            "reinvest | mempool | honeypot (1/0)",
            parse_mode="Markdown"
        )
        return
    num_map = {
        "eth": "snipe_eth", "tp": "take_profit_pct", "trail": "trailing_stop_pct",
        "hardstop": "hard_stop_pct", "mintrail": "min_profit_to_trail",
        "minliq": "min_liquidity_eth", "slippage": "slippage_bps", "maxpos": "max_positions",
        "gas": "gas_multiplier", "maxgas": "max_gas_gwei", "reinvestpct": "reinvest_pct",
        "maxage": "max_token_age_blocks", "monitor": "monitor_interval",
    }
    bool_map = {"reinvest": "reinvest", "mempool": "mempool_mode", "honeypot": "honeypot_check"}
    key = context.args[0].lower()
    val = context.args[1]
    if key in num_map:
        config[num_map[key]] = float(val)
        await update.message.reply_text("[OK] " + key + " -> " + val)
    elif key in bool_map:
        config[bool_map[key]] = bool(int(val))
        state = "aan" if config[bool_map[key]] else "uit"
        await update.message.reply_text("[OK] " + key + " -> " + state)
    else:
        await update.message.reply_text("[ERR] Onbekende instelling.")

async def cmd_buy(update, context):
    if update.effective_user.id != OWNER_ID:
        return
    if not context.args:
        await update.message.reply_text("Gebruik: /buy <token_adres>")
        return
    token = w3s.to_checksum_address(context.args[0])
    msg   = await update.message.reply_text("Handmatig kopen...")
    try:
        factory = w3s.eth.contract(address=AERODROME_FACTORY, abi=FACTORY_ABI)
        events  = factory.events.PoolCreated.get_logs(fromBlock=w3s.eth.block_number - 100000, toBlock="latest")
        pool    = None
        for ev in events:
            t0, t1 = ev["args"]["token0"], ev["args"]["token1"]
            if token.lower() in [t0.lower(), t1.lower()]:
                pool = ev["args"]["pool"]
                break
        if not pool:
            await msg.edit_text("[ERR] Pool niet gevonden.")
            return
        ok = await buy_token(token, pool)
        if not ok:
            await msg.edit_text("[ERR] Koop mislukt.")
    except Exception as e:
        await msg.edit_text("[ERR] " + str(e))

async def cmd_sell(update, context):
    if update.effective_user.id != OWNER_ID:
        return
    if not context.args:
        await update.message.reply_text("Gebruik: /sell <token_adres>")
        return
    token = w3s.to_checksum_address(context.args[0])
    if token not in positions:
        await update.message.reply_text("[ERR] Geen open positie.")
        return
    await sell_token(token, "Handmatig")

async def cmd_closeall(update, context):
    if update.effective_user.id != OWNER_ID:
        return
    if not positions:
        await update.message.reply_text("Geen open posities.")
        return
    await update.message.reply_text("Sluiten: " + str(len(positions)) + " posities...")
    await asyncio.gather(*[sell_token(t, "Alles sluiten") for t in list(positions.keys())])

async def cmd_skyline(update, context):
    if update.effective_user.id != OWNER_ID:
        return
    balance = w3s.from_wei(w3s.eth.get_balance(signer.address), "ether")
    block   = w3s.eth.block_number
    NL      = chr(10)
    await update.message.reply_text(
        "*Skyline*" + NL + NL +
        "Wallet: " + signer.address + NL +
        "Saldo: " + str(round(float(balance), 6)) + " ETH" + NL +
        "Block: " + str(block) + NL +
        "Chain: Base Mainnet " + str(BASE_CHAIN_ID),
        parse_mode="Markdown"
    )

async def run_bot():
    global tg_bot
    await asyncio.sleep(2)
    tg_bot = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    for cmd, fn in [
        ("start",    cmd_start),
        ("stop",     cmd_stop),
        ("status",   cmd_status),
        ("stats",    cmd_stats),
        ("set",      cmd_set),
        ("buy",      cmd_buy),
        ("sell",     cmd_sell),
        ("closeall", cmd_closeall),
        ("skyline",  cmd_skyline),
    ]:
        tg_bot.add_handler(CommandHandler(cmd, fn))
    await tg_bot.initialize()
    await tg_bot.start()
    await tg_bot.updater.start_polling()
    logger.info("[START] Synthora Elite v3 Online")

@app.on_event("startup")
async def startup():
    asyncio.create_task(run_bot())
    asyncio.create_task(websocket_mempool_scanner())
    asyncio.create_task(scan_new_pools())
    asyncio.create_task(monitor_positions())

@app.get("/")
async def health():
    return {
        "status":    "Active",
        "chain":     "Base Mainnet " + str(BASE_CHAIN_ID),
        "sniper":    config["active"],
        "block":     w3s.eth.block_number,
        "positions": len(positions),
        "pnl_eth":   round(stats["total_pnl"], 6),
        "wallet":    signer.address,
    }

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
