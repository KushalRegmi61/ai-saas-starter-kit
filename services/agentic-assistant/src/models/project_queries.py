"""Bounded project reads used by the manager-facing agent tools."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from models import project_state
from models.project_state_ops import normalize_reference


async def list_features_async(
    connection: Any,
    *,
    project_id: str,
    query: str | None,
    statuses: list[str] | None,
    limit: int,
) -> list[project_state.ProjectFeature]:
    status_clause = ""
    params: list[Any] = [project_id]
    if statuses:
        status_clause = " AND status = ANY(%s)"
        params.append(statuses)
    cursor = await connection.execute(
        "SELECT id, project_id, name, description, status, created_at, updated_at "
        "FROM assistant_project_features WHERE project_id = %s"
        f"{status_clause} ORDER BY updated_at DESC NULLS LAST, name ASC LIMIT %s",
        (*params, limit),
    )
    rows = await cursor.fetchall()
    if query is None:
        return [project_state._feature(row) for row in rows]
    normalized = normalize_reference(query)
    return [
        project_state._feature(row)
        for row in rows
        if normalized in normalize_reference(row[2])
        or normalized in normalize_reference(row[3] or "")
    ]


async def feature_counts_async(connection: Any, *, project_id: str) -> dict[str, int]:
    cursor = await connection.execute(
        "SELECT status, COUNT(*) FROM assistant_project_features "
        "WHERE project_id = %s GROUP BY status",
        (project_id,),
    )
    return {str(row[0]): int(row[1]) for row in await cursor.fetchall()}


async def open_blocker_count_async(connection: Any, *, project_id: str) -> int:
    cursor = await connection.execute(
        "SELECT COUNT(*) FROM assistant_project_blockers "
        "WHERE project_id = %s AND status = 'OPEN'",
        (project_id,),
    )
    row = await cursor.fetchone()
    return int(row[0]) if row is not None else 0


async def list_blockers_async(
    connection: Any,
    *,
    project_id: str,
    query: str | None,
    statuses: list[str],
    severities: list[str] | None,
    limit: int,
) -> list[project_state.ProjectBlocker]:
    status_clause = " AND status = ANY(%s)"
    params: list[Any] = [project_id, statuses]
    severity_clause = ""
    if severities:
        severity_clause = " AND severity = ANY(%s)"
        params.append(severities)
    cursor = await connection.execute(
        "SELECT id, project_id, title, description, severity, status, created_at, resolved_at "
        "FROM assistant_project_blockers WHERE project_id = %s"
        f"{status_clause}{severity_clause} ORDER BY created_at DESC LIMIT %s",
        (*params, limit),
    )
    rows = await cursor.fetchall()
    if query is None:
        return [project_state._blocker(row) for row in rows]
    normalized = normalize_reference(query)
    return [
        project_state._blocker(row)
        for row in rows
        if normalized in normalize_reference(row[2])
        or normalized in normalize_reference(row[3] or "")
    ]


async def list_history_async(
    connection: Any, *, project_id: str, since: datetime | None, limit: int
) -> list[project_state.FeatureStatusHistory]:
    since_clause = " AND h.changed_at >= %s" if since is not None else ""
    params: tuple[Any, ...] = (project_id, since) if since is not None else (project_id,)
    cursor = await connection.execute(
        "SELECT h.id, h.feature_id, f.name, h.old_status, h.new_status, "
        "h.changed_by, h.changed_at FROM assistant_feature_status_history AS h "
        "JOIN assistant_project_features AS f ON f.id = h.feature_id "
        f"WHERE f.project_id = %s{since_clause} ORDER BY h.changed_at DESC LIMIT %s",
        (*params, limit),
    )
    return [
        project_state.FeatureStatusHistory(
            id=row[0],
            feature_id=row[1],
            feature_name=row[2],
            old_status=project_state.FeatureStatus(row[3]),
            new_status=project_state.FeatureStatus(row[4]),
            changed_by=row[5],
            changed_at=row[6],
        )
        for row in await cursor.fetchall()
    ]
