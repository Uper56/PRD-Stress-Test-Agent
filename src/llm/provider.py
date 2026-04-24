"""Abstract LLM provider interface and shared response model.

Concrete providers (mock, openai, etc.) subclass LLMProvider and implement
`complete` and `stream`. Downstream agent code depends only on this module.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator

from pydantic import BaseModel, Field


class LLMResponse(BaseModel):
    """Unified response object returned by every provider."""

    text: str
    thinking: str | None = None
    usage: dict = Field(default_factory=dict)
    model_id: str


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    async def complete(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int | None = None,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """Return a full completion."""

    @abstractmethod
    async def stream(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int | None = None,
        temperature: float = 0.7,
    ) -> AsyncIterator[dict]:
        """Yield streaming chunks as dicts with at least a 'type' and 'delta' key."""
