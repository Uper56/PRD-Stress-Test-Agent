"""SSE framing helpers.

The wire format is standard text/event-stream: each event carries an
incrementing `id` (reconnect replay), an `event:` name matching the
logical event type, and a JSON `data:` payload.
"""

from __future__ import annotations

import json
from typing import Any


def sse_frame(event_id: int, event_type: str, data: dict[str, Any]) -> str:
    """Encode one SSE event as a wire frame (two newlines terminate it)."""
    payload = json.dumps(data, ensure_ascii=False, default=str)
    return f"id: {event_id}\nevent: {event_type}\ndata: {payload}\n\n"


SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",  # nginx/HF proxies: don't buffer the stream
}
