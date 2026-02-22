import os
import asyncio
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# We laden de zware AI-onderdelen op een veilige manier
from langchain_openai import ChatOpenAI
from coinbase_agentkit import AgentKit, AgentKitValues
from coinbase_agentkit_langchain.utils import create_react_agent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- 1. DE AI ENGINE (SNEL & MEERTALIG) ---
def setup_synthora():
    # gpt-4o-mini is razendsnel voor trading en talen
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.2)
    
    # Haal de keys op uit Render (CDP_API_KEY_NAME, etc.)
    agent_kit = AgentKit(AgentKitValues(
        cdp_api_key_name=os.getenv("CDP_API_KEY_NAME"),
        cdp_api_key_private_key=os.getenv("CDP_API_KEY_PRIVATE_KEY").replace('\\n', '\n'),
        network_id="base-mainnet"
    ))

    # Instructies voor de bot
    system_instructions = (
        "You are SYNTHORA, a high-speed AI Trading Agent on Base. "
        "Always respond in the user's language. Keep it brief and professional."
    )

    return create_react_agent(llm, agent_kit.get_tools(), state_modifier=system_instructions)

# Initialiseer de agent één keer
agent_executor = setup_synthora()

# --- 2. HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 SYNTHORA is live. Ik ben je AI Agent op Base.\n\n/status — Snelheidscheck")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⚡ Engine: Lite | Base: Verbonden | Status: Actief")

async def handle_ai_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Dit is de AI-schil die automatisch Nederlands (of andere talen) herkent
    try:
        user_text = update.message.text
        # De agent denkt na en voert eventueel acties uit op Base
        response = await agent_executor.ainvoke({"messages": [("user", user_text)]})
        await update.message.reply_text(response["messages"][-1].content)
    except Exception as e:
        logger.error(f"Fout: {e}")

# --- 3. ARCHITECT COMMAND (SECRET) ---
async def skyline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Alleen jij (de eigenaar) mag dit rapport zien
    if str(update.effective_user.id) == os.getenv("OWNER_ID"):
        await update.message.reply_text("📊 Architect, ik stel het wekelijkse Skyline Report op...")
        res = await agent_executor.ainvoke({"input": "Genereer een beknopt wekelijks rapport van de wallet activiteit."})
        await update.message.reply_text(res["messages"][-1].content)

# --- 4. RENDER STARTUP (DE FIX) ---
async def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    app = ApplicationBuilder().token(token).build()

    # Handlers toevoegen
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('status', status))
    app.add_handler(CommandHandler('skyline', skyline))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_ai_message))

    # Cruciaal voor Render (Lost 'Application.initialize was never awaited' op)
    await app.initialize()
    await app.start()
    
    logger.info("🤖 SYNTHORA IS LIVE")
    
    await app.updater.start_polling(drop_pending_updates=True)
    
    # Houdt de bot in leven
    await asyncio.Event().wait()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
                  
