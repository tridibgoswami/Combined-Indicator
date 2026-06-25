from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend_api.app.auth.security import get_current_user, require_admin
from backend_api.app.database.models import User
from backend_api.app.schemas.schemas import EngineStatusOut, ModeChangeRequest
from backend_api.app.services import config_service, engine_controller

router = APIRouter(prefix="/engine", tags=["engine"])


@router.get("/status", response_model=EngineStatusOut)
def get_status(user: User = Depends(get_current_user)):
    return engine_controller.status()


@router.post("/start", response_model=EngineStatusOut)
def start(user: User = Depends(require_admin)):
    return engine_controller.start()


@router.post("/stop", response_model=EngineStatusOut)
def stop(user: User = Depends(require_admin)):
    return engine_controller.stop()


@router.post("/restart", response_model=EngineStatusOut)
def restart(user: User = Depends(require_admin)):
    return engine_controller.restart()


@router.post("/paper-mode")
def paper_mode(user: User = Depends(require_admin)):
    # Paper mode is always safe to set without extra confirmation.
    from backend_api.app.database.session import SessionLocal
    db = SessionLocal()
    try:
        config_service.patch_config("execution.mode", "PAPER", db, user.id)
        config_service.patch_config("execution.allow_live_orders", False, db, user.id)
    finally:
        db.close()
    return {"status": "ok", "mode": "PAPER"}


@router.post("/live-mode")
def live_mode(payload: ModeChangeRequest, user: User = Depends(require_admin)):
    if not payload.confirm:
        raise HTTPException(
            status_code=400,
            detail="LIVE mode requires explicit confirm=true. Live orders remain gated by "
                   "execution.allow_live_orders in config until separately enabled.",
        )
    from backend_api.app.database.session import SessionLocal
    db = SessionLocal()
    try:
        config_service.patch_config("execution.mode", "LIVE", db, user.id)
    finally:
        db.close()
    return {"status": "ok", "mode": "LIVE", "note": "execution.allow_live_orders still controls real order placement"}
