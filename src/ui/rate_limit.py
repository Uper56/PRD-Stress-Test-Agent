"""Rate limiting for the public HuggingFace Space demo.

Two layers:

  1. **Per-IP**, in-memory, 5 requests/hour. Resets on process restart, which
     is fine for the demo — HF Spaces cycle frequently and we'd rather a
     fresh visitor get a clean window than carry state through a restart.

  2. **Global**, file-backed, 50 requests/day across all visitors. Persisted
     to `data/results/daily_count.json` so it survives a Streamlit script
     rerun (which happens on every widget click). Resets at UTC midnight.

Tunables live as module constants so the deployment can override them
via env vars without touching code:

  RATE_LIMIT_PER_IP_PER_HOUR        (default 5)
  RATE_LIMIT_GLOBAL_PER_DAY         (default 50)

Failure mode: if the disk write fails (read-only FS, full disk), the
global counter quietly degrades to in-memory — visitors don't get a
worse UX, the cap just doesn't survive a restart that day.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

logger = logging.getLogger(__name__)


# ---- Tunables --------------------------------------------------------------

PER_IP_PER_HOUR = int(os.getenv("RATE_LIMIT_PER_IP_PER_HOUR", "5"))
GLOBAL_PER_DAY = int(os.getenv("RATE_LIMIT_GLOBAL_PER_DAY", "50"))

# When set, rate-limiting is bypassed entirely. Used in local dev /
# tests / when the operator wants to demo unrestricted.
DISABLED = os.getenv("RATE_LIMIT_DISABLED", "0") == "1"

# Where the daily-count file lives. Kept under data/results/ so it's
# already covered by the .gitignore.
COUNTER_PATH = Path(os.getenv("RATE_LIMIT_COUNTER_PATH", "data/results/daily_count.json"))


# ---- Per-IP (in-memory, hour-window) ---------------------------------------

# {ip: deque[timestamp]}  — sliding window. We don't bother evicting old
# entries until a request from that IP comes in; the process is short-lived
# enough that the dict won't grow unbounded.
_per_ip: dict[str, deque[float]] = defaultdict(deque)
_per_ip_lock = threading.Lock()


def _prune_ip_window(stamps: deque[float], window_seconds: int = 3600) -> None:
    """Drop timestamps older than `window_seconds` from `stamps` in-place."""
    cutoff = time.time() - window_seconds
    while stamps and stamps[0] < cutoff:
        stamps.popleft()


# ---- Global (file-backed, day-window) --------------------------------------


def _today_key() -> str:
    """UTC date string — the global counter resets when this rolls over."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _read_global_counter() -> tuple[str, int]:
    """Return (date_key, count) from disk; resets if the date moved on."""
    if not COUNTER_PATH.exists():
        return (_today_key(), 0)
    try:
        with COUNTER_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        date_key = data.get("date") or ""
        count = int(data.get("count", 0) or 0)
        if date_key != _today_key():
            return (_today_key(), 0)
        return (date_key, count)
    except (OSError, ValueError, json.JSONDecodeError) as e:
        logger.warning("rate_limit: counter unreadable, resetting: %s", e)
        return (_today_key(), 0)


def _write_global_counter(date_key: str, count: int) -> None:
    """Atomic write of the global counter. Best-effort; logs and continues on error."""
    try:
        COUNTER_PATH.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            prefix="daily_count.", suffix=".tmp", dir=str(COUNTER_PATH.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"date": date_key, "count": count}, f)
            os.replace(tmp, COUNTER_PATH)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except Exception as e:  # noqa: BLE001
        logger.warning("rate_limit: counter write failed: %s", e)


# ---- Public API ------------------------------------------------------------


class Decision(NamedTuple):
    """Outcome of a rate-limit check.

    `allowed` — True if the caller may proceed.
    `reason` — short tag identifying the reason ("ok" / "ip" / "global").
    `remaining_global` — how many runs are left today across all visitors.
    `remaining_ip` — how many runs are left this hour for this IP.
    """

    allowed: bool
    reason: str
    remaining_global: int
    remaining_ip: int


def check(ip: str | None) -> Decision:
    """Non-mutating check — would a request from `ip` be allowed right now?

    The Streamlit UI uses `check()` to render the demo banner with live
    remaining quotas before the user even clicks Run. The actual debit
    happens in `consume()` once the run starts.
    """
    if DISABLED:
        return Decision(True, "ok", GLOBAL_PER_DAY, PER_IP_PER_HOUR)

    _, global_count = _read_global_counter()
    rem_global = max(GLOBAL_PER_DAY - global_count, 0)

    ip_key = ip or "_anon_"
    with _per_ip_lock:
        stamps = _per_ip[ip_key]
        _prune_ip_window(stamps)
        rem_ip = max(PER_IP_PER_HOUR - len(stamps), 0)

    if rem_global <= 0:
        return Decision(False, "global", 0, rem_ip)
    if rem_ip <= 0:
        return Decision(False, "ip", rem_global, 0)
    return Decision(True, "ok", rem_global, rem_ip)


def consume(ip: str | None) -> Decision:
    """Try to consume a slot for `ip`. Atomic: per-IP and global decrement
    together, OR neither moves (if either cap is hit).

    Returns the post-decision state. If `allowed=False`, no counter was
    touched.
    """
    if DISABLED:
        return Decision(True, "ok", GLOBAL_PER_DAY, PER_IP_PER_HOUR)

    date_key, global_count = _read_global_counter()
    if global_count >= GLOBAL_PER_DAY:
        ip_key = ip or "_anon_"
        with _per_ip_lock:
            _prune_ip_window(_per_ip[ip_key])
            rem_ip = max(PER_IP_PER_HOUR - len(_per_ip[ip_key]), 0)
        return Decision(False, "global", 0, rem_ip)

    ip_key = ip or "_anon_"
    with _per_ip_lock:
        stamps = _per_ip[ip_key]
        _prune_ip_window(stamps)
        if len(stamps) >= PER_IP_PER_HOUR:
            return Decision(
                False,
                "ip",
                max(GLOBAL_PER_DAY - global_count, 0),
                0,
            )
        # Charge both counters.
        stamps.append(time.time())
        rem_ip = max(PER_IP_PER_HOUR - len(stamps), 0)

    new_count = global_count + 1
    _write_global_counter(date_key, new_count)
    return Decision(
        True,
        "ok",
        max(GLOBAL_PER_DAY - new_count, 0),
        rem_ip,
    )


def detect_ip() -> str | None:
    """Best-effort IP detection in a Streamlit context.

    Uses `st.context.headers` (1.28+). On HF Space the `x-forwarded-for`
    header is set by the reverse proxy; locally it usually isn't, in
    which case every visitor shares the `_anon_` bucket — which is fine
    because the global cap still protects the key.
    """
    try:
        import streamlit as st

        headers = getattr(st, "context", None)
        if headers is None:
            return None
        h = getattr(headers, "headers", {}) or {}
        xff = h.get("x-forwarded-for") or h.get("X-Forwarded-For")
        if xff:
            # x-forwarded-for can be a comma-separated chain; take the first.
            return xff.split(",")[0].strip()
        return h.get("x-real-ip") or h.get("X-Real-Ip")
    except Exception:  # noqa: BLE001 — never fail the request because of IP detection
        return None
