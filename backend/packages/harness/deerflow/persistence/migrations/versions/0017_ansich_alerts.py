"""Add Ansich Phase 6 assessors, Alerts, and operator audit projections.

Revision ID: 0017_ansich_alerts
Revises: 0016_ansich_operations
Create Date: 2026-07-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_ansich_alerts"
down_revision: str | Sequence[str] | None = "0016_ansich_operations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LEGACY_CONFIG_HASH = "c49fea7425fa7f8699897a97c159c6690267d9003bb78c53bbbf8b384ce23c98"


def _create_table(name: str, *elements: sa.SchemaItem) -> None:
    if not sa.inspect(op.get_bind()).has_table(name):
        op.create_table(name, *elements)


def _create_index(
    name: str,
    table_name: str,
    columns: list[str],
) -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table_name):
        return
    if name not in {index["name"] for index in inspector.get_indexes(table_name)}:
        op.create_index(name, table_name, columns, unique=False)


def _extend_belief_assertions() -> None:
    existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("ansich_belief_assertions")}
    definitions = {
        "assessor_name": sa.Column("assessor_name", sa.String(64)),
        "assessor_version": sa.Column("assessor_version", sa.String(32)),
        "config_hash": sa.Column("config_hash", sa.String(64)),
        "authority_class": sa.Column("authority_class", sa.String(32)),
        "confidence": sa.Column("confidence", sa.Float()),
    }
    with op.batch_alter_table("ansich_belief_assertions") as batch:
        for name, column in definitions.items():
            if name not in existing:
                batch.add_column(column)

    assertions = sa.table(
        "ansich_belief_assertions",
        sa.column("source_name", sa.String),
        sa.column("source_version", sa.String),
        sa.column("fidelity_class", sa.String),
        sa.column("assessor_name", sa.String),
        sa.column("assessor_version", sa.String),
        sa.column("config_hash", sa.String),
        sa.column("authority_class", sa.String),
    )
    op.execute(
        assertions.update().values(
            assessor_name=assertions.c.source_name,
            assessor_version=assertions.c.source_version,
            config_hash=_LEGACY_CONFIG_HASH,
            authority_class=sa.case(
                (assertions.c.fidelity_class == "hard", "deterministic"),
                (
                    assertions.c.fidelity_class == "rule",
                    "configured_rule",
                ),
                else_="automated",
            ),
        )
    )
    with op.batch_alter_table("ansich_belief_assertions") as batch:
        for name, column_type in (
            ("assessor_name", sa.String(64)),
            ("assessor_version", sa.String(32)),
            ("config_hash", sa.String(64)),
            ("authority_class", sa.String(32)),
        ):
            batch.alter_column(
                name,
                existing_type=column_type,
                nullable=False,
            )


def upgrade() -> None:
    _extend_belief_assertions()
    _create_table(
        "ansich_assessor_jobs",
        sa.Column("job_id", sa.String(36), nullable=False),
        sa.Column("subject_id", sa.String(36), nullable=False),
        sa.Column("assessor_name", sa.String(64), nullable=False),
        sa.Column("assessor_version", sa.String(32), nullable=False),
        sa.Column("evidence_watermark", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_owner", sa.String(128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["subject_id"],
            ["ansich_tasks.entity_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("job_id"),
        sa.UniqueConstraint(
            "subject_id",
            "assessor_name",
            "assessor_version",
            "evidence_watermark",
            name="uq_ansich_assessor_job_watermark",
        ),
    )
    _create_index(
        "ix_ansich_assessor_jobs_claim",
        "ansich_assessor_jobs",
        ["status", "available_at", "lease_expires_at"],
    )
    _create_table(
        "ansich_assessor_errors",
        sa.Column("error_id", sa.String(36), nullable=False),
        sa.Column("job_id", sa.String(36), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("error_type", sa.String(128), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["ansich_assessor_jobs.job_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("error_id"),
    )
    _create_table(
        "ansich_alerts",
        sa.Column("entity_id", sa.String(36), nullable=False),
        sa.Column("alert_key", sa.String(64), nullable=False),
        sa.Column("episode", sa.Integer(), nullable=False),
        sa.Column("alert_type", sa.String(32), nullable=False),
        sa.Column("subject_id", sa.String(36), nullable=False),
        sa.Column("source_assertion_id", sa.String(36), nullable=False),
        sa.Column("rule_name", sa.String(64), nullable=False),
        sa.Column("rule_version", sa.String(32), nullable=False),
        sa.Column("rule_config_hash", sa.String(64), nullable=False),
        sa.Column("stable_condition_key", sa.String(256), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("shadow", sa.Boolean(), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_reason", sa.String(64), nullable=True),
        sa.Column("workflow_state", sa.String(16), nullable=False),
        sa.Column("workflow_version", sa.Integer(), nullable=False),
        sa.Column("dismissal_reason", sa.String(512), nullable=True),
        sa.ForeignKeyConstraint(
            ["entity_id"],
            ["ansich_entities.entity_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_assertion_id"],
            ["ansich_belief_assertions.assertion_id"],
        ),
        sa.ForeignKeyConstraint(
            ["subject_id"],
            ["ansich_entities.entity_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("entity_id"),
        sa.UniqueConstraint(
            "alert_key",
            "episode",
            name="uq_ansich_alert_episode",
        ),
    )
    _create_index(
        "ix_ansich_alerts_workflow_updated",
        "ansich_alerts",
        ["workflow_state", "updated_at"],
    )
    _create_index(
        "ix_ansich_alerts_subject_type",
        "ansich_alerts",
        ["subject_id", "alert_type"],
    )
    _create_table(
        "ansich_alert_evidence",
        sa.Column("alert_id", sa.String(36), nullable=False),
        sa.Column("obs_id", sa.String(36), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["alert_id"],
            ["ansich_alerts.entity_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["obs_id"],
            ["ansich_observations.obs_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("alert_id", "obs_id"),
        sa.UniqueConstraint(
            "alert_id",
            "ordinal",
            name="uq_ansich_alert_evidence_ordinal",
        ),
    )
    _create_table(
        "ansich_alert_workflow_events",
        sa.Column("event_id", sa.String(36), nullable=False),
        sa.Column("alert_id", sa.String(36), nullable=False),
        sa.Column("obs_id", sa.String(36), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("from_state", sa.String(16), nullable=False),
        sa.Column("to_state", sa.String(16), nullable=False),
        sa.Column("workflow_version", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(512), nullable=True),
        sa.Column("operator_id", sa.String(256), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["alert_id"],
            ["ansich_alerts.entity_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["obs_id"],
            ["ansich_observations.obs_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("event_id"),
        sa.UniqueConstraint("obs_id"),
    )
    _create_index(
        "ix_ansich_alert_workflow_history",
        "ansich_alert_workflow_events",
        ["alert_id", "workflow_version"],
    )
    _create_table(
        "ansich_alert_read_model",
        sa.Column("alert_id", sa.String(36), nullable=False),
        sa.Column("subject_id", sa.String(36), nullable=False),
        sa.Column("alert_type", sa.String(32), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("workflow_state", sa.String(16), nullable=False),
        sa.Column("shadow", sa.Boolean(), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("summary_json", sa.JSON(), nullable=False),
        sa.Column("evidence_count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["alert_id"],
            ["ansich_alerts.entity_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("alert_id"),
    )
    _create_index(
        "ix_ansich_alert_read_filters",
        "ansich_alert_read_model",
        ["workflow_state", "severity", "alert_type", "updated_at"],
    )
    _create_index(
        "ix_ansich_alert_read_subject",
        "ansich_alert_read_model",
        ["subject_id", "updated_at"],
    )
    _create_table(
        "ansich_operator_actions",
        sa.Column("action_id", sa.String(36), nullable=False),
        sa.Column("task_id", sa.String(36), nullable=False),
        sa.Column("action_type", sa.String(32), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("requested_obs_id", sa.String(36), nullable=True),
        sa.Column("terminal_obs_id", sa.String(36), nullable=True),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["requested_obs_id"],
            ["ansich_observations.obs_id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["ansich_tasks.entity_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["terminal_obs_id"],
            ["ansich_observations.obs_id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("action_id"),
        sa.UniqueConstraint(
            "task_id",
            "action_type",
            "idempotency_key",
            name="uq_ansich_operator_action_idempotency",
        ),
    )
    _create_index(
        "ix_ansich_operator_actions_task_updated",
        "ansich_operator_actions",
        ["task_id", "updated_at"],
    )


def downgrade() -> None:
    for table_name in (
        "ansich_operator_actions",
        "ansich_alert_read_model",
        "ansich_alert_workflow_events",
        "ansich_alert_evidence",
        "ansich_alerts",
        "ansich_assessor_errors",
        "ansich_assessor_jobs",
    ):
        if sa.inspect(op.get_bind()).has_table(table_name):
            op.drop_table(table_name)
    existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("ansich_belief_assertions")}
    with op.batch_alter_table("ansich_belief_assertions") as batch:
        for name in (
            "confidence",
            "authority_class",
            "config_hash",
            "assessor_version",
            "assessor_name",
        ):
            if name in existing:
                batch.drop_column(name)
