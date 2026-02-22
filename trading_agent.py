import os
import asyncio
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# Lite imports: we laden alleen wat nodig is
from langchain_openai import ChatOpenAI
from coinbase_agentkit import AgentKit, AgentKitValues
from coinbase_agentkit_langchain.utils import create_react_agent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- ARCHITECTUUR: LITE AI SETUP ---
def setup_synthora():
    # We gebruiken gpt-4o-mini: extreem snel en begrijpt alle talen
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.2)

    # Wallet connectie met Base
    agent_kit = AgentKit(AgentKitValues(
        cdp_api_key_name=os.getenv("CDP_API_KEY_NAME"),
        cdp_api_key_private_key=os.getenv("CDP_API_KEY_PRIVATE_KEY").replace('\\n', '\n'),
        network_id="base-mainnet"
    ))

    # Meertalige instructies: Synthora past zich aan de gebruiker aan
    system_instructions = (
        "You are SYNTHORA, a high-speed AI Trading Agent on Base. "
        "Always respond in the same language the user speaks. "
        "Be technical, brief, and professional. No fluff."
    )

    return create_react_agent(llm, agent_kit.get_tools(), state_modifier=system_instructions)

# Initialiseer de agent één keer bij het opstarten
agent_executor = setup_synthora()

# --- HANDLERS ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user_text = update.message.text

    # AI Track voor analyse en vragen
    try:
        # De agent handelt nu meertalig af
        response = await agent_executor.ainvoke({"messages": [("user", user_text)]})
        await update.message.reply_text(response["messages"][-1].content)
    except Exception as e:
        logger.error(f"Fout: {e}")

# SECRET COMMAND: Alleen voor de eigenaar
async def skyline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != os.getenv("OWNER_ID"):
        return
    await update.message.reply_text("📊 *Generating Weekly Skyline Report...*")
    # Voer hier de specifieke Architect taak uit

# --- RENDER STARTUP ---
async def main():
    app = ApplicationBuilder().token(os.getenv("TELEGRAM_BOT_TOKEN")).build()

    app.add_handler(CommandHandler('skyline', skyline))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

    await app.initialize() # Voorkomt de 'never awaited' error uit je logs
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    
    logger.info("🤖 SYNTHORA LITE IS LIVE")
    await asyncio.Event().wait()

if __name__ == '__main__':
    asyncio.run(main())
    
