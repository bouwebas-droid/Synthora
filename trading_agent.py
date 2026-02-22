 import os
import asyncio
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# We laden de zware jongens alleen als het echt moet
from langchain_openai import ChatOpenAI
from coinbase_agentkit import AgentKit, AgentKitValues
from coinbase_agentkit_langchain.utils import create_react_agent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- 1. DE AI ENGINE (LITE & SNEL) ---
def setup_agent():
    # Gebruik gpt-4o-mini voor snelheid en alle talen
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.2)
    
    # Haal keys uit Render Secrets
    values = AgentKitValues(
        cdp_api_key_name=os.getenv("CDP_API_KEY_NAME"),
        cdp_api_key_private_key=os.getenv("CDP_API_KEY_PRIVATE_KEY").replace('\\n', '\n'),
        network_id="base-mainnet"
    )
    agent_kit = AgentKit(values)

    # Instructies voor Synthora
    instructions = "You are SYNTHORA. A professional trading agent on Base. Answer in the user's language."
    
    return create_react_agent(llm, agent_kit.get_tools(), state_modifier=instructions)

# We maken de agent één keer aan
agent_executor = setup_agent()

# --- 2. DE HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 SYNTHORA is live. Ik ben je AI Agent op Base.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Dit is de AI-schil die automatisch Nederlands herkent
    try:
        user_text = update.message.text
        response = await agent_executor.ainvoke({"messages": [("user", user_text)]})
        await update.message.reply_text(response["messages"][-1].content)
    except Exception as e:
        logger.error(f"Fout: {e}")

# --- 3. DE GEHEIME ARCHITECT COMMANDS ---
async def skyline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Alleen voor jou als eigenaar
    if str(update.effective_user.id) == os.getenv("OWNER_ID"):
        await update.message.reply_text("📊 Architect, ik genereer nu het Skyline Report...")
        res = await agent_executor.ainvoke({"input": "Geef een wekelijks overzicht van de wallet activiteit."})
        await update.message.reply_text(res["messages"][-1].content)

# --- 4. DE STABIELE STARTUP (FIX VOOR RENDER) ---
async def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN NIET GEVONDEN!")
        return

    # Bouw de app
    app = ApplicationBuilder().token(token).build()

    # Handlers toevoegen
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('skyline', skyline))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

    # DEZE STAPPEN ZIJN CRUCIAAL VOOR RENDER (Lost de RuntimeError op)
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    
    logger.info("🤖 SYNTHORA IS LIVE")
    
    # Houdt de loop levend
    await asyncio.Event().wait()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
    
