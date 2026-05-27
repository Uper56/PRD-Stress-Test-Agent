"""Environment-driven configuration and LLM provider factories.

`LLM_PROVIDER` switches which concrete provider is returned. Today:
  - "mock"   → `MockProvider` (deterministic, free, used by tests)
  - "openai" → `OpenAIProvider` (vanilla / proxy / Azure — see provider docstring)

Critic and supervisor each get their own model tier so the cheap critics
fan out wide and the supervisor uses a stronger model for synthesis.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

from .llm.mock_provider import MockProvider
from .llm.provider import LLMProvider

load_dotenv()


def _resolve_provider() -> str:
    """Decide which LLM provider is active.

    Priority:
      1. Explicit `LLM_PROVIDER` env var wins. Set this to "mock" to
         force MockProvider even when a key is present (useful for
         deterministic demos, screenshots, tests).
      2. Otherwise, if `OPENAI_API_KEY` is set, infer `openai`. This is
         the path that fixes the HF-Space-deployment trap: a user who
         goes to Settings → Variables and secrets and adds the API key
         expects the system to USE it, not silently stay on Mock.
      3. Final fallback: "mock".
    """
    explicit = os.getenv("LLM_PROVIDER")
    if explicit:
        return explicit.strip().lower()
    if os.getenv("OPENAI_API_KEY"):
        return "openai"
    return "mock"


PROVIDER = _resolve_provider()
MAX_CRITIC_TOKENS = int(os.getenv("MAX_CRITIC_TOKENS", "1500"))
MAX_SUPERVISOR_TOKENS = int(os.getenv("MAX_SUPERVISOR_TOKENS", "4000"))
MAX_CROSS_CHALLENGE_ROUNDS = int(os.getenv("MAX_CROSS_CHALLENGE_ROUNDS", "2"))
TIMEOUT_SECONDS = int(os.getenv("TIMEOUT_SECONDS", "120"))


def _build_openai(model: str, *, json_mode: bool) -> LLMProvider:
    """Factory shared by `get_critic_llm` / `get_supervisor_llm`."""
    from .llm.openai_provider import OpenAIProvider

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "LLM_PROVIDER=openai but OPENAI_API_KEY is not set. "
            "Add it to .env or fall back to LLM_PROVIDER=mock."
        )
    return OpenAIProvider(
        api_key=api_key,
        model=model,
        base_url=os.getenv("OPENAI_BASE_URL") or None,
        organization=os.getenv("OPENAI_ORGANIZATION") or None,
        timeout=float(TIMEOUT_SECONDS),
        json_mode=json_mode,
    )


def get_critic_llm() -> LLMProvider:
    """Return the LLM provider used by intake / 4 critics / cross-challenger.

    Critics are JSON-mode (the response_format hint keeps them from wrapping
    in ``` fences). On OpenAI we default to gpt-4o-mini — fast and cheap,
    sufficient for finding-extraction with a structured schema.
    """
    if PROVIDER == "mock":
        return MockProvider()
    if PROVIDER == "openai":
        model = os.getenv("OPENAI_CRITIC_MODEL", "gpt-4o-mini")
        return _build_openai(model, json_mode=True)
    raise NotImplementedError(f"Provider '{PROVIDER}' not implemented yet.")


def get_supervisor_llm() -> LLMProvider:
    """Return the LLM provider used by the supervisor agent.

    Supervisor wraps JSON inside an XML envelope (`<thinking>…</thinking>
    <verdict>{…}</verdict>`), so JSON-mode is OFF. On OpenAI we default to
    gpt-4o — better synthesis quality than mini, and supports streaming
    (unlike o1, which is why we don't use it here).
    """
    if PROVIDER == "mock":
        return MockProvider()
    if PROVIDER == "openai":
        model = os.getenv("OPENAI_SUPERVISOR_MODEL", "gpt-4o")
        return _build_openai(model, json_mode=False)
    raise NotImplementedError(f"Provider '{PROVIDER}' not implemented yet.")
