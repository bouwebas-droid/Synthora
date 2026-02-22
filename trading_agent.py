    import os
import asyncio
import logging
import sys

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# Correcte imports voor de nieuwste Coinbase AgentKit SDK
from coinbase_agentkit import AgentKit, AgentKitConfig
from coinbase_agentkit_langchain import get_langchain_tools
from langgraph.prebuilt import create_react_agent
from langchain_openai import ChatOpenAI

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- CONFIGURATIE ---
# OWNER_ID en agent worden pas geladen in main(), NIET op module-niveau
OWNER_ID = None
agent_executor = None


def setup_synthora():
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

    # Wallet setup (Base Mainnet) - keys komen uit Render Environment Variables
    agent_kit = AgentKit(AgentKitConfig(
        network_id="base-mainnet"
    ))

    # Haal de tools op via de correcte methode
    tools = get_langchain_tools(agent_kit)

    # Instructies voor SYNTHORA
    instructions = (
        "Je bent SYNTHORA, een high-speed trading agent op Base. "
        "Jouw doel is het verhandelen van de token van de Architect. "
        "Je hebt toestemming om swaps uit te voeren via je tools. "
        "Reageer altijd in de taal van de gebruiker (NL/EN)."
    )

    return create_react_agent(
        model=llm,
        tools=tools,
        prompt=instructions
    )


# --- BEVEILIGING ---
def is_architect(update: Update):
    return str(update.effective_user.id) == OWNER_ID


# --- HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_architect(update):
        await update.message.reply_text(
            "⚡ **SYNTHORA Engine Live**\nStatus: 🔓 Architect Toegang\n\n"
            "Ik ben klaar voor trading orders en analyses op Base.",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text("⛔ Geen toegang.")


async def handle_trading(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global agent_executor

    if not is_architect(update):
        await update.message.reply_text("⛔ Toegang geweigerd. Alleen de Architect kan trades uitvoeren.")
        return

    try:
        user_msg = update.message.text
        response = await agent_executor.ainvoke({"messages": [("user", user_msg)]})
        await update.message.reply_text(response["messages"][-1].content)
    except Exception as e:
        logger.error(f"Trading Error: {e}")
        await update.message.reply_text(f"⚠️ Transactie mislukt:\n`{e}`", parse_mode="Markdown")


# SECRET COMMAND: Skyline Report
async def skyline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_architect(update):
        return

    await update.message.reply_text("📊 **Skyline Report** wordt gegenereerd...", parse_mode="Markdown")
    try:
        res = await agent_executor.ainvoke({
            "messages": [("user", "Geef een technisch marktbericht voor Base op basis van huidige trends.")]
        })
        await update.message.reply_text(res["messages"][-1].content)
    except Exception as e:
        logger.error(f"Skyline Error: {e}")
        await update.message.reply_text(f"⚠️ Skyline rapport mislukt:\n`{e}`", parse_mode="Markdown")


# --- RENDER BOOTSTRAP ---
async def main():
    global agent_executor, OWNER_ID

    OWNER_ID = os.getenv("OWNER_ID")
    if not OWNER_ID:
        logger.critical("FATAL: OWNER_ID is niet ingesteld in Render Environment Variables.")
        sys.exit(1)

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.critical("FATAL: TELEGRAM_BOT_TOKEN is niet ingesteld in Render Environment Variables.")
        sys.exit(1)

    logger.info("Agent wordt opgestart...")
    agent_executor = setup_synthora()
    logger.info("Agent succesvol opgestart.")

    app = ApplicationBuilder().token(token).build()

    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('skyline', skyline))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_trading))

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
    
