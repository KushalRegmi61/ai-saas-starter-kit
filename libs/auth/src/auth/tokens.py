"""Assistant JWT mint/verify. Pure functions of explicit params — the lib
owns no secrets; the consuming service passes its configured secret/TTL."""

import time

from jose import JWTError, jwt

from auth.types import ASSISTANT_ROLES, AssistantClaims

ASSISTANT_TOKEN_ISSUER = "assistant-auth"
ASSISTANT_TOKEN_ALGORITHM = "HS256"
DEFAULT_TOKEN_TTL_SECONDS = 12 * 3600
DEFAULT_WS_TICKET_TTL_SECONDS = 60
_WS_TICKET_TYPE = "assistant-ws-ticket"


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


def mint_assistant_ws_ticket(
    *,
    user_id: str,
    role: str,
    secret: str,
    ttl_seconds: int = DEFAULT_WS_TICKET_TTL_SECONDS,
    roles: tuple[str, ...] = ASSISTANT_ROLES,
) -> str:
    """Mint a short-lived token intended only for a WebSocket handshake."""
    if role not in roles:
        raise InvalidToken(f"unknown role: {role}")
    now = int(time.time())
    return jwt.encode(
        {
            "sub": user_id,
            "role": role,
            "typ": _WS_TICKET_TYPE,
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
    return _decode_token(token, secret=secret, roles=roles, expected_type=None)


def decode_assistant_ws_ticket(
    token: str, *, secret: str, roles: tuple[str, ...] = ASSISTANT_ROLES
) -> AssistantClaims:
    """Decode only the dedicated short-lived WebSocket token type."""
    return _decode_token(token, secret=secret, roles=roles, expected_type=_WS_TICKET_TYPE)


def _decode_token(
    token: str,
    *,
    secret: str,
    roles: tuple[str, ...],
    expected_type: str | None,
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
    token_type = payload.get("typ")
    if expected_type is None and token_type is not None:
        raise InvalidToken("invalid token type")
    if expected_type is not None and token_type != expected_type:
        raise InvalidToken("invalid token type")
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
