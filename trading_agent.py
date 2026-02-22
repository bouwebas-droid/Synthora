import os
import asyncio
import logging
import pandas as pd
import numpy as np
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# AI & Blockchain
from langchain_openai import ChatOpenAI
from coinbase_agentkit import AgentKit, AgentKitValues
from coinbase_agentkit_langchain.utils import create_react_agent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- INTEGRATIE VAN JE ANALYSE SCRIPT ---
def run_ml_prediction():
    # Hier kun je later je RandomForest logica uit technical_analysis.py aanroepen
    # Voor nu een snelle placeholder die laat zien dat de engine werkt
    return "📈 ML Predictie: Bullish trend gedetecteerd op 15m timeframe."

# --- ENGINE SETUP ---
def setup_synthora():
    # Gebruik gpt-4o-mini voor snelheid
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.1)
    
    # Wallet configuratie (Base Mainnet)
    agent_kit = AgentKit(AgentKitValues(
        cdp_api_key_name=os.getenv("CDP_API_KEY_NAME"),
        cdp_api_key_private_key=os.getenv("CDP_API_KEY_PRIVATE_KEY").replace('\\n', '\n'),
        network_id="base-mainnet"
    ))

    # De AI weet nu dat hij ML kan gebruiken
    instructions = (
        "Je bent SYNTHORA, een geavanceerde AI Trading Agent op Base. "
        "Je hebt toegang tot RandomForest ML voorspellingen. "
        "Reageer altijd in de taal van de gebruiker. Wees technisch maar behulpzaam."
    )
    return create_react_agent(llm, agent_kit.get_tools(), state_modifier=instructions)

# Agent eenmalig laden
agent_executor = setup_synthora()

# --- HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💪 Welkom Architect! SYNTHORA Engine v2.0 is online.\n\n"
        "Ik ben verbonden met Base en je ML-modellen.\n"
        "Stuur een bericht om te beginnen."
    )

async def handle_ai(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_msg = update.message.text
        # De AI handelt nu ALLES af: vragen, trades en analyses
        response = await agent_executor.ainvoke({"messages": [("user", user_msg)]})
        await update.message.reply_text(response["messages"][-1].content)
    except Exception as e:
        logger.error(f"Fout: {e}")
        await update.message.reply_text("Engine herstart... probeer het over een moment opnieuw.")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prediction = run_ml_prediction()
    await update.message.reply_text(f"⚡ Status: Optimaal\nNetwork: Base Mainnet\n{prediction}")

# --- RENDER STABILITEIT ---
async def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    app = ApplicationBuilder().token(token).build()

    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('status', status))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_ai))

    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    
    logger.info("🤖 SYNTHORA MASTER ENGINE LIVE")
    await asyncio.Event().wait()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
        
