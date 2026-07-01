from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from trading_engine.instrument_selector.instrument_selector import (
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
    last_idempotency_key: str | None = None


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
        # File-based control flags so the backend platform (or any external
        # supervisor) can pause/flatten execution without coupling this
        # engine layer to a specific infra dependency (Redis/DB/etc).
        control_dir = Path(self.cfg.get("execution", {}).get("control_dir") or "data/cache")
        if not control_dir.is_absolute():
            control_dir = Path(__file__).resolve().parents[2] / control_dir
        control_dir.mkdir(parents=True, exist_ok=True)
        self.emergency_stop_flag = control_dir / "EMERGENCY_STOP"
        self.exit_all_flag = control_dir / "EXIT_ALL_REQUESTED"

    def _ensure_order_log(self) -> None:
        self.order_log.parent.mkdir(parents=True, exist_ok=True)
        if self.order_log.exists():
            # Migrate legacy files that are missing the ltp column
            with self.order_log.open("r", encoding="utf-8") as f:
                first = f.readline()
            if "ltp" not in first:
                import tempfile, shutil
                tmp = self.order_log.with_suffix(".tmp")
                with self.order_log.open("r", encoding="utf-8") as src, tmp.open("w", newline="", encoding="utf-8") as dst:
                    reader = csv.DictReader(src)
                    writer = csv.DictWriter(dst, fieldnames=[
                        "datetime", "mode", "instrument_mode", "action", "side", "quantity",
                        "tradingsymbol", "symboltoken", "exchange", "from_position", "to_position",
                        "reason", "ltp", "broker_response",
                    ])
                    writer.writeheader()
                    for row in reader:
                        row.setdefault("ltp", "")
                        writer.writerow(row)
                shutil.move(str(tmp), str(self.order_log))
            return
        with self.order_log.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "datetime", "mode", "instrument_mode", "action", "side", "quantity",
                "tradingsymbol", "symboltoken", "exchange", "from_position", "to_position",
                "reason", "ltp", "broker_response",
            ])

    def _log_order(self, action: str, side: str, quantity: int, from_pos: int, to_pos: int, reason: str, response: Any, instrument: Dict[str, Any] | None = None, ltp: float | None = None) -> None:
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
                ltp if ltp is not None else "",
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
                broker_position = 1 if net_qty > 0 else -1 if net_qty < 0 else 0
                if broker_position != 0 and broker_position != desired:
                    # Broker already holds a position that disagrees with the
                    # strategy's reconstructed state. Pausing avoids placing an
                    # order on top of an unexpected/manual position.
                    self.emergency_stop_flag.write_text(
                        f"Paused at startup: broker position ({broker_position}) conflicts with "
                        f"strategy position ({desired}). Resolve manually then delete this file.",
                        encoding="utf-8",
                    )
                    print(f"EXECUTION PAUSED: broker net position qty={net_qty} conflicts with strategy state. Wrote {self.emergency_stop_flag}")
                self.state.position = broker_position
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

    def _execution_ltp(self) -> float | None:
        """Fetch the live LTP for the execution instrument (futures contract)."""
        try:
            if hasattr(self.broker, "ltp"):
                return float(self.broker.ltp(execution=True))
        except Exception:
            pass
        return None

    def _send(self, side: str, quantity: int, from_pos: int, to_pos: int, reason: str, instrument: Dict[str, Any] | None = None) -> Any:
        if quantity <= 0:
            return {"status": False, "message": "quantity <= 0"}
        ltp: float | None = None
        if self.mode == "PAPER":
            ltp = self._execution_ltp()
            response = {
                "status": True,
                "paper": True,
                "side": side,
                "quantity": quantity,
                "reason": reason,
                "ltp": ltp,
                "instrument": instrument or (self.cfg.get("execution", {}) or {}).get("resolved_instrument", {}),
            }
        else:
            if not self.allow_live_orders:
                raise RuntimeError("LIVE execution requested but execution.allow_live_orders=false")
            response = self.broker.place_order(side, quantity, instrument=instrument)
            # For LIVE orders the broker response contains the fill price; try to extract it.
            try:
                ltp = float(response.get("ltp") or response.get("price") or 0) or None
            except (TypeError, ValueError):
                ltp = None
        self._log_order("ORDER", side, quantity, from_pos, to_pos, reason, response, instrument, ltp=ltp)
        sym = (instrument or {}).get("tradingsymbol", "RESOLVED")
        print(f"ORDER [{self.mode}/{self.instrument_mode}] {side} {sym} qty={quantity} | {from_pos} -> {to_pos} | reason={reason} | ltp={ltp} | response={response}")
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

    def _is_emergency_stopped(self) -> bool:
        return self.emergency_stop_flag.exists()

    def exit_all(self, reason: str = "EXIT_ALL_REQUESTED") -> None:
        """Flatten any open position/legs immediately, bypassing the emergency-stop gate."""
        current = self.state.position
        if current == 0 and not self.state.active_legs:
            return
        if self.instrument_mode == "FUTURES":
            self.state.position = self._align_futures(0, reason, current)
        elif self.instrument_mode in {"OPTION_BUYING", "OPTION_SELLING"}:
            self.state.position = self._align_options(0, reason, current)

    def align_to_strategy(self, summary: Dict[str, Any], reason: str = "SIGNAL_UPDATE") -> None:
        if not self.enabled:
            return

        # Idempotency: never re-fire the same signal/order event twice (e.g. if
        # the live loop reprocesses the same closed candle after a restart).
        signal_dt = str((summary.get("last_signal") or {}).get("datetime") or "")
        idempotency_key = f"{signal_dt}:{self.instrument_mode}:{summary.get('current_position')}"
        if signal_dt and idempotency_key == self.state.last_idempotency_key:
            return

        if self.exit_all_flag.exists():
            self.exit_all(reason="EXIT_ALL_FLAG")
            self.exit_all_flag.unlink(missing_ok=True)
            return

        if self._is_emergency_stopped():
            self._log_order("BLOCKED", "NONE", 0, self.state.position, self.state.position, "EMERGENCY_STOP_ACTIVE", {"status": False, "message": "emergency stop active"})
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
        if signal_dt:
            self.state.last_idempotency_key = idempotency_key
