"""Bounded SQL project discovery primitives."""

from __future__ import annotations

from typing import Any

from models.projects import _PROJECT_COLUMNS, Project, _project_from_row


async def search_projects_async(
    connection: Any, *, reference: str, lead_id: str | None = None, limit: int = 10
) -> list[Project]:
    """Search names/descriptions without loading an unbounded portfolio."""

    terms = [term for term in reference.split() if term][:6]
    if not terms:
        return []
    clauses = []
    params: list[Any] = []
    for term in terms:
        pattern = f"%{term}%"
        clauses.append("(name ILIKE %s OR description ILIKE %s)")
        params.extend((pattern, pattern))
    scope = " AND lead_id = %s" if lead_id is not None else ""
    if lead_id is not None:
        params.append(lead_id)
    params.extend((reference, limit))
    cursor = await connection.execute(
        f"""
        SELECT {_PROJECT_COLUMNS}
        FROM assistant_projects
        WHERE ({" OR ".join(clauses)}){scope}
        ORDER BY CASE WHEN LOWER(name) = LOWER(%s) THEN 0 ELSE 1 END,
                 updated_at DESC
        LIMIT %s
        """,
        tuple(params),
    )
    return [_project_from_row(row) for row in await cursor.fetchall()]
