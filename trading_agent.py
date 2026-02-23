# --- 1. IMPORTS & FUNDERING ---
import logging, os, asyncio, time, httpx
from web3 import Web3
from eth_account import Account
from eth_abi import encode
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from langchain_openai import ChatOpenAI
from fastapi import FastAPI
import uvicorn

# --- CONFIGURATIE ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Synthora")

BASE_RPC_URL = "https://mainnet.base.org"
w3 = Web3(Web3.HTTPProvider(BASE_RPC_URL))

# Pimlico & ERC-4337 Adressen (Base Network - Chain ID 8453)
PIMLICO_API_KEY = os.environ.get("PIMLICO_API_KEY", "")
BUNDLER_URL = f"https://api.pimlico.io/v2/8453/rpc?apikey={PIMLICO_API_KEY}"
PAYMASTER_URL = BUNDLER_URL

ENTRY_POINT_ADDRESS = "0x5FF137D4b0FDCD49DcA30c7CF57E578a026d2789"
SIMPLE_ACCOUNT_FACTORY = "0x9406Cc6185a346906296840746125a0E44976454"

# Adressen Base
AERODROME_ROUTER = "0xcF77a3Ba9A5CA399B7c97c74d54e5b1Beb874E43"
WETH = "0x4200000000000000000000000000000000000006"

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
OWNER_ID = int(os.environ.get("OWNER_ID", 0))

private_key = os.environ.get("ARCHITECT_SESSION_KEY")
architect_signer = Account.from_key(private_key) if private_key else None
llm = ChatOpenAI(model="gpt-4o", api_key=OPENAI_API_KEY)

# ABIs
ROUTER_ABI = [{"inputs":[{"name":"amountOutMin","type":"uint256"},{"name":"routes","type":"tuple[]","components":[{"name":"from","type":"address"},{"name":"to","type":"address"},{"name":"stable","type":"bool"},{"name":"factory","type":"address"}]},{"name":"to","type":"address"},{"name":"deadline","type":"uint256"}],"name":"swapExactETHForTokens","outputs":[{"name":"amounts","type":"uint256[]"}],"stateMutability":"payable","type":"function"}]
ERC20_ABI = [{"inputs":[{"name":"spender","type":"address"},{"name":"amount","type":"uint256"}],"name":"approve","outputs":[{"name":"","type":"bool"}],"stateMutability":"nonpayable","type":"function"},{"inputs":[{"name":"account","type":"address"}],"name":"balanceOf","outputs":[{"name":"","type":"uint256"}],"stateMutability":"view","type":"function"}]
ACCOUNT_ABI = [{"inputs":[{"name":"dest","type":"address"},{"name":"value","type":"uint256"},{"name":"func","type":"bytes"}],"name":"execute","outputs":[],"stateMutability":"nonpayable","type":"function"}]
FACTORY_ABI = [{"inputs":[{"name":"owner","type":"address"},{"name":"salt","type":"uint256"}],"name":"getAddress","outputs":[{"name":"","type":"address"}],"stateMutability":"view","type":"function"},{"inputs":[{"name":"owner","type":"address"},{"name":"salt","type":"uint256"}],"name":"createAccount","outputs":[{"name":"","type":"address"}],"stateMutability":"nonpayable","type":"function"}]

# --- 2. ERC-4337 CRYPTOGRAFIE ---

def pack_user_op(op):
    """Pakt de UserOp in voor de hashing (volgens EntryPoint v0.6 specs)."""
    return encode(
        ['address', 'uint256', 'bytes32', 'bytes32', 'uint256', 'uint256', 'uint256', 'uint256', 'uint256', 'bytes32'],
        [
            w3.to_checksum_address(op['sender']),
            int(op['nonce'], 16),
            w3.keccak(hexstr=op['initCode']),
            w3.keccak(hexstr=op['callData']),
            int(op['callGasLimit'], 16),
            int(op['verificationGasLimit'], 16),
            int(op['preVerificationGas'], 16),
            int(op['maxFeePerGas'], 16),
            int(op['maxPriorityFeePerGas'], 16),
            w3.keccak(hexstr=op['paymasterAndData'])
        ]
    )

async def send_user_operation(call_data, to_address, value=0):
    vault_address = await get_smart_vault_address()
    
    init_code = "0x"
    if w3.eth.get_code(vault_address) == b'':
        factory = w3.eth.contract(address=SIMPLE_ACCOUNT_FACTORY, abi=FACTORY_ABI)
        init_code = SIMPLE_ACCOUNT_FACTORY + factory.encode_abi("createAccount", args=[architect_signer.address, 0])[2:]

    # Haal de echte nonce op
    ep_abi = [{"inputs":[{"name":"sender","type":"address"},{"name":"key","type":"uint192"}],"name":"getNonce","outputs":[{"name":"nonce","type":"uint256"}],"stateMutability":"view","type":"function"}]
    ep_contract = w3.eth.contract(address=ENTRY_POINT_ADDRESS, abi=ep_abi)
    nonce = ep_contract.functions.getNonce(vault_address, 0).call()

    account_contract = w3.eth.contract(address=vault_address, abi=ACCOUNT_ABI)
    encoded_execute = account_contract.encode_abi("execute", args=[to_address, value, call_data])

    user_op = {
        "sender": vault_address,
        "nonce": hex(nonce),
        "initCode": init_code,
        "callData": encoded_execute,
        "callGasLimit": hex(1000000), # Placeholder voor schatting
        "verificationGasLimit": hex(1000000),
        "preVerificationGas": hex(1000000),
        "maxFeePerGas": hex(w3.eth.gas_price),
        "maxPriorityFeePerGas": hex(w3.to_wei(0.001, 'gwei')),
        "paymasterAndData": "0x",
        "signature": "0x" + "00" * 65
    }

    async with httpx.AsyncClient() as client:
        # 1. Sponsor
        res = await client.post(PAYMASTER_URL, json={"jsonrpc":"2.0","id":1,"method":"pm_sponsorUserOperation","params":[user_op, ENTRY_POINT_ADDRESS]})
        if "error" in res.json(): raise Exception(f"Sponsor Fout: {res.json()['error']}")
        user_op.update(res.json()["result"])

        # 2. SignHash (Zonder prefix, pure ECDSA)
        user_op_hash = w3.keccak(encode(['bytes32', 'address', 'uint256'], [w3.keccak(pack_user_op(user_op)), ENTRY_POINT_ADDRESS, 8453]))
        signature = w3.eth.account.signHash(user_op_hash, private_key=private_key)
        user_op["signature"] = signature.signature.hex()

        # 3. Submit
        submit = await client.post(BUNDLER_URL, json={"jsonrpc":"2.0","id":1,"method":"eth_sendUserOperation","params":[user_op, ENTRY_POINT_ADDRESS]})
        if "error" in submit.json(): raise Exception(f"Bundler Fout: {submit.json()['error']}")
        return submit.json()["result"]

async def get_smart_vault_address():
    factory = w3.eth.contract(address=SIMPLE_ACCOUNT_FACTORY, abi=FACTORY_ABI)
    return factory.functions.getAddress(architect_signer.address, 0).call()

# --- 3. COMMANDS ---

async def trade_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    try:
        token, eth_amt = context.args[0], float(context.args[1])
        router = w3.eth.contract(address=AERODROME_ROUTER, abi=ROUTER_ABI)
        route = [{"from": WETH, "to": w3.to_checksum_address(token), "stable": False, "factory": "0x4200000000000000000000000000000000000001"}]
        call_data = router.encode_abi("swapExactETHForTokens", args=[0, route, await get_smart_vault_address(), int(time.time()) + 600])
        
        op_hash = await send_user_operation(call_data, AERODROME_ROUTER, value=w3.to_wei(eth_amt, 'ether'))
        await update.message.reply_text(f"🚀 **UserOp Verzonden!**\nHash: `{op_hash}`")
    except Exception as e:
        await update.message.reply_text(f"❌ **Fout:** {e}")

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
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    while True: await asyncio.sleep(3600)

app = FastAPI()
@app.on_event("startup")
async def startup(): asyncio.create_task(run_bot())

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
        

# --- 4. AUTONOME JACHT (RADAR & HUNT) ---

async def fetch_hunting_target():
    async with httpx.AsyncClient() as client:
        res = await client.get("https://api.dexscreener.com/latest/dex/search?q=WETH")
        if res.status_code != 200: return None
        data = res.json()
        base_pairs = [p for p in data.get('pairs', []) if p.get('chainId') == 'base']
        valid_pairs = [p for p in base_pairs if p.get('liquidity', {}).get('usd', 0) > 10000]
        valid_pairs.sort(key=lambda x: x.get('volume', {}).get('h24', 0), reverse=True)
        for pair in valid_pairs:
            if pair['baseToken']['address'].lower() != WETH.lower():
                return pair
    return None

async def hunt_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    try:
        eth_amt, target_pct = float(context.args[0]), float(context.args[1])
        await update.message.reply_text("🐺 **De Jacht is Geopend.**\nDe Architect scant Base via DexScreener...")
        
        target = await fetch_hunting_target()
        if not target:
            await update.message.reply_text("📉 Geen geschikte targets gevonden.")
            return
            
        token_name, token_addr = target['baseToken']['name'], target['baseToken']['address']
        liquidity, volume = target.get('liquidity', {}).get('usd', 0), target.get('volume', {}).get('h24', 0)
        
        await update.message.reply_text(f"🎯 **Target Gevonden:** `{token_name}`\nAdres: `{token_addr}`\n💧 Liq: `${liquidity:,.0f}` | 📊 Vol: `${volume:,.0f}`\n\nAI check...")
        
        gas = w3.from_wei(w3.eth.gas_price, 'gwei')
        prompt = f"Je bent de trading architect voor Chillzilla. Gas: {gas:.2f}. Token: {token_name}. Liq: ${liquidity}. Vol: ${volume}. Antwoord UITSLUITEND met 'EXECUTE' of 'HOLD'."
        
        if "EXECUTE" in llm.invoke(prompt).content.strip().upper():
            await update.message.reply_text(f"⚡ **AI GEEFT GROEN LICHT!** Meteen inkopen (Gasless)...")
            tx_hash = await execute_trade(token_addr, eth_amt)
            await update.message.reply_text(f"✅ **Hunt Geslaagd.** UserOp: `{tx_hash}`\nGuardian overname voor `{target_pct}%` winst.")
            asyncio.create_task(profit_guardian(update, token_addr, eth_amt, target_pct))
        else:
            await update.message.reply_text(f"🛑 **AI weigert.** Condities niet optimaal.")
    except Exception as e:
        await update.message.reply_text(f"❌ **Hunt Fout:** {e}")

async def radar_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    try:
        token, eth_amt, target = context.args[0], float(context.args[1]), float(context.args[2])
        await update.message.reply_text(f"📡 **Radar Actief** op `{token}`. Wachten op AI-sein.")
        
        while True:
            gas = w3.from_wei(w3.eth.gas_price, 'gwei')
            prompt = f"Architect. Gas: {gas:.2f}. Token: {token}. Antwoord UITSLUITEND met 'EXECUTE' of 'HOLD'."
            if "EXECUTE" in llm.invoke(prompt).content.strip().upper():
                await update.message.reply_text(f"⚡ **AI GEEFT GROEN LICHT!**")
                tx_hash = await execute_trade(token, eth_amt)
                await update.message.reply_text(f"✅ **Auto-Snipe Geslaagd.** UserOp: `{tx_hash}`\nGuardian overname (`{target}%`).")
                asyncio.create_task(profit_guardian(update, token, eth_amt, target))
                break 
            await asyncio.sleep(60) 
    except Exception as e:
        await update.message.reply_text(f"❌ **Radar Fout:** {e}")

# --- 5. STANDAARD COMMANDO'S ---

async def vault_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    await update.message.reply_chat_action("typing")
    vault_addr = await get_smart_vault_address()
    signer_bal = w3.from_wei(w3.eth.get_balance(architect_signer.address), 'ether') if architect_signer else 0
    vault_bal = w3.from_wei(w3.eth.get_balance(vault_addr), 'ether') if vault_addr and vault_addr.startswith("0x") else 0
    code = w3.eth.get_code(vault_addr) if vault_addr and vault_addr.startswith("0x") else b''
    status = "🟢 Actief" if code != b'' else "🟡 Counterfactual (Wacht op eerste trade)"
    
    await update.message.reply_text(f"🔐 **Chillzilla Smart Vault**\n\n**Signer:** `{architect_signer.address if architect_signer else 'Geen'}` ({signer_bal:.4f} ETH)\n**Vault:** `{vault_addr}`\n**Status:** {status}\n**Balans:** `{vault_bal:.4f} ETH`", parse_mode='Markdown')

async def trade_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    try:
        token, eth_amt, target = context.args[0], float(context.args[1]), float(context.args[2])
        tx_hash = await execute_trade(token, eth_amt)
        await update.message.reply_text(f"🚀 **Gekocht (Gasless)!** UserOp: `{tx_hash}`\nGuardian is actief voor `{target}%` winst.", parse_mode='Markdown')
        asyncio.create_task(profit_guardian(update, token, eth_amt, target))
    except Exception as e:
        await update.message.reply_text(f"❌ **Trade Fout:** {e}")

async def panic_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    try:
        token = context.args[0]
        await update.message.reply_text(f"⚠️ **PANIC MODE!** Alles liquideren...")
        tx = await execute_sell(token)
        if token in active_positions: del active_positions[token]
        await update.message.reply_text(f"🏁 **Nooduitgang voltooid.** UserOp: `{tx}`", parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"❌ **Panic Fout:** {e}")

async def skyline_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    await update.message.reply_chat_action("typing")
    try:
        gas = w3.from_wei(w3.eth.gas_price, 'gwei')
        vault_addr = await get_smart_vault_address()
        bal = w3.from_wei(w3.eth.get_balance(vault_addr), 'ether') if vault_addr else 0
        res = llm.invoke(f"Schrijf een vlijmscherp on-chain rapport. Gas: {gas:.4f} Gwei, Vault Balans: {bal:.4f} ETH.")
        await update.message.reply_text(f"🏙️ **Skyline Status**\n\n{res.content}\n\n⛽ Gas: `{gas:.4f}` | 💳 Vault: `{bal:.4f} ETH`", parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"❌ Skyline sensor fout: {e}")

# --- 6. FASTAPI & TELEGRAM RUNNER ---

async def run_bot():
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler("vault", vault_command))
    application.add_handler(CommandHandler("trade", trade_command))
    application.add_handler(CommandHandler("radar", radar_command))
    application.add_handler(CommandHandler("hunt", hunt_command))
    application.add_handler(CommandHandler("panic", panic_command))
    application.add_handler(CommandHandler("skyline", skyline_command))
    application.add_handler(CommandHandler("start", lambda u, c: u.message.reply_text("Architect Command Center Online.")))
    
    await application.initialize()
    await application.start()
    await application.updater.start_polling(drop_pending_updates=True)
    logger.info("🚀 Architect Telegram Bot is live met ERC-4337!")
    while True: await asyncio.sleep(3600)

app = FastAPI()

@app.on_event("startup")
async def startup():
    asyncio.create_task(run_bot())

@app.get("/")
async def health():
    return {"status": "active", "agent": "Synthora Architect ERC-4337"}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
    
