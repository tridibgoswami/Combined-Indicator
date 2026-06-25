from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import pandas as pd
import pytz


DEFAULT_MASTER_URL = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"


@dataclass
class InstrumentSelection:
    exchange: str
    tradingsymbol: str
    symboltoken: str
    expiry: str | None
    lot_size: int
    name: str
    instrument_type: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except Exception:
        return default


def _parse_expiry(value: Any) -> pd.Timestamp | None:
    if value is None or value == "":
        return None
    s = str(value).strip()
    # AngelOne normally uses strings such as 30JUN2026 / 30JUN26 / 2026-06-30.
    fmts = ["%d%b%Y", "%d%b%y", "%Y-%m-%d", "%d-%b-%Y", "%d-%b-%y"]
    for fmt in fmts:
        try:
            return pd.Timestamp(datetime.strptime(s.upper(), fmt)).tz_localize(None)
        except Exception:
            pass
    # Defensive extraction from symbols like BANKNIFTY30JUN26FUT.
    m = re.search(r"(\d{1,2}[A-Z]{3}\d{2,4})", s.upper())
    if m:
        return _parse_expiry(m.group(1))
    return None


def _download_json(url: str) -> list[dict[str, Any]]:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read().decode("utf-8")
    data = json.loads(raw)
    if not isinstance(data, list):
        raise RuntimeError("AngelOne scrip master did not return a list")
    return data


def load_scrip_master(cfg: Dict[str, Any], *, force: bool = False) -> list[dict[str, Any]]:
    execution = cfg.get("execution", {}) or {}
    selector = execution.get("instrument_selector", {}) or {}
    url = selector.get("master_url") or DEFAULT_MASTER_URL
    cache_path = Path(selector.get("cache_path") or "data/cache/angelone_scrip_master.json")
    if not cache_path.is_absolute():
        cache_path = _project_root() / cache_path
    refresh_hours = float(selector.get("refresh_hours", 12) or 12)
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    use_cache = cache_path.exists() and not force
    if use_cache:
        age = datetime.now() - datetime.fromtimestamp(cache_path.stat().st_mtime)
        use_cache = age <= timedelta(hours=refresh_hours)

    if use_cache:
        return json.loads(cache_path.read_text(encoding="utf-8"))

    print("Downloading AngelOne instrument list...")
    data = _download_json(url)
    cache_path.write_text(json.dumps(data), encoding="utf-8")
    return data


def _matches_underlying(row: Dict[str, Any], underlying: str) -> bool:
    u = underlying.upper().strip()
    fields = [str(row.get(k, "")).upper() for k in ["name", "symbol", "tradingsymbol", "exch_seg"]]
    return any(f == u or f.startswith(u) or u in f for f in fields)


def select_nearest_futures(cfg: Dict[str, Any], *, now: Optional[pd.Timestamp] = None, force_master_refresh: bool = False) -> InstrumentSelection:
    execution = cfg.get("execution", {}) or {}
    selector = execution.get("instrument_selector", {}) or {}
    underlying = str(selector.get("underlying") or execution.get("underlying") or cfg.get("instrument", {}).get("underlying") or "BANKNIFTY").upper()
    exchange = str(selector.get("exchange") or execution.get("exchange") or "NFO").upper()
    instrument_type = str(selector.get("instrument_type") or execution.get("instrument_type") or "FUTIDX").upper()
    expiry_mode = str(selector.get("expiry_mode") or execution.get("expiry_mode") or "NEAREST").upper()
    tz = pytz.timezone(cfg.get("engine", {}).get("timezone", "Asia/Kolkata"))
    now_ts = now or pd.Timestamp.now(tz=tz)
    today = pd.Timestamp(now_ts.date()).tz_localize(None)

    rows = load_scrip_master(cfg, force=force_master_refresh)
    print(f"Instrument list loaded: {len(rows)} contracts")

    candidates: list[tuple[pd.Timestamp, Dict[str, Any]]] = []
    for row in rows:
        exch = str(row.get("exch_seg") or row.get("exchange") or "").upper()
        itype = str(row.get("instrumenttype") or row.get("instrument_type") or "").upper()
        symbol = str(row.get("symbol") or row.get("tradingsymbol") or "").upper()
        if exch != exchange:
            continue
        if instrument_type and itype != instrument_type:
            continue
        if "FUT" not in symbol and "FUT" not in itype:
            continue
        if not _matches_underlying(row, underlying):
            continue
        expiry = _parse_expiry(row.get("expiry") or symbol)
        if expiry is None or expiry < today:
            continue
        candidates.append((expiry, row))

    if not candidates:
        raise RuntimeError(f"No active {underlying} futures found in AngelOne scrip master for exchange={exchange}, type={instrument_type}")

    candidates.sort(key=lambda x: x[0])
    if expiry_mode == "NEXT" and len(candidates) > 1:
        expiry, row = candidates[1]
    else:
        expiry, row = candidates[0]

    tradingsymbol = str(row.get("symbol") or row.get("tradingsymbol") or "")
    token = str(row.get("token") or row.get("symboltoken") or "")
    lot_size = _safe_int(row.get("lotsize") or row.get("lot_size") or row.get("lots") or execution.get("lot_size") or cfg.get("instrument", {}).get("lot_size"), 1)
    name = str(row.get("name") or underlying)
    selected = InstrumentSelection(
        exchange=exchange,
        tradingsymbol=tradingsymbol,
        symboltoken=token,
        expiry=expiry.strftime("%d %b %Y"),
        lot_size=lot_size,
        name=name,
        instrument_type=instrument_type,
    )
    print(f"[{underlying}] Futures: {selected.tradingsymbol} | Expiry: {selected.expiry} | Lot: {selected.lot_size} | Token: {selected.symboltoken}")
    return selected


def apply_execution_instrument(cfg: Dict[str, Any], selected: InstrumentSelection) -> Dict[str, Any]:
    cfg.setdefault("execution", {})["resolved_instrument"] = selected.to_dict()
    return cfg


# -----------------------------------------------------------------------------
# Option instrument selection
# -----------------------------------------------------------------------------

def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def _normalise_strike(value: Any) -> float:
    """AngelOne scrip master stores option strikes as price * 100."""
    raw = _safe_float(value, 0.0)
    if raw > 100000:
        return raw / 100.0
    return raw


def _option_side_from_symbol(symbol: str) -> str | None:
    s = str(symbol).upper()
    if s.endswith("CE"):
        return "CE"
    if s.endswith("PE"):
        return "PE"
    return None


def _select_expiry(candidates: list[tuple[pd.Timestamp, Dict[str, Any]]], expiry_mode: str) -> tuple[pd.Timestamp, Dict[str, Any]]:
    if not candidates:
        raise RuntimeError("No option candidates available for expiry selection")
    candidates.sort(key=lambda x: x[0])
    expiry_mode = str(expiry_mode or "NEAREST").upper()
    if expiry_mode == "NEXT" and len({x[0] for x in candidates}) > 1:
        first = candidates[0][0]
        for expiry, row in candidates:
            if expiry != first:
                return expiry, row
    # MONTHLY is handled by choosing the farthest expiry within the nearest month
    # when weekly contracts are present. BANKNIFTY currently behaves as monthly in
    # the user's setup; for NIFTY this lets the user choose NEAREST weekly.
    if expiry_mode == "MONTHLY":
        first_month = candidates[0][0].month
        first_year = candidates[0][0].year
        same_month = [(e, r) for e, r in candidates if e.month == first_month and e.year == first_year]
        return same_month[-1] if same_month else candidates[0]
    return candidates[0]


def _available_option_contracts(
    cfg: Dict[str, Any],
    option_type: str,
    *,
    expiry_mode: str = "NEAREST",
    force_master_refresh: bool = False,
    now: Optional[pd.Timestamp] = None,
) -> list[dict[str, Any]]:
    execution = cfg.get("execution", {}) or {}
    opt_cfg = cfg.get("option_execution", {}) or {}
    underlying = str(opt_cfg.get("underlying") or execution.get("underlying") or cfg.get("instrument", {}).get("symbol") or "BANKNIFTY").upper()
    exchange = str(opt_cfg.get("exchange") or execution.get("exchange") or "NFO").upper()
    tz = pytz.timezone(cfg.get("engine", {}).get("timezone", "Asia/Kolkata"))
    now_ts = now or pd.Timestamp.now(tz=tz)
    today = pd.Timestamp(now_ts.date()).tz_localize(None)
    option_type = option_type.upper()

    rows = load_scrip_master(cfg, force=force_master_refresh)
    candidates: list[tuple[pd.Timestamp, Dict[str, Any]]] = []
    for row in rows:
        exch = str(row.get("exch_seg") or row.get("exchange") or "").upper()
        itype = str(row.get("instrumenttype") or row.get("instrument_type") or "").upper()
        symbol = str(row.get("symbol") or row.get("tradingsymbol") or "").upper()
        if exch != exchange or itype != "OPTIDX":
            continue
        if not _matches_underlying(row, underlying):
            continue
        if _option_side_from_symbol(symbol) != option_type:
            continue
        expiry = _parse_expiry(row.get("expiry") or symbol)
        if expiry is None or expiry < today:
            continue
        candidates.append((expiry, row))

    if not candidates:
        raise RuntimeError(f"No active {underlying} {option_type} options found in AngelOne scrip master")

    selected_expiry, _ = _select_expiry(candidates, expiry_mode)
    contracts: list[dict[str, Any]] = []
    for expiry, row in candidates:
        if expiry != selected_expiry:
            continue
        strike = _normalise_strike(row.get("strike"))
        if strike <= 0:
            continue
        contracts.append({
            "exchange": exchange,
            "tradingsymbol": str(row.get("symbol") or row.get("tradingsymbol") or ""),
            "symboltoken": str(row.get("token") or row.get("symboltoken") or ""),
            "expiry": expiry.strftime("%d %b %Y"),
            "lot_size": _safe_int(row.get("lotsize") or row.get("lot_size") or execution.get("lot_size") or cfg.get("instrument", {}).get("lot_size"), 1),
            "name": str(row.get("name") or underlying),
            "instrument_type": "OPTIDX",
            "option_type": option_type,
            "strike": strike,
        })
    contracts.sort(key=lambda r: r["strike"])
    return contracts


def _strike_step(contracts: list[dict[str, Any]], default: float = 100.0) -> float:
    strikes = sorted({float(c["strike"]) for c in contracts})
    diffs = [round(strikes[i] - strikes[i-1], 2) for i in range(1, len(strikes)) if strikes[i] > strikes[i-1]]
    return min(diffs) if diffs else default


def _nearest_contract_by_strike(contracts: list[dict[str, Any]], target_strike: float) -> dict[str, Any]:
    if not contracts:
        raise RuntimeError("Cannot choose option strike: empty contract list")
    return min(contracts, key=lambda r: abs(float(r["strike"]) - float(target_strike)))


def _atm_strike(contracts: list[dict[str, Any]], underlying_ltp: float) -> float:
    return float(_nearest_contract_by_strike(contracts, underlying_ltp)["strike"])


def select_option_contract(
    cfg: Dict[str, Any],
    *,
    option_type: str,
    underlying_ltp: float,
    purpose: str = "BUY",
    target_delta: Optional[float] = None,
    expiry_mode: Optional[str] = None,
) -> InstrumentSelection:
    """Select one option contract.

    The engine supports DELTA mode as a live-trading approximation unless a
    broker Greek feed is added later. For target delta > 0.50, it chooses an
    ITM strike near the requested delta; for target delta < 0.50, it chooses an
    OTM strike. ATM mode chooses the nearest strike to the underlying LTP.
    """
    execution = cfg.get("execution", {}) or {}
    opt_cfg = cfg.get("option_execution", {}) or {}
    sel_cfg = opt_cfg.get("strike_selection", {}) or {}
    mode = str(sel_cfg.get("mode") or "DELTA").upper()
    fallback = str(sel_cfg.get("fallback") or "ATM").upper()
    expiry_mode = expiry_mode or opt_cfg.get("expiry_mode") or execution.get("expiry_mode") or "NEAREST"
    target_delta = float(target_delta if target_delta is not None else sel_cfg.get("target_delta", 0.60) or 0.60)
    option_type = option_type.upper()

    contracts = _available_option_contracts(
        cfg,
        option_type,
        expiry_mode=expiry_mode,
        force_master_refresh=bool((execution.get("instrument_selector", {}) or {}).get("force_refresh", False)),
    )
    step = float(sel_cfg.get("strike_step") or _strike_step(contracts, 100.0))
    atm = _atm_strike(contracts, float(underlying_ltp))

    if mode == "ATM":
        target_strike = atm
        selection_note = "ATM"
    elif mode == "DELTA":
        # Conservative delta proxy:
        #   0.50 ≈ ATM
        #   0.60 ≈ 1 strike ITM
        #   0.70 ≈ 2 strikes ITM
        #   0.30 ≈ 2 strikes OTM for short-option selling
        # This is deterministic and safe for paper/live until true Greeks are
        # added from an option-chain provider.
        if target_delta >= 0.50:
            steps = max(0, int(round((target_delta - 0.50) / 0.10)))
            if option_type == "CE":
                target_strike = atm - steps * step
            else:
                target_strike = atm + steps * step
        else:
            steps = max(1, int(round((0.50 - target_delta) / 0.10)))
            if option_type == "CE":
                target_strike = atm + steps * step
            else:
                target_strike = atm - steps * step
        selection_note = f"DELTA_PROXY target={target_delta:.2f}"
    else:
        if fallback != "ATM":
            raise RuntimeError(f"Unsupported strike_selection.mode={mode}; fallback={fallback}")
        target_strike = atm
        selection_note = f"fallback ATM from unsupported mode {mode}"

    chosen = _nearest_contract_by_strike(contracts, target_strike)
    selected = InstrumentSelection(
        exchange=str(chosen["exchange"]),
        tradingsymbol=str(chosen["tradingsymbol"]),
        symboltoken=str(chosen["symboltoken"]),
        expiry=str(chosen["expiry"]),
        lot_size=int(chosen["lot_size"]),
        name=str(chosen["name"]),
        instrument_type="OPTIDX",
    )
    d = selected.to_dict()
    d["option_type"] = option_type
    d["strike"] = float(chosen["strike"])
    d["selection_note"] = selection_note
    # Attach temporary attributes via dict in caller; InstrumentSelection remains
    # backward-compatible for futures.
    selected._extra = d  # type: ignore[attr-defined]
    print(
        f"[{chosen['name']}] Option selected: {selected.tradingsymbol} | "
        f"{option_type} {chosen['strike']:.0f} | Expiry: {selected.expiry} | "
        f"Lot: {selected.lot_size} | Token: {selected.symboltoken} | {selection_note}"
    )
    return selected


def selection_to_dict(selected: InstrumentSelection) -> Dict[str, Any]:
    extra = getattr(selected, "_extra", None)
    if isinstance(extra, dict):
        return extra
    return selected.to_dict()


def select_option_by_strike(
    cfg: Dict[str, Any],
    *,
    option_type: str,
    strike: float,
    expiry_mode: Optional[str] = None,
) -> Dict[str, Any]:
    execution = cfg.get("execution", {}) or {}
    opt_cfg = cfg.get("option_execution", {}) or {}
    expiry_mode = expiry_mode or opt_cfg.get("expiry_mode") or execution.get("expiry_mode") or "NEAREST"
    contracts = _available_option_contracts(
        cfg,
        option_type.upper(),
        expiry_mode=expiry_mode,
        force_master_refresh=bool((execution.get("instrument_selector", {}) or {}).get("force_refresh", False)),
    )
    chosen = _nearest_contract_by_strike(contracts, float(strike))
    return {
        "exchange": str(chosen["exchange"]),
        "tradingsymbol": str(chosen["tradingsymbol"]),
        "symboltoken": str(chosen["symboltoken"]),
        "expiry": str(chosen["expiry"]),
        "lot_size": int(chosen["lot_size"]),
        "name": str(chosen["name"]),
        "instrument_type": "OPTIDX",
        "option_type": option_type.upper(),
        "strike": float(chosen["strike"]),
    }
