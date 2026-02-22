import os
from coinbase_agentkit import AgentKit, AgentKitConfig
from coinbase_agentkit.wallet_providers import LocalWalletProvider

# eventueel andere imports die je al had, laat die erboven/eronder staan
# zoals: from synthora.agent import build_agent_executor  (of hoe het bij jou heet)

def setup_synthora():
    private_key = os.environ["EVM_PRIVATE_KEY"]
    rpc_url = os.environ["EVM_RPC_URL"]

    wallet = LocalWalletProvider(
        private_key=private_key,
        rpc_url=rpc_url,
        chain_id=8453  # Base mainnet
    )

    agent_kit = AgentKit(
        AgentKitConfig(
            network_id="base-mainnet",
            wallet_provider=wallet
        )
    )

    return build_agent_executor(agent_kit)


if __name__ == "__main__":
    # start je agent hier, als dat in jouw originele file ook zo was
    setup_synthora()
