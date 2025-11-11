"""Password hashing utilities."""
from __future__ import annotations

import bcrypt


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against the stored hash."""

    if not hashed_password:
        return False
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


def get_password_hash(password: str) -> str:
    """Hash a password for storage."""

    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
