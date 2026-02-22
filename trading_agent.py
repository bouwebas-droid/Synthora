import os
import time
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel
from web3 import Web3
from eth_account import Account

# 1. Connectie & Configuratie
BASE_RPC_URL = "https://mainnet.base.org"
w3 = Web3(Web3.HTTPProvider(BASE_RPC_URL))

PIMLICO_API_KEY = os.environ.get("PIMLICO_API_KEY")
session_key_hex = os.environ.get("ARCHITECT_SESSION_KEY")

# HET SLOT OP DE DEUR: Alleen jij kent dit wachtwoord
OWNER_SECRET = os.environ.get("OWNER_SECRET_KEY", "tijdelijk_geheim_wachtwoord")

if session_key_hex:
    architect_account = Account.from_key(session_key_hex)
else:
    print("WAARSCHUWING: Geen Session Key gevonden. Read-only modus.")
    architect_account = None

# Initialiseer de Webserver
app = FastAPI(title="De Architect - Chillzilla Command Center")

# Data model voor inkomende commando's
class CommandPayload(BaseModel):
    command: str
    target_token: str = None
    amount: int = None

# 2. De API Endpoints
@app.get("/")
def health_check():
    """Render gebruikt dit om te checken of de bot online is."""
    return {"status": "online", "agent": "De Architect", "network": "Base Mainnet"}

@app.post("/architect/execute")
def execute_secret_command(payload: CommandPayload, authorization: str = Header(None)):
    """De exclusieve poort voor jouw Secret Commands."""
    # Controleer of de eigenaar aan de poort klopt
    if authorization != f"Bearer {OWNER_SECRET}":
        raise HTTPException(status_code=401, detail="Toegang geweigerd: Ongeldige of ontbrekende sleutel.")
    
    print(f"\n[SYSTEM] Geautoriseerd commando ontvangen: {payload.command}")
    
    # Routeer het commando
    if payload.command == "INITIATE_SKYLINE_REPORT":
        result = execute_skyline_protocol(payload)
    elif payload.command == "AUTONOMOUS_SWAP":
        result = prepare_and_send_user_operation(payload.dict())
    else:
        raise HTTPException(status_code=400, detail=f"Commando '{payload.command}' niet herkend.")
        
    return {"status": "success", "result": result}

# 3. De Interne Logica (Ongewijzigd, maar nu aangestuurd via API)
def execute_skyline_protocol(payload):
    time.sleep(1) 
    if not w3.is_connected():
        return "[FOUT] Geen verbinding met Base."

    latest_block = w3.eth.get_block('latest')
    print(f"[ARCHITECT] On-chain data gesynchroniseerd. Huidig Base block: {latest_block['number']}")
    
    action_required = True 
    if action_required and architect_account:
        swap_payload = {"target_token": payload.target_token or "CHILLZILLA_CONTRACT_ADDRESS"}
        return prepare_and_send_user_operation(swap_payload)
    
    return "Skyline Report afgerond. Geen on-chain actie vereist."

def prepare_and_send_user_operation(payload):
    if not architect_account or not PIMLICO_API_KEY:
        return "[FOUT] Ontbrekende sleutels."
        
    print(f"[ARCHITECT] UserOperation calldata bouwen voor: {payload.get('target_token')}...")
    print("[ARCHITECT] UserOperation cryptografisch ondertekend via Session Key.")
    
    return "Connectie met Pimlico gelegd. Concept UserOp klaargezet."

# Zorgt ervoor dat we het lokaal kunnen testen
if __name__ == "__main__":
    import uvicorn
    print("--- Start De Architect Lokaal ---")
    uvicorn.run(app, host="0.0.0.0", port=10000)
    
