import os
import asyncio
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# Blockchain & AI Imports
from langchain_openai import ChatOpenAI
from coinbase_agentkit import AgentKit, AgentKitValues
from coinbase_agentkit_langchain.utils import create_react_agent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- INITIALISATIE ---
def get_synthora():
    # OpenAI voor intelligentie en talen
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.2)
    
    # Coinbase Wallet Connectie
    agent_kit = AgentKit(AgentKitValues(
        cdp_api_key_name=os.getenv("CDP_API_KEY_NAME"),
        cdp_api_key_private_key=os.getenv("CDP_API_KEY_PRIVATE_KEY").replace('\\n', '\n'),
        network_id="base-mainnet"
    ))

    # De Agent die echt kan traden
    instructions = (
        "Je bent SYNTHORA, een professionele trading bot op Base. "
        "Reageer altijd in de taal van de gebruiker. "
        "Je kunt tokens swappen, balansen checken en prijzen opzoeken."
    )
    return create_react_agent(llm, agent_kit.get_tools(), state_modifier=instructions)

agent_executor = get_synthora()

# --- HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 SYNTHORA is live! Ik ben klaar om te traden op Base.")

async def handle_ai_trading(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Dit is de kern: hier stuurt de bot je tekst naar de AgentKit voor trades
    try:
        response = await agent_executor.ainvoke({"messages": [("user", update.message.text)]})
        await update.message.reply_text(response["messages"][-1].content)
    except Exception as e:
        logger.error(f"Trading Error: {e}")
        await update.message.reply_text("Oeps, er ging iets mis bij het uitvoeren van die actie op Base.")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⚡ Engine: Online | Base: Verbonden | Status: High-Speed")

# --- STARTUP (Fix voor Render) ---
async def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    # Gebruik de moderne ApplicationBuilder om crashen te voorkomen
    app = ApplicationBuilder().token(token).build()

    # Handlers koppelen
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('status', status))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_ai_trading))

    # De cruciale Render-fix
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    
    logger.info("🤖 SYNTHORA IS LIVE")
    
    # Houdt de bot actief zonder de CPU te overbelasten
    await asyncio.Event().wait()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
    
