# --- 1. BOVENAAN: DEFINITIEVE IMPORTS ---
import logging
import os
import asyncio
from fastapi import FastAPI
import uvicorn

# De specifieke paden voor AgentKit v0.7.4
from coinbase_agentkit import AgentKit, AgentKitConfig
from coinbase_agentkit.wallet_providers.cdp import CdpWalletProvider, CdpWalletProviderConfig
from coinbase_agentkit_langchain import get_langchain_tools

from langchain_openai import ChatOpenAI
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# --- CONFIGURATIE ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Synthora")

CDP_API_KEY_NAME = os.environ.get("CDP_API_KEY_NAME")
# New-line fix voor Render
CDP_PRIVATE_KEY = os.environ.get("CDP_API_KEY_PRIVATE_KEY", "").replace('\\n', '\n')
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
OWNER_ID = int(os.environ.get("OWNER_ID", 0))

# --- 2. DE AGENT INITIALISEREN ---
def setup_architect():
    if not all([CDP_API_KEY_NAME, CDP_PRIVATE_KEY, OPENAI_API_KEY]):
        logger.error("❌ Cruciale API keys missen in Render Environment Variables!")
        return None, None, None

    try:
        # Initialiseer de CDP Wallet Provider (Rechtstreeks op Base)
        wallet_provider = CdpWalletProvider(CdpWalletProviderConfig(
            api_key_id=CDP_API_KEY_NAME,
            api_key_secret=CDP_PRIVATE_KEY,
            network_id="base-mainnet"
        ))
        
        agent_kit = AgentKit(AgentKitConfig(wallet_provider=wallet_provider))
        
        # De hersenen van Synthora
        llm = ChatOpenAI(model="gpt-4o", api_key=OPENAI_API_KEY)
        
        return wallet_provider, agent_kit, llm
    except Exception as e:
        logger.error(f"❌ Initialisatiefout: {e}")
        return None, None, None

wallet, agent, llm = setup_architect()

# --- 3. COMMANDO'S ---

async def skyline_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toon on-chain balans en adres."""
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
        await update.message.reply_text(f"⚠️ On-chain data onbereikbaar: {str(e)}")

async def weekly_report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Secret Command: AI-analyse van de status."""
    if update.effective_user.id != OWNER_ID: return
    
    await update.message.reply_text("📊 **Secret Command: Genereer Skyline Report via AI...**")
    await update.message.reply_chat_action("typing")
    
    try:
        prompt = f"Je bent de Synthora Architect op Base. Wallet adres: {wallet.address if wallet else 'onbekend'}. Schrijf een kort, krachtig en professioneel wekelijks rapport over de status van de skyline."
        response = llm.invoke(prompt)
        await update.message.reply_text(f"📝 **OFFICIEEL SKYLINE REPORT**\n\n{response.content}", parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text("⚠️ AI-module kon het rapport niet voltooien.")

# --- 4. DE RUNNER ---
async def run_telegram_bot():
    if not TELEGRAM_TOKEN: return
    
    app_bot = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    # Handlers
    app_bot.add_handler(CommandHandler("start", lambda u, c: u.message.reply_text("🏗️ Architect Online.")))
    app_bot.add_handler(CommandHandler("skyline", skyline_command))
    app_bot.add_handler(CommandHandler("weekly_report", weekly_report_command))
    
    await app_bot.initialize()
    await app_bot.start()
    await app_bot.updater.start_polling()
    
    logger.info("🚀 Synthora Bot luistert nu op Telegram.")
    while True: await asyncio.sleep(3600)

app = FastAPI()

@app.get("/")
async def health(): return {"status": "online", "agent": "Synthora Architect"}

@app.on_event("startup")
async def startup_event():
    # Start bot in de achtergrond
    asyncio.create_task(run_telegram_bot())

if __name__ == "__main__":
    # Render poort configuratie
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
    
