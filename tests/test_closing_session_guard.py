import pandas as pd

from trading_engine.signal_engine.trades import build_trades


def _calc(rows):
    return pd.DataFrame(
        {
            "datetime": pd.to_datetime([t for t, _, _ in rows]).tz_localize("Asia/Kolkata"),
            "close": [p for _, p, _ in rows],
            "signal": [s for _, _, s in rows],
        }
    )


def _cfg(enabled=True):
    return {
        "instrument": {"lot_size": 65},
        "entry_filters": {
            "enable_time_block_filter": False,
            "closing_session_guard": {"enabled": enabled, "cutoff": "15:15"},
        },
        "risk_management": {"mode": "NONE", "enable_mae_exit": False},
    }


def test_signal_on_1514_candle_can_enter():
    calc = _calc([("2026-11-11 15:13", 100, ""), ("2026-11-11 15:14", 101, "BUY")])
    _, trades, summary = build_trades(calc, _cfg())
    assert summary["current_position"] == "LONG"
    assert summary["current_entry_price"] == 101


def test_signal_after_cutoff_does_not_enter():
    calc = _calc([("2026-11-11 15:14", 100, ""), ("2026-11-11 15:20", 105, "BUY")])
    signals, trades, summary = build_trades(calc, _cfg())
    assert summary["current_position"] == "FLAT"
    assert trades.empty
    assert bool(signals.iloc[-1]["closing_session_blocked"]) is True


def test_opposite_signal_after_cutoff_exits_without_reversing():
    calc = _calc([
        ("2026-11-11 14:00", 100, "BUY"),
        ("2026-11-11 15:20", 110, "SELL"),
    ])
    _, trades, summary = build_trades(calc, _cfg())
    assert summary["current_position"] == "FLAT"
    assert len(trades) == 1
    assert trades.iloc[0]["exit_signal"] == "SELL"
    assert trades.iloc[0]["points"] == 10


def test_position_held_overnight_without_opposite_signal():
    calc = _calc([
        ("2026-11-11 14:00", 100, "BUY"),
        ("2026-11-11 15:20", 108, "BUY"),
        ("2026-11-11 15:29", 109, ""),
        ("2026-11-12 09:15", 112, ""),
    ])
    _, trades, summary = build_trades(calc, _cfg())
    assert summary["current_position"] == "LONG"
    assert summary["current_entry_price"] == 100
    assert trades.empty


def test_next_session_entries_allowed_again():
    calc = _calc([("2026-11-11 15:20", 100, "BUY"), ("2026-11-12 09:16", 101, "BUY")])
    _, _, summary = build_trades(calc, _cfg())
    assert summary["current_position"] == "LONG"
    assert summary["current_entry_price"] == 101


def test_guard_disabled_keeps_old_behaviour():
    calc = _calc([("2026-11-11 14:00", 100, "BUY"), ("2026-11-11 15:20", 110, "SELL")])
    _, _, summary = build_trades(calc, _cfg(enabled=False))
    assert summary["current_position"] == "SHORT"
