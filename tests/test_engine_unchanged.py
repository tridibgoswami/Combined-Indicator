"""Verifies the restructure didn't change signal/backtest/risk behavior."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from trading_engine.config import load_config
from trading_engine.data.loaders import load_csv, filter_session
from trading_engine.signal_engine.indicator import calculate_pine_replica
from trading_engine.signal_engine.trades import build_trades

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def cfg():
    cfg = load_config(ROOT / "config" / "config.yaml")
    cfg["backtest"]["start"] = "2026-06-01"
    cfg["backtest"]["end"] = "2026-06-01"
    return cfg


def _run(cfg):
    df = load_csv(cfg["backtest"]["csv_path"], cfg)
    df = filter_session(df, cfg["instrument"].get("session_start"), cfg["instrument"].get("session_end"))
    calc = calculate_pine_replica(df, cfg)
    return build_trades(calc, cfg)


def test_backtest_is_deterministic(cfg):
    signals1, trades1, summary1 = _run(cfg)
    signals2, trades2, summary2 = _run(cfg)
    assert summary1["signals"] == summary2["signals"]
    assert summary1["closed_trades"] == summary2["closed_trades"]
    assert summary1["net_points"] == pytest.approx(summary2["net_points"])
    pd.testing.assert_frame_equal(trades1, trades2)


def test_backtest_produces_known_trade_count(cfg):
    _, trades, summary = _run(cfg)
    # Locks in current behavior so future refactors can't silently change it.
    assert summary["closed_trades"] == 3
    assert summary["current_position"] == "LONG"


def test_mae_exit_is_config_driven(cfg):
    cfg["risk_management"]["enable_mae_exit"] = False
    cfg["risk_management"]["mode"] = "NONE"
    _, _, summary_disabled = _run(cfg)
    assert summary_disabled["mae_enabled"] is False

    cfg["risk_management"]["enable_mae_exit"] = True
    cfg["risk_management"]["mode"] = "FIXED_POINTS"
    cfg["risk_management"]["mae_points"] = 30
    _, trades, summary_enabled = _run(cfg)
    assert summary_enabled["mae_enabled"] is True
    closed = trades[trades["points"].notna()]
    assert (closed["points"] >= -30 - 1e-6).all()


def test_entry_time_block_filter_blocks_new_entries(cfg):
    cfg["entry_filters"]["enable_time_block_filter"] = True
    cfg["entry_filters"]["blocked_entry_windows"] = ["00:00-23:59"]
    signals, trades, summary = _run(cfg)
    # Every signal time falls inside the all-day blocked window, so no new
    # entries should be opened.
    assert summary["closed_trades"] == 0
    assert summary["current_position"] == "FLAT"
