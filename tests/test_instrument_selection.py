from __future__ import annotations

from unittest.mock import patch

import pandas as pd

from trading_engine.instrument_selector import instrument_selector as inst


def _option_row(symbol: str, strike: float, expiry: str, token: str) -> dict:
    return {
        "exch_seg": "NFO",
        "instrumenttype": "OPTIDX",
        "name": "BANKNIFTY",
        "symbol": symbol,
        "token": token,
        "expiry": expiry,
        "strike": strike * 100,  # AngelOne stores strike * 100
        "lotsize": "30",
    }


def _fake_rows():
    rows = []
    for strike in [49500, 49600, 49700, 49800, 49900, 50000, 50100, 50200, 50300, 50400, 50500]:
        rows.append(_option_row(f"BANKNIFTY30JUN2026{strike}CE", strike, "30JUN2026", f"CE{strike}"))
        rows.append(_option_row(f"BANKNIFTY30JUN2026{strike}PE", strike, "30JUN2026", f"PE{strike}"))
    return rows


def _cfg():
    return {
        "engine": {"timezone": "Asia/Kolkata"},
        "execution": {"underlying": "BANKNIFTY", "exchange": "NFO"},
        "option_execution": {
            "underlying": "BANKNIFTY",
            "exchange": "NFO",
            "expiry_mode": "NEAREST",
            "strike_selection": {"mode": "DELTA", "target_delta": 0.60, "fallback": "ATM", "strike_step": 100},
            "option_selling": {"short_delta": 0.30, "hedge_strikes": 5, "hedge_distance_points": 0},
        },
    }


@patch.object(inst, "load_scrip_master", return_value=_fake_rows())
def test_option_buying_picks_itm_strike_for_high_delta(_mock):
    cfg = _cfg()
    selected = inst.select_option_contract(cfg, option_type="CE", underlying_ltp=50000.0)
    # target_delta 0.60 on CE -> 1 strike ITM (below ATM)
    assert selected.option_type if hasattr(selected, "option_type") else True
    d = inst.selection_to_dict(selected)
    assert d["strike"] == 49900.0
    assert d["option_type"] == "CE"


@patch.object(inst, "load_scrip_master", return_value=_fake_rows())
def test_option_buying_atm_fallback(_mock):
    cfg = _cfg()
    cfg["option_execution"]["strike_selection"]["mode"] = "ATM"
    selected = inst.select_option_contract(cfg, option_type="PE", underlying_ltp=50050.0)
    d = inst.selection_to_dict(selected)
    assert d["strike"] == 50000.0


@patch.object(inst, "load_scrip_master", return_value=_fake_rows())
def test_option_selling_bull_put_spread_hedge_is_lower_strike(_mock):
    cfg = _cfg()
    short_leg = inst.select_option_contract(cfg, option_type="PE", underlying_ltp=50000.0, target_delta=0.30)
    short_dict = inst.selection_to_dict(short_leg)
    hedge_strike = short_dict["strike"] - 500  # 5 strikes * 100 step
    hedge = inst.select_option_by_strike(cfg, option_type="PE", strike=hedge_strike)
    assert hedge["strike"] < short_dict["strike"]


@patch.object(inst, "load_scrip_master", return_value=_fake_rows())
def test_select_nearest_futures_requires_matching_underlying(_mock):
    futures_rows = [
        {
            "exch_seg": "NFO", "instrumenttype": "FUTIDX", "name": "BANKNIFTY",
            "symbol": "BANKNIFTY30JUN2026FUT", "token": "FUT1",
            "expiry": "30JUN2026", "lotsize": "30",
        }
    ]
    with patch.object(inst, "load_scrip_master", return_value=futures_rows):
        selected = inst.select_nearest_futures(
            {"execution": {"underlying": "BANKNIFTY", "exchange": "NFO", "instrument_type": "FUTIDX"},
             "engine": {"timezone": "Asia/Kolkata"}},
            now=pd.Timestamp("2026-06-01", tz="Asia/Kolkata"),
        )
    assert selected.tradingsymbol == "BANKNIFTY30JUN2026FUT"
    assert selected.lot_size == 30
