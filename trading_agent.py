# --- 1. IMPORTS & FUNDERING ---
import logging, os, asyncio, time, httpx
from web3 import Web3
from eth_account import Account
from eth_account.messages import encode_defunct
from eth_utils import to_hex, to_bytes
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

# FIX: Geen hardcoded API key fallback — script faalt luid als env var ontbreekt
PIMLICO_API_KEY = os.environ["PIMLICO_API_KEY"]
BUNDLER_URL = f"https://api.pimlico.io/v2/8453/rpc?apikey={PIMLICO_API_KEY}"

ENTRY_POINT_ADDRESS  = "0x5FF137D4b0FDCD49DcA30c7CF57E578a026d2789"
SIMPLE_ACCOUNT_FACTORY = "0x9406Cc6185a346906296840746125a0E44976454"
AERODROME_ROUTER     = "0xcF77a3Ba9A5CA399B7c97c74d54e5b1Beb874E43"
# FIX: Correcte Aerodrome v2 pool factory op Base (was 0x420...0001, een systeemprecompile)
AERODROME_FACTORY    = "0x420DD381b31aEf6683db6B902084cB0FFECe40Da"
WETH                 = "0x4200000000000000000000000000000000000006"
SLIPPAGE_BPS         = 100  # 1% slippage tolerantie (100 basispunten)

EP_ABI = [
    {"inputs":[{"name":"sender","type":"address"},{"name":"key","type":"uint192"}],
     "name":"getNonce","outputs":[{"name":"nonce","type":"uint256"}],
     "stateMutability":"view","type":"function"},
    {"inputs":[{"name":"userOp","type":"tuple","components":[
        {"name":"sender","type":"address"},{"name":"nonce","type":"uint256"},
        {"name":"initCode","type":"bytes"},{"name":"callData","type":"bytes"},
        {"name":"callGasLimit","type":"uint256"},{"name":"verificationGasLimit","type":"uint256"},
        {"name":"preVerificationGas","type":"uint256"},{"name":"maxFeePerGas","type":"uint256"},
        {"name":"maxPriorityFeePerGas","type":"uint256"},{"name":"paymasterAndData","type":"bytes"},
        {"name":"signature","type":"bytes"}]}],
     "name":"getUserOpHash","outputs":[{"name":"","type":"bytes32"}],
     "stateMutability":"view","type":"function"}
]

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

# Beveiligde Key Inlezing
raw_key = os.environ.get("ARCHITECT_SESSION_KEY", "")
try:
    clean_key = raw_key.strip().replace('"', '').replace("'", "")
    architect_signer = Account.from_key(clean_key)
    logger.info(f"✅ Signer geladen: {architect_signer.address}")
except Exception as e:
    logger.error(f"❌ KEY ERROR: De private key in je environment is ongeldig: {e}")
    architect_signer = None

OWNER_ID       = int(os.environ.get("OWNER_ID", 0))
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

# --- 3. CRYPTOGRAFIE ENGINE ---

async def get_smart_vault_address() -> str:
    factory_abi = [{"inputs":[{"name":"owner","type":"address"},{"name":"salt","type":"uint256"}],
                    "name":"getAddress","outputs":[{"name":"","type":"address"}],
                    "stateMutability":"view","type":"function"}]
    factory = w3.eth.contract(address=SIMPLE_ACCOUNT_FACTORY, abi=factory_abi)
    return factory.functions.getAddress(architect_signer.address, 0).call()

async def send_user_operation(call_data: str, to_address: str, value: int = 0) -> str:
    vault_address = await get_smart_vault_address()
    ep_contract   = w3.eth.contract(address=ENTRY_POINT_ADDRESS, abi=EP_ABI)

    # FIX: Robuustere check op ongedeployede vault (HexBytes('0x') en b'' zijn beide leeg)
    init_code = "0x"
    if len(w3.eth.get_code(vault_address)) == 0:
        factory_contract = w3.eth.contract(
            address=SIMPLE_ACCOUNT_FACTORY,
            abi=[{"inputs":[{"name":"owner","type":"address"},{"name":"salt","type":"uint256"}],
                  "name":"createAccount","outputs":[{"name":"","type":"address"}],
                  "stateMutability":"nonpayable","type":"function"}]
        )
        init_code = SIMPLE_ACCOUNT_FACTORY + \
            factory_contract.encode_abi("createAccount", args=[architect_signer.address, 0])[2:]

    nonce = ep_contract.functions.getNonce(vault_address, 0).call()

    vault_abi = [{"inputs":[{"name":"dest","type":"address"},{"name":"value","type":"uint256"},
                             {"name":"func","type":"bytes"}],
                  "name":"execute","outputs":[],"stateMutability":"nonpayable","type":"function"}]
    vault_contract = w3.eth.contract(address=vault_address, abi=vault_abi)
    execute_data   = vault_contract.encode_abi("execute", args=[to_address, value, call_data])

    async with httpx.AsyncClient(timeout=60.0) as client:
        gas_res = await client.post(
            BUNDLER_URL,
            json={"jsonrpc":"2.0","id":1,"method":"pimlico_getUserOperationGasPrice","params":[]}
        )
        gp = gas_res.json()["result"]["standard"]

        user_op = {
            "sender": vault_address, "nonce": to_hex(nonce), "initCode": init_code,
            "callData": execute_data,
            "callGasLimit": to_hex(2_000_000), "verificationGasLimit": to_hex(1_000_000),
            "preVerificationGas": to_hex(100_000),
            "maxFeePerGas": gp["maxFeePerGas"], "maxPriorityFeePerGas": gp["maxPriorityFeePerGas"],
            "paymasterAndData": "0x", "signature": "0x"
        }

        def sign_op(op: dict) -> str:
            op_tuple = (
                op['sender'], int(op['nonce'], 16), to_bytes(hexstr=op['initCode']),
                to_bytes(hexstr=op['callData']), int(op['callGasLimit'], 16),
                int(op['verificationGasLimit'], 16), int(op['preVerificationGas'], 16),
                int(op['maxFeePerGas'], 16), int(op['maxPriorityFeePerGas'], 16),
                to_bytes(hexstr=op['paymasterAndData']), b''
            )
            h = ep_contract.functions.getUserOpHash(op_tuple).call()
            sig = architect_signer.sign_message(encode_defunct(primitive=h)).signature
            return f"0x{sig.hex()}"

        user_op["signature"] = sign_op(user_op)

        # Sponsor aanvragen
        sponsor_res  = await client.post(
            BUNDLER_URL,
            json={"jsonrpc":"2.0","id":1,"method":"pm_sponsorUserOperation",
                  "params":[user_op, ENTRY_POINT_ADDRESS]}
        )
        sponsor_data = sponsor_res.json()
        if "error" in sponsor_data:
            raise Exception(f"Sponsor Fout: {sponsor_data['error'].get('message')}")

        user_op.update(sponsor_data["result"])
        user_op["signature"] = sign_op(user_op)

        # Versturen
        final_res  = await client.post(
            BUNDLER_URL,
            json={"jsonrpc":"2.0","id":1,"method":"eth_sendUserOperation",
                  "params":[user_op, ENTRY_POINT_ADDRESS]}
        )
        # FIX: JSON slechts één keer parsen; fout als exception gooien ipv stilletjes retourneren
        final_data = final_res.json()
        if "error" in final_data:
            raise Exception(f"Bundler Fout: {final_data['error'].get('message')}")
        return final_data["result"]

# --- 4. COMMAND CENTER ---

async def skyline_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    try:
        v = await get_smart_vault_address()
        b = w3.from_wei(w3.eth.get_balance(v), 'ether')
        await update.message.reply_text(
            f"🏙️ **Skyline Audit**\n\nVault: `{v}`\nSaldo: `{b:.6f} ETH`",
            parse_mode='Markdown'
        )
    except Exception as e:
        await update.message.reply_text(f"⚠️ Fout bij skyline: {e}")

async def trade_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    if len(context.args) < 2:
        await update.message.reply_text("Gebruik: /trade <token_adres> <eth_bedrag>")
        return

    msg = await update.message.reply_text("🏗️ **Synthetiseren...**", parse_mode='Markdown')
    try:
        token      = w3.to_checksum_address(context.args[0])
        amount_eth = float(context.args[1].replace(',', '.'))
        amount_wei = w3.to_wei(amount_eth, 'ether')

        # FIX: Correcte factory; slippage bescherming via getAmountsOut
        route = [{"from": WETH, "to": token, "stable": False, "factory": AERODROME_FACTORY}]
        router = w3.eth.contract(address=AERODROME_ROUTER, abi=ROUTER_ABI)

        amounts_out  = router.functions.getAmountsOut(amount_wei, route).call()
        expected_out = amounts_out[-1]
        # 1% slippage: minimaal te ontvangen = expected * (10000 - 100) / 10000
        amount_out_min = expected_out * (10_000 - SLIPPAGE_BPS) // 10_000

        vault = await get_smart_vault_address()
        call_data = router.encode_abi(
            "swapExactETHForTokens",
            args=[amount_out_min, route, vault, int(time.time()) + 600]
        )

        op_hash = await send_user_operation(call_data, AERODROME_ROUTER, value=amount_wei)
        await msg.edit_text(
            f"🚀 **Verzonden!**\n\nHash: `{op_hash}`\n"
            f"Min. ontvangen: `{w3.from_wei(amount_out_min, 'ether'):.6f}` tokens",
            parse_mode='Markdown'
        )
    except Exception as e:
        await msg.edit_text(f"⚠️ **Architect Error:**\n`{str(e)}`", parse_mode='Markdown')

# --- 5. RUNNER ---

async def run_bot():
    await asyncio.sleep(5)
    app_tg = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app_tg.add_handler(CommandHandler("trade",   trade_command))
    app_tg.add_handler(CommandHandler("skyline", skyline_report))
    await app_tg.initialize()
    await app_tg.start()
    await app_tg.updater.start_polling()
    logger.info("🚀 Synthora Engine Online.")
    while True:
        await asyncio.sleep(3600)

@app.on_event("startup")
async def startup():
    asyncio.create_task(run_bot())

@app.get("/")
async def health():
    return {"status": "Active", "signer_loaded": architect_signer is not None}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
