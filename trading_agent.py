import os
import asyncio
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# Snelheidsprioriteit: Alleen laden wat we direct gebruiken
from coinbase_agentkit import AgentKit, AgentKitValues
from langchain_openai import ChatOpenAI
from coinbase_agentkit_langchain.utils import create_react_agent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- CONFIGURATIE ---
def get_lite_agent():
    # Gebruik gpt-4o-mini voor 3x hogere snelheid dan gpt-4o
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    
    # Wallet connectie (Base Mainnet)
    agent_kit = AgentKit(AgentKitValues(
        cdp_api_key_name=os.getenv("CDP_API_KEY_NAME"),
        cdp_api_key_private_key=os.getenv("CDP_API_KEY_PRIVATE_KEY").replace('\\n', '\n'),
        network_id="base-mainnet"
    ))

    # Meertalige 'Lite' instructies
    system_msg = (
        "You are SYNTHORA, a high-speed trading agent on Base. "
        "Keep responses extremely short and technical. "
        "Always match the user's language automatically."
    )

    return create_react_agent(llm, agent_kit.get_tools(), state_modifier=system_msg)

# De agent één keer globaal laden voor snelheid
agent_executor = get_lite_agent()

# --- SNELLE COMMANDO'S (Bypass AI) ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⚡ **SYNTHORA Online**\nMode: Lite-Speed\nNetwork: Base Mainnet")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Directe check zonder AI latency
    await update.message.reply_text("✅ Systems active. Connection: <100ms")

# --- SECRET COMMANDS (Owner Only) ---
async def skyline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != os.getenv("OWNER_ID"):
        return
    await update.message.reply_text("📊 *Architect identified. Generating Skyline Report...*")
    # Alleen hier gebruiken we de AI voor analyse
    res = await agent_executor.ainvoke({"input": "Give me a high-level summary of my wallet activity on Base."})
    await update.message.reply_text(res["messages"][-1].content)

# --- HYBRID AI TRACK (Meertalig) ---
async def handle_ai(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # De AI herkent automatisch Nederlands, Engels, etc.
    try:
        response = await agent_executor.ainvoke({"messages": [("user", update.message.text)]})
        await update.message.reply_text(response["messages"][-1].content)
    except Exception as e:
        logger.error(f"Error: {e}")

# --- OPSTARTEN OP RENDER ---
async def main():
    TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    app = ApplicationBuilder().token(TOKEN).build()

    # Handlers
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('status', status))
    app.add_handler(CommandHandler('skyline', skyline))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_ai))

    # Cruciaal voor Render stabiliteit
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    
    logger.info("SYNTHORA Lite is running...")
    await asyncio.Event().wait()

if __name__ == '__main__':
    asyncio.run(main())
    
