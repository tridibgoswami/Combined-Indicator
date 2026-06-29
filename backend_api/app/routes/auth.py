from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend_api.app.auth.security import create_access_token, get_current_user, verify_password
from backend_api.app.database.models import User
from backend_api.app.database.session import get_db
from backend_api.app.schemas.schemas import LoginRequest, TokenResponse, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    return TokenResponse(access_token=create_access_token(user.email))


@router.post("/logout")
def logout(user: User = Depends(get_current_user)):
    # Stateless JWT: logout is a client-side token discard. Returned for API completeness.
    return {"status": "ok"}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user
