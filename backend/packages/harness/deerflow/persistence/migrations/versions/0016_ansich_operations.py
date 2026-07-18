"""Add Ansich Phase 5 heartbeat, usage, budget, and active-task projections.

Revision ID: 0016_ansich_operations
Revises: 0015_ansich_projection_deadline
Create Date: 2026-07-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_ansich_operations"
down_revision: str | Sequence[str] | None = "0015_ansich_projection_deadline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _create_table(name: str, *elements: sa.SchemaItem) -> None:
    """Create a Phase 5 table unless a legacy ``create_all`` already did."""
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
        "ansich_usage_contributions",
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("source_task_id", sa.String(length=36), nullable=False),
        sa.Column("dimension", sa.String(length=32), nullable=False),
        sa.Column("source_obs_id", sa.String(length=36), nullable=False),
        sa.Column("delta", sa.BigInteger(), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_obs_id"],
            ["ansich_observations.obs_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_task_id"],
            ["ansich_tasks.entity_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["ansich_tasks.entity_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "task_id",
            "source_task_id",
            "dimension",
            "source_obs_id",
        ),
    )
    _create_index(
        "ix_ansich_usage_contributions_task_dimension",
        "ansich_usage_contributions",
        ["task_id", "dimension"],
    )
    _create_table(
        "ansich_task_usage",
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("dimension", sa.String(length=32), nullable=False),
        sa.Column("aggregation_scope", sa.String(length=16), nullable=False),
        sa.Column("value", sa.BigInteger(), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "complete_through_ingest_seq",
            sa.BigInteger(),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["ansich_tasks.entity_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("task_id", "dimension", "aggregation_scope"),
    )
    _create_table(
        "ansich_task_budgets",
        sa.Column("entity_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("dimension", sa.String(length=32), nullable=False),
        sa.Column("aggregation_scope", sa.String(length=16), nullable=False),
        sa.Column("warning_limit", sa.BigInteger(), nullable=True),
        sa.Column("hard_limit", sa.BigInteger(), nullable=True),
        sa.Column("enforcement", sa.Boolean(), nullable=False),
        sa.Column("source_kind", sa.String(length=32), nullable=False),
        sa.Column("requested_value", sa.BigInteger(), nullable=True),
        sa.Column("effective_value", sa.BigInteger(), nullable=False),
        sa.Column("configured_obs_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["configured_obs_id"],
            ["ansich_observations.obs_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"],
            ["ansich_entities.entity_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["ansich_tasks.entity_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("entity_id"),
        sa.UniqueConstraint(
            "task_id",
            "dimension",
            "aggregation_scope",
            "configured_obs_id",
            name="uq_ansich_task_budget_configuration",
        ),
    )
    _create_index(
        "ix_ansich_task_budgets_task_dimension",
        "ansich_task_budgets",
        ["task_id", "dimension"],
    )
    _create_table(
        "ansich_task_heartbeats",
        sa.Column("heartbeat_obs_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("producer_instance_id", sa.String(length=128), nullable=False),
        sa.Column("ownership_epoch", sa.String(length=128), nullable=False),
        sa.Column("elapsed_ms", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["heartbeat_obs_id"],
            ["ansich_observations.obs_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["ansich_tasks.entity_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("heartbeat_obs_id"),
    )
    _create_index(
        "ix_ansich_task_heartbeats_task_occurred",
        "ansich_task_heartbeats",
        ["task_id", "occurred_at"],
    )
    _create_table(
        "ansich_active_task_read_model",
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=128), nullable=False),
        sa.Column("source_kind", sa.String(length=64), nullable=False),
        sa.Column("owner_id", sa.String(length=256), nullable=True),
        sa.Column("thread_id", sa.String(length=256), nullable=True),
        sa.Column("agent_id", sa.String(length=256), nullable=True),
        sa.Column("control_value", sa.String(length=32), nullable=False),
        sa.Column("current_step_id", sa.String(length=36), nullable=True),
        sa.Column("current_tool_call_id", sa.String(length=36), nullable=True),
        sa.Column("heartbeat_value", sa.String(length=16), nullable=False),
        sa.Column("budget_status", sa.String(length=16), nullable=False),
        sa.Column("duration_ms", sa.BigInteger(), nullable=False),
        sa.Column("observability_status", sa.String(length=16), nullable=False),
        sa.Column("projection_watermark", sa.BigInteger(), nullable=True),
        sa.Column("projection_lag_ms", sa.BigInteger(), nullable=False),
        sa.Column("control_json", sa.JSON(), nullable=False),
        sa.Column("current_step_json", sa.JSON(), nullable=True),
        sa.Column("current_tool_json", sa.JSON(), nullable=True),
        sa.Column("dwell_json", sa.JSON(), nullable=False),
        sa.Column("heartbeat_json", sa.JSON(), nullable=False),
        sa.Column("usage_json", sa.JSON(), nullable=False),
        sa.Column("budgets_json", sa.JSON(), nullable=False),
        sa.Column("budget_health_json", sa.JSON(), nullable=False),
        sa.Column("lost_ranges_json", sa.JSON(), nullable=False),
        sa.Column("last_evidence_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["ansich_tasks.entity_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("task_id"),
    )
    _create_index(
        "ix_ansich_active_tasks_evidence",
        "ansich_active_task_read_model",
        ["last_evidence_at", "task_id"],
    )
    _create_index(
        "ix_ansich_active_tasks_filters",
        "ansich_active_task_read_model",
        ["owner_id", "heartbeat_value", "budget_status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ansich_active_tasks_filters",
        table_name="ansich_active_task_read_model",
    )
    op.drop_index(
        "ix_ansich_active_tasks_evidence",
        table_name="ansich_active_task_read_model",
    )
    op.drop_table("ansich_active_task_read_model")
    op.drop_index(
        "ix_ansich_task_heartbeats_task_occurred",
        table_name="ansich_task_heartbeats",
    )
    op.drop_table("ansich_task_heartbeats")
    op.drop_index(
        "ix_ansich_task_budgets_task_dimension",
        table_name="ansich_task_budgets",
    )
    op.drop_table("ansich_task_budgets")
    op.drop_table("ansich_task_usage")
    op.drop_index(
        "ix_ansich_usage_contributions_task_dimension",
        table_name="ansich_usage_contributions",
    )
    op.drop_table("ansich_usage_contributions")
