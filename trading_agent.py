# -import os
import asyncio
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# Essentiële AI & Blockchain imports
from langchain_openai import ChatOpenAI
from coinbase_agentkit import AgentKit, AgentKitValues
from coinbase_agentkit_langchain.utils import create_react_agent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- CONFIGURATIE ---
def setup_synthora():
    # Razendsnel brein (GPT-4o-mini) voor meertaligheid
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.1)
    
    # Verbinding met de Base Wallet via CDP
    agent_kit = AgentKit(AgentKitValues(
        cdp_api_key_name=os.getenv("CDP_API_KEY_NAME"),
        cdp_api_key_private_key=os.getenv("CDP_API_KEY_PRIVATE_KEY").replace('\\n', '\n'),
        network_id="base-mainnet"
    ))

    # De instructies voor jouw token agent
    system_instructions = (
        "Je bent SYNTHORA, de officiële AI Trading Agent op de Base blockchain. "
        "Je bent professioneel, technisch en reageert ALTIJD in de taal van de gebruiker. "
        "Je kunt saldi checken, tokens swappen en prijsinformatie geven. "
        "Help de gebruiker om succesvol te handelen op Base."
    )

    return create_react_agent(llm, agent_kit.get_tools(), state_modifier=system_instructions)

# Initialiseer de engine
agent_executor = setup_synthora()

# --- HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⚡ **SYNTHORA Engine Live**\n\n"
        "Ik ben je AI-agent op Base. Je kunt me vragen stellen over de markt, "
        "je balans checken of direct tokens swappen.\n\n"
        "Probeer: 'Wat is mijn balans?' of 'Hoe staat ETH ervoor?'"
    )

async def handle_ai_trading(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Dit is het hart van de bot: koppelt tekst aan blockchain acties
    try:
        user_input = update.message.text
        # De AI bepaalt of het een vraag is of een handelsopdracht
        response = await agent_executor.ainvoke({"messages": [("user", user_input)]})
        await update.message.reply_text(response["messages"][-1].content)
    except Exception as e:
        logger.error(f"Engine Error: {e}")
        await update.message.reply_text("Ik ondervind momenteel hinder bij het ophalen van Base-data.")

# SECRET ARCHITECT COMMAND: Skyline Report
async def skyline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Beveiliging: Alleen voor de eigenaar
    if str(update.effective_user.id) == os.getenv("OWNER_ID"):
        await update.message.reply_text("📊 **Architect geïdentificeerd.** Skyline Report wordt gegenereerd...")
        res = await agent_executor.ainvoke({"input": "Genereer een wekelijks rapport over wallet activiteit en token prestaties."})
        await update.message.reply_text(res["messages"][-1].content)

# --- DE STABIELE BOOTSTRAP (FIX VOOR RENDER) ---
async def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    app = ApplicationBuilder().token(token).build()

    # Registreer handlers
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('skyline', skyline))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_ai_trading))

    # Cruciaal: wacht op volledige startup voor Render stabiliteit
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
        
