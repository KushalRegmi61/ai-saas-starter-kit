"""Project persistence primitives for the project-scoped MCP foundation."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ProjectStatus(StrEnum):
    ON_TRACK = "ON_TRACK"
    AT_RISK = "AT_RISK"
    BLOCKED = "BLOCKED"
    COMPLETED = "COMPLETED"


class Project(BaseModel):
    """Public project shape; no credentials or internal user fields escape."""

    id: str
    name: str
    description: str | None = None
    lead_id: str | None = None
    status: ProjectStatus = ProjectStatus.ON_TRACK
    completion_percentage: int = Field(default=0, ge=0, le=100)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2_000)
    status: ProjectStatus = ProjectStatus.ON_TRACK


class ProjectError(RuntimeError):
    """Base error for project persistence operations."""


class ProjectNotFound(ProjectError):
    """Raised when a project ID does not exist."""


class LeadNotFound(ProjectError):
    """Raised when the requested lead user does not exist."""


class InvalidLeadAssignment(ProjectError):
    """Raised when a non-lead user is assigned to a project."""


class AssignmentConflict(ProjectError):
    """Raised when assignment would silently replace another lead."""


_PROJECT_COLUMNS = (
    "id, name, description, lead_id, status, created_at, updated_at, completion_percentage"
)
_UNSET = object()


def _project_from_row(row: tuple[Any, ...]) -> Project:
    return Project(
        id=row[0],
        name=row[1],
        description=row[2],
        lead_id=row[3],
        status=ProjectStatus(row[4]),
        created_at=row[5],
        updated_at=row[6],
        completion_percentage=row[7] if len(row) > 7 and row[7] is not None else 0,
    )


def _normalized_name(name: str) -> str:
    normalized = name.strip()
    if not normalized:
        raise ValueError("project name must not be empty")
    return normalized


def _normalized_description(description: str | None) -> str | None:
    if description is None:
        return None
    normalized = description.strip()
    return normalized or None


async def ensure_project_tables_async(connection: Any) -> None:
    """Create the POC project table and lead lookup index idempotently."""

    await connection.execute(
        """
        CREATE TABLE IF NOT EXISTS assistant_projects (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            lead_id TEXT REFERENCES assistant_users(id) ON DELETE RESTRICT,
            status TEXT NOT NULL DEFAULT 'ON_TRACK'
                CHECK (status IN ('ON_TRACK', 'AT_RISK', 'BLOCKED', 'COMPLETED')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            completion_percentage INTEGER NOT NULL DEFAULT 0
                CHECK (completion_percentage BETWEEN 0 AND 100)
        )
        """
    )
    await connection.execute(
        "ALTER TABLE assistant_projects ADD COLUMN IF NOT EXISTS "
        "completion_percentage INTEGER NOT NULL DEFAULT 0"
    )
    await connection.execute(
        """
        DO $$ BEGIN
            ALTER TABLE assistant_projects
            ADD CONSTRAINT assistant_projects_completion_percentage_check
            CHECK (completion_percentage BETWEEN 0 AND 100);
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
        """
    )
    await connection.execute(
        "CREATE INDEX IF NOT EXISTS assistant_projects_lead_idx ON assistant_projects (lead_id)"
    )


async def create_project_async(
    connection: Any,
    *,
    name: str,
    description: str | None = None,
    status: ProjectStatus = ProjectStatus.ON_TRACK,
) -> Project:
    """Insert a project without committing the caller's transaction."""

    cursor = await connection.execute(
        f"""
        INSERT INTO assistant_projects (id, name, description, status)
        VALUES (%s, %s, %s, %s)
        RETURNING {_PROJECT_COLUMNS}
        """,
        (
            str(uuid.uuid4()),
            _normalized_name(name),
            _normalized_description(description),
            ProjectStatus(status).value,
        ),
    )
    row = await cursor.fetchone()
    if row is None:
        raise ProjectError("project insert returned no row")
    return _project_from_row(row)


async def get_project_async(connection: Any, project_id: str) -> Project | None:
    cursor = await connection.execute(
        f"SELECT {_PROJECT_COLUMNS} FROM assistant_projects WHERE id = %s",
        (project_id,),
    )
    row = await cursor.fetchone()
    return _project_from_row(row) if row is not None else None


async def list_projects_async(connection: Any) -> list[Project]:
    cursor = await connection.execute(
        f"SELECT {_PROJECT_COLUMNS} FROM assistant_projects ORDER BY created_at DESC"
    )
    return [_project_from_row(row) for row in await cursor.fetchall()]

async def update_project_async(
    connection: Any,
    project_id: str,
    *,
    name: str | object | None = _UNSET,
    description: str | object | None = _UNSET,
    status: ProjectStatus | str | object = _UNSET,
) -> Project | None:
    """Update supplied fields only; the caller owns the transaction."""

    assignments: list[str] = []
    params: list[Any] = []
    if name is not _UNSET:
        assignments.append("name = %s")
        params.append(_normalized_name(name))
    if description is not _UNSET:
        assignments.append("description = %s")
        params.append(_normalized_description(description))
    if status is not _UNSET:
        assignments.append("status = %s")
        params.append(ProjectStatus(status).value)
    if not assignments:
        return await get_project_async(connection, project_id)

    assignments.append("updated_at = now()")
    params.append(project_id)
    cursor = await connection.execute(
        f"""
        UPDATE assistant_projects
        SET {", ".join(assignments)}
        WHERE id = %s
        RETURNING {_PROJECT_COLUMNS}
        """,
        tuple(params),
    )
    row = await cursor.fetchone()
    return _project_from_row(row) if row is not None else None


async def assign_project_lead_async(connection: Any, *, project_id: str, lead_id: str) -> Project:
    """Assign a lead, allowing idempotent repeats but not silent replacement."""

    project = await get_project_async(connection, project_id)
    if project is None:
        raise ProjectNotFound(project_id)

    lead_cursor = await connection.execute(
        "SELECT id, role FROM assistant_users WHERE id = %s",
        (lead_id,),
    )
    lead_row = await lead_cursor.fetchone()
    if lead_row is None:
        raise LeadNotFound(lead_id)
    if lead_row[1] != "lead":
        raise InvalidLeadAssignment(lead_id)
    if project.lead_id is not None and project.lead_id != lead_id:
        raise AssignmentConflict(project_id)
    if project.lead_id == lead_id:
        return project

    cursor = await connection.execute(
        f"""
        UPDATE assistant_projects
        SET lead_id = %s, updated_at = now()
        WHERE id = %s
        RETURNING {_PROJECT_COLUMNS}
        """,
        (lead_id, project_id),
    )
    row = await cursor.fetchone()
    if row is None:
        raise ProjectNotFound(project_id)
    return _project_from_row(row)


async def replace_project_lead_async(
    connection: Any, *, project_id: str, lead_id: str | None
) -> Project:
    """Replace or remove a lead while locking the project row."""

    cursor = await connection.execute(
        f"""
        SELECT {_PROJECT_COLUMNS}
        FROM assistant_projects
        WHERE id = %s
        FOR UPDATE
        """,
        (project_id,),
    )
    current_row = await cursor.fetchone()
    if current_row is None:
        raise ProjectNotFound(project_id)

    if lead_id is not None:
        lead_cursor = await connection.execute(
            "SELECT id, role FROM assistant_users WHERE id = %s",
            (lead_id,),
        )
        lead_row = await lead_cursor.fetchone()
        if lead_row is None:
            raise LeadNotFound(lead_id)
        if lead_row[1] != "lead":
            raise InvalidLeadAssignment(lead_id)

    current = _project_from_row(current_row)
    if current.lead_id == lead_id:
        return current

    update_cursor = await connection.execute(
        f"""
        UPDATE assistant_projects
        SET lead_id = %s, updated_at = now()
        WHERE id = %s
        RETURNING {_PROJECT_COLUMNS}
        """,
        (lead_id, project_id),
    )
    updated_row = await update_cursor.fetchone()
    if updated_row is None:
        raise ProjectNotFound(project_id)
    return _project_from_row(updated_row)


async def list_projects_for_lead_async(connection: Any, lead_id: str) -> list[Project]:
    cursor = await connection.execute(
        f"""
        SELECT {_PROJECT_COLUMNS}
        FROM assistant_projects
        WHERE lead_id = %s
        ORDER BY created_at DESC
        """,
        (lead_id,),
    )
    return [_project_from_row(row) for row in await cursor.fetchall()]
