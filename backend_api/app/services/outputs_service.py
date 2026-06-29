from __future__ import annotations

import csv
import json
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


def get_live_signals() -> list[dict[str, Any]]:
    return _read_csv("live_latest_signals.csv")


def get_live_trades() -> list[dict[str, Any]]:
    return _read_csv("live_latest_trades.csv")


def get_summary() -> dict[str, Any]:
    path = OUTPUTS_DIR / "live_latest_summary.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def get_pnl() -> dict[str, Any]:
    summary = get_summary()
    return {
        "net_points": summary.get("net_points", 0),
        "open_points": summary.get("open_points", 0),
        "current_position": summary.get("current_position", "FLAT"),
    }
