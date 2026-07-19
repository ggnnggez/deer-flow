"""Add immutable AgentRelease manifests and Task starting-release bindings.

Revision ID: 0018_ansich_agent_releases
Revises: 0017_ansich_alerts
Create Date: 2026-07-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_ansich_agent_releases"
down_revision: str | Sequence[str] | None = "0017_ansich_alerts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


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
    _create_table(
        "ansich_agent_releases",
        sa.Column("entity_id", sa.String(36), nullable=False),
        sa.Column("namespace", sa.String(128), nullable=False),
        sa.Column("agent_name", sa.String(128), nullable=False),
        sa.Column("release_hash", sa.String(64), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("model_hash", sa.String(64), nullable=False),
        sa.Column("prompt_hash", sa.String(64), nullable=False),
        sa.Column("tool_catalog_hash", sa.String(64), nullable=False),
        sa.Column("policy_hash", sa.String(64), nullable=False),
        sa.Column("runtime_build_id", sa.String(64), nullable=False),
        sa.Column("manifest_payload_id", sa.String(36), nullable=False),
        sa.Column("discovered_obs_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["entity_id"],
            ["ansich_entities.entity_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["manifest_payload_id"],
            ["ansich_payloads.payload_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["discovered_obs_id"],
            ["ansich_observations.obs_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("entity_id"),
        sa.UniqueConstraint(
            "namespace",
            "agent_name",
            "release_hash",
            name="uq_ansich_agent_release_identity",
        ),
    )
    _create_index(
        "ix_ansich_agent_releases_agent_created",
        "ansich_agent_releases",
        ["agent_name", "created_at"],
    )
    for name, column in (
        ("ix_ansich_agent_releases_model_hash", "model_hash"),
        ("ix_ansich_agent_releases_prompt_hash", "prompt_hash"),
        ("ix_ansich_agent_releases_tool_hash", "tool_catalog_hash"),
        ("ix_ansich_agent_releases_policy_hash", "policy_hash"),
        ("ix_ansich_agent_releases_runtime_build", "runtime_build_id"),
    ):
        _create_index(name, "ansich_agent_releases", [column])
    _create_table(
        "ansich_agent_release_components",
        sa.Column("release_id", sa.String(36), nullable=False),
        sa.Column("component_kind", sa.String(32), nullable=False),
        sa.Column("component_hash", sa.String(64), nullable=False),
        sa.Column("summary_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["release_id"],
            ["ansich_agent_releases.entity_id"],
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "component_kind IN ('model', 'prompt', 'tools', 'policy', 'runtime_build')",
            name="ck_ansich_agent_release_component_kind",
        ),
        sa.PrimaryKeyConstraint("release_id", "component_kind"),
    )
    _create_index(
        "ix_ansich_agent_release_components_hash",
        "ansich_agent_release_components",
        ["component_kind", "component_hash"],
    )
    _create_table(
        "ansich_task_agent_releases",
        sa.Column("task_id", sa.String(36), nullable=False),
        sa.Column("release_id", sa.String(36), nullable=False),
        sa.Column("relation_role", sa.String(32), nullable=False),
        sa.Column("established_obs_id", sa.String(36), nullable=False),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["ansich_tasks.entity_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["release_id"],
            ["ansich_agent_releases.entity_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["established_obs_id"],
            ["ansich_observations.obs_id"],
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "relation_role = 'executed_by'",
            name="ck_ansich_task_agent_release_role",
        ),
        sa.PrimaryKeyConstraint("task_id"),
    )
    _create_index(
        "ix_ansich_task_agent_releases_release",
        "ansich_task_agent_releases",
        ["release_id", "task_id"],
    )


def downgrade() -> None:
    for table_name in (
        "ansich_task_agent_releases",
        "ansich_agent_release_components",
        "ansich_agent_releases",
    ):
        if sa.inspect(op.get_bind()).has_table(table_name):
            op.drop_table(table_name)
