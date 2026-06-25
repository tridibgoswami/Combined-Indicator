from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend_api.app.auth.security import get_current_user, require_admin
from backend_api.app.database.models import User
from backend_api.app.database.session import get_db
from backend_api.app.schemas.schemas import ConfigPatchRequest
from backend_api.app.services import config_service

router = APIRouter(prefix="/config", tags=["config"])

# Secret fields are never returned by the API even though they live in the
# config file structure (real secrets come from .env, not config.yaml).
_REDACT_PATHS = {("broker", "angelone")}


def _redact(cfg: dict) -> dict:
    cfg = dict(cfg)
    broker = cfg.get("broker", {})
    if isinstance(broker, dict) and "angelone" in broker:
        cfg["broker"] = {**broker, "angelone": {k: "***" for k in broker["angelone"]}}
    return cfg


@router.get("")
def get_config(user: User = Depends(get_current_user)):
    return _redact(config_service.read_config())


@router.patch("")
def patch_config(payload: ConfigPatchRequest, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    if payload.path.startswith("broker."):
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Broker secrets must be set via .env, not the config API")
    cfg = config_service.patch_config(payload.path, payload.value, db, user.id)
    return _redact(cfg)
