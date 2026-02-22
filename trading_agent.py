import os
import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

from langchain_openai import ChatOpenAI
from coinbase_agentkit import AgentKit, AgentKitValues
from coinbase_agentkit_langchain.utils import create_react_agent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- ENGINE SETUP ---
def setup_engine():
    # GPT-4o-mini voor snelheid en meertaligheid
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.1)
    
    # Wallet configuratie (Base Mainnet)
    agent_kit = AgentKit(AgentKitValues(
        cdp_api_key_name=os.getenv("CDP_API_KEY_NAME"),
        cdp_api_key_private_key=os.getenv("CDP_API_KEY_PRIVATE_KEY").replace('\\n', '\n'),
        network_id="base-mainnet"
    ))

    instructions = (
        "You are SYNTHORA, the official AI Agent for our token on Base. "
        "Be professional, fast, and respond in the user's language. "
        "Help users with swaps, price checks, and token info."
    )
    return create_react_agent(llm, agent_kit.get_tools(), state_modifier=instructions)

agent_executor = setup_engine()

# --- HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Knoppen voor de community (Lite & Fast)
    keyboard = [
        [InlineKeyboardButton("📈 Price Check", callback_data='price'),
         InlineKeyboardButton("🔄 Swap Tokens", callback_data='swap')],
        [InlineKeyboardButton("🌍 Community", url='https://t.me/jouwmunt')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "⚡ **SYNTHORA v1.0 Live**\nYour gateway to Base Trading.\n\n"
        "Ask me anything or use the buttons below:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def handle_ai(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Meertalige AI Track
    try:
        response = await agent_executor.ainvoke({"messages": [("user", update.message.text)]})
        await update.message.reply_text(response["messages"][-1].content)
    except Exception as e:
        logger.error(f"AI Error: {e}")

# --- ARCHITECT COMMANDS (OWNER ONLY) ---
async def skyline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != os.getenv("OWNER_ID"):
        return # Negeer anderen
    
    await update.message.reply_text("📊 **Architect identified.** Generating Weekly Skyline Report...")
    res = await agent_executor.ainvoke({"input": "Generate a weekly report on wallet activity and token performance."})
    await update.message.reply_text(res["messages"][-1].content)

# --- BOOTSTRAP ---
async def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    app = ApplicationBuilder().token(token).build()

    # Handlers
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('skyline', skyline))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_ai))

    # Fix voor Render Logs
    await app.initialize() 
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    
    logger.info("SYNTHORA Production Engine Live")
    await asyncio.Event().wait()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
    
        
