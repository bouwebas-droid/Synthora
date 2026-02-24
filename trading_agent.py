# --- 1. IMPORTS & FUNDERING ---
import logging, os, asyncio, time, httpx
from web3 import Web3
from eth_account import Account
from eth_account.messages import encode_defunct
from eth_utils import to_hex, to_bytes, keccak
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

PIMLICO_API_KEY = os.environ.get("PIMLICO_API_KEY", "pim_ST3uu8TuhhbGHzNbGUxBeS")
BUNDLER_URL = f"https://api.pimlico.io/v2/8453/rpc?apikey={PIMLICO_API_KEY}"

ENTRY_POINT_ADDRESS = "0x5FF137D4b0FDCD49DcA30c7CF57E578a026d2789"
SIMPLE_ACCOUNT_FACTORY = "0x9406Cc6185a346906296840746125a0E44976454"
AERODROME_ROUTER = "0xcF77a3Ba9A5CA399B7c97c74d54e5b1Beb874E43"
WETH = "0x4200000000000000000000000000000000000006"
CHAIN_ID = 8453

# --- 3. ARCHITECT CORE LOGICA ---

def calculate_user_op_hash(user_op):
    """Berekent de UserOp hash handmatig volgens de ERC-4337 standaard."""
    packed_op = w3.codec.encode(
        ['address', 'uint256', 'bytes32', 'bytes32', 'uint256', 'uint256', 'uint256', 'uint256', 'uint256', 'bytes32'],
        [
            user_op['sender'],
            int(user_op['nonce'], 16),
            keccak(to_bytes(hexstr=user_op['initCode'])),
            keccak(to_bytes(hexstr=user_op['callData'])),
            int(user_op['callGasLimit'], 16),
            int(user_op['verificationGasLimit'], 16),
            int(user_op['preVerificationGas'], 16),
            int(user_op['maxFeePerGas'], 16),
            int(user_op['maxPriorityFeePerGas'], 16),
            keccak(to_bytes(hexstr=user_op['paymasterAndData']))
        ]
    )
    user_op_hash = keccak(packed_op)
    final_packed = w3.codec.encode(['bytes32', 'address', 'uint256'], [user_op_hash, ENTRY_POINT_ADDRESS, CHAIN_ID])
    return keccak(final_packed)

async def get_smart_vault_address():
    factory_abi = [{"inputs":[{"name":"owner","type":"address"},{"name":"salt","type":"uint256"}],"name":"getAddress","outputs":[{"name":"","type":"address"}],"stateMutability":"view","type":"function"}]
    factory = w3.eth.contract(address=SIMPLE_ACCOUNT_FACTORY, abi=factory_abi)
    return factory.functions.getAddress(architect_signer.address, 0).call()

async def send_user_operation(call_data, to_address, value=0):
    vault_address = await get_smart_vault_address()
    
    init_code = "0x"
    if w3.eth.get_code(vault_address) == b'':
        factory_contract = w3.eth.contract(address=SIMPLE_ACCOUNT_FACTORY, abi=[{"inputs":[{"name":"owner","type":"address"},{"name":"salt","type":"uint256"}],"name":"createAccount","outputs":[{"name":"","type":"address"}],"stateMutability":"nonpayable","type":"function"}])
        init_code = SIMPLE_ACCOUNT_FACTORY + factory_contract.encode_abi("createAccount", args=[architect_signer.address, 0])[2:]

    ep_contract = w3.eth.contract(address=ENTRY_POINT_ADDRESS, abi=[{"inputs":[{"name":"sender","type":"address"},{"name":"key","type":"uint192"}],"name":"getNonce","outputs":[{"name":"nonce","type":"uint256"}],"stateMutability":"view","type":"function"}])
    nonce = ep_contract.functions.getNonce(vault_address, 0).call()
    
    vault_contract = w3.eth.contract(address=vault_address, abi=[{"inputs":[{"name":"dest","type":"address"},{"name":"value","type":"uint256"},{"name":"func","type":"bytes"}],"name":"execute","outputs":[],"stateMutability":"nonpayable","type":"function"}])
    execute_data = vault_contract.encode_abi("execute", args=[to_address, value, call_data])

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Stap 1: Gas prijzen
        gas_res = await client.post(BUNDLER_URL, json={"jsonrpc":"2.0","id":1,"method":"pimlico_getUserOperationGasPrice","params":[]})
        gp = gas_res.json()["result"]["standard"]

        user_op = {
            "sender": vault_address, "nonce": to_hex(nonce), "initCode": init_code, "callData": execute_data,
            "callGasLimit": to_hex(2000000), "verificationGasLimit": to_hex(1000000), "preVerificationGas": to_hex(100000),
            "maxFeePerGas": gp["maxFeePerGas"], "maxPriorityFeePerGas": gp["maxPriorityFeePerGas"],
            "paymasterAndData": "0x", "signature": "0x"
        }

        # --- EERSTE HANDTEKENING (Simulatie) ---
        op_hash = calculate_user_op_hash(user_op)
        sig = architect_signer.sign_message(encode_defunct(primitive=op_hash))
        user_op["signature"] = f"0x{sig.signature.hex()}"

        # Stap 2: Sponsoring
        res = await client.post(BUNDLER_URL, json={"jsonrpc":"2.0","id":1,"method":"pm_sponsorUserOperation","params":[user_op, ENTRY_POINT_ADDRESS]})
        sponsor_data = res.json()
        if "error" in sponsor_data:
            raise Exception(f"Sponsor Fout: {sponsor_data['error'].get('message')}")
        
        user_op.update(sponsor_data["result"])

        # --- TWEEDE HANDTEKENING (Definitief) ---
        final_hash = calculate_user_op_hash(user_op)
        final_sig = architect_signer.sign_message(encode_defunct(primitive=final_hash))
        user_op["signature"] = f"0x{final_sig.signature.hex()}"

        # Stap 3: Verzenden
        final_res = await client.post(BUNDLER_URL, json={"jsonrpc":"2.0","id":1,"method":"eth_sendUserOperation","params":[user_op, ENTRY_POINT_ADDRESS]})
        return final_res.json().get("result") or str(final_res.json().get("error"))

# --- 4. COMMAND CENTER ---

OWNER_ID = int(os.environ.get("OWNER_ID", 0))
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
architect_signer = Account.from_key(os.environ.get("ARCHITECT_SESSION_KEY")) if os.environ.get("ARCHITECT_SESSION_KEY") else None

async def skyline_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    v = await get_smart_vault_address()
    b = w3.from_wei(w3.eth.get_balance(v), 'ether')
    await update.message.reply_text(f"🏙️ **Synthora Skyline Audit**\nVault: `{v}`\nSaldo: `{b:.6f} ETH`", parse_mode='Markdown')

async def trade_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    if len(context.args) < 2: return
    msg = await update.message.reply_text("🏗️ **Synthetiseren van operatie...**")
    try:
        token = w3.to_checksum_address(context.args[0])
        amount = float(context.args[1].replace(',', '.'))
        
        # GEFIXTE ABI VOOR AERODROME
        router_abi = [{
            "inputs": [
                {"name": "amountOutMin", "type": "uint256"},
                {"name": "routes", "type": "tuple[]", "components": [
                    {"name": "from", "type": "address"},
                    {"name": "to", "type": "address"},
                    {"name": "stable", "type": "bool"},
                    {"name": "factory", "type": "address"}
                ]},
                {"name": "to", "type": "address"},
                {"name": "deadline", "type": "uint256"}
            ],
            "name": "swapExactETHForTokens",
            "outputs": [{"name": "amounts", "type": "uint256[]"}],
            "stateMutability": "payable",
            "type": "function"
        }]
        
        router = w3.eth.contract(address=AERODROME_ROUTER, abi=router_abi)
        route = [{"from": WETH, "to": token, "stable": False, "factory": "0x4200000000000000000000000000000000000001"}]
        
        call_data = router.encode_abi("swapExactETHForTokens", args=[0, route, await get_smart_vault_address(), int(time.time()) + 600])
        
        op_hash = await send_user_operation(call_data, AERODROME_ROUTER, value=w3.to_wei(amount, 'ether'))
        await msg.edit_text(f"🚀 **Operatie verzonden naar Base!**\nHash: `{op_hash}`")
    except Exception as e:
        logger.error(f"Trade Error: {e}")
        await msg.edit_text(f"⚠️ **Architect Error:** `{str(e)}`")

# --- 5. RUNNER ---
async def run_bot():
    await asyncio.sleep(5)
    app_tg = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app_tg.add_handler(CommandHandler("trade", trade_command))
    app_tg.add_handler(CommandHandler("skyline", skyline_report))
    await app_tg.initialize()
    await app_tg.start()
    await app_tg.updater.start_polling()
    logger.info("🚀 Synthora Engine Online.")
    while True: await asyncio.sleep(3600)

@app.on_event("startup")
async def startup(): asyncio.create_task(run_bot())

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
        
