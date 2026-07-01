from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
OUTPUTS_DIR = ROOT / "outputs"


def _read_csv(name: str) -> list[dict[str, Any]]:
    path = OUTPUTS_DIR / name
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def get_orders() -> list[dict[str, Any]]:
    return _read_csv("orders.csv")


def _most_recent_path(*names: str) -> Path | None:
    """Return the most recently modified file among the given names in OUTPUTS_DIR."""
    existing = [OUTPUTS_DIR / n for n in names if (OUTPUTS_DIR / n).exists()]
    if not existing:
        return None
    return max(existing, key=lambda p: p.stat().st_mtime)


def get_live_signals() -> list[dict[str, Any]]:
    path = _most_recent_path("live_latest_signals.csv", "live_postmarket_signals.csv")
    if path is None:
        return []
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def get_live_trades() -> list[dict[str, Any]]:
    path = _most_recent_path("live_latest_trades.csv", "live_postmarket_trades.csv")
    if path is None:
        return []
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def get_summary() -> dict[str, Any]:
    path = _most_recent_path("live_latest_summary.json", "live_postmarket_summary.json")
    if path is None:
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _futures_price_near(target_time: str, entry: bool) -> float | None:
    """Return the futures LTP from orders.csv for the order closest to target_time.

    entry=True  → look for an order that opens a position (from_position == "0").
    entry=False → look for an order that closes a position (to_position == "0").
    """
    orders = get_orders()
    if not orders:
        return None
    candidates = []
    for o in orders:
        if not o.get("ltp"):
            continue
        if o.get("instrument_mode", "").upper() != "FUTURES":
            continue
        if entry and str(o.get("from_position", "")) != "0":
            continue
        if not entry and str(o.get("to_position", "")) != "0":
            continue
        candidates.append(o)
    if not candidates:
        return None

    def _to_naive_dt(s: str) -> datetime:
        # Take first 19 chars "YYYY-MM-DD HH:MM:SS" — ignores timezone but is
        # consistent across all rows so relative comparison is correct.
        try:
            return datetime.strptime(str(s).strip()[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
        try:
            return datetime.strptime(str(s).strip()[:19], "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            return datetime.min

    target_dt = _to_naive_dt(target_time)
    best = min(candidates, key=lambda o: abs((_to_naive_dt(o.get("datetime", "")) - target_dt).total_seconds()))
    try:
        return float(best["ltp"])
    except (ValueError, TypeError):
        return None


def get_last_closed_trade() -> dict[str, Any] | None:
    """Return the most recent CLOSED trade enriched with futures prices from orders.csv."""
    from backend_api.app.services.config_service import read_config

    trades = get_live_trades()
    closed = [t for t in trades if t.get("status", "").upper() == "CLOSED"]
    if not closed:
        return None
    last = closed[-1]
    instrument = (read_config() or {}).get("instrument", {}) or {}
    lot_size = float(instrument.get("lot_size", 1) or 1)
    lots = float(instrument.get("lots", 1) or 1)
    try:
        points = float(last.get("points") or 0)
    except (ValueError, TypeError):
        points = 0.0
    pnl_value = last.get("pnl_value")
    if pnl_value is None or pnl_value == "":
        pnl_value = points * lot_size * lots
    else:
        try:
            pnl_value = float(pnl_value)
        except (ValueError, TypeError):
            pnl_value = points * lot_size * lots

    return {
        "signal": last.get("entry_signal"),
        "entry_spot_price": last.get("entry_price"),
        "exit_spot_price": last.get("exit_price"),
        "entry_futures_price": _futures_price_near(last.get("entry_time", ""), entry=True),
        "exit_futures_price": _futures_price_near(last.get("exit_time", ""), entry=False),
        "entry_time": last.get("entry_time"),
        "exit_time": last.get("exit_time"),
        "points": points,
        "final_pnl": pnl_value,
        "exit_reason": last.get("exit_reason"),
    }


def get_pnl() -> dict[str, Any]:
    from backend_api.app.services.config_service import read_config

    summary = get_summary()
    open_points = float(summary.get("open_points", 0) or 0)
    instrument = (read_config() or {}).get("instrument", {}) or {}
    lot_size = float(instrument.get("lot_size", 1) or 1)
    lots = float(instrument.get("lots", 1) or 1)
    return {
        "net_points": summary.get("net_points", 0),
        "open_points": open_points,
        "open_pnl": open_points * lot_size * lots,
        "current_position": summary.get("current_position", "FLAT"),
    }
