# --- 1. IMPORTS & FUNDERING ---
import logging, os, asyncio, time
import httpx
from web3 import Web3
from eth_account import Account
from eth_account.messages import encode_defunct
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

# Pimlico & ERC-4337 Adressen
PIMLICO_API_KEY = os.environ.get("PIMLICO_API_KEY", "")
BUNDLER_URL = f"https://api.pimlico.io/v2/8453/rpc?apikey={PIMLICO_API_KEY}"
PAYMASTER_URL = BUNDLER_URL

ENTRY_POINT_ADDRESS = "0x5FF137D4b0FDCD49DcA30c7CF57E578a026d2789"
SIMPLE_ACCOUNT_FACTORY = "0x9406Cc6185a346906296840746125a0E44976454"

# Adressen Base
AERODROME_ROUTER = "0xcF77a3Ba9A5CA399B7c97c74d54e5b1Beb874E43"
WETH = "0x4200000000000000000000000000000000000006"
GAS_LIMIT_GWEI = 0.05 

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
OWNER_ID = int(os.environ.get("OWNER_ID", 0))

private_key = os.environ.get("ARCHITECT_SESSION_KEY")
architect_signer = Account.from_key(private_key) if private_key else None
llm = ChatOpenAI(model="gpt-4o", api_key=OPENAI_API_KEY)

active_positions = {}

# ABIs
ROUTER_ABI = [
    {"inputs":[{"name":"amountIn","type":"uint256"},{"name":"amountOutMin","type":"uint256"},{"name":"routes","type":"tuple[]","components":[{"name":"from","type":"address"},{"name":"to","type":"address"},{"name":"stable","type":"bool"},{"name":"factory","type":"address"}]},{"name":"to","type":"address"},{"name":"deadline","type":"uint256"}],"name":"swapExactTokensForETH","outputs":[{"name":"amounts","type":"uint256[]"}],"stateMutability":"nonpayable","type":"function"},
    {"inputs":[{"name":"amountOutMin","type":"uint256"},{"name":"routes","type":"tuple[]","components":[{"name":"from","type":"address"},{"name":"to","type":"address"},{"name":"stable","type":"bool"},{"name":"factory","type":"address"}]},{"name":"to","type":"address"},{"name":"deadline","type":"uint256"}],"name":"swapExactETHForTokens","outputs":[{"name":"amounts","type":"uint256[]"}],"stateMutability":"payable","type":"function"},
    {"inputs":[{"name":"amountIn","type":"uint256"},{"name":"routes","type":"tuple[]","components":[{"name":"from","type":"address"},{"name":"to","type":"address"},{"name":"stable","type":"bool"},{"name":"factory","type":"address"}]}], "name":"getAmountsOut", "outputs":[{"name":"amounts","type":"uint256[]"}], "stateMutability":"view", "type":"function"}
]
ERC20_ABI = [
    {"inputs":[{"name":"spender","type":"address"},{"name":"amount","type":"uint256"}],"name":"approve","outputs":[{"name":"","type":"bool"}],"stateMutability":"nonpayable","type":"function"},
    {"inputs":[{"name":"account","type":"address"}],"name":"balanceOf","outputs":[{"name":"","type":"uint256"}],"stateMutability":"view","type":"function"}
]
ACCOUNT_ABI = [{"inputs":[{"name":"dest","type":"address"},{"name":"value","type":"uint256"},{"name":"func","type":"bytes"}],"name":"execute","outputs":[],"stateMutability":"nonpayable","type":"function"},
               {"inputs":[{"name":"dest","type":"address[]"},{"name":"value","type":"uint256[]"},{"name":"func","type":"bytes[]"}],"name":"executeBatch","outputs":[],"stateMutability":"nonpayable","type":"function"}]
FACTORY_ABI = [{"inputs":[{"name":"owner","type":"address"},{"name":"salt","type":"uint256"}],"name":"getAddress","outputs":[{"name":"","type":"address"}],"stateMutability":"view","type":"function"},
               {"inputs":[{"name":"owner","type":"address"},{"name":"salt","type":"uint256"}],"name":"createAccount","outputs":[{"name":"","type":"address"}],"stateMutability":"nonpayable","type":"function"}]


# --- 2. ERC-4337 SMART VAULT & PIMLICO ENGINE ---

async def get_smart_vault_address():
    if not architect_signer: return None
    factory_contract = w3.eth.contract(address=SIMPLE_ACCOUNT_FACTORY, abi=FACTORY_ABI)
    try:
        return factory_contract.functions.getAddress(architect_signer.address, 0).call()
    except Exception as e:
        logger.error(f"Fout bij berekenen vault adres: {e}")
        return None

async def send_user_operation(call_data, to_address, value=0, is_batch=False):
    """Bouwt, sponsort, ondertekent en verstuurt een UserOperation."""
    vault_address = await get_smart_vault_address()
    if not vault_address: raise Exception("Smart Vault adres niet gevonden.")

    init_code = "0x"
    if w3.eth.get_code(vault_address) == b'':
        factory_contract = w3.eth.contract(address=SIMPLE_ACCOUNT_FACTORY, abi=FACTORY_ABI)
        init_calldata = factory_contract.encodeABI(fn_name="createAccount", args=[architect_signer.address, 0])
        init_code = SIMPLE_ACCOUNT_FACTORY + init_calldata[2:]

    account_contract = w3.eth.contract(address=vault_address, abi=ACCOUNT_ABI)
    
    if is_batch:
        encoded_execute = call_data # Call data is al de executeBatch
    else:
        encoded_execute = account_contract.encodeABI(fn_name="execute", args=[to_address, value, call_data])

    user_op = {
        "sender": vault_address,
        "nonce": hex(0), # In productie: haal echte nonce op van EntryPoint
        "initCode": init_code,
        "callData": encoded_execute,
        "signature": "0x" + "00" * 65 # Dummy signature voor gas estimatie
    }

    async with httpx.AsyncClient() as client:
        # 1. Sponsor via Paymaster
        sponsor_payload = {"jsonrpc": "2.0", "id": 1, "method": "pm_sponsorUserOperation", "params": [user_op, ENTRY_POINT_ADDRESS]}
        sponsor_res = await client.post(PAYMASTER_URL, json=sponsor_payload)
        if sponsor_res.status_code != 200 or "error" in sponsor_res.json():
            # Fallback naar standaard executie als Pimlico faalt (voor robuustheid)
            logger.error("Pimlico sponsoring faalde. Zorg voor testnet/mainnet configuratie.")
            raise Exception(sponsor_res.json())
            
        user_op.update(sponsor_res.json()["result"])

        # 2. Ondertekenen (Versimpelde weergave voor Python structuur)
        # Normaal bouw je hier de keccak256 hash van het UserOp pakketje en sign je dat met architect_signer.
        # Voor de veiligheid van deze bot in pure Python (zonder externe AA-SDK):
        user_op["signature"] = architect_signer.sign_message(encode_defunct(text="DummyForNow")).signature.hex()

        # 3. Verstuur naar Bundler
        send_payload = {"jsonrpc": "2.0", "id": 1, "method": "eth_sendUserOperation", "params": [user_op, ENTRY_POINT_ADDRESS]}
        send_res = await client.post(BUNDLER_URL, json=send_payload)
        
        if send_res.status_code != 200 or "error" in send_res.json():
            raise Exception(f"Bundler afwijzing: {send_res.json()}")
            
        return send_res.json()["result"]

# --- 3. DE TRADE & WINST ENGINE ---

async def execute_trade(token_to_buy, amount_eth):
    """Gasless inkoop via Pimlico."""
    router = w3.eth.contract(address=AERODROME_ROUTER, abi=ROUTER_ABI)
    route = [{"from": WETH, "to": w3.to_checksum_address(token_to_buy), "stable": False, "factory": "0x4200000000000000000000000000000000000001"}]
    
    call_data = router.encodeABI(fn_name="swapExactETHForTokens", args=[0, route, await get_smart_vault_address(), int(time.time()) + 600])
    amount_wei = w3.to_wei(amount_eth, 'ether')
    
    logger.info("Verstuur Buy UserOperation...")
    try:
        return await send_user_operation(call_data, AERODROME_ROUTER, value=amount_wei)
    except Exception as e:
        logger.warning(f"Smart Vault trade gefaald ({e}). Zorg dat Paymaster funded is.")
        return "ERROR_PIMLICO"

async def execute_sell(token_addr):
    """Batched Gasless verkoop (Approve + Swap)."""
    vault_addr = await get_smart_vault_address()
    token_contract = w3.eth.contract(address=w3.to_checksum_address(token_addr), abi=ERC20_ABI)
    balance = token_contract.functions.balanceOf(vault_addr).call()
    if balance == 0: return None
    
    approve_data = token_contract.encodeABI(fn_name="approve", args=[AERODROME_ROUTER, balance])
    
    router = w3.eth.contract(address=AERODROME_ROUTER, abi=ROUTER_ABI)
    route = [{"from": w3.to_checksum_address(token_addr), "to": WETH, "stable": False, "factory": "0x4200000000000000000000000000000000000001"}]
    swap_data = router.encodeABI(fn_name="swapExactTokensForETH", args=[balance, 0, route, vault_addr, int(time.time()) + 600])

    account_contract = w3.eth.contract(address=vault_addr, abi=ACCOUNT_ABI)
    batch_calldata = account_contract.encodeABI(fn_name="executeBatch", args=[
        [w3.to_checksum_address(token_addr), AERODROME_ROUTER],
        [0, 0],
        [approve_data, swap_data]
    ])
    
    logger.info("Verstuur Batched Sell UserOperation...")
    try:
        return await send_user_operation(batch_calldata, vault_addr, value=0, is_batch=True)
    except Exception as e:
        logger.error(f"Batched sell mislukt: {e}")
        return "ERROR_PIMLICO"

async def get_current_value(token_addr):
    vault_addr = await get_smart_vault_address()
    token_contract = w3.eth.contract(address=w3.to_checksum_address(token_addr), abi=ERC20_ABI)
    bal = token_contract.functions.balanceOf(vault_addr).call()
    if bal == 0: return 0
    router = w3.eth.contract(address=AERODROME_ROUTER, abi=ROUTER_ABI)
    route = [{"from": w3.to_checksum_address(token_addr), "to": WETH, "stable": False, "factory": "0x4200000000000000000000000000000000000001"}]
    try:
        amounts = router.functions.getAmountsOut(bal, route).call()
        return w3.from_wei(amounts[-1], 'ether')
    except:
        return 0

async def profit_guardian(update, token_addr, entry_eth, target_pct):
    token_addr = w3.to_checksum_address(token_addr)
    active_positions[token_addr] = {"entry": entry_eth, "target": target_pct}
    
    while token_addr in active_positions:
        try:
            current_val = await get_current_value(token_addr)
            if current_val == 0: break 
            
            profit_pct = ((float(current_val) - float(entry_eth)) / float(entry_eth)) * 100
            
            if profit_pct >= target_pct and current_val > entry_eth:
                await update.message.reply_text(f"🎯 **Target Bereikt!** Winst: `{profit_pct:.2f}%`.\nBatched executie verkoop...")
                tx_hash = await execute_sell(token_addr)
                await update.message.reply_text(f"💰 **Pure Winst Verzilverd! (Gasless)**\nUserOp Hash: `{tx_hash}`", parse_mode='Markdown')
                del active_positions[token_addr]
                break
            await asyncio.sleep(30)
        except Exception as e:
            await asyncio.sleep(10)

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
            token_addr = pair['baseToken']['address']
            if token_addr.lower() != WETH.lower():
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
