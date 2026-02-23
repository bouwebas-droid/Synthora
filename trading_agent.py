from eth_utils import to_hex

async def send_user_operation(call_data, to_address, value=0, is_batch=False):
    """
    Verstuurt een UserOperation naar Base via Pimlico.
    Ondersteunt zowel enkele transacties als batches.
    """
    vault_address = await get_smart_vault_address()
    
    # 1. InitCode: Alleen bij de allereerste transactie van de wallet
    init_code = "0x"
    if w3.eth.get_code(vault_address) == b'':
        logger.info(f"First transaction for {vault_address}. Generating initCode...")
        factory_contract = w3.eth.contract(address=SIMPLE_ACCOUNT_FACTORY, abi=[{"inputs":[{"name":"owner","type":"address"},{"name":"salt","type":"uint256"}],"name":"createAccount","outputs":[{"name":"","type":"address"}],"stateMutability":"nonpayable","type":"function"}])
        # SimpleAccountFactory: createAccount(owner, salt)
        init_code = SIMPLE_ACCOUNT_FACTORY + factory_contract.encode_abi("createAccount", args=[architect_signer.address, 0])[2:]

    # 2. Nonce & Gas ophalen
    ep_abi = [{"inputs":[{"name":"sender","type":"address"},{"name":"key","type":"uint192"}],"name":"getNonce","outputs":[{"name":"nonce","type":"uint256"}],"stateMutability":"view","type":"function"}]
    ep_contract = w3.eth.contract(address=ENTRY_POINT_ADDRESS, abi=ep_abi)
    nonce = ep_contract.functions.getNonce(vault_address, 0).call()
    
    gas_price = w3.eth.gas_price
    # We zetten de priority fee iets hoger voor snelle verwerking op Base
    priority_fee = w3.to_wei(0.001, 'gwei') 

    # 3. Calldata bepalen (Single vs Batch)
    # SimpleAccount.sol gebruikt 'execute' voor 1 call en 'executeBatch' voor meerdere
    if not is_batch:
        acc_abi = [{"inputs":[{"name":"dest","type":"address"},{"name":"value","type":"uint256"},{"name":"func","type":"bytes"}],"name":"execute","outputs":[],"stateMutability":"nonpayable","type":"function"}]
        vault_contract = w3.eth.contract(address=vault_address, abi=acc_abi)
        execute_data = vault_contract.encode_abi("execute", args=[to_address, value, call_data])
    else:
        # call_data moet hier een list van bytes zijn, to_address een list van adressen
        acc_abi = [{"inputs":[{"name":"dest","type":"address[]"},{"name":"value","type":"uint256[]"},{"name":"func","type":"bytes[]"}],"name":"executeBatch","outputs":[],"stateMutability":"nonpayable","type":"function"}]
        vault_contract = w3.eth.contract(address=vault_address, abi=acc_abi)
        execute_data = vault_contract.encode_abi("executeBatch", args=[to_address, value, call_data])

    # 4. De UserOp Structuur met de 'Safe Dummy Signature'
    user_op = {
        "sender": vault_address,
        "nonce": to_hex(nonce),
        "initCode": init_code,
        "callData": execute_data,
        "callGasLimit": to_hex(2000000),         # Wordt overschreven door Pimlico
        "verificationGasLimit": to_hex(1000000), # Wordt overschreven door Pimlico
        "preVerificationGas": to_hex(100000),    # Wordt overschreven door Pimlico
        "maxFeePerGas": to_hex(gas_price),
        "maxPriorityFeePerGas": to_hex(priority_fee),
        "paymasterAndData": "0x",
        "signature": "0x" + "00" * 64 + "1b" # De '1b' voorkomt de AA23 revert in simulatie
    }

    async with httpx.AsyncClient() as client:
        # STAP 1: Pimlico Sponsoring (Vult gas limits en paymaster data in)
        res = await client.post(BUNDLER_URL, json={
            "jsonrpc": "2.0", "id": 1,
            "method": "pm_sponsorUserOperation",
            "params": [user_op, ENTRY_POINT_ADDRESS]
        })
        
        res_data = res.json()
        if "error" in res_data:
            # Als dit faalt, heeft de wallet vaak te weinig balans voor gas of is de callData fout
            error_msg = res_data['error'].get('message', 'Unknown Sponsor Error')
            raise Exception(f"Sponsor Error: {error_msg}")
        
        # Merge de gesponsorde velden (paymasterAndData + gas limits)
        user_op.update(res_data["result"])

        # STAP 2: Cryptografisch Ondertekenen
        # Gebruik de get_user_op_hash functie die je al had
        op_hash = get_user_op_hash(user_op, ENTRY_POINT_ADDRESS, 8453)
        
        # Onderteken de hash met de EIP-191 prefix (\x19Ethereum Signed Message:\n32...)
        signature = architect_signer.sign_message(encode_defunct(primitive=op_hash))
        user_op["signature"] = signature.signature.hex()

        # STAP 3: Verzenden naar de Bundler
        final_res = await client.post(BUNDLER_URL, json={
            "jsonrpc": "2.0", "id": 1,
            "method": "eth_sendUserOperation",
            "params": [user_op, ENTRY_POINT_ADDRESS]
        })
        
        final_data = final_res.json()
        if "error" in final_data:
            raise Exception(f"Bundler Error: {final_data['error'].get('message')}")
            
        user_op_hash = final_data["result"]
        logger.info(f"UserOp succesvol verzonden! Hash: {user_op_hash}")
        return user_op_hash
        
