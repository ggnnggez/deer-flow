"""Add a durable deadline anchor for pending Ansich projection dependencies.

Revision ID: 0015_ansich_projection_deadline
Revises: 0014_ansich_context_lineage
Create Date: 2026-07-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from deerflow.persistence.migrations._helpers import safe_add_column, safe_drop_column

revision: str = "0015_ansich_projection_deadline"
down_revision: str | Sequence[str] | None = "0014_ansich_context_lineage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    safe_add_column(
        "ansich_projection_jobs",
        sa.Column(
            "dependency_pending_since",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    safe_drop_column("ansich_projection_jobs", "dependency_pending_since")
