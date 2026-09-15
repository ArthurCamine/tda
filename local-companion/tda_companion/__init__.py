VERSION = "0.3.5"

# Install the production retry policy at package import time so every
# AgentConnection consumer shares the same idempotency-aware transport contract.
from .agent_retry_policy import install_agent_retry_policy

install_agent_retry_policy()
