import os
import asyncio
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# We laden alleen wat strikt noodzakelijk is voor de start
from langchain_openai import ChatOpenAI
from coinbase_agentkit import AgentKit, AgentKitValues
from coinbase_agentkit_langchain.utils import create_react_agent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def run_synthora():
    # 1. SETUP: Gebruik gpt-4o-mini voor snelheid en talen
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    
    agent_kit = AgentKit(AgentKitValues(
        cdp_api_key_name=os.getenv("CDP_API_KEY_NAME"),
        cdp_api_key_private_key=os.getenv("CDP_API_KEY_PRIVATE_KEY").replace('\\n', '\n'),
        network_id="base-mainnet"
    ))

    # Meertalige instructie
    instructions = "You are SYNTHORA. Answer in the user's language. Be fast and professional."
    agent_executor = create_react_agent(llm, agent_kit.get_tools(), state_modifier=instructions)

    # 2. TELEGRAM HANDLERS
    async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
        # AI Track
        try:
            response = await agent_executor.ainvoke({"messages": [("user", update.message.text)]})
            await update.message.reply_text(response["messages"][-1].content)
        except Exception as e:
            logger.error(f"Error: {e}")

    # 3. INITIALISATIE (Dit lost je logs op!)
    # We gebruiken de officiële Telegram ApplicationBuilder
    app = ApplicationBuilder().token(os.getenv("TELEGRAM_BOT_TOKEN")).build()
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

    # DE CRUCIALE FIX VOOR JOUW LOGS:
    await app.initialize() # <--- Dit is wat je screenshot vroeg!
    await app.start()
    
    logger.info("🤖 SYNTHORA LITE IS LIVE")
    
    # Start polling
    await app.updater.start_polling(drop_pending_updates=True)
    
    # Houdt de loop open op Render
    try:
        await asyncio.Event().wait()
    finally:
        await app.shutdown() # <--- Netjes afsluiten

if __name__ == '__main__':
    try:
        asyncio.run(run_synthora())
    except (KeyboardInterrupt, SystemExit):
        pass
        
