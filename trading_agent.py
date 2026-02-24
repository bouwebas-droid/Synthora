# =============================================================
#  SYNTHORA ELITE SNIPER
#  Base Mainnet | Aerodrome | Direct Wallet
#
#  Wat dit onderscheidt van andere bots:
#  1. MEMPOOL sniping \u2014 ziet addLiquidity VOOR bevestiging
#  2. Honeypot simulatie \u2014 simuleert koop+verkoop voor executie
#  3. Bytecode analyse \u2014 detecteert blacklist/pause functies
#  4. Dynamische gas \u2014 overbiedt concurrenten automatisch
#  5. Parallelle monitoring \u2014 alle posities simultaan
#  6. Auto-reinvest \u2014 compound winst automatisch
#  7. Multi-layer veiligheid \u2014 6 checks voor elke snipe
# =============================================================
import logging, os, asyncio, time, json
from web3 import Web3
from web3.middleware import geth_poa_middleware
from eth_account import Account
from eth_abi import decode as abi_decode
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from fastapi import FastAPI
import uvicorn

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger("Synthora-Elite")
app    = FastAPI()

# =============================================================
#  VERBINDING \u2014 twee RPC's: \u00e9\u00e9n voor speed, \u00e9\u00e9n als backup
# =============================================================
BASE_RPC_URL      = os.environ.get("BASE_RPC_URL", "https://mainnet.base.org")
BASE_RPC_BACKUP   = os.environ.get("BASE_RPC_BACKUP", "https://base.llamarpc.com")
BASE_CHAIN_ID     = 8453

w3  = Web3(Web3.HTTPProvider(BASE_RPC_URL, request_kwargs={"timeout": 10}))
w3b = Web3(Web3.HTTPProvider(BASE_RPC_BACKUP, request_kwargs={"timeout": 10}))
# Base gebruikt Optimism PoA \u2014 vereist deze middleware voor juiste block parsing
w3.middleware_onion.inject(geth_poa_middleware, layer=0)
w3b.middleware_onion.inject(geth_poa_middleware, layer=0)

def rpc(prefer_backup=False) -> Web3:
    """Geeft werkende RPC terug, valt terug op backup."""
    primary = w3b if prefer_backup else w3
    backup  = w3  if prefer_backup else w3b
    try:
        primary.eth.block_number
        return primary
    except:
        return backup

# Chain check
_chain = w3.eth.chain_id
if _chain != BASE_CHAIN_ID:
    raise SystemExit(
        f"\u26d4 VERKEERDE CHAIN! Verwacht Base ({BASE_CHAIN_ID}), kreeg {_chain}"
    )
logger.info(f"\u2705 Base Mainnet bevestigd (chain_id={BASE_CHAIN_ID})")

# =============================================================
#  ADRESSEN
# =============================================================
AERODROME_ROUTER   = "0xcF77a3Ba9A5CA399B7c97c74d54e5b1Beb874E43"
AERODROME_FACTORY  = "0x420DD381b31aEf6683db6B902084cB0FFECe40Da"
WETH               = "0x4200000000000000000000000000000000000006"

# Aerodrome addLiquidity function selectors \u2014 voor mempool detectie
ADD_LIQUIDITY_SELECTORS = {
    "0xe8e33700",  # addLiquidity(address,address,bool,uint,uint,uint,uint,address,uint)
    "0xf91b3f5e",  # addLiquidityETH(...)
}

# Bekende scam/rug factory adressen \u2014 nooit snipen
FACTORY_BLACKLIST = set()

# =============================================================
#  CONFIGURATIE
# =============================================================
config = {
    "active":              False,
    "snipe_eth":           0.01,    # ETH per snipe
    "take_profit_pct":     75,      # verkoop bij +75%
    "trailing_stop_pct":   12,      # trailing stop 12% van piek
    "hard_stop_pct":       30,      # absolute bodem -30%
    "min_profit_to_trail": 15,      # trailing activeert bij +15% winst
    "slippage_bps":        500,     # 5% slippage (mempool = hoog risico)
    "min_liquidity_eth":   0.5,     # min 0.5 ETH liquiditeit
    "max_positions":       8,
    "reinvest":            True,
    "reinvest_pct":        40,      # 40% winst herinvesteren
    "gas_multiplier":      1.5,     # x1.5 boven base fee voor concurrentie
    "max_gas_gwei":        5.0,     # nooit meer dan 5 gwei betalen
    "honeypot_check":      True,    # simuleer koop+verkoop voor executie
    "mempool_mode":        True,    # scan mempool voor pending addLiquidity
    "max_token_age_blocks": 3,      # koop alleen tokens jonger dan 3 blocks
    "min_holders_skip":    False,   # skip holder check (te traag voor snipen)
}

# Posities: { token: { entry_eth, token_amount, buy_tx, timestamp, peak_eth, pool } }
positions: dict = {}
blacklist:  set  = set()
seen_pools: set  = set()  # voorkomt dubbel verwerken

# Sessie statistieken
stats = {
    "trades": 0, "wins": 0, "losses": 0,
    "total_pnl": 0.0, "best_trade": 0.0, "worst_trade": 0.0,
    "honeypots_blocked": 0, "rugs_blocked": 0,
    "started": time.time(),
}

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
    {"inputs":[],"name":"decimals","outputs":[{"name":"","type":"uint8"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"totalSupply","outputs":[{"name":"","type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"owner","outputs":[{"name":"","type":"address"}],"stateMutability":"view","type":"function"},
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
#  WALLET
# =============================================================
raw_key = os.environ.get("ARCHITECT_SESSION_KEY", "")
try:
    signer = Account.from_key(raw_key.strip().replace('"','').replace("'",""))
    logger.info(f"\u2705 Wallet: {signer.address}")
except Exception as e:
    raise SystemExit(f"\u274c KEY ERROR: {e}")

OWNER_ID       = int(os.environ.get("OWNER_ID", 0))
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
tg_bot         = None

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
#  TRANSACTIE ENGINE \u2014 dynamische gas, chain guard
# =============================================================
def get_gas_params() -> dict:
    """Berekent optimale gas prijs om concurrenten te verslaan."""
    node = rpc()
    base_fee = node.eth.get_block("latest")["baseFeePerGas"]
    # Multiplier boven base fee \u2014 hoe hoger hoe sneller, maar nooit meer dan max
    raw_priority = int(base_fee * config["gas_multiplier"])
    max_priority = node.to_wei(config["max_gas_gwei"], "gwei")
    priority     = min(raw_priority, max_priority)
    return {
        "maxPriorityFeePerGas": priority,
        "maxFeePerGas":         base_fee * 2 + priority,
    }

def send_tx(tx: dict) -> str:
    node = rpc()
    if node.eth.chain_id != BASE_CHAIN_ID:
        raise Exception(f"\u26d4 Chain mismatch! Verwacht {BASE_CHAIN_ID}")
    tx["nonce"]   = node.eth.get_transaction_count(signer.address, "pending")
    tx["chainId"] = BASE_CHAIN_ID
    tx["from"]    = signer.address
    tx.update(get_gas_params())
    if "gas" not in tx:
        try:
            tx["gas"] = int(node.eth.estimate_gas(tx) * 1.3)
        except:
            tx["gas"] = 500_000
    signed  = signer.sign_transaction(tx)
    raw
