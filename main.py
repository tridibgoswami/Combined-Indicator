from __future__ import annotations

import argparse
from pathlib import Path

from trading_engine.config import load_config
from trading_engine.runner import run_from_config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SVMKR UT HMA ORB ChopNoADX Engine")
    parser.add_argument("--from", dest="start", help="Backtest start date/time, e.g. 2026-06-15 or '2026-06-15 09:15'")
    parser.add_argument("--to", dest="end", help="Backtest end date/time, e.g. 2026-06-22 or '2026-06-22 15:30'")
    parser.add_argument("--export", dest="export", help="Backtest export CSV path. Defaults to outputs/backtest_results.csv")
    parser.add_argument("--csv", dest="csv_path", help="Optional explicit CSV for offline backtest. If omitted, broker+cache is used.")
    parser.add_argument("--source", choices=["broker", "csv"], help="Backtest data source. Defaults to broker when --from/--to are supplied.")
    parser.add_argument("--force-refresh", action="store_true", help="Ignore cache and re-download broker candles for requested range.")
    parser.add_argument("--mae-points", type=float, help="Enable FIXED_POINTS MAE exit for this run, e.g. --mae-points 400")
    parser.add_argument("--disable-mae", action="store_true", help="Disable MAE exit for this run even if config enables it.")
    parser.add_argument("--config", default="config/config.yaml", help="Config YAML path")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    cfg = load_config(args.config)

    # Supplying --from/--to switches to broker-backed backtest. Plain `python main.py`
    # remains live/config-driven.
    if args.start or args.end or args.export or args.csv_path or args.source:
        cfg.setdefault("engine", {})["mode"] = "backtest"
        bt = cfg.setdefault("backtest", {})
        if args.start:
            bt["start"] = args.start
        if args.end:
            bt["end"] = args.end
        if args.export:
            bt["export"] = args.export
        if args.csv_path:
            bt["csv_path"] = args.csv_path
            bt["use_csv"] = True
            bt["source"] = "csv"
        if args.source:
            bt["source"] = args.source
            bt["use_csv"] = args.source == "csv"
        if args.force_refresh:
            bt["force_refresh"] = True
        if args.mae_points is not None:
            risk = cfg.setdefault("risk_management", {})
            risk["mode"] = "FIXED_POINTS"
            risk["enable_mae_exit"] = True
            risk["mae_points"] = float(args.mae_points)
        if args.disable_mae:
            risk = cfg.setdefault("risk_management", {})
            risk["mode"] = "NONE"
            risk["enable_mae_exit"] = False

    run_from_config(cfg)
