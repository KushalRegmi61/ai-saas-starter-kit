"""Password hashing. Boring bcrypt wrapper with explicit limits."""

import bcrypt

# bcrypt silently truncates past 72 bytes; reject instead of weakening.
_MAX_PASSWORD_BYTES = 72


def hash_password(password: str) -> str:
    raw = password.encode("utf-8")
    if not raw:
        raise ValueError("password must not be empty")
    if len(raw) > _MAX_PASSWORD_BYTES:
        raise ValueError("password must be at most 72 bytes")
    return bcrypt.hashpw(raw, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False
