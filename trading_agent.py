import os
import asyncio
import logging
import sys

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes
)

from coinbase_agentkit import AgentKit, AgentKitConfig
from coinbase_agentkit_langchain import get_langchain_tools
from langgraph.prebuilt import create_react_agent
from langchain_openai import ChatOpenAI

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

OWNER_ID = None
agent_executor = None


def setup_synthora():
    """Initialiseert de trading agent + wallet + tools."""
    # Check CDP environment variables
    required_env = ["CDP_API_KEY_ID", "CDP_API_KEY_SECRET", "CDP_WALLET_SECRET"]
    for var in required_env:
        if not os.getenv(var):
            logger.critical(f"FATAL: {var} ontbreekt in environment variables.")
            sys.exit(1)

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

    try:
        agent_kit = AgentKit(AgentKitConfig(network_id="base-mainnet"))
    except Exception as e:
        logger.critical(f"CDP Wallet initialisatie mislukt: {e}")
        raise

    tools = get_langchain_tools(agent_kit)

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


def is_architect(update: Update):
    return str(update.effective_user.id) == OWNER_ID


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_architect(update):
        await update.message.reply_text(
            "SYNTHORA Engine Live\nStatus: Architect Toegang\n\n"
            "Ik ben klaar voor trading orders op Base."
        )
    else:
        await update.message.reply_text("Geen toegang.")


async def handle_trading(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global agent_executor

    if not is_architect(update):
        await update.message.reply_text("Toegang geweigerd. Alleen de Architect kan trades uitvoeren.")
        return

    try:
        user_msg = update.message.text
        response = await agent_executor.ainvoke({"messages": [("user", user_msg)]})
        await update.message.reply_text(response["messages"][-1].content)

    except Exception as e:
        logger.error(f"Trading Error: {e}")
        await update.message.reply_text(f"Transactie mislukt: {e}")


async def skyline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_architect(update):
        return

    await update.message.reply_text("Skyline Report wordt gegenereerd...")

    try:
        res = await agent_executor.ainvoke({
            "messages": [("user", "Geef een technisch marktbericht voor Base op basis van huidige trends.")]
        })
        await update.message.reply_text(res["messages"][-1].content)

    except Exception as e:
        logger.error(f"Skyline Error: {e}")
        await update.message.reply_text(f"Skyline mislukt: {e}")


async def main():
    global agent_executor, OWNER_ID

    OWNER_ID = os.getenv("OWNER_ID")
    if not OWNER_ID:
        logger.critical("FATAL: OWNER_ID niet ingesteld.")
        sys.exit(1)

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.critical("FATAL: TELEGRAM_BOT_TOKEN niet ingesteld.")
        sys.exit(1)

    logger.info("Agent wordt opgestart...")

    try:
        agent_executor = setup_synthora()
    except Exception as e:
        logger.critical(f"Agent initialisatie mislukt: {e}")
        sys.exit(1)

    logger.info("Agent succesvol opgestart.")

    app = ApplicationBuilder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("skyline", skyline))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_trading))

    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)

    logger.info("SYNTHORA IS LIVE EN BEVEILIGD")

    await asyncio.Event().wait()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("SYNTHORA afgesloten.")
