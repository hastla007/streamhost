"""Email validation helpers with optional external dependency."""
from __future__ import annotations

import re
from types import SimpleNamespace

try:  # pragma: no cover - exercised when dependency is installed
    from email_validator import EmailNotValidError as _EmailNotValidError
    from email_validator import validate_email as _validate_email
except ImportError:  # pragma: no cover - fallback behaviour
    class _EmailNotValidError(ValueError):
        """Fallback error raised when email validation fails."""

    _EMAIL_REGEX = re.compile(
        r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
        r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
        r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$"
    )

    def _validate_email(address: str, allow_smtputf8: bool = False):
        if not isinstance(address, str) or not _EMAIL_REGEX.fullmatch(address):
            raise _EmailNotValidError("Invalid email address")
        return SimpleNamespace(email=address)

EmailNotValidError = _EmailNotValidError


def validate_email(address: str, *, allow_smtputf8: bool = False):
    """Validate an email address using the best available implementation."""

    return _validate_email(address, allow_smtputf8=allow_smtputf8)
