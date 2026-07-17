"""Compatibility anchor for the originally released Ansich Phase 1 revision.

Revision ID: 0005_ansich_task_core
Revises: 0004_run_ownership
Create Date: 2026-07-17

Phase 1 shipped with this revision id. An upstream merge subsequently added
``0005_run_stop_reason`` and moved the idempotent Ansich DDL to
``0006_ansich_task_core``. This no-op anchor keeps databases stamped at the
released id resolvable; 0006 is a merge revision and applies/validates the
Ansich schema after both 0005 branches are present.
"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "0005_ansich_task_core"
down_revision: str | Sequence[str] | None = "0004_run_ownership"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
