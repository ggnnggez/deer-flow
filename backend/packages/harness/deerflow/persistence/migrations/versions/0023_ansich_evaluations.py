"""Add Ansich Phase 10 evaluation index and release quality statistics.

Revision ID: 0023_ansich_evaluations
Revises: 0022_ansich_assessor_deadline
Create Date: 2026-08-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023_ansich_evaluations"
down_revision: str | Sequence[str] | None = "0022_ansich_assessor_deadline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _create_table(name: str, *elements: sa.SchemaItem) -> None:
    """Create a Phase 10 table unless a legacy ``create_all`` already did."""
    if not sa.inspect(op.get_bind()).has_table(name):
        op.create_table(name, *elements)


def _create_index(name: str, table_name: str, columns: list[str]) -> None:
    """Backfill an index independently from its table for partial legacy schemas."""
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table_name):
        return
    if name not in {index["name"] for index in inspector.get_indexes(table_name)}:
        op.create_index(name, table_name, columns, unique=False)


def upgrade() -> None:
    _create_table(
        "ansich_evaluation_index",
        sa.Column("evaluation_obs_id", sa.String(length=36), nullable=False),
        sa.Column("subject_type", sa.String(length=32), nullable=False),
        sa.Column("subject_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("evaluation_kind", sa.String(length=32), nullable=False),
        sa.Column("dimension", sa.String(length=32), nullable=False),
        sa.Column("verdict", sa.String(length=16), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("scale_min", sa.Float(), nullable=True),
        sa.Column("scale_max", sa.Float(), nullable=True),
        sa.Column("scale_higher_is_better", sa.Boolean(), nullable=True),
        sa.Column("assessor_name", sa.String(length=64), nullable=False),
        sa.Column("assessor_version", sa.String(length=32), nullable=True),
        sa.Column("authority_class", sa.String(length=32), nullable=False),
        sa.Column("fidelity_class", sa.String(length=16), nullable=False),
        sa.Column("cohort_key", sa.String(length=128), nullable=True),
        sa.Column("suite_id", sa.String(length=128), nullable=True),
        sa.Column("suite_version", sa.String(length=64), nullable=True),
        sa.Column("case_id", sa.String(length=128), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("projector_version", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(
            ["evaluation_obs_id"],
            ["ansich_observations.obs_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("evaluation_obs_id"),
    )
    _create_index(
        "ix_ansich_evaluation_subject_dimension",
        "ansich_evaluation_index",
        ["subject_type", "subject_id", "dimension", "occurred_at"],
    )
    _create_index(
        "ix_ansich_evaluation_suite_case",
        "ansich_evaluation_index",
        ["suite_id", "suite_version", "case_id"],
    )
    _create_index(
        "ix_ansich_evaluation_task",
        "ansich_evaluation_index",
        ["task_id", "occurred_at"],
    )
    _create_table(
        "ansich_release_quality_stats",
        sa.Column("release_id", sa.String(length=36), nullable=False),
        sa.Column("cohort_key", sa.String(length=128), nullable=False),
        sa.Column("dimension", sa.String(length=32), nullable=False),
        sa.Column("assessed_count", sa.Integer(), nullable=False),
        sa.Column("pass_count", sa.Integer(), nullable=False),
        sa.Column("fail_count", sa.Integer(), nullable=False),
        sa.Column("partial_count", sa.Integer(), nullable=False),
        sa.Column("score_sum", sa.Float(), nullable=True),
        sa.Column("score_count", sa.Integer(), nullable=False),
        sa.Column("scale_min", sa.Float(), nullable=True),
        sa.Column("scale_max", sa.Float(), nullable=True),
        sa.Column("scale_higher_is_better", sa.Boolean(), nullable=True),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("projector_version", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(
            ["release_id"],
            ["ansich_entities.entity_id"],
            ondelete="CASCADE",
        ),
        # The primary key's unique index already covers
        # (release_id, cohort_key, dimension), so no extra index is created.
        sa.PrimaryKeyConstraint("release_id", "cohort_key", "dimension"),
    )


def downgrade() -> None:
    op.drop_table("ansich_release_quality_stats")
    op.drop_index(
        "ix_ansich_evaluation_task",
        table_name="ansich_evaluation_index",
    )
    op.drop_index(
        "ix_ansich_evaluation_suite_case",
        table_name="ansich_evaluation_index",
    )
    op.drop_index(
        "ix_ansich_evaluation_subject_dimension",
        table_name="ansich_evaluation_index",
    )
    op.drop_table("ansich_evaluation_index")
