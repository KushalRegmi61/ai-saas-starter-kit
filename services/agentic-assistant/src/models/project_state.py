"""Normalized project-state persistence used by the MCP tools."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from models.project_state_schema import ensure_project_state_tables_async
from models.projects import Project

__all__ = ["ensure_project_state_tables_async"]


class FeatureStatus(StrEnum):
    DEV = "DEV"
    QA = "QA"
    UAT = "UAT"
    PROD = "PROD"
    BUG = "BUG"
    BLOCKED = "BLOCKED"


class BlockerStatus(StrEnum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class BlockerSeverity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ProjectFeature(BaseModel):
    id: str
    project_id: str
    name: str
    description: str | None = None
    status: FeatureStatus
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ProjectBlocker(BaseModel):
    id: str
    project_id: str
    title: str
    description: str | None = None
    severity: BlockerSeverity
    status: BlockerStatus
    created_at: datetime | None = None
    resolved_at: datetime | None = None


class DailyProjectUpdate(BaseModel):
    id: str
    project_id: str
    submitted_by: str
    summary: str
    completion_percentage: int = Field(ge=0, le=100)
    blocker_ids: list[str] = Field(default_factory=list)
    created_at: datetime | None = None


class FeatureStatusHistory(BaseModel):
    id: int
    feature_id: str
    feature_name: str
    old_status: FeatureStatus
    new_status: FeatureStatus
    changed_by: str
    changed_at: datetime | None = None


class ProjectContext(BaseModel):
    project: Project
    feature_counts: dict[str, int]
    features_by_status: dict[str, list[str]] = Field(default_factory=dict)
    open_blockers: list[ProjectBlocker]
    latest_update: DailyProjectUpdate | None = None
    scope: dict[str, str]


_FEATURE_COLUMNS = "id, project_id, name, description, status, created_at, updated_at"
_BLOCKER_COLUMNS = "id, project_id, title, description, severity, status, created_at, resolved_at"
_UPDATE_COLUMNS = (
    "id, project_id, submitted_by, summary, completion_percentage, blocker_ids, created_at"
)
_HISTORY_COLUMNS = (
    "h.id, h.feature_id, f.name, h.old_status, h.new_status, "
    "h.changed_by, h.changed_at"
)


def _feature(row: tuple[Any, ...]) -> ProjectFeature:
    return ProjectFeature(
        id=row[0],
        project_id=row[1],
        name=row[2],
        description=row[3],
        status=FeatureStatus(row[4]),
        created_at=row[5],
        updated_at=row[6],
    )


def _blocker(row: tuple[Any, ...]) -> ProjectBlocker:
    return ProjectBlocker(
        id=row[0],
        project_id=row[1],
        title=row[2],
        description=row[3],
        severity=BlockerSeverity(row[4]),
        status=BlockerStatus(row[5]),
        created_at=row[6],
        resolved_at=row[7],
    )


def _update(row: tuple[Any, ...]) -> DailyProjectUpdate:
    blocker_ids = row[5] or []
    if isinstance(blocker_ids, str):
        blocker_ids = json.loads(blocker_ids)
    return DailyProjectUpdate(
        id=row[0],
        project_id=row[1],
        submitted_by=row[2],
        summary=row[3],
        completion_percentage=row[4],
        blocker_ids=list(blocker_ids),
        created_at=row[6],
    )


async def list_project_features_async(connection: Any, *, project_id: str) -> list[ProjectFeature]:
    cursor = await connection.execute(
        f"SELECT {_FEATURE_COLUMNS} FROM assistant_project_features "
        "WHERE project_id = %s ORDER BY created_at ASC",
        (project_id,),
    )
    return [_feature(row) for row in await cursor.fetchall()]


async def list_open_project_blockers_async(
    connection: Any, *, project_id: str
) -> list[ProjectBlocker]:
    cursor = await connection.execute(
        f"SELECT {_BLOCKER_COLUMNS} FROM assistant_project_blockers "
        "WHERE project_id = %s AND status = 'OPEN' ORDER BY created_at DESC",
        (project_id,),
    )
    return [_blocker(row) for row in await cursor.fetchall()]


async def get_latest_project_update_async(
    connection: Any, *, project_id: str
) -> DailyProjectUpdate | None:
    cursor = await connection.execute(
        f"SELECT {_UPDATE_COLUMNS} FROM assistant_daily_project_updates "
        "WHERE project_id = %s ORDER BY created_at DESC LIMIT 1",
        (project_id,),
    )
    row = await cursor.fetchone()
    return _update(row) if row is not None else None


async def list_project_updates_async(
    connection: Any, *, project_id: str, since: datetime | None = None, limit: int = 50
) -> list[DailyProjectUpdate]:
    bounded_limit = max(1, min(limit, 100))
    since_clause = " AND created_at >= %s" if since is not None else ""
    params: tuple[Any, ...] = (project_id, since) if since is not None else (project_id,)
    cursor = await connection.execute(
        f"SELECT {_UPDATE_COLUMNS} FROM assistant_daily_project_updates "
        f"WHERE project_id = %s{since_clause} ORDER BY created_at DESC LIMIT %s",
        (*params, bounded_limit),
    )
    return [_update(row) for row in await cursor.fetchall()]


async def list_project_feature_history_async(
    connection: Any, *, project_id: str, limit: int = 100
) -> list[FeatureStatusHistory]:
    bounded_limit = max(1, min(limit, 200))
    cursor = await connection.execute(
        f"SELECT {_HISTORY_COLUMNS} FROM assistant_feature_status_history AS h "
        "JOIN assistant_project_features AS f ON f.id = h.feature_id "
        "WHERE f.project_id = %s ORDER BY h.changed_at DESC LIMIT %s",
        (project_id, bounded_limit),
    )
    return [
        FeatureStatusHistory(
            id=row[0],
            feature_id=row[1],
            feature_name=row[2],
            old_status=FeatureStatus(row[3]),
            new_status=FeatureStatus(row[4]),
            changed_by=row[5],
            changed_at=row[6],
        )
        for row in await cursor.fetchall()
    ]


async def get_project_features_by_ids_async(
    connection: Any, *, project_id: str, feature_ids: list[str]
) -> list[ProjectFeature]:
    if not feature_ids:
        return []
    placeholders = ", ".join(["%s"] * len(feature_ids))
    cursor = await connection.execute(
        f"SELECT {_FEATURE_COLUMNS} FROM assistant_project_features "
        f"WHERE project_id = %s AND id IN ({placeholders})",
        (project_id, *feature_ids),
    )
    return [_feature(row) for row in await cursor.fetchall()]


async def get_project_blockers_by_ids_async(
    connection: Any, *, project_id: str, blocker_ids: list[str]
) -> list[ProjectBlocker]:
    if not blocker_ids:
        return []
    placeholders = ", ".join(["%s"] * len(blocker_ids))
    cursor = await connection.execute(
        f"SELECT {_BLOCKER_COLUMNS} FROM assistant_project_blockers "
        f"WHERE project_id = %s AND id IN ({placeholders})",
        (project_id, *blocker_ids),
    )
    return [_blocker(row) for row in await cursor.fetchall()]


async def update_feature_status_async(
    connection: Any, *, project_id: str, feature_id: str, new_status: FeatureStatus, changed_by: str
) -> tuple[ProjectFeature, FeatureStatus]:
    cursor = await connection.execute(
        f"SELECT {_FEATURE_COLUMNS} FROM assistant_project_features "
        "WHERE project_id = %s AND id = %s FOR UPDATE",
        (project_id, feature_id),
    )
    row = await cursor.fetchone()
    if row is None:
        raise KeyError("feature not found")
    current = _feature(row)
    new_status = FeatureStatus(new_status)
    if current.status == new_status:
        return current, current.status
    updated = await connection.execute(
        f"UPDATE assistant_project_features SET status = %s, updated_at = now() "
        f"WHERE project_id = %s AND id = %s RETURNING {_FEATURE_COLUMNS}",
        (new_status.value, project_id, feature_id),
    )
    updated_row = await updated.fetchone()
    if updated_row is None:
        raise KeyError("feature not found")
    await connection.execute(
        "INSERT INTO assistant_feature_status_history "
        "(feature_id, old_status, new_status, changed_by) VALUES (%s, %s, %s, %s)",
        (feature_id, current.status.value, new_status.value, changed_by),
    )
    return _feature(updated_row), current.status


async def create_daily_project_update_async(
    connection: Any,
    *,
    project_id: str,
    submitted_by: str,
    summary: str,
    completion_percentage: int,
    blocker_ids: list[str],
) -> DailyProjectUpdate:
    cursor = await connection.execute(
        f"INSERT INTO assistant_daily_project_updates "
        "(id, project_id, submitted_by, summary, completion_percentage, blocker_ids) "
        f"VALUES (%s, %s, %s, %s, %s, %s) RETURNING {_UPDATE_COLUMNS}",
        (
            str(uuid.uuid4()),
            project_id,
            submitted_by,
            summary,
            completion_percentage,
            json.dumps(blocker_ids),
        ),
    )
    row = await cursor.fetchone()
    if row is None:
        raise RuntimeError("daily update insert returned no row")
    return _update(row)
