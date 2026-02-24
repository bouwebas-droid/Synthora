import logging, os, asyncio, time, httpx
from web3 import Web3
from eth_account import Account
from eth_account.messages import encode_defunct
from eth_utils import to_hex, to_bytes, keccak
from eth_abi import encode
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from fastapi import FastAPI
import uvicorn

# Logging instellen
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger("BlockchainAgent")
app = FastAPI()

# --- CONFIGURATIE ---
# Vul hier je eigen omgevingsvariabelen of waarden in
RPC_URL = "https://mainnet.base.org"
PIMLICO_API_KEY = os.environ.get("PIMLICO_API_KEY", "JOUW_PIMLICO_KEY")
BUNDLER_URL = f"https://api.pimlico.io/v2/8453/rpc?apikey={PIMLICO_API_KEY}"

PRIVATE_KEY = os.environ.get("PRIVATE_KEY", "JOUW_PRIVATE_KEY")
OWNER_ID = int(os.environ.get("OWNER_ID", 0))
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

# Contracten (Base Mainnet)
ENTRY_POINT = "0x5FF137D4b0FDCD49DcA30c7CF57E578a026d2789"
ACCOUNT_FACTORY = "0x9406Cc6185a346906296840746125a0E44976454"
AERODROME_ROUTER = "0xcF77a3Ba9A5CA399B7c97c74d54e5b1Beb874E43"
WETH = "0x4200000000000000000000000000000000000006"
CHAIN_ID = 8453

w3 = Web3(Web3.HTTPProvider(RPC_URL))
signer = Account.from_key(PRIVATE_KEY)

# --- CORE LOGICA ---

def get_user_op_hash(user_op):
    """
    Berekent de UserOp hash exact volgens de EntryPoint v0.6 standaard.
    Dit voorkomt de 0x9a73ab46 (Invalid Signature) fout.
    """
    # 1. Hash de individuele bytes velden (initCode, callData, paymasterAndData)
    init_hash = keccak(to_bytes(hexstr=user_op['initCode']))
    call_hash = keccak(to_bytes(hexstr=user_op['callData']))
    pm_hash = keccak(to_bytes(hexstr=user_op['paymasterAndData']))

    # 2. Pack de hoofd-structuur volgens de ABI-specificatie
    user_op_encoded = encode(
        ['address', 'uint256', 'bytes32', 'bytes32', 'uint256', 'uint256', 'uint256', 'uint256', 'uint256', 'bytes32'],
        [
            w3.to_checksum_address(user_op['sender']),
            int(user_op['nonce'], 16),
            init_hash,
            call_hash,
            int(user_op['callGasLimit'], 16),
            int(user_op['verificationGasLimit'], 16),
            int(user_op['preVerificationGas'], 16),
            int(user_op['maxFeePerGas'], 16),
            int(user_op['maxPriorityFeePerGas'], 16),
            pm_hash
        ]
    )
    
    # 3. Combineer de gehashte structuur met het EntryPoint adres en de Chain ID
    hashed_op = keccak(user_op_encoded)
    final_encoded = encode(
        ['bytes32', 'address', 'uint256'],
        [hashed_op, w3.to_checksum_address(ENTRY_POINT), CHAIN_ID]
    )
    return keccak(final_encoded)

async def get_vault_address():
    factory_abi = [{"inputs":[{"name":"owner","type":"address"},{"name":"salt","type":"uint256"}],"name":"getAddress","outputs":[{"name":"","type":"address"}],"stateMutability":"view","type":"function"}]
    factory = w3.eth.contract(address=ACCOUNT_FACTORY, abi=factory_abi)
    return factory.functions.getAddress(signer.address, 0).call()

async def send_user_operation(call_data, to_address, value=0):
    vault_addr = await get_vault_address()
    
    # InitCode bepalen
    init_code = "0x"
    if w3.eth.get_code(vault_addr) == b'':
        factory_contract = w3.eth.contract(address=ACCOUNT_FACTORY, abi=[{"inputs":[{"name":"owner","type":"address"},{"name":"salt","type":"uint256"}],"name":"createAccount","outputs":[{"name":"","type":"address"}],"stateMutability":"nonpayable","type":"function"}])
        init_code = ACCOUNT_FACTORY + factory_contract.encode_abi("createAccount", args=[signer.address, 0])[2:]

    # Nonce ophalen
    ep_abi = [{"inputs":[{"name":"sender","type":"address"},{"name":"key","type":"uint192"}],"name":"getNonce","outputs":[{"name":"nonce","type":"uint256"}],"stateMutability":"view","type":"function"}]
    nonce = w3.eth.contract(address=ENTRY_POINT, abi=ep_abi).functions.getNonce(vault_addr, 0).call()
    
    # Execute data voor de kluis
    acc_abi = [{"inputs":[{"name":"dest","type":"address"},{"name":"value","type":"uint256"},{"name":"func","type":"bytes"}],"name":"execute","outputs":[],"stateMutability":"nonpayable","type":"function"}]
    vault_contract = w3.eth.contract(address=vault_addr, abi=acc_abi)
    execute_data = vault_contract.encode_abi("execute", args=[to_address, value, call_data])

    async with httpx.AsyncClient(timeout=60.0) as client:
        # Gas prijzen ophalen
        gas_res = await client.post(BUNDLER_URL, json={"jsonrpc":"2.0","id":1,"method":"pimlico_getUserOperationGasPrice","params":[]})
        gp = gas_res.json()["result"]["standard"]

        user_op = {
            "sender": vault_addr, "nonce": to_hex(nonce), "initCode": init_code, "callData": execute_data,
            "callGasLimit": to_hex(2000000), "verificationGasLimit": to_hex(1000000), "preVerificationGas": to_hex(100000),
            "maxFeePerGas": gp["maxFeePerGas"], "maxPriorityFeePerGas": gp["maxPriorityFeePerGas"],
            "paymasterAndData": "0x", "signature": "0x"
        }

        # --- STAP 1: ONDERTEKENEN VOOR SIMULATIE ---
        op_hash = get_user_op_hash(user_op)
        sig = signer.sign_message(encode_defunct(primitive=op_hash))
        user_op["signature"] = f"0x{sig.signature.hex()}"

        # Sponsoring aanvragen
        res = await client.post(BUNDLER_URL, json={"jsonrpc":"2.0","id":1,"method":"pm_sponsorUserOperation","params":[user_op, ENTRY_POINT]})
        sponsor_data = res.json()
        if "error" in sponsor_data:
            raise Exception(f"Sponsor Fout: {sponsor_data['error'].get('message')}")
        
        user_op.update(sponsor_data["result"])

        # --- STAP 2: DEFINITIEVE HANDTEKENING ---
        final_hash = get_user_op_hash(user_op)
        final_sig = signer.sign_message(encode_defunct(primitive=final_hash))
        user_op["signature"] = f"0x{final_sig.signature.hex()}"

        # Verzenden naar bundler
        final_res = await client.post(BUNDLER_URL, json={"jsonrpc":"2.0","id":1,"method":"eth_sendUserOperation","params":[user_op, ENTRY_POINT]})
        return final_res.json().get("result") or str(final_res.json().get("error"))

# --- TELEGRAM HANDLERS ---

async def trade_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    if len(context.args) < 2: return
    
    status = await update.message.reply_text("🏗️ Bezig met verwerken...")
    try:
        token_addr = w3.to_checksum_address(context.args[0])
        amount_eth = float(context.args[1].replace(',', '.'))
        
        # Aerodrome Router logica
        router_abi = [{"inputs": [{"name": "amountOutMin", "type": "uint256"}, {"name": "routes", "type": "tuple[]", "components": [{"name": "from", "type": "address"}, {"name": "to", "type": "address"}, {"name": "stable", "type": "bool"}, {"name": "factory", "type": "address"}]}, {"name": "to", "type": "address"}, {"name": "deadline", "type": "uint256"}], "name": "swapExactETHForTokens", "outputs": [{"name": "amounts", "type": "uint256[]"}], "stateMutability": "payable", "type": "function"}]
        router = w3.eth.contract(address=AERODROME_ROUTER, abi=router_abi)
        route = [{"from": WETH, "to": token_addr, "stable": False, "factory": "0x4200000000000000000000000000000000000001"}]
        
        call_data = router.encode_abi("swapExactETHForTokens", args=[0, route, await get_vault_address(), int(time.time()) + 600])
        op_hash = await send_user_operation(call_data, AERODROME_ROUTER, value=w3.to_wei(amount_eth, 'ether'))
        
        await status.edit_text(f"🚀 Succesvol verzonden!\nHash: `{op_hash}`", parse_mode='Markdown')
    except Exception as e:
        await status.edit_text(f"⚠️ Fout: `{e}`")

async def run_bot():
    bot_app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    bot_app.add_handler(CommandHandler("trade", trade_command))
    await bot_app.initialize()
    await bot_app.start()
    await bot_app.updater.start_polling()
    while True: await asyncio.sleep(3600)

@app.on_event("startup")
async def startup():
    asyncio.create_task(run_bot())

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
