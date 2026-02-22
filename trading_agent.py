import os
import asyncio
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# AI & Blockchain
from langchain_openai import ChatOpenAI
from coinbase_agentkit import AgentKit, AgentKitValues
from coinbase_agentkit_langchain.utils import create_react_agent

# Importeer je eigen analyse-logica (zorg dat dit bestand in dezelfde map staat)
# We laden dit 'lite' in om geheugen te besparen
try:
    import technical_analysis as ta
except ImportError:
    ta = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- INITIALISATIE ---
def setup_synthora():
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.1)
    
    agent_kit = AgentKit(AgentKitValues(
        cdp_api_key_name=os.getenv("CDP_API_KEY_NAME"),
        cdp_api_key_private_key=os.getenv("CDP_API_KEY_PRIVATE_KEY").replace('\\n', '\n'),
        network_id="base-mainnet"
    ))

    instructions = (
        "Je bent SYNTHORA. Een professionele AI bot op Base. "
        "Je gebruikt Machine Learning (RandomForest) om trades te analyseren. "
        "Reageer altijd in de taal van de gebruiker."
    )
    return create_react_agent(llm, agent_kit.get_tools(), state_modifier=instructions)

agent_executor = setup_synthora()

# --- HANDLERS ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_text = update.message.text
        # De AI besluit nu of hij een trade moet doen of een analyse moet draaien
        response = await agent_executor.ainvoke({"messages": [("user", user_text)]})
        await update.message.reply_text(response["messages"][-1].content)
    except Exception as e:
        logger.error(f"Fout: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_msg = "✅ ML Engine geladen." if ta else "⚠️ ML Engine ontbreekt."
    await update.message.reply_text(f"⚡ SYNTHORA Online.\n{status_msg}\nHoe kan ik je helpen op Base?")

# --- RENDER LOOP ---
async def main():
    app = ApplicationBuilder().token(os.getenv("TELEGRAM_BOT_TOKEN")).build()
    app.add_handler(CommandHandler('start', start))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    
    logger.info("SYNTHORA LIVE")
    await asyncio.Event().wait()

if __name__ == '__main__':
    asyncio.run(main())
    
    
