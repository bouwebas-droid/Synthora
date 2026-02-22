import os
import asyncio
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# Strikt noodzakelijke imports voor de engine
from langchain_openai import ChatOpenAI
from coinbase_agentkit import AgentKit, AgentKitValues
from coinbase_agentkit_langchain.utils import create_react_agent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- LITE AI ENGINE ---
def get_synthora_engine():
    # gpt-4o-mini is razendsnel en meertalig
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.1)
    
    # Haal de keys op uit Render Secrets
    agent_kit = AgentKit(AgentKitValues(
        cdp_api_key_name=os.getenv("CDP_API_KEY_NAME"),
        cdp_api_key_private_key=os.getenv("CDP_API_KEY_PRIVATE_KEY").replace('\\n', '\n'),
        network_id="base-mainnet"
    ))

    # Meertalige instructies
    instructions = "You are SYNTHORA. A high-speed Base trading agent. Respond in the user's language."
    return create_react_agent(llm, agent_kit.get_tools(), state_modifier=instructions)

# We laden de agent pas als we hem echt nodig hebben (Lazy Loading)
agent_executor = None

# --- HANDLERS ---
async def handle_any_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global agent_executor
    if agent_executor is None:
        agent_executor = get_synthora_engine()
    
    try:
        # OpenAI herkent automatisch de taal (NL, EN, etc.)
        user_input = update.message.text
        response = await agent_executor.ainvoke({"messages": [("user", user_input)]})
        await update.message.reply_text(response["messages"][-1].content)
    except Exception as e:
        logger.error(f"Fout: {e}")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⚡ SYNTHORA Lite: Online | Base: Connected")

# --- SECRET ARCHITECT COMMAND ---
async def skyline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Alleen jij (de owner) kan dit
    if str(update.effective_user.id) == os.getenv("OWNER_ID"):
        await update.message.reply_text("📊 Architect, ik genereer nu je wekelijkse Skyline Report...")
        # Voer hier de zware AI-analyse uit
    else:
        pass # Anderen krijgen geen antwoord

# --- DE STABIELE BOOTSTRAP ---
async def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    app = ApplicationBuilder().token(token).build()

    # Handlers koppelen
    app.add_handler(CommandHandler('status', status))
    app.add_handler(CommandHandler('skyline', skyline))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_any_message))

    # De stappen die je in je screenshot miste:
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
                  
