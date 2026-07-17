"""Add Ansich ToolCall accountability projections.

Revision ID: 0013_ansich_tool_accountability
Revises: 0012_ansich_attempt_metadata
Create Date: 2026-07-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from deerflow.persistence.migrations._helpers import safe_add_column, safe_drop_column

revision: str = "0013_ansich_tool_accountability"
down_revision: str | Sequence[str] | None = "0012_ansich_attempt_metadata"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    safe_add_column(
        "ansich_task_summaries",
        sa.Column(
            "tool_calls_issued",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
    )
    safe_add_column(
        "ansich_task_summaries",
        sa.Column(
            "tool_calls_executed",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
    )
    if sa.inspect(op.get_bind()).has_table("ansich_task_summaries"):
        with op.batch_alter_table("ansich_task_summaries") as batch:
            batch.alter_column(
                "tool_calls_issued",
                existing_type=sa.BigInteger(),
                existing_nullable=False,
                server_default=None,
            )
            batch.alter_column(
                "tool_calls_executed",
                existing_type=sa.BigInteger(),
                existing_nullable=False,
                server_default=None,
            )

    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("ansich_tool_calls"):
        op.create_table(
            "ansich_tool_calls",
            sa.Column("entity_id", sa.String(length=36), nullable=False),
            sa.Column("task_id", sa.String(length=36), nullable=False),
            sa.Column("step_id", sa.String(length=36), nullable=False),
            sa.Column("call_seq", sa.Integer(), nullable=False),
            sa.Column("provider_call_id", sa.String(length=256), nullable=True),
            sa.Column("tool_name", sa.String(length=256), nullable=False),
            sa.Column("args_hash", sa.String(length=64), nullable=False),
            sa.Column("args_preview_json", sa.JSON(), nullable=True),
            sa.Column("tool_schema_block_id", sa.String(length=36), nullable=True),
            sa.Column("issued_obs_id", sa.String(length=36), nullable=True),
            sa.Column("started_obs_id", sa.String(length=36), nullable=True),
            sa.Column("raw_terminal_obs_id", sa.String(length=36), nullable=True),
            sa.Column("visible_result_obs_id", sa.String(length=36), nullable=True),
            sa.Column("execution_status", sa.String(length=32), nullable=False),
            sa.Column("visible_result_status", sa.String(length=16), nullable=False),
            sa.Column("duration_ms", sa.BigInteger(), nullable=True),
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
            sa.ForeignKeyConstraint(
                ["step_id"],
                ["ansich_steps.entity_id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["tool_schema_block_id"],
                ["ansich_content_blocks.entity_id"],
                ondelete="SET NULL",
            ),
            sa.ForeignKeyConstraint(
                ["issued_obs_id"],
                ["ansich_observations.obs_id"],
                ondelete="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["started_obs_id"],
                ["ansich_observations.obs_id"],
                ondelete="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["raw_terminal_obs_id"],
                ["ansich_observations.obs_id"],
                ondelete="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["visible_result_obs_id"],
                ["ansich_observations.obs_id"],
                ondelete="RESTRICT",
            ),
            sa.PrimaryKeyConstraint("entity_id"),
            sa.UniqueConstraint("issued_obs_id"),
            sa.UniqueConstraint("started_obs_id"),
            sa.UniqueConstraint("raw_terminal_obs_id"),
            sa.UniqueConstraint("visible_result_obs_id"),
            sa.UniqueConstraint(
                "step_id",
                "call_seq",
                name="uq_ansich_tool_call_step_seq",
            ),
        )
        op.create_index(
            "ix_ansich_tool_calls_step_seq",
            "ansich_tool_calls",
            ["step_id", "call_seq"],
        )
        op.create_index(
            "ix_ansich_tool_calls_provider",
            "ansich_tool_calls",
            ["provider_call_id"],
        )
        op.create_index(
            "ix_ansich_tool_calls_name_issued",
            "ansich_tool_calls",
            ["tool_name", "issued_obs_id"],
        )

    if not sa.inspect(op.get_bind()).has_table("ansich_tool_call_results"):
        op.create_table(
            "ansich_tool_call_results",
            sa.Column("tool_call_id", sa.String(length=36), nullable=False),
            sa.Column("result_role", sa.String(length=16), nullable=False),
            sa.Column("source_obs_id", sa.String(length=36), nullable=False),
            sa.Column("content_block_id", sa.String(length=36), nullable=False),
            sa.Column("metadata_json", sa.JSON(), nullable=False),
            sa.ForeignKeyConstraint(
                ["tool_call_id"],
                ["ansich_tool_calls.entity_id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["source_obs_id"],
                ["ansich_observations.obs_id"],
                ondelete="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["content_block_id"],
                ["ansich_content_blocks.entity_id"],
                ondelete="RESTRICT",
            ),
            sa.PrimaryKeyConstraint("tool_call_id", "result_role", "source_obs_id"),
        )
        op.create_index(
            "ix_ansich_tool_call_results_block",
            "ansich_tool_call_results",
            ["content_block_id"],
        )

    if not sa.inspect(op.get_bind()).has_table("ansich_content_block_derivations"):
        op.create_table(
            "ansich_content_block_derivations",
            sa.Column("derived_block_id", sa.String(length=36), nullable=False),
            sa.Column("source_block_id", sa.String(length=36), nullable=False),
            sa.Column("transform_kind", sa.String(length=32), nullable=False),
            sa.Column("transform_version", sa.String(length=32), nullable=False),
            sa.Column("established_obs_id", sa.String(length=36), nullable=False),
            sa.ForeignKeyConstraint(
                ["derived_block_id"],
                ["ansich_content_blocks.entity_id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["source_block_id"],
                ["ansich_content_blocks.entity_id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["established_obs_id"],
                ["ansich_observations.obs_id"],
                ondelete="RESTRICT",
            ),
            sa.PrimaryKeyConstraint(
                "derived_block_id",
                "source_block_id",
                "transform_kind",
            ),
        )
        op.create_index(
            "ix_ansich_derivations_derived",
            "ansich_content_block_derivations",
            ["derived_block_id"],
        )
        op.create_index(
            "ix_ansich_derivations_source",
            "ansich_content_block_derivations",
            ["source_block_id"],
        )


def downgrade() -> None:
    for table in (
        "ansich_content_block_derivations",
        "ansich_tool_call_results",
        "ansich_tool_calls",
    ):
        if sa.inspect(op.get_bind()).has_table(table):
            op.drop_table(table)
    safe_drop_column("ansich_task_summaries", "tool_calls_executed")
    safe_drop_column("ansich_task_summaries", "tool_calls_issued")
