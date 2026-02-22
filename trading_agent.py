import os
from coinbase_agentkit import AgentKit, AgentKitConfig
from coinbase_agentkit.wallet_providers.local_evm_wallet_provider import LocalEvmWalletProvider

def setup_synthora():
    # Haal private key + RPC uit environment variables
    private_key = os.environ["EVM_PRIVATE_KEY"]
    rpc_url = os.environ["EVM_RPC_URL"]

    # Lokale wallet provider (GEEN Coinbase meer)
    wallet = LocalEvmWalletProvider(
        private_key=private_key,
        rpc_url=rpc_url,
        chain_id=8453  # Base mainnet
    )

    # AgentKit met lokale wallet
    agent_kit = AgentKit(
        AgentKitConfig(
            network_id="base-mainnet",
            wallet_provider=wallet
        )
    )

    # Bouw de agent zoals Synthora dat verwacht
    return build_agent_executor(agent_kit)
