from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend_api.app.database.session import get_db
from backend_api.app.services import redis_state
from backend_api.app.services.engine_controller import status as engine_status

router = APIRouter(tags=["health"])


@router.get("/health")
def health(db: Session = Depends(get_db)):
    db_ok = "ok"
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        db_ok = f"error: {exc}"

    redis_ok = "ok"
    try:
        redis_state.get_redis().ping()
    except Exception as exc:
        redis_ok = f"error: {exc}"

    return {"status": "ok", "database": db_ok, "redis": redis_ok}


@router.get("/broker/status")
def broker_status():
    state = engine_status()
    return {"engine_state": state["state"], "mode": state["mode"]}
