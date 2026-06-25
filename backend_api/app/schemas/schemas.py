from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: int
    email: str
    role: str

    class Config:
        from_attributes = True


class EngineStatusOut(BaseModel):
    engine_id: str
    state: str
    mode: str
    instrument_mode: Optional[str] = None
    pid: Optional[int] = None
    detail: Optional[str] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ModeChangeRequest(BaseModel):
    confirm: bool = False


class BacktestRunRequest(BaseModel):
    start: str
    end: str
    source: str = "broker"
    csv_path: Optional[str] = None
    mae_points: Optional[float] = None


class BacktestRunResponse(BaseModel):
    backtest_id: str
    status: str


class ConfigPatchRequest(BaseModel):
    path: str  # dotted key, e.g. "risk_management.mae_points"
    value: Any


class HealthOut(BaseModel):
    status: str
    database: str
    redis: str
