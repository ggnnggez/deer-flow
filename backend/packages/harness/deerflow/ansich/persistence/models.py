from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.persistence.base import Base


def _utc_now() -> datetime:
    return datetime.now(UTC)


class AnsichPayloadRow(Base):
    __tablename__ = "ansich_payloads"

    payload_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    encoding: Mapped[str] = mapped_column(String(32), nullable=False)
    compression: Mapped[str] = mapped_column(String(32), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    body: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now)


class AnsichObservationRow(Base):
    __tablename__ = "ansich_observations"

    ingest_seq: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    obs_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    task_id: Mapped[str] = mapped_column(String(36), nullable=False)
    subject_type: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(36), nullable=False)
    fidelity_class: Mapped[str] = mapped_column(String(16), nullable=False)
    producer_name: Mapped[str] = mapped_column(String(128), nullable=False)
    producer_version: Mapped[str] = mapped_column(String(32), nullable=False)
    producer_instance_id: Mapped[str] = mapped_column(String(128), nullable=False)
    producer_seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_event_id: Mapped[str] = mapped_column(String(256), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    causation_obs_id: Mapped[str | None] = mapped_column(String(36))
    payload_json: Mapped[dict | None] = mapped_column(JSON(none_as_null=True))
    payload_ref_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("ansich_payloads.payload_id", ondelete="RESTRICT"),
    )

    __table_args__ = (
        CheckConstraint(
            "(payload_json IS NOT NULL AND payload_ref_id IS NULL) OR (payload_json IS NULL AND payload_ref_id IS NOT NULL)",
            name="ck_ansich_observation_payload_one_of",
        ),
        UniqueConstraint("producer_name", "producer_instance_id", "source_event_id", name="uq_ansich_observation_source"),
        Index("ix_ansich_observations_task_ingest", "task_id", "ingest_seq"),
        Index("ix_ansich_observations_kind_occurred", "kind", "occurred_at"),
    )


class AnsichProjectionJobRow(Base):
    __tablename__ = "ansich_projection_jobs"

    job_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    obs_id: Mapped[str] = mapped_column(String(36), ForeignKey("ansich_observations.obs_id", ondelete="CASCADE"), nullable=False)
    projector_name: Mapped[str] = mapped_column(String(64), nullable=False)
    projector_version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now)
    lease_owner: Mapped[str | None] = mapped_column(String(128))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("obs_id", "projector_name", "projector_version", name="uq_ansich_projection_job_version"),
        Index("ix_ansich_projection_jobs_claim", "status", "available_at", "lease_expires_at"),
    )


class AnsichProjectionErrorRow(Base):
    __tablename__ = "ansich_projection_errors"

    error_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("ansich_projection_jobs.job_id", ondelete="CASCADE"),
        nullable=False,
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    error_type: Mapped[str] = mapped_column(String(128), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now)


class AnsichProjectorVersionRow(Base):
    __tablename__ = "ansich_projector_versions"

    projector_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    projector_version: Mapped[str] = mapped_column(String(32), primary_key=True)
    installed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now)


class AnsichEntityRow(Base):
    __tablename__ = "ansich_entities"

    entity_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    discovered_obs_id: Mapped[str] = mapped_column(String(36), ForeignKey("ansich_observations.obs_id"), nullable=False)


class AnsichTaskRow(Base):
    __tablename__ = "ansich_tasks"

    entity_id: Mapped[str] = mapped_column(String(36), ForeignKey("ansich_entities.entity_id", ondelete="CASCADE"), primary_key=True)
    source_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    source_id: Mapped[str] = mapped_column(String(128), nullable=False)
    trigger_obs_id: Mapped[str] = mapped_column(String(36), ForeignKey("ansich_observations.obs_id"), nullable=False)

    __table_args__ = (UniqueConstraint("source_kind", "source_id", name="uq_ansich_task_source"),)


class AnsichScopeRow(Base):
    __tablename__ = "ansich_scopes"

    entity_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("ansich_entities.entity_id", ondelete="CASCADE"),
        primary_key=True,
    )
    scope_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    scope_value: Mapped[str] = mapped_column(String(256), nullable=False)

    __table_args__ = (UniqueConstraint("scope_kind", "scope_value", name="uq_ansich_scope_kind_value"),)


class AnsichRelationRow(Base):
    __tablename__ = "ansich_relations"

    relation_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    subject_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("ansich_entities.entity_id", ondelete="CASCADE"),
        nullable=False,
    )
    predicate: Mapped[str] = mapped_column(String(64), nullable=False)
    object_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("ansich_entities.entity_id", ondelete="CASCADE"),
        nullable=False,
    )
    asserted_obs_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("ansich_observations.obs_id", ondelete="RESTRICT"),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("subject_id", "predicate", "object_id", name="uq_ansich_relation_edge"),
        Index("ix_ansich_relations_subject_predicate", "subject_id", "predicate"),
        Index("ix_ansich_relations_object_predicate", "object_id", "predicate"),
    )


class AnsichRelationEvidenceRow(Base):
    __tablename__ = "ansich_relation_evidence"

    relation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("ansich_relations.relation_id", ondelete="CASCADE"),
        primary_key=True,
    )
    obs_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("ansich_observations.obs_id", ondelete="CASCADE"),
        primary_key=True,
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class AnsichBeliefAssertionRow(Base):
    __tablename__ = "ansich_belief_assertions"

    assertion_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    subject_id: Mapped[str] = mapped_column(String(36), ForeignKey("ansich_entities.entity_id", ondelete="CASCADE"), nullable=False)
    field_name: Mapped[str] = mapped_column(String(64), nullable=False)
    value_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    asserted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_name: Mapped[str] = mapped_column(String(64), nullable=False)
    source_version: Mapped[str] = mapped_column(String(32), nullable=False)
    fidelity_class: Mapped[str] = mapped_column(String(16), nullable=False)


class AnsichCurrentBeliefRow(Base):
    __tablename__ = "ansich_current_beliefs"

    subject_id: Mapped[str] = mapped_column(String(36), ForeignKey("ansich_entities.entity_id", ondelete="CASCADE"), primary_key=True)
    field_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    assertion_id: Mapped[str] = mapped_column(String(36), ForeignKey("ansich_belief_assertions.assertion_id", ondelete="CASCADE"), nullable=False)
    resolver_name: Mapped[str] = mapped_column(String(64), nullable=False)
    resolver_version: Mapped[str] = mapped_column(String(32), nullable=False)


class AnsichBeliefEvidenceRow(Base):
    __tablename__ = "ansich_belief_evidence"

    assertion_id: Mapped[str] = mapped_column(String(36), ForeignKey("ansich_belief_assertions.assertion_id", ondelete="CASCADE"), primary_key=True)
    obs_id: Mapped[str] = mapped_column(String(36), ForeignKey("ansich_observations.obs_id", ondelete="CASCADE"), primary_key=True)
    evidence_role: Mapped[str] = mapped_column(String(32), nullable=False, default="supporting")
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class AnsichTransitionRow(Base):
    __tablename__ = "ansich_transitions"

    transition_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    subject_id: Mapped[str] = mapped_column(String(36), ForeignKey("ansich_entities.entity_id", ondelete="CASCADE"), nullable=False)
    field_name: Mapped[str] = mapped_column(String(64), nullable=False)
    from_value: Mapped[str] = mapped_column(String(32), nullable=False)
    to_value: Mapped[str] = mapped_column(String(32), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evidence_obs_id: Mapped[str] = mapped_column(String(36), ForeignKey("ansich_observations.obs_id"), nullable=False, unique=True)


class AnsichTaskSummaryRow(Base):
    __tablename__ = "ansich_task_summaries"

    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("ansich_tasks.entity_id", ondelete="CASCADE"), primary_key=True)
    source_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    source_id: Mapped[str] = mapped_column(String(128), nullable=False)
    control_value: Mapped[str] = mapped_column(String(32), nullable=False)
    control_as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_evidence_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    assertion_id: Mapped[str] = mapped_column(String(36), ForeignKey("ansich_belief_assertions.assertion_id"), nullable=False)
    projection_watermark: Mapped[int] = mapped_column(BigInteger, nullable=False)
    observability_status: Mapped[str] = mapped_column(String(16), nullable=False, default="healthy")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now)

    __table_args__ = (Index("ix_ansich_task_summaries_control_evidence", "control_value", "last_evidence_at"),)
