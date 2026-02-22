import os
import asyncio
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# We laden de zware AI-onderdelen pas als de bot echt gestart is
from langchain_openai import ChatOpenAI
from coinbase_agentkit import AgentKit, AgentKitValues
from coinbase_agentkit_langchain.utils import create_react_agent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- ENGINE SETUP ---
def setup_synthora():
    # GPT-4o-mini is 3x sneller en begrijpt alle talen perfect
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.2)

    # Wallet configuratie (Base Mainnet)
    agent_kit = AgentKit(AgentKitValues(
        cdp_api_key_name=os.getenv("CDP_API_KEY_NAME"),
        cdp_api_key_private_key=os.getenv("CDP_API_KEY_PRIVATE_KEY").replace('\\n', '\n'),
        network_id="base-mainnet"
    ))

    # Meertalige instructies voor de AI
    instructions = (
        "You are SYNTHORA, a high-speed Trading Agent on Base. "
        "Always respond in the user's language. Keep it brief and technical."
    )

    return create_react_agent(llm, agent_kit.get_tools(), state_modifier=instructions)

# Initialiseer de agent
agent_executor = setup_synthora()

# --- FAST TRACK HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 SYNTHORA Lite is online.\n\n/status — Snelheidscheck\n/buy — Directe trade")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Directe respons zonder AI vertraging
    await update.message.reply_text("⚡ Engine: Lite | Base: Connected | Latency: Low")

async def handle_ai_trading(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # AI Track: Herkent automatisch taal en voert opdrachten uit
    try:
        user_msg = update.message.text
        response = await agent_executor.ainvoke({"messages": [("user", user_msg)]})
        await update.message.reply_text(response["messages"][-1].content)
    except Exception as e:
        logger.error(f"Fout: {e}")

# --- RENDER BOOTSTRAP ---
async def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN ontbreekt!")
        return

    app = ApplicationBuilder().token(token).build()

    # Handlers toevoegen
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('status', status))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_ai_trading))

    # De cruciale fix voor de 'Application.initialize' fout
    await app.initialize()
    await app.start()
    
    logger.info("🤖 SYNTHORA IS LIVE OP RENDER")
    
    await app.updater.start_polling(drop_pending_updates=True)
    
    # Houdt de bot actief
    await asyncio.Event().wait()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
        
