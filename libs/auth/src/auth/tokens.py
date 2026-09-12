"""Assistant JWT mint/verify. Pure functions of explicit params — the lib
owns no secrets; the consuming service passes its configured secret/TTL."""

import time

from jose import JWTError, jwt

from auth.types import ASSISTANT_ROLES, AssistantClaims

ASSISTANT_TOKEN_ISSUER = "assistant-auth"
ASSISTANT_TOKEN_ALGORITHM = "HS256"
DEFAULT_TOKEN_TTL_SECONDS = 12 * 3600


class InvalidToken(RuntimeError):
    """Raised when a token is malformed, expired, or carries an unknown role."""


def mint_assistant_token(
    *,
    user_id: str,
    role: str,
    secret: str,
    ttl_seconds: int = DEFAULT_TOKEN_TTL_SECONDS,
    roles: tuple[str, ...] = ASSISTANT_ROLES,
) -> str:
    if role not in roles:
        raise InvalidToken(f"unknown role: {role}")
    now = int(time.time())
    return jwt.encode(
        {
            "sub": user_id,
            "role": role,
            "iss": ASSISTANT_TOKEN_ISSUER,
            "iat": now,
            "exp": now + ttl_seconds,
        },
        secret,
        algorithm=ASSISTANT_TOKEN_ALGORITHM,
    )


def decode_assistant_token(
    token: str, *, secret: str, roles: tuple[str, ...] = ASSISTANT_ROLES
) -> AssistantClaims:
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=[ASSISTANT_TOKEN_ALGORITHM],
            issuer=ASSISTANT_TOKEN_ISSUER,
        )
    except JWTError as exc:
        raise InvalidToken(f"invalid token: {exc}") from None
    subject = payload.get("sub")
    role = payload.get("role")
    if not subject or role not in roles:
        raise InvalidToken("token missing required claims: sub, known role")
    return AssistantClaims(
        subject=subject,
        role=role,
        issued_at=int(payload.get("iat", 0)),
        expires_at=int(payload.get("exp", 0)),
    )
