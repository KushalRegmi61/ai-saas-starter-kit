"""Login and admin user-management routes for the assistant identity store."""

from __future__ import annotations

import logging
from typing import Literal

from auth.tokens import mint_assistant_token, mint_assistant_ws_ticket
from auth.types import AssistantClaims, AssistantUser, CreateUserRequest, LoginRequest
from fastapi import APIRouter, Depends, HTTPException, Request, status
from psycopg.errors import UniqueViolation
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel, Field

from agent.authz import require_jwt_admin, require_jwt_user
from agent.config import get_agent_settings
from models import users

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth")


class LoginResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    user: AssistantUser


class WebSocketTicketResponse(BaseModel):
    access_token: str
    token_type: Literal["ws-ticket"] = "ws-ticket"
    expires_in: int


class RoleUpdateRequest(BaseModel):
    role: str = Field(pattern="^(employee|lead|manager|admin)$")


def get_user_pool(request: Request) -> AsyncConnectionPool:
    pool = getattr(request.app.state, "assistant_user_pool", None)
    if pool is None:
        logger.warning("auth: user pool unavailable")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Assistant authentication is not configured",
        )
    return pool


def _require_jwt_secret() -> str:
    secret = get_agent_settings().assistant_jwt_secret
    if not secret:
        logger.warning("auth: JWT secret unconfigured")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Assistant authentication is not configured",
        )
    return secret


def _invalid_login() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid email or password",
        headers={"WWW-Authenticate": "Bearer"},
    )


@router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest, pool: AsyncConnectionPool = Depends(get_user_pool)) -> LoginResponse:
    logger.info("auth: login attempt email=%s", payload.email.strip().lower())
    secret = _require_jwt_secret()
    async with pool.connection() as connection:
        user = await users.authenticate_async(connection, payload.email, payload.password)
        await connection.commit()
    if user is None:
        logger.warning("auth: login failed email=%s", payload.email.strip().lower())
        raise _invalid_login()
    logger.info("auth: login success role=%s", user["role"])

    settings = get_agent_settings()
    token = mint_assistant_token(
        user_id=user["id"],
        role=user["role"],
        secret=secret,
        ttl_seconds=settings.agentic_assistant_jwt_ttl_seconds,
    )
    return LoginResponse(
        access_token=token,
        expires_in=settings.agentic_assistant_jwt_ttl_seconds,
        user=user,
    )


@router.post("/ws-ticket", response_model=WebSocketTicketResponse)
async def websocket_ticket(
    _pool: AsyncConnectionPool = Depends(get_user_pool),
    claims: AssistantClaims = Depends(require_jwt_user),
) -> WebSocketTicketResponse:
    logger.info("auth: ws-ticket mint subject=%s", claims.subject)
    secret = _require_jwt_secret()
    settings = get_agent_settings()
    return WebSocketTicketResponse(
        access_token=mint_assistant_ws_ticket(
            user_id=claims.subject,
            role=claims.role,
            secret=secret,
            ttl_seconds=settings.ws_ticket_ttl_seconds,
        ),
        expires_in=settings.ws_ticket_ttl_seconds,
    )


@router.post("/users", response_model=AssistantUser, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: CreateUserRequest,
    pool: AsyncConnectionPool = Depends(get_user_pool),
    claims: AssistantClaims = Depends(require_jwt_admin),
) -> AssistantUser:
    logger.info("auth: create user email=%s role=%s", payload.email.strip().lower(), payload.role)
    try:
        async with pool.connection() as connection:
            result = await users.create_user_async(
                connection,
                email=payload.email,
                password=payload.password,
                role=payload.role,
                actor_id=claims.subject,
            )
            await connection.commit()
            return result
    except UniqueViolation:
        logger.warning("auth: create user conflict email=%s", payload.email.strip().lower())
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email already exists"
        ) from None
    except ValueError as exc:
        logger.warning("auth: create user invalid: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from None


@router.get("/users", response_model=list[AssistantUser])
async def list_users(
    pool: AsyncConnectionPool = Depends(get_user_pool),
    _claims: AssistantClaims = Depends(require_jwt_admin),
) -> list[AssistantUser]:
    logger.info("auth: list users")
    async with pool.connection() as connection:
        result = await users.list_users_async(connection)
    logger.info("auth: list users done count=%d", len(result))
    return result


@router.patch("/users/{user_id}/role", response_model=AssistantUser)
async def update_role(
    user_id: str,
    payload: RoleUpdateRequest,
    pool: AsyncConnectionPool = Depends(get_user_pool),
    claims: AssistantClaims = Depends(require_jwt_admin),
) -> AssistantUser:
    logger.info("auth: role change user_id=%s role=%s", user_id, payload.role)
    if claims.subject == user_id:
        logger.warning("auth: admin self-role change blocked user_id=%s", user_id)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="An admin cannot change their own role",
        )
    async with pool.connection() as connection:
        user = await users.set_role_async(
            connection,
            user_id=user_id,
            role=payload.role,
            actor_id=claims.subject,
        )
        await connection.commit()
    if user is None:
        logger.warning("auth: role change user not found user_id=%s", user_id)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    logger.info("auth: role change done user_id=%s", user_id)
    return user
