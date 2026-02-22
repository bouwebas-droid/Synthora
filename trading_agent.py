import os
import asyncio
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# Stabiele imports voor Wallet & AI
from coinbase_agentkit import AgentKit, AgentKitConfig
from coinbase_agentkit_langchain.utils import create_react_agent
from langchain_openai import ChatOpenAI

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- 1. VEILIGE WALLET SETUP ---
def setup_synthora():
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

    # De bot haalt je CDP keys veilig uit de Render omgeving
    agent_kit = AgentKit(AgentKitConfig(
        network_id="base-mainnet"
    ))

    # Instructies voor de bot (Trade focus)
    instructions = (
        "Je bent SYNTHORA. Je beheert een wallet op Base Mainnet. "
        "Je voert swaps en trades uit wanneer de geautoriseerde eigenaar dat vraagt. "
        "Wees uiterst precies met getallen en bedragen."
    )

    return create_react_agent(llm, agent_kit.get_tools(), state_modifier=instructions)

agent_executor = setup_synthora()

# --- 2. BEVEILIGINGSFILTER ---
def is_owner(update: Update):
    # Controleert of het bericht van jouw Telegram ID komt
    return str(update.effective_user.id) == os.getenv("OWNER_ID")

# --- 3. HANDLERS MET BEVEILIGING ---
async def handle_secure_trade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Alleen de eigenaar kan traden
    if not is_owner(update):
        await update.message.reply_text("⛔ Toegang geweigerd. Alleen de Architect kan trades uitvoeren.")
        return

    try:
        user_input = update.message.text
        # Voer de trade uit via de AI en Wallet integratie
        response = await agent_executor.ainvoke({"messages": [("user", user_input)]})
        await update.message.reply_text(response["messages"][-1].content)
    except Exception as e:
        logger.error(f"Trading Fout: {e}")
        await update.message.reply_text("De transactie kon niet worden voltooid op Base.")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status = "Beveiligd (Architect Mode)" if is_owner(update) else "Public Mode"
    await update.message.reply_text(f"⚡ **SYNTHORA v2.0 Live**\nStatus: {status}\n\nGeef een handelsopdracht op Base.")

# --- 4. STARTUP ---
async def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    app = ApplicationBuilder().token(token).build()

    app.add_handler(CommandHandler('start', start))
    # Alle tekstberichten gaan door de beveiligde handelsfilter
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_secure_trade))

    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    
    logger.info("🤖 SYNTHORA SECURE ENGINE LIVE")
    await asyncio.Event().wait()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
        
