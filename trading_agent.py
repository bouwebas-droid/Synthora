# --- 1. BOVENAAN: EXTRA IMPORTS ---
import logging, os, asyncio, time
from web3 import Web3
from eth_account import Account
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from langchain_openai import ChatOpenAI
from fastapi import FastAPI
import uvicorn

# --- CONFIG & GLOBALS ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Synthora")
w3 = Web3(Web3.HTTPProvider("https://mainnet.base.org"))

AERODROME_ROUTER = "0xcF77a3Ba9A5CA399B7c97c74d54e5b1Beb874E43"
WETH = "0x4200000000000000000000000000000000000006"
GAS_LIMIT = 0.05 

OWNER_ID = int(os.environ.get("OWNER_ID", 0))
private_key = os.environ.get("ARCHITECT_SESSION_KEY")
architect_account = Account.from_key(private_key) if private_key else None
llm = ChatOpenAI(model="gpt-4o", api_key=os.environ.get("OPENAI_API_KEY"))

# Dit houdt je actieve posities bij in het geheugen van de bot
active_positions = {} 

# --- 2. DE "PURE PROFIT" ENGINE ---

async def get_current_value(token_addr):
    """Berekent de huidige waarde van je tokens in ETH."""
    token_contract = w3.eth.contract(address=w3.to_checksum_address(token_addr), abi=ERC20_ABI)
    bal = token_contract.functions.balanceOf(architect_account.address).call()
    if bal == 0: return 0
    
    router = w3.eth.contract(address=AERODROME_ROUTER, abi=ROUTER_ABI)
    route = [{"from": w3.to_checksum_address(token_addr), "to": WETH, "stable": False, "factory": "0x4200000000000000000000000000000000000001"}]
    amounts = router.functions.getAmountsOut(bal, route).call()
    return w3.from_wei(amounts[-1], 'ether')

async def profit_guardian(update, token_addr, entry_eth, target_pct):
    """De bewaker die alleen bij winst verkoopt."""
    token_addr = w3.to_checksum_address(token_addr)
    # De bot onthoudt dat we deze token hebben
    active_positions[token_addr] = {"entry": entry_eth, "target": target_pct}
    
    while token_addr in active_positions:
        try:
            current_val = await get_current_value(token_addr)
            if current_val == 0: break # Positie is blijkbaar al weg
            
            profit_pct = ((current_val - entry_eth) / entry_eth) * 100
            
            # Alleen verkopen als target is bereikt EN we boven entry zitten
            if profit_pct >= target_pct and current_val > entry_eth:
                await update.message.reply_text(f"🎯 **Target Bereikt!** Winst: `{profit_pct:.2f}%`.\nExecutie verkoop...")
                tx = await execute_sell(token_addr)
                await update.message.reply_text(f"💰 **Pure Winst Verzilverd!**\nHash: [Basescan](https://basescan.org/tx/{tx})", parse_mode='Markdown')
                del active_positions[token_addr]
                break
                
            await asyncio.sleep(30) # Check elke 30 seconden voor snelle Skyline actie
        except Exception as e:
            logger.error(f"Guardian error: {e}")
            await asyncio.sleep(10)

# --- 3. COMMAND CENTER ---

async def trade_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gebruik: /trade [token] [eth] [winst%]"""
    if update.effective_user.id != OWNER_ID: return
    try:
        token, eth_amt, target = context.args[0], float(context.args[1]), float(context.args[2])
        
        # 1. De Koop
        tx_hash = await execute_trade(token, eth_amt)
        await update.message.reply_text(f"🚀 **Gekocht!** De Architect schaduwt nu de koers voor `{target}%` winst.")
        
        # 2. Start de Guardian
        asyncio.create_task(profit_guardian(update, token, eth_amt, target))
    except Exception as e:
        await update.message.reply_text(f"❌ **Trade Fout:** {e}")

async def panic_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """De nooduitgang: /panic [token] - Verkoopt ALLES direct."""
    if update.effective_user.id != OWNER_ID: return
    token = context.args[0]
    await update.message.reply_text(f"⚠️ **PANIC MODE!** De Architect dumpt alles voor `{token[:10]}...`")
    tx = await execute_sell(token)
    if token in active_positions: del active_positions[token]
    await update.message.reply_text(f"🏁 **Nooduitgang voltooid.** Hash: `{tx}`")
    
