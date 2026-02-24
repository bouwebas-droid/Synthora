# --- 1. IMPORTS ---
import logging, os, asyncio, time, httpx
from web3 import Web3
from eth_account import Account
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from fastapi import FastAPI
import uvicorn

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger("Synthora")
app = FastAPI()

# --- 2. CONFIGURATIE ---
BASE_RPC_URL = "https://mainnet.base.org"
w3 = Web3(Web3.HTTPProvider(BASE_RPC_URL))

AERODROME_ROUTER  = "0xcF77a3Ba9A5CA399B7c97c74d54e5b1Beb874E43"
AERODROME_FACTORY = "0x420DD381b31aEf6683db6B902084cB0FFECe40Da"
WETH              = "0x4200000000000000000000000000000000000006"
SLIPPAGE_BPS      = 100  # 1% slippage

ROUTER_ABI = [
    {
        "inputs":[
            {"name":"amountOutMin","type":"uint256"},
            {"name":"routes","type":"tuple[]","components":[
                {"name":"from","type":"address"},{"name":"to","type":"address"},
                {"name":"stable","type":"bool"},{"name":"factory","type":"address"}]},
            {"name":"to","type":"address"},
            {"name":"deadline","type":"uint256"}
        ],
        "name":"swapExactETHForTokens",
        "outputs":[{"name":"amounts","type":"uint256[]"}],
        "stateMutability":"payable","type":"function"
    },
    {
        "inputs":[
            {"name":"amountIn","type":"uint256"},
            {"name":"routes","type":"tuple[]","components":[
                {"name":"from","type":"address"},{"name":"to","type":"address"},
                {"name":"stable","type":"bool"},{"name":"factory","type":"address"}]}
        ],
        "name":"getAmountsOut",
        "outputs":[{"name":"amounts","type":"uint256[]"}],
        "stateMutability":"view","type":"function"
    }
]

# --- 3. WALLET LADEN ---
raw_key = os.environ.get("ARCHITECT_SESSION_KEY", "")
try:
    clean_key = raw_key.strip().replace('"', '').replace("'", "")
    signer = Account.from_key(clean_key)
    logger.info(f"✅ Wallet geladen: {signer.address}")
except Exception as e:
    logger.error(f"❌ KEY ERROR: {e}")
    signer = None

OWNER_ID       = int(os.environ.get("OWNER_ID", 0))
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

# --- 4. TRANSACTIE ENGINE ---

def send_transaction(tx: dict) -> str:
    """Ondertekent en verstuurt een transactie vanuit de eigen wallet."""
    tx["nonce"]    = w3.eth.get_transaction_count(signer.address)
    tx["chainId"]  = 8453  # Base mainnet
    tx["from"]     = signer.address

    # Gas automatisch schatten als niet opgegeven
    if "gas" not in tx:
        tx["gas"] = w3.eth.estimate_gas(tx)

    # EIP-1559 gas prijzen ophalen
    base_fee   = w3.eth.get_block("latest")["baseFeePerGas"]
    priority   = w3.to_wei(0.001, "gwei")  # kleine tip
    tx["maxPriorityFeePerGas"] = priority
    tx["maxFeePerGas"]         = base_fee * 2 + priority

    signed = signer.sign_transaction(tx)
    # web3.py v6+: raw_transaction (v5 gebruikte rawTransaction)
    raw = getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction", None)
    tx_hash = w3.eth.send_raw_transaction(raw)
    return tx_hash.hex()

# --- 5. TELEGRAM COMMANDS ---

async def skyline_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toont wallet adres en ETH saldo."""
    if update.effective_user.id != OWNER_ID:
        return
    try:
        balance = w3.from_wei(w3.eth.get_balance(signer.address), "ether")
        await update.message.reply_text(
            f"🏙️ *Skyline Audit*\n\n"
            f"Wallet: `{signer.address}`\n"
            f"Saldo: `{balance:.6f} ETH`",
            parse_mode="Markdown"
        )
    except Exception as e:
        await update.message.reply_text(f"⚠️ Fout: {e}")

async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Stuurt een test transactie van 0 ETH naar jezelf om gas te testen."""
    if update.effective_user.id != OWNER_ID:
        return
    msg = await update.message.reply_text("🔧 *Test transactie versturen...*", parse_mode="Markdown")
    try:
        tx_hash = send_transaction({
            "to":    signer.address,
            "value": 0,
            "data":  b""
        })
        await msg.edit_text(
            f"✅ *Test geslaagd!*\n\n"
            f"Tx Hash: `{tx_hash}`\n"
            f"Bekijk op: https://basescan.org/tx/{tx_hash}",
            parse_mode="Markdown"
        )
    except Exception as e:
        await msg.edit_text(f"⚠️ *Fout:*\n`{str(e)}`", parse_mode="Markdown")

async def trade_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Swap ETH naar een token via Aerodrome.
    Gebruik: /trade <token_adres> <eth_bedrag>
    Voorbeeld: /trade 0xabc...def 0.001
    """
    if update.effective_user.id != OWNER_ID:
        return
    if len(context.args) < 2:
        await update.message.reply_text(
            "Gebruik: `/trade <token_adres> <eth_bedrag>`\n"
            "Voorbeeld: `/trade 0xabc...def 0.001`",
            parse_mode="Markdown"
        )
        return

    msg = await update.message.reply_text("🏗️ *Synthetiseren...*", parse_mode="Markdown")
    try:
        token      = w3.to_checksum_address(context.args[0])
        amount_eth = float(context.args[1].replace(",", "."))
        amount_wei = w3.to_wei(amount_eth, "ether")

        router = w3.eth.contract(address=AERODROME_ROUTER, abi=ROUTER_ABI)
        route  = [{"from": WETH, "to": token, "stable": False, "factory": AERODROME_FACTORY}]

        # Verwachte output ophalen voor slippage berekening
        amounts_out    = router.functions.getAmountsOut(amount_wei, route).call()
        expected_out   = amounts_out[-1]
        amount_out_min = expected_out * (10_000 - SLIPPAGE_BPS) // 10_000

        # Transactie data encoderen
        call_data = router.encode_abi(
            "swapExactETHForTokens",
            args=[amount_out_min, route, signer.address, int(time.time()) + 600]
        )

        tx_hash = send_transaction({
            "to":    AERODROME_ROUTER,
            "value": amount_wei,
            "data":  call_data
        })

        await msg.edit_text(
            f"🚀 *Swap verstuurd!*\n\n"
            f"Tx Hash: `{tx_hash}`\n"
            f"Bekijk op: https://basescan.org/tx/{tx_hash}",
            parse_mode="Markdown"
        )
    except Exception as e:
        await msg.edit_text(f"⚠️ *Architect Error:*\n`{str(e)}`", parse_mode="Markdown")

# --- 6. RUNNER ---

async def run_bot():
    await asyncio.sleep(5)
    app_tg = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app_tg.add_handler(CommandHandler("skyline", skyline_report))
    app_tg.add_handler(CommandHandler("test",    test_command))
    app_tg.add_handler(CommandHandler("trade",   trade_command))
    await app_tg.initialize()
    await app_tg.start()
    await app_tg.updater.start_polling()
    logger.info("🚀 Synthora Direct Engine Online.")
    while True:
        await asyncio.sleep(3600)

@app.on_event("startup")
async def startup():
    asyncio.create_task(run_bot())

@app.get("/")
async def health():
    return {
        "status": "Active",
        "wallet": signer.address if signer else "niet geladen"
    }

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
