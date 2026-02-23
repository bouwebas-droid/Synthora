async def send_user_operation(call_data, to_address, value=0, is_batch=False):
    vault_address = await get_smart_vault_address()
    
    # 1. InitCode (alleen nodig als de wallet nog niet op-chain staat)
    init_code = "0x"
    if w3.eth.get_code(vault_address) == b'':
        factory_contract = w3.eth.contract(address=SIMPLE_ACCOUNT_FACTORY, abi=[{"inputs":[{"name":"owner","type":"address"},{"name":"salt","type":"uint256"}],"name":"createAccount","outputs":[{"name":"","type":"address"}],"stateMutability":"nonpayable","type":"function"}])
        init_code = SIMPLE_ACCOUNT_FACTORY + factory_contract.encode_abi("createAccount", args=[architect_signer.address, 0])[2:]

    # 2. Nonce ophalen
    ep_abi = [{"inputs":[{"name":"sender","type":"address"},{"name":"key","type":"uint192"}],"name":"getNonce","outputs":[{"name":"nonce","type":"uint256"}],"stateMutability":"view","type":"function"}]
    ep_contract = w3.eth.contract(address=ENTRY_POINT_ADDRESS, abi=ep_abi)
    nonce = ep_contract.functions.getNonce(vault_address, 0).call()

    # 3. Execute Calldata
    acc_abi = [{"inputs":[{"name":"dest","type":"address"},{"name":"value","type":"uint256"},{"name":"func","type":"bytes"}],"name":"execute","outputs":[],"stateMutability":"nonpayable","type":"function"}]
    vault_contract = w3.eth.contract(address=vault_address, abi=acc_abi)
    execute_data = vault_contract.encode_abi("execute", args=[to_address, value, call_data])

    # De UserOp structuur
    user_op = {
        "sender": vault_address,
        "nonce": hex(nonce),
        "initCode": init_code,
        "callData": execute_data,
        "callGasLimit": hex(2000000),         # Iets ruimer voor Aerodrome swaps
        "verificationGasLimit": hex(1000000),
        "preVerificationGas": hex(50000),
        "maxFeePerGas": hex(w3.eth.gas_price),
        "maxPriorityFeePerGas": hex(w3.to_wei(0.001, 'gwei')),
        "paymasterAndData": "0x",
        # CRUCIAL: Gebruik een 'v' van 27 (1b) om REVERT tijdens simulatie te voorkomen
        "signature": "0x" + "00" * 128 + "1b" 
    }

    async with httpx.AsyncClient() as client:
        # STAP 1: Sponsoring aanvragen
        # Pimlico v2 vult de gas-velden en paymasterAndData voor je in
        res = await client.post(BUNDLER_URL, json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "pm_sponsorUserOperation",
            "params": [user_op, ENTRY_POINT_ADDRESS]
        })
        
        res_data = res.json()
        if "error" in res_data:
            raise Exception(f"Sponsor Error: {res_data['error'].get('message')}")
        
        # Update UserOp met waarden van Pimlico (gas limits + paymasterAndData)
        user_op.update(res_data["result"])

        # STAP 2: De definitieve Hash berekenen en ondertekenen
        op_hash = get_user_op_hash(user_op, ENTRY_POINT_ADDRESS, 8453)
        
        # SimpleAccount verwacht de EIP-191 prefix (\x19Ethereum Signed Message:\n32...)
        signature = architect_signer.sign_message(encode_defunct(primitive=op_hash))
        user_op["signature"] = signature.signature.hex()

        # STAP 3: Versturen naar de Bundler
        final_res = await client.post(BUNDLER_URL, json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_sendUserOperation",
            "params": [user_op, ENTRY_POINT_ADDRESS]
        })
        
        final_data = final_res.json()
        if "error" in final_data:
            raise Exception(f"Bundler Error: {final_data['error'].get('message')}")
            
        return final_data["result"]
        
