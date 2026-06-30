from __future__ import annotations

import json
import os
from typing import Any

import redis

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

EMERGENCY_STOP_KEY = "engine:emergency_stop"
ENGINE_STATE_KEY = "engine:state"
HEARTBEAT_KEY = "engine:heartbeat"
RATE_LIMIT_PREFIX = "ratelimit:"


def get_redis() -> redis.Redis:
    return redis.from_url(REDIS_URL, decode_responses=True)


def set_engine_state(state: dict[str, Any]) -> None:
    get_redis().set(ENGINE_STATE_KEY, json.dumps(state))


def get_engine_state() -> dict[str, Any] | None:
    raw = get_redis().get(ENGINE_STATE_KEY)
    return json.loads(raw) if raw else None


def set_emergency_stop(active: bool) -> None:
    r = get_redis()
    if active:
        r.set(EMERGENCY_STOP_KEY, "1")
    else:
        r.delete(EMERGENCY_STOP_KEY)


def is_emergency_stopped() -> bool:
    return get_redis().exists(EMERGENCY_STOP_KEY) == 1


def get_heartbeat() -> dict[str, Any] | None:
    """Returns the trading_engine's last heartbeat payload, or None if missing/
    expired/unreachable. The heartbeat key has a TTL set by the engine itself,
    so its mere presence indicates the engine process is alive and recent."""
    try:
        raw = get_redis().get(HEARTBEAT_KEY)
    except Exception:
        return None
    return json.loads(raw) if raw else None


def acquire_rate_limit_lock(name: str, ttl_seconds: int = 5) -> bool:
    """Returns True if the lock was acquired (i.e. caller may proceed)."""
    return bool(get_redis().set(f"{RATE_LIMIT_PREFIX}{name}", "1", nx=True, ex=ttl_seconds))
