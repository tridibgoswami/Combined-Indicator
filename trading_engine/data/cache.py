from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import pandas as pd

from trading_engine.data.loaders import normalize_ohlc


def _root() -> Path:
    return Path(__file__).resolve().parents[2]


def _safe_name(value: Any) -> str:
    return str(value or "UNKNOWN").replace("/", "_").replace(" ", "_").upper()


def cache_path(cfg: Dict[str, Any]) -> Path:
    data_cfg = cfg.get("data", {}) or {}
    instr = cfg.get("instrument", {}) or {}
    cache_dir = Path(data_cfg.get("cache_dir", "data/cache"))
    if not cache_dir.is_absolute():
        cache_dir = _root() / cache_dir
    cache_dir.mkdir(parents=True, exist_ok=True)
    symbol = _safe_name(instr.get("symbol") or instr.get("tradingsymbol"))
    interval = _safe_name(instr.get("interval", "FIVE_MINUTE"))
    token = _safe_name(instr.get("symboltoken", ""))
    return cache_dir / f"{symbol}_{token}_{interval}.csv"


def load_cache(cfg: Dict[str, Any]) -> pd.DataFrame:
    p = cache_path(cfg)
    if not p.exists():
        return pd.DataFrame(columns=["datetime", "open", "high", "low", "close", "volume"])
    try:
        return normalize_ohlc(pd.read_csv(p), cfg.get("engine", {}).get("timezone", "Asia/Kolkata"))
    except Exception:
        # Corrupt cache should not silently produce bad signals. Rename and start fresh.
        bad = p.with_suffix(p.suffix + f".bad.{int(time.time())}")
        p.rename(bad)
        return pd.DataFrame(columns=["datetime", "open", "high", "low", "close", "volume"])


def save_cache(cfg: Dict[str, Any], df: pd.DataFrame) -> Path:
    p = cache_path(cfg)
    out = normalize_ohlc(df, cfg.get("engine", {}).get("timezone", "Asia/Kolkata"))
    out = out.sort_values("datetime").drop_duplicates("datetime", keep="last").reset_index(drop=True)
    out.to_csv(p, index=False)
    return p


def merge_ohlc(a: pd.DataFrame, b: pd.DataFrame, cfg: Dict[str, Any]) -> pd.DataFrame:
    parts = [x for x in [a, b] if x is not None and not x.empty]
    if not parts:
        return pd.DataFrame(columns=["datetime", "open", "high", "low", "close", "volume"])
    return normalize_ohlc(pd.concat(parts, ignore_index=True), cfg.get("engine", {}).get("timezone", "Asia/Kolkata"))


def _missing_segments(cache: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp, interval_minutes: int) -> list[Tuple[pd.Timestamp, pd.Timestamp]]:
    """Return coarse missing edge segments. This intentionally fills from the
    requested start to the first cached candle and from the last cached candle to
    the requested end. It avoids expensive gap scanning inside every trading day.
    """
    if cache.empty:
        return [(start, end)]
    c = cache[(cache["datetime"] >= start) & (cache["datetime"] <= end)].copy()
    if c.empty:
        return [(start, end)]
    segs: list[Tuple[pd.Timestamp, pd.Timestamp]] = []
    first = c["datetime"].min()
    last = c["datetime"].max()
    step = pd.Timedelta(minutes=interval_minutes)
    if first > start + step:
        segs.append((start, first - step))
    if last < end - step:
        segs.append((last + step, end))
    return segs


def _chunk_ranges(start: pd.Timestamp, end: pd.Timestamp, max_days: int) -> list[Tuple[pd.Timestamp, pd.Timestamp]]:
    ranges = []
    cur = start
    max_delta = pd.Timedelta(days=max(1, int(max_days)))
    while cur <= end:
        chunk_end = min(cur + max_delta, end)
        ranges.append((cur, chunk_end))
        cur = chunk_end + pd.Timedelta(minutes=1)
    return ranges


def ensure_broker_data(
    cfg: Dict[str, Any],
    broker,
    start: pd.Timestamp,
    end: pd.Timestamp,
    *,
    purpose: str = "backtest",
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Return OHLC candles for [start, end], downloading missing data from broker.

    Broker is the source of truth. Local CSV cache is only a speed layer. If the
    requested range cannot be covered, caller receives an explicit RuntimeError
    instead of a misleading empty backtest.
    """
    data_cfg = cfg.get("data", {}) or {}
    interval_minutes = int(getattr(broker, "interval_minutes", cfg.get("instrument", {}).get("timeframe_minutes", 5)) or 5)
    max_days_per_call = int(data_cfg.get("max_days_per_fetch", 30) or 30)
    sleep_seconds = float(data_cfg.get("fetch_sleep_seconds", 0.35) or 0.35)
    use_cache = bool(data_cfg.get("use_cache", True))

    cache = pd.DataFrame(columns=["datetime", "open", "high", "low", "close", "volume"])
    if use_cache and not force_refresh:
        cache = load_cache(cfg)

    print("Checking historical candle cache...")
    if not cache.empty:
        print(f"Cache Range       : {cache['datetime'].min()} -> {cache['datetime'].max()}")
    else:
        print("Cache Range       : EMPTY")

    segments = [(start, end)] if force_refresh or cache.empty else _missing_segments(cache, start, end, interval_minutes)
    downloaded = []
    if segments:
        print("Downloading missing candles from AngelOne...")
        for seg_start, seg_end in segments:
            if seg_start > seg_end:
                continue
            for chunk_start, chunk_end in _chunk_ranges(seg_start, seg_end, max_days_per_call):
                print(f"  Fetch           : {chunk_start} -> {chunk_end}")
                df = broker.get_candles(chunk_start.to_pydatetime(), chunk_end.to_pydatetime())
                if df is not None and not df.empty:
                    downloaded.append(df)
                time.sleep(max(0.0, sleep_seconds))
    else:
        print("Downloading missing candles: none; cache already covers requested range.")

    all_df = merge_ohlc(cache, pd.concat(downloaded, ignore_index=True) if downloaded else pd.DataFrame(), cfg)
    if use_cache:
        p = save_cache(cfg, all_df)
        print(f"Cache Updated     : {p}")

    window = all_df[(all_df["datetime"] >= start) & (all_df["datetime"] <= end)].copy().reset_index(drop=True)
    if window.empty:
        available = "EMPTY" if all_df.empty else f"{all_df['datetime'].min()} -> {all_df['datetime'].max()}"
        raise RuntimeError(
            "Insufficient historical data.\n"
            f"Requested Range   : {start} -> {end}\n"
            f"Available Range   : {available}\n"
            "Backtest aborted instead of returning misleading zero trades."
        )

    # Ensure edge coverage is close enough for candle-based backtest. We allow
    # a few calendar gaps for weekends/holidays but not a completely stale cache.
    latest = window["datetime"].max()
    if latest < end - pd.Timedelta(days=3):
        raise RuntimeError(
            "Historical data is stale for the requested range.\n"
            f"Requested End     : {end}\n"
            f"Latest Candle     : {latest}\n"
            "Check AngelOne historical API response/token/date range."
        )
    print(f"Data Ready        : {window['datetime'].min()} -> {window['datetime'].max()} | Candles: {len(window)}")
    return window
