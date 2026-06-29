from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

import yaml

ROOT = Path(__file__).resolve().parents[1]


def load_env(path: str | Path = ".env") -> None:
    p = Path(path)
    if not p.is_absolute():
        p = ROOT / p
    if not p.exists():
        return
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out



def _as_bool_value(val: Any, default: bool = False) -> bool:
    if val is None or val == "":
        return default
    if isinstance(val, bool):
        return val
    return str(val).strip().lower() in {"1", "true", "yes", "y", "on"}


def env_bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None or val == "":
        return default
    return val.strip().lower() in {"1", "true", "yes", "y", "on"}


def env_int(name: str, default: int) -> int:
    val = os.getenv(name)
    return default if val is None or val == "" else int(val)


def env_float(name: str, default: float) -> float:
    val = os.getenv(name)
    return default if val is None or val == "" else float(val)


def apply_env_overrides(cfg: Dict[str, Any]) -> Dict[str, Any]:
    cfg = deep_merge({}, cfg)
    b = cfg.setdefault("broker", {})
    a = b.setdefault("angelone", {})
    a["api_key"] = os.getenv("ANGELONE_API_KEY", a.get("api_key", ""))
    a["client_id"] = os.getenv("ANGELONE_CLIENT_ID", a.get("client_id", ""))
    a["mpin"] = os.getenv("ANGELONE_MPIN", a.get("mpin", ""))
    a["totp_secret"] = os.getenv("ANGELONE_TOTP_SECRET", a.get("totp_secret", ""))

    t = cfg.setdefault("trading", {})
    t["execute_orders"] = env_bool("EXECUTE_ORDERS", bool(t.get("execute_orders", False)))
    t["paper_trade"] = env_bool("PAPER_TRADE", bool(t.get("paper_trade", True)))
    t["quantity"] = env_int("ORDER_QUANTITY", int(t.get("quantity", 0)))

    e = cfg.setdefault("execution", {})
    e["enabled"] = env_bool("EXECUTION_ENABLED", bool(e.get("enabled", False)))
    if os.getenv("EXECUTION_MODE"):
        e["mode"] = os.getenv("EXECUTION_MODE", e.get("mode", "PAPER")).upper()
    e["allow_live_orders"] = env_bool("ALLOW_LIVE_ORDERS", bool(e.get("allow_live_orders", False)))
    e["lots"] = env_int("EXECUTION_LOTS", int(e.get("lots", t.get("lots", 1)) or 1))
    e["quantity"] = env_int("EXECUTION_QUANTITY", int(e.get("quantity", 0) or 0))
    if os.getenv("EXECUTION_UNDERLYING"):
        e["underlying"] = os.getenv("EXECUTION_UNDERLYING")
        e.setdefault("instrument_selector", {})["underlying"] = os.getenv("EXECUTION_UNDERLYING")
    if os.getenv("EXECUTION_EXPIRY_MODE"):
        e["expiry_mode"] = os.getenv("EXECUTION_EXPIRY_MODE")
        e.setdefault("instrument_selector", {})["expiry_mode"] = os.getenv("EXECUTION_EXPIRY_MODE")
    if os.getenv("TRADE_STARTUP_POSITION") is not None:
        e["trade_reconstructed_position_on_startup"] = env_bool("TRADE_STARTUP_POSITION", bool(e.get("trade_reconstructed_position_on_startup", False)))

    r = cfg.setdefault("risk_management", {})
    if os.getenv("RISK_MODE"):
        r["mode"] = os.getenv("RISK_MODE")
    if os.getenv("ENABLE_MAE_EXIT") is not None:
        r["enable_mae_exit"] = env_bool("ENABLE_MAE_EXIT", _as_bool_value(r.get("enable_mae_exit", False), False))
    if os.getenv("MAE_POINTS"):
        r["mae_points"] = env_float("MAE_POINTS", float(r.get("mae_points", 0) or 0))

    n = cfg.setdefault("notifications", {}).setdefault("telegram", {})
    n["bot_token"] = os.getenv("TELEGRAM_BOT_TOKEN", n.get("bot_token", ""))
    n["chat_id"] = os.getenv("TELEGRAM_CHAT_ID", n.get("chat_id", ""))
    return cfg


def load_config(config_path: str | Path = "config/config.yaml") -> Dict[str, Any]:
    load_env(".env")
    p = Path(config_path)
    if not p.is_absolute():
        p = ROOT / p
    if not p.exists():
        raise FileNotFoundError(f"Config file not found: {p}")
    cfg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return apply_env_overrides(cfg)
