"""RBAC enforcement constants, ported from enterprise app/access/rbac.py.

rag never resolves roles — the caller passes AccessFilter. This module only
enforces: department membership + numeric access-level ceiling.
"""

from __future__ import annotations

ACCESS_LEVELS = {
    "public": 0,
    "internal": 1,
    "confidential": 2,
    "restricted": 3,
}

ACCESS_LEVEL_LABELS = {v: k for k, v in ACCESS_LEVELS.items()}

# Filename prefix -> department mapping used at ingest time
FILENAME_DEPARTMENT_MAP: dict[str, str] = {
    "hr_": "hr",
    "security_": "security",
    "incident_": "security",
    "product_": "product",
    "finance_": "finance",
}

# Filename prefix -> access level mapping used at ingest time
FILENAME_ACCESS_LEVEL_MAP: dict[str, str] = {
    "hr_": "confidential",
    "security_": "restricted",
    "incident_": "restricted",
    "product_": "public",
    "finance_": "confidential",
}


def infer_document_metadata(filename: str) -> dict[str, str]:
    """
    Infer department and access_level from a filename at ingest time.
    Falls back to department='general', access_level='internal' when unknown.
    """
    lower = filename.lower()
    department = "general"
    access_level = "internal"

    for prefix, dept in FILENAME_DEPARTMENT_MAP.items():
        if lower.startswith(prefix):
            department = dept
            break

    for prefix, level in FILENAME_ACCESS_LEVEL_MAP.items():
        if lower.startswith(prefix):
            access_level = level
            break

    return {"department": department, "access_level": access_level}


def passes_access_filter(
    metadata: dict,
    departments: list[str],
    max_access_level: int,
    tenant: str | None = None,
) -> bool:
    chunk_dept = metadata.get("department", "general")
    chunk_level_str = metadata.get("access_level", "internal")
    chunk_level = ACCESS_LEVELS.get(chunk_level_str, 1)
    dept_ok = "all" in departments or chunk_dept in departments
    level_ok = chunk_level <= max_access_level
    if tenant is None:
        return dept_ok and level_ok
    return dept_ok and level_ok and metadata.get("tenant", "default") == tenant


def allowed_level_labels(max_level: int) -> tuple[str, ...]:
    return tuple(label for label, value in ACCESS_LEVELS.items() if value <= max_level)


def normalize_tenant(tenant: str | None) -> str:
    """Single normalization point: empty/None becomes "default"."""
    return tenant or "default"
