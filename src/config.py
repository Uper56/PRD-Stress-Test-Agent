"""Environment-driven configuration and LLM provider factories."""

from __future__ import annotations

import os

from dotenv import load_dotenv

from .llm.mock_provider import MockProvider
from .llm.provider import LLMProvider

load_dotenv()


PROVIDER = os.getenv("LLM_PROVIDER", "mock").lower()
MAX_CRITIC_TOKENS = int(os.getenv("MAX_CRITIC_TOKENS", "1500"))
MAX_CROSS_CHALLENGE_ROUNDS = int(os.getenv("MAX_CROSS_CHALLENGE_ROUNDS", "2"))
TIMEOUT_SECONDS = int(os.getenv("TIMEOUT_SECONDS", "60"))


def get_critic_llm() -> LLMProvider:
    """Return the LLM provider used by critic agents."""
    if PROVIDER == "mock":
        return MockProvider()
    # TODO: add openai / anthropic / gemini branches once keys are available.
    raise NotImplementedError(f"Provider '{PROVIDER}' not implemented yet.")


def get_supervisor_llm() -> LLMProvider:
    """Return the LLM provider used by the supervisor agent."""
    if PROVIDER == "mock":
        return MockProvider()
    # TODO: supervisor may use a more capable model tier than critics.
    raise NotImplementedError(f"Provider '{PROVIDER}' not implemented yet.")
