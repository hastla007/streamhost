"""Authentication endpoints."""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core.auth import AuthenticatedUser, authenticate_user, create_access_token, get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.core.security import enforce_rate_limit
from app.schemas import DEFAULT_ERROR_RESPONSES, Token

router = APIRouter()


@router.post(
    "/token",
    response_model=Token,
    responses=DEFAULT_ERROR_RESPONSES,
    dependencies=[Depends(enforce_rate_limit)],
)
def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)
) -> Token:
    user = authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect username or password")
    access_token = create_access_token(subject=user.username, expires_delta=timedelta(minutes=settings.jwt_expiry_minutes))
    return Token(access_token=access_token, token_type="bearer")


@router.get("/me", responses=DEFAULT_ERROR_RESPONSES)
def read_users_me(current_user: AuthenticatedUser = Depends(get_current_user)) -> AuthenticatedUser:
    return current_user
