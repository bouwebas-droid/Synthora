# Definieer de UserOp structuur exact zoals het EntryPoint contract het verwacht
user_op_tuple = (
    user_op['sender'], 
    int(user_op['nonce'], 16), 
    user_op['initCode'],
    user_op['callData'], 
    int(user_op['callGasLimit'], 16),
    int(user_op['verificationGasLimit'], 16), 
    int(user_op['preVerificationGas'], 16),
    int(user_op['maxFeePerGas'], 16), 
    int(user_op['maxPriorityFeePerGas'], 16),
    user_op['paymasterAndData'], 
    b'' # De signature is leeg tijdens het hashen
)

# Vraag de officiële hash aan het EntryPoint contract op Base
op_hash = ep_contract.functions.getUserOpHash(user_op_tuple).call()

# Onderteken de hash met de EIP-191 prefix (vereist voor SimpleAccount)
signature = architect_signer.sign_message(encode_defunct(primitive=op_hash))
user_op["signature"] = signature.signature.hex()
