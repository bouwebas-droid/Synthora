# =============================================================
#  SYNTHORA SNIPER — Base Mainnet | Aerodrome | Direct Wallet
# =============================================================
import logging, os, asyncio, time
from web3 import Web3
from eth_account import Account
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from fastapi import FastAPI
import uvicorn

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger("Synthora")
app    = FastAPI()

# =============================================================
#  CONFIGURATIE
# =============================================================
BASE_RPC_URL      = "https://mainnet.base.org"
w3                = Web3(Web3.HTTPProvider(BASE_RPC_URL))

AERODROME_ROUTER  = "0xcF77a3Ba9A5CA399B7c97c74d54e5b1Beb874E43"
AERODROME_FACTORY = "0x420DD381b31aEf6683db6B902084cB0FFECe40Da"
WETH              = "0x4200000000000000000000000000000000000006"

# Instellingen — aanpasbaar via /set commando
config = {
    "active":              False,  # sniper aan/uit
    "snipe_eth":           0.01,   # ETH per snipe
    "take_profit_pct":     50,     # verkoop bij +50%
    "trailing_stop_pct":   15,     # verkoop als prijs X% daalt vanaf de PIEK (volgt winst omhoog)
    "hard_stop_pct":       25,     # absolute bodem — verkoop altijd als verlies groter dan dit is
    "min_profit_to_trail": 10,     # trailing stop activeert pas als we >= 10% winst hebben
    "slippage_bps":        300,    # 3% slippage
    "min_liquidity_eth":   1.0,    # negeer pools met minder dan 1 ETH
    "max_positions":       5,      # max gelijktijdige posities
}
# Logica:
# - Onder min_profit_to_trail: alleen hard_stop actief (ruimte om te ademen)
# - Boven min_profit_to_trail: trailing stop volgt de piek mee omhoog
# - Voorbeeld: koop @ 1 ETH, stijgt naar 1.6 ETH (piek), daalt naar 1.36 ETH → verkoop (15% van piek)
# - Hard stop: als het echt crasht zonder ooit winst te maken → exit

# Actieve posities:
# { token: { entry_eth_per_token, token_amount, buy_tx, timestamp, peak_eth } }
# peak_eth = hoogste waarde ooit gezien — trailing stop volgt dit mee omhoog
positions: dict = {}
blacklist:  set = set()

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
    {"inputs":[],"name":"decimals","outputs":[{"name":"","type":"uint8"}],
     "stateMutability":"view","type":"function"},
    {"inputs":[],"name":"totalSupply","outputs":[{"name":"","type":"uint256"}],
     "stateMutability":"view","type":"function"},
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
    {"inputs":[],"name":"token0","outputs":[{"name":"","type":"address"}],
     "stateMutability":"view","type":"function"},
    {"inputs":[],"name":"token1","outputs":[{"name":"","type":"address"}],
     "stateMutability":"view","type":"function"},
]

# =============================================================
#  WALLET
# =============================================================
raw_key = os.environ.get("ARCHITECT_SESSION_KEY", "")
try:
    signer = Account.from_key(raw_key.strip().replace('"','').replace("'",""))
    logger.info(f"✅ Wallet geladen: {signer.address}")
except Exception as e:
    logger.error(f"❌ KEY ERROR: {e}")
    signer = None

OWNER_ID       = int(os.environ.get("OWNER_ID", 0))
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
tg_bot         = None

# =============================================================
#  TRANSACTIE ENGINE
# =============================================================
def send_tx(tx: dict) -> str:
    tx["nonce"]   = w3.eth.get_transaction_count(signer.address, "pending")
    tx["chainId"] = 8453
    tx["from"]    = signer.address
    if "gas" not in tx:
        tx["gas"] = int(w3.eth.estimate_gas(tx) * 1.2)
    base_fee = w3.eth.get_block("latest")["baseFeePerGas"]
    priority = w3.to_wei(0.01, "gwei")
    tx["maxPriorityFeePerGas"] = priority
    tx["maxFeePerGas"]         = base_fee * 2 + priority
    signed  = signer.sign_transaction(tx)
    raw     = getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction", None)
    return w3.eth.send_raw_transaction(raw).hex()

# =============================================================
#  TELEGRAM NOTIFICATIE
# =============================================================
async def notify(msg: str):
    if tg_bot and OWNER_ID:
        try:
            await tg_bot.bot.send_message(chat_id=OWNER_ID, text=msg, parse_mode="Markdown")
        except Exception as e:
            logger.warning(f"Telegram notificatie mislukt: {e}")

# =============================================================
#  VEILIGHEIDSCHECK
# =============================================================
def is_safe_token(token: str, pool: str) -> bool:
    try:
        pool_contract = w3.eth.contract(address=pool, abi=POOL_ABI)
        r0, r1, _    = pool_contract.functions.getReserves().call()
        t0           = pool_contract.functions.token0().call()
        weth_reserve = r0 if t0.lower() == WETH.lower() else r1
        eth_in_pool  = w3.from_wei(weth_reserve, "ether")

        if eth_in_pool < config["min_liquidity_eth"]:
            logger.info(f"❌ Te weinig liquiditeit: {eth_in_pool:.4f} ETH")
            return False

        if len(w3.eth.get_code(token)) == 0:
            logger.info("❌ Geen contract code")
            return False

        token_contract = w3.eth.contract(address=token, abi=ERC20_ABI)
        if token_contract.functions.totalSupply().call() == 0:
            logger.info("❌ TotalSupply is 0")
            return False

        logger.info(f"✅ Token veilig — {eth_in_pool:.4f} ETH in pool")
        return True
    except Exception as e:
        logger.warning(f"⚠️ Veiligheidscheck mislukt: {e}")
        return False

# =============================================================
#  KOPEN
# =============================================================
async def buy_token(token: str) -> bool:
    if token in positions or token in blacklist:
        return False
    if len(positions) >= config["max_positions"]:
        logger.info("⚠️ Max posities bereikt")
        return False

    amount_eth = config["snipe_eth"]
    amount_wei = w3.to_wei(amount_eth, "ether")
    router     = w3.eth.contract(address=AERODROME_ROUTER, abi=ROUTER_ABI)
    route      = [{"from": WETH, "to": token, "stable": False, "factory": AERODROME_FACTORY}]

    try:
        amounts_out    = router.functions.getAmountsOut(amount_wei, route).call()
        amount_out_min = amounts_out[-1] * (10_000 - config["slippage_bps"]) // 10_000

        call_data = router.encode_abi(
            "swapExactETHForTokens",
            args=[amount_out_min, route, signer.address, int(time.time()) + 60]
        )
        tx_hash = send_tx({"to": AERODROME_ROUTER, "value": amount_wei, "data": call_data})
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)

        if receipt["status"] != 1:
            raise Exception("Transactie gefaald op chain")

        token_contract = w3.eth.contract(address=token, abi=ERC20_ABI)
        token_balance  = token_contract.functions.balanceOf(signer.address).call()
        entry_price    = amount_eth / (token_balance / 10**18) if token_balance > 0 else 0

        positions[token] = {
            "entry_eth_per_token": entry_price,
            "token_amount":        token_balance,
            "buy_tx":              tx_hash,
            "timestamp":           time.time(),
            "peak_eth":            amount_eth,   # begint op inleg, stijgt mee met prijs
        }

        await notify(
            f"🎯 *Snipe uitgevoerd!*\n\n"
            f"Token: `{token}`\n"
            f"Betaald: `{amount_eth} ETH`\n"
            f"Ontvangen: `{token_balance / 10**18:.4f}` tokens\n"
            f"Tx: https://basescan.org/tx/{tx_hash}"
        )
        return True

    except Exception as e:
        logger.error(f"❌ Koop mislukt {token}: {e}")
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
    router       = w3.eth.contract(address=AERODROME_ROUTER, abi=ROUTER_ABI)
    route        = [{"from": token, "to": WETH, "stable": False, "factory": AERODROME_FACTORY}]

    try:
        # Approve
        token_contract = w3.eth.contract(address=token, abi=ERC20_ABI)
        approve_data   = token_contract.encode_abi("approve", args=[AERODROME_ROUTER, token_amount])
        approve_hash   = send_tx({"to": token, "value": 0, "data": approve_data})
        w3.eth.wait_for_transaction_receipt(approve_hash, timeout=60)

        # Verkoop
        amounts_out  = router.functions.getAmountsOut(token_amount, route).call()
        expected_eth = amounts_out[-1]
        min_eth_out  = expected_eth * (10_000 - config["slippage_bps"]) // 10_000

        sell_data = router.encode_abi(
            "swapExactTokensForETH",
            args=[token_amount, min_eth_out, route, signer.address, int(time.time()) + 60]
        )
        tx_hash = send_tx({"to": AERODROME_ROUTER, "value": 0, "data": sell_data})
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)

        if receipt["status"] != 1:
            raise Exception("Verkoop gefaald op chain")

        received_eth = w3.from_wei(expected_eth, "ether")
        invested_eth = config["snipe_eth"]
        pnl_pct      = ((received_eth - invested_eth) / invested_eth) * 100
        emoji        = "🟢" if pnl_pct >= 0 else "🔴"

        await notify(
            f"{emoji} *Positie gesloten — {reden}*\n\n"
            f"Token: `{token}`\n"
            f"Ingezet: `{invested_eth:.4f} ETH`\n"
            f"Ontvangen: `{received_eth:.4f} ETH`\n"
            f"PnL: `{pnl_pct:+.1f}%`\n"
            f"Tx: https://basescan.org/tx/{tx_hash}"
        )
        del positions[token]

    except Exception as e:
        logger.error(f"❌ Verkoop mislukt {token}: {e}")
        await notify(f"⚠️ *Verkoop mislukt* `{token}`\n`{e}`")

# =============================================================
#  POSITIE MONITOR — take profit / stop loss loop
# =============================================================
async def monitor_positions():
    while True:
        await asyncio.sleep(5)
        if not positions:
            continue
        router = w3.eth.contract(address=AERODROME_ROUTER, abi=ROUTER_ABI)
        for token, pos in list(positions.items()):
            try:
                route       = [{"from": token, "to": WETH, "stable": False, "factory": AERODROME_FACTORY}]
                amounts_out = router.functions.getAmountsOut(pos["token_amount"], route).call()
                current_eth = float(w3.from_wei(amounts_out[-1], "ether"))
                invested    = config["snipe_eth"]
                pnl_pct     = ((current_eth - invested) / invested) * 100

                # Piek bijwerken als prijs hoger is dan ooit
                if current_eth > pos["peak_eth"]:
                    positions[token]["peak_eth"] = current_eth
                    logger.info(f"📈 Nieuwe piek {token[:10]}...: {current_eth:.5f} ETH (+{pnl_pct:.1f}%)")

                peak_eth        = positions[token]["peak_eth"]
                drop_from_peak  = ((peak_eth - current_eth) / peak_eth) * 100
                profit_at_peak  = ((peak_eth - invested) / invested) * 100

                logger.info(f"📊 {token[:10]}... PnL: {pnl_pct:+.1f}% | Piek: +{profit_at_peak:.1f}% | Daling: -{drop_from_peak:.1f}%")

                # Take profit: harde bovengrens
                if pnl_pct >= config["take_profit_pct"]:
                    await sell_token(token, f"Take Profit +{pnl_pct:.1f}%")

                # Trailing stop: alleen actief als we al genoeg winst hebben gehad
                elif profit_at_peak >= config["min_profit_to_trail"] and drop_from_peak >= config["trailing_stop_pct"]:
                    await sell_token(token, f"Trailing Stop (piek +{profit_at_peak:.1f}%, nu {pnl_pct:+.1f}%)")

                # Hard stop: absoluut verlies te groot — altijd verkopen
                elif pnl_pct <= -config["hard_stop_pct"]:
                    await sell_token(token, f"Hard Stop {pnl_pct:.1f}%")

            except Exception as e:
                logger.warning(f"⚠️ Monitor fout {token}: {e}")

# =============================================================
#  POOL SCANNER — nieuwe Aerodrome pools block-by-block
# =============================================================
async def scan_new_pools():
    factory    = w3.eth.contract(address=AERODROME_FACTORY, abi=FACTORY_ABI)
    last_block = w3.eth.block_number
    logger.info(f"🔍 Scanner actief vanaf block {last_block}")

    while True:
        await asyncio.sleep(2)
        if not config["active"]:
            continue
        try:
            current_block = w3.eth.block_number
            if current_block <= last_block:
                continue

            events = factory.events.PoolCreated.get_logs(
                fromBlock=last_block + 1, toBlock=current_block
            )

            for event in events:
                token0 = event["args"]["token0"]
                token1 = event["args"]["token1"]
                pool   = event["args"]["pool"]

                if token1.lower() == WETH.lower():
                    new_token = token0
                elif token0.lower() == WETH.lower():
                    new_token = token1
                else:
                    continue  # geen WETH pair

                if new_token in blacklist or new_token in positions:
                    continue

                logger.info(f"🆕 Nieuwe pool: {new_token}")
                await notify(f"🆕 *Nieuwe pool*\nToken: `{new_token}`\nPool: `{pool}`")

                if is_safe_token(new_token, pool):
                    await buy_token(new_token)
                else:
                    blacklist.add(new_token)

            last_block = current_block

        except Exception as e:
            logger.error(f"❌ Scanner fout: {e}")
            await asyncio.sleep(5)

# =============================================================
#  TELEGRAM COMMANDO'S
# =============================================================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    config["active"] = True
    await update.message.reply_text("🟢 *Sniper ACTIEF*", parse_mode="Markdown")

async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    config["active"] = False
    await update.message.reply_text("🔴 *Sniper GESTOPT*", parse_mode="Markdown")

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    balance = w3.from_wei(w3.eth.get_balance(signer.address), "ether")
    status  = "🟢 ACTIEF" if config["active"] else "🔴 GESTOPT"
    pos_txt = "\n".join([f"• `{t[:12]}...`" for t in positions]) or "Geen"
    await update.message.reply_text(
        f"📊 *Synthora Status*\n\n"
        f"Status: {status}\n"
        f"Wallet: `{signer.address}`\n"
        f"Saldo: `{balance:.6f} ETH`\n"
        f"Posities ({len(positions)}/{config['max_positions']}):\n{pos_txt}\n\n"
        f"⚙️ *Instellingen*\n"
        f"Snipe bedrag: `{config['snipe_eth']} ETH`\n"
        f"Take Profit: `+{config['take_profit_pct']}%`\n"
        f"Trailing Stop: `-{config['trailing_stop_pct']}% vanaf piek`\n"
        f"Trailing activeert bij: `+{config['min_profit_to_trail']}% winst`\n"
        f"Hard Stop: `-{config['hard_stop_pct']}%`\n"
        f"Min. liquiditeit: `{config['min_liquidity_eth']} ETH`\n"
        f"Slippage: `{config['slippage_bps']} bps`",
        parse_mode="Markdown"
    )

async def cmd_set(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gebruik: /set <instelling> <waarde>
    eth | tp | sl | minliq | slippage | maxpos"""
    if update.effective_user.id != OWNER_ID: return
    if len(context.args) < 2:
        await update.message.reply_text(
            "Gebruik: `/set <instelling> <waarde>`\n\n"
            "`eth` — ETH per snipe\n"
            "`tp` — Take profit %\n"
            "`trail` — Trailing stop % vanaf piek\n"
            "`hardstop` — Hard stop % verlies (absolute bodem)\n"
            "`mintrail` — Min winst% voor trailing stop activeert\n"
            "`minliq` — Min liquiditeit ETH\n"
            "`slippage` — Slippage basispunten\n"
            "`maxpos` — Max posities",
            parse_mode="Markdown"
        )
        return
    mapping = {"eth":"snipe_eth","tp":"take_profit_pct","trail":"trailing_stop_pct",
               "hardstop":"hard_stop_pct","mintrail":"min_profit_to_trail",
               "minliq":"min_liquidity_eth","slippage":"slippage_bps","maxpos":"max_positions"}
    key = context.args[0].lower()
    if key not in mapping:
        await update.message.reply_text("❌ Onbekende instelling.")
        return
    val = float(context.args[1])
    config[mapping[key]] = val
    await update.message.reply_text(f"✅ `{key}` → `{val}`", parse_mode="Markdown")

async def cmd_buy(upda
