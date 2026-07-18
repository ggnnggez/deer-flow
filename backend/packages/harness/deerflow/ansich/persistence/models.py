from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
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
    step_id: Mapped[str | None] = mapped_column(String(36))
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
    dependency_pending_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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


class AnsichStepRow(Base):
    __tablename__ = "ansich_steps"

    entity_id: Mapped[str] = mapped_column(String(36), ForeignKey("ansich_entities.entity_id", ondelete="CASCADE"), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("ansich_tasks.entity_id", ondelete="CASCADE"), nullable=False)
    step_seq: Mapped[int] = mapped_column(Integer, nullable=False)
    actor_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="deciding")
    result: Mapped[str | None] = mapped_column(String(32))
    started_obs_id: Mapped[str] = mapped_column(String(36), ForeignKey("ansich_observations.obs_id"), nullable=False)
    closed_obs_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("ansich_observations.obs_id"))
    effective_attempt_no: Mapped[int | None] = mapped_column(Integer)
    effective_context_snapshot_id: Mapped[str | None] = mapped_column(String(36))
    issued_tools_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    __table_args__ = (
        UniqueConstraint("task_id", "step_seq", name="uq_ansich_step_task_seq"),
        Index("ix_ansich_steps_task_seq", "task_id", "step_seq"),
    )


class AnsichLlmAttemptRow(Base):
    __tablename__ = "ansich_llm_attempts"

    attempt_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    step_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("ansich_steps.entity_id", ondelete="CASCADE"))
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("ansich_tasks.entity_id", ondelete="CASCADE"), nullable=False)
    actor_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    operation_id: Mapped[str | None] = mapped_column(String(36))
    operation_kind: Mapped[str | None] = mapped_column(String(32))
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="requested")
    request_obs_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("ansich_observations.obs_id"), unique=True)
    response_obs_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("ansich_observations.obs_id"), unique=True)
    failure_obs_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("ansich_observations.obs_id"), unique=True)
    provider_model: Mapped[str | None] = mapped_column(String(256))
    usage_json: Mapped[dict | None] = mapped_column(JSON)
    response_metadata_json: Mapped[dict | None] = mapped_column(JSON)
    latency_ms: Mapped[int | None] = mapped_column(BigInteger)
    context_snapshot_id: Mapped[str | None] = mapped_column(String(36))

    __table_args__ = (
        UniqueConstraint("step_id", "attempt_no", name="uq_ansich_llm_attempt_step_no"),
        UniqueConstraint("task_id", "operation_id", "attempt_no", name="uq_ansich_llm_attempt_operation_no"),
        Index("ix_ansich_llm_attempts_step_no", "step_id", "attempt_no"),
        Index("ix_ansich_llm_attempts_task_request", "task_id", "request_obs_id"),
    )


class AnsichContentBlockRow(Base):
    __tablename__ = "ansich_content_blocks"

    entity_id: Mapped[str] = mapped_column(String(36), ForeignKey("ansich_entities.entity_id", ondelete="CASCADE"), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_obs_id: Mapped[str] = mapped_column(String(36), ForeignKey("ansich_observations.obs_id"), nullable=False)
    producer_obs_id: Mapped[str] = mapped_column(String(36), ForeignKey("ansich_observations.obs_id"), nullable=False, unique=True)
    blob_key: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("ansich_content_blobs.blob_key", ondelete="RESTRICT", name="fk_ansich_content_blocks_blob_key"),
    )
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    token_estimate: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sensitivity_flags_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    __table_args__ = (
        Index("ix_ansich_content_blocks_hash", "content_hash"),
        Index("ix_ansich_content_blocks_blob", "blob_key"),
    )


class AnsichContentBlobRow(Base):
    __tablename__ = "ansich_content_blobs"

    blob_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_type: Mapped[str] = mapped_column(String(64), nullable=False)
    canonicalization_version: Mapped[str] = mapped_column(String(16), nullable=False)
    payload_status: Mapped[str] = mapped_column(String(16), nullable=False, default="available", server_default="available")
    inline_body: Mapped[bytes | None] = mapped_column(LargeBinary)
    payload_ref_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("ansich_payloads.payload_id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now)

    __table_args__ = (
        CheckConstraint(
            "(inline_body IS NOT NULL AND payload_ref_id IS NULL) OR (inline_body IS NULL AND payload_ref_id IS NOT NULL)",
            name="ck_ansich_content_blob_payload_one_of",
        ),
        UniqueConstraint(
            "content_hash",
            "byte_size",
            "content_type",
            "canonicalization_version",
            name="uq_ansich_content_blob_value",
        ),
    )


class AnsichContentOccurrenceRow(Base):
    __tablename__ = "ansich_content_occurrences"

    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("ansich_tasks.entity_id", ondelete="CASCADE"), primary_key=True)
    source_identity: Mapped[str] = mapped_column(String(512), primary_key=True)
    content_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), primary_key=True)
    block_id: Mapped[str] = mapped_column(String(36), ForeignKey("ansich_content_blocks.entity_id", ondelete="RESTRICT"), nullable=False, unique=True)
    producer_obs_id: Mapped[str] = mapped_column(String(36), ForeignKey("ansich_observations.obs_id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now)

    __table_args__ = (
        Index("ix_ansich_content_occurrences_task_source", "task_id", "source_identity"),
        Index("ix_ansich_content_occurrences_block", "block_id"),
    )


class AnsichToolCallRow(Base):
    __tablename__ = "ansich_tool_calls"

    entity_id: Mapped[str] = mapped_column(String(36), ForeignKey("ansich_entities.entity_id", ondelete="CASCADE"), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("ansich_tasks.entity_id", ondelete="CASCADE"), nullable=False)
    step_id: Mapped[str] = mapped_column(String(36), ForeignKey("ansich_steps.entity_id", ondelete="CASCADE"), nullable=False)
    call_seq: Mapped[int] = mapped_column(Integer, nullable=False)
    provider_call_id: Mapped[str | None] = mapped_column(String(256))
    tool_name: Mapped[str] = mapped_column(String(256), nullable=False, default="unknown")
    args_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    args_preview_json: Mapped[object | None] = mapped_column(JSON)
    tool_schema_block_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("ansich_content_blocks.entity_id", ondelete="SET NULL"))
    issued_obs_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("ansich_observations.obs_id", ondelete="RESTRICT"), unique=True)
    started_obs_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("ansich_observations.obs_id", ondelete="RESTRICT"), unique=True)
    raw_terminal_obs_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("ansich_observations.obs_id", ondelete="RESTRICT"), unique=True)
    visible_result_obs_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("ansich_observations.obs_id", ondelete="RESTRICT"), unique=True)
    execution_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    visible_result_status: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    duration_ms: Mapped[int | None] = mapped_column(BigInteger)

    __table_args__ = (
        UniqueConstraint("step_id", "call_seq", name="uq_ansich_tool_call_step_seq"),
        Index("ix_ansich_tool_calls_step_seq", "step_id", "call_seq"),
        Index("ix_ansich_tool_calls_provider", "provider_call_id"),
        Index("ix_ansich_tool_calls_name_issued", "tool_name", "issued_obs_id"),
    )


class AnsichToolCallResultRow(Base):
    __tablename__ = "ansich_tool_call_results"

    tool_call_id: Mapped[str] = mapped_column(String(36), ForeignKey("ansich_tool_calls.entity_id", ondelete="CASCADE"), primary_key=True)
    result_role: Mapped[str] = mapped_column(String(16), primary_key=True)
    source_obs_id: Mapped[str] = mapped_column(String(36), ForeignKey("ansich_observations.obs_id", ondelete="RESTRICT"), primary_key=True)
    content_block_id: Mapped[str] = mapped_column(String(36), ForeignKey("ansich_content_blocks.entity_id", ondelete="RESTRICT"), nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    __table_args__ = (Index("ix_ansich_tool_call_results_block", "content_block_id"),)


class AnsichContentBlockDerivationRow(Base):
    __tablename__ = "ansich_content_block_derivations"

    derived_block_id: Mapped[str] = mapped_column(String(36), ForeignKey("ansich_content_blocks.entity_id", ondelete="CASCADE"), primary_key=True)
    source_block_id: Mapped[str] = mapped_column(String(36), ForeignKey("ansich_content_blocks.entity_id", ondelete="CASCADE"), primary_key=True)
    transform_kind: Mapped[str] = mapped_column(String(32), primary_key=True)
    transform_version: Mapped[str] = mapped_column(String(32), nullable=False)
    source_role: Mapped[str] = mapped_column(String(16), nullable=False, default="source")
    ordinal: Mapped[int | None] = mapped_column(Integer)
    established_obs_id: Mapped[str] = mapped_column(String(36), ForeignKey("ansich_observations.obs_id", ondelete="RESTRICT"), nullable=False)

    __table_args__ = (
        Index("ix_ansich_derivations_derived", "derived_block_id"),
        Index("ix_ansich_derivations_source", "source_block_id"),
        Index(
            "ix_ansich_derivations_derived_source",
            "derived_block_id",
            "source_block_id",
        ),
        Index(
            "ix_ansich_derivations_source_derived",
            "source_block_id",
            "derived_block_id",
        ),
    )


class AnsichBlockProducerRow(Base):
    __tablename__ = "ansich_block_producers"

    block_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("ansich_content_blocks.entity_id", ondelete="CASCADE"),
        primary_key=True,
    )
    producer_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    producer_entity_id: Mapped[str | None] = mapped_column(String(36))
    producer_obs_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("ansich_observations.obs_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )

    __table_args__ = (Index("ix_ansich_block_producers_entity", "producer_kind", "producer_entity_id"),)


class AnsichContextCompressionRow(Base):
    __tablename__ = "ansich_context_compressions"

    entity_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("ansich_entities.entity_id", ondelete="CASCADE"),
        primary_key=True,
    )
    task_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("ansich_tasks.entity_id", ondelete="CASCADE"),
        nullable=False,
    )
    operation_id: Mapped[str | None] = mapped_column(String(36))
    summary_block_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("ansich_content_blocks.entity_id", ondelete="RESTRICT"),
        nullable=False,
    )
    before_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    after_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    before_visible_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    after_visible_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    algorithm: Mapped[str] = mapped_column(String(64), nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(32), nullable=False)
    source_obs_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("ansich_observations.obs_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="complete",
        server_default="complete",
    )

    __table_args__ = (Index("ix_ansich_context_compressions_task", "task_id", "source_obs_id"),)


class AnsichContextCompressionItemRow(Base):
    __tablename__ = "ansich_context_compression_items"

    compression_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("ansich_context_compressions.entity_id", ondelete="CASCADE"),
        primary_key=True,
    )
    disposition: Mapped[str] = mapped_column(String(16), primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer, primary_key=True)
    block_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("ansich_content_blocks.entity_id", ondelete="RESTRICT"),
        nullable=False,
    )

    __table_args__ = (Index("ix_ansich_context_compression_items_block", "block_id", "compression_id"),)


class AnsichContextStateRow(Base):
    __tablename__ = "ansich_context_states"

    state_id: Mapped[str] = mapped_column(String(36), ForeignKey("ansich_entities.entity_id", ondelete="CASCADE"), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("ansich_tasks.entity_id", ondelete="CASCADE"), nullable=False)
    state_hash: Mapped[str | None] = mapped_column(String(64))
    parent_state_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("ansich_context_states.state_id", ondelete="CASCADE"))
    created_obs_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("ansich_observations.obs_id", ondelete="RESTRICT"), unique=True)
    chain_depth: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_checkpoint: Mapped[bool] = mapped_column(nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="missing")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now)

    __table_args__ = (
        UniqueConstraint("task_id", "state_hash", name="uq_ansich_context_state_task_hash"),
        Index("ix_ansich_context_states_task_created", "task_id", "created_at"),
        Index("ix_ansich_context_states_parent", "parent_state_id"),
    )


class AnsichContextStateCheckpointItemRow(Base):
    __tablename__ = "ansich_context_state_checkpoint_items"

    state_id: Mapped[str] = mapped_column(String(36), ForeignKey("ansich_context_states.state_id", ondelete="CASCADE"), primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    role: Mapped[str | None] = mapped_column(String(16))
    message_id: Mapped[str | None] = mapped_column(String(256))
    source_identity: Mapped[str | None] = mapped_column(String(512))
    name: Mapped[str | None] = mapped_column(String(256))
    block_id: Mapped[str] = mapped_column(String(36), nullable=False)
    visible_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    estimated_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    __table_args__ = (Index("ix_ansich_context_state_checkpoint_items_block", "block_id"),)


class AnsichContextStateDeltaRow(Base):
    __tablename__ = "ansich_context_state_deltas"

    state_id: Mapped[str] = mapped_column(String(36), ForeignKey("ansich_context_states.state_id", ondelete="CASCADE"), primary_key=True)
    operation_ordinal: Mapped[int] = mapped_column(Integer, primary_key=True)
    operation: Mapped[str] = mapped_column(String(16), nullable=False)
    source_ordinal: Mapped[int | None] = mapped_column(Integer)
    target_ordinal: Mapped[int | None] = mapped_column(Integer)
    channel: Mapped[str | None] = mapped_column(String(32))
    role: Mapped[str | None] = mapped_column(String(16))
    message_id: Mapped[str | None] = mapped_column(String(256))
    source_identity: Mapped[str | None] = mapped_column(String(512))
    name: Mapped[str | None] = mapped_column(String(256))
    block_id: Mapped[str | None] = mapped_column(String(36))
    visible_bytes: Mapped[int | None] = mapped_column(BigInteger)
    estimated_tokens: Mapped[int | None] = mapped_column(BigInteger)
    metadata_json: Mapped[dict | None] = mapped_column(JSON)

    __table_args__ = (Index("ix_ansich_context_state_deltas_block", "block_id"),)


class AnsichContextStateMissingBlockRow(Base):
    __tablename__ = "ansich_context_state_missing_blocks"

    state_id: Mapped[str] = mapped_column(String(36), ForeignKey("ansich_context_states.state_id", ondelete="CASCADE"), primary_key=True)
    block_id: Mapped[str] = mapped_column(String(36), primary_key=True)

    __table_args__ = (Index("ix_ansich_context_state_missing_blocks_block", "block_id"),)


class AnsichContextWindowRow(Base):
    __tablename__ = "ansich_context_windows"

    entity_id: Mapped[str] = mapped_column(String(36), ForeignKey("ansich_entities.entity_id", ondelete="CASCADE"), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("ansich_tasks.entity_id", ondelete="CASCADE"), nullable=False, unique=True)
    capacity_tokens: Mapped[int | None] = mapped_column(BigInteger)
    estimator_name: Mapped[str] = mapped_column(String(64), nullable=False)
    estimator_version: Mapped[str] = mapped_column(String(32), nullable=False)


class AnsichContextSnapshotRow(Base):
    __tablename__ = "ansich_context_snapshots"

    entity_id: Mapped[str] = mapped_column(String(36), ForeignKey("ansich_entities.entity_id", ondelete="CASCADE"), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("ansich_tasks.entity_id", ondelete="CASCADE"), nullable=False)
    step_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("ansich_steps.entity_id", ondelete="CASCADE"))
    operation_id: Mapped[str | None] = mapped_column(String(36))
    state_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("ansich_context_states.state_id", ondelete="RESTRICT"))
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    request_obs_id: Mapped[str] = mapped_column(String(36), ForeignKey("ansich_observations.obs_id"), nullable=False, unique=True)
    message_count: Mapped[int] = mapped_column(Integer, nullable=False)
    tool_schema_count: Mapped[int] = mapped_column(Integer, nullable=False)
    visible_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    estimated_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    estimator_name: Mapped[str] = mapped_column(String(64), nullable=False)
    estimator_version: Mapped[str] = mapped_column(String(32), nullable=False)
    adapter_name: Mapped[str] = mapped_column(String(256), nullable=False)
    adapter_version: Mapped[str] = mapped_column(String(64), nullable=False)
    configured_model: Mapped[str | None] = mapped_column(String(256))
    response_format_json: Mapped[object | None] = mapped_column(JSON)
    generation_settings_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    redactions_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    warnings_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="complete", server_default="complete")

    __table_args__ = (Index("ix_ansich_context_snapshots_task_request", "task_id", "request_obs_id"),)


class AnsichContextSnapshotItemRow(Base):
    __tablename__ = "ansich_context_snapshot_items"

    snapshot_id: Mapped[str] = mapped_column(String(36), ForeignKey("ansich_context_snapshots.entity_id", ondelete="CASCADE"), primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    role: Mapped[str | None] = mapped_column(String(16))
    name: Mapped[str | None] = mapped_column(String(256))
    message_id: Mapped[str | None] = mapped_column(String(256))
    source_identity: Mapped[str | None] = mapped_column(String(512))
    content_block_id: Mapped[str] = mapped_column(String(36), ForeignKey("ansich_content_blocks.entity_id", ondelete="RESTRICT"), nullable=False)
    visible_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    estimated_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    __table_args__ = (
        Index("ix_ansich_context_snapshot_items_block", "content_block_id"),
        Index(
            "ix_ansich_context_snapshot_items_block_snapshot",
            "content_block_id",
            "snapshot_id",
        ),
    )


class AnsichContextSnapshotBlockMembershipRow(Base):
    __tablename__ = "ansich_context_snapshot_block_memberships"

    snapshot_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("ansich_context_snapshots.entity_id", ondelete="CASCADE"),
        primary_key=True,
    )
    ordinal: Mapped[int] = mapped_column(Integer, primary_key=True)
    content_block_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("ansich_content_blocks.entity_id", ondelete="RESTRICT"),
        nullable=False,
    )

    __table_args__ = (
        Index(
            "ix_ansich_snapshot_block_memberships_block",
            "content_block_id",
            "snapshot_id",
        ),
    )


class AnsichContextSnapshotMissingItemRow(Base):
    __tablename__ = "ansich_context_snapshot_missing_items"

    snapshot_id: Mapped[str] = mapped_column(String(36), ForeignKey("ansich_context_snapshots.entity_id", ondelete="CASCADE"), primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer, primary_key=True)
    expected_content_block_id: Mapped[str] = mapped_column(String(36), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    role: Mapped[str | None] = mapped_column(String(16))
    name: Mapped[str | None] = mapped_column(String(256))
    message_id: Mapped[str | None] = mapped_column(String(256))
    source_identity: Mapped[str | None] = mapped_column(String(512))
    visible_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    estimated_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    __table_args__ = (Index("ix_ansich_context_snapshot_missing_items_block", "expected_content_block_id"),)


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
    tool_calls_issued: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    tool_calls_executed: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now)

    __table_args__ = (Index("ix_ansich_task_summaries_control_evidence", "control_value", "last_evidence_at"),)


class AnsichUsageContributionRow(Base):
    __tablename__ = "ansich_usage_contributions"

    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("ansich_tasks.entity_id", ondelete="CASCADE"), primary_key=True)
    source_task_id: Mapped[str] = mapped_column(String(36), ForeignKey("ansich_tasks.entity_id", ondelete="CASCADE"), primary_key=True)
    dimension: Mapped[str] = mapped_column(String(32), primary_key=True)
    source_obs_id: Mapped[str] = mapped_column(String(36), ForeignKey("ansich_observations.obs_id", ondelete="CASCADE"), primary_key=True)
    delta: Mapped[int] = mapped_column(BigInteger, nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_ansich_usage_contributions_task_dimension", "task_id", "dimension"),)


class AnsichTaskUsageRow(Base):
    __tablename__ = "ansich_task_usage"

    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("ansich_tasks.entity_id", ondelete="CASCADE"), primary_key=True)
    dimension: Mapped[str] = mapped_column(String(32), primary_key=True)
    aggregation_scope: Mapped[str] = mapped_column(String(16), primary_key=True)
    value: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    complete_through_ingest_seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now)


class AnsichTaskBudgetRow(Base):
    __tablename__ = "ansich_task_budgets"

    entity_id: Mapped[str] = mapped_column(String(36), ForeignKey("ansich_entities.entity_id", ondelete="CASCADE"), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("ansich_tasks.entity_id", ondelete="CASCADE"), nullable=False)
    dimension: Mapped[str] = mapped_column(String(32), nullable=False)
    aggregation_scope: Mapped[str] = mapped_column(String(16), nullable=False)
    warning_limit: Mapped[int | None] = mapped_column(BigInteger)
    hard_limit: Mapped[int | None] = mapped_column(BigInteger)
    enforcement: Mapped[bool] = mapped_column(Boolean, nullable=False)
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    requested_value: Mapped[int | None] = mapped_column(BigInteger)
    effective_value: Mapped[int] = mapped_column(BigInteger, nullable=False)
    configured_obs_id: Mapped[str] = mapped_column(String(36), ForeignKey("ansich_observations.obs_id", ondelete="CASCADE"), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "task_id",
            "dimension",
            "aggregation_scope",
            "configured_obs_id",
            name="uq_ansich_task_budget_configuration",
        ),
        Index("ix_ansich_task_budgets_task_dimension", "task_id", "dimension"),
    )


class AnsichTaskHeartbeatRow(Base):
    __tablename__ = "ansich_task_heartbeats"

    heartbeat_obs_id: Mapped[str] = mapped_column(String(36), ForeignKey("ansich_observations.obs_id", ondelete="CASCADE"), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("ansich_tasks.entity_id", ondelete="CASCADE"), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    producer_instance_id: Mapped[str] = mapped_column(String(128), nullable=False)
    ownership_epoch: Mapped[str] = mapped_column(String(128), nullable=False)
    elapsed_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)

    __table_args__ = (Index("ix_ansich_task_heartbeats_task_occurred", "task_id", "occurred_at"),)


class AnsichActiveTaskReadModelRow(Base):
    __tablename__ = "ansich_active_task_read_model"

    task_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("ansich_tasks.entity_id", ondelete="CASCADE"),
        primary_key=True,
    )
    run_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    owner_id: Mapped[str | None] = mapped_column(String(256))
    thread_id: Mapped[str | None] = mapped_column(String(256))
    agent_id: Mapped[str | None] = mapped_column(String(256))
    control_value: Mapped[str] = mapped_column(String(32), nullable=False)
    current_step_id: Mapped[str | None] = mapped_column(String(36))
    current_tool_call_id: Mapped[str | None] = mapped_column(String(36))
    heartbeat_value: Mapped[str] = mapped_column(String(16), nullable=False)
    budget_status: Mapped[str] = mapped_column(String(16), nullable=False)
    duration_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    observability_status: Mapped[str] = mapped_column(String(16), nullable=False)
    projection_watermark: Mapped[int | None] = mapped_column(BigInteger)
    projection_lag_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    control_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    current_step_json: Mapped[dict | None] = mapped_column(JSON)
    current_tool_json: Mapped[dict | None] = mapped_column(JSON)
    dwell_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    heartbeat_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    usage_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    budgets_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    budget_health_json: Mapped[list] = mapped_column(JSON, nullable=False)
    lost_ranges_json: Mapped[list] = mapped_column(JSON, nullable=False)
    last_evidence_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index(
            "ix_ansich_active_tasks_evidence",
            "last_evidence_at",
            "task_id",
        ),
        Index(
            "ix_ansich_active_tasks_filters",
            "owner_id",
            "heartbeat_value",
            "budget_status",
        ),
    )
