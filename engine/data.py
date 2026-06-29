from __future__ import annotations

from pathlib import Path
from typing import Dict, Any

import pandas as pd
import pytz


COLUMN_ALIASES = {
    "datetime": ["datetime", "timestamp", "time", "date", "Date", "Datetime", "Timestamp"],
    "open": ["open", "Open", "OPEN"],
    "high": ["high", "High", "HIGH"],
    "low": ["low", "Low", "LOW"],
    "close": ["close", "Close", "CLOSE", "ltp"],
    "volume": ["volume", "Volume", "VOLUME", "vol"],
}


def _find_col(df: pd.DataFrame, names: list[str]) -> str | None:
    lower_map = {str(c).strip().lower(): c for c in df.columns}
    for n in names:
        if str(n).lower() in lower_map:
            return lower_map[str(n).lower()]
    return None


def normalize_ohlc(df: pd.DataFrame, timezone: str = "Asia/Kolkata") -> pd.DataFrame:
    mapping: Dict[str, str] = {}
    for std, aliases in COLUMN_ALIASES.items():
        col = _find_col(df, aliases)
        if col is not None:
            mapping[col] = std
    out = df.rename(columns=mapping).copy()
    required = ["datetime", "open", "high", "low", "close"]
    missing = [c for c in required if c not in out.columns]
    if missing:
        raise ValueError(f"Missing OHLC columns: {missing}. Found columns: {list(df.columns)}")
    out["datetime"] = pd.to_datetime(out["datetime"], errors="coerce")
    if out["datetime"].dt.tz is None:
        out["datetime"] = out["datetime"].dt.tz_localize(timezone, nonexistent="shift_forward", ambiguous="NaT")
    else:
        out["datetime"] = out["datetime"].dt.tz_convert(timezone)
    out = out.dropna(subset=["datetime"]).sort_values("datetime").drop_duplicates("datetime", keep="last")
    for c in ["open", "high", "low", "close", "volume"]:
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce")
    out = out.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)
    if "volume" not in out.columns:
        out["volume"] = 0
    return out[["datetime", "open", "high", "low", "close", "volume"]]


def load_csv(path: str | Path, cfg: Dict[str, Any]) -> pd.DataFrame:
    p = Path(path)
    if not p.is_absolute():
        p = Path(__file__).resolve().parents[1] / p
    if not p.exists():
        raise FileNotFoundError(f"CSV file not found: {p}")
    return normalize_ohlc(pd.read_csv(p), cfg.get("engine", {}).get("timezone", "Asia/Kolkata"))


def filter_session(df: pd.DataFrame, session_start: str | None, session_end: str | None) -> pd.DataFrame:
    if not session_start or not session_end:
        return df.copy()
    t = df["datetime"].dt.strftime("%H:%M")
    return df[(t >= session_start) & (t <= session_end)].reset_index(drop=True)


def parse_dt(value: str | None, timezone: str):
    if not value:
        return None
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize(timezone)
    else:
        ts = ts.tz_convert(timezone)
    return ts
