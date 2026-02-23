# --- 1. BOVENAAN: INTELLIGENTE IMPORTS ---
import logging
import os
import asyncio
from fastapi import FastAPI
import uvicorn

# Dynamische import-zoeker voor de Architect
try:
    from coinbase_agentkit.wallet_providers.cdp_wallet_provider import CdpWalletProvider, CdpWalletProviderConfig
    import_status = "Pad A succesvol"
except ImportError:
    try:
        from coinbase_agentkit.wallet_providers.cdp import CdpWalletProvider, CdpWalletProviderConfig
        import_status = "Pad B succesvol"
    except ImportError:
        from coinbase_agentkit import CdpWalletProvider, CdpWalletProviderConfig
        import_status = "Pad C succesvol"

from coinbase_agentkit import AgentKit, AgentKitConfig
from coinbase_agentkit_langchain import get_langchain_tools
from langchain_openai import ChatOpenAI
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# --- CONFIGURATIE ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Synthora")
logger.info(f"✅ Architect-module geladen via: {import_status}")

# API Keys uit Render Environment
CDP_API_KEY_NAME = os.environ.get("CDP_API_KEY_NAME")
# De .replace zorgt dat de private key met \n goed gelezen wordt
CDP_PRIVATE_KEY = os.environ.get("CDP_API_KEY_PRIVATE_KEY", "").replace('\\n', '\n')
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
OWNER_ID = int(os.environ.get("OWNER_ID", 0))

# --- 2. DE AGENT INITIALISEREN ---
def setup_architect():
    if not all([CDP_API_KEY_NAME, CDP_PRIVATE_KEY, OPENAI_API_KEY]):
        logger.error("❌ Cruciale API keys missen!")
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

# --- 3. COMMANDO'S ---

async def skyline_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toon on-chain balans via CDP."""
    if update.effective_user.id != OWNER_ID: return
    await update.message.reply_chat_action("typing")
    try:
        balance = wallet.balance("eth")
        addr = wallet.address
        await update.message.reply_text(
            f"🏙️ **Synthora Skyline Report**\n📍 Adres: `{addr}`\n💳 Balans: `{balance} ETH`", 
            parse_mode='Markdown'
        )
    except Exception as e:
        await update.message.reply_text(f"⚠️ Scan mislukt: {str(e)}")

async def weekly_report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Secret Command: AI Skyline Report."""
    if update.effective_user.id != OWNER_ID: return
    await update.message.reply_text("📊 **Genereren van Weekly Skyline Report...**")
    await update.message.reply_chat_action("typing")
    try:
        prompt = f"Je bent de Synthora Architect op Base. Wallet: {wallet.address}. Schrijf een kort, technisch weekoverzicht voor de eigenaar."
        response = llm.invoke(prompt)
        await update.message.reply_text(f"📝 **OFFICIEEL RAPPORT**\n\n{response.content}", parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text("⚠️ AI-module offline.")

# --- 4. DE RUNNER ---
async def run_telegram_bot():
    if not TELEGRAM_TOKEN: return
    app_bot = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    app_bot.add_handler(CommandHandler("start", lambda u, c: u.message.reply_text("🏗️ Architect Online.")))
    app_bot.add_handler(CommandHandler("skyline", skyline_command))
    app_bot.add_handler(CommandHandler("weekly_report", weekly_report_command))
    
    await app_bot.initialize()
    await app_bot.start()
    await app_bot.updater.start_polling()
    logger.info("🚀 Synthora is actief op Telegram.")
    while True: await asyncio.sleep(3600)

app = FastAPI()

@app.get("/")
async def health(): return {"status": "online", "agent": "Synthora Architect"}

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(run_telegram_bot())

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
    
