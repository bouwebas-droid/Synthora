# --- NIEUWE IMPORTS VOOR TRADING ---
import json

# Aerodrome Router Adres op Base (Mainnet)
AERODROME_ROUTER = "0xcF77a3Ba9A5CA399B7c97c74d54e5b1Beb874E43"
WETH_ADDRESS = "0x4200000000000000000000000000000000000006"

# Minimale ABI voor een swap
ROUTER_ABI = [
    {"inputs":[{"name":"amountOutMin","type":"uint256"},{"name":"routes","type":"tuple[]","components":[{"name":"from","type":"address"},{"name":"to","type":"address"},{"name":"stable","type":"bool"},{"name":"factory","type":"address"}]},{"name":"to","type":"address"},{"name":"deadline","type":"uint256"}],"name":"swapExactETHForTokens","outputs":[{"name":"amounts","type":"uint256[]"}],"stateMutability":"payable","type":"function"}
]

# --- 2. DE TRADE LOGICA ---

async def execute_swap_eth_to_token(token_to_buy, amount_in_eth):
    """Voert een directe swap uit van ETH naar een opgegeven token."""
    amount_in_wei = w3.to_wei(amount_in_eth, 'ether')
    router = w3.eth.contract(address=AERODROME_ROUTER, abi=ROUTER_ABI)
    
    # Route: ETH (WETH) -> Target Token (Volatile swap)
    route = [{"from": WETH_ADDRESS, "to": w3.to_checksum_address(token_to_buy), "stable": False, "factory": "0x4200000000000000000000000000000000000001"}]
    
    nonce = w3.eth.get_transaction_count(architect_account.address)
    
    # Transactie bouwen
    tx = router.functions.swapExactETHForTokens(
        0, # amountOutMin: Voor nu 0 voor test, later AI-berekend
        route,
        architect_account.address,
        int(time.time()) + 600
    ).build_transaction({
        'from': architect_account.address,
        'value': amount_in_wei,
        'gas': 250000,
        'gasPrice': w3.eth.gas_price,
        'nonce': nonce,
        'chainId': 8453 # Base Mainnet
    })
    
    signed_tx = w3.eth.account.sign_transaction(tx, os.environ.get("ARCHITECT_SESSION_KEY"))
    tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
    return w3.to_hex(tx_hash)

# --- 3. HET SECRET COMMAND: /trade ---

async def trade_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gebruik: /trade [token_adres] [hoeveelheid_eth]"""
    if update.effective_user.id != OWNER_ID: return

    if len(context.args) < 2:
        await update.message.reply_text("Geef data op: `/trade [token_adres] [eth_hoeveelheid]`")
        return

    token_addr = context.args[0]
    amount_eth = float(context.args[1])

    await update.message.reply_text(f"🚀 **De Architect voert trade uit op Base...**\nInvoer: `{amount_eth} ETH` -> `{token_addr[:10]}...`")

    try:
        tx_hash = await execute_swap_eth_to_token(token_addr, amount_eth)
        await update.message.reply_text(
            f"✅ **Trade Geslaagd!**\n"
            f"🔗 View on Basescan: [Hier](https://basescan.org/tx/{tx_hash})",
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Trade Error: {e}")
        await update.message.reply_text(f"❌ **Trade Mislukt:** {str(e)}")
        
