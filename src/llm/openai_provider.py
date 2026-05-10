"""OpenAI provider — vanilla OpenAI, OpenAI-compatible proxies, and Azure.

Activated via `LLM_PROVIDER=openai` in `.env`. Three deployment shapes are
supported by sniffing env vars:

  1. **Vanilla OpenAI** (default) — `OPENAI_API_KEY` only.
  2. **OpenAI-compatible proxy** (e.g. a school-issued gateway) — also set
     `OPENAI_BASE_URL=https://<proxy>/v1`.
  3. **Azure OpenAI** — set `AZURE_OPENAI_ENDPOINT` AND
     `AZURE_OPENAI_DEPLOYMENT_NAME` (deployment name overrides `model`).
     Optionally set `AZURE_OPENAI_API_VERSION` (defaults to a recent stable).

Streaming chunk shape mirrors `MockProvider.stream()`:
  `{"type": "text", "delta": str}`

Tolerant retry: a single 5-second backoff retry on 429 / transient timeout.
JSON-mode requests pass `response_format={"type": "json_object"}` so the
critic / intake JSON parsers don't have to strip ``` fences.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, AsyncIterator

from .provider import (
    LLMError,
    LLMProvider,
    LLMRateLimitError,
    LLMResponse,
    LLMTimeoutError,
)

logger = logging.getLogger(__name__)


# Single retry on 429 / timeout — keeps the ablation harness moving without
# masking real outages. Longer backoffs belong in a queue, not in here.
_RETRY_DELAY_SECONDS = 5.0


class OpenAIProvider(LLMProvider):
    """Async OpenAI-compatible provider."""

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        base_url: str | None = None,
        organization: str | None = None,
        timeout: float = 120.0,
        json_mode: bool = True,
    ) -> None:
        self.model_id = model
        self.timeout = timeout
        self.json_mode = json_mode

        # Lazy import: keeps the rest of the package usable when `openai` isn't
        # installed (tests run under MockProvider).
        try:
            from openai import AsyncAzureOpenAI, AsyncOpenAI  # noqa: WPS433
        except ImportError as e:  # pragma: no cover
            raise LLMError(
                "openai>=1.50 not installed. `pip install openai>=1.50`."
            ) from e

        azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        azure_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")
        if azure_endpoint and azure_deployment:
            api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")
            self._client = AsyncAzureOpenAI(
                api_key=api_key,
                azure_endpoint=azure_endpoint,
                api_version=api_version,
                timeout=timeout,
            )
            # On Azure, `model` arg to chat.completions IS the deployment name.
            self.model_id = azure_deployment
            logger.info(
                "OpenAIProvider: Azure mode, deployment=%s api_version=%s",
                azure_deployment,
                api_version,
            )
        else:
            self._client = AsyncOpenAI(
                api_key=api_key,
                base_url=base_url,
                organization=organization,
                timeout=timeout,
            )
            logger.info(
                "OpenAIProvider: vanilla mode, model=%s base_url=%s",
                self.model_id,
                base_url or "<default>",
            )

    # ---- complete ---------------------------------------------------------

    async def complete(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int | None = None,
        temperature: float = 0.7,
    ) -> LLMResponse:
        kwargs = self._build_kwargs(system, user, max_tokens, temperature, stream=False)
        resp = await self._call_with_retry(self._client.chat.completions.create, **kwargs)

        choice = resp.choices[0] if resp.choices else None
        text = (choice.message.content if choice and choice.message else "") or ""
        usage = {
            "input_tokens": getattr(resp.usage, "prompt_tokens", 0) or 0,
            "output_tokens": getattr(resp.usage, "completion_tokens", 0) or 0,
            "total_tokens": getattr(resp.usage, "total_tokens", 0) or 0,
        }

        return LLMResponse(
            text=text,
            thinking=None,
            usage=usage,
            model_id=getattr(resp, "model", self.model_id),
        )

    # ---- stream -----------------------------------------------------------

    async def stream(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int | None = None,
        temperature: float = 0.7,
    ) -> AsyncIterator[dict]:
        # JSON mode + streaming is supported by gpt-4o-mini / gpt-4o; we
        # leave it ON for consistency with `complete`. Supervisor stream
        # consumer doesn't care — it only watches text deltas.
        kwargs = self._build_kwargs(system, user, max_tokens, temperature, stream=True)
        try:
            stream = await self._client.chat.completions.create(**kwargs)
        except Exception as e:  # noqa: BLE001
            raise self._classify(e) from e

        async for chunk in stream:
            try:
                delta = chunk.choices[0].delta.content if chunk.choices else None
            except (AttributeError, IndexError):
                delta = None
            if delta:
                yield {"type": "text", "delta": delta}

    # ---- internals --------------------------------------------------------

    def _build_kwargs(
        self,
        system: str,
        user: str,
        max_tokens: int | None,
        temperature: float,
        *,
        stream: bool,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": self.model_id,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "stream": stream,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        # JSON mode only applies to non-supervisor calls; the supervisor
        # wraps JSON inside an XML envelope, which json_mode would refuse.
        # Sniff the system prompt for the supervisor sentinel.
        if self.json_mode and "supervisor" not in system.lower():
            kwargs["response_format"] = {"type": "json_object"}
        if stream:
            # Ask the API to include token usage on the final chunk.
            kwargs["stream_options"] = {"include_usage": True}
        return kwargs

    async def _call_with_retry(self, fn, **kwargs) -> Any:
        try:
            return await fn(**kwargs)
        except Exception as e:  # noqa: BLE001
            classified = self._classify(e)
            if isinstance(classified, (LLMRateLimitError, LLMTimeoutError)):
                logger.warning(
                    "OpenAIProvider: %s — sleeping %ss and retrying once",
                    type(classified).__name__,
                    _RETRY_DELAY_SECONDS,
                )
                await asyncio.sleep(_RETRY_DELAY_SECONDS)
                try:
                    return await fn(**kwargs)
                except Exception as e2:  # noqa: BLE001
                    raise self._classify(e2) from e2
            raise classified from e

    @staticmethod
    def _classify(exc: Exception) -> Exception:
        """Map raw OpenAI / httpx exceptions to our typed hierarchy."""
        try:
            from openai import APITimeoutError, RateLimitError  # noqa: WPS433
        except ImportError:
            APITimeoutError = ()  # type: ignore[assignment]
            RateLimitError = ()  # type: ignore[assignment]

        if isinstance(exc, RateLimitError):
            return LLMRateLimitError(str(exc))
        if isinstance(exc, APITimeoutError) or isinstance(exc, asyncio.TimeoutError):
            return LLMTimeoutError(str(exc))
        if isinstance(exc, LLMError):
            return exc
        return LLMError(f"{type(exc).__name__}: {exc}")
