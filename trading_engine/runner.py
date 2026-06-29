from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, time as dtime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import pandas as pd
import pytz

from trading_engine.data.loaders import filter_session, load_csv, parse_dt
from trading_engine.data.cache import ensure_broker_data
from trading_engine.signal_engine.indicator import calculate_pine_replica
from trading_engine.signal_engine.trades import build_trades
from trading_engine.execution_engine.execution import ExecutionManager
from trading_engine.instrument_selector.instrument_selector import select_nearest_futures, apply_execution_instrument


# -----------------------------------------------------------------------------
# Paths / outputs
# -----------------------------------------------------------------------------

def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def ensure_dirs(cfg: Dict[str, Any]) -> Path:
    out = project_root() / cfg.get("engine", {}).get("output_dir", "outputs")
    out.mkdir(parents=True, exist_ok=True)
    (project_root() / cfg.get("engine", {}).get("log_dir", "logs")).mkdir(parents=True, exist_ok=True)
    return out


def write_outputs(out_dir: Path, calc: pd.DataFrame, signals: pd.DataFrame, trades: pd.DataFrame, summary: Dict[str, Any], prefix: str = "") -> None:
    pfx = f"{prefix}_" if prefix else ""
    calc.to_csv(out_dir / f"{pfx}bars_with_indicators.csv", index=False)
    signals.to_csv(out_dir / f"{pfx}signals.csv", index=False)
    trades.to_csv(out_dir / f"{pfx}trades.csv", index=False)
    serializable = {k: (str(v) if isinstance(v, (pd.Timestamp, datetime)) else v) for k, v in summary.items()}
    for nested_key in ["last_signal", "last_risk_exit"]:
        if isinstance(serializable.get(nested_key), dict):
            serializable[nested_key] = {
                k: (str(v) if isinstance(v, (pd.Timestamp, datetime)) else v)
                for k, v in serializable[nested_key].items()
            }
    (out_dir / f"{pfx}summary.json").write_text(json.dumps(serializable, indent=2, default=str), encoding="utf-8")


# -----------------------------------------------------------------------------
# Market calendar / session state
# -----------------------------------------------------------------------------

def _tz(cfg: Dict[str, Any]):
    return pytz.timezone(cfg.get("engine", {}).get("timezone", "Asia/Kolkata"))


def _parse_clock(value: str | None, default: str) -> dtime:
    txt = (value or default).strip()
    parts = [int(x) for x in txt.split(":")]
    if len(parts) == 2:
        return dtime(parts[0], parts[1], 0)
    return dtime(parts[0], parts[1], parts[2])


def _localize_date_time(tz, date_obj, clock: dtime) -> pd.Timestamp:
    return pd.Timestamp(datetime.combine(date_obj, clock), tz=tz)


def _holiday_set(cfg: Dict[str, Any]) -> set[str]:
    market = cfg.get("market", {}) or {}
    return {str(x) for x in market.get("holidays", []) or []}


def is_trading_day(day: pd.Timestamp | datetime, cfg: Dict[str, Any]) -> bool:
    ts = pd.Timestamp(day)
    date_str = str(ts.date())
    if ts.weekday() >= 5:
        return False
    if date_str in _holiday_set(cfg):
        return False
    return True


def next_trading_session(now: pd.Timestamp, cfg: Dict[str, Any]) -> pd.Timestamp:
    tz = _tz(cfg)
    instr = cfg.get("instrument", {}) or {}
    market = cfg.get("market", {}) or {}
    session_start = _parse_clock(market.get("session_start") or instr.get("session_start"), "09:15")
    candidate = now
    # If today is a trading day and market has not opened yet, next session is today.
    today_open = _localize_date_time(tz, candidate.date(), session_start)
    if is_trading_day(candidate, cfg) and now < today_open:
        return today_open
    # Otherwise advance day-by-day.
    for i in range(1, 20):
        d = (candidate + pd.Timedelta(days=i)).date()
        ts = _localize_date_time(tz, d, session_start)
        if is_trading_day(ts, cfg):
            return ts
    raise RuntimeError("Could not locate the next trading session within 20 calendar days. Check market.holidays config.")


def market_state(now: pd.Timestamp, cfg: Dict[str, Any]) -> Tuple[str, str, Optional[pd.Timestamp]]:
    """Return (state, display, next_session).

    States:
      CLOSED_WEEKEND, CLOSED_HOLIDAY, PRE_MARKET, OPENING_RANGE, LIVE, POST_MARKET
    """
    tz = _tz(cfg)
    instr = cfg.get("instrument", {}) or {}
    market = cfg.get("market", {}) or {}
    session_start = _parse_clock(market.get("session_start") or instr.get("session_start"), "09:15")
    session_end = _parse_clock(market.get("session_end") or instr.get("session_end"), "15:30")
    first_trade = _parse_clock(market.get("first_trade_time"), (market.get("session_start") or instr.get("session_start") or "09:15"))

    if now.weekday() >= 5:
        return "CLOSED_WEEKEND", "CLOSED (Weekend)", next_trading_session(now, cfg)
    if str(now.date()) in _holiday_set(cfg):
        return "CLOSED_HOLIDAY", "CLOSED (Holiday)", next_trading_session(now, cfg)

    start_ts = _localize_date_time(tz, now.date(), session_start)
    first_trade_ts = _localize_date_time(tz, now.date(), first_trade)
    end_ts = _localize_date_time(tz, now.date(), session_end)

    if now < start_ts:
        return "PRE_MARKET", "PRE-MARKET", start_ts
    if start_ts <= now < first_trade_ts:
        return "OPENING_RANGE", "OPEN - Opening Range / No-Trade Window", first_trade_ts
    if first_trade_ts <= now < end_ts:
        return "LIVE", "OPEN", None
    return "POST_MARKET", "CLOSED (Post Market)", next_trading_session(now, cfg)


def _format_timedelta(delta: pd.Timedelta | timedelta) -> str:
    total = max(0, int(delta.total_seconds()))
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    mins, secs = divmod(rem, 60)
    if days:
        return f"{days}d {hours:02d}h {mins:02d}m {secs:02d}s"
    return f"{hours:02d}h {mins:02d}m {secs:02d}s"


def _session_wait_message(now: pd.Timestamp, target: Optional[pd.Timestamp], label: str) -> str:
    if target is None:
        return ""
    return f"{label}: {target.strftime('%Y-%m-%d %H:%M:%S %Z')} | Time left: {_format_timedelta(target - now)}"


# -----------------------------------------------------------------------------
# Dashboards
# -----------------------------------------------------------------------------

def print_dashboard(cfg: Dict[str, Any], summary: Dict[str, Any], signals: pd.DataFrame, trades: pd.DataFrame) -> None:
    instr = cfg.get("instrument", {})
    engine = cfg.get("engine", {})
    print("\n" + "=" * 72)
    print("SVMKR UT HMA ORB CHOP-NO-ADX ENGINE")
    print("=" * 72)
    print(f"Mode              : {engine.get('mode')}")
    print(f"Signal Instrument : {instr.get('symbol')} / {instr.get('tradingsymbol')} / token {instr.get('symboltoken')}")
    resolved_exe = ((cfg.get("execution", {}) or {}).get("resolved_instrument", {}) or {})
    if resolved_exe:
        print(f"Execution Instr.  : {resolved_exe.get('tradingsymbol')} / token {resolved_exe.get('symboltoken')} / lot {resolved_exe.get('lot_size')}")
    print(f"Timeframe         : {instr.get('interval')}")
    print(f"Signals           : {summary.get('signals', 0)}")
    print(f"Closed Trades     : {summary.get('closed_trades', 0)}")
    print(f"Wins/Loss/Flat    : {summary.get('wins', 0)} / {summary.get('losses', 0)} / {summary.get('flat', 0)}")
    print(f"Win Rate          : {summary.get('win_rate', 0):.2f}%")
    print(f"Net Points        : {summary.get('net_points', 0):.2f}")
    print(f"Open Points       : {summary.get('open_points', 0):.2f}")
    print(f"Best/Worst        : {summary.get('best_trade')} / {summary.get('worst_trade')}")
    print(f"Current Position  : {summary.get('current_position')}")
    if summary.get("current_entry_price") is not None:
        print(f"Current Entry     : {summary.get('current_entry_time')} @ {summary.get('current_entry_price')}")
    print("-" * 72)
    print("Last 10 Signals")
    print("No signals yet." if signals.empty else signals.tail(10).to_string(index=False))
    print("-" * 72)
    print("Last 10 Closed Trades")
    print("No closed trades yet." if trades.empty else trades.tail(10).to_string(index=False))
    print("=" * 72 + "\n")


def _format_live_signal_results(cfg: Dict[str, Any], trades: pd.DataFrame, summary: Dict[str, Any], limit: int | None = 10) -> pd.DataFrame:
    lot_size = float(cfg.get("instrument", {}).get("lot_size", 1) or 1)
    lots = int(cfg.get("trading", {}).get("lots", cfg.get("instrument", {}).get("lots", 1)) or 1)
    rows = []

    if trades is not None and not trades.empty:
        keep_cols = [
            "entry_time", "entry_signal", "entry_price",
            "exit_time", "exit_signal", "exit_price",
            "position", "points", "pnl_value",
        ]
        for _, r in trades[keep_cols].iterrows():
            row = r.to_dict()
            row["status"] = "CLOSED"
            rows.append(row)

    current_position = summary.get("current_position", "FLAT")
    entry_time = summary.get("current_entry_time")
    entry_price = summary.get("current_entry_price")
    if current_position != "FLAT" and entry_time is not None and entry_price is not None:
        open_points = float(summary.get("open_points", 0.0) or 0.0)
        rows.append({
            "entry_time": entry_time,
            "entry_signal": "BUY" if current_position == "LONG" else "SELL",
            "entry_price": float(entry_price),
            "exit_time": "OPEN",
            "exit_signal": "OPEN",
            "exit_price": "OPEN",
            "position": current_position,
            "points": open_points,
            "pnl_value": open_points * lot_size * lots,
            "status": "OPEN",
        })

    cols = [
        "entry_time", "entry_signal", "entry_price",
        "exit_time", "exit_signal", "exit_price",
        "position", "points", "pnl_value", "status",
    ]
    if not rows:
        return pd.DataFrame(columns=cols)
    result = pd.DataFrame(rows, columns=cols).reset_index(drop=True)
    if limit is not None and int(limit) > 0:
        return result.tail(int(limit)).reset_index(drop=True)
    return result


def print_live_dashboard(
    cfg: Dict[str, Any],
    summary: Dict[str, Any],
    signals: pd.DataFrame,
    trades: pd.DataFrame,
    market_status: str = "OPEN",
    exit_message: str | None = None,
    next_session_message: str | None = None,
    show_signal_results: bool = True,
) -> None:
    instr = cfg.get("instrument", {})
    engine = cfg.get("engine", {})
    last_signal = summary.get("last_signal") or {}
    current_position = summary.get("current_position", "FLAT")
    current_entry_time = summary.get("current_entry_time")
    current_entry_price = summary.get("current_entry_price")
    open_points = float(summary.get("open_points", 0.0) or 0.0)
    lot_size = float(instr.get("lot_size", 1) or 1)
    lots = int(cfg.get("trading", {}).get("lots", instr.get("lots", 1)) or 1)
    open_pnl = open_points * lot_size * lots

    print("\n" + "=" * 72)
    print("SVMKR UT HMA ORB CHOP-NO-ADX LIVE STATUS")
    print("=" * 72)
    print(f"Market Status     : {market_status}")
    print(f"Mode              : {engine.get('mode')}")
    print(f"Signal Instrument : {instr.get('symbol')} / {instr.get('tradingsymbol')} / token {instr.get('symboltoken')}")
    resolved_exe = ((cfg.get("execution", {}) or {}).get("resolved_instrument", {}) or {})
    if resolved_exe:
        print(f"Execution Instr.  : {resolved_exe.get('tradingsymbol')} / token {resolved_exe.get('symboltoken')} / lot {resolved_exe.get('lot_size')}")
    print(f"Timeframe         : {instr.get('interval')}")
    mae_enabled = bool(summary.get("mae_enabled", False))
    mae_points = summary.get("mae_points")
    if mae_enabled and mae_points is not None:
        print(f"Risk Control      : MAE EXIT enabled / {float(mae_points):.2f} points")
    else:
        print("Risk Control      : MAE EXIT disabled")
    if summary.get("time_block_filter_enabled"):
        windows = ", ".join(summary.get("blocked_entry_windows") or [])
        print(f"Entry Time Filter : enabled / {windows}")
    else:
        print("Entry Time Filter : disabled")
    print("-" * 72)
    print("CURRENT STATUS")
    print(f"Current Position  : {current_position}")
    if current_entry_price is not None:
        print(f"Current Entry     : {current_entry_time} @ {current_entry_price}")
        print(f"Open Points       : {open_points:.2f}")
        print(f"Open PnL          : {open_pnl:.2f}")
        if mae_enabled and mae_points is not None:
            remaining = max(0.0, float(mae_points) + open_points) if open_points < 0 else float(mae_points)
            print(f"MAE Limit         : {float(mae_points):.2f}")
            print(f"Risk Left to MAE  : {remaining:.2f}")
    else:
        print("Current Entry     : None")
        print("Open Points       : 0.00")
        print("Open PnL          : 0.00")
    if last_signal:
        print(f"Last Signal       : {last_signal.get('signal')} @ {last_signal.get('price')} on {last_signal.get('datetime')}")
        if str(last_signal.get("signal", "")).startswith("MAE_EXIT"):
            print("Last Action       : Risk exit hit; engine is flat until next fresh BUY/SELL signal")
    else:
        print("Last Signal       : None")
    if next_session_message:
        print(next_session_message)
    if show_signal_results:
        print("-" * 72)
        print("LAST 10 SIGNAL RESULTS")
        results = _format_live_signal_results(cfg, trades, summary)
        if results.empty:
            print("No reconstructed signal results found in warmup window.")
        else:
            display = results.copy()
            for col in ["entry_price", "points", "pnl_value"]:
                if col in display.columns:
                    display[col] = display[col].map(lambda x: f"{float(x):.2f}" if pd.notna(x) and str(x) != "OPEN" else x)
            if "exit_price" in display.columns:
                display["exit_price"] = display["exit_price"].map(lambda x: f"{float(x):.2f}" if str(x) != "OPEN" and pd.notna(x) else x)
            print(display.to_string(index=False))
    if exit_message:
        print("-" * 72)
        print(exit_message)
    print("=" * 72 + "\n")


# -----------------------------------------------------------------------------
# Backtest / replay
# -----------------------------------------------------------------------------

def _backtest_required_range(cfg: Dict[str, Any], start: Optional[pd.Timestamp], end: Optional[pd.Timestamp]) -> tuple[pd.Timestamp, pd.Timestamp]:
    tz = _tz(cfg)
    live = cfg.get("live", {}) or {}
    bt = cfg.get("backtest", {}) or {}
    if start is None:
        raw_start = bt.get("start") or ""
        start = parse_dt(raw_start, cfg.get("engine", {}).get("timezone", "Asia/Kolkata"))
    if end is None:
        raw_end = bt.get("end") or ""
        end = parse_dt(raw_end, cfg.get("engine", {}).get("timezone", "Asia/Kolkata"))
    if start is None or end is None:
        raise ValueError("Backtest needs --from and --to, or backtest.start/backtest.end in config/config.yaml")
    # Date-only --to should include the full day.
    if str(end.time()) == "00:00:00":
        end = end + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
    warmup_days = int(bt.get("warmup_days", live.get("warmup_days", 10)) or 10)
    mult = int(bt.get("warmup_calendar_multiplier", live.get("warmup_calendar_multiplier", 3)) or 3)
    required_start = start - pd.Timedelta(days=warmup_days * mult)
    return required_start, end


def _summarize_backtest(cfg: Dict[str, Any], summary: Dict[str, Any], start: pd.Timestamp, end: pd.Timestamp, export_path: Path, results: pd.DataFrame) -> None:
    instr = cfg.get("instrument", {}) or {}
    print("\n" + "=" * 72)
    print("SVMKR UT HMA ORB CHOP-NO-ADX BACKTEST RESULTS")
    print("=" * 72)
    print(f"From              : {start}")
    print(f"To                : {end}")
    print(f"Instrument        : {instr.get('symbol')} / {instr.get('tradingsymbol')} / token {instr.get('symboltoken')}")
    print(f"Timeframe         : {instr.get('interval')}")
    if summary.get("mae_enabled"):
        print(f"Risk Control      : MAE EXIT enabled / {float(summary.get('mae_points') or 0):.2f} points")
    else:
        print("Risk Control      : MAE EXIT disabled")
    if summary.get("time_block_filter_enabled"):
        windows = ", ".join(summary.get("blocked_entry_windows") or [])
        print(f"Entry Time Filter : enabled / {windows}")
    else:
        print("Entry Time Filter : disabled")
    print(f"Indicator Signals : {summary.get('signals', 0)}")
    print(f"Closed Trades     : {summary.get('closed_trades', 0)}")
    print(f"Open Trades       : {1 if summary.get('current_position') != 'FLAT' else 0}")
    print(f"Wins/Loss/Flat    : {summary.get('wins', 0)} / {summary.get('losses', 0)} / {summary.get('flat', 0)}")
    print(f"Win Rate          : {summary.get('win_rate', 0):.2f}%")
    print(f"Net Points        : {summary.get('net_points', 0):+.2f}")
    print(f"PnL               : {float(summary.get('net_points', 0) or 0) * float(instr.get('lot_size', 1)) * int(cfg.get('trading', {}).get('lots', 1)):+.2f}")
    print(f"Best/Worst        : {summary.get('best_trade')} / {summary.get('worst_trade')}")
    print(f"Current Position  : {summary.get('current_position')}")
    print(f"Export            : {export_path}")
    print("-" * 72)
    print("SIGNAL RESULTS")
    if results.empty:
        print("No trades/signals found in selected range.")
    else:
        if summary.get("mae_enabled") and "points" in results.columns:
            pts = pd.to_numeric(results["points"].replace("OPEN", pd.NA), errors="coerce")
            mae_points = float(summary.get("mae_points") or 0)
            bad_losses = results[(pts < -mae_points - 1e-9) & (results.get("status") == "CLOSED")]
            if not bad_losses.empty:
                print("WARNING: Some closed losses exceed the configured MAE cap. Check whether those rows were generated before MAE was enabled.")
        display = results.copy()
        print(f"Showing {len(display)} of {len(results)} trades")
        for col in ["entry_price", "points", "pnl_value"]:
            if col in display.columns:
                display[col] = display[col].map(lambda x: f"{float(x):.2f}" if pd.notna(x) and str(x) != "OPEN" else x)
        if "exit_price" in display.columns:
            display["exit_price"] = display["exit_price"].map(lambda x: f"{float(x):.2f}" if str(x) != "OPEN" and pd.notna(x) else x)
        print(display.to_string(index=False))
    print("=" * 72 + "\n")


def run_backtest(cfg: Dict[str, Any]) -> None:
    out_dir = ensure_dirs(cfg)
    bt = cfg.get("backtest", {}) or {}
    eng = cfg.get("engine", {}) or {}
    instr = cfg.get("instrument", {}) or {}
    tzname = eng.get("timezone", "Asia/Kolkata")

    start = parse_dt(bt.get("start"), tzname)
    end = parse_dt(bt.get("end"), tzname)
    if end is not None and str(end.time()) == "00:00:00":
        end = end + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
    required_start, required_end = _backtest_required_range(cfg, start, end)

    explicit_csv = bool(bt.get("csv_path")) and bool(bt.get("use_csv", False))
    source = str(bt.get("source", "broker") or "broker").lower()

    if explicit_csv or source == "csv":
        csv_path = bt.get("csv_path") or instr.get("csv_path")
        if not csv_path:
            raise ValueError("CSV backtest source needs backtest.csv_path")
        print(f"Backtest Data Source : CSV ({csv_path})")
        df = load_csv(csv_path, cfg)
        available = "EMPTY" if df.empty else f"{df['datetime'].min()} -> {df['datetime'].max()}"
        print(f"CSV Available Range  : {available}")
        if df.empty or df["datetime"].max() < required_start or df["datetime"].min() > required_end:
            raise RuntimeError(
                "CSV does not contain the requested backtest range.\n"
                f"Requested Range   : {start} -> {end}\n"
                f"Warmup Required   : {required_start} -> {required_end}\n"
                f"CSV Range         : {available}\n"
                "Use broker source or provide a CSV covering the range."
            )
        df = df[(df["datetime"] >= required_start) & (df["datetime"] <= required_end)].copy()
    else:
        print("Backtest Data Source : AngelOne Historical API + local cache")
        from trading_engine.broker_adapters.angelone import AngelOneBroker
        broker = AngelOneBroker(cfg)
        broker.connect()
        print("AngelOne login successful.")
        df = ensure_broker_data(cfg, broker, required_start, required_end, purpose="backtest", force_refresh=bool(bt.get("force_refresh", False)))

    df = filter_session(df, instr.get("session_start"), instr.get("session_end"))
    calc = calculate_pine_replica(df, cfg)
    signals, trades, summary = build_trades(calc, cfg, start=start, end=end)
    window = calc.copy()
    if start is not None:
        window = window[window["datetime"] >= start]
    if end is not None:
        window = window[window["datetime"] <= end]

    # Unified result table including current open trade, same as live dashboard.
    # Backtest must include ALL signal/trade results for the requested range.
    # Live dashboard intentionally keeps the last 10 only, but backtest reporting
    # and CSV export should never use that live truncation.
    results = _format_live_signal_results(cfg, trades, summary, limit=None)
    export_arg = bt.get("export") or "backtest_results.csv"
    export_path = Path(export_arg)
    if not export_path.is_absolute():
        export_path = out_dir / export_path
    export_path.parent.mkdir(parents=True, exist_ok=True)
    results.to_csv(export_path, index=False)

    write_outputs(out_dir, window, signals, trades, summary, prefix="backtest")
    _summarize_backtest(cfg, summary, start, end, export_path, results)
    print(f"Files written to: {out_dir}")

def run_replay(cfg: Dict[str, Any]) -> None:
    out_dir = ensure_dirs(cfg)
    replay = cfg.get("replay", {})
    eng = cfg.get("engine", {})
    instr = cfg.get("instrument", {})
    csv_path = replay.get("csv_path") or cfg.get("backtest", {}).get("csv_path")
    df = load_csv(csv_path, cfg) if csv_path else pd.DataFrame()
    until = parse_dt(replay.get("until"), eng.get("timezone", "Asia/Kolkata"))
    if not csv_path or df.empty:
        raise ValueError("Replay mode needs replay.csv_path with candles in config/config.yaml")
    if until is None:
        until = df["datetime"].max()
        print(f"Replay until not set; using latest CSV candle: {until}")
    latest_date = df["datetime"].max().date()
    today_date = pd.Timestamp.now(tz=eng.get("timezone", "Asia/Kolkata")).date()
    if latest_date < today_date:
        print(f"WARNING: Replay CSV latest candle is {latest_date}; this is historical data, not current live market data.")
    df = filter_session(df, instr.get("session_start"), instr.get("session_end"))
    df = df[df["datetime"] <= until].reset_index(drop=True)
    calc = calculate_pine_replica(df, cfg)
    signals, trades, summary = build_trades(calc, cfg, end=until)
    write_outputs(out_dir, calc, signals, trades, summary, prefix="replay")
    print_live_dashboard(cfg, summary, signals, trades, market_status="REPLAY")
    print(f"Files written to: {out_dir}")


# -----------------------------------------------------------------------------
# Live / state machine
# -----------------------------------------------------------------------------

def _drop_unclosed_last_candle(df: pd.DataFrame, interval_minutes: int, now: pd.Timestamp) -> pd.DataFrame:
    if df.empty:
        return df
    last_dt = df.iloc[-1]["datetime"]
    close_time = last_dt + pd.Timedelta(minutes=interval_minutes)
    if now < close_time:
        return df.iloc[:-1].copy()
    return df


def _warmup_start(now: pd.Timestamp, cfg: Dict[str, Any]) -> pd.Timestamp:
    live = cfg.get("live", {}) or {}
    # Calendar days are multiplied to survive weekends/holidays while still simple.
    days = int(live.get("warmup_days", 10) or 10) * int(live.get("warmup_calendar_multiplier", 3) or 3)
    return now - pd.Timedelta(days=days)


def _reconstruct_from_broker(cfg: Dict[str, Any], broker, now: pd.Timestamp, out_dir: Path, prefix: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
    instr = cfg.get("instrument", {}) or {}
    start_dt = _warmup_start(now, cfg).to_pydatetime()
    df = broker.get_candles(start_dt, now.to_pydatetime())
    df = filter_session(df, instr.get("session_start"), instr.get("session_end"))
    df = _drop_unclosed_last_candle(df, broker.interval_minutes, now)
    calc = calculate_pine_replica(df, cfg)
    signals, trades, summary = build_trades(calc, cfg)
    write_outputs(out_dir, calc, signals, trades, summary, prefix=prefix)
    return calc, signals, trades, summary


def _sleep_countdown(cfg: Dict[str, Any], target: pd.Timestamp, label: str) -> None:
    live = cfg.get("live", {}) or {}
    refresh = max(1, int(live.get("pre_market_refresh_seconds", 5) or 5))
    tz = _tz(cfg)
    while True:
        now = pd.Timestamp(datetime.now(tz))
        if now >= target:
            return
        print(f"{label}: {target.strftime('%Y-%m-%d %H:%M:%S %Z')} | Time left: {_format_timedelta(target - now)}", end="\r", flush=True)
        time.sleep(min(refresh, max(1, int((target - now).total_seconds()))))



def _next_candle_fetch_time(now: pd.Timestamp, interval_minutes: int, buffer_seconds: int = 3) -> pd.Timestamp:
    """Return next time when it is useful to call historical candle API.

    AngelOne candle API is rate-limited. For a 5-minute signal engine,
    there is no value in calling it every 10 seconds. We wait until just
    after the next expected candle close, then fetch once.
    """
    minute = (now.minute // interval_minutes) * interval_minutes
    current_bucket = now.replace(minute=minute, second=0, microsecond=0)
    next_close = current_bucket + pd.Timedelta(minutes=interval_minutes)
    due = next_close + pd.Timedelta(seconds=max(0, int(buffer_seconds)))
    if now >= due:
        due = due + pd.Timedelta(minutes=interval_minutes)
    return due


def _is_rate_limit_error(exc: Exception) -> bool:
    txt = str(exc).lower()
    return "access rate" in txt or "exceeding access rate" in txt or "rate" in txt and "exceed" in txt


def _resolve_execution_instrument_if_needed(cfg: Dict[str, Any], broker=None) -> None:
    """Resolve the tradeable NFO instrument at startup.

    FUTURES mode resolves the active futures contract immediately.
    OPTION modes resolve strikes at signal time because CE/PE and strike depend
    on the live underlying price and signal direction.
    """
    execution = cfg.get("execution", {}) or {}
    instrument_mode = str(execution.get("instrument_mode") or execution.get("execution_mode") or "FUTURES").upper()
    selector = execution.get("instrument_selector", {}) or {}
    auto_select = bool(selector.get("enabled", execution.get("auto_select_futures", False)))

    if instrument_mode in {"OPTION_BUYING", "OPTION_SELLING"}:
        # Warm/cache the scrip master so option selection is fast at signal time.
        if auto_select:
            from trading_engine.instrument_selector.instrument_selector import load_scrip_master
            rows = load_scrip_master(cfg, force=bool(selector.get("force_refresh", False)))
            print(f"Instrument list loaded: {len(rows)} contracts")
            print(f"Option execution mode ready: {instrument_mode}. Strikes will be selected on each fresh signal.")
        return

    if not auto_select:
        resolved = execution.get("resolved_instrument", {}) or {}
        if resolved and broker is not None and hasattr(broker, "set_execution_instrument"):
            broker.set_execution_instrument(resolved)
        return
    selected = select_nearest_futures(cfg, force_master_refresh=bool(selector.get("force_refresh", False)))
    apply_execution_instrument(cfg, selected)
    if broker is not None and hasattr(broker, "set_execution_instrument"):
        broker.set_execution_instrument(selected.to_dict())
    print(f"Execution instrument ready: {selected.tradingsymbol} | Token: {selected.symboltoken} | Lot: {selected.lot_size}")


def run_live(cfg: Dict[str, Any]) -> None:
    from trading_engine.broker_adapters.angelone import AngelOneBroker

    out_dir = ensure_dirs(cfg)
    live = cfg.get("live", {}) or {}
    market = cfg.get("market", {}) or {}
    tz = _tz(cfg)
    broker = AngelOneBroker(cfg)
    broker.connect()
    print("AngelOne login successful.")
    _resolve_execution_instrument_if_needed(cfg, broker)
    execution_manager = ExecutionManager(cfg, broker, out_dir)
    execution_started = False

    poll_seconds = max(1, int(live.get("poll_seconds", 10) or 10))
    candle_close_buffer_seconds = max(0, int(live.get("candle_close_buffer_seconds", 5) or 5))
    rate_limit_backoff_seconds = max(60, int(live.get("rate_limit_backoff_seconds", 180) or 180))
    status_refresh_seconds = max(5, int(live.get("status_refresh_seconds", 30) or 30))
    auto_exit = bool(market.get("auto_exit_after_market_close", True))
    stay_alive_closed = bool(market.get("stay_alive_on_closed_day", False))
    post_market_refresh = max(5, int(live.get("post_market_refresh_seconds", 60) or 60))

    last_processed_candle: Optional[pd.Timestamp] = None
    last_dashboard_state: Optional[str] = None
    next_fetch_due: Optional[pd.Timestamp] = None
    last_wait_print: Optional[pd.Timestamp] = None
    startup_signal_results_shown = False

    while True:
        now = pd.Timestamp(datetime.now(tz))
        state, status_text, target = market_state(now, cfg)

        if state in {"CLOSED_WEEKEND", "CLOSED_HOLIDAY"}:
            reason = "weekend" if state == "CLOSED_WEEKEND" else "holiday"
            print(f"Market closed today ({reason}). Reconstructing last state...")
            try:
                _, signals, trades, summary = _reconstruct_from_broker(cfg, broker, now, out_dir, prefix="live_closed_day")
            except Exception as exc:
                print(f"Unable to reconstruct closed-day state: {exc}")
                signals, trades, summary = pd.DataFrame(), pd.DataFrame(), {"current_position": "UNKNOWN", "open_points": 0.0}
            msg = _session_wait_message(now, target, "Next trading session")
            print_live_dashboard(cfg, summary, signals, trades, market_status=status_text, exit_message=(msg + ("\nEngine exiting gracefully." if not stay_alive_closed else "")), show_signal_results=not startup_signal_results_shown)
            startup_signal_results_shown = True
            if not stay_alive_closed:
                return
            _sleep_countdown(cfg, target, "Waiting for next trading session")
            continue

        if state in {"PRE_MARKET", "OPENING_RANGE"}:
            if last_dashboard_state != state:
                print("Startup reconstruction complete using historical warmup candles.")
                _, signals, trades, summary = _reconstruct_from_broker(cfg, broker, now, out_dir, prefix="live_premarket")
                label = "Market opens at" if state == "PRE_MARKET" else "Trading begins at"
                msg = _session_wait_message(now, target, label)
                print_live_dashboard(cfg, summary, signals, trades, market_status=status_text, next_session_message=msg, show_signal_results=not startup_signal_results_shown)
                startup_signal_results_shown = True
                if not execution_started:
                    execution_manager.startup_sync(summary)
                    execution_started = True
                last_dashboard_state = state
            label = "Waiting for market open" if state == "PRE_MARKET" else "Opening range active; waiting for trading start"
            _sleep_countdown(cfg, target, label)
            continue

        if state == "POST_MARKET":
            print("Market closed. Reconstructing final post-market state...")
            _, signals, trades, summary = _reconstruct_from_broker(cfg, broker, now, out_dir, prefix="live_postmarket")
            msg = _session_wait_message(now, target, "Next trading session")
            suffix = "\nEngine exiting gracefully." if auto_exit else "\nEngine will remain alive and wait for the next session."
            print_live_dashboard(cfg, summary, signals, trades, market_status=status_text, exit_message=msg + suffix, show_signal_results=not startup_signal_results_shown)
            startup_signal_results_shown = True
            if auto_exit:
                return
            time.sleep(post_market_refresh)
            continue

        # LIVE state
        if last_dashboard_state != "LIVE":
            print("Market open. Entering live monitoring mode...")
            last_dashboard_state = "LIVE"
            next_fetch_due = None
            last_wait_print = None

        # Fetch historical candles only when a new completed candle can exist.
        # This avoids AngelOne access-rate throttling from calling getCandleData
        # every 10 seconds for a 5-minute candle strategy.
        if next_fetch_due is None:
            next_fetch_due = now  # immediate first live reconstruction after entering LIVE

        if now < next_fetch_due:
            if last_wait_print is None or (now - last_wait_print).total_seconds() >= status_refresh_seconds:
                print(f"Waiting for next closed candle fetch at {next_fetch_due.strftime('%H:%M:%S %Z')} | Time left: {_format_timedelta(next_fetch_due - now)}")
                last_wait_print = now
            time.sleep(min(poll_seconds, max(1, int((next_fetch_due - now).total_seconds()))))
            continue

        try:
            calc, signals, trades, summary = _reconstruct_from_broker(cfg, broker, now, out_dir, prefix="live_latest")
            latest_closed = calc["datetime"].max() if not calc.empty else None
            if latest_closed is not None and latest_closed != last_processed_candle:
                last_processed_candle = latest_closed
                print_live_dashboard(cfg, summary, signals, trades, market_status=status_text, show_signal_results=False)
                if not execution_started:
                    execution_manager.startup_sync(summary)
                    execution_started = True
                else:
                    execution_manager.align_to_strategy(summary, reason="CANDLE_CLOSE_SIGNAL")
                next_fetch_due = _next_candle_fetch_time(now, broker.interval_minutes, candle_close_buffer_seconds)
                print(f"Processed latest closed candle: {latest_closed}. Next candle fetch at {next_fetch_due.strftime('%H:%M:%S %Z')}.")
            else:
                next_fetch_due = _next_candle_fetch_time(now, broker.interval_minutes, candle_close_buffer_seconds)
                print(f"No new closed candle returned. Next candle fetch at {next_fetch_due.strftime('%H:%M:%S %Z')}.")
        except KeyboardInterrupt:
            print("\nUser interrupted engine. Exiting gracefully.")
            return
        except Exception as exc:
            if _is_rate_limit_error(exc):
                next_fetch_due = pd.Timestamp(datetime.now(tz)) + pd.Timedelta(seconds=rate_limit_backoff_seconds)
                print(f"\nAngelOne rate limit hit. Backing off for {rate_limit_backoff_seconds}s. Next retry at {next_fetch_due.strftime('%H:%M:%S %Z')}.")
            else:
                next_fetch_due = pd.Timestamp(datetime.now(tz)) + pd.Timedelta(seconds=max(poll_seconds, 30))
                print(f"\nLive polling error: {exc}. Retrying at {next_fetch_due.strftime('%H:%M:%S %Z')}.")
        time.sleep(poll_seconds)


def run_from_config(cfg: Dict[str, Any]) -> None:
    mode = str(cfg.get("engine", {}).get("mode", "backtest")).lower()
    if mode == "backtest":
        run_backtest(cfg)
    elif mode == "replay":
        run_replay(cfg)
    elif mode == "live":
        run_live(cfg)
    else:
        raise ValueError("engine.mode must be one of: backtest, replay, live")
