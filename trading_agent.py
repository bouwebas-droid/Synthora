import os
from coinbase_agentkit import AgentKit, AgentKitConfig
from coinbase_agentkit.wallet_providers.local_evm_wallet_provider import LocalEvmWalletProvider

def setup_synthora():
    private_key = os.environ["EVM_PRIVATE_KEY"]
    rpc_url = os.environ["EVM_RPC_URL"]

    wallet = LocalEvmWalletProvider(
        private_key=private_key,
        rpc_url=rpc_url,
        chain_id=8453
    )

    agent_kit = AgentKit(
        AgentKitConfig(
            network_id="base-mainnet",
            wallet_provider=wallet
        )
    )

    return build_agent_executor(agent_kit)
