"""Ansich Task observation and control projection core.

Revision ID: 0006_ansich_task_core
Revises: 0005_run_stop_reason, 0005_ansich_task_core
Create Date: 2026-07-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_ansich_task_core"
down_revision: str | Sequence[str] | None = (
    "0005_run_stop_reason",
    "0005_ansich_task_core",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _create_table(name: str, *elements: sa.SchemaItem) -> None:
    """Create a Phase 1 table unless legacy create_all already backfilled it."""

    if not sa.inspect(op.get_bind()).has_table(name):
        op.create_table(name, *elements)


def _create_index(name: str, table_name: str, columns: list[str], *, unique: bool) -> None:
    inspector = sa.inspect(op.get_bind())
    existing = {index["name"] for index in inspector.get_indexes(table_name)}
    if name not in existing:
        op.create_index(name, table_name, columns, unique=unique)


def upgrade() -> None:
    _create_table(
        "ansich_payloads",
        sa.Column("payload_id", sa.String(length=36), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("encoding", sa.String(length=32), nullable=False),
        sa.Column("compression", sa.String(length=32), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("body", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("payload_id"),
    )
    _create_table(
        "ansich_observations",
        sa.Column("ingest_seq", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), autoincrement=True, nullable=False),
        sa.Column("obs_id", sa.String(length=36), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("subject_type", sa.String(length=32), nullable=False),
        sa.Column("subject_id", sa.String(length=36), nullable=False),
        sa.Column("fidelity_class", sa.String(length=16), nullable=False),
        sa.Column("producer_name", sa.String(length=128), nullable=False),
        sa.Column("producer_version", sa.String(length=32), nullable=False),
        sa.Column("producer_instance_id", sa.String(length=128), nullable=False),
        sa.Column("producer_seq", sa.BigInteger(), nullable=False),
        sa.Column("source_event_id", sa.String(length=256), nullable=False),
        sa.Column("correlation_id", sa.String(length=128), nullable=False),
        sa.Column("causation_obs_id", sa.String(length=36), nullable=True),
        sa.Column("payload_json", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("payload_ref_id", sa.String(length=36), nullable=True),
        sa.CheckConstraint(
            "(payload_json IS NOT NULL AND payload_ref_id IS NULL) OR (payload_json IS NULL AND payload_ref_id IS NOT NULL)",
            name="ck_ansich_observation_payload_one_of",
        ),
        sa.ForeignKeyConstraint(["payload_ref_id"], ["ansich_payloads.payload_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("ingest_seq"),
        sa.UniqueConstraint("obs_id"),
        sa.UniqueConstraint("producer_name", "producer_instance_id", "source_event_id", name="uq_ansich_observation_source"),
    )
    _create_index("ix_ansich_observations_kind_occurred", "ansich_observations", ["kind", "occurred_at"], unique=False)
    _create_index("ix_ansich_observations_task_ingest", "ansich_observations", ["task_id", "ingest_seq"], unique=False)

    _create_table(
        "ansich_entities",
        sa.Column("entity_id", sa.String(length=36), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("discovered_obs_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(["discovered_obs_id"], ["ansich_observations.obs_id"]),
        sa.PrimaryKeyConstraint("entity_id"),
    )
    _create_table(
        "ansich_tasks",
        sa.Column("entity_id", sa.String(length=36), nullable=False),
        sa.Column("source_kind", sa.String(length=64), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("trigger_obs_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(["entity_id"], ["ansich_entities.entity_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["trigger_obs_id"], ["ansich_observations.obs_id"]),
        sa.PrimaryKeyConstraint("entity_id"),
        sa.UniqueConstraint("source_kind", "source_id", name="uq_ansich_task_source"),
    )
    _create_table(
        "ansich_scopes",
        sa.Column("entity_id", sa.String(length=36), nullable=False),
        sa.Column("scope_kind", sa.String(length=32), nullable=False),
        sa.Column("scope_value", sa.String(length=256), nullable=False),
        sa.ForeignKeyConstraint(["entity_id"], ["ansich_entities.entity_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("entity_id"),
        sa.UniqueConstraint("scope_kind", "scope_value", name="uq_ansich_scope_kind_value"),
    )
    _create_table(
        "ansich_relations",
        sa.Column("relation_id", sa.String(length=36), nullable=False),
        sa.Column("subject_id", sa.String(length=36), nullable=False),
        sa.Column("predicate", sa.String(length=64), nullable=False),
        sa.Column("object_id", sa.String(length=36), nullable=False),
        sa.Column("asserted_obs_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(["asserted_obs_id"], ["ansich_observations.obs_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["object_id"], ["ansich_entities.entity_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["subject_id"], ["ansich_entities.entity_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("relation_id"),
        sa.UniqueConstraint("subject_id", "predicate", "object_id", name="uq_ansich_relation_edge"),
    )
    _create_index(
        "ix_ansich_relations_subject_predicate",
        "ansich_relations",
        ["subject_id", "predicate"],
        unique=False,
    )
    _create_index(
        "ix_ansich_relations_object_predicate",
        "ansich_relations",
        ["object_id", "predicate"],
        unique=False,
    )
    _create_table(
        "ansich_relation_evidence",
        sa.Column("relation_id", sa.String(length=36), nullable=False),
        sa.Column("obs_id", sa.String(length=36), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["obs_id"], ["ansich_observations.obs_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["relation_id"], ["ansich_relations.relation_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("relation_id", "obs_id"),
    )
    _create_table(
        "ansich_belief_assertions",
        sa.Column("assertion_id", sa.String(length=36), nullable=False),
        sa.Column("subject_id", sa.String(length=36), nullable=False),
        sa.Column("field_name", sa.String(length=64), nullable=False),
        sa.Column("value_json", sa.JSON(), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("asserted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_name", sa.String(length=64), nullable=False),
        sa.Column("source_version", sa.String(length=32), nullable=False),
        sa.Column("fidelity_class", sa.String(length=16), nullable=False),
        sa.ForeignKeyConstraint(["subject_id"], ["ansich_entities.entity_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("assertion_id"),
    )
    _create_table(
        "ansich_belief_evidence",
        sa.Column("assertion_id", sa.String(length=36), nullable=False),
        sa.Column("obs_id", sa.String(length=36), nullable=False),
        sa.Column("evidence_role", sa.String(length=32), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["assertion_id"], ["ansich_belief_assertions.assertion_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["obs_id"], ["ansich_observations.obs_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("assertion_id", "obs_id"),
    )
    _create_table(
        "ansich_current_beliefs",
        sa.Column("subject_id", sa.String(length=36), nullable=False),
        sa.Column("field_name", sa.String(length=64), nullable=False),
        sa.Column("assertion_id", sa.String(length=36), nullable=False),
        sa.Column("resolver_name", sa.String(length=64), nullable=False),
        sa.Column("resolver_version", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(["assertion_id"], ["ansich_belief_assertions.assertion_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["subject_id"], ["ansich_entities.entity_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("subject_id", "field_name"),
    )
    _create_table(
        "ansich_projector_versions",
        sa.Column("projector_name", sa.String(length=64), nullable=False),
        sa.Column("projector_version", sa.String(length=32), nullable=False),
        sa.Column("installed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("projector_name", "projector_version"),
    )
    _create_table(
        "ansich_projection_jobs",
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("obs_id", sa.String(length=36), nullable=False),
        sa.Column("projector_name", sa.String(length=64), nullable=False),
        sa.Column("projector_version", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["obs_id"], ["ansich_observations.obs_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("job_id"),
        sa.UniqueConstraint("obs_id", "projector_name", "projector_version", name="uq_ansich_projection_job_version"),
    )
    _create_index(
        "ix_ansich_projection_jobs_claim",
        "ansich_projection_jobs",
        ["status", "available_at", "lease_expires_at"],
        unique=False,
    )
    _create_table(
        "ansich_projection_errors",
        sa.Column("error_id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("error_type", sa.String(length=128), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["ansich_projection_jobs.job_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("error_id"),
    )
    _create_table(
        "ansich_transitions",
        sa.Column("transition_id", sa.String(length=36), nullable=False),
        sa.Column("subject_id", sa.String(length=36), nullable=False),
        sa.Column("field_name", sa.String(length=64), nullable=False),
        sa.Column("from_value", sa.String(length=32), nullable=False),
        sa.Column("to_value", sa.String(length=32), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence_obs_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(["evidence_obs_id"], ["ansich_observations.obs_id"]),
        sa.ForeignKeyConstraint(["subject_id"], ["ansich_entities.entity_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("transition_id"),
        sa.UniqueConstraint("evidence_obs_id"),
    )
    _create_table(
        "ansich_task_summaries",
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("source_kind", sa.String(length=64), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("control_value", sa.String(length=32), nullable=False),
        sa.Column("control_as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_evidence_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("assertion_id", sa.String(length=36), nullable=False),
        sa.Column("projection_watermark", sa.BigInteger(), nullable=False),
        sa.Column("observability_status", sa.String(length=16), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["assertion_id"], ["ansich_belief_assertions.assertion_id"]),
        sa.ForeignKeyConstraint(["task_id"], ["ansich_tasks.entity_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("task_id"),
    )
    _create_index(
        "ix_ansich_task_summaries_control_evidence",
        "ansich_task_summaries",
        ["control_value", "last_evidence_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_ansich_task_summaries_control_evidence", table_name="ansich_task_summaries")
    op.drop_table("ansich_task_summaries")
    op.drop_table("ansich_transitions")
    op.drop_table("ansich_projection_errors")
    op.drop_index("ix_ansich_projection_jobs_claim", table_name="ansich_projection_jobs")
    op.drop_table("ansich_projection_jobs")
    op.drop_table("ansich_projector_versions")
    op.drop_table("ansich_current_beliefs")
    op.drop_table("ansich_belief_evidence")
    op.drop_table("ansich_belief_assertions")
    op.drop_table("ansich_relation_evidence")
    op.drop_index("ix_ansich_relations_object_predicate", table_name="ansich_relations")
    op.drop_index("ix_ansich_relations_subject_predicate", table_name="ansich_relations")
    op.drop_table("ansich_relations")
    op.drop_table("ansich_scopes")
    op.drop_table("ansich_tasks")
    op.drop_table("ansich_entities")
    op.drop_index("ix_ansich_observations_task_ingest", table_name="ansich_observations")
    op.drop_index("ix_ansich_observations_kind_occurred", table_name="ansich_observations")
    op.drop_table("ansich_observations")
    op.drop_table("ansich_payloads")
