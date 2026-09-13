"""Bounded project-state searches and mutations for the MCP service."""

from __future__ import annotations

import re
import unicodedata
import uuid
from typing import Any

from models import project_state


def normalize_reference(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).strip().casefold()
    return re.sub(r"[^\w]+", " ", value, flags=re.UNICODE).strip()


def _matches(reference: str, *values: str | None) -> bool:
    normalized = normalize_reference(reference)
    if not normalized:
        return False
    tokens = normalized.split()
    candidates = [normalize_reference(value or "") for value in values]
    return any(
        normalized in candidate or all(token in candidate for token in tokens)
        for candidate in candidates
    )


async def find_features_async(
    connection: Any, *, project_id: str, reference: str, limit: int = 5
) -> list[project_state.ProjectFeature]:
    bounded_limit = max(1, min(limit, 5))
    cursor = await connection.execute(
        "SELECT id, project_id, name, description, status, created_at, updated_at "
        "FROM assistant_project_features WHERE project_id = %s "
        "ORDER BY created_at ASC LIMIT %s",
        (project_id, 200),
    )
    rows = await cursor.fetchall()
    normalized = normalize_reference(reference)
    features = [
        project_state._feature(row)
        for row in rows
        if row[0] == reference or _matches(reference, row[2], row[3])
    ]
    return sorted(
        features,
        key=lambda item: (
            0 if normalize_reference(item.name) == normalized else 1,
            0 if normalized in normalize_reference(item.name) else 1,
        ),
    )[:bounded_limit]


async def find_blockers_async(
    connection: Any, *, project_id: str, reference: str, limit: int = 5
) -> list[project_state.ProjectBlocker]:
    bounded_limit = max(1, min(limit, 5))
    cursor = await connection.execute(
        "SELECT id, project_id, title, description, severity, status, created_at, resolved_at "
        "FROM assistant_project_blockers WHERE project_id = %s "
        "ORDER BY created_at DESC LIMIT %s",
        (project_id, 200),
    )
    rows = await cursor.fetchall()
    normalized = normalize_reference(reference)
    blockers = [
        project_state._blocker(row)
        for row in rows
        if row[0] == reference or _matches(reference, row[2], row[3])
    ]
    return sorted(
        blockers,
        key=lambda item: (
            0 if normalize_reference(item.title) == normalized else 1,
            0 if normalized in normalize_reference(item.title) else 1,
        ),
    )[:bounded_limit]


async def create_feature_async(
    connection: Any, *, project_id: str, name: str, description: str | None, status: str
) -> project_state.ProjectFeature:
    cursor = await connection.execute(
        "INSERT INTO assistant_project_features "
        "(id, project_id, name, description, status) VALUES (%s, %s, %s, %s, %s) "
        "RETURNING id, project_id, name, description, status, created_at, updated_at",
        (str(uuid.uuid4()), project_id, name, description, status),
    )
    row = await cursor.fetchone()
    if row is None:
        raise RuntimeError("feature insert returned no row")
    return project_state._feature(row)


async def create_blocker_async(
    connection: Any,
    *,
    project_id: str,
    title: str,
    description: str | None,
    severity: str,
) -> project_state.ProjectBlocker:
    cursor = await connection.execute(
        "INSERT INTO assistant_project_blockers "
        "(id, project_id, title, description, severity) VALUES (%s, %s, %s, %s, %s) "
        "RETURNING id, project_id, title, description, severity, status, created_at, resolved_at",
        (str(uuid.uuid4()), project_id, title, description, severity),
    )
    row = await cursor.fetchone()
    if row is None:
        raise RuntimeError("blocker insert returned no row")
    return project_state._blocker(row)


async def resolve_blocker_async(
    connection: Any, *, project_id: str, blocker_id: str
) -> project_state.ProjectBlocker:
    cursor = await connection.execute(
        "UPDATE assistant_project_blockers SET status = 'RESOLVED', resolved_at = now() "
        "WHERE project_id = %s AND id = %s "
        "RETURNING id, project_id, title, description, severity, status, created_at, resolved_at",
        (project_id, blocker_id),
    )
    row = await cursor.fetchone()
    if row is None:
        raise KeyError("blocker not found")
    return project_state._blocker(row)
