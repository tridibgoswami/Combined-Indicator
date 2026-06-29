from __future__ import annotations

from typing import Any, Dict, Tuple

import pandas as pd


def _points(pos: int, entry: float, exit_: float) -> float:
    return exit_ - entry if pos == 1 else entry - exit_


def _to_bool(val: Any, default: bool = False) -> bool:
    if val is None or val == "":
        return default
    if isinstance(val, bool):
        return val
    return str(val).strip().lower() in {"1", "true", "yes", "y", "on"}


def _risk_settings(cfg: Dict[str, Any]) -> tuple[bool, float | None]:
    """Return (mae_enabled, mae_points). Disabled by default.

    Supports both global risk_management and optional backtest.risk_management
    overrides. This prevents the backtest path from silently running with MAE
    disabled when the user intended FIXED_POINTS.
    """
    risk = dict(cfg.get("risk_management", {}) or {})
    bt_risk = ((cfg.get("backtest", {}) or {}).get("risk_management", {}) or {})
    risk.update(bt_risk)
    mode = str(risk.get("mode", "NONE") or "NONE").strip().upper()
    enabled = _to_bool(risk.get("enable_mae_exit", False), False) or mode in {"FIXED_POINTS", "MAE", "MAE_POINTS"}
    raw_points = risk.get("mae_points", None)
    try:
        points = float(raw_points) if raw_points not in {None, ""} else None
    except (TypeError, ValueError):
        points = None
    if not enabled or points is None or points <= 0 or mode in {"NONE", "OFF", "DISABLED"}:
        return False, None
    return True, points


def _entry_filter_settings(cfg: Dict[str, Any]) -> tuple[bool, list[tuple[str, str]]]:
    """Return (enabled, blocked_windows) for config-driven entry time blocks.

    Supported config:

    entry_filters:
      enable_time_block_filter: true
      blocked_entry_windows:
        - "10:30-11:00"
        - "13:15-13:45"

    The filter blocks NEW entries only. Opposite signals still close an
    existing trade, but reversal entry is suppressed when the signal time is
    inside a blocked window.
    """
    filt = dict(cfg.get("entry_filters", {}) or {})
    enabled = _to_bool(filt.get("enable_time_block_filter", False), False)
    windows_raw = filt.get("blocked_entry_windows", []) or []
    windows: list[tuple[str, str]] = []
    for item in windows_raw:
        if isinstance(item, dict):
            raw = item.get("window", "")
        else:
            raw = str(item)
        raw = raw.strip()
        if not raw or "-" not in raw:
            continue
        start, end = [x.strip() for x in raw.split("-", 1)]
        if start and end:
            windows.append((start, end))
    return enabled and bool(windows), windows


def _parse_hhmm(value: str) -> tuple[int, int]:
    parts = str(value).strip().split(":")
    if len(parts) == 1:
        return int(parts[0]), 0
    return int(parts[0]), int(parts[1])


def _minutes_since_midnight(dt: Any) -> int:
    ts = pd.Timestamp(dt)
    return int(ts.hour) * 60 + int(ts.minute)


def _is_time_blocked(dt: Any, windows: list[tuple[str, str]]) -> bool:
    minute = _minutes_since_midnight(dt)
    for start_raw, end_raw in windows:
        sh, sm = _parse_hhmm(start_raw)
        eh, em = _parse_hhmm(end_raw)
        start_min = sh * 60 + sm
        end_min = eh * 60 + em
        # Interpret end as exclusive. So "10:30-11:00" blocks
        # 10:30 through 10:59:59 and allows 11:00.
        if start_min <= end_min:
            if start_min <= minute < end_min:
                return True
        else:
            # Overnight windows are supported defensively, although NSE
            # intraday settings normally won't use them.
            if minute >= start_min or minute < end_min:
                return True
    return False


def _pnl_value(points: float, cfg: Dict[str, Any]) -> float:
    return points * float(cfg.get("instrument", {}).get("lot_size", 1)) * int(cfg.get("trading", {}).get("lots", 1))


def _close_trade(
    trades: list[dict[str, Any]],
    *,
    entry_time: Any,
    entry_signal: str,
    entry_price: float,
    exit_time: Any,
    exit_signal: str,
    exit_price: float,
    pos: int,
    cfg: Dict[str, Any],
) -> float:
    pts = _points(pos, float(entry_price), float(exit_price))
    trades.append({
        "entry_time": entry_time,
        "entry_signal": entry_signal,
        "entry_price": float(entry_price),
        "exit_time": exit_time,
        "exit_signal": exit_signal,
        "exit_price": float(exit_price),
        "position": "LONG" if pos == 1 else "SHORT",
        "points": pts,
        "pnl_value": _pnl_value(pts, cfg),
        "exit_reason": "MAE" if str(exit_signal).startswith("MAE_EXIT") else "SIGNAL",
        "status": "CLOSED",
    })
    return pts


def build_trades(calc: pd.DataFrame, cfg: Dict[str, Any], start=None, end=None) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
    """Build trade lifecycle from immutable Pine BUY/SELL signals.

    Important MAE design rules:
    1. Indicator signal generation is never modified. signals_df contains only
       original Pine BUY/SELL events.
    2. MAE is a trade/risk-layer exit only. It can close a trade early, but it
       is not inserted into the indicator signal stream.
    3. MAE loss is capped exactly at mae_points by recording the configured
       threshold price, not the candle close that crossed the threshold.
    4. After an MAE exit, the engine remains FLAT but keeps the previous market
       bias blocked. It will ignore same-direction signals and re-enter only on
       the next opposite BUY/SELL signal. This preserves the original signal
       sequence/bias and avoids adding extra trades from repeated same-side
       signals after a risk exit.
    """
    df = calc.copy()
    if start is not None:
        df = df[df["datetime"] >= start]
    if end is not None:
        df = df[df["datetime"] <= end]
    df = df.reset_index(drop=True)

    mae_enabled, mae_points = _risk_settings(cfg)
    time_filter_enabled, blocked_entry_windows = _entry_filter_settings(cfg)

    pos = 0
    entry_price = None
    entry_time = None
    entry_signal = None

    # When an MAE exit has flattened a trade, blocked_side stores the side that
    # was stopped out (1 long, -1 short). While blocked, same-side indicator
    # signals are ignored for re-entry. Only the opposite signal resets bias and
    # opens a new trade.
    blocked_side = 0

    trades: list[dict[str, Any]] = []
    signals: list[dict[str, Any]] = []
    net_points = 0.0
    equity_peak = 0.0
    max_dd = 0.0
    last_risk_exit = None

    for _, r in df.iterrows():
        sig = r.get("signal", "")
        price = float(r["close"])
        time = r["datetime"]

        # Optional MAE risk exit is evaluated before opening/reversing on this
        # bar's indicator signal. The recorded exit price is the exact threshold,
        # not the close, so the configured loss cap is respected precisely.
        if mae_enabled and pos != 0 and entry_price is not None:
            ep = float(entry_price)
            if pos == 1:
                threshold_price = ep - float(mae_points)
                mae_hit = price <= threshold_price
                exit_signal = "MAE_EXIT_LONG"
            else:
                threshold_price = ep + float(mae_points)
                mae_hit = price >= threshold_price
                exit_signal = "MAE_EXIT_SHORT"

            if mae_hit:
                pts = _close_trade(
                    trades,
                    entry_time=entry_time,
                    entry_signal=str(entry_signal),
                    entry_price=ep,
                    exit_time=time,
                    exit_signal=exit_signal,
                    exit_price=float(threshold_price),
                    pos=pos,
                    cfg=cfg,
                )
                net_points += pts
                equity_peak = max(equity_peak, net_points)
                max_dd = max(max_dd, equity_peak - net_points)
                last_risk_exit = {
                    "datetime": time,
                    "signal": exit_signal,
                    "price": float(threshold_price),
                    "points": pts,
                    "mae_points": mae_points,
                }
                blocked_side = pos
                pos = 0
                entry_price = None
                entry_time = None
                entry_signal = None
                # Do not `continue`: this candle can also contain an opposite
                # Pine signal. If it does, it is allowed to open the new side.

        # Pine-generated BUY/SELL signals are logged exactly as produced by the
        # indicator. MAE exits are intentionally not appended here.
        if sig in {"BUY", "SELL"}:
            side = 1 if sig == "BUY" else -1
            entry_blocked = time_filter_enabled and _is_time_blocked(time, blocked_entry_windows)
            signals.append({
                "datetime": time,
                "signal": sig,
                "price": price,
                "hma": r.get("hma"),
                "atr_stop": r.get("xATRTrailingStop"),
                "is_chop": bool(r.get("is_chop", False)),
                "source": "INDICATOR",
                "entry_time_blocked": entry_blocked,
            })

            if pos == 0:
                # After a risk exit, same-side signals are ignored until the
                # opposite indicator signal arrives. This avoids creating extra
                # trades that did not exist in the original signal lifecycle.
                if blocked_side != 0 and side == blocked_side:
                    continue
                # Configurable intraday time filter blocks NEW entries only.
                # The original Pine signal is still logged above.
                if entry_blocked:
                    blocked_side = 0
                    continue
                blocked_side = 0
                pos = side
                entry_price = price
                entry_time = time
                entry_signal = sig
                continue

            if side != pos:
                pts = _close_trade(
                    trades,
                    entry_time=entry_time,
                    entry_signal=str(entry_signal),
                    entry_price=float(entry_price),
                    exit_time=time,
                    exit_signal=sig,
                    exit_price=price,
                    pos=pos,
                    cfg=cfg,
                )
                net_points += pts
                equity_peak = max(equity_peak, net_points)
                max_dd = max(max_dd, equity_peak - net_points)
                blocked_side = 0
                if entry_blocked:
                    # Exit the existing trade, but do not reverse into a new
                    # position during a blocked entry window.
                    pos = 0
                    entry_price = None
                    entry_time = None
                    entry_signal = None
                    continue
                pos = side
                entry_price = price
                entry_time = time
                entry_signal = sig
                continue
            # repeated same-direction signal is counted as signal, not a new trade.

    trades_df = pd.DataFrame(trades)
    sig_df = pd.DataFrame(signals)
    wins = int((trades_df["points"] > 0).sum()) if not trades_df.empty else 0
    losses = int((trades_df["points"] < 0).sum()) if not trades_df.empty else 0
    flat = int((trades_df["points"] == 0).sum()) if not trades_df.empty else 0
    gross_profit = float(trades_df.loc[trades_df["points"] > 0, "points"].sum()) if not trades_df.empty else 0.0
    gross_loss = float((-trades_df.loc[trades_df["points"] < 0, "points"]).sum()) if not trades_df.empty else 0.0
    open_points = 0.0
    if pos != 0 and entry_price is not None and not df.empty:
        open_points = _points(pos, float(entry_price), float(df.iloc[-1]["close"]))
    summary = {
        "signals": len(sig_df),
        "closed_trades": len(trades_df),
        "wins": wins,
        "losses": losses,
        "flat": flat,
        "win_rate": (wins / len(trades_df) * 100.0) if len(trades_df) else 0.0,
        "net_points": float(trades_df["points"].sum()) if not trades_df.empty else 0.0,
        "open_points": open_points,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "profit_factor": (gross_profit / gross_loss) if gross_loss else None,
        "best_trade": float(trades_df["points"].max()) if not trades_df.empty else None,
        "worst_trade": float(trades_df["points"].min()) if not trades_df.empty else None,
        "max_drawdown": max_dd,
        "current_position": "LONG" if pos == 1 else "SHORT" if pos == -1 else "FLAT",
        "current_entry_price": entry_price,
        "current_entry_time": entry_time,
        "last_signal": signals[-1] if signals else None,
        "last_risk_exit": last_risk_exit,
        "blocked_side_after_mae": "LONG" if blocked_side == 1 else "SHORT" if blocked_side == -1 else None,
        "mae_enabled": mae_enabled,
        "mae_points": mae_points,
        "time_block_filter_enabled": time_filter_enabled,
        "blocked_entry_windows": [f"{a}-{b}" for a, b in blocked_entry_windows],
    }
    return sig_df, trades_df, summary
