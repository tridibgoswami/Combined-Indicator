from __future__ import annotations

import csv
import copy
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from brokers.instrument_selector import (
    select_option_contract,
    select_option_by_strike,
    selection_to_dict,
)


class Ansi:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"


def _color(text: object, color: str) -> str:
    return f"{color}{text}{Ansi.RESET}"


def _fmt_money(x: object) -> str:
    try:
        return f"₹{float(x):,.2f}"
    except Exception:
        return str(x)


def _fmt_num(x: object) -> str:
    try:
        return f"{float(x):,.2f}"
    except Exception:
        return str(x)


def _parse_execution_modes(value: Any) -> List[str]:
    """Return execution instrument modes as a clean list.

    Supports legacy comma-separated strings as well as the new list-based
    execution.enabled_modes / execution_engines.*.enabled config.
    """
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        raw = []
        for item in value:
            raw.extend(str(item).replace("|", ",").split(","))
    else:
        raw = str(value).replace("|", ",").split(",")
    modes = []
    for item in raw:
        m = str(item).strip().upper().replace("-", "_").replace(" ", "_")
        if not m:
            continue
        if m in {"FUTURE", "FUTURES"}:
            m = "FUTURES"
        elif m in {"OPTION_BUY", "OPTIONS_BUYING", "OPTION_BUYING"}:
            m = "OPTION_BUYING"
        elif m in {"OPTION_SELL", "OPTIONS_SELLING", "OPTION_SELLING"}:
            m = "OPTION_SELLING"
        if m not in modes:
            modes.append(m)
    return modes


def enabled_execution_modes(cfg: Dict[str, Any]) -> List[str]:
    execution = cfg.get("execution", {}) or {}
    engines = cfg.get("execution_engines", {}) or {}

    explicit = execution.get("enabled_modes") or execution.get("instrument_modes")
    modes = _parse_execution_modes(explicit)

    if not modes and engines:
        if bool((engines.get("futures", {}) or {}).get("enabled", False)):
            modes.append("FUTURES")
        if bool((engines.get("option_buying", {}) or {}).get("enabled", False)):
            modes.append("OPTION_BUYING")
        if bool((engines.get("option_selling", {}) or {}).get("enabled", False)):
            modes.append("OPTION_SELLING")

    if not modes:
        modes = _parse_execution_modes(
            execution.get("instrument_mode")
            or execution.get("execution_mode")
            or cfg.get("instrument_mode")
            or cfg.get("execution_mode")
            or "FUTURES"
        )
    return modes or ["FUTURES"]


@dataclass
class ExecutionState:
    position: int = 0  # 1 long/bullish, -1 short/bearish, 0 flat
    quantity: int = 0
    last_strategy_position: str = "FLAT"
    startup_synced: bool = False
    active_legs: List[Dict[str, Any]] = field(default_factory=list)


class ExecutionManager:
    """Order-execution layer for the signal engine.

    Supported execution.instrument_mode:
      FUTURES        BUY -> long future, SELL -> short future
      OPTION_BUYING  BUY -> buy CE, SELL -> buy PE
      OPTION_SELLING BUY -> bull put spread, SELL -> bear call spread

    Safety rules:
    - Defaults to disabled/paper mode from config.
    - LIVE orders require execution.allow_live_orders=true.
    - Startup reconstructed positions are not automatically traded unless
      execution.trade_reconstructed_position_on_startup=true.
    """

    def __init__(self, cfg: Dict[str, Any], broker: Any, out_dir: Path):
        self.cfg = cfg
        self.broker = broker
        self.out_dir = out_dir
        self.execution = cfg.get("execution", {}) or {}
        self.trading = cfg.get("trading", {}) or {}
        self.option_cfg = cfg.get("option_execution", {}) or {}
        self.enabled = bool(self.execution.get("enabled", self.trading.get("execute_orders", False)))
        self.mode = str(self.execution.get("mode", "PAPER" if self.trading.get("paper_trade", True) else "LIVE")).upper()
        self.allow_live_orders = bool(self.execution.get("allow_live_orders", False))
        self.trade_startup = bool(self.execution.get("trade_reconstructed_position_on_startup", False))
        self.reconcile_on_startup = bool(self.execution.get("reconcile_on_startup", True))

        self.multi_modes = enabled_execution_modes(cfg)
        self.children: List[ExecutionManager] = []
        if len(self.multi_modes) > 1:
            # Parent fan-out manager. Each child has its own position state and
            # writes to the same order log, but strategy signals remain shared.
            for mode in self.multi_modes:
                child_cfg = copy.deepcopy(cfg)
                child_cfg.setdefault("execution", {})["enabled_modes"] = [mode]
                child_cfg.setdefault("execution", {})["instrument_mode"] = mode
                child_cfg.setdefault("execution", {})["execution_mode"] = mode
                self.children.append(ExecutionManager(child_cfg, broker, out_dir))
            self.instrument_mode = ", ".join(self.multi_modes)
            self.state = ExecutionState()
            self.order_log = out_dir / "orders.csv"
            self._ensure_order_log()
            return

        self.instrument_mode = self.multi_modes[0]
        self.state = ExecutionState()
        self.order_log = out_dir / "orders.csv"
        self._ensure_order_log()

    def _ensure_order_log(self) -> None:
        if self.order_log.exists():
            return
        self.order_log.parent.mkdir(parents=True, exist_ok=True)
        with self.order_log.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "datetime", "mode", "instrument_mode", "action", "side", "quantity",
                "tradingsymbol", "symboltoken", "exchange", "from_position", "to_position",
                "reason", "ltp", "strike", "option_type", "expiry", "broker_response",
            ])

    def _log_order(self, action: str, side: str, quantity: int, from_pos: int, to_pos: int, reason: str, response: Any, instrument: Dict[str, Any] | None = None) -> None:
        instrument = instrument or {}
        with self.order_log.open("a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.now().isoformat(timespec="seconds"),
                self.mode,
                self.instrument_mode,
                action,
                side,
                quantity,
                instrument.get("tradingsymbol", ""),
                instrument.get("symboltoken", ""),
                instrument.get("exchange", ""),
                from_pos,
                to_pos,
                reason,
                instrument.get("ltp", response.get("ltp", "") if isinstance(response, dict) else ""),
                instrument.get("strike", ""),
                instrument.get("option_type", ""),
                instrument.get("expiry", ""),
                str(response),
            ])

    def _base_quantity(self, instrument: Dict[str, Any] | None = None) -> int:
        instrument = instrument or {}
        resolved = (self.cfg.get("execution", {}) or {}).get("resolved_instrument", {}) or {}
        lot_size = int(
            instrument.get("lot_size")
            or resolved.get("lot_size")
            or self.execution.get("lot_size")
            or self.cfg.get("instrument", {}).get("lot_size")
            or 1
        )
        lots = int(self.execution.get("lots") or self.trading.get("lots") or self.cfg.get("instrument", {}).get("lots") or 1)
        explicit = int(self.execution.get("quantity") or self.trading.get("quantity") or 0)
        return explicit if explicit > 0 else lot_size * lots

    def _quantity(self) -> int:
        return self._base_quantity()

    def _strategy_pos_int(self, summary: Dict[str, Any]) -> int:
        pos = str(summary.get("current_position") or "FLAT").upper()
        if pos == "LONG":
            return 1
        if pos == "SHORT":
            return -1
        return 0

    def startup_sync(self, summary: Dict[str, Any]) -> None:
        if self.children:
            print("Execution engines active: " + ", ".join(self.multi_modes) + f" | Mode: {self.mode} | {'enabled' if self.enabled else 'disabled'}")
            for child in self.children:
                child.startup_sync(summary)
            return
        desired = self._strategy_pos_int(summary)
        qty = self._quantity()
        self.state.quantity = qty
        self.state.last_strategy_position = str(summary.get("current_position") or "FLAT").upper()

        if self.reconcile_on_startup and self.instrument_mode == "FUTURES" and self.mode == "LIVE" and self.allow_live_orders and hasattr(self.broker, "get_net_position_qty"):
            try:
                net_qty = int(self.broker.get_net_position_qty())
                self.state.position = 1 if net_qty > 0 else -1 if net_qty < 0 else 0
                print(f"Execution sync: broker net position qty={net_qty}; local execution position={self.state.position}")
            except Exception as exc:
                print(f"Execution sync warning: could not read broker positions: {exc}")
                self.state.position = 0
        else:
            self.state.position = 0

        print(
            f"Execution mode: {'DISABLED' if not self.enabled else self.mode} | "
            f"Instrument mode: {self.instrument_mode} | Qty: {qty} | Startup trade: {self.trade_startup}"
        )
        if self.enabled and self.trade_startup:
            self.align_to_strategy(summary, reason="STARTUP_RECONSTRUCTION")
        else:
            # Prevent the first reconstructed state from firing a stale order.
            self.state.position = desired
            self.state.startup_synced = True

    def _instrument_ltp_safe(self, instrument: Dict[str, Any] | None) -> float | None:
        if not instrument or not hasattr(self.broker, "ltp_for"):
            return None
        try:
            return float(self.broker.ltp_for(instrument))
        except Exception:
            return None

    def _execution_title(self, side: str, reason: str, instrument: Dict[str, Any] | None) -> str:
        reason_u = str(reason).upper()
        if self.instrument_mode == "OPTION_BUYING":
            opt = (instrument or {}).get("option_type", "OPTION")
            return f"OPTION BUYING | {side} {opt}"
        if self.instrument_mode == "OPTION_SELLING":
            if "BULL_PUT" in reason_u:
                return "OPTION SELLING | BULL PUT SPREAD LEG"
            if "BEAR_CALL" in reason_u:
                return "OPTION SELLING | BEAR CALL SPREAD LEG"
            return "OPTION SELLING | SPREAD LEG"
        return "FUTURES EXECUTION"

    def _print_order_block(self, side: str, quantity: int, from_pos: int, to_pos: int, reason: str, response: Any, instrument: Dict[str, Any] | None) -> None:
        instrument = instrument or (self.cfg.get("execution", {}) or {}).get("resolved_instrument", {}) or {}
        ltp = None
        if isinstance(response, dict) and response.get("ltp") is not None:
            try:
                ltp = float(response.get("ltp"))
            except Exception:
                ltp = None
        title = self._execution_title(side, reason, instrument)
        title_color = Ansi.GREEN if side.upper() == "BUY" else Ansi.RED
        paper_live = "PAPER ONLY - no broker order placed" if self.mode == "PAPER" else "LIVE ORDER SENT"
        print("\n" + _color("=" * 72, Ansi.BLUE))
        print(_color(title, title_color + Ansi.BOLD))
        print(_color("=" * 72, Ansi.BLUE))
        print(f"Execution Mode   : {self.instrument_mode}")
        print(f"Order Mode       : {self.mode}")
        print(f"Action           : {_color(side.upper(), title_color + Ansi.BOLD)}")
        print(f"Tradingsymbol    : {instrument.get('tradingsymbol', 'RESOLVED')}")
        print(f"Token            : {instrument.get('symboltoken', '')}")
        print(f"Exchange         : {instrument.get('exchange', '')}")
        if instrument.get("option_type"):
            print(f"Option Type      : {instrument.get('option_type')}")
        if instrument.get("strike") not in (None, ""):
            print(f"Strike           : {_fmt_num(instrument.get('strike'))}")
        if instrument.get("expiry"):
            print(f"Expiry           : {instrument.get('expiry')}")
        if instrument.get("selection_note"):
            print(f"Selection        : {instrument.get('selection_note')}")
        if ltp is not None:
            print(f"LTP/Premium      : {_fmt_money(ltp)}")
        print(f"Quantity         : {quantity}")
        print(f"Position Change  : {from_pos} -> {to_pos}")
        print(f"Reason           : {reason}")
        print(f"Status           : {_color(paper_live, Ansi.YELLOW if self.mode == 'PAPER' else Ansi.GREEN)}")
        print(_color("=" * 72, Ansi.BLUE) + "\n")

    def _send(self, side: str, quantity: int, from_pos: int, to_pos: int, reason: str, instrument: Dict[str, Any] | None = None) -> Any:
        if quantity <= 0:
            return {"status": False, "message": "quantity <= 0"}
        quoted_ltp = self._instrument_ltp_safe(instrument)
        if instrument is not None and quoted_ltp is not None:
            instrument = dict(instrument)
            instrument["ltp"] = quoted_ltp
        if self.mode == "PAPER":
            response = {
                "status": True,
                "paper": True,
                "side": side,
                "quantity": quantity,
                "reason": reason,
                "ltp": quoted_ltp,
                "instrument": instrument or (self.cfg.get("execution", {}) or {}).get("resolved_instrument", {}),
            }
        else:
            if not self.allow_live_orders:
                raise RuntimeError("LIVE execution requested but execution.allow_live_orders=false")
            response = self.broker.place_order(side, quantity, instrument=instrument)
            if isinstance(response, dict) and quoted_ltp is not None:
                response.setdefault("ltp", quoted_ltp)
        self._log_order("ORDER", side, quantity, from_pos, to_pos, reason, response, instrument)
        self._print_order_block(side, quantity, from_pos, to_pos, reason, response, instrument)
        return response

    def _underlying_ltp(self) -> float:
        # Signal instrument LTP is used as the underlying reference for option strike selection.
        if hasattr(self.broker, "ltp"):
            return float(self.broker.ltp(execution=False))
        price = self.cfg.get("last_underlying_ltp")
        if price is None:
            raise RuntimeError("Cannot select option strike: broker LTP method unavailable")
        return float(price)

    def _select_buy_option_leg(self, desired: int) -> Dict[str, Any]:
        option_type = "CE" if desired == 1 else "PE"
        underlying_ltp = self._underlying_ltp()
        selected = select_option_contract(
            self.cfg,
            option_type=option_type,
            underlying_ltp=underlying_ltp,
            purpose="OPTION_BUYING",
            target_delta=float((self.option_cfg.get("strike_selection", {}) or {}).get("target_delta", 0.60) or 0.60),
            expiry_mode=self.option_cfg.get("expiry_mode"),
        )
        return selection_to_dict(selected)

    def _select_hedge_by_premium(self, option_type: str, short_strike: float, direction: int, selling: Dict[str, Any]) -> Dict[str, Any] | None:
        """Find a cheap hedge by premium range.

        direction = -1 scans lower strikes, +1 scans higher strikes.
        Returns None if no valid hedge is found or LTP lookup is unavailable.
        """
        if not hasattr(self.broker, "ltp_for"):
            return None
        min_p = float(selling.get("hedge_premium_min", 10) or 10)
        max_p = float(selling.get("hedge_premium_max", 30) or 30)
        max_scan = int(selling.get("hedge_max_scan_strikes", 20) or 20)
        step = float((self.option_cfg.get("strike_selection", {}) or {}).get("strike_step") or 100)
        best = None
        best_ltp = None
        for i in range(1, max_scan + 1):
            strike = float(short_strike) + direction * step * i
            try:
                inst = select_option_by_strike(self.cfg, option_type=option_type, strike=strike, expiry_mode=self.option_cfg.get("expiry_mode"))
                ltp = float(self.broker.ltp_for(inst))
                if min_p <= ltp <= max_p:
                    inst = dict(inst)
                    inst["ltp"] = ltp
                    inst["selection_note"] = f"PREMIUM_HEDGE ₹{min_p:.0f}-₹{max_p:.0f}"
                    return inst
                # Keep the closest premium as diagnostic fallback candidate.
                dist = min(abs(ltp - min_p), abs(ltp - max_p))
                if best is None or dist < best_ltp:
                    best = dict(inst)
                    best["ltp"] = ltp
                    best["selection_note"] = f"nearest premium fallback; target ₹{min_p:.0f}-₹{max_p:.0f}"
                    best_ltp = dist
            except Exception:
                continue
        return None

    def _fallback_hedge_by_distance(self, option_type: str, short_strike: float, direction: int, selling: Dict[str, Any]) -> Dict[str, Any]:
        step = float((self.option_cfg.get("strike_selection", {}) or {}).get("strike_step") or 100)
        fallback_distance = float(selling.get("fallback_distance_points") or selling.get("hedge_distance_points") or 0)
        hedge_strikes = int(selling.get("hedge_strikes", 5) or 5)
        distance = fallback_distance if fallback_distance > 0 else hedge_strikes * step
        hedge_strike = float(short_strike) + direction * distance
        hedge = select_option_by_strike(self.cfg, option_type=option_type, strike=hedge_strike, expiry_mode=self.option_cfg.get("expiry_mode"))
        hedge["selection_note"] = f"STRIKE_DISTANCE fallback {distance:.0f} points"
        return hedge

    def _select_spread_legs(self, desired: int) -> List[Dict[str, Any]]:
        selling = self.option_cfg.get("option_selling", {}) or {}
        short_delta = float(selling.get("short_delta", 0.30) or 0.30)
        hedge_mode = str(selling.get("hedge_selection_mode", "PREMIUM") or "PREMIUM").upper()
        underlying_ltp = self._underlying_ltp()

        if desired == 1:
            # Bull Put Spread: sell PE, buy lower PE hedge.
            opt_type, hedge_dir, suffix = "PE", -1, "_BULL_PUT_SPREAD"
        else:
            # Bear Call Spread: sell CE, buy higher CE hedge.
            opt_type, hedge_dir, suffix = "CE", 1, "_BEAR_CALL_SPREAD"

        short_sel = select_option_contract(
            self.cfg,
            option_type=opt_type,
            underlying_ltp=underlying_ltp,
            purpose="OPTION_SELLING_SHORT",
            target_delta=short_delta,
            expiry_mode=self.option_cfg.get("expiry_mode"),
        )
        short_leg = selection_to_dict(short_sel)

        hedge_leg = None
        if hedge_mode == "PREMIUM":
            hedge_leg = self._select_hedge_by_premium(opt_type, float(short_leg["strike"]), hedge_dir, selling)
        if hedge_leg is None:
            hedge_leg = self._fallback_hedge_by_distance(opt_type, float(short_leg["strike"]), hedge_dir, selling)

        return [
            {"action": "SELL", "instrument": short_leg, "spread_suffix": suffix},
            {"action": "BUY", "instrument": hedge_leg, "spread_suffix": suffix},
        ]

    @staticmethod
    def _opposite_side(action: str) -> str:
        return "SELL" if str(action).upper() == "BUY" else "BUY"

    def _close_active_option_legs(self, from_pos: int, reason: str) -> None:
        if not self.state.active_legs:
            return
        # Close in reverse order: hedge first/last does not matter in paper mode,
        # but reverse order is safer for spread flattening.
        for leg in reversed(self.state.active_legs):
            close_side = self._opposite_side(leg["action"])
            instr = leg["instrument"]
            qty = self._base_quantity(instr)
            self._send(close_side, qty, from_pos, 0, reason + "_CLOSE_" + str(instr.get("tradingsymbol", "")), instr)
        self.state.active_legs = []

    def _open_option_target(self, desired: int, reason: str) -> None:
        if desired == 0:
            return
        if self.instrument_mode == "OPTION_BUYING":
            leg = {"action": "BUY", "instrument": self._select_buy_option_leg(desired)}
            qty = self._base_quantity(leg["instrument"])
            self._send(leg["action"], qty, 0, desired, reason + ("_BUY_CE" if desired == 1 else "_BUY_PE"), leg["instrument"])
            self.state.active_legs = [leg]
            return

        if self.instrument_mode == "OPTION_SELLING":
            legs = self._select_spread_legs(desired)
            for leg in legs:
                qty = self._base_quantity(leg["instrument"])
                suffix = leg.get("spread_suffix") or ("_BULL_PUT_SPREAD" if desired == 1 else "_BEAR_CALL_SPREAD")
                self._send(leg["action"], qty, 0, desired, reason + suffix, leg["instrument"])
            self.state.active_legs = legs
            return

        raise RuntimeError(f"Unsupported option instrument_mode={self.instrument_mode}")

    def _align_futures(self, desired: int, reason: str, current: int) -> int:
        qty = self._quantity()
        if desired == current:
            return current

        # Exit current position first if needed.
        if current == 1 and desired <= 0:
            self._send("SELL", qty, current, 0 if desired == 0 else desired, reason + "_EXIT_LONG")
            current = 0
        elif current == -1 and desired >= 0:
            self._send("BUY", qty, current, 0 if desired == 0 else desired, reason + "_EXIT_SHORT")
            current = 0

        # Enter new target side if needed.
        if desired == 1 and current == 0:
            self._send("BUY", qty, current, desired, reason + "_ENTER_LONG")
            current = 1
        elif desired == -1 and current == 0:
            self._send("SELL", qty, current, desired, reason + "_ENTER_SHORT")
            current = -1
        return desired

    def _align_options(self, desired: int, reason: str, current: int) -> int:
        if desired == current:
            return current
        self._close_active_option_legs(current, reason)
        self._open_option_target(desired, reason)
        return desired


    def _print_recommendation_header(self, title: str, color: str) -> None:
        print("\n" + _color("=" * 72, Ansi.BLUE))
        print(_color(title, color + Ansi.BOLD))
        print(_color("=" * 72, Ansi.BLUE))
        print(f"Execution Mode   : {self.instrument_mode}")
        print(f"Order Mode       : {self.mode}")
        print(_color("Status           : RECOMMENDATION / PAPER PREVIEW - no broker order placed", Ansi.YELLOW))

    def _print_instrument_recommendation(self, action: str, instrument: Dict[str, Any], quantity: int, note: str = "") -> float | None:
        inst = dict(instrument or {})
        ltp = inst.get("ltp")
        if ltp is None:
            try:
                ltp = self._instrument_ltp_safe(inst)
                if ltp is not None:
                    inst["ltp"] = ltp
            except Exception:
                ltp = None
        color = Ansi.GREEN if str(action).upper() == "BUY" else Ansi.RED
        print(f"Action           : {_color(str(action).upper(), color + Ansi.BOLD)}")
        print(f"Tradingsymbol    : {inst.get('tradingsymbol', '')}")
        print(f"Token            : {inst.get('symboltoken', '')}")
        print(f"Exchange         : {inst.get('exchange', '')}")
        if inst.get("option_type"):
            print(f"Option Type      : {inst.get('option_type')}")
        if inst.get("strike") not in (None, ""):
            print(f"Strike           : {_fmt_num(inst.get('strike'))}")
        if inst.get("expiry"):
            print(f"Expiry           : {inst.get('expiry')}")
        if inst.get("selection_note"):
            print(f"Selection        : {inst.get('selection_note')}")
        if ltp is not None:
            print(f"LTP/Premium      : {_fmt_money(ltp)}")
        else:
            print("LTP/Premium      : unavailable")
        print(f"Quantity         : {quantity}")
        if note:
            print(f"Note             : {note}")
        return float(ltp) if ltp is not None else None

    def print_recommendation_for_summary(self, summary: Dict[str, Any], reason: str = "CURRENT_SIGNAL_RECOMMENDATION") -> None:
        """Print selected execution instruments for the current strategy state.

        This is intentionally display-only. It does not send orders and does not
        mutate execution position state. Used for PAPER/live monitoring so the
        console always shows which futures/options/spread would be traded.
        """
        if self.children:
            for child in self.children:
                child.print_recommendation_for_summary(summary, reason=reason)
            return
        if not self.enabled:
            return
        desired = self._strategy_pos_int(summary)
        if desired == 0:
            return
        sig = "BUY" if desired == 1 else "SELL"
        try:
            if self.instrument_mode == "FUTURES":
                inst = (self.cfg.get("execution", {}) or {}).get("resolved_instrument", {}) or {}
                side = "BUY" if desired == 1 else "SELL"
                qty = self._base_quantity(inst)
                self._print_recommendation_header(f"FUTURES {sig} RECOMMENDATION", Ansi.GREEN if desired == 1 else Ansi.RED)
                self._print_instrument_recommendation(side, inst, qty, note=reason)
                print(_color("=" * 72, Ansi.BLUE) + "\n")
                return

            if self.instrument_mode == "OPTION_BUYING":
                inst = self._select_buy_option_leg(desired)
                side = "BUY"
                qty = self._base_quantity(inst)
                opt = inst.get("option_type", "OPTION")
                self._print_recommendation_header(f"OPTION BUYING {sig} SIGNAL | BUY {opt}", Ansi.GREEN if desired == 1 else Ansi.RED)
                self._print_instrument_recommendation(side, inst, qty, note=reason)
                print(_color("=" * 72, Ansi.BLUE) + "\n")
                return

            if self.instrument_mode == "OPTION_SELLING":
                legs = self._select_spread_legs(desired)
                title = "OPTION SELLING BUY SIGNAL | BULL PUT SPREAD" if desired == 1 else "OPTION SELLING SELL SIGNAL | BEAR CALL SPREAD"
                self._print_recommendation_header(title, Ansi.GREEN if desired == 1 else Ansi.RED)
                credit = 0.0
                credit_known = True
                for idx, leg in enumerate(legs, start=1):
                    print(_color(f"LEG {idx}", Ansi.CYAN + Ansi.BOLD))
                    inst = leg["instrument"]
                    action = leg["action"]
                    qty = self._base_quantity(inst)
                    ltp = self._print_instrument_recommendation(action, inst, qty, note=reason)
                    if ltp is None:
                        credit_known = False
                    else:
                        credit += ltp if action.upper() == "SELL" else -ltp
                    if idx < len(legs):
                        print(_color("-" * 72, Ansi.BLUE))
                if credit_known:
                    print(f"Net Credit       : {_color(_fmt_money(credit), Ansi.GREEN + Ansi.BOLD)}")
                else:
                    print("Net Credit       : unavailable")
                print(_color("=" * 72, Ansi.BLUE) + "\n")
                return
        except Exception as exc:
            print(_color(f"Execution recommendation unavailable for {self.instrument_mode}: {exc}", Ansi.YELLOW))

    def align_to_strategy(self, summary: Dict[str, Any], reason: str = "SIGNAL_UPDATE") -> None:
        if self.children:
            for child in self.children:
                child.align_to_strategy(summary, reason=reason)
            return
        if not self.enabled:
            return
        desired = self._strategy_pos_int(summary)
        current = self.state.position

        if self.instrument_mode == "FUTURES":
            self.state.position = self._align_futures(desired, reason, current)
        elif self.instrument_mode in {"OPTION_BUYING", "OPTION_SELLING"}:
            self.state.position = self._align_options(desired, reason, current)
        else:
            raise RuntimeError(f"execution.instrument_mode must be FUTURES, OPTION_BUYING, or OPTION_SELLING. Got: {self.instrument_mode}")

        self.state.last_strategy_position = str(summary.get("current_position") or "FLAT").upper()
