import os
import asyncio
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# Gecorrigeerde imports voor de nieuwste Coinbase SDK
from coinbase_agentkit import AgentKit, AgentKitConfig
from coinbase_agentkit_langchain.utils import create_react_agent
from langchain_openai import ChatOpenAI

# Importeer je ML logica
try:
    import technical_analysis as ta
except ImportError:
    ta = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- CONFIGURATIE ---
OWNER_ID = os.getenv("OWNER_ID")

def setup_synthora():
    # Gebruik gpt-4o-mini voor maximale snelheid op Render
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    
    # Wallet setup (Base Mainnet) - Gebruik Config ipv Values
    agent_kit = AgentKit(AgentKitConfig(
        network_id="base-mainnet"
    ))

    # De 'Harsens' van de bot: Focus op TRADING en jouw TOKEN
    instructions = (
        "Je bent SYNTHORA, een high-speed trading agent op Base. "
        "Jouw doel is het verhandelen van de token van de Architect. "
        "Je hebt toestemming om swaps uit te voeren via je tools. "
        "Reageer altijd in de taal van de gebruiker (NL/EN)."
    )

    return create_react_agent(llm, agent_kit.get_tools(), state_modifier=instructions)

agent_executor = setup_synthora()

# --- BEVEILIGING ---
def is_architect(update: Update):
    return str(update.effective_user.id) == OWNER_ID

# --- HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status = "🔒 Beveiligd" if not is_architect(update) else "🔓 Architect Toegang"
    await update.message.reply_text(
        f"⚡ **SYNTHORA Engine Live**\nStatus: {status}\n\n"
        "Ik ben klaar voor trading orders en analyses op Base."
    )

async def handle_trading(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # De belangrijkste check: alleen jij mag traden
    if not is_architect(update):
        await update.message.reply_text("⛔ Toegang geweigerd. Alleen de Architect kan trades uitvoeren.")
        return

    try:
        user_msg = update.message.text
        # De AI koppelt je bericht aan de Coinbase Trade Tool
        response = await agent_executor.ainvoke({"messages": [("user", user_msg)]})
        await update.message.reply_text(response["messages"][-1].content)
    except Exception as e:
        logger.error(f"Trading Error: {e}")
        await update.message.reply_text("Transactie mislukt. Check je balans of CDP keys.")

# SECRET COMMAND: Skyline Report
async def skyline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_architect(update): return
    
    await update.message.reply_text("📊 **Skyline Report** wordt gegenereerd via ML Engine...")
    # AI voert een diepe analyse uit
    res = await agent_executor.ainvoke({"input": "Geef een technisch marktbericht voor Base op basis van huidige trends."})
    await update.message.reply_text(res["messages"][-1].content)

# --- RENDER BOOTSTRAP ---
async def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    app = ApplicationBuilder().token(token).build()

    # Handlers
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('skyline', skyline))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_trading))

    # Fix voor 'initialize was never awaited'
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
