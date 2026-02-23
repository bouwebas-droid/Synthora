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

active_positions = {}

# ABIs
ROUTER_ABI = [{"inputs":[{"name":"amountOutMin","type":"uint256"},{"name":"routes","type":"tuple[]","components":[{"name":"from","type":"address"},{"name":"to","type":"address"},{"name":"stable","type":"bool"},{"name":"factory","type":"address"}]},{"name":"to","type":"address"},{"name":"deadline","type":"uint256"}],"name":"swapExactETHForTokens","outputs":[{"name":"amounts","type":"uint256[]"}],"stateMutability":"payable","type":"function"},
              {"inputs":[{"name":"amountIn","type":"uint256"},{"name":"amountOutMin","type":"uint256"},{"name":"routes","type":"tuple[]","components":[{"name":"from","type":"address"},{"name":"to","type":"address"},{"name":"stable","type":"bool"},{"name":"factory","type":"address"}]},{"name":"to","type":"address"},{"name":"deadline","type":"uint256"}],"name":"swapExactTokensForETH","outputs":[{"name":"amounts","type":"uint256[]"}],"stateMutability":"nonpayable","type":"function"},
              {"inputs":[{"name":"amountIn","type":"uint256"},{"name":"routes","type":"tuple[]","components":[{"name":"from","type":"address"},{"name":"to","type":"address"},{"name":"stable","type":"bool"},{"name":"factory","type":"address"}]}], "name":"getAmountsOut", "outputs":[{"name":"amounts","type":"uint256[]"}], "stateMutability":"view", "type":"function"}]
ERC20_ABI = [{"inputs":[{"name":"spender","type":"address"},{"name":"amount","type":"uint256"}],"name":"approve","outputs":[{"name":"","type":"bool"}],"stateMutability":"nonpayable","type":"function"},{"inputs":[{"name":"account","type":"address"}],"name":"balanceOf","outputs":[{"name":"","type":"uint256"}],"stateMutability":"view","type":"function"}]
ACCOUNT_ABI = [{"inputs":[{"name":"dest","type":"address"},{"name":"value","type":"uint256"},{"name":"func","type":"bytes"}],"name":"execute","outputs":[],"stateMutability":"nonpayable","type":"function"},
               {"inputs":[{"name":"dest","type":"address[]"},{"name":"value","type":"uint256[]"},{"name":"func","type":"bytes[]"}],"name":"executeBatch","outputs":[],"stateMutability":"nonpayable","type":"function"}]

# --- 2. ERC-4337 CORE ENGINE ---

def get_user_op_hash(op, entry_point, chain_id):
    user_op_packed = encode(
        ['address', 'uint256', 'bytes32', 'bytes32', 'uint256', 'uint256', 'uint256', 'uint256', 'uint256', 'bytes32'],
        [w3.to_checksum_address(op['sender']), int(op['nonce'], 16), w3.keccak(hexstr=op['initCode']), 
         w3.keccak(hexstr=op['callData']), int(op['callGasLimit'], 16), int(op['verificationGasLimit'], 16), 
         int(op['preVerificationGas'], 16), int(op['maxFeePerGas'], 16), int(op['maxPriorityFeePerGas'], 16), 
         w3.keccak(hexstr=op['paymasterAndData'])]
    )
    return w3.keccak(encode(['bytes32', 'address', 'uint256'], [w3.keccak(user_op_packed), w3.to_checksum_address(entry_point), chain_id]))

async def get_smart_vault_address():
    factory = w3.eth.contract(address=SIMPLE_ACCOUNT_FACTORY, abi=[{"inputs":[{"name":"owner","type":"address"},{"name":"salt","type":"uint256"}],"name":"getAddress","outputs":[{"name":"","type":"address"}],"stateMutability":"view","type":"function"}])
    return factory.functions.getAddress(architect_signer.address, 0).call()

async def send_user_operation(call_data, to_address, value=0, is_batch=False):
    vault_address = await get_smart_vault_address()
    init_code = "0x"
    if w3.eth.get_code(vault_address) == b'':
        factory_abi = [{"inputs":[{"name":"owner","type":"address"},{"name":"salt","type":"uint256"}],"name":"createAccount","outputs":[{"name":"","type":"address"}],"stateMutability":"nonpayable","type":"function"}]
        factory = w3.eth.contract(address=SIMPLE_ACCOUNT_FACTORY, abi=factory_abi)
        init_code = SIMPLE_ACCOUNT_FACTORY + factory.encode_abi("createAccount", args=[architect_signer.address, 0])[2:]

    ep_abi = [{"inputs":[{"name":"sender","type":"address"},{"name":"key","type":"uint192"}],"name":"getNonce","outputs":[{"name":"nonce","type":"uint256"}],"stateMutability":"view","type":"function"}]
    ep_contract = w3.eth.contract(address=ENTRY_POINT_ADDRESS, abi=ep_abi)
    nonce = ep_contract.functions.getNonce(vault_address, 0).call()

    if is_batch:
        execute_data = call_data # Call data is al de executeBatch call
    else:
        vault_contract = w3.eth.contract(address=vault_address, abi=ACCOUNT_ABI)
        execute_data = vault_contract.encode_abi("execute", args=[to_address, value, call_data])

    user_op = {
        "sender": vault_address, "nonce": hex(nonce), "initCode": init_code, "callData": execute_data,
        "callGasLimit": hex(2000000), "verificationGasLimit": hex(2000000), "preVerificationGas": hex(2000000),
        "maxFeePerGas": hex(w3.eth.gas_price), "maxPriorityFeePerGas": hex(w3.to_wei(0.001, 'gwei')),
        "paymasterAndData": "0x", "signature": "0x" + "00" * 65
    }

    async with httpx.AsyncClient() as client:
        res = await client.post(PAYMASTER_URL, json={"jsonrpc":"2.0","id":1,"method":"pm_sponsorUserOperation","params":[user_op, ENTRY_POINT_ADDRESS]})
        if "error" in res.json(): raise Exception(f"Sponsor: {res.json()['error'].get('message', res.json()['error'])}")
        user_op.update(res.json()["result"])
        op_hash = get_user_op_hash(user_op, ENTRY_POINT_ADDRESS, 8453)
        user_op["signature"] = architect_signer.signHash(op_hash).signature.hex()
        sub = await client.post(BUNDLER_URL, json={"jsonrpc":"2.0","id":1,"method":"eth_sendUserOperation","params":[user_op, ENTRY_POINT_ADDRESS]})
        if "error" in sub.json(): raise Exception(f"Bundler: {sub.json()['error'].get('message', sub.json()['error'])}")
        return sub.json()["result"]

# --- 3. HIGH-LEVEL TRADE ENGINE ---

async def execute_trade(token_addr, eth_amt):
    """De functie waar commando's naar zochten."""
    token = w3.to_checksum_address(token_addr)
    router = w3.eth.contract(address=AERODROME_ROUTER, abi=ROUTER_ABI)
    route = [{"from": WETH, "to": token, "stable": False, "factory": "0x4200000000000000000000000000000000000001"}]
    call_data = router.encode_abi("swapExactETHForTokens", args=[0, route, await get_smart_vault_address(), int(time.time()) + 600])
    return await send_user_operation(call_data, AERODROME_ROUTER, value=w3.to_wei(eth_amt, 'ether'))

async def execute_sell(token_addr):
    """Batched verkoop voor winst-zekerheid."""
    vault_addr = await get_smart_vault_address()
    token_contract = w3.eth.contract(address=w3.to_checksum_address(token_addr), abi=ERC20_ABI)
    balance = token_contract.functions.balanceOf(vault_addr).call()
    if balance == 0: return "Geen balans"
    
    approve_data = token_contract.encode_abi("approve", args=[AERODROME_ROUTER, balance])
    router = w3.eth.contract(address=AERODROME_ROUTER, abi=ROUTER_ABI)
    route = [{"from": w3.to_checksum_address(token_addr), "to": WETH, "stable": False, "factory": "0x4200000000000000000000000000000000000001"}]
    swap_data = router.encode_abi("swapExactTokensForETH", args=[balance, 0, route, vault_addr, int(time.time()) + 600])

    vault_contract = w3.eth.contract(address=vault_addr, abi=ACCOUNT_ABI)
    batch_calldata = vault_contract.encode_abi("executeBatch", args=[[w3.to_checksum_address(token_addr), AERODROME_ROUTER], [0, 0], [approve_data, swap_data]])
    return await send_user_operation(batch_calldata, vault_addr, is_batch=True)

# --- 4. TELEGRAM COMMAND CENTER ---

async def trade_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    try:
        token, eth_amt = context.args[0], float(context.args[1])
        await update.message.reply_text(f"🏗️ Architect verwerkt trade voor `{token[:8]}...`")
        op_hash = await execute_trade(token, eth_amt)
        await update.message.reply_text(f"🚀 **Succes!** UserOp Hash: `{op_hash}`")
    except Exception as e:
        await update.message.reply_text(f"❌ **Trade Fout:** {e}")

async def vault_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    v = await get_smart_vault_address()
    b = w3.from_wei(w3.eth.get_balance(v), 'ether')
    await update.message.reply_text(f"🔐 **Vault:** `{v}`\n💰 **Balans:** `{b:.4f} ETH`")

async def hunt_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    try:
        eth_amt = float(context.args[0])
        await update.message.reply_text("🐺 **De Jacht is Geopend.** Scannen...")
        async with httpx.AsyncClient() as client:
            res = await client.get("https://api.dexscreener.com/latest/dex/search?q=WETH")
            target = [p for p in res.json().get('pairs', []) if p.get('chainId') == 'base' and p.get('liquidity', {}).get('usd', 0) > 10000][0]
            token_addr = target['baseToken']['address']
            await update.message.reply_text(f"🎯 **Target:** `{target['baseToken']['name']}`. AI executie...")
            op_hash = await execute_trade(token_addr, eth_amt)
            await update.message.reply_text(f"✅ **Hunt Geslaagd!** Hash: `{op_hash}`")
    except Exception as e:
        await update.message.reply_text(f"❌ **Hunt Fout:** {e}")

async def skyline_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    gas = w3.from_wei(w3.eth.gas_price, 'gwei')
    v = await get_smart_vault_address()
    bal = w3.from_wei(w3.eth.get_balance(v), 'ether')
    res = llm.invoke(f"Schrijf een vlijmscherp on-chain rapport voor Chillzilla. Gas: {gas:.4f} Gwei, Vault: {bal:.4f} ETH.")
    await update.message.reply_text(f"🏙️ **Skyline Status**\n\n{res.content}", parse_mode='Markdown')

# --- 5. RUNNER ---
async def run_bot():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("trade", trade_command))
    app.add_handler(CommandHandler("vault", vault_command))
    app.add_handler(CommandHandler("hunt", hunt_command))
    app.add_handler(CommandHandler("skyline", skyline_command))
    await app.initialize(); await app.start(); await app.updater.start_polling(drop_pending_updates=True)
    while True: await asyncio.sleep(3600)

app = FastAPI()
@app.on_event("startup")
async def startup(): asyncio.create_task(run_bot())

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
