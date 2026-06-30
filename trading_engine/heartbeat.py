from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict

HEARTBEAT_KEY = "engine:heartbeat"

_redis_client = None
_redis_unavailable = False


def _client():
    """Lazily connect to Redis. Returns None if redis isn't installed/reachable
    so the trading engine keeps running standalone (e.g. local/offline use)
    without this purely observational heartbeat ever affecting signal logic."""
    global _redis_client, _redis_unavailable
    if _redis_unavailable:
        return None
    if _redis_client is not None:
        return _redis_client
    try:
        import redis

        url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        client = redis.from_url(url, decode_responses=True, socket_connect_timeout=2)
        client.ping()
        _redis_client = client
        return client
    except Exception:
        _redis_unavailable = True
        return None


def write_heartbeat(mode: str, instrument_mode: str | None = None, detail: str | None = None) -> None:
    client = _client()
    if client is None:
        return
    payload: Dict[str, Any] = {
        "mode": mode,
        "instrument_mode": instrument_mode,
        "detail": detail,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        client.set(HEARTBEAT_KEY, json.dumps(payload), ex=120)
    except Exception:
        pass
