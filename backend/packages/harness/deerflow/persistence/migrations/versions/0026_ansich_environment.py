"""Add Ansich environment-observability read-model tables.

Introduces three new tables for per-command and per-Scope environment
observability:

- ``ansich_environment_coverage`` — per-(Scope, environment_scope) materialized
  probe coverage (e.g. is a cgroup/procfs/docker-stats probe currently
  observing this Scope, and with what provider).
- ``ansich_environment_state`` — per-(Scope, environment_scope, metric)
  materialized latest reading plus a bounded growth window, so an assessor can
  detect sustained monotonic growth (e.g. a leaking fd count) without
  rescanning raw observations.
- ``ansich_tool_env_samples`` — per-tool-call environment sample (I/O bytes,
  peak fd count). Deliberately carries no foreign keys: per-command
  environment rows do not participate in dependency-wait projection (Task 8),
  so a sample can be written before its Task/Scope/ToolCall projections land.

Also adds one additive nullable column, ``possibly_affected_task_ids``, to the
existing ``ansich_alert_read_model`` table.

Revision ID: 0026_ansich_environment
Revises: 0025_ansich_assessor_watermarks
Create Date: 2026-08-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from deerflow.persistence.migrations._helpers import safe_add_column, safe_drop_column

revision: str = "0026_ansich_environment"
down_revision: str | Sequence[str] | None = "0025_ansich_assessor_watermarks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _create_table(name: str, *elements: sa.SchemaItem) -> None:
    """Create a Task 7 table unless a legacy ``create_all`` already did."""
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
        "ansich_environment_coverage",
        sa.Column("scope_id", sa.String(length=36), nullable=False),
        sa.Column("environment_scope", sa.String(length=64), nullable=False),
        sa.Column("coverage", sa.String(length=32), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_obs_id", sa.String(length=36), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["scope_id"],
            ["ansich_entities.entity_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("scope_id", "environment_scope"),
    )
    _create_table(
        "ansich_environment_state",
        sa.Column("scope_id", sa.String(length=36), nullable=False),
        sa.Column("environment_scope", sa.String(length=64), nullable=False),
        sa.Column("metric", sa.String(length=64), nullable=False),
        sa.Column("latest_value", sa.BigInteger(), nullable=False),
        sa.Column("limit_value", sa.BigInteger(), nullable=True),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_min_value", sa.BigInteger(), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("consecutive_growth_count", sa.Integer(), nullable=False),
        sa.Column("growth_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_obs_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["scope_id"],
            ["ansich_entities.entity_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("scope_id", "environment_scope", "metric"),
    )
    _create_index(
        "ix_ansich_env_state_scope",
        "ansich_environment_state",
        ["scope_id"],
    )
    _create_table(
        "ansich_tool_env_samples",
        sa.Column("tool_call_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("scope_id", sa.String(length=36), nullable=False),
        sa.Column("io_read_bytes", sa.BigInteger(), nullable=True),
        sa.Column("io_write_bytes", sa.BigInteger(), nullable=True),
        sa.Column("fd_peak", sa.BigInteger(), nullable=True),
        sa.Column("sample_count", sa.BigInteger(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("obs_id", sa.String(length=36), nullable=False),
        sa.PrimaryKeyConstraint("tool_call_id"),
    )
    _create_index(
        "ix_ansich_tool_env_samples_task",
        "ansich_tool_env_samples",
        ["task_id"],
    )
    safe_add_column(
        "ansich_alert_read_model",
        sa.Column("possibly_affected_task_ids", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    safe_drop_column("ansich_alert_read_model", "possibly_affected_task_ids")
    op.drop_index(
        "ix_ansich_tool_env_samples_task",
        table_name="ansich_tool_env_samples",
    )
    op.drop_table("ansich_tool_env_samples")
    op.drop_index(
        "ix_ansich_env_state_scope",
        table_name="ansich_environment_state",
    )
    op.drop_table("ansich_environment_state")
    op.drop_table("ansich_environment_coverage")
