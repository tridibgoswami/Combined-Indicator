"""Fetch raw candles straight from AngelOne for a time window and flag problems.

Bypasses the engine's in-memory incremental cache and signal logic, so the
output is exactly what AngelOne's historical API returns.

Usage:
    python tools/check_candles.py --from "2026-11-11 14:55" --to "2026-11-11 15:30"
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trading_engine.broker_adapters.angelone import AngelOneBroker  # noqa: E402
from trading_engine.config import load_config  # noqa: E402
from trading_engine.instrument_selector.instrument_selector import select_nearest_futures  # noqa: E402


def _report(label: str, df: pd.DataFrame, step_minutes: int, jump_points: float) -> None:
    print(f"\n=== {label}: {len(df)} candles ===")
    if df.empty:
        print("No candles returned.")
        return
    prev = None
    for _, r in df.iterrows():
        notes = []
        if prev is not None:
            gap = (r["datetime"] - prev["datetime"]).total_seconds() / 60
            if gap > step_minutes:
                notes.append(f"GAP {int(gap - step_minutes)} missing candle(s)")
            jump = float(r["open"]) - float(prev["close"])
            if abs(jump) >= jump_points:
                notes.append(f"JUMP {jump:+.2f} from prev close")
        print(
            f"{r['datetime']:%Y-%m-%d %H:%M}  O {float(r['open']):>10.2f}  H {float(r['high']):>10.2f}  "
            f"L {float(r['low']):>10.2f}  C {float(r['close']):>10.2f}  {'  '.join(notes)}"
        )
        prev = r


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="start", required=True, help="Start, e.g. '2026-11-11 14:55'")
    ap.add_argument("--to", dest="end", required=True, help="End, e.g. '2026-11-11 15:30'")
    ap.add_argument("--jump", type=float, default=50.0, help="Flag open-vs-previous-close jumps of at least this many points")
    ap.add_argument("--config", default="config/config.yaml")
    args = ap.parse_args()

    cfg = load_config(args.config)
    broker = AngelOneBroker(cfg)
    broker.connect()
    start = pd.Timestamp(args.start).to_pydatetime()
    end = pd.Timestamp(args.end).to_pydatetime()
    step = broker.interval_minutes
    instr = cfg.get("instrument", {}) or {}

    try:
        print(f"Spot LTP now      : {broker.ltp(execution=False):.2f}")
    except Exception as exc:
        print(f"Spot LTP now      : unavailable ({exc})")

    spot = broker.get_candles(start, end)
    _report(f"SPOT {instr.get('symbol')} token {instr.get('symboltoken')} {broker.settings.interval}", spot, step, args.jump)

    try:
        fut = select_nearest_futures(cfg)
        broker.set_execution_instrument(fut.to_dict())
        print(f"\nFutures LTP now   : {broker.ltp(execution=True):.2f}")
        _report(f"FUTURES {fut.tradingsymbol} token {fut.symboltoken}", broker.get_futures_candles(start, end), step, args.jump)
    except Exception as exc:
        print(f"\nFutures check skipped: {exc}")


if __name__ == "__main__":
    main()
