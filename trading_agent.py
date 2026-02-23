from eth_utils import to_hex

async def send_user_operation(call_data, to_address, value=0):
    vault_address = await get_smart_vault_address()
    
    # 1. InitCode (Alleen nodig als de wallet nog niet bestaat)
    init_code = "0x"
    if w3.eth.get_code(vault_address) == b'':
        factory = w3.eth.contract(address=SIMPLE_ACCOUNT_FACTORY, abi=[{"inputs":[{"name":"owner","type":"address"},{"name":"salt","type":"uint256"}],"name":"createAccount","outputs":[{"name":"","type":"address"}],"stateMutability":"nonpayable","type":"function"}])
        init_code = SIMPLE_ACCOUNT_FACTORY + factory.encode_abi("createAccount", args=[architect_signer.address, 0])[2:]

    # 2. Nonce ophalen via EntryPoint
    ep_abi = [{"inputs":[{"name":"sender","type":"address"},{"name":"key","type":"uint192"}],"name":"getNonce","outputs":[{"name":"nonce","type":"uint256"}],"stateMutability":"view","type":"function"},{"inputs":[{"name":"userOp","type":"tuple","components":[{"name":"sender","type":"address"},{"name":"nonce","type":"uint256"},{"name":"initCode","type":"bytes"},{"name":"callData","type":"bytes"},{"name":"callGasLimit","type":"uint256"},{"name":"verificationGasLimit","type":"uint256"},{"name":"preVerificationGas","type":"uint256"},{"name":"maxFeePerGas","type":"uint256"},{"name":"maxPriorityFeePerGas","type":"uint256"},{"name":"paymasterAndData","type":"bytes"},{"name":"signature","type":"bytes"}]}],"name":"getUserOpHash","outputs":[{"name":"","type":"bytes32"}],"stateMutability":"view","type":"function"}]
    ep_contract = w3.eth.contract(address=ENTRY_POINT_ADDRESS, abi=ep_abi)
    nonce = ep_contract.functions.getNonce(vault_address, 0).call()

    # 3. Execute Calldata (Single transaction)
    acc_abi = [{"inputs":[{"name":"dest","type":"address"},{"name":"value","type":"uint256"},{"name":"func","type":"bytes"}],"name":"execute","outputs":[],"stateMutability":"nonpayable","type":"function"}]
    vault_contract = w3.eth.contract(address=vault_address, abi=acc_abi)
    execute_data = vault_contract.encode_abi("execute", args=[to_address, value, call_data])

    # Basis UserOp (Pimlico v2 verwacht hex-strings voor getallen)
    user_op = {
        "sender": vault_address,
        "nonce": to_hex(nonce),
        "initCode": init_code,
        "callData": execute_data,
        "callGasLimit": to_hex(2000000), 
        "verificationGasLimit": to_hex(1000000),
        "preVerificationGas": to_hex(100000),
        "maxFeePerGas": to_hex(w3.eth.gas_price),
        "maxPriorityFeePerGas": to_hex(w3.to_wei(0.001, 'gwei')),
        "paymasterAndData": "0x",
        "signature": "0x" + "00" * 128 + "1b" # De '1b' voorkomt AA23 revert in simulatie
    }

    async with httpx.AsyncClient() as client:
        # STAP 1: Sponsoring (Gas estimatie)
        res = await client.post(BUNDLER_URL, json={
            "jsonrpc": "2.0", "id": 1,
            "method": "pm_sponsorUserOperation",
            "params": [user_op, ENTRY_POINT_ADDRESS]
        })
        
        sponsor_res = res.json()
        if "error" in sponsor_res:
            raise Exception(f"Sponsor Error: {sponsor_res['error'].get('message')}")
        
        # Update UserOp met Pimlico's gas-waarden en paymasterData
        user_op.update(sponsor_res["result"])

        # STAP 2: Cryptografisch Ondertekenen
        # We halen de hash DIRECT op van het EntryPoint contract op Base
        # Dit is de 'Architect' methode: geen risico op handmatige rekenfouten
        user_op_tuple = (
            user_op['sender'], int(user_op['nonce'], 16), user_op['initCode'],
            user_op['callData'], int(user_op['callGasLimit'], 16),
            int(user_op['verificationGasLimit'], 16), int(user_op['preVerificationGas'], 16),
            int(user_op['maxFeePerGas'], 16), int(user_op['maxPriorityFeePerGas'], 16),
            user_op['paymasterAndData'], b'' # Signature is leeg voor de hash
        )
        
        op_hash = ep_contract.functions.getUserOpHash(user_op_tuple).call()
        
        # Ondertekenen met EIP-191 prefix
        signature = architect_signer.sign_message(encode_defunct(primitive=op_hash))
        user_op["signature"] = signature.signature.hex()

        # STAP 3: Verzenden naar Bundler
        final_res = await client.post(BUNDLER_URL, json={
            "jsonrpc": "2.0", "id": 1,
            "method": "eth_sendUserOperation",
            "params": [user_op, ENTRY_POINT_ADDRESS]
        })
        
        return final_res.json().get("result") or final_res.json().get("error")
    
