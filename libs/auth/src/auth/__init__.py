"""Shared assistant identity: roles, password hashing, tokens, user store."""

from auth.crypto import hash_password, verify_password
from auth.mapping import (
    DEFAULT_ROLE_POLICY,
    ROLE_LEVELS,
    UnknownRole,
    role_to_filter,
)
from auth.store import (
    ensure_assistant_tables,
    find_user_by_email,
    find_user_by_id,
    insert_user,
    list_users,
    record_audit_event,
    set_user_role,
)
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
from auth.types import (
    ASSISTANT_ROLES,
    AssistantClaims,
    AssistantUser,
    CreateUserRequest,
    FilterSpec,
    LoginRequest,
    RoleDefinition,
    RolePolicy,
)

__all__ = [
    "ASSISTANT_ROLES",
    "ASSISTANT_TOKEN_ISSUER",
    "DEFAULT_ROLE_POLICY",
    "DEFAULT_TOKEN_TTL_SECONDS",
    "DEFAULT_WS_TICKET_TTL_SECONDS",
    "ROLE_LEVELS",
    "AssistantClaims",
    "AssistantUser",
    "CreateUserRequest",
    "FilterSpec",
    "InvalidToken",
    "LoginRequest",
    "RoleDefinition",
    "RolePolicy",
    "UnknownRole",
    "decode_assistant_token",
    "decode_assistant_ws_ticket",
    "ensure_assistant_tables",
    "find_user_by_email",
    "find_user_by_id",
    "hash_password",
    "insert_user",
    "list_users",
    "mint_assistant_token",
    "mint_assistant_ws_ticket",
    "record_audit_event",
    "role_to_filter",
    "set_user_role",
    "verify_password",
]
