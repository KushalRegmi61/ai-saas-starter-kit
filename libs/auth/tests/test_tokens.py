"""Token mint/verify contract: round-trip, expiry, fail-closed decode."""

from jose import jwt

from auth.tokens import (
    ASSISTANT_TOKEN_ISSUER,
    DEFAULT_TOKEN_TTL_SECONDS,
    DEFAULT_WS_TICKET_TTL_SECONDS,
    InvalidToken,
    decode_assistant_token,
    decode_assistant_ws_ticket,
    mint_assistant_token,
    mint_assistant_ws_ticket,
)

SECRET = "test-secret-for-assistant-tokens"


def test_round_trip_preserves_identity():
    token = mint_assistant_token(user_id="u-1", role="manager", secret=SECRET, ttl_seconds=600)
    claims = decode_assistant_token(token, secret=SECRET)
    assert claims.subject == "u-1"
    assert claims.role == "manager"
    assert claims.expires_at - claims.issued_at == 600


def test_default_ttl_is_twelve_hours():
    assert DEFAULT_TOKEN_TTL_SECONDS == 12 * 3600
    claims = decode_assistant_token(
        mint_assistant_token(user_id="u-1", role="employee", secret=SECRET),
        secret=SECRET,
    )
    assert claims.expires_at - claims.issued_at == DEFAULT_TOKEN_TTL_SECONDS


def test_wrong_secret_rejected():
    token = mint_assistant_token(user_id="u-1", role="lead", secret=SECRET)
    try:
        decode_assistant_token(token, secret="other-secret")
    except InvalidToken:
        return
    raise AssertionError("expected InvalidToken")


def test_tampered_token_rejected():
    token = mint_assistant_token(user_id="u-1", role="lead", secret=SECRET)
    try:
        decode_assistant_token(token + "tamper", secret=SECRET)
    except InvalidToken:
        return
    raise AssertionError("expected InvalidToken")


def test_expired_token_rejected():
    token = mint_assistant_token(user_id="u-1", role="employee", secret=SECRET, ttl_seconds=-1)
    try:
        decode_assistant_token(token, secret=SECRET)
    except InvalidToken:
        return
    raise AssertionError("expected InvalidToken")


def test_unknown_role_rejected_even_if_signed():
    token = jwt.encode(
        {"sub": "u-1", "role": "superuser", "iss": ASSISTANT_TOKEN_ISSUER},
        SECRET,
        algorithm="HS256",
    )
    try:
        decode_assistant_token(token, secret=SECRET)
    except InvalidToken:
        return
    raise AssertionError("expected InvalidToken")


def test_missing_role_rejected():
    token = jwt.encode({"sub": "u-1", "iss": ASSISTANT_TOKEN_ISSUER}, SECRET, algorithm="HS256")
    try:
        decode_assistant_token(token, secret=SECRET)
    except InvalidToken:
        return
    raise AssertionError("expected InvalidToken")


def test_websocket_ticket_round_trip_and_ttl():
    token = mint_assistant_ws_ticket(user_id="u-1", role="manager", secret=SECRET, ttl_seconds=30)
    claims = decode_assistant_ws_ticket(token, secret=SECRET)
    assert (claims.subject, claims.role) == ("u-1", "manager")
    assert claims.expires_at - claims.issued_at == 30
    assert DEFAULT_WS_TICKET_TTL_SECONDS == 60


def test_websocket_ticket_cannot_authorize_normal_routes():
    token = mint_assistant_ws_ticket(user_id="u-1", role="employee", secret=SECRET)
    try:
        decode_assistant_token(token, secret=SECRET)
    except InvalidToken:
        return
    raise AssertionError("WebSocket tickets must not decode as assistant access tokens")


def test_normal_token_cannot_authorize_websocket():
    token = mint_assistant_token(user_id="u-1", role="employee", secret=SECRET)
    try:
        decode_assistant_ws_ticket(token, secret=SECRET)
    except InvalidToken:
        return
    raise AssertionError("normal assistant tokens must not decode as WebSocket tickets")
