# --- 1. IMPORTS & FUNDERING ---
import logging, os, asyncio, time, httpx
from web3 import Web3
from eth_account import Account
from eth_account.messages import encode_defunct
from eth_utils import to_hex
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from fastapi import FastAPI
import uvicorn

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger("Synthora")
app = FastAPI()

# --- 2. CONFIGURATIE (Base Mainnet) ---
BASE_RPC_URL = "https://mainnet.base.org"
w3 = Web3(Web3.HTTPProvider(BASE_RPC_URL))

PIMLICO_API_KEY = os.environ.get("PIMLICO_API_KEY", "")
BUNDLER_URL = f"https://api.pimlico.io/v2/8453/rpc?apikey={PIMLICO_API_KEY}"

ENTRY_POINT_ADDRESS = "0x5FF137D4b0FDCD49DcA30c7CF57E578a026d2789"
SIMPLE_ACCOUNT_FACTORY = "0x9406Cc6185a346906296840746125a0E44976454"
AERODROME_ROUTER = "0xcF77a3Ba9A5CA399B7c97c74d54e5b1Beb874E43"
WETH = "0x4200000000000000000000000000000000000006"

ENTRY_POINT_ABI = [
    {"inputs":[{"name":"sender","type":"address"},{"name":"key","type":"uint192"}],"name":"getNonce","outputs":[{"name":"nonce","type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"name":"userOp","type":"tuple","components":[{"name":"sender","type":"address"},{"name":"nonce","type":"uint256"},{"name":"initCode","type":"bytes"},{"name":"callData","type":"bytes"},{"name":"callGasLimit","type":"uint256"},{"name":"verificationGasLimit","type":"uint256"},{"name":"preVerificationGas","type":"uint256"},{"name":"maxFeePerGas","type":"uint256"},{"name":"maxPriorityFeePerGas","type":"uint256"},{"name":"paymasterAndData","type":"bytes"},{"name":"signature","type":"bytes"}]}],"name":"getUserOpHash","outputs":[{"name":"","type":"bytes32"}],"stateMutability":"view","type":"function"}
]

OWNER_ID = int(os.environ.get("OWNER_ID", 0))
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
private_key = os.environ.get("ARCHITECT_SESSION_KEY")
architect_signer = Account.from_key(private_key) if private_key else None

# --- 3. CRYPTOGRAFIE & SMART ACCOUNT LOGICA ---

async def get_smart_vault_address():
    factory_abi = [{"inputs":[{"name":"owner","type":"address"},{"name":"salt","type":"uint256"}],"name":"getAddress","outputs":[{"name":"","type":"address"}],"stateMutability":"view","type":"function"}]
    factory = w3.eth.contract(address=SIMPLE_ACCOUNT_FACTORY, abi=factory_abi)
    return factory.functions.getAddress(architect_signer.address, 0).call()

async def send_user_operation(call_data, to_address, value=0):
    vault_address = await get_smart_vault_address()
    ep_contract = w3.eth.contract(address=ENTRY_POINT_ADDRESS, abi=ENTRY_POINT_ABI)
    
    init_code = "0x"
    if w3.eth.get_code(vault_address) == b'':
        factory_contract = w3.eth.contract(address=SIMPLE_ACCOUNT_FACTORY, abi=[{"inputs":[{"name":"owner","type":"address"},{"name":"salt","type":"uint256"}],"name":"createAccount","outputs":[{"name":"","type":"address"}],"stateMutability":"nonpayable","type":"function"}])
        init_code = SIMPLE_ACCOUNT_FACTORY + factory_contract.encode_abi("createAccount", args=[architect_signer.address, 0])[2:]

    nonce = ep_contract.functions.getNonce(vault_address, 0).call()
    
    acc_abi = [{"inputs":[{"name":"dest","type":"address"},{"name":"value","type":"uint256"},{"name":"func","type":"bytes"}],"name":"execute","outputs":[],"stateMutability":"nonpayable","type":"function"}]
    vault_contract = w3.eth.contract(address=vault_address, abi=acc_abi)
    execute_data = vault_contract.encode_abi("execute", args=[to_address, value, call_data])

    async with httpx.AsyncClient(timeout=30.0) as client:
        # 1. Dynamische Gas-prijzen ophalen
        gas_price_res = await client.post(BUNDLER_URL, json={
            "jsonrpc": "2.0", "id": 1, "method": "pimlico_getUserOperationGasPrice", "params": []
        })
        gp = gas_price_res.json()["result"]["standard"]

        # 2. UserOp voorbereiden (Met 0x gefixte dummy signature)
        user_op = {
            "sender": vault_address,
            "nonce": to_hex(nonce),
            "initCode": init_code,
            "callData": execute_data,
            "callGasLimit": to_hex(2000000), 
            "verificationGasLimit": to_hex(1000000),
            "preVerificationGas": to_hex(100000),
            "maxFeePerGas": gp["maxFeePerGas"],
            "maxPriorityFeePerGas": gp["maxPriorityFeePerGas"],
            "paymasterAndData": "0x",
            "signature": "0x" 
        }

        # --- DOUBLE-SIGN: Stap 1 (Simulatie) ---
        dummy_tuple = (
            user_op['sender'], int(user_op['nonce'], 16), user_op['initCode'],
            user_op['callData'], int(user_op['callGasLimit'], 16),
            int(user_op['verificationGasLimit'], 16), int(user_op['preVerificationGas'], 16),
            int(user_op['maxFeePerGas'], 16), int(user_op['maxPriorityFeePerGas'], 16),
            user_op['paymasterAndData'], b''
        )
        dummy_hash = ep_contract.functions.getUserOpHash(dummy_tuple).call()
        # FIX: Forceer 0x prefix
        user_op["signature"] = f"0x{architect_signer.sign_message(encode_defunct(primitive=dummy_hash)).signature.hex()}"

        # 3. Sponsoring aanvragen
        res = await client.post(BUNDLER_URL, json={
            "jsonrpc": "2.0", "id": 1, "method": "pm_sponsorUserOperation", 
            "params": [user_op, ENTRY_POINT_ADDRESS]
        })
        
        sponsor_data = res.json()
        if "error" in sponsor_data:
            raise Exception(f"Sponsor Fout: {sponsor_data['error'].get('message')}")
        
        user_op.update(sponsor_data["result"])

        # --- DOUBLE-SIGN: Stap 2 (Definitief) ---
        final_tuple = (
            user_op['sender'], int(user_op['nonce'], 16), user_op['initCode'],
            user_op['callData'], int(user_op['callGasLimit'], 16),
            int(user_op['verificationGasLimit'], 16), int(user_op['preVerificationGas'], 16),
            int(user_op['maxFeePerGas'], 16), int(user_op['maxPriorityFeePerGas'], 16),
            user_op['paymasterAndData'], b''
        )
        final_hash = ep_contract.functions.getUserOpHash(final_tuple).call()
        # FIX: Forceer 0x prefix
        user_op["signature"] = f"0x{architect_signer.sign_message(encode_defunct(primitive=final_hash)).signature.hex()}"

        # 4. Verzenden naar de Bundler
        final_res = await client.post(BUNDLER_URL, json={
            "jsonrpc": "2.0", "id": 1, "method": "eth_sendUserOperation", 
            "params": [user_op, ENTRY_POINT_ADDRESS]
        })
        
        return final_res.json().get("result") or str(final_res.json().get("error"))

# --- 4. COMMAND CENTER ---

async def skyline_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    try:
        v = await get_smart_vault_address()
        b = w3.from_wei(w3.eth.get_balance(v), 'ether')
        report = (
            "🏙️ **Synthora Skyline Audit**\n"
            "-------------------------------------\n"
            f"🔐 **Vault:** `{v}`\n"
            f"💰 **Saldo:** `{b:.6f} ETH`\n"
            "-------------------------------------\n"
            "✅ *Signer en Vault zijn gesynchroniseerd.*"
        )
        await update.message.reply_text(report, parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"⚠️ Fout: `{e}`")

async def trade_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    if len(context.args) < 2:
        await update.message.reply_text("❌ Gebruik: `/trade [token] [eth]`")
        return
    
    status = await update.message.reply_text("🏗️ **Architect bouwt UserOp...**")
    try:
        token = w3.to_checksum_address(context.args[0])
        amount = float(context.args[1].replace(',', '.'))
        
        router_abi = [{"inputs":[{"name":"amountOutMin","type":"uint256"},{"name":"routes","type":"tuple[]","components":[{"name":"from","type":"address"},{"name":"to","type":"address"},{"name":"stable","type":"bool"},{"name":"factory","type":"address"}]},{"name":"to","type":"address"},{"name":"deadline","type":"uint256"}],"name":"swapExactETHForTokens","outputs":[{"name":"amounts","type":"uint256[]"}],"stateMutability":"payable","type":"function"}]
        router = w3.eth.contract(address=AERODROME_ROUTER, abi=router_abi)
        route = [{"from": WETH, "to": token, "stable": False, "factory": "0x4200000000000000000000000000000000000001"}]
        
        call_data = router.encode_abi("swapExactETHForTokens", args=[0, route, await get_smart_vault_address(), int(time.time()) + 600])
        
        op_hash = await send_user_operation(call_data, AERODROME_ROUTER, value=w3.to_wei(amount, 'ether'))
        await status.edit_text(f"🚀 **Operatie verzonden!**\n\nHash: `{op_hash}`")
    except Exception as e:
        logger.error(f"Trade Error: {e}")
        await status.edit_text(f"⚠️ **Architect Error:**\n`{str(e)}`")

# --- 5. RUNNER ---

async def run_bot():
    await asyncio.sleep(5) 
    app_tg = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app_tg.add_handler(CommandHandler("trade", trade_command))
    app_tg.add_handler(CommandHandler("skyline", skyline_report))
    
    await app_tg.initialize()
    await app_tg.start()
    await app_tg.updater.start_polling(poll_interval=2.0)
    logger.info("🚀 Synthora Engine Online.")
    
    while True:
        await asyncio.sleep(3600)

@app.on_event("startup")
async def startup():
    asyncio.create_task(run_bot())

@app.get("/")
async def health():
    return {"status": "Synthora Architect Engine Active"}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
