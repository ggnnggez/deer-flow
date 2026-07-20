"""Add typed Task ancestry and inclusive usage aggregation.

Revision ID: 0019_ansich_task_tree_usage
Revises: 0018_ansich_agent_releases
Create Date: 2026-07-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_ansich_task_tree_usage"
down_revision: str | Sequence[str] | None = "0018_ansich_agent_releases"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _unique_names(table_name: str) -> set[str]:
    return {str(item["name"]) for item in sa.inspect(op.get_bind()).get_unique_constraints(table_name) if item.get("name")}


def _create_table(name: str, *elements: sa.SchemaItem) -> None:
    if not sa.inspect(op.get_bind()).has_table(name):
        op.create_table(name, *elements)


def _create_index(name: str, table_name: str, columns: list[str]) -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table_name):
        return
    if name not in {index["name"] for index in inspector.get_indexes(table_name)}:
        op.create_index(name, table_name, columns, unique=False)


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("ansich_steps"):
        if "uq_ansich_step_entity_task" not in _unique_names("ansich_steps"):
            with op.batch_alter_table("ansich_steps") as batch:
                batch.create_unique_constraint(
                    "uq_ansich_step_entity_task",
                    ["entity_id", "task_id"],
                )
    if inspector.has_table("ansich_tool_calls"):
        if "uq_ansich_tool_call_entity_step_task" not in _unique_names("ansich_tool_calls"):
            with op.batch_alter_table("ansich_tool_calls") as batch:
                batch.create_unique_constraint(
                    "uq_ansich_tool_call_entity_step_task",
                    ["entity_id", "step_id", "task_id"],
                )

    contribution_columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("ansich_usage_contributions")}
    if "task_id" in contribution_columns and "aggregate_task_id" not in contribution_columns:
        with op.batch_alter_table("ansich_usage_contributions") as batch:
            batch.alter_column(
                "task_id",
                new_column_name="aggregate_task_id",
                existing_type=sa.String(length=36),
                existing_nullable=False,
            )

    # Before Phase 8 every summary was local. Seed an inclusive self summary
    # so historical top-level Tasks remain immediately queryable without a
    # projection rebuild; later child edges backfill descendant contributions.
    op.execute(
        sa.text(
            """
            INSERT INTO ansich_task_usage (
                task_id, dimension, aggregation_scope, value, as_of,
                complete_through_ingest_seq, updated_at
            )
            SELECT
                local.task_id, local.dimension, 'inclusive', local.value,
                local.as_of, local.complete_through_ingest_seq, local.updated_at
            FROM ansich_task_usage AS local
            WHERE local.aggregation_scope = 'local'
              AND NOT EXISTS (
                  SELECT 1
                  FROM ansich_task_usage AS existing
                  WHERE existing.task_id = local.task_id
                    AND existing.dimension = local.dimension
                    AND existing.aggregation_scope = 'inclusive'
              )
            """
        )
    )
    # The serialized Phase 5 read model carries
    # ``inclusive_status=not_available`` and cannot be parsed by the Phase 8
    # contract. It is a rebuildable projection; clearing it lets the existing
    # cold-start/periodic assessor regenerate rows from the summaries above.
    op.execute(sa.text("DELETE FROM ansich_active_task_read_model"))

    _create_table(
        "ansich_task_spawns",
        sa.Column("parent_task_id", sa.String(36), nullable=False),
        sa.Column("spawning_step_id", sa.String(36), nullable=False),
        sa.Column("spawning_tool_call_id", sa.String(36), nullable=False),
        sa.Column("child_task_id", sa.String(36), nullable=False),
        sa.Column("established_obs_id", sa.String(36), nullable=False),
        sa.Column("subagent_name", sa.String(128), nullable=True),
        sa.ForeignKeyConstraint(
            ["parent_task_id"],
            ["ansich_tasks.entity_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["child_task_id"],
            ["ansich_tasks.entity_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["spawning_step_id", "parent_task_id"],
            ["ansich_steps.entity_id", "ansich_steps.task_id"],
            ondelete="CASCADE",
            name="fk_ansich_task_spawn_parent_step",
        ),
        sa.ForeignKeyConstraint(
            ["spawning_tool_call_id", "spawning_step_id", "parent_task_id"],
            [
                "ansich_tool_calls.entity_id",
                "ansich_tool_calls.step_id",
                "ansich_tool_calls.task_id",
            ],
            ondelete="CASCADE",
            name="fk_ansich_task_spawn_parent_tool",
        ),
        sa.ForeignKeyConstraint(
            ["established_obs_id"],
            ["ansich_observations.obs_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("child_task_id"),
    )
    _create_index(
        "ix_ansich_task_spawns_parent_child",
        "ansich_task_spawns",
        ["parent_task_id", "child_task_id"],
    )
    _create_table(
        "ansich_task_ancestry",
        sa.Column("ancestor_task_id", sa.String(36), nullable=False),
        sa.Column("descendant_task_id", sa.String(36), nullable=False),
        sa.Column("depth", sa.Integer(), nullable=False),
        sa.Column("established_obs_id", sa.String(36), nullable=False),
        sa.ForeignKeyConstraint(
            ["ancestor_task_id"],
            ["ansich_tasks.entity_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["descendant_task_id"],
            ["ansich_tasks.entity_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["established_obs_id"],
            ["ansich_observations.obs_id"],
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "ancestor_task_id <> descendant_task_id",
            name="ck_ansich_task_ancestry_self_free",
        ),
        sa.CheckConstraint(
            "depth > 0",
            name="ck_ansich_task_ancestry_positive_depth",
        ),
        sa.PrimaryKeyConstraint("ancestor_task_id", "descendant_task_id"),
    )
    _create_index(
        "ix_ansich_task_ancestry_descendant_ancestor",
        "ansich_task_ancestry",
        ["descendant_task_id", "ancestor_task_id"],
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for table_name in ("ansich_task_ancestry", "ansich_task_spawns"):
        if inspector.has_table(table_name):
            op.drop_table(table_name)

    contribution_columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("ansich_usage_contributions")}
    if "aggregate_task_id" in contribution_columns and "task_id" not in contribution_columns:
        op.execute(sa.text("DELETE FROM ansich_usage_contributions WHERE aggregate_task_id <> source_task_id"))
        op.execute(sa.text("DELETE FROM ansich_task_usage WHERE aggregation_scope = 'inclusive'"))
        with op.batch_alter_table("ansich_usage_contributions") as batch:
            batch.alter_column(
                "aggregate_task_id",
                new_column_name="task_id",
                existing_type=sa.String(length=36),
                existing_nullable=False,
            )
    if "uq_ansich_tool_call_entity_step_task" in _unique_names("ansich_tool_calls"):
        with op.batch_alter_table("ansich_tool_calls") as batch:
            batch.drop_constraint(
                "uq_ansich_tool_call_entity_step_task",
                type_="unique",
            )
    if "uq_ansich_step_entity_task" in _unique_names("ansich_steps"):
        with op.batch_alter_table("ansich_steps") as batch:
            batch.drop_constraint("uq_ansich_step_entity_task", type_="unique")
