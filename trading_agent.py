import os
import asyncio
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# De juiste imports voor de nieuwste AgentKit versie
from coinbase_agentkit import AgentKit, AgentKitConfig
from coinbase_agentkit_langchain.utils import create_react_agent
from langchain_openai import ChatOpenAI

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- 1. CONFIGURATIE & BEVEILIGING ---
# Dit zorgt dat de bot alleen naar JOU luistert voor trades
OWNER_ID = os.getenv("OWNER_ID")

def setup_agent():
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0) # Temp 0 voor precisie bij trades

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

agent_executor = setup_agent()

# --- 2. BEVEILIGINGS CHECK ---
def check_auth(update: Update):
    user_id = str(update.effective_user.id)
    if user_id != OWNER_ID:
        logger.warning(f"Onbevoegde toegang geprobeerd door ID: {user_id}")
        return False
    return True

# --- 3. HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    auth_status = "✅ Architect Geautoriseerd" if check_auth(update) else "🔒 Publieke Modus (Kijken alleen)"
    await update.message.reply_text(f"⚡ **SYNTHORA Engine Live**\nStatus: {auth_status}\n\nHoe kan ik je helpen op Base?")

async def handle_secure_trade(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        await update.message.reply_text("Transactie kon niet worden voltooid. Controleer je saldo of CDP instellingen.")

# --- 4. RENDER STARTUP ---
async def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
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
        pass
        
