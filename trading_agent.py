# --- 1. IMPORTS & FUNDERING ---
import logging, os, asyncio, time, httpx
from web3 import Web3
from eth_account import Account
from eth_account.messages import encode_defunct
from eth_abi import encode
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from langchain_openai import ChatOpenAI
from fastapi import FastAPI
import uvicorn

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Synthora")

BASE_RPC_URL = "https://mainnet.base.org"
w3 = Web3(Web3.HTTPProvider(BASE_RPC_URL))

PIMLICO_API_KEY = os.environ.get("PIMLICO_API_KEY", "")
BUNDLER_URL = f"https://api.pimlico.io/v2/8453/rpc?apikey={PIMLICO_API_KEY}"
PAYMASTER_URL = BUNDLER_URL

ENTRY_POINT_ADDRESS = "0x5FF137D4b0FDCD49DcA30c7CF57E578a026d2789"
SIMPLE_ACCOUNT_FACTORY = "0x9406Cc6185a346906296840746125a0E44976454"
AERODROME_ROUTER = "0xcF77a3Ba9A5CA399B7c97c74d54e5b1Beb874E43"
WETH = "0x4200000000000000000000000000000000000006"

OWNER_ID = int(os.environ.get("OWNER_ID", 0))
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
private_key = os.environ.get("ARCHITECT_SESSION_KEY")
architect_signer = Account.from_key(private_key) if private_key else None
llm = ChatOpenAI(model="gpt-4o", api_key=os.environ.get("OPENAI_API_KEY"))

# --- 2. CRYPTOGRAFIE ENGINE (PRECISIEWERK) ---

def get_user_op_hash(op, entry_point, chain_id):
    """Berekent de UserOpHash conform de ERC-4337 standaard."""
    # Hash de individuele velden die bytes vereisen
    init_code_hash = w3.keccak(hexstr=op['initCode'])
    call_data_hash = w3.keccak(hexstr=op['callData'])
    paymaster_and_data_hash = w3.keccak(hexstr=op['paymasterAndData'])

    # 1. Pack de UserOp
    user_op_encoded = encode(
        ['address', 'uint256', 'bytes32', 'bytes32', 'uint256', 'uint256', 'uint256', 'uint256', 'uint256', 'bytes32'],
        [
            w3.to_checksum_address(op['sender']),
            int(op['nonce'], 16),
            init_code_hash,
            call_data_hash,
            int(op['callGasLimit'], 16),
            int(op['verificationGasLimit'], 16),
            int(op['preVerificationGas'], 16),
            int(op['maxFeePerGas'], 16),
            int(op['maxPriorityFeePerGas'], 16),
            paymaster_and_data_hash
        ]
    )
    user_op_hash = w3.keccak(user_op_encoded)
    
    # 2. Combineer met EntryPoint en ChainId
    final_encoded = encode(
        ['bytes32', 'address', 'uint256'],
        [user_op_hash, w3.to_checksum_address(entry_point), chain_id]
    )
    return w3.keccak(final_encoded)

async def get_smart_vault_address():
    factory_abi = [{"inputs":[{"name":"owner","type":"address"},{"name":"salt","type":"uint256"}],"name":"getAddress","outputs":[{"name":"","type":"address"}],"stateMutability":"view","type":"function"}]
    factory = w3.eth.contract(address=SIMPLE_ACCOUNT_FACTORY, abi=factory_abi)
    return factory.functions.getAddress(architect_signer.address, 0).call()

async def send_user_operation(call_data, to_address, value=0, is_batch=False):
    vault_address = await get_smart_vault_address()
    
    # InitCode bepalen
    init_code = "0x"
    if w3.eth.get_code(vault_address) == b'':
        factory_contract = w3.eth.contract(address=SIMPLE_ACCOUNT_FACTORY, abi=[{"inputs":[{"name":"owner","type":"address"},{"name":"salt","type":"uint256"}],"name":"createAccount","outputs":[{"name":"","type":"address"}],"stateMutability":"nonpayable","type":"function"}])
        init_code = SIMPLE_ACCOUNT_FACTORY + factory_contract.encode_abi("createAccount", args=[architect_signer.address, 0])[2:]

    # Nonce ophalen
    ep_abi = [{"inputs":[{"name":"sender","type":"address"},{"name":"key","type":"uint192"}],"name":"getNonce","outputs":[{"name":"nonce","type":"uint256"}],"stateMutability":"view","type":"function"}]
    ep_contract = w3.eth.contract(address=ENTRY_POINT_ADDRESS, abi=ep_abi)
    nonce = ep_contract.functions.getNonce(vault_address, 0).call()

    # Execute Calldata
    acc_abi = [{"inputs":[{"name":"dest","type":"address"},{"name":"value","type":"uint256"},{"name":"func","type":"bytes"}],"name":"execute","outputs":[],"stateMutability":"nonpayable","type":"function"}]
    vault_contract = w3.eth.contract(address=vault_address, abi=acc_abi)
    execute_data = vault_contract.encode_abi("execute", args=[to_address, value, call_data])

    user_op = {
        "sender": vault_address,
        "nonce": hex(nonce),
        "initCode": init_code,
        "callData": execute_data,
        "callGasLimit": hex(1500000),
        "verificationGasLimit": hex(1500000),
        "preVerificationGas": hex(1500000),
        "maxFeePerGas": hex(w3.eth.gas_price),
        "maxPriorityFeePerGas": hex(w3.to_wei(0.001, 'gwei')),
        "paymasterAndData": "0x",
        "signature": "0x" + "00" * 65 # Dummy voor sponsoring
    }

    async with httpx.AsyncClient() as client:
        # 1. Sponsor via Pimlico
        res = await client.post(PAYMASTER_URL, json={"jsonrpc":"2.0","id":1,"method":"pm_sponsorUserOperation","params":[user_op, ENTRY_POINT_ADDRESS]})
        if "error" in res.json(): 
            raise Exception(f"Sponsor: {res.json()['error'].get('message', res.json()['error'])}")
        
        user_op.update(res.json()["result"])

        # 2. Cryptografisch Ondertekenen
        op_hash = get_user_op_hash(user_op, ENTRY_POINT_ADDRESS, 8453)
        # Gebruik sign_message met encode_defunct voor de standaard Ethereum prefix (SimpleAccount verwacht dit)
        signature = architect_signer.sign_message(encode_defunct(primitive=op_hash))
        user_op["signature"] = signature.signature.hex()

        # 3. Verzenden naar Bundler
        sub = await client.post(BUNDLER_URL, json={"jsonrpc":"2.0","id":1,"method":"eth_sendUserOperation","params":[user_op, ENTRY_POINT_ADDRESS]})
        if "error" in sub.json(): 
            raise Exception(f"Bundler: {sub.json()['error'].get('message', sub.json()['error'])}")
            
        return sub.json()["result"]

# --- 3. COMMAND CENTER ---

async def trade_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    if len(context.args) < 2:
        await update.message.reply_text("❌ Gebruik: `/trade [token_adres] [eth_bedrag]`")
        return
    try:
        token, eth_amt = context.args[0], float(context.args[1])
        await update.message.reply_text(f"🏗️ Architect zet UserOp on-chain...")
        
        router_abi = [{"inputs":[{"name":"amountOutMin","type":"uint256"},{"name":"routes","type":"tuple[]","components":[{"name":"from","type":"address"},{"name":"to","type":"address"},{"name":"stable","type":"bool"},{"name":"factory","type":"address"}]},{"name":"to","type":"address"},{"name":"deadline","type":"uint256"}],"name":"swapExactETHForTokens","outputs":[{"name":"amounts","type":"uint256[]"}],"stateMutability":"payable","type":"function"}]
        router = w3.eth.contract(address=AERODROME_ROUTER, abi=router_abi)
        route = [{"from": WETH, "to": w3.to_checksum_address(token), "stable": False, "factory": "0x4200000000000000000000000000000000000001"}]
        call_data = router.encode_abi("swapExactETHForTokens", args=[0, route, await get_smart_vault_address(), int(time.time()) + 600])
        
        op_hash = await send_user_operation(call_data, AERODROME_ROUTER, value=w3.to_wei(eth_amt, 'ether'))
        await update.message.reply_text(f"🚀 **Succes!** UserOp Hash: `{op_hash}`")
    except Exception as e:
        await update.message.reply_text(f"❌ **Fout melding:**\n`{str(e)}`")

async def vault_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    v = await get_smart_vault_address()
    b = w3.from_wei(w3.eth.get_balance(v), 'ether')
    await update.message.reply_text(f"🔐 **Vault:** `{v}`\n💰 **Balans:** `{b:.4f} ETH`")

# --- 4. RUNNER ---
async def run_bot():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("trade", trade_command))
    app.add_handler(CommandHandler("vault", vault_command))
    await app.initialize(); await app.start(); await app.updater.start_polling(drop_pending_updates=True)
    logger.info("🚀 Architect Online.")
    while True: await asyncio.sleep(3600)

app = FastAPI()
@app.on_event("startup")
async def startup(): asyncio.create_task(run_bot())

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
                        
