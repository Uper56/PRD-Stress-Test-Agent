"""Shared JSON-parsing helpers for agent response handling.

Models sometimes wrap JSON in ```json ... ``` fences or prepend prose; these
helpers strip that down before `json.loads`. Failures return None so callers
can graceful-degrade to empty results instead of propagating exceptions.
"""

from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def extract_json(text: str) -> dict | None:
    """Parse a JSON object out of a model response, tolerating markdown fences.

    Returns None (and logs a warning) if no JSON object can be recovered.
    """
    if not text:
        logger.warning("extract_json: empty response")
        return None

    candidates: list[str] = []

    fenced = _FENCE.findall(text)
    candidates.extend(fenced)
    candidates.append(text.strip())

    # Fallback: slice from first '{' to last '}'.
    first, last = text.find("{"), text.rfind("}")
    if first != -1 and last != -1 and last > first:
        candidates.append(text[first : last + 1])

    for candidate in candidates:
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue

    logger.warning("extract_json: could not parse JSON from response: %r", text[:200])
    return None
