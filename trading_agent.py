# --- 1. IMPORTS & FUNDERING ---
import logging, os, asyncio, time
import httpx
from web3 import Web3
from eth_account import Account
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
architect_account = Account.from_key(private_key) if private_key else None
# Voor de duidelijkheid in de Smart Account logica hernoemen we hem ook even:
architect_signer = architect_account 

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

# --- 2. DE TRADE & WINST ENGINE ---

async def execute_trade(token_to_buy, amount_eth):
    current_gas = w3.from_wei(w3.eth.gas_price, 'gwei')
    if current_gas > GAS_LIMIT_GWEI:
        raise Exception(f"Gas te hoog: {current_gas:.4f} Gwei (Limiet: {GAS_LIMIT_GWEI})")

    amount_wei = w3.to_wei(amount_eth, 'ether')
    router = w3.eth.contract(address=AERODROME_ROUTER, abi=ROUTER_ABI)
    route = [{"from": WETH, "to": w3.to_checksum_address(token_to_buy), "stable": False, "factory": "0x4200000000000000000000000000000000000001"}]
    
    nonce = w3.eth.get_transaction_count(architect_account.address)
    tx = router.functions.swapExactETHForTokens(0, route, architect_account.address, int(time.time()) + 600).build_transaction({
        'from': architect_account.address, 'value': amount_wei, 'gas': 250000, 'gasPrice': w3.eth.gas_price, 'nonce': nonce, 'chainId': 8453
    })
    signed_tx = w3.eth.account.sign_transaction(tx, private_key)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
    return w3.to_hex(tx_hash)

async def execute_sell(token_addr):
    token_contract = w3.eth.contract(address=w3.to_checksum_address(token_addr), abi=ERC20_ABI)
    balance = token_contract.functions.balanceOf(architect_account.address).call()
    if balance == 0: return None
    
    token_contract.functions.approve(AERODROME_ROUTER, balance).transact({'from': architect_account.address})
    router = w3.eth.contract(address=AERODROME_ROUTER, abi=ROUTER_ABI)
    route = [{"from": w3.to_checksum_address(token_addr), "to": WETH, "stable": False, "factory": "0x4200000000000000000000000000000000000001"}]
    
    tx = router.functions.swapExactTokensForETH(balance, 0, route, architect_account.address, int(time.time()) + 600).build_transaction({
        'from': architect_account.address, 'nonce': w3.eth.get_transaction_count(architect_account.address), 'gas': 300000, 'gasPrice': w3.eth.gas_price, 'chainId': 8453
    })
    signed = w3.eth.account.sign_transaction(tx, private_key)
    return w3.to_hex(w3.eth.send_raw_transaction(signed.rawTransaction))

async def get_current_value(token_addr):
    token_contract = w3.eth.contract(address=w3.to_checksum_address(token_addr), abi=ERC20_ABI)
    bal = token_contract.functions.balanceOf(architect_account.address).call()
    if bal == 0: return 0
    router = w3.eth.contract(address=AERODROME_ROUTER, abi=ROUTER_ABI)
    route = [{"from": w3.to_checksum_address(token_addr), "to": WETH, "stable": False, "factory": "0x4200000000000000000000000000000000000001"}]
    amounts = router.functions.getAmountsOut(bal, route).call()
    return w3.from_wei(amounts[-1], 'ether')

async def profit_guardian(update, token_addr, entry_eth, target_pct):
    token_addr = w3.to_checksum_address(token_addr)
    active_positions[token_addr] = {"entry": entry_eth, "target": target_pct}
    
    while token_addr in active_positions:
        try:
            current_val = await get_current_value(token_addr)
            if current_val == 0: break 
            
            profit_pct = ((float(current_val) - float(entry_eth)) / float(entry_eth)) * 100
            
            if profit_pct >= target_pct and current_val > entry_eth:
                await update.message.reply_text(f"🎯 **Target Bereikt!** Winst: `{profit_pct:.2f}%`.\nExecutie verkoop...")
                tx = await execute_sell(token_addr)
                await update.message.reply_text(f"💰 **Pure Winst Verzilverd!**\nHash: [Basescan](https://basescan.org/tx/{tx})", parse_mode='Markdown')
                del active_positions[token_addr]
                break
            await asyncio.sleep(30)
        except Exception as e:
            logger.error(f"Guardian error: {e}")
            await asyncio.sleep(10)

# --- 3. COMMAND CENTER & SKYLINE RADAR ---

async def radar_scanner(update, token_addr, eth_amt, target_pct):
    await update.message.reply_text(f"📡 **Skyline Radar Geactiveerd.**\nToken `{token_addr[:8]}...` staat op de monitor voor Chillzilla. De AI zoekt de perfecte setup.")
    
    while True:
        try:
            gas = w3.from_wei(w3.eth.gas_price, 'gwei')
            prompt = (
                f"Je bent de meedogenloze trading-architect voor Chillzilla op Base. "
                f"De gas prijs is {gas:.4f} Gwei. We scannen token {token_addr}. "
                f"Is de markt gunstig voor een on-chain snipe? "
                f"Antwoord UITSLUITEND met 'EXECUTE' of 'HOLD'."
            )
            
            beslissing = llm.invoke(prompt).content.strip().upper()
            
            if "EXECUTE" in beslissing and gas <= GAS_LIMIT_GWEI:
                await update.message.reply_text(f"⚡ **AI GEEFT GROEN LICHT!** Executie gestart voor `{token_addr[:8]}...`")
                tx_hash = await execute_trade(token_addr, eth_amt)
                await update.message.reply_text(f"✅ **Auto-Snipe Geslaagd.** Hash: `{tx_hash}`\nDe Profit Guardian neemt het over voor `{target_pct}%` winst.")
                
                asyncio.create_task(profit_guardian(update, token_addr, eth_amt, target_pct))
                break 
                
            elif "EXECUTE" in beslissing and gas > GAS_LIMIT_GWEI:
                logger.info(f"AI wilde snipen op {token_addr}, maar Gas ({gas:.2f}) was te hoog.")
                
            await asyncio.sleep(60) 
            
        except Exception as e:
            logger.error(f"Radar error: {e}")
            await asyncio.sleep(30)

async def radar_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    try:
        token, eth_amt, target = context.args[0], float(context.args[1]), float(context.args[2])
        asyncio.create_task(radar_scanner(update, token, eth_amt, target))
    except Exception as e:
        await update.message.reply_text(f"❌ **Radar Setup Fout:** Gebruik `/radar [adres] [eth] [winst%]`")

async def trade_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    try:
        token, eth_amt, target = context.args[0], float(context.args[1]), float(context.args[2])
        tx_hash = await execute_trade(token, eth_amt)
        await update.message.reply_text(f"🚀 **Gekocht!** Hash: `{tx_hash}`\nDe Architect schaduwt nu de koers voor `{target}%` winst.", parse_mode='Markdown')
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
        await update.message.reply_text(f"🏁 **Nooduitgang voltooid.** Hash: `{tx}`", parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"❌ **Panic Fout:** {e}")

async def skyline_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    await update.message.reply_chat_action("typing")
    try:
        gas = w3.from_wei(w3.eth.gas_price, 'gwei')
        bal = w3.from_wei(w3.eth.get_balance(architect_account.address), 'ether')
        res = llm.invoke(f"Schrijf een vlijmscherp on-chain rapport. Gas: {gas:.4f} Gwei, Balans: {bal:.4f} ETH.")
        await update.message.reply_text(f"🏙️ **Skyline Status**\n\n{res.content}\n\n⛽ Gas: `{gas:.4f}` | 💳 Vault: `{bal:.4f} ETH`", parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"❌ Skyline sensor fout: {e}")

# --- 4. SMART VAULT LOGICA (ERC-4337) ---

async def get_smart_vault_address():
    if not architect_signer: return "Geen Signer Key gevonden."
    factory_abi = [{"inputs":[{"name":"owner","type":"address"},{"name":"salt","type":"uint256"}],"name":"getAddress","outputs":[{"name":"","type":"address"}],"stateMutability":"view","type":"function"}]
    factory_contract = w3.eth.contract(address=SIMPLE_ACCOUNT_FACTORY, abi=factory_abi)
    try:
        vault_address = factory_contract.functions.getAddress(architect_signer.address, 0).call()
        return vault_address
    except Exception as e:
        logger.error(f"Fout bij berekenen vault adres: {e}")
        return "Berekening mislukt"

async def vault_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    await update.message.reply_chat_action("typing")
    
    vault_addr = await get_smart_vault_address()
    signer_bal = w3.from_wei(w3.eth.get_balance(architect_signer.address), 'ether') if architect_signer else 0
    vault_bal = w3.from_wei(w3.eth.get_balance(vault_addr), 'ether') if vault_addr.startswith("0x") else 0
    
    code = w3.eth.get_code(vault_addr) if vault_addr.startswith("0x") else b''
    status = "🟢 Gedeployed (Actief)" if code != b'' else "🟡 Wacht op deployment (Counterfactual)"
    
    bericht = (
        f"🔐 **Chillzilla Smart Vault Status**\n\n"
        f"**Signer (Sleutelmeester):**\n"
        f"Adres: `{architect_signer.address if architect_signer else 'Ontbreekt'}`\n"
        f"Balans: `{signer_bal:.4f} ETH`\n\n"
        f"**Smart Vault (De Kluis):**\n"
        f"Adres: `{vault_addr}`\n"
        f"Status: {status}\n"
        f"Balans: `{vault_bal:.4f} ETH`\n\n"
        f"*(De Vault wordt on-chain gezet bij de eerste gasless trade via Pimlico.)*"
    )
    await update.message.reply_text(bericht, parse_mode='Markdown')

# --- 5. FASTAPI & TELEGRAM RUNNER ---

async def run_bot():
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler("trade", trade_command))
    application.add_handler(CommandHandler("radar", radar_command))
    application.add_handler(CommandHandler("panic", panic_command))
    application.add_handler(CommandHandler("skyline", skyline_command))
    application.add_handler(CommandHandler("vault", vault_command)) # Nieuw commando geregistreerd
    application.add_handler(CommandHandler("start", lambda u, c: u.message.reply_text("Architect Command Center Online.")))
    
    await application.initialize()
    await application.start()
    await application.updater.start_polling(drop_pending_updates=True)
    logger.info("🚀 Architect Telegram Bot is live!")
    while True: await asyncio.sleep(3600)

app = FastAPI()

@app.on_event("startup")
async def startup():
    asyncio.create_task(run_bot())

@app.get("/")
async def health():
    return {"status": "active", "agent": "Synthora Architect"}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
                
