from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from brokers.instrument_selector import (
    select_option_contract,
    select_option_by_strike,
    selection_to_dict,
)


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
        self.instrument_mode = str(
            self.execution.get("instrument_mode")
            or self.execution.get("execution_mode")
            or "FUTURES"
        ).upper()
        self.allow_live_orders = bool(self.execution.get("allow_live_orders", False))
        self.trade_startup = bool(self.execution.get("trade_reconstructed_position_on_startup", False))
        self.reconcile_on_startup = bool(self.execution.get("reconcile_on_startup", True))
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
                "reason", "broker_response",
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

    def _send(self, side: str, quantity: int, from_pos: int, to_pos: int, reason: str, instrument: Dict[str, Any] | None = None) -> Any:
        if quantity <= 0:
            return {"status": False, "message": "quantity <= 0"}
        if self.mode == "PAPER":
            response = {
                "status": True,
                "paper": True,
                "side": side,
                "quantity": quantity,
                "reason": reason,
                "instrument": instrument or (self.cfg.get("execution", {}) or {}).get("resolved_instrument", {}),
            }
        else:
            if not self.allow_live_orders:
                raise RuntimeError("LIVE execution requested but execution.allow_live_orders=false")
            response = self.broker.place_order(side, quantity, instrument=instrument)
        self._log_order("ORDER", side, quantity, from_pos, to_pos, reason, response, instrument)
        sym = (instrument or {}).get("tradingsymbol", "RESOLVED")
        print(f"ORDER [{self.mode}/{self.instrument_mode}] {side} {sym} qty={quantity} | {from_pos} -> {to_pos} | reason={reason} | response={response}")
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

    def _select_spread_legs(self, desired: int) -> List[Dict[str, Any]]:
        selling = self.option_cfg.get("option_selling", {}) or {}
        short_delta = float(selling.get("short_delta", 0.30) or 0.30)
        hedge_strikes = int(selling.get("hedge_strikes", 5) or 5)
        hedge_distance_points = float(selling.get("hedge_distance_points", 0) or 0)
        underlying_ltp = self._underlying_ltp()

        if desired == 1:
            # Bull Put Spread: sell PE, buy lower PE hedge.
            short_sel = select_option_contract(
                self.cfg,
                option_type="PE",
                underlying_ltp=underlying_ltp,
                purpose="OPTION_SELLING_SHORT",
                target_delta=short_delta,
                expiry_mode=self.option_cfg.get("expiry_mode"),
            )
            short_leg = selection_to_dict(short_sel)
            step = float((self.option_cfg.get("strike_selection", {}) or {}).get("strike_step") or 100)
            hedge_strike = float(short_leg["strike"]) - (hedge_distance_points if hedge_distance_points > 0 else hedge_strikes * step)
            hedge_leg = select_option_by_strike(self.cfg, option_type="PE", strike=hedge_strike, expiry_mode=self.option_cfg.get("expiry_mode"))
            return [
                {"action": "SELL", "instrument": short_leg},
                {"action": "BUY", "instrument": hedge_leg},
            ]

        # Bear Call Spread: sell CE, buy higher CE hedge.
        short_sel = select_option_contract(
            self.cfg,
            option_type="CE",
            underlying_ltp=underlying_ltp,
            purpose="OPTION_SELLING_SHORT",
            target_delta=short_delta,
            expiry_mode=self.option_cfg.get("expiry_mode"),
        )
        short_leg = selection_to_dict(short_sel)
        step = float((self.option_cfg.get("strike_selection", {}) or {}).get("strike_step") or 100)
        hedge_strike = float(short_leg["strike"]) + (hedge_distance_points if hedge_distance_points > 0 else hedge_strikes * step)
        hedge_leg = select_option_by_strike(self.cfg, option_type="CE", strike=hedge_strike, expiry_mode=self.option_cfg.get("expiry_mode"))
        return [
            {"action": "SELL", "instrument": short_leg},
            {"action": "BUY", "instrument": hedge_leg},
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
                suffix = "_BULL_PUT_SPREAD" if desired == 1 else "_BEAR_CALL_SPREAD"
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

    def align_to_strategy(self, summary: Dict[str, Any], reason: str = "SIGNAL_UPDATE") -> None:
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
