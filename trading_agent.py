import os
import logging
import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestRegressor
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# ── Logging ──────────────────────────────────────────────
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ── Technical Indicators ─────────────────────────────────
class TechnicalIndicators:
    def __init__(self, data):
        self.data = data

    def calculate_rsi(self, periods=14):
        delta = self.data['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=periods).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=periods).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi

    def calculate_macd(self, short_window=12, long_window=26, signal_window=9):
        exp1 = self.data['Close'].ewm(span=short_window, adjust=False).mean()
        exp2 = self.data['Close'].ewm(span=long_window, adjust=False).mean()
        macd = exp1 - exp2
        signal = macd.ewm(span=signal_window, adjust=False).mean()
        return macd, signal

    def calculate_bollinger_bands(self, window=20, no_of_std=2):
        rolling_mean = self.data['Close'].rolling(window=window).mean()
        rolling_std = self.data['Close'].rolling(window=window).std()
        upper_band = rolling_mean + (rolling_std * no_of_std)
        lower_band = rolling_mean - (rolling_std * no_of_std)
        return upper_band, lower_band

    def calculate_moving_average(self, window=50):
        return self.data['Close'].rolling(window=window).mean()


# ── ML Model ─────────────────────────────────────────────
def train_model(X, y):
    model = RandomForestRegressor(n_estimators=100, random_state=42)
    model.fit(X, y)
    return model


# ── Telegram Handlers ────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welkom! Ik ben je trading bot.\n\n"
        "Beschikbare commando's:\n"
        "/start — Dit bericht\n"
        "/status — Bot status\n"
        "/analyse — Voorbeeld analyse\n"
    )

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Bot is actief en draait op Render.")

async def analyse(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📊 Analyse gestart... (koppel je data bron om echte signalen te krijgen)")

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Je zei: {update.message.text}")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Exception:", exc_info=context.error)


# ── Main ──────────────────────────────────────────────────
if __name__ == '__main__':
    TOKEN = os.environ.get("TELEGRAM_TOKEN")

    if not TOKEN:
        logger.error("❌ TELEGRAM_TOKEN niet gevonden! Zet hem in Render onder Environment Variables.")
        exit(1)

    logger.info("✅ Token gevonden, bot wordt gestart...")

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('status', status))
    app.add_handler(CommandHandler('analyse', analyse))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))
    app.add_error_handler(error_handler)

    logger.info("🤖 Bot draait nu! Polling gestart.")
    app.run_polling(drop_pending_updates=True)

        
    
        

