"""Startup schema for normalized project delivery state."""

from __future__ import annotations

from typing import Any


async def ensure_project_state_tables_async(connection: Any) -> None:
    """Create project-state tables idempotently for the POC startup path."""

    await connection.execute(
        """
        CREATE TABLE IF NOT EXISTS assistant_project_features (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES assistant_projects(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            description TEXT,
            status TEXT NOT NULL DEFAULT 'DEV'
                CHECK (status IN ('DEV', 'QA', 'UAT', 'PROD', 'BUG', 'BLOCKED')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    await connection.execute(
        """
        CREATE TABLE IF NOT EXISTS assistant_project_blockers (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES assistant_projects(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            description TEXT,
            severity TEXT NOT NULL DEFAULT 'MEDIUM'
                CHECK (severity IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')),
            status TEXT NOT NULL DEFAULT 'OPEN'
                CHECK (status IN ('OPEN', 'RESOLVED')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            resolved_at TIMESTAMPTZ
        )
        """
    )
    await connection.execute(
        """
        CREATE TABLE IF NOT EXISTS assistant_daily_project_updates (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES assistant_projects(id) ON DELETE CASCADE,
            submitted_by TEXT NOT NULL REFERENCES assistant_users(id),
            summary TEXT NOT NULL,
            completion_percentage INTEGER NOT NULL CHECK (completion_percentage BETWEEN 0 AND 100),
            blocker_ids JSONB NOT NULL DEFAULT '[]',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    await connection.execute(
        """
        CREATE TABLE IF NOT EXISTS assistant_feature_status_history (
            id BIGSERIAL PRIMARY KEY,
            feature_id TEXT NOT NULL REFERENCES assistant_project_features(id) ON DELETE CASCADE,
            old_status TEXT NOT NULL,
            new_status TEXT NOT NULL,
            changed_by TEXT NOT NULL REFERENCES assistant_users(id),
            changed_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    await connection.execute(
        "ALTER TABLE assistant_project_features ADD COLUMN IF NOT EXISTS description TEXT"
    )
    await connection.execute(
        "CREATE INDEX IF NOT EXISTS assistant_project_features_project_idx "
        "ON assistant_project_features (project_id)"
    )
    await connection.execute(
        "CREATE INDEX IF NOT EXISTS assistant_project_blockers_project_idx "
        "ON assistant_project_blockers (project_id, status)"
    )
    await connection.execute(
        "CREATE INDEX IF NOT EXISTS assistant_daily_project_updates_project_idx "
        "ON assistant_daily_project_updates (project_id, created_at DESC)"
    )
