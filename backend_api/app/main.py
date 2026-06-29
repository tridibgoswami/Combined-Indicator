from __future__ import annotations

import os
import time
from collections import defaultdict

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend_api.app.auth.security import hash_password
from backend_api.app.database.models import Role, User
from backend_api.app.database.session import SessionLocal, init_db
from backend_api.app.routes import auth, backtest, config, engine, health, trading

app = FastAPI(title="Trading Platform API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Simple in-memory sliding-window rate limiter (per client IP). For multi-process
# deployments, swap this for the Redis-backed lock in services/redis_state.py.
_rate_limit_hits: dict[str, list[float]] = defaultdict(list)
RATE_LIMIT_REQUESTS = int(os.getenv("RATE_LIMIT_REQUESTS", "120"))
RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    client_ip = request.client.host if request.client else "unknown"
    now = time.time()
    window_start = now - RATE_LIMIT_WINDOW_SECONDS
    hits = [t for t in _rate_limit_hits[client_ip] if t > window_start]
    hits.append(now)
    _rate_limit_hits[client_ip] = hits
    if len(hits) > RATE_LIMIT_REQUESTS:
        return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"})
    return await call_next(request)


app.include_router(auth.router)
app.include_router(engine.router)
app.include_router(trading.router)
app.include_router(backtest.router)
app.include_router(config.router)
app.include_router(health.router)


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    _bootstrap_admin()


def _bootstrap_admin() -> None:
    """Create the initial admin user from env vars if no users exist yet.

    Required so a fresh deployment has a strong, non-default admin login
    instead of a hardcoded credential.
    """
    admin_email = os.getenv("ADMIN_EMAIL")
    admin_password = os.getenv("ADMIN_PASSWORD")
    if not admin_email or not admin_password:
        return
    db = SessionLocal()
    try:
        if db.query(User).count() == 0:
            db.add(User(email=admin_email, hashed_password=hash_password(admin_password), role=Role.ADMIN))
            db.commit()
    finally:
        db.close()
