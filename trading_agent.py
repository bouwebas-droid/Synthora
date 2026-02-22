import os
import asyncio
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# AI & Blockchain Imports
from langchain_openai import ChatOpenAI
from coinbase_agentkit import AgentKit, AgentKitValues
from coinbase_agentkit_langchain.utils import create_react_agent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- ENGINE SETUP ---
def setup_synthora():
    # gpt-4o-mini is razendsnel en meertalig
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.1)
    
    # Wallet configuratie (Base Mainnet)
    agent_kit = AgentKit(AgentKitValues(
        cdp_api_key_name=os.getenv("CDP_API_KEY_NAME"),
        cdp_api_key_private_key=os.getenv("CDP_API_KEY_PRIVATE_KEY").replace('\\n', '\n'),
        network_id="base-mainnet"
    ))

    # Instructies: Synthora past zich aan de taal van de gebruiker aan
    instructions = (
        "Je bent SYNTHORA, een professionele AI Trading Agent op Base. "
        "Reageer altijd in de taal van de gebruiker. Wees technisch en kort."
    )

    return create_react_agent(llm, agent_kit.get_tools(), state_modifier=instructions)

# Agent één keer laden
agent_executor = setup_synthora()

# --- HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⚡ SYNTHORA Online. Hoe kan ik je helpen op Base?")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Engine: Lite | Base: Verbonden | Status: Optimaal")

async def handle_ai(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Dit zorgt dat de bot reageert op "Hallo" en vragen
    try:
        user_msg = update.message.text
        response = await agent_executor.ainvoke({"messages": [("user", user_msg)]})
        await update.message.reply_text(response["messages"][-1].content)
    except Exception as e:
        logger.error(f"Fout: {e}")

# SECRET COMMAND (Alleen voor jou)
async def skyline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) == os.getenv("OWNER_ID"):
        await update.message.reply_text("📊 Architect, ik stel het Skyline Report op...")
        res = await agent_executor.ainvoke({"input": "Geef een wekelijks overzicht van de wallet activiteit."})
        await update.message.reply_text(res["messages"][-1].content)

# --- STARTUP ---
async def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    app = ApplicationBuilder().token(token).build()

    # Handlers koppelen
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('status', status))
    app.add_handler(CommandHandler('skyline', skyline))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_ai))

    # Cruciaal voor Render stabiliteit
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    
    logger.info("🤖 SYNTHORA IS LIVE")
    await asyncio.Event().wait()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
    
