from __future__ import annotations

from fastapi import APIRouter, Depends

from backend_api.app.auth.security import get_current_user, require_admin
from backend_api.app.database.models import User
from backend_api.app.services import engine_controller, outputs_service

router = APIRouter(tags=["trading"])


@router.get("/broker/status")
def broker_status(user: User = Depends(get_current_user)):
    eng_status = engine_controller.status()
    connected = eng_status["state"] == "RUNNING"
    return {
        "status": "CONNECTED" if connected else "DISCONNECTED",
        "detail": "AngelOne session active via running engine" if connected else "Engine not running",
    }


@router.get("/positions")
def positions(user: User = Depends(get_current_user)):
    summary = outputs_service.get_summary()
    entry_time = summary.get("current_entry_time")
    return {
        "current_position": summary.get("current_position", "FLAT"),
        "entry_spot_price": summary.get("current_entry_price"),
        "entry_futures_price": outputs_service._futures_price_near(entry_time or "", entry=True),
        "entry_time": entry_time,
        "open_points": summary.get("open_points", 0),
    }


@router.get("/orders")
def orders(user: User = Depends(get_current_user)):
    return outputs_service.get_orders()


@router.get("/signals")
def signals(user: User = Depends(get_current_user)):
    return outputs_service.get_live_signals()


@router.get("/trades")
def trades(user: User = Depends(get_current_user)):
    return outputs_service.get_live_trades()


@router.get("/last-trade")
def last_trade(user: User = Depends(get_current_user)):
    return outputs_service.get_last_closed_trade()


@router.get("/pnl")
def pnl(user: User = Depends(get_current_user)):
    return outputs_service.get_pnl()


@router.post("/risk/exit-all")
def exit_all(user: User = Depends(require_admin)):
    engine_controller.exit_all()
    return {"status": "ok", "message": "exit-all flag set; engine will flatten open positions on next loop tick"}


@router.post("/risk/disable-live-trading")
def disable_live_trading(user: User = Depends(require_admin)):
    engine_controller.disable_live_trading()
    return {"status": "ok", "message": "emergency stop active; no new orders will be placed"}
