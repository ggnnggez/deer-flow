"""Add a durable deadline anchor for pending Ansich assessor dependencies.

Revision ID: 0022_ansich_assessor_deadline
Revises: 0021_ansich_summary_assertion_fk
Create Date: 2026-08-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from deerflow.persistence.migrations._helpers import safe_add_column, safe_drop_column

revision: str = "0022_ansich_assessor_deadline"
down_revision: str | Sequence[str] | None = "0021_ansich_summary_assertion_fk"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    safe_add_column(
        "ansich_assessor_jobs",
        sa.Column(
            "dependency_pending_since",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    safe_drop_column("ansich_assessor_jobs", "dependency_pending_since")
