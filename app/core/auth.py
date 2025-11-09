"""Authentication helpers for JWT based auth."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.models import User
from app.security.passwords import verify_password


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")


class TokenPayload(BaseModel):
    sub: str
    exp: int


class AuthenticatedUser(BaseModel):
    id: int
    username: str
    is_admin: bool


def authenticate_user(db: Session, username: str, password: str) -> User | None:
    """Validate credentials and return the user."""

    user = db.scalar(select(User).where(User.username == username))
    if not user or not user.is_active:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


def create_access_token(subject: str, expires_delta: timedelta | None = None) -> str:
    """Create a signed JWT access token."""

    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=settings.jwt_expiry_minutes))
    to_encode = {"sub": subject, "exp": expire}
    return jwt.encode(to_encode, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)], db: Annotated[Session, Depends(get_db)]
) -> AuthenticatedUser:
    """Retrieve the authenticated user from the token."""

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        token_data = TokenPayload(**payload)
    except JWTError as exc:
        raise credentials_exception from exc

    user = db.scalar(select(User).where(User.username == token_data.sub))
    if not user or not user.is_active:
        raise credentials_exception
    return AuthenticatedUser(id=user.id, username=user.username, is_admin=user.is_admin)


def require_admin(user: Annotated[AuthenticatedUser, Depends(get_current_user)]) -> AuthenticatedUser:
    """Ensure the requester is an administrator."""

    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user
