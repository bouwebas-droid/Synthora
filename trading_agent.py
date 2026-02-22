import os
import asyncio
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# De juiste namen voor de imports
from langchain_openai import ChatOpenAI
from coinbase_agentkit import AgentKit, AgentKitValues
from coinbase_agentkit_langchain.utils import create_react_agent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- LITE ENGINE SETUP ---
def setup_engine():
    # Gebruik gpt-4o-mini: dit is de snelste 'brain' voor trading
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    
    # Wallet configuratie
    values = AgentKitValues(
        cdp_api_key_name=os.getenv("CDP_API_KEY_NAME"),
        cdp_api_key_private_key=os.getenv("CDP_API_KEY_PRIVATE_KEY").replace('\\n', '\n'),
        network_id="base-mainnet"
    )
    agent_kit = AgentKit(values)

    # Instructies voor meertaligheid en snelheid
    instructions = "You are SYNTHORA. Professional, lite, and multi-lingual. Respond in the user's language."
    
    return create_react_agent(llm, agent_kit.get_tools(), state_modifier=instructions)

# Agent één keer laden voor snelheid
agent_executor = setup_engine()

# --- HANDLERS ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # De AI herkent automatisch Nederlands, Engels, etc.
    try:
        user_input = update.message.text
        response = await agent_executor.ainvoke({"messages": [("user", user_input)]})
        await update.message.reply_text(response["messages"][-1].content)
    except Exception as e:
        logger.error(f"Error: {e}")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⚡ SYNTHORA Lite: Engine Online | Base: Connected")

# --- RENDER BOOTSTRAP ---
async def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    app = ApplicationBuilder().token(token).build()

    app.add_handler(CommandHandler('status', status))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

    # Fix voor de 'never awaited' errors in je logs
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    
    logger.info("SYNTHORA is gestart op Render.")
    await asyncio.Event().wait()

if __name__ == '__main__':
    asyncio.run(main())
    
