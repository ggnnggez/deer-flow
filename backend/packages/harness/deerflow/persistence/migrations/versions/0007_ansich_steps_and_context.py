"""Ansich logical steps, LLM attempts, and context snapshots.

Revision ID: 0007_ansich_steps_and_context
Revises: 0006_ansich_task_core
Create Date: 2026-07-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from deerflow.persistence.migrations._helpers import safe_add_column, safe_drop_column

revision: str = "0007_ansich_steps_and_context"
down_revision: str | Sequence[str] | None = "0006_ansich_task_core"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _create_table(name: str, *elements: sa.SchemaItem) -> None:
    if not sa.inspect(op.get_bind()).has_table(name):
        op.create_table(name, *elements)


def _create_index(name: str, table_name: str, columns: list[str], *, unique: bool = False) -> None:
    inspector = sa.inspect(op.get_bind())
    existing = {index["name"] for index in inspector.get_indexes(table_name)}
    if name not in existing:
        op.create_index(name, table_name, columns, unique=unique)


def upgrade() -> None:
    safe_add_column("ansich_observations", sa.Column("step_id", sa.String(length=36), nullable=True))

    _create_table(
        "ansich_steps",
        sa.Column("entity_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("step_seq", sa.Integer(), nullable=False),
        sa.Column("actor_kind", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("result", sa.String(length=32), nullable=True),
        sa.Column("started_obs_id", sa.String(length=36), nullable=False),
        sa.Column("closed_obs_id", sa.String(length=36), nullable=True),
        sa.Column("effective_attempt_no", sa.Integer(), nullable=True),
        sa.Column("effective_context_snapshot_id", sa.String(length=36), nullable=True),
        sa.Column("issued_tools_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["closed_obs_id"], ["ansich_observations.obs_id"]),
        sa.ForeignKeyConstraint(["entity_id"], ["ansich_entities.entity_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["started_obs_id"], ["ansich_observations.obs_id"]),
        sa.ForeignKeyConstraint(["task_id"], ["ansich_tasks.entity_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("entity_id"),
        sa.UniqueConstraint("task_id", "step_seq", name="uq_ansich_step_task_seq"),
    )
    _create_index("ix_ansich_steps_task_seq", "ansich_steps", ["task_id", "step_seq"])

    _create_table(
        "ansich_llm_attempts",
        sa.Column("attempt_id", sa.String(length=36), nullable=False),
        sa.Column("step_id", sa.String(length=36), nullable=True),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("actor_kind", sa.String(length=32), nullable=False),
        sa.Column("operation_id", sa.String(length=36), nullable=True),
        sa.Column("operation_kind", sa.String(length=32), nullable=True),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("request_obs_id", sa.String(length=36), nullable=True),
        sa.Column("response_obs_id", sa.String(length=36), nullable=True),
        sa.Column("failure_obs_id", sa.String(length=36), nullable=True),
        sa.Column("provider_model", sa.String(length=256), nullable=True),
        sa.Column("usage_json", sa.JSON(), nullable=True),
        sa.Column("latency_ms", sa.BigInteger(), nullable=True),
        sa.Column("context_snapshot_id", sa.String(length=36), nullable=True),
        sa.ForeignKeyConstraint(["failure_obs_id"], ["ansich_observations.obs_id"]),
        sa.ForeignKeyConstraint(["request_obs_id"], ["ansich_observations.obs_id"]),
        sa.ForeignKeyConstraint(["response_obs_id"], ["ansich_observations.obs_id"]),
        sa.ForeignKeyConstraint(["step_id"], ["ansich_steps.entity_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["ansich_tasks.entity_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("attempt_id"),
        sa.UniqueConstraint("failure_obs_id"),
        sa.UniqueConstraint("request_obs_id"),
        sa.UniqueConstraint("response_obs_id"),
        sa.UniqueConstraint("step_id", "attempt_no", name="uq_ansich_llm_attempt_step_no"),
        sa.UniqueConstraint("task_id", "operation_id", "attempt_no", name="uq_ansich_llm_attempt_operation_no"),
    )
    _create_index("ix_ansich_llm_attempts_step_no", "ansich_llm_attempts", ["step_id", "attempt_no"])
    _create_index("ix_ansich_llm_attempts_task_request", "ansich_llm_attempts", ["task_id", "request_obs_id"])

    _create_table(
        "ansich_content_blocks",
        sa.Column("entity_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("payload_obs_id", sa.String(length=36), nullable=False),
        sa.Column("producer_obs_id", sa.String(length=36), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("token_estimate", sa.BigInteger(), nullable=False),
        sa.Column("sensitivity_flags_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["entity_id"], ["ansich_entities.entity_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["payload_obs_id"], ["ansich_observations.obs_id"]),
        sa.ForeignKeyConstraint(["producer_obs_id"], ["ansich_observations.obs_id"]),
        sa.PrimaryKeyConstraint("entity_id"),
        sa.UniqueConstraint("producer_obs_id"),
    )
    _create_index("ix_ansich_content_blocks_hash", "ansich_content_blocks", ["content_hash"])

    _create_table(
        "ansich_context_windows",
        sa.Column("entity_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("capacity_tokens", sa.BigInteger(), nullable=True),
        sa.Column("estimator_name", sa.String(length=64), nullable=False),
        sa.Column("estimator_version", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(["entity_id"], ["ansich_entities.entity_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["ansich_tasks.entity_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("entity_id"),
        sa.UniqueConstraint("task_id"),
    )

    _create_table(
        "ansich_context_snapshots",
        sa.Column("entity_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("step_id", sa.String(length=36), nullable=True),
        sa.Column("operation_id", sa.String(length=36), nullable=True),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("request_obs_id", sa.String(length=36), nullable=False),
        sa.Column("message_count", sa.Integer(), nullable=False),
        sa.Column("tool_schema_count", sa.Integer(), nullable=False),
        sa.Column("visible_bytes", sa.BigInteger(), nullable=False),
        sa.Column("estimated_tokens", sa.BigInteger(), nullable=False),
        sa.Column("estimator_name", sa.String(length=64), nullable=False),
        sa.Column("estimator_version", sa.String(length=32), nullable=False),
        sa.Column("adapter_name", sa.String(length=256), nullable=False),
        sa.Column("adapter_version", sa.String(length=64), nullable=False),
        sa.Column("configured_model", sa.String(length=256), nullable=True),
        sa.Column("response_format_json", sa.JSON(), nullable=True),
        sa.Column("generation_settings_json", sa.JSON(), nullable=False),
        sa.Column("redactions_json", sa.JSON(), nullable=False),
        sa.Column("warnings_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["entity_id"], ["ansich_entities.entity_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["request_obs_id"], ["ansich_observations.obs_id"]),
        sa.ForeignKeyConstraint(["step_id"], ["ansich_steps.entity_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["ansich_tasks.entity_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("entity_id"),
        sa.UniqueConstraint("request_obs_id"),
    )
    _create_index(
        "ix_ansich_context_snapshots_task_request",
        "ansich_context_snapshots",
        ["task_id", "request_obs_id"],
    )

    _create_table(
        "ansich_context_snapshot_items",
        sa.Column("snapshot_id", sa.String(length=36), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=True),
        sa.Column("name", sa.String(length=256), nullable=True),
        sa.Column("content_block_id", sa.String(length=36), nullable=False),
        sa.Column("visible_bytes", sa.BigInteger(), nullable=False),
        sa.Column("estimated_tokens", sa.BigInteger(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["content_block_id"], ["ansich_content_blocks.entity_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["snapshot_id"], ["ansich_context_snapshots.entity_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("snapshot_id", "ordinal"),
    )
    _create_index(
        "ix_ansich_context_snapshot_items_block",
        "ansich_context_snapshot_items",
        ["content_block_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_ansich_context_snapshot_items_block", table_name="ansich_context_snapshot_items")
    op.drop_table("ansich_context_snapshot_items")
    op.drop_index("ix_ansich_context_snapshots_task_request", table_name="ansich_context_snapshots")
    op.drop_table("ansich_context_snapshots")
    op.drop_table("ansich_context_windows")
    op.drop_index("ix_ansich_content_blocks_hash", table_name="ansich_content_blocks")
    op.drop_table("ansich_content_blocks")
    op.drop_index("ix_ansich_llm_attempts_task_request", table_name="ansich_llm_attempts")
    op.drop_index("ix_ansich_llm_attempts_step_no", table_name="ansich_llm_attempts")
    op.drop_table("ansich_llm_attempts")
    op.drop_index("ix_ansich_steps_task_seq", table_name="ansich_steps")
    op.drop_table("ansich_steps")
    safe_drop_column("ansich_observations", "step_id")
