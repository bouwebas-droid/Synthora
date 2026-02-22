import asyncio
import logging
import os
import sys

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# De juiste imports voor de nieuwste AgentKit versie
from coinbase_agentkit import AgentKit, AgentKitConfig
from coinbase_agentkit_langchain.utils import create_react_agent
from langchain_openai import ChatOpenAI

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- 1. CONFIGURATIE ---
# OWNER_ID en TOKEN worden pas gevalideerd in main(), NIET op module-niveau
# Zo crasht Render niet bij het importeren van het bestand
OWNER_ID = None
agent_executor = None


def setup_agent():
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)  # Temp 0 voor precisie bij trades

    # Wallet setup voor Base Mainnet
    # De private keys worden veilig uit je Render Environment gehaald
    agent_kit = AgentKit(AgentKitConfig(
        network_id="base-mainnet"
    ))

    # Specifieke instructies voor SYNTHORA
    instructions = (
        "Je bent SYNTHORA, een beveiligde trading bot op Base. "
        "Je voert transacties uit zoals swaps en transfers. "
        "Reageer kort, krachtig en professioneel in de taal van de gebruiker."
    )

    return create_react_agent(llm, agent_kit.get_tools(), state_modifier=instructions)


# --- 2. BEVEILIGINGS CHECK ---
def check_auth(update: Update):
    user_id = str(update.effective_user.id)
    if user_id != OWNER_ID:
        logger.warning(f"Onbevoegde toegang geprobeerd door ID: {user_id}")
        return False
    return True


# --- 3. HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if check_auth(update):
        await update.message.reply_text(
            "⚡ **SYNTHORA Engine Live**\nStatus: ✅ Architect Geautoriseerd\n\nHoe kan ik je helpen op Base?",
            parse_mode="Markdown"
        )
    else:
        # Geef onbevoegden geen info over de bot
        await update.message.reply_text("⛔ Geen toegang.")


async def handle_secure_trade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global agent_executor

    # De belangrijkste beveiliging: Alleen jij kunt trades uitvoeren
    if not check_auth(update):
        await update.message.reply_text("⛔ Fout: Alleen de eigenaar kan handelsopdrachten geven.")
        return

    try:
        user_input = update.message.text
        # Hier wordt de tekst omgezet in een echte blockchain actie
        response = await agent_executor.ainvoke({"messages": [("user", user_input)]})
        await update.message.reply_text(response["messages"][-1].content)
    except Exception as e:
        logger.error(f"Trading Error: {e}")
        # Stuur de echte foutmelding naar jou zodat je kunt debuggen
        await update.message.reply_text(f"⚠️ Transactie mislukt:\n`{e}`", parse_mode="Markdown")


# --- 4. RENDER STARTUP ---
async def main():
    global agent_executor, OWNER_ID

    # Valideer omgevingsvariabelen HIER, niet op module-niveau
    OWNER_ID = os.getenv("OWNER_ID")
    if not OWNER_ID:
        logger.critical("FATAL: OWNER_ID is niet ingesteld in Render Environment Variables.")
        sys.exit(1)

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.critical("FATAL: TELEGRAM_BOT_TOKEN is niet ingesteld in Render Environment Variables.")
        sys.exit(1)

    # Agent wordt hier aangemaakt, niet op module-niveau
    logger.info("Agent wordt opgestart...")
    agent_executor = setup_agent()
    logger.info("Agent succesvol opgestart.")

    app = ApplicationBuilder().token(token).build()

    app.add_handler(CommandHandler('start', start))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_secure_trade))

    # Cruciaal voor stabiliteit op Render
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)

    logger.info("🤖 SYNTHORA IS LIVE EN BEVEILIGD")
    await asyncio.Event().wait()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("SYNTHORA afgesloten.")
        
