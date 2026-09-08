import os

import instructor
from openai import OpenAI

LITELLM_URL = os.environ.get("LITELLM_URL", "http://litellm:4000")

_AGENT_KEY_ENV = {
    "extraction": "LITELLM_KEY_AGENT_EXTRACTION",
    "risk-scoring": "LITELLM_KEY_AGENT_RISK_SCORING",
    "approval": "LITELLM_KEY_AGENT_APPROVAL",
    "payment-execution": "LITELLM_KEY_AGENT_PAYMENT_EXECUTION",
}

_clients: dict[str, instructor.Instructor] = {}


def get_client(agent: str) -> instructor.Instructor:
    """Every agent's output is a typed, validated object with automatic
    retry on failure (Instructor), routed exclusively through LiteLLM with
    that agent's own budget-capped, model-scoped virtual key - never a raw
    provider SDK, never the master key."""
    if agent not in _clients:
        api_key = os.environ[_AGENT_KEY_ENV[agent]]
        raw_client = OpenAI(base_url=LITELLM_URL, api_key=api_key)
        _clients[agent] = instructor.from_openai(raw_client)
    return _clients[agent]
