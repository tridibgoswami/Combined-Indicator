from __future__ import annotations

import math
from typing import Any, Dict

import numpy as np
import pandas as pd


def _tr(df: pd.DataFrame) -> pd.Series:
    pc = df["close"].shift(1)
    return pd.concat([(df["high"] - df["low"]).abs(), (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)


def pine_rma(src: pd.Series, length: int) -> pd.Series:
    src = src.astype(float).reset_index(drop=True)
    out = pd.Series(np.nan, index=src.index, dtype=float)
    if length <= 0:
        return src
    prev = np.nan
    for i, x in enumerate(src):
        if np.isnan(x):
            out.iloc[i] = np.nan
            continue
        if np.isnan(prev):
            if i + 1 >= length:
                window = src.iloc[i - length + 1 : i + 1]
                if window.notna().all():
                    prev = float(window.mean())
                    out.iloc[i] = prev
        else:
            prev = (prev * (length - 1) + float(x)) / length
            out.iloc[i] = prev
    return out


def pine_atr(df: pd.DataFrame, length: int) -> pd.Series:
    return pine_rma(_tr(df), length)


def pine_wma(src: pd.Series, length: int) -> pd.Series:
    src = src.astype(float).reset_index(drop=True)
    if length <= 0:
        return src
    weights = np.arange(1, length + 1, dtype=float)
    denom = weights.sum()
    return src.rolling(length, min_periods=length).apply(lambda x: float(np.dot(x, weights) / denom), raw=True)


def heikin_ashi_close(df: pd.DataFrame) -> pd.Series:
    return (df["open"] + df["high"] + df["low"] + df["close"]) / 4.0


def crossover(a: pd.Series, b: pd.Series) -> pd.Series:
    return (a > b) & (a.shift(1) <= b.shift(1))


def highest_prev(s: pd.Series, length: int) -> pd.Series:
    return s.rolling(length, min_periods=length).max().shift(1)


def lowest_prev(s: pd.Series, length: int) -> pd.Series:
    return s.rolling(length, min_periods=length).min().shift(1)


def _mode_slope_threshold(mode: str, manual: float, auto: bool) -> float:
    if not auto:
        return manual
    return {"Light": 0.030, "Medium": 0.045, "Strict": 0.060, "Off": 0.0}.get(mode, manual)


def _mode_distance_mult(mode: str, manual: float, auto: bool) -> float:
    if not auto:
        return manual
    return {"Light": 0.06, "Medium": 0.10, "Strict": 0.14, "Off": 0.0}.get(mode, manual)


def _mode_cooldown(mode: str, manual: int) -> int:
    if mode == "Light":
        return max(manual, 2)
    if mode == "Medium":
        return max(manual, 3)
    if mode == "Strict":
        return max(manual, 5)
    return manual


def calculate_pine_replica(df: pd.DataFrame, cfg: Dict[str, Any]) -> pd.DataFrame:
    """Bar-by-bar Python replica of SVMKR_UT_HMA_ORB_ChopNoADX BUY/SELL logic."""
    ind = cfg.get("indicator", {})
    instr = cfg.get("instrument", {})
    out = df.copy().reset_index(drop=True)
    out["bar_index"] = np.arange(len(out))

    a = float(ind.get("ut_key_value", 3.0))
    c = int(ind.get("ut_atr_period", 14))
    use_ha = bool(ind.get("use_heikin_ashi_source", False))
    n = int(ind.get("hma_period", 14))
    mintick = float(instr.get("mintick", ind.get("mintick", 0.05)))

    xatr = pine_atr(out, c)
    nloss = a * xatr
    src = heikin_ashi_close(out) if use_ha else out["close"].astype(float)
    out["src"] = src
    out["xATR"] = xatr
    out["nLoss"] = nloss

    # UT ATR trailing stop exactly follows Pine's recursive nz(prev, 0) style.
    trail = pd.Series(np.nan, index=out.index, dtype=float)
    pos = pd.Series(0, index=out.index, dtype=int)
    for i in out.index:
        prev_trail_nz = 0.0 if i == 0 or pd.isna(trail.iloc[i - 1]) else float(trail.iloc[i - 1])
        prev_src = np.nan if i == 0 else float(src.iloc[i - 1])
        s = float(src.iloc[i])
        nl = float(nloss.iloc[i]) if not pd.isna(nloss.iloc[i]) else np.nan
        if s > prev_trail_nz and (not pd.isna(prev_src) and prev_src > prev_trail_nz):
            val = max(prev_trail_nz, s - nl) if not pd.isna(nl) else np.nan
        elif s < prev_trail_nz and (not pd.isna(prev_src) and prev_src < prev_trail_nz):
            val = min(prev_trail_nz, s + nl) if not pd.isna(nl) else np.nan
        elif s > prev_trail_nz:
            val = s - nl if not pd.isna(nl) else np.nan
        else:
            val = s + nl if not pd.isna(nl) else np.nan
        trail.iloc[i] = val

        prev_pos_nz = 0 if i == 0 or pd.isna(pos.iloc[i - 1]) else int(pos.iloc[i - 1])
        if i > 0 and (src.iloc[i - 1] < prev_trail_nz) and (src.iloc[i] > prev_trail_nz):
            pos.iloc[i] = 1
        elif i > 0 and (src.iloc[i - 1] > prev_trail_nz) and (src.iloc[i] < prev_trail_nz):
            pos.iloc[i] = -1
        else:
            pos.iloc[i] = prev_pos_nz
    out["xATRTrailingStop"] = trail
    out["ut_pos"] = pos

    ema1 = src  # Pine ema(src, 1) equals src.
    above = crossover(ema1, trail).fillna(False)
    below = crossover(trail, ema1).fillna(False)
    out["raw_buy"] = ((src > trail) & above).fillna(False)
    out["raw_sell"] = ((src < trail) & below).fillna(False)

    half = int(round(n / 2.0))
    sqn = int(round(math.sqrt(n)))
    n2ma = 2.0 * pine_wma(out["close"], half)
    nma = pine_wma(out["close"], n)
    diff = n2ma - nma
    hma = pine_wma(diff, sqn)
    hma_prev = hma.shift(1)
    out["hma"] = hma
    out["hma_prev"] = hma_prev

    atr_norm_len = int(ind.get("atr_norm_len", 14))
    atr_norm = pine_atr(out, atr_norm_len)
    out["atr_norm"] = atr_norm

    chop_mode = str(ind.get("chop_mode", "Medium"))
    enable_chop = bool(ind.get("enable_chop_filter", True))
    filters_enabled = enable_chop and chop_mode != "Off"
    slope_len = int(ind.get("slope_len", 3))
    slope_threshold = _mode_slope_threshold(chop_mode, float(ind.get("manual_slope_threshold", 0.045)), bool(ind.get("use_auto_threshold", True)))
    distance_mult = _mode_distance_mult(chop_mode, float(ind.get("manual_distance_mult", 0.10)), bool(ind.get("use_auto_distance", True)))
    cooldown_bars = _mode_cooldown(chop_mode, int(ind.get("cooldown_bars_manual", 3)))
    range_lookback = int(ind.get("range_lookback", 9))

    hma_slope = hma - hma.shift(slope_len)
    hma_slope_norm = (hma_slope.abs() / np.maximum(atr_norm, mintick)).replace([np.inf, -np.inf], np.nan)
    hma_slope_bull = (hma_slope > 0) & (hma_slope_norm >= slope_threshold)
    hma_slope_bear = (hma_slope < 0) & (hma_slope_norm >= slope_threshold)
    hma_trend_bull = hma > hma_prev
    hma_trend_bear = hma < hma_prev
    dist_ok = (out["close"] - hma).abs() >= atr_norm * distance_mult
    range_buy_ok = out["close"] > highest_prev(out["high"], range_lookback)
    range_sell_ok = out["close"] < lowest_prev(out["low"], range_lookback)

    buy = pd.Series(False, index=out.index)
    sell = pd.Series(False, index=out.index)
    cooldown_ok_s = pd.Series(False, index=out.index)
    stable_bias = pd.Series(0, index=out.index, dtype=int)
    last_signal_bar = None
    for i in out.index:
        cooldown_ok = last_signal_bar is None or (int(out.at[i, "bar_index"]) - last_signal_bar > cooldown_bars)
        cooldown_ok_s.iloc[i] = cooldown_ok
        buy_hma_trend_ok = (not filters_enabled) or (not bool(ind.get("use_hma_trend_filter", True))) or bool(hma_trend_bull.iloc[i])
        sell_hma_trend_ok = (not filters_enabled) or (not bool(ind.get("use_hma_trend_filter", True))) or bool(hma_trend_bear.iloc[i])
        buy_slope_ok = (not filters_enabled) or (not bool(ind.get("use_hma_slope_filter", True))) or bool(hma_slope_bull.iloc[i])
        sell_slope_ok = (not filters_enabled) or (not bool(ind.get("use_hma_slope_filter", True))) or bool(hma_slope_bear.iloc[i])
        buy_distance_ok = (not filters_enabled) or (not bool(ind.get("use_distance_filter", True))) or bool(dist_ok.iloc[i])
        sell_distance_ok = (not filters_enabled) or (not bool(ind.get("use_distance_filter", True))) or bool(dist_ok.iloc[i])
        buy_cooldown_ok = (not filters_enabled) or (not bool(ind.get("use_cooldown_filter", True))) or cooldown_ok
        sell_cooldown_ok = (not filters_enabled) or (not bool(ind.get("use_cooldown_filter", True))) or cooldown_ok
        buy_range_ok = (not filters_enabled) or (not bool(ind.get("use_range_filter", False))) or bool(range_buy_ok.iloc[i])
        sell_range_ok = (not filters_enabled) or (not bool(ind.get("use_range_filter", False))) or bool(range_sell_ok.iloc[i])

        buy.iloc[i] = bool(out.at[i, "raw_buy"] and buy_hma_trend_ok and buy_slope_ok and buy_distance_ok and buy_cooldown_ok and buy_range_ok)
        sell.iloc[i] = bool(out.at[i, "raw_sell"] and sell_hma_trend_ok and sell_slope_ok and sell_distance_ok and sell_cooldown_ok and sell_range_ok)
        if buy.iloc[i] or sell.iloc[i]:
            last_signal_bar = int(out.at[i, "bar_index"])

        if bool(hma_slope_bull.iloc[i]) and bool(hma_trend_bull.iloc[i]):
            stable_bias.iloc[i] = 1
        elif bool(hma_slope_bear.iloc[i]) and bool(hma_trend_bear.iloc[i]):
            stable_bias.iloc[i] = -1
        else:
            stable_bias.iloc[i] = stable_bias.iloc[i - 1] if i > 0 else 0

    out["hma_slope"] = hma_slope
    out["hma_slope_norm"] = hma_slope_norm
    out["slope_threshold"] = slope_threshold
    out["dist_ok"] = dist_ok.fillna(False)
    out["cooldown_ok"] = cooldown_ok_s
    out["range_buy_ok"] = range_buy_ok.fillna(False)
    out["range_sell_ok"] = range_sell_ok.fillna(False)
    out["buy"] = buy
    out["sell"] = sell
    out["signal"] = np.where(buy, "BUY", np.where(sell, "SELL", ""))
    out["blocked_buy"] = (out["raw_buy"] & ~buy).fillna(False)
    out["blocked_sell"] = (out["raw_sell"] & ~sell).fillna(False)
    out["is_chop"] = (filters_enabled and bool(ind.get("use_hma_slope_filter", True))) & (hma_slope_norm < slope_threshold)
    out["stable_bias"] = stable_bias
    return out
