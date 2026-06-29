from __future__ import annotations

from pathlib import Path

import pytest

from trading_engine.execution_engine.execution import ExecutionManager


class FakeBroker:
    def __init__(self, net_qty: int = 0, ltp: float = 50000.0):
        self._net_qty = net_qty
        self._ltp = ltp
        self.orders = []

    def get_net_position_qty(self) -> int:
        return self._net_qty

    def ltp(self, execution: bool = False) -> float:
        return self._ltp

    def place_order(self, side, quantity, instrument=None):
        self.orders.append((side, quantity, instrument))
        return {"status": True, "order_id": f"FAKE-{len(self.orders)}"}


def _base_cfg(tmp_path: Path) -> dict:
    return {
        "instrument": {"lot_size": 30, "lots": 1},
        "trading": {"lots": 1, "quantity": 0},
        "execution": {
            "enabled": True,
            "mode": "PAPER",
            "instrument_mode": "FUTURES",
            "allow_live_orders": False,
            "trade_reconstructed_position_on_startup": False,
            "reconcile_on_startup": True,
            "control_dir": str(tmp_path),
        },
        "option_execution": {},
    }


def _summary(position: str, signal_dt: str = "2026-06-01 10:00:00"):
    return {"current_position": position, "last_signal": {"datetime": signal_dt}}


def test_paper_orders_are_logged_not_sent_live(tmp_path):
    cfg = _base_cfg(tmp_path)
    broker = FakeBroker()
    mgr = ExecutionManager(cfg, broker, tmp_path)
    mgr.startup_sync(_summary("FLAT"))
    mgr.align_to_strategy(_summary("LONG"))
    assert broker.orders == []  # paper mode never calls broker.place_order
    rows = mgr.order_log.read_text().splitlines()
    assert any("PAPER" in row and "BUY" in row for row in rows[1:])


def test_emergency_stop_blocks_new_orders(tmp_path):
    cfg = _base_cfg(tmp_path)
    mgr = ExecutionManager(cfg, FakeBroker(), tmp_path)
    mgr.startup_sync(_summary("FLAT"))
    mgr.emergency_stop_flag.write_text("stopped")
    mgr.align_to_strategy(_summary("LONG"))
    assert mgr.state.position == 0  # never entered
    rows = mgr.order_log.read_text().splitlines()
    assert any("BLOCKED" in row for row in rows[1:])


def test_exit_all_flattens_open_position(tmp_path):
    cfg = _base_cfg(tmp_path)
    mgr = ExecutionManager(cfg, FakeBroker(), tmp_path)
    mgr.startup_sync(_summary("FLAT"))
    mgr.align_to_strategy(_summary("LONG"))
    assert mgr.state.position == 1
    mgr.exit_all_flag.write_text("requested")
    mgr.align_to_strategy(_summary("LONG", signal_dt="2026-06-01 10:05:00"))
    assert mgr.state.position == 0
    assert not mgr.exit_all_flag.exists()


def test_duplicate_signal_does_not_double_order(tmp_path):
    cfg = _base_cfg(tmp_path)
    broker = FakeBroker()
    mgr = ExecutionManager(cfg, broker, tmp_path)
    mgr.startup_sync(_summary("FLAT"))
    mgr.align_to_strategy(_summary("LONG", signal_dt="2026-06-01 10:00:00"))
    rows_after_first = mgr.order_log.read_text().splitlines()
    mgr.align_to_strategy(_summary("LONG", signal_dt="2026-06-01 10:00:00"))
    rows_after_second = mgr.order_log.read_text().splitlines()
    assert rows_after_first == rows_after_second  # idempotency key matched, no-op


def test_startup_reconciliation_pauses_on_conflict(tmp_path):
    cfg = _base_cfg(tmp_path)
    cfg["execution"]["mode"] = "LIVE"
    cfg["execution"]["allow_live_orders"] = True
    broker = FakeBroker(net_qty=30)  # broker already long
    mgr = ExecutionManager(cfg, broker, tmp_path)
    mgr.startup_sync(_summary("SHORT"))  # strategy thinks it should be short
    assert mgr.emergency_stop_flag.exists()


def test_live_orders_blocked_without_allow_live_orders(tmp_path):
    cfg = _base_cfg(tmp_path)
    cfg["execution"]["mode"] = "LIVE"
    cfg["execution"]["allow_live_orders"] = False
    mgr = ExecutionManager(cfg, FakeBroker(), tmp_path)
    mgr.startup_sync(_summary("FLAT"))
    with pytest.raises(RuntimeError):
        mgr.align_to_strategy(_summary("LONG"))
