"""Durable per-assessor evidence watermark for incremental re-assessment.

``scope-safety`` conclusions are decided per ``tool_call_id`` and are
independent of each other, but the assessor re-scanned every Scope observation
of the Task and re-judged every ToolCall on every trigger, so a Task with N
ToolCalls trended O(N^2) as evidence arrived (phase-9 review followup M2).

Judging only the ToolCalls named by the new watermark window needs a lower
bound, and it has to be one that advances only when an evaluation actually
committed. The assessor job table cannot supply it: ``_claim_assessor_job``
coalesces the group's lower jobs to ``completed`` at claim time, before the
evaluation runs, so a failed or crashed evaluation leaves them completed with
nothing assessed and their evidence would be skipped forever on the retry.

This row is written inside the evaluation's own transaction next to the
conclusions, so it is exactly as durable as they are, and ``rebuild_projections()``
deletes it with them — a replayed database therefore starts from the same
cold-start full scan and rebuilds identical conclusions.

Revision ID: 0025_ansich_assessor_watermarks
Revises: 0024_ansich_wall_time_watermarks
Create Date: 2026-08-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025_ansich_assessor_watermarks"
down_revision: str | Sequence[str] | None = "0024_ansich_wall_time_watermarks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    # Guarded like 0016/0023/0024: a partially provisioned legacy database may
    # not carry the referenced table yet, and re-running must stay a no-op.
    if not inspector.has_table("ansich_tasks"):
        return
    if inspector.has_table("ansich_assessor_watermarks"):
        return
    op.create_table(
        "ansich_assessor_watermarks",
        sa.Column("subject_id", sa.String(length=36), nullable=False),
        sa.Column("assessor_name", sa.String(length=64), nullable=False),
        sa.Column("assessor_version", sa.String(length=32), nullable=False),
        sa.Column("evidence_watermark", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["subject_id"],
            ["ansich_tasks.entity_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("subject_id", "assessor_name", "assessor_version"),
    )


def downgrade() -> None:
    """Drop the mark; the conclusions it guards are rebuildable without it.

    Losing the mark cannot lose evidence: an absent row is the cold-start
    signal, so the next assessment falls back to the full Task scan the
    pre-0025 code performed.
    """

    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("ansich_assessor_watermarks"):
        return
    op.drop_table("ansich_assessor_watermarks")
