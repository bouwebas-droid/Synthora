import logging
import os
import asyncio
from fastapi import FastAPI
import uvicorn

# Gecorrigeerde imports voor versie 0.7.4
from coinbase_agentkit import AgentKit, AgentKitConfig
from coinbase_agentkit.wallet_providers.cdp_wallet_provider import CdpWalletProvider, CdpWalletProviderConfig
from coinbase_agentkit_langchain import get_langchain_tools

from langchain_openai import ChatOpenAI
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# --- CONFIGURATIE ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Synthora")

CDP_API_KEY_NAME = os.environ.get("CDP_API_KEY_NAME")
# De .replace zorgt dat de private key altijd goed gelezen wordt door Python op Render
CDP_PRIVATE_KEY = os.environ.get("CDP_API_KEY_PRIVATE_KEY", "").replace('\\n', '\n')
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
OWNER_ID = int(os.environ.get("OWNER_ID", 0))

# --- 2. AGENT INITIALISATIE ---
def setup_architect():
    if not all([CDP_API_KEY_NAME, CDP_PRIVATE_KEY, OPENAI_API_KEY]):
        logger.warning("⚠️ Sleutels missen in Environment Variables!")
        return None, None, None

    wallet_provider = CdpWalletProvider(CdpWalletProviderConfig(
        api_key_id=CDP_API_KEY_NAME,
        api_key_secret=CDP_PRIVATE_KEY,
        network_id="base-mainnet"
    ))
    
    agent_kit = AgentKit(AgentKitConfig(wallet_provider=wallet_provider))
    llm = ChatOpenAI(model="gpt-4o", api_key=OPENAI_API_KEY)
    
    return wallet_provider, agent_kit, llm

wallet, agent, llm = setup_architect()

# --- 3. TELEGRAM INTERFACE ---
async def skyline_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    await update.message.reply_chat_action("typing")
    try:
        balance = wallet.balance("eth") if wallet else "N/A"
        addr = wallet.address if wallet else "N/A"
        await update.message.reply_text(
            f"🏙️ **Synthora Skyline Report**\n📍 Adres: `{addr}`\n💳 Balans: `{balance} ETH`", 
            parse_mode='Markdown'
        )
    except Exception as e:
        await update.message.reply_text(f"⚠️ Fout bij on-chain scan: {str(e)}")

# --- 4. RUNNER ---
async def run_telegram_bot():
    if not TELEGRAM_TOKEN: return
    app_bot = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app_bot.add_handler(CommandHandler("start", lambda u, c: u.message.reply_text("Architect Online.")))
    app_bot.add_handler(CommandHandler("skyline", skyline_command))
    
    await app_bot.initialize()
    await app_bot.start()
    await app_bot.updater.start_polling()
    
    logger.info("[SYSTEM] Synthora Bot is actief op Telegram.")
    while True: await asyncio.sleep(3600)

app = FastAPI()

@app.get("/")
async def health(): return {"status": "online", "agent": "Synthora"}

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(run_telegram_bot())

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
    
