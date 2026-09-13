"""Persistence contracts for project-scoped coding-agent credentials."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class ProjectTokenError(RuntimeError):
    """Base error for project credential persistence operations."""


class ProjectTokenNotFound(ProjectTokenError):
    """Raised when a token does not exist for a project."""


class ProjectToken(BaseModel):
    """Public token metadata; secret material never belongs in this shape."""

    id: str
    project_id: str
    created_by: str
    label: str
    expires_at: datetime
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None
    created_at: datetime | None = None


class ProjectMcpContext(BaseModel):
    """Immutable scope passed to future MCP request/tool handlers."""

    model_config = ConfigDict(frozen=True)

    token_id: str
    project_id: str
    project_name: str
    lead_id: str
    token_label: str


_TOKEN_COLUMNS = (
    "id, project_id, created_by, label, expires_at, last_used_at, revoked_at, created_at"
)


def _token_from_row(row: tuple[Any, ...]) -> ProjectToken:
    return ProjectToken(
        id=row[0],
        project_id=row[1],
        created_by=row[2],
        label=row[3],
        expires_at=row[4],
        last_used_at=row[5],
        revoked_at=row[6],
        created_at=row[7],
    )


async def ensure_project_token_tables_async(connection: Any) -> None:
    """Create project-token storage idempotently for the POC startup path."""

    await connection.execute(
        """
        CREATE TABLE IF NOT EXISTS assistant_project_mcp_tokens (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL
                REFERENCES assistant_projects(id) ON DELETE CASCADE,
            token_hash TEXT NOT NULL UNIQUE,
            created_by TEXT NOT NULL REFERENCES assistant_users(id),
            label TEXT NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            last_used_at TIMESTAMPTZ,
            revoked_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    await connection.execute(
        """
        CREATE INDEX IF NOT EXISTS assistant_project_mcp_tokens_hash_idx
        ON assistant_project_mcp_tokens (token_hash)
        """
    )
    await connection.execute(
        """
        CREATE INDEX IF NOT EXISTS assistant_project_mcp_tokens_active_project_idx
        ON assistant_project_mcp_tokens (project_id)
        WHERE revoked_at IS NULL
        """
    )
    await connection.execute(
        """
        CREATE INDEX IF NOT EXISTS assistant_project_mcp_tokens_active_expiry_idx
        ON assistant_project_mcp_tokens (expires_at)
        WHERE revoked_at IS NULL
        """
    )


async def create_project_token_async(
    connection: Any,
    *,
    token_id: str,
    project_id: str,
    token_hash: str,
    created_by: str,
    label: str,
    expires_at: datetime,
) -> ProjectToken:
    cursor = await connection.execute(
        f"""
        INSERT INTO assistant_project_mcp_tokens
            (id, project_id, token_hash, created_by, label, expires_at)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING {_TOKEN_COLUMNS}
        """,
        (token_id, project_id, token_hash, created_by, label, expires_at),
    )
    row = await cursor.fetchone()
    if row is None:
        raise ProjectTokenError("token insert returned no row")
    return _token_from_row(row)


async def find_active_project_token_async(
    connection: Any, *, token_hash: str
) -> tuple[ProjectToken, str, str | None] | None:
    """Find a non-revoked, non-expired token and its project ownership."""

    cursor = await connection.execute(
        f"""
        SELECT t.{_TOKEN_COLUMNS.replace(", ", ", t.")}, p.name, p.lead_id
        FROM assistant_project_mcp_tokens AS t
        JOIN assistant_projects AS p ON p.id = t.project_id
        WHERE t.token_hash = %s
          AND t.revoked_at IS NULL
          AND t.expires_at > now()
        """,
        (token_hash,),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    return _token_from_row(row[:8]), row[8], row[9]


async def list_project_tokens_async(connection: Any, *, project_id: str) -> list[ProjectToken]:
    cursor = await connection.execute(
        f"""
        SELECT {_TOKEN_COLUMNS}
        FROM assistant_project_mcp_tokens
        WHERE project_id = %s
        ORDER BY created_at DESC
        """,
        (project_id,),
    )
    return [_token_from_row(row) for row in await cursor.fetchall()]


async def revoke_project_token_async(
    connection: Any, *, project_id: str, token_id: str
) -> ProjectToken | None:
    cursor = await connection.execute(
        f"""
        UPDATE assistant_project_mcp_tokens
        SET revoked_at = COALESCE(revoked_at, now())
        WHERE project_id = %s AND id = %s
        RETURNING {_TOKEN_COLUMNS}
        """,
        (project_id, token_id),
    )
    row = await cursor.fetchone()
    return _token_from_row(row) if row is not None else None


async def revoke_project_tokens_for_project_async(
    connection: Any, *, project_id: str
) -> list[ProjectToken]:
    cursor = await connection.execute(
        f"""
        UPDATE assistant_project_mcp_tokens
        SET revoked_at = COALESCE(revoked_at, now())
        WHERE project_id = %s AND revoked_at IS NULL
        RETURNING {_TOKEN_COLUMNS}
        """,
        (project_id,),
    )
    return [_token_from_row(row) for row in await cursor.fetchall()]


async def revoke_project_tokens_for_creator_async(
    connection: Any, *, creator_id: str
) -> list[ProjectToken]:
    cursor = await connection.execute(
        f"""
        UPDATE assistant_project_mcp_tokens
        SET revoked_at = COALESCE(revoked_at, now())
        WHERE created_by = %s AND revoked_at IS NULL
        RETURNING {_TOKEN_COLUMNS}
        """,
        (creator_id,),
    )
    return [_token_from_row(row) for row in await cursor.fetchall()]


async def touch_project_token_last_used_async(connection: Any, *, token_id: str) -> None:
    await connection.execute(
        "UPDATE assistant_project_mcp_tokens SET last_used_at = now() WHERE id = %s",
        (token_id,),
    )
