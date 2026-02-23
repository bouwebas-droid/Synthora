import threading
import telebot  # Vergeet niet: pip install pyTelegramBotAPI
from fastapi import FastAPI

# ... je bestaande variabelen ...
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
OWNER_ID = int(os.environ.get("OWNER_ID", 0)) # Je eigen ID van @userinfobot

bot = telebot.TeleBot(TELEGRAM_TOKEN)

# --- TELEGRAM LOGICA ---

@bot.message_handler(commands=['start', 'status'])
def send_welcome(message):
    if message.from_user.id == OWNER_ID:
        bot.reply_to(message, "🏗️ De Architect is online. De Skyline van Base is stabiel. Klaar voor commando's.")
    else:
        bot.reply_to(message, "Toegang geweigerd. Alleen de Eigenaar kan de Architect aansturen.")

@bot.message_handler(commands=['report'])
def telegram_report(message):
    if message.from_user.id == OWNER_ID:
        bot.send_chat_action(message.chat.id, 'typing')
        # Hier koppelen we je bestaande logica
        result = execute_skyline_protocol({"command": "INITIATE_SKYLINE_REPORT"})
        bot.reply_to(message, f"📊 **Skyline Report:**\n\n{result}")

# --- WEB SERVER & STARTUP ---

app = FastAPI(title="De Architect - Chillzilla Command Center")

@app.get("/")
def health_check():
    return {"status": "online", "agent": "Synthora", "telegram_active": True}

# De functie die de bot in de achtergrond laat draaien
def start_bot():
    print("[SYSTEM] Telegram Bot wordt opgestart...")
    bot.infinity_polling()

if __name__ == "__main__":
    import uvicorn
    # Start de Telegram bot in een aparte thread
    if TELEGRAM_TOKEN:
        threading.Thread(target=start_bot, daemon=True).start()
    
    print("--- Start De Architect API & Bot ---")
    uvicorn.run(app, host="0.0.0.0", port=10000)
