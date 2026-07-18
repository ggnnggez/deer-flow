from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Literal, cast
from uuid import uuid4

from ansich import (
    ContentBlockPayloadView,
    ContentBlockView,
    ContentDerivationView,
    ContentOccurrenceView,
    ContentProducerView,
    ContextCompressionItemView,
    ContextCompressionView,
    ContextSnapshotItemView,
    ContextSnapshotView,
    ContextStateDelta,
    ContextStateItem,
    ContextStateView,
    ControlBelief,
    LlmAttemptView,
    NamedVersion,
    ObservationEnvelope,
    PossibleExposureItemView,
    Producer,
    StepView,
    TaskView,
    ToolBelief,
    ToolCallView,
    ToolResultView,
    new_id,
)
from ansich.budget import (
    BudgetHealthBelief,
    BudgetSourceKind,
    TaskBudgetsView,
    TaskBudgetView,
    assess_budget_health,
)
from ansich.compression import CompressionDisposition
from ansich.context_state import context_state_hash, materialize_context_state
from ansich.contracts import ControlValue, LostRange, TaskLifecycleScope, control_values_for_lifecycle_scope
from ansich.control import should_select_control_candidate
from ansich.heartbeat import TaskHeartbeatView
from ansich.lineage import LineageDirection
from ansich.operations import (
    ActiveStepView,
    ActiveTaskView,
    ActiveToolView,
    DwellBelief,
    HeartbeatBelief,
    assess_dwell,
    assess_heartbeat,
)
from ansich.tool import ContentDerivationSourceRole, ToolTransformKind
from ansich.usage import (
    TaskUsageValue,
    TaskUsageView,
    child_task_contribution_for_tool_started,
    usage_contributions_for_observation,
)
from sqlalchemy import and_, case, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.ansich.persistence.models import (
    AnsichActiveTaskReadModelRow,
    AnsichBeliefAssertionRow,
    AnsichBeliefEvidenceRow,
    AnsichBlockProducerRow,
    AnsichContentBlobRow,
    AnsichContentBlockDerivationRow,
    AnsichContentBlockRow,
    AnsichContentOccurrenceRow,
    AnsichContextCompressionItemRow,
    AnsichContextCompressionRow,
    AnsichContextSnapshotBlockMembershipRow,
    AnsichContextSnapshotItemRow,
    AnsichContextSnapshotMissingItemRow,
    AnsichContextSnapshotRow,
    AnsichContextStateCheckpointItemRow,
    AnsichContextStateDeltaRow,
    AnsichContextStateMissingBlockRow,
    AnsichContextStateRow,
    AnsichContextWindowRow,
    AnsichCurrentBeliefRow,
    AnsichEntityRow,
    AnsichLlmAttemptRow,
    AnsichObservationRow,
    AnsichPayloadRow,
    AnsichProjectionErrorRow,
    AnsichProjectionJobRow,
    AnsichProjectorVersionRow,
    AnsichRelationEvidenceRow,
    AnsichRelationRow,
    AnsichScopeRow,
    AnsichStepRow,
    AnsichTaskBudgetRow,
    AnsichTaskHeartbeatRow,
    AnsichTaskRow,
    AnsichTaskSummaryRow,
    AnsichTaskUsageRow,
    AnsichToolCallResultRow,
    AnsichToolCallRow,
    AnsichTransitionRow,
    AnsichUsageContributionRow,
)

_CONTROL_BY_KIND = {
    "task.created": "created",
    "task.started": "running",
    "task.completed": "completed",
    "task.failed": "failed",
    "task.interrupted": "interrupted",
}
_STEP_PROJECTION_KINDS = frozenset(
    {
        "step.started",
        "step.closed",
        "llm.requested",
        "llm.responded",
        "llm.failed",
        "content.produced",
        "context.state_recorded",
        "context.snapshotted",
        "context.compressed",
        "tool.issued",
        "tool.started",
        "tool.returned_raw",
        "tool.result_visible",
        "tool.denied",
        "tool.timed_out",
        "tool.cancelled",
        "tool.failed",
        "tool.unknown_terminal",
    }
)
#: Registration order is execution priority for jobs of one observation:
#: structural projections must land before belief/control projections, and
#: future projectors (e.g. Phase 2 steps) run after both. Claim ordering
#: derives from this tuple — never from projector_name collation.
_USAGE_PROJECTION_KINDS = frozenset(
    {
        "llm.requested",
        "llm.responded",
        "step.started",
        "tool.issued",
        "tool.started",
        "tool.returned_raw",
        "tool.timed_out",
        "tool.cancelled",
        "tool.failed",
        "budget.consumed",
    }
)
_PROJECTORS = (("task-structural", "1"), ("task-control", "1"), ("task-step", "1"), ("task-usage", "1"), ("task-budget", "1"), ("task-heartbeat", "1"))
_PROJECTOR_KINDS = {
    "task-structural": frozenset(_CONTROL_BY_KIND),
    "task-control": frozenset(_CONTROL_BY_KIND),
    "task-step": _STEP_PROJECTION_KINDS,
    "task-usage": _USAGE_PROJECTION_KINDS,
    "task-budget": frozenset({"budget.configured"}),
    "task-heartbeat": frozenset({"task.heartbeat"}),
}
_USAGE_DIMENSION_ORDER = {
    "input_tokens": 0,
    "output_tokens": 1,
    "total_tokens": 2,
    "llm_attempts": 3,
    "steps": 4,
    "tool_calls_issued": 5,
    "tool_calls_executed": 6,
    "wall_time_ms": 7,
    "child_tasks_spawned": 8,
}
_CONTENT_CANONICALIZATION_VERSION = "1"
_TOOL_TERMINAL_PRECEDENCE = {
    "unknown_terminal": 0,
    "denied": 1,
    "cancelled": 2,
    "timed_out": 3,
    "failed": 4,
    "returned": 5,
}


class _ProjectionDependencyPending(RuntimeError):
    """A replay-safe projection dependency has not landed yet."""


def _projectors_for_kind(kind: str) -> tuple[tuple[str, str], ...]:
    return tuple(registration for registration in _PROJECTORS if kind in _PROJECTOR_KINDS.get(registration[0], ()))


def _projector_priority_expression():
    priority_by_name = {name: index for index, (name, _) in enumerate(_PROJECTORS)}
    return case(priority_by_name, value=AnsichProjectionJobRow.projector_name, else_=len(priority_by_name))


def _periodic_budget_rows_statement():
    return (
        select(AnsichTaskBudgetRow)
        .join(
            AnsichTaskSummaryRow,
            AnsichTaskSummaryRow.task_id == AnsichTaskBudgetRow.task_id,
        )
        .where(AnsichTaskSummaryRow.control_value == "running")
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _read_model_values_equal(current: object, candidate: object) -> bool:
    if isinstance(current, datetime) and isinstance(candidate, datetime):
        return _as_utc(current) == _as_utc(candidate)
    return current == candidate


def _list_task_views_statement(
    *,
    limit: int,
    control: ControlValue | None,
    lifecycle_scope: TaskLifecycleScope,
    from_time: datetime | None,
    to_time: datetime | None,
    cursor: tuple[datetime, str] | None,
):
    page_statement = select(
        AnsichTaskSummaryRow.task_id,
        AnsichTaskSummaryRow.source_kind,
        AnsichTaskSummaryRow.source_id,
        AnsichTaskSummaryRow.control_value,
        AnsichTaskSummaryRow.control_as_of,
        AnsichTaskSummaryRow.last_evidence_at,
        AnsichTaskSummaryRow.assertion_id,
        AnsichTaskSummaryRow.observability_status,
        AnsichTaskSummaryRow.tool_calls_issued,
        AnsichTaskSummaryRow.tool_calls_executed,
    )
    if control is not None:
        page_statement = page_statement.where(AnsichTaskSummaryRow.control_value == control)
    lifecycle_controls = control_values_for_lifecycle_scope(lifecycle_scope)
    if lifecycle_controls is not None:
        page_statement = page_statement.where(AnsichTaskSummaryRow.control_value.in_(lifecycle_controls))
    if from_time is not None:
        page_statement = page_statement.where(AnsichTaskSummaryRow.last_evidence_at >= from_time)
    if to_time is not None:
        page_statement = page_statement.where(AnsichTaskSummaryRow.last_evidence_at <= to_time)
    if cursor is not None:
        cursor_time, cursor_task_id = cursor
        page_statement = page_statement.where(
            or_(
                AnsichTaskSummaryRow.last_evidence_at < cursor_time,
                and_(
                    AnsichTaskSummaryRow.last_evidence_at == cursor_time,
                    AnsichTaskSummaryRow.task_id > cursor_task_id,
                ),
            )
        )
    page = (
        page_statement.order_by(
            AnsichTaskSummaryRow.last_evidence_at.desc(),
            AnsichTaskSummaryRow.task_id,
        )
        .limit(limit)
        .cte("ansich_task_page")
    )
    return (
        select(
            page,
            AnsichCurrentBeliefRow.resolver_name.label("resolver_name"),
            AnsichCurrentBeliefRow.resolver_version.label("resolver_version"),
            AnsichBeliefAssertionRow.value_json.label("assertion_value_json"),
            AnsichBeliefAssertionRow.as_of.label("assertion_as_of"),
            AnsichBeliefAssertionRow.asserted_at.label("assertion_asserted_at"),
            AnsichBeliefAssertionRow.source_name.label("assertion_source_name"),
            AnsichBeliefAssertionRow.source_version.label("assertion_source_version"),
            AnsichBeliefEvidenceRow.obs_id.label("evidence_obs_id"),
            AnsichBeliefEvidenceRow.ordinal.label("evidence_ordinal"),
        )
        .select_from(page)
        .outerjoin(
            AnsichCurrentBeliefRow,
            and_(
                AnsichCurrentBeliefRow.subject_id == page.c.task_id,
                AnsichCurrentBeliefRow.field_name == "control",
                AnsichCurrentBeliefRow.assertion_id == page.c.assertion_id,
            ),
        )
        .outerjoin(
            AnsichBeliefAssertionRow,
            AnsichBeliefAssertionRow.assertion_id == page.c.assertion_id,
        )
        .outerjoin(
            AnsichBeliefEvidenceRow,
            AnsichBeliefEvidenceRow.assertion_id == page.c.assertion_id,
        )
        .order_by(
            page.c.last_evidence_at.desc(),
            page.c.task_id,
            AnsichBeliefEvidenceRow.ordinal,
            AnsichBeliefEvidenceRow.obs_id,
        )
    )


def _canonical_content_bytes(body: object) -> tuple[str, bytes]:
    if isinstance(body, str):
        return "text/plain; charset=utf-8", body.encode("utf-8")
    return (
        "application/json",
        json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"),
    )


def _content_blob_key(content_type: str, body: bytes) -> str:
    digest = hashlib.sha256()
    digest.update(f"ansich-content:{_CONTENT_CANONICALIZATION_VERSION}:{content_type}\0".encode())
    digest.update(body)
    return digest.hexdigest()


class SqlAnsichBackend:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        projector_lease_seconds: int = 30,
        projector_max_attempts: int = 5,
        projector_dependency_timeout_seconds: int = 300,
        inline_payload_max_bytes: int = 65_536,
        heartbeat_stale_after_seconds: int = 30,
        long_dwell_seconds: int = 120,
    ) -> None:
        self._session_factory = session_factory
        self._projector_lease_seconds = projector_lease_seconds
        self._projector_max_attempts = projector_max_attempts
        self._projector_dependency_timeout = timedelta(seconds=projector_dependency_timeout_seconds)
        self._inline_payload_max_bytes = inline_payload_max_bytes
        self._heartbeat_stale_after_seconds = heartbeat_stale_after_seconds
        self._long_dwell_seconds = long_dwell_seconds
        self._lease_owner = str(uuid4())
        self._watermark: int | None = None
        self._failed_jobs = 0
        self._latest_recorded_at: datetime | None = None
        self._latest_projected_at: datetime | None = None
        self._context_metrics = {
            "snapshot_count": 0,
            "snapshot_item_count": 0,
            "snapshot_visible_bytes": 0,
            "incomplete_snapshot_count": 0,
            "missing_content_block_count": 0,
        }

    async def initialize_metrics(self) -> None:
        async with self._session_factory() as session:
            failed_jobs = await session.scalar(select(func.count()).select_from(AnsichProjectionJobRow).where(AnsichProjectionJobRow.status == "failed"))
        self._failed_jobs = int(failed_jobs or 0)
        await self._refresh_context_metrics()

    async def persist_and_project(self, observations: list[ObservationEnvelope]) -> int:
        processed = 0
        async with self._session_factory() as session, session.begin():
            for observation in observations:
                existing_obs = await session.scalar(
                    select(AnsichObservationRow).where(
                        or_(
                            AnsichObservationRow.obs_id == observation.obs_id,
                            (
                                (AnsichObservationRow.producer_name == observation.producer.name)
                                & (AnsichObservationRow.producer_instance_id == observation.producer.instance_id)
                                & (AnsichObservationRow.source_event_id == observation.source_event_id)
                            ),
                        )
                    )
                )
                if existing_obs is not None:
                    continue
                payload_json = observation.payload
                payload_ref_id = observation.payload_ref_id
                if observation.kind == "content.produced" and payload_json is not None and "body" in payload_json:
                    body = payload_json["body"]
                    content_type, content_bytes = _canonical_content_bytes(body)
                    content_hash = hashlib.sha256(content_bytes).hexdigest()
                    if payload_json.get("content_hash") != content_hash:
                        raise ValueError("content.produced hash does not match canonical body")
                    blob_key = _content_blob_key(content_type, content_bytes)
                    await self._ensure_content_blob(
                        session,
                        blob_key=blob_key,
                        content_hash=content_hash,
                        content_type=content_type,
                        content_bytes=content_bytes,
                    )
                    payload_json = dict(payload_json)
                    payload_json.pop("body", None)
                    payload_json["blob_key"] = blob_key
                    payload_json["content_type"] = content_type
                    payload_json["canonicalization_version"] = _CONTENT_CANONICALIZATION_VERSION
                if payload_json is not None:
                    encoded_payload = json.dumps(
                        payload_json,
                        ensure_ascii=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    ).encode("utf-8")
                    if len(encoded_payload) > self._inline_payload_max_bytes:
                        payload_ref_id = new_id()
                        session.add(
                            AnsichPayloadRow(
                                payload_id=payload_ref_id,
                                content_type="application/json",
                                encoding="utf-8",
                                compression="none",
                                byte_size=len(encoded_payload),
                                sha256=hashlib.sha256(encoded_payload).hexdigest(),
                                body=encoded_payload,
                            )
                        )
                        payload_json = None
                session.add(
                    AnsichObservationRow(
                        obs_id=observation.obs_id,
                        schema_version=observation.schema_version,
                        kind=observation.kind,
                        occurred_at=observation.occurred_at,
                        recorded_at=observation.recorded_at,
                        task_id=observation.task_id,
                        step_id=observation.step_id,
                        subject_type=observation.subject_type,
                        subject_id=observation.subject_id,
                        fidelity_class=observation.fidelity_class,
                        producer_name=observation.producer.name,
                        producer_version=observation.producer.version,
                        producer_instance_id=observation.producer.instance_id,
                        producer_seq=observation.producer_seq,
                        source_event_id=observation.source_event_id,
                        correlation_id=observation.correlation_id,
                        causation_obs_id=observation.causation_obs_id,
                        payload_json=payload_json,
                        payload_ref_id=payload_ref_id,
                    )
                )
                await session.flush()
                for projector_name, projector_version in _projectors_for_kind(observation.kind):
                    version = await session.get(AnsichProjectorVersionRow, (projector_name, projector_version))
                    if version is None:
                        session.add(
                            AnsichProjectorVersionRow(
                                projector_name=projector_name,
                                projector_version=projector_version,
                            )
                        )
                    job = AnsichProjectionJobRow(
                        job_id=new_id(),
                        obs_id=observation.obs_id,
                        projector_name=projector_name,
                        projector_version=projector_version,
                        status="pending",
                    )
                    session.add(job)
                processed += 1
        if processed:
            latest = max(observation.recorded_at for observation in observations)
            if self._latest_recorded_at is None or latest > self._latest_recorded_at:
                self._latest_recorded_at = latest
        return processed

    async def _ensure_content_blob(
        self,
        session: AsyncSession,
        *,
        blob_key: str,
        content_hash: str,
        content_type: str,
        content_bytes: bytes,
    ) -> None:
        blob = await session.get(AnsichContentBlobRow, blob_key)
        if blob is None:
            blob_payload_ref_id = None
            inline_body = content_bytes
            if len(content_bytes) > self._inline_payload_max_bytes:
                blob_payload_ref_id = new_id()
                inline_body = None
                session.add(
                    AnsichPayloadRow(
                        payload_id=blob_payload_ref_id,
                        content_type=content_type,
                        encoding="utf-8",
                        compression="none",
                        byte_size=len(content_bytes),
                        sha256=content_hash,
                        body=content_bytes,
                    )
                )
                await session.flush()
            values = {
                "blob_key": blob_key,
                "content_hash": content_hash,
                "byte_size": len(content_bytes),
                "content_type": content_type,
                "canonicalization_version": _CONTENT_CANONICALIZATION_VERSION,
                "payload_status": "available",
                "inline_body": inline_body,
                "payload_ref_id": blob_payload_ref_id,
            }
            dialect_name = session.bind.dialect.name if session.bind is not None else ""
            if dialect_name == "postgresql":
                statement = postgresql_insert(AnsichContentBlobRow).values(**values)
            elif dialect_name == "sqlite":
                statement = sqlite_insert(AnsichContentBlobRow).values(**values)
            else:
                raise ValueError(f"unsupported Ansich SQL dialect: {dialect_name}")
            inserted_key = (await session.execute(statement.on_conflict_do_nothing(index_elements=["blob_key"]).returning(AnsichContentBlobRow.blob_key))).scalar_one_or_none()
            if inserted_key is None and blob_payload_ref_id is not None:
                losing_payload = await session.get(AnsichPayloadRow, blob_payload_ref_id)
                if losing_payload is not None:
                    await session.delete(losing_payload)
            blob = await session.get(AnsichContentBlobRow, blob_key)
            if blob is None:
                raise RuntimeError("Ansich ContentBlob upsert did not produce a row")
        existing_bytes = await self._content_blob_bytes(session, blob)
        if existing_bytes != content_bytes:
            raise ValueError("Ansich ContentBlob key collision")

    async def project_pending(self, *, limit: int = 200) -> int:
        processed = 0
        for _ in range(limit):
            claim = await self._claim_projection_job()
            if claim is None:
                break
            job_id, projector_name, observation, ingest_seq, attempt = claim
            try:
                context_metrics_changed = False
                async with self._session_factory() as session, session.begin():
                    if projector_name == "task-structural":
                        await self._project_structural(session, observation)
                    elif projector_name == "task-control":
                        await self._project_control(session, observation, ingest_seq=ingest_seq)
                    elif projector_name == "task-step":
                        context_metrics_changed = await self._project_step(session, observation)
                    elif projector_name == "task-usage":
                        await self._project_usage(session, observation, ingest_seq=ingest_seq)
                    elif projector_name == "task-budget":
                        await self._project_budget(session, observation)
                    elif projector_name == "task-heartbeat":
                        await self._project_heartbeat(
                            session,
                            observation,
                            ingest_seq=ingest_seq,
                        )
                    else:
                        raise ValueError(f"unknown Ansich projector: {projector_name}")
                    job = await session.get(AnsichProjectionJobRow, job_id)
                    if job is None:
                        raise RuntimeError("claimed Ansich projection job disappeared")
                    job.status = "completed"
                    job.dependency_pending_since = None
                    job.lease_owner = None
                    job.lease_expires_at = None
                    job.last_error = None
                if context_metrics_changed:
                    await self._refresh_context_metrics()
                processed += 1
                self._watermark = ingest_seq if self._watermark is None else max(self._watermark, ingest_seq)
                if self._latest_projected_at is None or observation.recorded_at > self._latest_projected_at:
                    self._latest_projected_at = observation.recorded_at
            except Exception as exc:
                await self._record_projection_error(job_id, attempt, exc)
        return processed

    def get_projection_metrics(self) -> dict[str, int | None]:
        lag_ms = 0
        if self._latest_recorded_at is not None:
            projected_at = self._latest_projected_at
            if projected_at is None:
                lag_ms = max(0, int((datetime.now(UTC) - self._latest_recorded_at).total_seconds() * 1000))
            else:
                lag_ms = max(0, int((self._latest_recorded_at - projected_at).total_seconds() * 1000))
        return {
            "watermark": self._watermark,
            "lag_ms": lag_ms,
            "failed_jobs": self._failed_jobs,
            **self._context_metrics,
        }

    async def _refresh_context_metrics(self) -> None:
        async with self._session_factory() as session:
            snapshot_count = await session.scalar(select(func.count()).select_from(AnsichContextSnapshotRow))
            snapshot_visible_bytes = await session.scalar(select(func.coalesce(func.sum(AnsichContextSnapshotRow.visible_bytes), 0)))
            complete_items = await session.scalar(select(func.count()).select_from(AnsichContextSnapshotItemRow))
            missing_items = await session.scalar(select(func.count()).select_from(AnsichContextSnapshotMissingItemRow))
            state_items = await session.scalar(
                select(func.coalesce(func.sum(AnsichContextStateRow.item_count), 0)).select_from(AnsichContextSnapshotRow).join(AnsichContextStateRow, AnsichContextStateRow.state_id == AnsichContextSnapshotRow.state_id)
            )
            state_missing_blocks = await session.scalar(select(func.count()).select_from(AnsichContextStateMissingBlockRow))
            incomplete_snapshots = await session.scalar(select(func.count()).select_from(AnsichContextSnapshotRow).where(AnsichContextSnapshotRow.status == "incomplete"))
        self._context_metrics = {
            "snapshot_count": int(snapshot_count or 0),
            "snapshot_item_count": int(complete_items or 0) + int(missing_items or 0) + int(state_items or 0),
            "snapshot_visible_bytes": int(snapshot_visible_bytes or 0),
            "incomplete_snapshot_count": int(incomplete_snapshots or 0),
            "missing_content_block_count": int(missing_items or 0) + int(state_missing_blocks or 0),
        }

    async def has_pending_for_task(self, task_id: str) -> bool:
        async with self._session_factory() as session:
            pending = await session.scalar(
                select(AnsichProjectionJobRow.job_id)
                .join(AnsichObservationRow, AnsichObservationRow.obs_id == AnsichProjectionJobRow.obs_id)
                .where(
                    AnsichObservationRow.task_id == task_id,
                    or_(
                        AnsichProjectionJobRow.status == "pending",
                        AnsichProjectionJobRow.status == "processing",
                    ),
                )
                .limit(1)
            )
        return pending is not None

    async def rebuild_projections(self) -> int:
        """Delete rebuildable Phase 1 state and replay every durable job."""

        async with self._session_factory() as session, session.begin():
            for model in (
                AnsichTaskHeartbeatRow,
                AnsichActiveTaskReadModelRow,
                AnsichTaskBudgetRow,
                AnsichTaskUsageRow,
                AnsichUsageContributionRow,
                AnsichContextSnapshotMissingItemRow,
                AnsichContextSnapshotBlockMembershipRow,
                AnsichContextSnapshotItemRow,
                AnsichContextSnapshotRow,
                AnsichContextWindowRow,
                AnsichContextCompressionItemRow,
                AnsichContextCompressionRow,
                AnsichContextStateMissingBlockRow,
                AnsichContextStateDeltaRow,
                AnsichContextStateCheckpointItemRow,
                AnsichContextStateRow,
                AnsichContentBlockDerivationRow,
                AnsichBlockProducerRow,
                AnsichToolCallResultRow,
                AnsichToolCallRow,
                AnsichContentOccurrenceRow,
                AnsichContentBlockRow,
                AnsichLlmAttemptRow,
                AnsichStepRow,
                AnsichTaskSummaryRow,
                AnsichCurrentBeliefRow,
                AnsichBeliefEvidenceRow,
                AnsichTransitionRow,
                AnsichBeliefAssertionRow,
                AnsichRelationEvidenceRow,
                AnsichRelationRow,
                AnsichScopeRow,
                AnsichTaskRow,
                AnsichEntityRow,
                AnsichProjectionErrorRow,
            ):
                await session.execute(delete(model))
            await session.execute(
                update(AnsichProjectionJobRow).values(
                    status="pending",
                    attempts=0,
                    available_at=datetime.now(UTC),
                    dependency_pending_since=None,
                    lease_owner=None,
                    lease_expires_at=None,
                    last_error=None,
                )
            )
        self._watermark = None
        self._failed_jobs = 0
        self._latest_projected_at = None
        replayed = 0
        while True:
            processed = await self.project_pending(limit=200)
            replayed += processed
            if processed == 0:
                await self._refresh_context_metrics()
                return replayed

    async def retry_failed_projections(self, *, task_id: str | None = None) -> int:
        """Requeue failed durable jobs and settle them without deleting projections."""

        async with self._session_factory() as session, session.begin():
            failed_job_ids = select(AnsichProjectionJobRow.job_id).where(AnsichProjectionJobRow.status == "failed")
            if task_id is not None:
                failed_job_ids = failed_job_ids.join(
                    AnsichObservationRow,
                    AnsichObservationRow.obs_id == AnsichProjectionJobRow.obs_id,
                ).where(AnsichObservationRow.task_id == task_id)
            job_ids = tuple((await session.execute(failed_job_ids)).scalars())
            if job_ids:
                await session.execute(
                    update(AnsichProjectionJobRow)
                    .where(AnsichProjectionJobRow.job_id.in_(job_ids))
                    .values(
                        status="pending",
                        attempts=0,
                        available_at=datetime.now(UTC),
                        dependency_pending_since=None,
                        lease_owner=None,
                        lease_expires_at=None,
                        last_error=None,
                    )
                )
        if not job_ids:
            return 0

        while await self.project_pending(limit=200):
            pass
        async with self._session_factory() as session:
            failed_count = await session.scalar(select(func.count()).select_from(AnsichProjectionJobRow).where(AnsichProjectionJobRow.status == "failed"))
        self._failed_jobs = int(failed_count or 0)
        await self._refresh_context_metrics()
        return len(job_ids)

    async def _claim_projection_job(
        self,
    ) -> tuple[str, str, ObservationEnvelope, int, int] | None:
        now = datetime.now(UTC)
        async with self._session_factory() as session, session.begin():
            row = (
                await session.execute(
                    select(AnsichProjectionJobRow, AnsichObservationRow)
                    .join(AnsichObservationRow, AnsichObservationRow.obs_id == AnsichProjectionJobRow.obs_id)
                    .where(
                        AnsichProjectionJobRow.available_at <= now,
                        or_(
                            AnsichProjectionJobRow.status == "pending",
                            (AnsichProjectionJobRow.status == "processing") & (AnsichProjectionJobRow.lease_expires_at <= now),
                        ),
                    )
                    .order_by(
                        AnsichObservationRow.ingest_seq,
                        _projector_priority_expression(),
                        AnsichProjectionJobRow.projector_name,
                    )
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
            ).first()
            if row is None:
                return None
            job, observation_row = row
            job.status = "processing"
            job.attempts += 1
            job.lease_owner = self._lease_owner
            job.lease_expires_at = now + timedelta(seconds=self._projector_lease_seconds)
            observation = self._observation_from_row(observation_row)
            if observation.payload is None and observation.payload_ref_id is not None:
                payload = await session.get(AnsichPayloadRow, observation.payload_ref_id)
                if payload is None:
                    raise RuntimeError(f"Ansich payload disappeared: {observation.payload_ref_id}")
                decoded = json.loads(payload.body.decode(payload.encoding))
                if not isinstance(decoded, dict):
                    raise ValueError("Ansich projection payload must decode to an object")
                observation = observation.model_copy(update={"payload": decoded, "payload_ref_id": None})
            return job.job_id, job.projector_name, observation, observation_row.ingest_seq, job.attempts

    async def _record_projection_error(self, job_id: str, attempt: int, exc: Exception) -> None:
        async with self._session_factory() as session, session.begin():
            job = await session.get(AnsichProjectionJobRow, job_id)
            if job is None:
                return
            message = str(exc)[:4_000]
            if isinstance(exc, _ProjectionDependencyPending):
                now = datetime.now(UTC)
                pending_since = now if job.dependency_pending_since is None else _as_utc(job.dependency_pending_since)
                job.dependency_pending_since = pending_since
                job.status = "failed" if now - pending_since >= self._projector_dependency_timeout else "pending"
                job.attempts = max(0, job.attempts - 1)
                job.available_at = now + timedelta(milliseconds=250)
                job.lease_owner = None
                job.lease_expires_at = None
                job.last_error = message
                if job.status == "failed":
                    self._failed_jobs += 1
                    session.add(
                        AnsichProjectionErrorRow(
                            error_id=new_id(),
                            job_id=job_id,
                            attempt=attempt,
                            error_type=type(exc).__name__,
                            message=message,
                        )
                    )
                return
            job.dependency_pending_since = None
            job.status = "failed" if attempt >= self._projector_max_attempts else "pending"
            if job.status == "failed":
                self._failed_jobs += 1
            job.available_at = datetime.now(UTC) + timedelta(milliseconds=250)
            job.lease_owner = None
            job.lease_expires_at = None
            job.last_error = message
            session.add(
                AnsichProjectionErrorRow(
                    error_id=new_id(),
                    job_id=job_id,
                    attempt=attempt,
                    error_type=type(exc).__name__,
                    message=message,
                )
            )

    async def get_task(self, task_id: str) -> TaskView | None:
        async with self._session_factory() as session:
            task = await session.get(AnsichTaskRow, task_id)
            if task is None:
                return None
            summary = await session.get(AnsichTaskSummaryRow, task_id)
            usage = {
                "observability_status": ("healthy" if summary is None else summary.observability_status),
                "tool_calls_issued": 0 if summary is None else summary.tool_calls_issued,
                "tool_calls_executed": 0 if summary is None else summary.tool_calls_executed,
            }
            current = await session.get(AnsichCurrentBeliefRow, (task_id, "control"))
            if current is None:
                trigger = await session.scalar(select(AnsichObservationRow).where(AnsichObservationRow.obs_id == task.trigger_obs_id))
                asserted_at = datetime.now(UTC) if trigger is None else _as_utc(trigger.recorded_at)
                return TaskView(
                    task_id=task.entity_id,
                    source_kind=task.source_kind,
                    source_id=task.source_id,
                    control=ControlBelief(
                        value="unknown",
                        as_of=None,
                        asserted_at=asserted_at,
                        source=NamedVersion(name="task-control", version="1"),
                        fidelity_class="hard",
                        selected_by=NamedVersion(name="control-state", version="1"),
                        evidence_obs_ids=(),
                    ),
                    **usage,
                )
            assertion = await session.get(AnsichBeliefAssertionRow, current.assertion_id)
            if assertion is None:
                return None
            evidence_rows = (await session.execute(select(AnsichBeliefEvidenceRow).where(AnsichBeliefEvidenceRow.assertion_id == assertion.assertion_id).order_by(AnsichBeliefEvidenceRow.ordinal))).scalars()
            return TaskView(
                task_id=task.entity_id,
                source_kind=task.source_kind,
                source_id=task.source_id,
                control=ControlBelief(
                    value=cast(str, assertion.value_json["value"]),
                    as_of=_as_utc(assertion.as_of),
                    asserted_at=_as_utc(assertion.asserted_at),
                    source=NamedVersion(name=assertion.source_name, version=assertion.source_version),
                    fidelity_class="hard",
                    selected_by=NamedVersion(name=current.resolver_name, version=current.resolver_version),
                    evidence_obs_ids=tuple(row.obs_id for row in evidence_rows),
                ),
                **usage,
            )

    async def get_task_by_source(self, source_kind: str, source_id: str) -> TaskView | None:
        async with self._session_factory() as session:
            task_id = await session.scalar(
                select(AnsichTaskRow.entity_id).where(
                    AnsichTaskRow.source_kind == source_kind,
                    AnsichTaskRow.source_id == source_id,
                )
            )
        if task_id is None:
            return None
        return await self.get_task(task_id)

    async def list_tasks(
        self,
        *,
        limit: int = 100,
        control: ControlValue | None = None,
        lifecycle_scope: TaskLifecycleScope = "all",
        from_time: datetime | None = None,
        to_time: datetime | None = None,
        cursor: tuple[datetime, str] | None = None,
    ) -> list[TaskView]:
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    _list_task_views_statement(
                        limit=limit,
                        control=control,
                        lifecycle_scope=lifecycle_scope,
                        from_time=from_time,
                        to_time=to_time,
                        cursor=cursor,
                    )
                )
            ).all()
        row_by_task_id = {}
        evidence_by_task_id: dict[str, list[str]] = {}
        for row in rows:
            if row.task_id not in row_by_task_id:
                row_by_task_id[row.task_id] = row
                evidence_by_task_id[row.task_id] = []
            if row.evidence_obs_id is not None:
                evidence_by_task_id[row.task_id].append(row.evidence_obs_id)

        tasks: list[TaskView] = []
        for task_id, row in row_by_task_id.items():
            assertion_value = row.assertion_value_json
            control_value = assertion_value.get("value", row.control_value) if isinstance(assertion_value, dict) else row.control_value
            tasks.append(
                TaskView(
                    task_id=task_id,
                    source_kind=row.source_kind,
                    source_id=row.source_id,
                    control=ControlBelief(
                        value=cast(str, control_value),
                        as_of=_as_utc(row.assertion_as_of or row.control_as_of),
                        asserted_at=_as_utc(row.assertion_asserted_at or row.last_evidence_at),
                        source=NamedVersion(
                            name=row.assertion_source_name or "task-control",
                            version=row.assertion_source_version or "1",
                        ),
                        fidelity_class="hard",
                        selected_by=NamedVersion(
                            name=row.resolver_name or "control-state",
                            version=row.resolver_version or "1",
                        ),
                        evidence_obs_ids=tuple(evidence_by_task_id[task_id]),
                    ),
                    observability_status=(row.observability_status if row.assertion_value_json is not None and row.resolver_name is not None else "degraded"),
                    tool_calls_issued=row.tool_calls_issued,
                    tool_calls_executed=row.tool_calls_executed,
                )
            )
        return tasks

    async def list_observations(self, task_id: str) -> list[ObservationEnvelope]:
        async with self._session_factory() as session:
            rows = list((await session.execute(select(AnsichObservationRow).where(AnsichObservationRow.task_id == task_id).order_by(AnsichObservationRow.ingest_seq))).scalars())
        return [self._observation_from_row(row) for row in rows]

    async def get_task_usage(self, task_id: str) -> TaskUsageView:
        async with self._session_factory() as session:
            rows = list(
                (
                    await session.execute(
                        select(AnsichTaskUsageRow).where(
                            AnsichTaskUsageRow.task_id == task_id,
                            AnsichTaskUsageRow.aggregation_scope == "local",
                        )
                    )
                ).scalars()
            )
        rows.sort(key=lambda row: _USAGE_DIMENSION_ORDER[row.dimension])
        return TaskUsageView(
            task_id=task_id,
            local=tuple(
                TaskUsageValue(
                    dimension=row.dimension,
                    aggregation_scope="local",
                    value=row.value,
                    as_of=_as_utc(row.as_of),
                    complete_through_ingest_seq=row.complete_through_ingest_seq,
                )
                for row in rows
            ),
        )

    async def get_task_budgets(self, task_id: str) -> TaskBudgetsView:
        async with self._session_factory() as session:
            rows = list((await session.execute(select(AnsichTaskBudgetRow).where(AnsichTaskBudgetRow.task_id == task_id))).scalars())
        rows.sort(
            key=lambda row: (
                _USAGE_DIMENSION_ORDER[row.dimension],
                row.aggregation_scope,
            )
        )
        return TaskBudgetsView(
            task_id=task_id,
            budgets=tuple(
                TaskBudgetView(
                    entity_id=row.entity_id,
                    task_id=row.task_id,
                    dimension=row.dimension,
                    aggregation_scope=row.aggregation_scope,
                    warning_limit=row.warning_limit,
                    hard_limit=row.hard_limit,
                    enforcement=row.enforcement,
                    source_kind=cast(BudgetSourceKind, row.source_kind),
                    requested_value=row.requested_value,
                    effective_value=row.effective_value,
                    configured_obs_id=row.configured_obs_id,
                )
                for row in rows
            ),
        )

    async def get_task_heartbeat(self, task_id: str) -> TaskHeartbeatView | None:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(AnsichTaskHeartbeatRow)
                .where(AnsichTaskHeartbeatRow.task_id == task_id)
                .order_by(
                    AnsichTaskHeartbeatRow.occurred_at.desc(),
                    AnsichTaskHeartbeatRow.heartbeat_obs_id.desc(),
                )
                .limit(1)
            )
        if row is None:
            return None
        return TaskHeartbeatView(
            task_id=row.task_id,
            heartbeat_obs_id=row.heartbeat_obs_id,
            occurred_at=_as_utc(row.occurred_at),
            producer_instance_id=row.producer_instance_id,
            ownership_epoch=row.ownership_epoch,
            elapsed_ms=row.elapsed_ms,
        )

    async def assess_operations(
        self,
        *,
        now: datetime | None = None,
        incomplete_task_ids: tuple[str, ...] = (),
        global_loss: bool = False,
        lost_ranges: tuple[LostRange, ...] = (),
    ) -> int:
        asserted_at = datetime.now(UTC) if now is None else now
        incomplete_tasks = frozenset(incomplete_task_ids)
        changed = 0
        async with self._session_factory() as session, session.begin():
            task_ids = tuple((await session.execute(select(AnsichTaskSummaryRow.task_id).where(AnsichTaskSummaryRow.control_value == "running"))).scalars())
            for task_id in task_ids:
                heartbeat_row = await session.scalar(
                    select(AnsichTaskHeartbeatRow)
                    .where(AnsichTaskHeartbeatRow.task_id == task_id)
                    .order_by(
                        AnsichTaskHeartbeatRow.occurred_at.desc(),
                        AnsichTaskHeartbeatRow.heartbeat_obs_id.desc(),
                    )
                    .limit(1)
                )
                heartbeat = None
                if heartbeat_row is not None:
                    heartbeat = TaskHeartbeatView(
                        task_id=heartbeat_row.task_id,
                        heartbeat_obs_id=heartbeat_row.heartbeat_obs_id,
                        occurred_at=_as_utc(heartbeat_row.occurred_at),
                        producer_instance_id=heartbeat_row.producer_instance_id,
                        ownership_epoch=heartbeat_row.ownership_epoch,
                        elapsed_ms=heartbeat_row.elapsed_ms,
                    )
                belief = assess_heartbeat(
                    heartbeat,
                    now=asserted_at,
                    stale_after_seconds=self._heartbeat_stale_after_seconds,
                )
                current = await session.get(
                    AnsichCurrentBeliefRow,
                    (task_id, "heartbeat"),
                )
                current_assertion = None
                current_evidence: tuple[str, ...] = ()
                if current is not None:
                    current_assertion = await session.get(
                        AnsichBeliefAssertionRow,
                        current.assertion_id,
                    )
                    current_evidence = tuple((await session.execute(select(AnsichBeliefEvidenceRow.obs_id).where(AnsichBeliefEvidenceRow.assertion_id == current.assertion_id).order_by(AnsichBeliefEvidenceRow.ordinal))).scalars())
                if current_assertion is not None and current_assertion.value_json == {"value": belief.value} and current_evidence == belief.evidence_obs_ids and current is not None and current.resolver_version == belief.selected_by.version:
                    continue
                assertion = AnsichBeliefAssertionRow(
                    assertion_id=new_id(),
                    subject_id=task_id,
                    field_name="heartbeat",
                    value_json={"value": belief.value},
                    as_of=belief.as_of or asserted_at,
                    asserted_at=belief.asserted_at,
                    source_name=belief.source.name,
                    source_version=belief.source.version,
                    fidelity_class=belief.fidelity_class,
                )
                session.add(assertion)
                for ordinal, obs_id in enumerate(belief.evidence_obs_ids):
                    session.add(
                        AnsichBeliefEvidenceRow(
                            assertion_id=assertion.assertion_id,
                            obs_id=obs_id,
                            evidence_role="supporting",
                            ordinal=ordinal,
                        )
                    )
                if current is None:
                    session.add(
                        AnsichCurrentBeliefRow(
                            subject_id=task_id,
                            field_name="heartbeat",
                            assertion_id=assertion.assertion_id,
                            resolver_name=belief.selected_by.name,
                            resolver_version=belief.selected_by.version,
                        )
                    )
                else:
                    current.assertion_id = assertion.assertion_id
                    current.resolver_name = belief.selected_by.name
                    current.resolver_version = belief.selected_by.version
                changed += 1
            budget_rows = list((await session.execute(_periodic_budget_rows_statement())).scalars())
            changed += await self._assess_budget_rows(
                session,
                budget_rows=budget_rows,
                asserted_at=asserted_at,
                incomplete_tasks=incomplete_tasks,
                global_loss=global_loss,
            )
        await self._refresh_active_task_read_model(
            now=asserted_at,
            lost_ranges=lost_ranges,
        )
        return changed

    async def _assess_budget_rows(
        self,
        session: AsyncSession,
        *,
        budget_rows: list[AnsichTaskBudgetRow],
        asserted_at: datetime,
        incomplete_tasks: frozenset[str],
        global_loss: bool,
    ) -> int:
        changed = 0
        for budget_row in budget_rows:
            usage_row = await session.get(
                AnsichTaskUsageRow,
                (
                    budget_row.task_id,
                    budget_row.dimension,
                    budget_row.aggregation_scope,
                ),
            )
            budget = TaskBudgetView(
                entity_id=budget_row.entity_id,
                task_id=budget_row.task_id,
                dimension=budget_row.dimension,
                aggregation_scope=budget_row.aggregation_scope,
                warning_limit=budget_row.warning_limit,
                hard_limit=budget_row.hard_limit,
                enforcement=budget_row.enforcement,
                source_kind=cast(BudgetSourceKind, budget_row.source_kind),
                requested_value=budget_row.requested_value,
                effective_value=budget_row.effective_value,
                configured_obs_id=budget_row.configured_obs_id,
            )
            usage = None
            usage_evidence: tuple[str, ...] = ()
            if usage_row is not None:
                usage = TaskUsageValue(
                    dimension=usage_row.dimension,
                    aggregation_scope=usage_row.aggregation_scope,
                    value=usage_row.value,
                    as_of=_as_utc(usage_row.as_of),
                    complete_through_ingest_seq=usage_row.complete_through_ingest_seq,
                )
                usage_evidence = tuple(
                    (
                        await session.execute(
                            select(AnsichUsageContributionRow.source_obs_id)
                            .where(
                                AnsichUsageContributionRow.task_id == budget_row.task_id,
                                AnsichUsageContributionRow.dimension == budget_row.dimension,
                            )
                            .order_by(
                                AnsichUsageContributionRow.as_of,
                                AnsichUsageContributionRow.source_obs_id,
                            )
                        )
                    ).scalars()
                )
            belief = assess_budget_health(
                budget,
                usage,
                now=asserted_at,
                usage_complete=(not global_loss and budget_row.task_id not in incomplete_tasks),
                usage_evidence_obs_ids=usage_evidence,
            )
            field_name = f"budget_health:{belief.dimension}:{belief.aggregation_scope}"
            value_json = {
                "value": belief.value,
                "dimension": belief.dimension,
                "aggregation_scope": belief.aggregation_scope,
                "usage_value": belief.usage_value,
                "warning_limit": belief.warning_limit,
                "hard_limit": belief.hard_limit,
                "overshoot": belief.overshoot,
                "as_of_known": belief.as_of is not None,
            }
            current = await session.get(
                AnsichCurrentBeliefRow,
                (budget_row.task_id, field_name),
            )
            current_assertion = None
            current_evidence: tuple[str, ...] = ()
            if current is not None:
                current_assertion = await session.get(
                    AnsichBeliefAssertionRow,
                    current.assertion_id,
                )
                current_evidence = tuple((await session.execute(select(AnsichBeliefEvidenceRow.obs_id).where(AnsichBeliefEvidenceRow.assertion_id == current.assertion_id).order_by(AnsichBeliefEvidenceRow.ordinal))).scalars())
            if current_assertion is not None and current_assertion.value_json == value_json and current_evidence == belief.evidence_obs_ids and current is not None and current.resolver_version == belief.selected_by.version:
                continue
            assertion = AnsichBeliefAssertionRow(
                assertion_id=new_id(),
                subject_id=budget_row.task_id,
                field_name=field_name,
                value_json=value_json,
                as_of=belief.as_of or asserted_at,
                asserted_at=belief.asserted_at,
                source_name=belief.source.name,
                source_version=belief.source.version,
                fidelity_class=belief.fidelity_class,
            )
            session.add(assertion)
            for ordinal, obs_id in enumerate(belief.evidence_obs_ids):
                session.add(
                    AnsichBeliefEvidenceRow(
                        assertion_id=assertion.assertion_id,
                        obs_id=obs_id,
                        evidence_role="supporting",
                        ordinal=ordinal,
                    )
                )
            if current is None:
                session.add(
                    AnsichCurrentBeliefRow(
                        subject_id=budget_row.task_id,
                        field_name=field_name,
                        assertion_id=assertion.assertion_id,
                        resolver_name=belief.selected_by.name,
                        resolver_version=belief.selected_by.version,
                    )
                )
            else:
                current.assertion_id = assertion.assertion_id
                current.resolver_name = belief.selected_by.name
                current.resolver_version = belief.selected_by.version
            changed += 1
        return changed

    async def get_task_heartbeat_belief(
        self,
        task_id: str,
        *,
        now: datetime | None = None,
    ) -> HeartbeatBelief | None:
        async with self._session_factory() as session:
            current = await session.get(
                AnsichCurrentBeliefRow,
                (task_id, "heartbeat"),
            )
            if current is None:
                return None
            assertion = await session.get(
                AnsichBeliefAssertionRow,
                current.assertion_id,
            )
            if assertion is None:
                return None
            evidence = tuple((await session.execute(select(AnsichBeliefEvidenceRow.obs_id).where(AnsichBeliefEvidenceRow.assertion_id == assertion.assertion_id).order_by(AnsichBeliefEvidenceRow.ordinal))).scalars())
            value = str(assertion.value_json["value"])
            as_of = None if value == "unknown" else _as_utc(assertion.as_of)
            age_reference = _as_utc(assertion.asserted_at) if now is None else now
            age_ms = None if as_of is None else max(0, int((age_reference - as_of).total_seconds() * 1000))
            return HeartbeatBelief(
                value=cast(Literal["unknown", "fresh", "stale"], value),
                as_of=as_of,
                asserted_at=_as_utc(assertion.asserted_at),
                age_ms=age_ms,
                source=NamedVersion(
                    name=assertion.source_name,
                    version=assertion.source_version,
                ),
                fidelity_class="rule",
                selected_by=NamedVersion(
                    name=current.resolver_name,
                    version=current.resolver_version,
                ),
                evidence_obs_ids=evidence,
            )

    async def get_task_budget_health(
        self,
        task_id: str,
    ) -> tuple[BudgetHealthBelief, ...]:
        async with self._session_factory() as session:
            rows = list(
                (
                    await session.execute(
                        select(AnsichCurrentBeliefRow, AnsichBeliefAssertionRow)
                        .join(
                            AnsichBeliefAssertionRow,
                            AnsichBeliefAssertionRow.assertion_id == AnsichCurrentBeliefRow.assertion_id,
                        )
                        .where(
                            AnsichCurrentBeliefRow.subject_id == task_id,
                            AnsichCurrentBeliefRow.field_name.like("budget_health:%"),
                        )
                    )
                ).all()
            )
            beliefs: list[BudgetHealthBelief] = []
            for current, assertion in rows:
                evidence = tuple((await session.execute(select(AnsichBeliefEvidenceRow.obs_id).where(AnsichBeliefEvidenceRow.assertion_id == assertion.assertion_id).order_by(AnsichBeliefEvidenceRow.ordinal))).scalars())
                value_json = assertion.value_json
                beliefs.append(
                    BudgetHealthBelief(
                        dimension=value_json["dimension"],
                        aggregation_scope=value_json["aggregation_scope"],
                        value=value_json["value"],
                        usage_value=value_json.get("usage_value"),
                        warning_limit=value_json.get("warning_limit"),
                        hard_limit=value_json.get("hard_limit"),
                        overshoot=value_json.get("overshoot"),
                        as_of=(_as_utc(assertion.as_of) if value_json.get("as_of_known") else None),
                        asserted_at=_as_utc(assertion.asserted_at),
                        source=NamedVersion(
                            name=assertion.source_name,
                            version=assertion.source_version,
                        ),
                        fidelity_class="rule",
                        selected_by=NamedVersion(
                            name=current.resolver_name,
                            version=current.resolver_version,
                        ),
                        evidence_obs_ids=evidence,
                    )
                )
        beliefs.sort(
            key=lambda item: (
                _USAGE_DIMENSION_ORDER[item.dimension],
                item.aggregation_scope,
            )
        )
        return tuple(beliefs)

    async def _refresh_active_task_read_model(
        self,
        *,
        now: datetime,
        lost_ranges: tuple[LostRange, ...],
    ) -> None:
        async with self._session_factory() as session:
            running_task_ids = tuple((await session.execute(select(AnsichTaskSummaryRow.task_id).where(AnsichTaskSummaryRow.control_value == "running"))).scalars())

        views: list[ActiveTaskView] = []
        metrics = self.get_projection_metrics()
        for task_id in running_task_ids:
            task = await self.get_task(task_id)
            if task is None:
                continue
            heartbeat = await self.get_task_heartbeat_belief(task_id, now=now)
            if heartbeat is None:
                heartbeat = assess_heartbeat(
                    None,
                    now=now,
                    stale_after_seconds=self._heartbeat_stale_after_seconds,
                )
            usage = await self.get_task_usage(task_id)
            budgets = await self.get_task_budgets(task_id)
            budget_health = await self.get_task_budget_health(task_id)
            async with self._session_factory() as session:
                scope_rows = list(
                    (
                        await session.execute(
                            select(AnsichScopeRow)
                            .join(
                                AnsichRelationRow,
                                AnsichRelationRow.object_id == AnsichScopeRow.entity_id,
                            )
                            .where(
                                AnsichRelationRow.subject_id == task_id,
                                AnsichRelationRow.predicate == "within_scope",
                            )
                        )
                    ).scalars()
                )
                scopes = {row.scope_kind: row.scope_value for row in scope_rows}
                step = await session.scalar(
                    select(AnsichStepRow)
                    .where(
                        AnsichStepRow.task_id == task_id,
                        AnsichStepRow.status.not_in(("closed", "model_failed")),
                    )
                    .order_by(AnsichStepRow.step_seq.desc())
                    .limit(1)
                )
                tool = None
                if step is not None:
                    tool = await session.scalar(
                        select(AnsichToolCallRow)
                        .where(
                            AnsichToolCallRow.step_id == step.entity_id,
                            AnsichToolCallRow.execution_status.in_(("issued", "acting")),
                        )
                        .order_by(AnsichToolCallRow.call_seq.desc())
                        .limit(1)
                    )
                evidence_obs_id = None
                if tool is not None:
                    evidence_obs_id = tool.started_obs_id or tool.issued_obs_id
                if evidence_obs_id is None and step is not None:
                    evidence_obs_id = step.started_obs_id
                action_observation = None if evidence_obs_id is None else await session.scalar(select(AnsichObservationRow).where(AnsichObservationRow.obs_id == evidence_obs_id))
                running_transition = await session.scalar(
                    select(AnsichTransitionRow)
                    .where(
                        AnsichTransitionRow.subject_id == task_id,
                        AnsichTransitionRow.field_name == "control",
                        AnsichTransitionRow.to_value == "running",
                    )
                    .order_by(AnsichTransitionRow.occurred_at.desc())
                    .limit(1)
                )
                last_evidence_at = await session.scalar(select(func.max(AnsichObservationRow.occurred_at)).where(AnsichObservationRow.task_id == task_id))

            dwell = assess_dwell(
                since=(None if action_observation is None else _as_utc(action_observation.occurred_at)),
                evidence_obs_id=evidence_obs_id,
                now=now,
                long_dwell_seconds=self._long_dwell_seconds,
            )
            started_at = task.control.as_of if running_transition is None else _as_utc(running_transition.occurred_at)
            duration_ms = 0 if started_at is None else max(0, int((now - started_at).total_seconds() * 1000))
            task_lost_ranges = tuple(item for item in lost_ranges if item.task_id is None or item.task_id == task_id)
            views.append(
                ActiveTaskView(
                    task_id=task_id,
                    run_id=task.source_id,
                    source_kind=task.source_kind,
                    owner_id=scopes.get("owner"),
                    thread_id=scopes.get("thread"),
                    agent_id=None,
                    control=task.control,
                    current_step=(
                        None
                        if step is None
                        else ActiveStepView(
                            step_id=step.entity_id,
                            step_seq=step.step_seq,
                            actor_kind=step.actor_kind,
                            status=step.status,
                        )
                    ),
                    current_tool=(
                        None
                        if tool is None
                        else ActiveToolView(
                            tool_call_id=tool.entity_id,
                            tool_name=tool.tool_name,
                            call_seq=tool.call_seq,
                            status=tool.execution_status,
                        )
                    ),
                    dwell=dwell,
                    heartbeat=heartbeat,
                    usage=usage,
                    budgets=budgets,
                    budget_health=budget_health,
                    duration_ms=duration_ms,
                    observability_status=task.observability_status,
                    projection_watermark=metrics.get("watermark"),
                    projection_lag_ms=int(metrics.get("lag_ms", 0)),
                    lost_ranges=task_lost_ranges,
                    last_evidence_at=(task.control.as_of if last_evidence_at is None else _as_utc(last_evidence_at)),
                    updated_at=now,
                )
            )

        async with self._session_factory() as session, session.begin():
            if running_task_ids:
                await session.execute(delete(AnsichActiveTaskReadModelRow).where(AnsichActiveTaskReadModelRow.task_id.not_in(running_task_ids)))
            else:
                await session.execute(delete(AnsichActiveTaskReadModelRow))
            for view in views:
                budget_status = "unknown"
                for candidate in ("exceeded", "warning", "unknown", "within"):
                    if any(belief.value == candidate for belief in view.budget_health):
                        budget_status = candidate
                        break
                values = {
                    "run_id": view.run_id,
                    "source_kind": view.source_kind,
                    "owner_id": view.owner_id,
                    "thread_id": view.thread_id,
                    "agent_id": view.agent_id,
                    "control_value": view.control.value,
                    "current_step_id": (None if view.current_step is None else view.current_step.step_id),
                    "current_tool_call_id": (None if view.current_tool is None else view.current_tool.tool_call_id),
                    "heartbeat_value": view.heartbeat.value,
                    "budget_status": budget_status,
                    "duration_ms": view.duration_ms,
                    "observability_status": view.observability_status,
                    "projection_watermark": view.projection_watermark,
                    "projection_lag_ms": view.projection_lag_ms,
                    "control_json": view.control.model_dump(mode="json"),
                    "current_step_json": (None if view.current_step is None else view.current_step.model_dump(mode="json")),
                    "current_tool_json": (None if view.current_tool is None else view.current_tool.model_dump(mode="json")),
                    "dwell_json": view.dwell.model_dump(mode="json"),
                    "heartbeat_json": view.heartbeat.model_dump(mode="json"),
                    "usage_json": view.usage.model_dump(mode="json"),
                    "budgets_json": view.budgets.model_dump(mode="json"),
                    "budget_health_json": [item.model_dump(mode="json") for item in view.budget_health],
                    "lost_ranges_json": [item.model_dump(mode="json") for item in view.lost_ranges],
                    "last_evidence_at": view.last_evidence_at,
                }
                row = await session.get(
                    AnsichActiveTaskReadModelRow,
                    view.task_id,
                )
                if row is None:
                    session.add(
                        AnsichActiveTaskReadModelRow(
                            task_id=view.task_id,
                            updated_at=view.updated_at,
                            **values,
                        )
                    )
                elif any(not _read_model_values_equal(getattr(row, key), value) for key, value in values.items()):
                    for key, value in values.items():
                        setattr(row, key, value)
                    row.updated_at = view.updated_at

    async def list_active_tasks(
        self,
        *,
        limit: int = 100,
        owner_id: str | None = None,
        agent_id: str | None = None,
        control: ControlValue | None = None,
        heartbeat_status: str | None = None,
        budget_status: str | None = None,
        min_duration_ms: int | None = None,
        max_duration_ms: int | None = None,
        observability_status: str | None = None,
        cursor: tuple[datetime, str] | None = None,
    ) -> list[ActiveTaskView]:
        if limit < 1:
            raise ValueError("limit must be positive")
        statement = select(AnsichActiveTaskReadModelRow)
        if owner_id is not None:
            statement = statement.where(AnsichActiveTaskReadModelRow.owner_id == owner_id)
        if agent_id is not None:
            statement = statement.where(AnsichActiveTaskReadModelRow.agent_id == agent_id)
        if control is not None:
            statement = statement.where(AnsichActiveTaskReadModelRow.control_value == control)
        if heartbeat_status is not None:
            statement = statement.where(AnsichActiveTaskReadModelRow.heartbeat_value == heartbeat_status)
        if budget_status is not None:
            statement = statement.where(AnsichActiveTaskReadModelRow.budget_status == budget_status)
        if min_duration_ms is not None:
            statement = statement.where(AnsichActiveTaskReadModelRow.duration_ms >= min_duration_ms)
        if max_duration_ms is not None:
            statement = statement.where(AnsichActiveTaskReadModelRow.duration_ms <= max_duration_ms)
        if observability_status is not None:
            statement = statement.where(AnsichActiveTaskReadModelRow.observability_status == observability_status)
        if cursor is not None:
            cursor_time, cursor_task_id = cursor
            statement = statement.where(
                or_(
                    AnsichActiveTaskReadModelRow.last_evidence_at < cursor_time,
                    and_(
                        AnsichActiveTaskReadModelRow.last_evidence_at == cursor_time,
                        AnsichActiveTaskReadModelRow.task_id > cursor_task_id,
                    ),
                )
            )
        statement = statement.order_by(
            AnsichActiveTaskReadModelRow.last_evidence_at.desc(),
            AnsichActiveTaskReadModelRow.task_id,
        ).limit(limit)
        async with self._session_factory() as session:
            rows = list((await session.execute(statement)).scalars())
        return [self._active_task_view(row) for row in rows]

    @staticmethod
    def _active_task_view(row: AnsichActiveTaskReadModelRow) -> ActiveTaskView:
        def strict_model(model_type, value):
            return model_type.model_validate_json(json.dumps(value))

        return ActiveTaskView(
            task_id=row.task_id,
            run_id=row.run_id,
            source_kind=row.source_kind,
            owner_id=row.owner_id,
            thread_id=row.thread_id,
            agent_id=row.agent_id,
            control=ControlBelief.model_validate(row.control_json),
            current_step=(None if row.current_step_json is None else strict_model(ActiveStepView, row.current_step_json)),
            current_tool=(None if row.current_tool_json is None else strict_model(ActiveToolView, row.current_tool_json)),
            dwell=strict_model(DwellBelief, row.dwell_json),
            heartbeat=strict_model(HeartbeatBelief, row.heartbeat_json),
            usage=strict_model(TaskUsageView, row.usage_json),
            budgets=strict_model(TaskBudgetsView, row.budgets_json),
            budget_health=tuple(strict_model(BudgetHealthBelief, item) for item in row.budget_health_json),
            duration_ms=row.duration_ms,
            observability_status=row.observability_status,
            projection_watermark=row.projection_watermark,
            projection_lag_ms=row.projection_lag_ms,
            lost_ranges=tuple(LostRange.model_validate(item) for item in row.lost_ranges_json),
            last_evidence_at=_as_utc(row.last_evidence_at),
            updated_at=_as_utc(row.updated_at),
        )

    async def list_timeline(
        self,
        task_id: str,
        *,
        limit: int,
        cursor: tuple[datetime, int] | None = None,
    ) -> list[tuple[int, ObservationEnvelope]]:
        statement = select(AnsichObservationRow).where(AnsichObservationRow.task_id == task_id)
        if cursor is not None:
            occurred_at, ingest_seq = cursor
            statement = statement.where(
                or_(
                    AnsichObservationRow.occurred_at > occurred_at,
                    and_(
                        AnsichObservationRow.occurred_at == occurred_at,
                        AnsichObservationRow.ingest_seq > ingest_seq,
                    ),
                )
            )
        async with self._session_factory() as session:
            rows = list(
                (
                    await session.execute(
                        statement.order_by(
                            AnsichObservationRow.occurred_at,
                            AnsichObservationRow.ingest_seq,
                        ).limit(limit)
                    )
                ).scalars()
            )
        return [(row.ingest_seq, self._observation_from_row(row)) for row in rows]

    async def get_max_step_seq(self, task_id: str) -> int:
        async with self._session_factory() as session:
            value = await session.scalar(select(func.max(AnsichStepRow.step_seq)).where(AnsichStepRow.task_id == task_id))
        return int(value or 0)

    async def list_content_occurrences(self, task_id: str) -> list[ContentOccurrenceView]:
        async with self._session_factory() as session:
            rows = list(
                (
                    await session.execute(
                        select(AnsichContentOccurrenceRow)
                        .where(AnsichContentOccurrenceRow.task_id == task_id)
                        .order_by(
                            AnsichContentOccurrenceRow.source_identity,
                            AnsichContentOccurrenceRow.content_hash,
                            AnsichContentOccurrenceRow.kind,
                        )
                    )
                ).scalars()
            )
        return [
            ContentOccurrenceView(
                task_id=row.task_id,
                source_identity=row.source_identity,
                content_hash=row.content_hash,
                kind=row.kind,
                block_id=row.block_id,
                producer_obs_id=row.producer_obs_id,
            )
            for row in rows
        ]

    async def get_latest_context_state(self, task_id: str) -> ContextStateView | None:
        async with self._session_factory() as session:
            state = await session.scalar(
                select(AnsichContextStateRow)
                .join(
                    AnsichObservationRow,
                    AnsichObservationRow.obs_id == AnsichContextStateRow.created_obs_id,
                )
                .where(
                    AnsichContextStateRow.task_id == task_id,
                    AnsichContextStateRow.created_obs_id.is_not(None),
                )
                .order_by(AnsichObservationRow.ingest_seq.desc())
                .limit(1)
            )
            return None if state is None else await self._context_state_view(session, state)

    async def list_steps(self, task_id: str) -> list[StepView]:
        async with self._session_factory() as session:
            rows = list((await session.execute(select(AnsichStepRow).where(AnsichStepRow.task_id == task_id).order_by(AnsichStepRow.step_seq))).scalars())
            return [await self._step_view(session, row) for row in rows]

    async def list_system_operations(self, task_id: str) -> list[LlmAttemptView]:
        async with self._session_factory() as session:
            rows = list(
                (
                    await session.execute(
                        select(AnsichLlmAttemptRow)
                        .join(
                            AnsichObservationRow,
                            AnsichObservationRow.obs_id == AnsichLlmAttemptRow.request_obs_id,
                        )
                        .where(
                            AnsichLlmAttemptRow.task_id == task_id,
                            AnsichLlmAttemptRow.step_id.is_(None),
                        )
                        .order_by(AnsichObservationRow.ingest_seq, AnsichLlmAttemptRow.attempt_no)
                    )
                ).scalars()
            )
            return [self._attempt_view(row) for row in rows]

    async def get_step(self, step_id: str) -> StepView | None:
        async with self._session_factory() as session:
            row = await session.get(AnsichStepRow, step_id)
            return None if row is None else await self._step_view(session, row)

    async def get_tool_call(self, tool_call_id: str) -> ToolCallView | None:
        async with self._session_factory() as session:
            row = await session.get(AnsichToolCallRow, tool_call_id)
            return None if row is None else await self._tool_call_view(session, row)

    async def get_step_context(self, step_id: str) -> ContextSnapshotView | None:
        async with self._session_factory() as session:
            step = await session.get(AnsichStepRow, step_id)
            if step is None or step.effective_context_snapshot_id is None:
                return None
            snapshot_id = step.effective_context_snapshot_id
        return await self.get_context_snapshot(snapshot_id)

    async def get_context_snapshot(
        self,
        snapshot_id: str,
    ) -> ContextSnapshotView | None:
        async with self._session_factory() as session:
            snapshot = await session.get(AnsichContextSnapshotRow, snapshot_id)
            if snapshot is None:
                return None
            status = snapshot.status
            if snapshot.state_id is not None:
                state = await session.get(AnsichContextStateRow, snapshot.state_id)
                state_view = None if state is None else await self._context_state_view(session, state)
                if state_view is None:
                    items: list[ContextSnapshotItemView] = []
                    status = "incomplete"
                else:
                    items = await self._context_snapshot_items_for_state(session, state_view)
                    status = "complete" if state_view.status == "complete" else "incomplete"
            else:
                item_rows = list(
                    (
                        await session.execute(
                            select(AnsichContextSnapshotItemRow, AnsichContentBlockRow)
                            .join(
                                AnsichContentBlockRow,
                                AnsichContentBlockRow.entity_id == AnsichContextSnapshotItemRow.content_block_id,
                            )
                            .where(AnsichContextSnapshotItemRow.snapshot_id == snapshot.entity_id)
                            .order_by(AnsichContextSnapshotItemRow.ordinal)
                        )
                    ).all()
                )
                missing_rows = list(
                    (await session.execute(select(AnsichContextSnapshotMissingItemRow).where(AnsichContextSnapshotMissingItemRow.snapshot_id == snapshot.entity_id).order_by(AnsichContextSnapshotMissingItemRow.ordinal))).scalars()
                )
                items = [
                    ContextSnapshotItemView(
                        ordinal=item.ordinal,
                        channel=item.channel,
                        role=item.role,
                        name=item.name,
                        message_id=item.message_id,
                        source_identity=item.source_identity,
                        block_id=block.entity_id,
                        kind=block.kind,
                        content_hash=block.content_hash,
                        visible_bytes=item.visible_bytes,
                        estimated_tokens=item.estimated_tokens,
                        metadata=item.metadata_json,
                        sensitivity_flags=tuple(block.sensitivity_flags_json),
                        payload_available=True,
                    )
                    for item, block in item_rows
                ]
                items.extend(
                    ContextSnapshotItemView(
                        ordinal=item.ordinal,
                        channel=cast(Literal["message", "tool_schema"], item.channel),
                        role=cast(Literal["system", "user", "assistant", "tool"] | None, item.role),
                        name=item.name,
                        message_id=item.message_id,
                        source_identity=item.source_identity,
                        block_id=item.expected_content_block_id,
                        kind=None,
                        content_hash=None,
                        visible_bytes=item.visible_bytes,
                        estimated_tokens=item.estimated_tokens,
                        metadata=item.metadata_json,
                        payload_available=False,
                        resolution_status="missing",
                    )
                    for item in missing_rows
                )
                items.sort(key=lambda item: item.ordinal)
            return ContextSnapshotView(
                snapshot_id=snapshot.entity_id,
                task_id=snapshot.task_id,
                step_id=snapshot.step_id,
                operation_id=snapshot.operation_id,
                attempt_no=snapshot.attempt_no,
                request_obs_id=snapshot.request_obs_id,
                message_count=snapshot.message_count,
                tool_schema_count=snapshot.tool_schema_count,
                visible_bytes=snapshot.visible_bytes,
                estimated_tokens=snapshot.estimated_tokens,
                estimator_name=snapshot.estimator_name,
                estimator_version=snapshot.estimator_version,
                adapter_name=snapshot.adapter_name,
                adapter_version=snapshot.adapter_version,
                configured_model=snapshot.configured_model,
                response_format=snapshot.response_format_json,
                generation_settings=snapshot.generation_settings_json,
                redactions=tuple(snapshot.redactions_json),
                warnings=tuple(snapshot.warnings_json),
                items=tuple(items),
                status=cast(Literal["complete", "incomplete"], status),
            )

    async def _context_state_view(
        self,
        session: AsyncSession,
        state: AnsichContextStateRow,
    ) -> ContextStateView:
        try:
            items = await self._materialize_context_state(session, state.state_id, frozenset())
        except ValueError:
            items = ()
        return ContextStateView(
            state_id=state.state_id,
            task_id=state.task_id,
            state_hash=state.state_hash or "",
            parent_state_id=state.parent_state_id,
            chain_depth=state.chain_depth,
            is_checkpoint=state.is_checkpoint,
            status=cast(Literal["complete", "incomplete", "missing"], state.status),
            items=items,
        )

    async def _materialize_context_state(
        self,
        session: AsyncSession,
        state_id: str,
        visited: frozenset[str],
    ) -> tuple[ContextStateItem, ...]:
        if state_id in visited:
            raise ValueError("ContextState parent cycle detected")
        state = await session.get(AnsichContextStateRow, state_id)
        if state is None or state.status == "missing":
            raise ValueError(f"ContextState is missing: {state_id}")
        if state.is_checkpoint:
            rows = list((await session.execute(select(AnsichContextStateCheckpointItemRow).where(AnsichContextStateCheckpointItemRow.state_id == state_id).order_by(AnsichContextStateCheckpointItemRow.ordinal))).scalars())
            return tuple(
                ContextStateItem(
                    ordinal=row.ordinal,
                    channel=cast(Literal["message", "tool_schema"], row.channel),
                    role=cast(Literal["system", "user", "assistant", "tool"] | None, row.role),
                    message_id=row.message_id,
                    source_identity=row.source_identity,
                    name=row.name,
                    block_id=row.block_id,
                    visible_bytes=row.visible_bytes,
                    estimated_tokens=row.estimated_tokens,
                    metadata=row.metadata_json,
                )
                for row in rows
            )
        if state.parent_state_id is None:
            raise ValueError(f"delta ContextState has no parent: {state_id}")
        parent = await self._materialize_context_state(session, state.parent_state_id, visited | {state_id})
        rows = list((await session.execute(select(AnsichContextStateDeltaRow).where(AnsichContextStateDeltaRow.state_id == state_id).order_by(AnsichContextStateDeltaRow.operation_ordinal))).scalars())
        operations = tuple(self._context_state_delta_from_row(row) for row in rows)
        return materialize_context_state(parent, operations, item_count=state.item_count)

    @staticmethod
    def _context_state_delta_from_row(row: AnsichContextStateDeltaRow) -> ContextStateDelta:
        item = None
        if row.block_id is not None:
            item = ContextStateItem(
                ordinal=int(row.target_ordinal or 0),
                channel=cast(Literal["message", "tool_schema"], row.channel),
                role=cast(Literal["system", "user", "assistant", "tool"] | None, row.role),
                message_id=row.message_id,
                source_identity=row.source_identity,
                name=row.name,
                block_id=row.block_id,
                visible_bytes=int(row.visible_bytes or 0),
                estimated_tokens=int(row.estimated_tokens or 0),
                metadata=dict(row.metadata_json or {}),
            )
        return ContextStateDelta(
            op=cast(Literal["append", "remove", "replace", "reorder"], row.operation),
            source_ordinal=row.source_ordinal,
            target_ordinal=row.target_ordinal,
            item=item,
        )

    async def _context_snapshot_items_for_state(
        self,
        session: AsyncSession,
        state: ContextStateView,
    ) -> list[ContextSnapshotItemView]:
        block_ids = [item.block_id for item in state.items]
        blocks: dict[str, AnsichContentBlockRow] = {}
        if block_ids:
            rows = list((await session.execute(select(AnsichContentBlockRow).where(AnsichContentBlockRow.entity_id.in_(block_ids)))).scalars())
            blocks = {row.entity_id: row for row in rows}
        return [
            ContextSnapshotItemView(
                ordinal=item.ordinal,
                channel=item.channel,
                role=item.role,
                name=item.name,
                message_id=item.message_id,
                source_identity=item.source_identity,
                block_id=item.block_id,
                kind=blocks[item.block_id].kind if item.block_id in blocks else None,
                content_hash=blocks[item.block_id].content_hash if item.block_id in blocks else None,
                visible_bytes=item.visible_bytes,
                estimated_tokens=item.estimated_tokens,
                metadata=item.metadata,
                sensitivity_flags=tuple(blocks[item.block_id].sensitivity_flags_json) if item.block_id in blocks else (),
                payload_available=item.block_id in blocks,
                resolution_status="available" if item.block_id in blocks else "missing",
            )
            for item in state.items
        ]

    async def get_content_block_payload(self, block_id: str) -> ContentBlockPayloadView | None:
        async with self._session_factory() as session:
            block = await session.get(AnsichContentBlockRow, block_id)
            if block is None:
                return None
            if block.blob_key is not None:
                blob = await session.get(AnsichContentBlobRow, block.blob_key)
                if blob is None or blob.payload_status != "available":
                    return None
                body_bytes = await self._content_blob_bytes(session, blob)
                body = body_bytes.decode("utf-8") if blob.content_type.startswith("text/plain") else json.loads(body_bytes.decode("utf-8"))
                return ContentBlockPayloadView(block_id=block_id, content_type=blob.content_type, body=body)
            observation = await session.scalar(select(AnsichObservationRow).where(AnsichObservationRow.obs_id == block.payload_obs_id))
            if observation is None or observation.payload_json is None or "body" not in observation.payload_json:
                if observation is None or observation.payload_ref_id is None:
                    return None
                payload = await session.get(AnsichPayloadRow, observation.payload_ref_id)
                if payload is None:
                    return None
                decoded = json.loads(payload.body.decode(payload.encoding))
                if not isinstance(decoded, dict) or "body" not in decoded:
                    return None
                return ContentBlockPayloadView(block_id=block_id, body=decoded["body"])
            return ContentBlockPayloadView(block_id=block_id, body=observation.payload_json["body"])

    async def get_context_compression(
        self,
        compression_id: str,
    ) -> ContextCompressionView | None:
        async with self._session_factory() as session:
            compression = await session.get(
                AnsichContextCompressionRow,
                compression_id,
            )
            if compression is None:
                return None
            item_rows = list(
                (
                    await session.execute(
                        select(AnsichContextCompressionItemRow)
                        .where(AnsichContextCompressionItemRow.compression_id == compression_id)
                        .order_by(
                            case(
                                (AnsichContextCompressionItemRow.disposition == "source", 0),
                                (AnsichContextCompressionItemRow.disposition == "preserved", 1),
                                else_=2,
                            ),
                            AnsichContextCompressionItemRow.ordinal,
                        )
                    )
                ).scalars()
            )
            summary_block_id = compression.summary_block_id
            task_id = compression.task_id
            operation_id = compression.operation_id
            before_tokens = compression.before_tokens
            after_tokens = compression.after_tokens
            before_visible_bytes = compression.before_visible_bytes
            after_visible_bytes = compression.after_visible_bytes
            algorithm = compression.algorithm
            algorithm_version = compression.algorithm_version
            source_obs_id = compression.source_obs_id
            stored_status = compression.status

        block_ids = tuple(dict.fromkeys([summary_block_id, *[item.block_id for item in item_rows]]))
        blocks = {block.block_id: block for block in await self.get_content_blocks(block_ids)}
        summary_block = blocks.get(summary_block_id)
        if summary_block is None:
            return None
        items = tuple(
            ContextCompressionItemView(
                disposition=cast(CompressionDisposition, item.disposition),
                ordinal=item.ordinal,
                block=blocks[item.block_id],
            )
            for item in item_rows
            if item.block_id in blocks
        )
        status = "complete" if stored_status == "complete" and len(items) == len(item_rows) else "incomplete"
        return ContextCompressionView(
            compression_id=compression_id,
            task_id=task_id,
            summary_operation_id=operation_id,
            summary_block=summary_block,
            before_tokens=before_tokens,
            after_tokens=after_tokens,
            before_visible_bytes=before_visible_bytes,
            after_visible_bytes=after_visible_bytes,
            algorithm=algorithm,
            algorithm_version=algorithm_version,
            source_obs_id=source_obs_id,
            status=cast(Literal["complete", "incomplete"], status),
            items=items,
        )

    async def get_content_blocks(
        self,
        block_ids: tuple[str, ...],
    ) -> list[ContentBlockView]:
        if not block_ids:
            return []
        async with self._session_factory() as session:
            rows = list(
                (
                    await session.execute(
                        select(
                            AnsichContentBlockRow,
                            AnsichBlockProducerRow,
                            AnsichObservationRow,
                            AnsichContentBlobRow,
                        )
                        .outerjoin(
                            AnsichBlockProducerRow,
                            AnsichBlockProducerRow.block_id == AnsichContentBlockRow.entity_id,
                        )
                        .join(
                            AnsichObservationRow,
                            AnsichObservationRow.obs_id == AnsichContentBlockRow.producer_obs_id,
                        )
                        .outerjoin(
                            AnsichContentBlobRow,
                            AnsichContentBlobRow.blob_key == AnsichContentBlockRow.blob_key,
                        )
                        .where(AnsichContentBlockRow.entity_id.in_(block_ids))
                    )
                ).all()
            )
        by_id = {
            block.entity_id: ContentBlockView(
                block_id=block.entity_id,
                kind=block.kind,
                content_hash=block.content_hash,
                byte_size=block.byte_size,
                token_estimate=block.token_estimate,
                sensitivity_flags=tuple(block.sensitivity_flags_json),
                payload_status=cast(
                    Literal["available", "missing"],
                    "available" if blob is None else blob.payload_status,
                ),
                producer=ContentProducerView(
                    producer_kind=(observation.producer_name if producer is None else producer.producer_kind),
                    producer_entity_id=(None if producer is None else producer.producer_entity_id),
                    producer_obs_id=(observation.obs_id if producer is None else producer.producer_obs_id),
                ),
            )
            for block, producer, observation, blob in rows
        }
        return [by_id[block_id] for block_id in block_ids if block_id in by_id]

    async def list_content_derivations(
        self,
        block_ids: tuple[str, ...],
        direction: LineageDirection,
    ) -> list[ContentDerivationView]:
        if not block_ids:
            return []
        endpoint = AnsichContentBlockDerivationRow.derived_block_id if direction == "backward" else AnsichContentBlockDerivationRow.source_block_id
        async with self._session_factory() as session:
            rows = list(
                (
                    await session.execute(
                        select(AnsichContentBlockDerivationRow)
                        .where(endpoint.in_(block_ids))
                        .order_by(
                            AnsichContentBlockDerivationRow.derived_block_id,
                            AnsichContentBlockDerivationRow.source_block_id,
                            AnsichContentBlockDerivationRow.transform_kind,
                        )
                    )
                ).scalars()
            )
        return [
            ContentDerivationView(
                derived_block_id=row.derived_block_id,
                source_block_id=row.source_block_id,
                transform_kind=cast(ToolTransformKind, row.transform_kind),
                transform_version=row.transform_version,
                established_obs_id=row.established_obs_id,
                source_role=cast(ContentDerivationSourceRole, row.source_role),
                ordinal=row.ordinal,
            )
            for row in rows
        ]

    async def list_snapshot_exposures(
        self,
        root_block_id: str,
        descendant_block_ids: tuple[str, ...],
    ) -> list[PossibleExposureItemView]:
        if not descendant_block_ids:
            return []
        async with self._session_factory() as session:
            root_block = await session.get(AnsichContentBlockRow, root_block_id)
            if root_block is None:
                return []
            root_observation = await session.scalar(select(AnsichObservationRow).where(AnsichObservationRow.obs_id == root_block.producer_obs_id))
            if root_observation is None:
                return []
            rows = list(
                (
                    await session.execute(
                        select(
                            AnsichContextSnapshotBlockMembershipRow,
                            AnsichContextSnapshotRow,
                            AnsichStepRow,
                            AnsichObservationRow,
                        )
                        .join(
                            AnsichContextSnapshotRow,
                            AnsichContextSnapshotRow.entity_id == AnsichContextSnapshotBlockMembershipRow.snapshot_id,
                        )
                        .join(
                            AnsichStepRow,
                            AnsichStepRow.entity_id == AnsichContextSnapshotRow.step_id,
                        )
                        .join(
                            AnsichObservationRow,
                            AnsichObservationRow.obs_id == AnsichContextSnapshotRow.request_obs_id,
                        )
                        .where(AnsichContextSnapshotBlockMembershipRow.content_block_id.in_(descendant_block_ids))
                        .order_by(
                            AnsichStepRow.step_seq,
                            AnsichContextSnapshotRow.entity_id,
                            AnsichContextSnapshotBlockMembershipRow.ordinal,
                            AnsichContextSnapshotBlockMembershipRow.content_block_id,
                        )
                    )
                ).all()
            )
        return [
            PossibleExposureItemView(
                task_id=snapshot.task_id,
                step_id=step.entity_id,
                step_seq=step.step_seq,
                snapshot_id=snapshot.entity_id,
                snapshot_ordinal=item.ordinal,
                descendant_block_id=item.content_block_id,
                ordering=("later" if request.occurred_at > root_observation.occurred_at else "unknown"),
            )
            for item, snapshot, step, request in rows
        ]

    @staticmethod
    async def _content_blob_bytes(session: AsyncSession, blob: AnsichContentBlobRow) -> bytes:
        if blob.inline_body is not None:
            return bytes(blob.inline_body)
        if blob.payload_ref_id is None:
            raise ValueError(f"Ansich ContentBlob has no payload: {blob.blob_key}")
        payload = await session.get(AnsichPayloadRow, blob.payload_ref_id)
        if payload is None:
            raise ValueError(f"Ansich ContentBlob payload disappeared: {blob.payload_ref_id}")
        return bytes(payload.body)

    @staticmethod
    async def _step_view(session: AsyncSession, step: AnsichStepRow) -> StepView:
        attempt_rows = list((await session.execute(select(AnsichLlmAttemptRow).where(AnsichLlmAttemptRow.step_id == step.entity_id).order_by(AnsichLlmAttemptRow.attempt_no))).scalars())
        attempts = tuple(
            SqlAnsichBackend._attempt_view(
                attempt,
                effective=attempt.attempt_no == step.effective_attempt_no and attempt.status == "success",
            )
            for attempt in attempt_rows
        )
        tool_rows = list((await session.execute(select(AnsichToolCallRow).where(AnsichToolCallRow.step_id == step.entity_id).order_by(AnsichToolCallRow.call_seq))).scalars())
        tool_calls = tuple([await SqlAnsichBackend._tool_call_view(session, row) for row in tool_rows])
        return StepView(
            step_id=step.entity_id,
            task_id=step.task_id,
            step_seq=step.step_seq,
            actor_kind=step.actor_kind,
            status=step.status,
            result=step.result,
            started_obs_id=step.started_obs_id,
            closed_obs_id=step.closed_obs_id,
            effective_attempt_no=step.effective_attempt_no,
            effective_context_snapshot_id=step.effective_context_snapshot_id,
            issued_tools=tuple(step.issued_tools_json),
            attempts=attempts,
            tool_calls=tool_calls,
        )

    @staticmethod
    async def _tool_call_view(
        session: AsyncSession,
        tool_call: AnsichToolCallRow,
    ) -> ToolCallView:
        step = await session.get(AnsichStepRow, tool_call.step_id)
        if step is None:
            raise ValueError(f"Ansich ToolCall step disappeared: {tool_call.step_id}")
        observation_ids = tuple(
            observation_id
            for observation_id in (
                tool_call.issued_obs_id,
                tool_call.started_obs_id,
                tool_call.raw_terminal_obs_id,
                tool_call.visible_result_obs_id,
            )
            if observation_id is not None
        )
        observations: dict[str, AnsichObservationRow] = {}
        if observation_ids:
            rows = list((await session.execute(select(AnsichObservationRow).where(AnsichObservationRow.obs_id.in_(observation_ids)))).scalars())
            observations = {row.obs_id: row for row in rows}

        result_rows = list(
            (
                await session.execute(
                    select(AnsichToolCallResultRow)
                    .where(AnsichToolCallResultRow.tool_call_id == tool_call.entity_id)
                    .order_by(
                        AnsichToolCallResultRow.result_role,
                        AnsichToolCallResultRow.source_obs_id,
                    )
                )
            ).scalars()
        )
        block_ids = tuple({row.content_block_id for row in result_rows})
        blocks: dict[str, AnsichContentBlockRow] = {}
        if block_ids:
            block_rows = list((await session.execute(select(AnsichContentBlockRow).where(AnsichContentBlockRow.entity_id.in_(block_ids)))).scalars())
            blocks = {row.entity_id: row for row in block_rows}
        results = tuple(
            ToolResultView(
                result_role=cast(Literal["raw", "visible"], result.result_role),
                content_block_id=result.content_block_id,
                source_obs_id=result.source_obs_id,
                content_hash=(blocks[result.content_block_id].content_hash if result.content_block_id in blocks else None),
                byte_size=(blocks[result.content_block_id].byte_size if result.content_block_id in blocks else None),
                payload_available=result.content_block_id in blocks,
                metadata=dict(result.metadata_json),
            )
            for result in result_rows
        )
        visible_block_ids = tuple(result.content_block_id for result in result_rows if result.result_role == "visible")
        derivation_rows: list[AnsichContentBlockDerivationRow] = []
        if visible_block_ids:
            derivation_rows = list(
                (
                    await session.execute(
                        select(AnsichContentBlockDerivationRow)
                        .where(AnsichContentBlockDerivationRow.derived_block_id.in_(visible_block_ids))
                        .order_by(
                            AnsichContentBlockDerivationRow.derived_block_id,
                            AnsichContentBlockDerivationRow.source_block_id,
                        )
                    )
                ).scalars()
            )

        issued = observations.get(tool_call.issued_obs_id or "")
        started = observations.get(tool_call.started_obs_id or "")
        terminal = observations.get(tool_call.raw_terminal_obs_id or "")
        visible = observations.get(tool_call.visible_result_obs_id or "")
        fallback = issued or started or terminal or visible
        asserted_at = _as_utc(fallback.recorded_at) if fallback is not None else datetime.now(UTC)

        def belief(
            value: str,
            evidence: AnsichObservationRow | None,
            *,
            resolver: str,
        ) -> ToolBelief:
            return ToolBelief(
                value=value,
                as_of=None if evidence is None else _as_utc(evidence.occurred_at),
                asserted_at=(asserted_at if evidence is None else _as_utc(evidence.recorded_at)),
                source=NamedVersion(
                    name="tool-accountability" if evidence is None else evidence.producer_name,
                    version="1" if evidence is None else evidence.producer_version,
                ),
                selected_by=NamedVersion(name=resolver, version="1"),
                evidence_obs_ids=() if evidence is None else (evidence.obs_id,),
            )

        authorization_evidence = terminal if tool_call.execution_status == "denied" else None
        return ToolCallView(
            tool_call_id=tool_call.entity_id,
            task_id=tool_call.task_id,
            step_id=tool_call.step_id,
            step_seq=step.step_seq,
            call_seq=tool_call.call_seq,
            provider_call_id=tool_call.provider_call_id,
            tool_name=tool_call.tool_name,
            args_hash=tool_call.args_hash,
            args_preview={} if tool_call.args_preview_json is None else tool_call.args_preview_json,
            tool_schema_block_id=tool_call.tool_schema_block_id,
            issued_obs_id=tool_call.issued_obs_id,
            started_obs_id=tool_call.started_obs_id,
            raw_terminal_obs_id=tool_call.raw_terminal_obs_id,
            visible_result_obs_id=tool_call.visible_result_obs_id,
            duration_ms=tool_call.duration_ms,
            authorization=belief(
                "denied" if authorization_evidence is not None else "unknown",
                authorization_evidence,
                resolver="tool-authorization-state",
            ),
            execution=belief(
                tool_call.execution_status,
                terminal or started or issued,
                resolver=("tool-terminal-precedence" if terminal is not None else "tool-execution-state"),
            ),
            visible_result=belief(
                tool_call.visible_result_status,
                visible,
                resolver="tool-visible-result-state",
            ),
            raw_results=tuple(result for result in results if result.result_role == "raw"),
            visible_results=tuple(result for result in results if result.result_role == "visible"),
            derivations=tuple(
                ContentDerivationView(
                    derived_block_id=row.derived_block_id,
                    source_block_id=row.source_block_id,
                    transform_kind=row.transform_kind,
                    transform_version=row.transform_version,
                    established_obs_id=row.established_obs_id,
                )
                for row in derivation_rows
            ),
        )

    @staticmethod
    def _attempt_view(attempt: AnsichLlmAttemptRow, *, effective: bool = False) -> LlmAttemptView:
        return LlmAttemptView(
            attempt_id=attempt.attempt_id,
            task_id=attempt.task_id,
            step_id=attempt.step_id,
            actor_kind=attempt.actor_kind,
            operation_id=attempt.operation_id,
            operation_kind=attempt.operation_kind,
            attempt_no=attempt.attempt_no,
            status=attempt.status,
            request_obs_id=attempt.request_obs_id,
            response_obs_id=attempt.response_obs_id,
            failure_obs_id=attempt.failure_obs_id,
            provider_model=attempt.provider_model,
            usage=dict(attempt.usage_json or {}),
            response_metadata=dict(attempt.response_metadata_json or {}),
            latency_ms=attempt.latency_ms,
            context_snapshot_id=attempt.context_snapshot_id,
            effective=effective,
        )

    @staticmethod
    def _observation_from_row(row: AnsichObservationRow) -> ObservationEnvelope:
        return ObservationEnvelope(
            obs_id=row.obs_id,
            schema_version=row.schema_version,
            kind=row.kind,
            occurred_at=_as_utc(row.occurred_at),
            recorded_at=_as_utc(row.recorded_at),
            task_id=row.task_id,
            step_id=row.step_id,
            subject_type=row.subject_type,
            subject_id=row.subject_id,
            fidelity_class=row.fidelity_class,
            producer=Producer(
                name=row.producer_name,
                version=row.producer_version,
                instance_id=row.producer_instance_id,
            ),
            producer_seq=row.producer_seq,
            source_event_id=row.source_event_id,
            correlation_id=row.correlation_id,
            causation_obs_id=row.causation_obs_id,
            payload=row.payload_json,
            payload_ref_id=row.payload_ref_id,
        )

    async def _project_structural(
        self,
        session: AsyncSession,
        observation: ObservationEnvelope,
    ) -> AnsichTaskRow | None:
        if observation.kind not in _CONTROL_BY_KIND or observation.payload is None:
            return None
        entity = await session.get(AnsichEntityRow, observation.task_id)
        task = await session.get(AnsichTaskRow, observation.task_id)
        if entity is None:
            session.add(
                AnsichEntityRow(
                    entity_id=observation.task_id,
                    entity_type="task",
                    discovered_obs_id=observation.obs_id,
                )
            )
        if task is None:
            task = AnsichTaskRow(
                entity_id=observation.task_id,
                source_kind=str(observation.payload["source_kind"]),
                source_id=str(observation.payload["source_id"]),
                trigger_obs_id=observation.obs_id,
            )
            session.add(task)
        await session.flush()
        await self._project_scopes(session, observation)
        return task

    async def _project_control(
        self,
        session: AsyncSession,
        observation: ObservationEnvelope,
        *,
        ingest_seq: int,
    ) -> None:
        task = await self._project_structural(session, observation)
        if task is None:
            return

        current = await session.get(AnsichCurrentBeliefRow, (observation.task_id, "control"))
        current_assertion = None
        if current is not None:
            current_assertion = await session.get(AnsichBeliefAssertionRow, current.assertion_id)

        assertion = AnsichBeliefAssertionRow(
            assertion_id=new_id(),
            subject_id=observation.task_id,
            field_name="control",
            value_json={"value": _CONTROL_BY_KIND[observation.kind]},
            as_of=observation.occurred_at,
            asserted_at=observation.recorded_at,
            source_name="task-control",
            source_version="1",
            fidelity_class="hard",
        )
        session.add(assertion)
        session.add(
            AnsichBeliefEvidenceRow(
                assertion_id=assertion.assertion_id,
                obs_id=observation.obs_id,
                evidence_role="supporting",
                ordinal=0,
            )
        )
        await session.flush()

        previous_value = "unknown" if current_assertion is None else str(current_assertion.value_json["value"])
        next_value = _CONTROL_BY_KIND[observation.kind]
        if not should_select_control_candidate(
            current_value=None if current_assertion is None else cast(ControlValue, previous_value),
            current_as_of=None if current_assertion is None else _as_utc(current_assertion.as_of),
            candidate_value=cast(ControlValue, next_value),
            candidate_as_of=observation.occurred_at,
        ):
            return

        session.add(
            AnsichTransitionRow(
                transition_id=new_id(),
                subject_id=observation.task_id,
                field_name="control",
                from_value=previous_value,
                to_value=next_value,
                occurred_at=observation.occurred_at,
                evidence_obs_id=observation.obs_id,
            )
        )
        if current is None:
            current = AnsichCurrentBeliefRow(
                subject_id=observation.task_id,
                field_name="control",
                assertion_id=assertion.assertion_id,
                resolver_name="control-state",
                resolver_version="1",
            )
            session.add(current)
        else:
            current.assertion_id = assertion.assertion_id

        summary = await session.get(AnsichTaskSummaryRow, observation.task_id)
        if summary is None:
            session.add(
                AnsichTaskSummaryRow(
                    task_id=observation.task_id,
                    source_kind=task.source_kind,
                    source_id=task.source_id,
                    control_value=next_value,
                    control_as_of=observation.occurred_at,
                    last_evidence_at=observation.occurred_at,
                    assertion_id=assertion.assertion_id,
                    projection_watermark=ingest_seq,
                    observability_status="healthy",
                )
            )
        else:
            summary.control_value = next_value
            summary.control_as_of = observation.occurred_at
            summary.last_evidence_at = observation.occurred_at
            summary.assertion_id = assertion.assertion_id
            summary.projection_watermark = ingest_seq
            summary.updated_at = observation.recorded_at
        if observation.kind in {
            "task.completed",
            "task.failed",
            "task.interrupted",
        }:
            await self._close_settled_acting_steps(
                session,
                task_id=observation.task_id,
                followup_observed=True,
            )
            budget_rows = list((await session.execute(select(AnsichTaskBudgetRow).where(AnsichTaskBudgetRow.task_id == observation.task_id))).scalars())
            await self._assess_budget_rows(
                session,
                budget_rows=budget_rows,
                asserted_at=observation.recorded_at,
                incomplete_tasks=frozenset(),
                global_loss=False,
            )

    async def _project_heartbeat(
        self,
        session: AsyncSession,
        observation: ObservationEnvelope,
        *,
        ingest_seq: int,
    ) -> None:
        if observation.payload is None:
            raise ValueError("task.heartbeat requires inline projection payload")
        if await session.get(AnsichTaskRow, observation.task_id) is None:
            raise _ProjectionDependencyPending(f"heartbeat observation {observation.obs_id} is waiting for Task {observation.task_id}")
        if await session.get(AnsichTaskHeartbeatRow, observation.obs_id) is not None:
            return
        session.add(
            AnsichTaskHeartbeatRow(
                heartbeat_obs_id=observation.obs_id,
                task_id=observation.task_id,
                occurred_at=observation.occurred_at,
                producer_instance_id=observation.producer.instance_id,
                ownership_epoch=str(observation.payload["ownership_epoch"]),
                elapsed_ms=max(0, int(observation.payload["elapsed_ms"])),
            )
        )
        elapsed_ms = max(0, int(observation.payload["elapsed_ms"]))
        usage = await session.get(
            AnsichTaskUsageRow,
            (observation.task_id, "wall_time_ms", "local"),
        )
        if usage is None:
            session.add(
                AnsichTaskUsageRow(
                    task_id=observation.task_id,
                    dimension="wall_time_ms",
                    aggregation_scope="local",
                    value=elapsed_ms,
                    as_of=observation.occurred_at,
                    complete_through_ingest_seq=ingest_seq,
                    updated_at=observation.recorded_at,
                )
            )
        elif elapsed_ms >= usage.value:
            usage.value = elapsed_ms
            usage.as_of = observation.occurred_at
            usage.complete_through_ingest_seq = max(
                usage.complete_through_ingest_seq,
                ingest_seq,
            )
            usage.updated_at = observation.recorded_at

    async def _project_budget(
        self,
        session: AsyncSession,
        observation: ObservationEnvelope,
    ) -> None:
        if observation.payload is None:
            raise ValueError("budget.configured requires inline projection payload")
        if await session.get(AnsichTaskRow, observation.task_id) is None:
            raise _ProjectionDependencyPending(f"budget observation {observation.obs_id} is waiting for Task {observation.task_id}")
        if await session.get(AnsichEntityRow, observation.obs_id) is None:
            session.add(
                AnsichEntityRow(
                    entity_id=observation.obs_id,
                    entity_type="task_budget",
                    discovered_obs_id=observation.obs_id,
                )
            )
            await session.flush()
        if await session.get(AnsichTaskBudgetRow, observation.obs_id) is not None:
            return
        payload = observation.payload
        session.add(
            AnsichTaskBudgetRow(
                entity_id=observation.obs_id,
                task_id=observation.task_id,
                dimension=str(payload["dimension"]),
                aggregation_scope=str(payload["aggregation_scope"]),
                warning_limit=(int(payload["warning_limit"]) if isinstance(payload.get("warning_limit"), int) else None),
                hard_limit=(int(payload["hard_limit"]) if isinstance(payload.get("hard_limit"), int) else None),
                enforcement=payload.get("enforcement") is True,
                source_kind=str(payload["source_kind"]),
                requested_value=(int(payload["requested_value"]) if isinstance(payload.get("requested_value"), int) else None),
                effective_value=int(payload["effective_value"]),
                configured_obs_id=observation.obs_id,
            )
        )

    async def _project_usage(
        self,
        session: AsyncSession,
        observation: ObservationEnvelope,
        *,
        ingest_seq: int,
    ) -> None:
        task = await session.get(AnsichTaskRow, observation.task_id)
        if task is None:
            raise _ProjectionDependencyPending(f"usage observation {observation.obs_id} is waiting for Task {observation.task_id}")

        contributions = list(usage_contributions_for_observation(observation))
        if observation.kind == "tool.started":
            tool_call = await session.get(
                AnsichToolCallRow,
                observation.subject_id,
            )
            if tool_call is None:
                raise _ProjectionDependencyPending(f"usage observation {observation.obs_id} is waiting for ToolCall {observation.subject_id}")
            child_contribution = child_task_contribution_for_tool_started(
                observation,
                tool_name=tool_call.tool_name,
            )
            if child_contribution is not None:
                contributions.append(child_contribution)

        for contribution in contributions:
            if contribution.dimension == "tool_calls_executed":
                existing_tool_contribution = await session.scalar(
                    select(AnsichUsageContributionRow.source_obs_id)
                    .join(
                        AnsichObservationRow,
                        AnsichObservationRow.obs_id == AnsichUsageContributionRow.source_obs_id,
                    )
                    .where(
                        AnsichUsageContributionRow.task_id == contribution.task_id,
                        AnsichUsageContributionRow.source_task_id == contribution.source_task_id,
                        AnsichUsageContributionRow.dimension == contribution.dimension,
                        AnsichObservationRow.subject_id == observation.subject_id,
                    )
                    .limit(1)
                )
                if existing_tool_contribution is not None:
                    continue

            values = {
                "task_id": contribution.task_id,
                "source_task_id": contribution.source_task_id,
                "dimension": contribution.dimension,
                "source_obs_id": contribution.source_obs_id,
                "delta": contribution.delta,
                "as_of": contribution.as_of,
            }
            dialect_name = session.bind.dialect.name if session.bind is not None else ""
            if dialect_name == "postgresql":
                statement = postgresql_insert(AnsichUsageContributionRow).values(**values)
            elif dialect_name == "sqlite":
                statement = sqlite_insert(AnsichUsageContributionRow).values(**values)
            else:
                raise ValueError(f"unsupported Ansich SQL dialect: {dialect_name}")
            inserted = (
                await session.execute(
                    statement.on_conflict_do_nothing(
                        index_elements=[
                            "task_id",
                            "source_task_id",
                            "dimension",
                            "source_obs_id",
                        ]
                    ).returning(AnsichUsageContributionRow.source_obs_id)
                )
            ).scalar_one_or_none()
            if inserted is None:
                continue

            usage = await session.get(
                AnsichTaskUsageRow,
                (contribution.task_id, contribution.dimension, "local"),
            )
            if usage is None:
                session.add(
                    AnsichTaskUsageRow(
                        task_id=contribution.task_id,
                        dimension=contribution.dimension,
                        aggregation_scope="local",
                        value=contribution.delta,
                        as_of=contribution.as_of,
                        complete_through_ingest_seq=ingest_seq,
                        updated_at=observation.recorded_at,
                    )
                )
            else:
                if contribution.dimension == "wall_time_ms":
                    usage.value = max(usage.value, contribution.delta)
                else:
                    usage.value += contribution.delta
                usage.as_of = max(_as_utc(usage.as_of), contribution.as_of)
                usage.complete_through_ingest_seq = max(
                    usage.complete_through_ingest_seq,
                    ingest_seq,
                )
                usage.updated_at = observation.recorded_at

    async def _project_step(self, session: AsyncSession, observation: ObservationEnvelope) -> bool:
        """Project logical decisions, physical LLM attempts, and request context.

        Projector routing creates jobs only for the event kinds consumed here;
        this guard remains a replay compatibility boundary for unknown kinds.
        """

        if observation.kind not in _STEP_PROJECTION_KINDS:
            return False
        if observation.payload is None:
            raise ValueError(f"{observation.kind} requires inline projection payload")
        if await session.get(AnsichTaskRow, observation.task_id) is None:
            raise _ProjectionDependencyPending(f"Ansich task is not projected: {observation.task_id}")

        payload = observation.payload
        if observation.kind == "step.started":
            if observation.step_id is None:
                raise ValueError("step.started is missing step_id")
            if await session.get(AnsichEntityRow, observation.step_id) is None:
                session.add(
                    AnsichEntityRow(
                        entity_id=observation.step_id,
                        entity_type="step",
                        discovered_obs_id=observation.obs_id,
                    )
                )
            if await session.get(AnsichStepRow, observation.step_id) is None:
                session.add(
                    AnsichStepRow(
                        entity_id=observation.step_id,
                        task_id=observation.task_id,
                        step_seq=int(payload["step_seq"]),
                        actor_kind=str(payload["actor_kind"]),
                        status="deciding",
                        started_obs_id=observation.obs_id,
                        issued_tools_json=[],
                    )
                )
            await self._close_settled_acting_steps(
                session,
                task_id=observation.task_id,
                before_step_seq=int(payload["step_seq"]),
                followup_observed=True,
            )
            return False

        if observation.kind == "step.closed":
            if observation.step_id is None:
                raise ValueError("step.closed is missing step_id")
            step = await session.get(AnsichStepRow, observation.step_id)
            if step is None:
                raise _ProjectionDependencyPending(f"step.started has not been projected: {observation.step_id}")
            result = str(payload["result"])
            step.result = result
            step.status = "model_failed" if result == "model_failed" else "acting" if result == "acting" else "closed"
            step.closed_obs_id = observation.obs_id
            step.issued_tools_json = list(payload.get("issued_tools", []))
            raw_effective_attempt_no = payload.get("effective_attempt_no")
            if isinstance(raw_effective_attempt_no, int):
                attempt = await session.scalar(
                    select(AnsichLlmAttemptRow).where(
                        AnsichLlmAttemptRow.step_id == step.entity_id,
                        AnsichLlmAttemptRow.attempt_no == raw_effective_attempt_no,
                        AnsichLlmAttemptRow.status == "success",
                    )
                )
                if attempt is not None:
                    step.effective_attempt_no = attempt.attempt_no
                    step.effective_context_snapshot_id = attempt.context_snapshot_id
            return False

        if observation.kind == "content.produced":
            if await session.get(AnsichEntityRow, observation.subject_id) is None:
                session.add(
                    AnsichEntityRow(
                        entity_id=observation.subject_id,
                        entity_type="content_block",
                        discovered_obs_id=observation.obs_id,
                    )
                )
            if await session.get(AnsichContentBlockRow, observation.subject_id) is None:
                session.add(
                    AnsichContentBlockRow(
                        entity_id=observation.subject_id,
                        kind=str(payload["kind"]),
                        content_hash=str(payload["content_hash"]),
                        payload_obs_id=observation.obs_id,
                        producer_obs_id=observation.obs_id,
                        blob_key=payload.get("blob_key") if isinstance(payload.get("blob_key"), str) else None,
                        byte_size=int(payload["visible_bytes"]),
                        token_estimate=int(payload["estimated_tokens"]),
                        sensitivity_flags_json=list(payload.get("sensitivity_flags", [])),
                    )
                )
                await session.flush()
            if await session.get(AnsichBlockProducerRow, observation.subject_id) is None:
                producer_entity_id = next(
                    (payload.get(key) for key in ("producer_entity_id", "compression_id", "attempt_id") if isinstance(payload.get(key), str)),
                    None,
                )
                session.add(
                    AnsichBlockProducerRow(
                        block_id=observation.subject_id,
                        producer_kind=str(payload.get("producer_kind") or observation.producer.name),
                        producer_entity_id=producer_entity_id,
                        producer_obs_id=observation.obs_id,
                    )
                )
            raw_derivations = [item for item in payload.get("derivation_sources", []) if isinstance(item, dict)]
            source_block_id = payload.get("source_block_id")
            if isinstance(source_block_id, str):
                raw_derivations.append(
                    {
                        "source_block_id": source_block_id,
                        "transform_kind": payload.get("transform_kind", "unknown"),
                        "transform_version": payload.get("transform_version", "1"),
                        "source_role": payload.get("source_role", "source"),
                        "ordinal": payload.get("source_ordinal"),
                    }
                )
            for derivation in raw_derivations:
                source_block_id = derivation.get("source_block_id")
                if not isinstance(source_block_id, str) or source_block_id == observation.subject_id:
                    continue
                if await session.get(AnsichContentBlockRow, source_block_id) is None:
                    raise _ProjectionDependencyPending(f"source content block has not been projected: {source_block_id}")
                transform_kind = str(derivation.get("transform_kind", "unknown"))
                derivation_key = (
                    observation.subject_id,
                    source_block_id,
                    transform_kind,
                )
                if (
                    await session.get(
                        AnsichContentBlockDerivationRow,
                        derivation_key,
                    )
                    is None
                ):
                    session.add(
                        AnsichContentBlockDerivationRow(
                            derived_block_id=observation.subject_id,
                            source_block_id=source_block_id,
                            transform_kind=transform_kind,
                            transform_version=str(derivation.get("transform_version", "1")),
                            source_role=str(derivation.get("source_role", "source")),
                            ordinal=(int(derivation["ordinal"]) if isinstance(derivation.get("ordinal"), int) else None),
                            established_obs_id=observation.obs_id,
                        )
                    )
            source_identity = payload.get("source_identity")
            if isinstance(source_identity, str) and source_identity:
                occurrence_key = (
                    observation.task_id,
                    source_identity,
                    str(payload["content_hash"]),
                    str(payload["kind"]),
                )
                if await session.get(AnsichContentOccurrenceRow, occurrence_key) is None:
                    session.add(
                        AnsichContentOccurrenceRow(
                            task_id=observation.task_id,
                            source_identity=source_identity,
                            content_hash=str(payload["content_hash"]),
                            kind=str(payload["kind"]),
                            block_id=observation.subject_id,
                            producer_obs_id=observation.obs_id,
                        )
                    )
            missing_items = list((await session.execute(select(AnsichContextSnapshotMissingItemRow).where(AnsichContextSnapshotMissingItemRow.expected_content_block_id == observation.subject_id))).scalars())
            affected_snapshot_ids: set[str] = set()
            for missing in missing_items:
                affected_snapshot_ids.add(missing.snapshot_id)
                if await session.get(AnsichContextSnapshotItemRow, (missing.snapshot_id, missing.ordinal)) is None:
                    session.add(
                        AnsichContextSnapshotItemRow(
                            snapshot_id=missing.snapshot_id,
                            ordinal=missing.ordinal,
                            channel=missing.channel,
                            role=missing.role,
                            name=missing.name,
                            message_id=missing.message_id,
                            source_identity=missing.source_identity,
                            content_block_id=observation.subject_id,
                            visible_bytes=missing.visible_bytes,
                            estimated_tokens=missing.estimated_tokens,
                            metadata_json=missing.metadata_json,
                        )
                    )
                if (
                    await session.get(
                        AnsichContextSnapshotBlockMembershipRow,
                        (missing.snapshot_id, missing.ordinal),
                    )
                    is None
                ):
                    session.add(
                        AnsichContextSnapshotBlockMembershipRow(
                            snapshot_id=missing.snapshot_id,
                            ordinal=missing.ordinal,
                            content_block_id=observation.subject_id,
                        )
                    )
                await session.delete(missing)
            if affected_snapshot_ids:
                await session.flush()
                for snapshot_id in affected_snapshot_ids:
                    remaining = await session.scalar(select(func.count()).select_from(AnsichContextSnapshotMissingItemRow).where(AnsichContextSnapshotMissingItemRow.snapshot_id == snapshot_id))
                    if not remaining:
                        repaired_snapshot = await session.get(AnsichContextSnapshotRow, snapshot_id)
                        if repaired_snapshot is not None:
                            repaired_snapshot.status = "complete"
            state_ids = list((await session.execute(select(AnsichContextStateMissingBlockRow.state_id).where(AnsichContextStateMissingBlockRow.block_id == observation.subject_id))).scalars())
            for state_id in state_ids:
                missing = await session.get(
                    AnsichContextStateMissingBlockRow,
                    (state_id, observation.subject_id),
                )
                if missing is not None:
                    await session.delete(missing)
                await self._refresh_context_state_and_descendants(session, state_id)
            return bool(affected_snapshot_ids or state_ids)

        if observation.kind == "context.state_recorded":
            await self._project_context_state(session, observation)
            return True

        if observation.kind == "context.snapshotted":
            await self._project_context_snapshot(session, observation)
            return True

        if observation.kind == "context.compressed":
            await self._project_context_compression(session, observation)
            return True

        if observation.kind.startswith("tool."):
            await self._project_tool_call(session, observation)
            return False

        attempt = await session.get(AnsichLlmAttemptRow, observation.subject_id)
        if attempt is None:
            actor_kind = "system_operation"
            if observation.step_id is not None:
                step = await session.get(AnsichStepRow, observation.step_id)
                if step is None:
                    raise _ProjectionDependencyPending(f"step.started has not been projected: {observation.step_id}")
                actor_kind = step.actor_kind
            attempt = AnsichLlmAttemptRow(
                attempt_id=observation.subject_id,
                task_id=observation.task_id,
                step_id=observation.step_id,
                actor_kind=str(payload.get("actor_kind", actor_kind)),
                operation_id=payload.get("operation_id") if isinstance(payload.get("operation_id"), str) else None,
                operation_kind=payload.get("operation_kind") if isinstance(payload.get("operation_kind"), str) else None,
                attempt_no=int(payload["attempt_no"]),
                status="incomplete",
            )
            session.add(attempt)

        if observation.kind == "llm.requested":
            attempt.request_obs_id = observation.obs_id
            attempt.actor_kind = str(payload.get("actor_kind", attempt.actor_kind))
            if isinstance(payload.get("operation_id"), str):
                attempt.operation_id = str(payload["operation_id"])
            if isinstance(payload.get("operation_kind"), str):
                attempt.operation_kind = str(payload["operation_kind"])
            attempt.provider_model = payload.get("configured_model") if isinstance(payload.get("configured_model"), str) else None
            if attempt.status == "incomplete":
                attempt.status = "requested"
        elif observation.kind == "llm.responded":
            attempt.response_obs_id = observation.obs_id
            attempt.status = "success"
            attempt.latency_ms = int(payload["latency_ms"])
            attempt.usage_json = dict(payload.get("usage", {}))
            attempt.response_metadata_json = dict(payload.get("response_metadata", {}))
        elif observation.kind == "llm.failed":
            attempt.failure_obs_id = observation.obs_id
            attempt.status = "failed"
            attempt.latency_ms = int(payload["latency_ms"])
        return False

    async def _project_tool_call(
        self,
        session: AsyncSession,
        observation: ObservationEnvelope,
    ) -> None:
        if observation.step_id is None or observation.payload is None:
            raise ValueError(f"{observation.kind} requires step_id and payload")
        step = await session.get(AnsichStepRow, observation.step_id)
        if step is None:
            raise _ProjectionDependencyPending(f"step.started has not been projected: {observation.step_id}")
        payload = observation.payload
        tool_call = await session.get(AnsichToolCallRow, observation.subject_id)
        if tool_call is None:
            if await session.get(AnsichEntityRow, observation.subject_id) is None:
                session.add(
                    AnsichEntityRow(
                        entity_id=observation.subject_id,
                        entity_type="tool_call",
                        discovered_obs_id=observation.obs_id,
                    )
                )
            tool_call = AnsichToolCallRow(
                entity_id=observation.subject_id,
                task_id=observation.task_id,
                step_id=observation.step_id,
                call_seq=int(payload.get("call_seq", 0)),
                tool_name="unknown",
                args_hash="",
                execution_status="unknown",
                visible_result_status="unknown",
            )
            session.add(tool_call)
            await session.flush()

        if observation.kind == "tool.issued":
            first_issued_evidence = tool_call.issued_obs_id is None
            tool_call.call_seq = int(payload["call_seq"])
            tool_call.provider_call_id = payload.get("provider_call_id") if isinstance(payload.get("provider_call_id"), str) else None
            tool_call.tool_name = str(payload["tool_name"])
            tool_call.args_hash = str(payload["args_hash"])
            tool_call.args_preview_json = payload.get("args_preview")
            tool_call.tool_schema_block_id = payload.get("tool_schema_block_id") if isinstance(payload.get("tool_schema_block_id"), str) else None
            tool_call.issued_obs_id = observation.obs_id
            if tool_call.execution_status == "unknown":
                tool_call.execution_status = "issued"
            if first_issued_evidence:
                await self._increment_tool_usage(
                    session,
                    observation.task_id,
                    issued=1,
                )
            return
        if observation.kind == "tool.started":
            first_execution_evidence = tool_call.execution_status in {"unknown", "issued"}
            tool_call.started_obs_id = observation.obs_id
            if tool_call.raw_terminal_obs_id is None:
                tool_call.execution_status = "acting"
            if first_execution_evidence:
                await self._increment_tool_usage(
                    session,
                    observation.task_id,
                    executed=1,
                )
            return
        if observation.kind == "tool.result_visible":
            tool_call.visible_result_obs_id = observation.obs_id
            tool_call.visible_result_status = "available"
            result_block_id = payload.get("result_block_id")
            if isinstance(result_block_id, str):
                result_key = (tool_call.entity_id, "visible", observation.obs_id)
                if await session.get(AnsichToolCallResultRow, result_key) is None:
                    session.add(
                        AnsichToolCallResultRow(
                            tool_call_id=tool_call.entity_id,
                            result_role="visible",
                            source_obs_id=observation.obs_id,
                            content_block_id=result_block_id,
                            metadata_json={"transform_kind": payload.get("transform_kind", "unknown")},
                        )
                    )
            source_block_id = payload.get("source_block_id")
            if isinstance(result_block_id, str) and isinstance(source_block_id, str) and result_block_id != source_block_id:
                transform_kind = str(payload.get("transform_kind", "unknown"))
                derivation_key = (result_block_id, source_block_id, transform_kind)
                if await session.get(AnsichContentBlockDerivationRow, derivation_key) is None:
                    session.add(
                        AnsichContentBlockDerivationRow(
                            derived_block_id=result_block_id,
                            source_block_id=source_block_id,
                            transform_kind=transform_kind,
                            transform_version=str(payload.get("transform_version", "1")),
                            established_obs_id=observation.obs_id,
                        )
                    )
            return

        terminal_status = {
            "tool.returned_raw": "returned",
            "tool.denied": "denied",
            "tool.timed_out": "timed_out",
            "tool.cancelled": "cancelled",
            "tool.failed": "failed",
            "tool.unknown_terminal": "unknown_terminal",
        }.get(observation.kind)
        if terminal_status is None:
            return
        previous_terminal_status = tool_call.execution_status if tool_call.raw_terminal_obs_id is not None else None
        assertion = AnsichBeliefAssertionRow(
            assertion_id=new_id(),
            subject_id=tool_call.entity_id,
            field_name="execution",
            value_json={"value": terminal_status},
            as_of=observation.occurred_at,
            asserted_at=observation.recorded_at,
            source_name=observation.producer.name,
            source_version=observation.producer.version,
            fidelity_class="hard",
        )
        session.add(assertion)
        session.add(
            AnsichBeliefEvidenceRow(
                assertion_id=assertion.assertion_id,
                obs_id=observation.obs_id,
                evidence_role="supporting",
                ordinal=0,
            )
        )
        current_execution = await session.get(
            AnsichCurrentBeliefRow,
            (tool_call.entity_id, "execution"),
        )
        if current_execution is None:
            session.add(
                AnsichCurrentBeliefRow(
                    subject_id=tool_call.entity_id,
                    field_name="execution",
                    assertion_id=assertion.assertion_id,
                    resolver_name="tool-terminal-precedence",
                    resolver_version="1",
                )
            )
        candidate_selected = previous_terminal_status is None or _TOOL_TERMINAL_PRECEDENCE[terminal_status] >= _TOOL_TERMINAL_PRECEDENCE[previous_terminal_status]
        if current_execution is not None and candidate_selected:
            current_execution.assertion_id = assertion.assertion_id
        if previous_terminal_status is not None and previous_terminal_status != terminal_status:
            summary = await session.get(AnsichTaskSummaryRow, observation.task_id)
            if summary is not None:
                summary.observability_status = "degraded"
        first_execution_evidence = terminal_status not in {"denied", "unknown_terminal"} and tool_call.execution_status in {"unknown", "issued", "denied", "unknown_terminal"}
        if candidate_selected:
            tool_call.raw_terminal_obs_id = observation.obs_id
            tool_call.execution_status = terminal_status
        if first_execution_evidence:
            await self._increment_tool_usage(
                session,
                observation.task_id,
                executed=1,
            )
        if candidate_selected and isinstance(payload.get("duration_ms"), int):
            tool_call.duration_ms = int(payload["duration_ms"])
        result_block_id = payload.get("result_block_id")
        if isinstance(result_block_id, str):
            result_key = (tool_call.entity_id, "raw", observation.obs_id)
            if await session.get(AnsichToolCallResultRow, result_key) is None:
                session.add(
                    AnsichToolCallResultRow(
                        tool_call_id=tool_call.entity_id,
                        result_role="raw",
                        source_obs_id=observation.obs_id,
                        content_block_id=result_block_id,
                        metadata_json={key: value for key, value in payload.items() if key not in {"result_block_id", "call_seq"}},
                    )
                )
        later_step_exists = (
            await session.scalar(
                select(AnsichStepRow.entity_id)
                .where(
                    AnsichStepRow.task_id == observation.task_id,
                    AnsichStepRow.step_seq > step.step_seq,
                )
                .limit(1)
            )
            is not None
        )
        summary = await session.get(AnsichTaskSummaryRow, observation.task_id)
        task_is_terminal = summary is not None and summary.control_value in {"completed", "failed", "interrupted"}
        if later_step_exists or task_is_terminal:
            await self._close_settled_acting_steps(
                session,
                task_id=observation.task_id,
                step_id=step.entity_id,
                followup_observed=True,
            )

    @staticmethod
    async def _close_settled_acting_steps(
        session: AsyncSession,
        *,
        task_id: str,
        step_id: str | None = None,
        before_step_seq: int | None = None,
        followup_observed: bool,
    ) -> None:
        if not followup_observed:
            return
        statement = select(AnsichStepRow).where(
            AnsichStepRow.task_id == task_id,
            AnsichStepRow.status == "acting",
        )
        if step_id is not None:
            statement = statement.where(AnsichStepRow.entity_id == step_id)
        if before_step_seq is not None:
            statement = statement.where(AnsichStepRow.step_seq < before_step_seq)
        steps = list((await session.execute(statement)).scalars())
        for acting_step in steps:
            issued_count = await session.scalar(select(func.count()).select_from(AnsichToolCallRow).where(AnsichToolCallRow.step_id == acting_step.entity_id))
            unsettled_count = await session.scalar(
                select(func.count())
                .select_from(AnsichToolCallRow)
                .where(
                    AnsichToolCallRow.step_id == acting_step.entity_id,
                    AnsichToolCallRow.raw_terminal_obs_id.is_(None),
                )
            )
            if int(issued_count or 0) > 0 and int(unsettled_count or 0) == 0:
                acting_step.status = "closed"

    @staticmethod
    async def _increment_tool_usage(
        session: AsyncSession,
        task_id: str,
        *,
        issued: int = 0,
        executed: int = 0,
    ) -> None:
        await session.execute(
            update(AnsichTaskSummaryRow)
            .where(AnsichTaskSummaryRow.task_id == task_id)
            .values(
                tool_calls_issued=AnsichTaskSummaryRow.tool_calls_issued + issued,
                tool_calls_executed=AnsichTaskSummaryRow.tool_calls_executed + executed,
            )
        )

    async def _ensure_context_state_placeholder(
        self,
        session: AsyncSession,
        *,
        state_id: str,
        task_id: str,
        discovered_obs_id: str,
    ) -> AnsichContextStateRow:
        if await session.get(AnsichEntityRow, state_id) is None:
            session.add(
                AnsichEntityRow(
                    entity_id=state_id,
                    entity_type="context_state",
                    discovered_obs_id=discovered_obs_id,
                )
            )
        state = await session.get(AnsichContextStateRow, state_id)
        if state is None:
            state = AnsichContextStateRow(
                state_id=state_id,
                task_id=task_id,
                state_hash=None,
                parent_state_id=None,
                created_obs_id=None,
                chain_depth=0,
                item_count=0,
                is_checkpoint=False,
                status="missing",
            )
            session.add(state)
            await session.flush()
        elif state.task_id != task_id:
            raise ValueError("ContextState placeholder belongs to a different task")
        return state

    async def _project_context_state(
        self,
        session: AsyncSession,
        observation: ObservationEnvelope,
    ) -> None:
        if observation.payload is None:
            raise ValueError("context.state_recorded is missing payload")
        payload = observation.payload
        parent_state_id = payload.get("parent_state_id") if isinstance(payload.get("parent_state_id"), str) else None
        if parent_state_id == observation.subject_id:
            raise ValueError("ContextState cannot parent itself")
        if parent_state_id is not None:
            await self._ensure_context_state_placeholder(
                session,
                state_id=parent_state_id,
                task_id=observation.task_id,
                discovered_obs_id=observation.obs_id,
            )
        state = await self._ensure_context_state_placeholder(
            session,
            state_id=observation.subject_id,
            task_id=observation.task_id,
            discovered_obs_id=observation.obs_id,
        )
        state_hash = str(payload["state_hash"])
        if state.created_obs_id is not None:
            if state.state_hash != state_hash:
                raise ValueError("ContextState ID collision")
            return
        is_checkpoint = bool(payload["is_checkpoint"])
        if is_checkpoint != (parent_state_id is None):
            raise ValueError("ContextState checkpoint/parent shape is inconsistent")
        state.state_hash = state_hash
        state.parent_state_id = parent_state_id
        state.created_obs_id = observation.obs_id
        state.chain_depth = int(payload["chain_depth"])
        state.item_count = int(payload["item_count"])
        state.is_checkpoint = is_checkpoint
        state.status = "incomplete"
        state.created_at = observation.recorded_at

        if is_checkpoint:
            items = tuple(ContextStateItem.model_validate(item) for item in payload.get("checkpoint_items", []))
            if len(items) != state.item_count:
                raise ValueError("ContextState checkpoint item_count mismatch")
            for item in items:
                session.add(
                    AnsichContextStateCheckpointItemRow(
                        state_id=state.state_id,
                        ordinal=item.ordinal,
                        channel=item.channel,
                        role=item.role,
                        message_id=item.message_id,
                        source_identity=item.source_identity,
                        name=item.name,
                        block_id=item.block_id,
                        visible_bytes=item.visible_bytes,
                        estimated_tokens=item.estimated_tokens,
                        metadata_json=item.metadata,
                    )
                )
        else:
            operations = tuple(ContextStateDelta.model_validate(item) for item in payload.get("delta", []))
            for operation_ordinal, operation in enumerate(operations):
                item = operation.item
                session.add(
                    AnsichContextStateDeltaRow(
                        state_id=state.state_id,
                        operation_ordinal=operation_ordinal,
                        operation=operation.op,
                        source_ordinal=operation.source_ordinal,
                        target_ordinal=operation.target_ordinal,
                        channel=None if item is None else item.channel,
                        role=None if item is None else item.role,
                        message_id=None if item is None else item.message_id,
                        source_identity=None if item is None else item.source_identity,
                        name=None if item is None else item.name,
                        block_id=None if item is None else item.block_id,
                        visible_bytes=None if item is None else item.visible_bytes,
                        estimated_tokens=None if item is None else item.estimated_tokens,
                        metadata_json=None if item is None else item.metadata,
                    )
                )
        await session.flush()
        await self._refresh_context_state_and_descendants(session, state.state_id)

    async def _refresh_context_state_and_descendants(
        self,
        session: AsyncSession,
        root_state_id: str,
    ) -> None:
        pending = [root_state_id]
        visited: set[str] = set()
        while pending:
            state_id = pending.pop(0)
            if state_id in visited:
                continue
            visited.add(state_id)
            state = await session.get(AnsichContextStateRow, state_id)
            if state is None or state.created_obs_id is None or state.state_hash is None:
                continue
            state.status = "incomplete"
            await session.flush()
            try:
                items = await self._materialize_context_state(session, state_id, frozenset())
            except ValueError:
                items = ()
            if items:
                if len(items) != state.item_count or context_state_hash(items) != state.state_hash:
                    raise ValueError("ContextState materialization does not match its declared hash")
            elif state.item_count != 0:
                children = list((await session.execute(select(AnsichContextStateRow.state_id).where(AnsichContextStateRow.parent_state_id == state_id))).scalars())
                pending.extend(children)
                continue
            await session.execute(delete(AnsichContextStateMissingBlockRow).where(AnsichContextStateMissingBlockRow.state_id == state_id))
            block_ids = {item.block_id for item in items}
            available: set[str] = set()
            if block_ids:
                available = set((await session.execute(select(AnsichContentBlockRow.entity_id).where(AnsichContentBlockRow.entity_id.in_(block_ids)))).scalars())
            for block_id in sorted(block_ids - available):
                session.add(
                    AnsichContextStateMissingBlockRow(
                        state_id=state_id,
                        block_id=block_id,
                    )
                )
            state.status = "complete" if block_ids == available else "incomplete"
            await session.execute(update(AnsichContextSnapshotRow).where(AnsichContextSnapshotRow.state_id == state_id).values(status="complete" if state.status == "complete" else "incomplete"))
            snapshot_ids = list((await session.execute(select(AnsichContextSnapshotRow.entity_id).where(AnsichContextSnapshotRow.state_id == state_id))).scalars())
            for snapshot_id in snapshot_ids:
                await self._sync_snapshot_block_memberships(
                    session,
                    snapshot_id=snapshot_id,
                    items=items,
                    available_block_ids=available,
                )
            children = list((await session.execute(select(AnsichContextStateRow.state_id).where(AnsichContextStateRow.parent_state_id == state_id))).scalars())
            pending.extend(children)

    @staticmethod
    async def _sync_snapshot_block_memberships(
        session: AsyncSession,
        *,
        snapshot_id: str,
        items: tuple[ContextStateItem, ...],
        available_block_ids: set[str] | None = None,
    ) -> None:
        available = available_block_ids
        if available is None:
            block_ids = {item.block_id for item in items}
            available = set((await session.execute(select(AnsichContentBlockRow.entity_id).where(AnsichContentBlockRow.entity_id.in_(block_ids)))).scalars()) if block_ids else set()
        for item in items:
            if item.block_id not in available:
                continue
            key = (snapshot_id, item.ordinal)
            existing = await session.get(
                AnsichContextSnapshotBlockMembershipRow,
                key,
            )
            if existing is None:
                session.add(
                    AnsichContextSnapshotBlockMembershipRow(
                        snapshot_id=snapshot_id,
                        ordinal=item.ordinal,
                        content_block_id=item.block_id,
                    )
                )
            elif existing.content_block_id != item.block_id:
                raise ValueError("snapshot block membership conflicts with existing ordinal")

    async def _project_context_snapshot(
        self,
        session: AsyncSession,
        observation: ObservationEnvelope,
    ) -> None:
        if observation.payload is None:
            raise ValueError("context.snapshotted is missing payload")
        payload = observation.payload
        attempt_id = str(payload["attempt_id"])
        attempt = await session.get(AnsichLlmAttemptRow, attempt_id)
        if attempt is None:
            raise _ProjectionDependencyPending(f"llm.requested has not been projected: {attempt_id}")
        state_id = payload.get("state_id") if isinstance(payload.get("state_id"), str) else None
        state = None
        if state_id is not None:
            state = await self._ensure_context_state_placeholder(
                session,
                state_id=state_id,
                task_id=observation.task_id,
                discovered_obs_id=observation.obs_id,
            )

        window = await session.scalar(select(AnsichContextWindowRow).where(AnsichContextWindowRow.task_id == observation.task_id))
        if window is None:
            window_id = new_id()
            session.add(
                AnsichEntityRow(
                    entity_id=window_id,
                    entity_type="context_window",
                    discovered_obs_id=observation.obs_id,
                )
            )
            await session.flush()
            window = AnsichContextWindowRow(
                entity_id=window_id,
                task_id=observation.task_id,
                capacity_tokens=None,
                estimator_name=str(payload["estimator_name"]),
                estimator_version=str(payload["estimator_version"]),
            )
            session.add(window)

        if await session.get(AnsichEntityRow, observation.subject_id) is None:
            session.add(
                AnsichEntityRow(
                    entity_id=observation.subject_id,
                    entity_type="context_snapshot",
                    discovered_obs_id=observation.obs_id,
                )
            )
        snapshot = await session.get(AnsichContextSnapshotRow, observation.subject_id)
        if snapshot is None:
            if observation.causation_obs_id is None:
                raise ValueError("context.snapshotted is missing request causation")
            snapshot = AnsichContextSnapshotRow(
                entity_id=observation.subject_id,
                task_id=observation.task_id,
                step_id=observation.step_id,
                operation_id=payload.get("operation_id") if isinstance(payload.get("operation_id"), str) else None,
                state_id=state_id,
                attempt_no=int(payload["attempt_no"]),
                request_obs_id=observation.causation_obs_id,
                message_count=int(payload["message_count"]),
                tool_schema_count=int(payload["tool_schema_count"]),
                visible_bytes=int(payload["visible_bytes"]),
                estimated_tokens=int(payload["estimated_tokens"]),
                estimator_name=str(payload["estimator_name"]),
                estimator_version=str(payload["estimator_version"]),
                adapter_name=str(payload["adapter_name"]),
                adapter_version=str(payload["adapter_version"]),
                configured_model=payload.get("configured_model") if isinstance(payload.get("configured_model"), str) else None,
                response_format_json=payload.get("response_format"),
                generation_settings_json=dict(payload.get("generation_settings", {})),
                redactions_json=list(payload.get("redactions", [])),
                warnings_json=list(payload.get("warnings", [])),
                status="complete" if state is None or state.status == "complete" else "incomplete",
            )
            session.add(snapshot)
            await session.flush()

        if state_id is not None:
            await self._link_attempt_context_snapshot(
                session,
                attempt=attempt,
                snapshot_id=snapshot.entity_id,
            )
            if state is not None and state.created_obs_id is not None:
                try:
                    items = await self._materialize_context_state(
                        session,
                        state_id,
                        frozenset(),
                    )
                except ValueError:
                    items = ()
                await self._sync_snapshot_block_memberships(
                    session,
                    snapshot_id=snapshot.entity_id,
                    items=items,
                )
            return

        for raw_item in payload.get("items", []):
            if not isinstance(raw_item, dict):
                continue
            block_id = str(raw_item["block_id"])
            if await session.get(AnsichContentBlockRow, block_id) is None:
                ordinal = int(raw_item["ordinal"])
                if await session.get(AnsichContextSnapshotMissingItemRow, (snapshot.entity_id, ordinal)) is None:
                    session.add(
                        AnsichContextSnapshotMissingItemRow(
                            snapshot_id=snapshot.entity_id,
                            ordinal=ordinal,
                            expected_content_block_id=block_id,
                            channel=str(raw_item["channel"]),
                            role=raw_item.get("role") if isinstance(raw_item.get("role"), str) else None,
                            name=raw_item.get("name") if isinstance(raw_item.get("name"), str) else None,
                            message_id=raw_item.get("message_id") if isinstance(raw_item.get("message_id"), str) else None,
                            source_identity=raw_item.get("source_identity") if isinstance(raw_item.get("source_identity"), str) else None,
                            visible_bytes=int(raw_item["visible_bytes"]),
                            estimated_tokens=int(raw_item["estimated_tokens"]),
                            metadata_json=dict(raw_item.get("metadata", {})),
                        )
                    )
                snapshot.status = "incomplete"
                continue
            ordinal = int(raw_item["ordinal"])
            if await session.get(AnsichContextSnapshotItemRow, (snapshot.entity_id, ordinal)) is None:
                session.add(
                    AnsichContextSnapshotItemRow(
                        snapshot_id=snapshot.entity_id,
                        ordinal=ordinal,
                        channel=str(raw_item["channel"]),
                        role=raw_item.get("role") if isinstance(raw_item.get("role"), str) else None,
                        name=raw_item.get("name") if isinstance(raw_item.get("name"), str) else None,
                        message_id=raw_item.get("message_id") if isinstance(raw_item.get("message_id"), str) else None,
                        source_identity=raw_item.get("source_identity") if isinstance(raw_item.get("source_identity"), str) else None,
                        content_block_id=block_id,
                        visible_bytes=int(raw_item["visible_bytes"]),
                        estimated_tokens=int(raw_item["estimated_tokens"]),
                        metadata_json=dict(raw_item.get("metadata", {})),
                    )
                )
            if (
                await session.get(
                    AnsichContextSnapshotBlockMembershipRow,
                    (snapshot.entity_id, ordinal),
                )
                is None
            ):
                session.add(
                    AnsichContextSnapshotBlockMembershipRow(
                        snapshot_id=snapshot.entity_id,
                        ordinal=ordinal,
                        content_block_id=block_id,
                    )
                )
        await self._link_attempt_context_snapshot(
            session,
            attempt=attempt,
            snapshot_id=snapshot.entity_id,
        )

    @staticmethod
    async def _link_attempt_context_snapshot(
        session: AsyncSession,
        *,
        attempt: AnsichLlmAttemptRow,
        snapshot_id: str,
    ) -> None:
        attempt.context_snapshot_id = snapshot_id
        if attempt.step_id is None:
            return
        step = await session.get(AnsichStepRow, attempt.step_id)
        if step is not None and step.effective_attempt_no == attempt.attempt_no:
            step.effective_context_snapshot_id = snapshot_id

    async def _project_context_compression(
        self,
        session: AsyncSession,
        observation: ObservationEnvelope,
    ) -> None:
        if observation.payload is None:
            raise ValueError("context.compressed is missing payload")
        payload = observation.payload
        summary_block_id = payload.get("summary_block_id")
        if not isinstance(summary_block_id, str):
            raise ValueError("context.compressed is missing summary_block_id")
        if await session.get(AnsichContentBlockRow, summary_block_id) is None:
            raise _ProjectionDependencyPending(f"summary content block has not been projected: {summary_block_id}")
        raw_items = payload.get("items", [])
        if not isinstance(raw_items, list):
            raise ValueError("context.compressed items must be a list")
        compression_status = payload.get("status", "complete")
        if compression_status not in {"complete", "incomplete"}:
            raise ValueError(f"invalid context compression status: {compression_status}")
        block_ids = {str(item["block_id"]) for item in raw_items if isinstance(item, dict) and isinstance(item.get("block_id"), str)}
        available_block_ids = set((await session.execute(select(AnsichContentBlockRow.entity_id).where(AnsichContentBlockRow.entity_id.in_(block_ids)))).scalars()) if block_ids else set()
        missing_block_ids = block_ids - available_block_ids
        if missing_block_ids:
            raise _ProjectionDependencyPending("compression content blocks have not been projected: " + ",".join(sorted(missing_block_ids)))

        if await session.get(AnsichEntityRow, observation.subject_id) is None:
            session.add(
                AnsichEntityRow(
                    entity_id=observation.subject_id,
                    entity_type="context_compression",
                    discovered_obs_id=observation.obs_id,
                )
            )
        compression = await session.get(
            AnsichContextCompressionRow,
            observation.subject_id,
        )
        if compression is None:
            compression = AnsichContextCompressionRow(
                entity_id=observation.subject_id,
                task_id=observation.task_id,
                operation_id=(payload.get("summary_operation_id") if isinstance(payload.get("summary_operation_id"), str) else None),
                summary_block_id=summary_block_id,
                before_tokens=int(payload["before_tokens"]),
                after_tokens=int(payload["after_tokens"]),
                before_visible_bytes=int(payload.get("before_visible_bytes", 0)),
                after_visible_bytes=int(payload.get("after_visible_bytes", 0)),
                algorithm=str(payload["algorithm"]),
                algorithm_version=str(payload["algorithm_version"]),
                source_obs_id=observation.obs_id,
                status=cast(Literal["complete", "incomplete"], compression_status),
            )
            session.add(compression)
            await session.flush()

        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                raise ValueError("context.compressed item must be an object")
            disposition = raw_item.get("disposition")
            if disposition not in {"source", "preserved", "removed"}:
                raise ValueError(f"invalid context compression disposition: {disposition}")
            block_id = raw_item.get("block_id")
            if not isinstance(block_id, str):
                raise ValueError("context.compressed item is missing block_id")
            ordinal = int(raw_item["ordinal"])
            item_key = (compression.entity_id, disposition, ordinal)
            existing_item = await session.get(
                AnsichContextCompressionItemRow,
                item_key,
            )
            if existing_item is None:
                session.add(
                    AnsichContextCompressionItemRow(
                        compression_id=compression.entity_id,
                        disposition=disposition,
                        ordinal=ordinal,
                        block_id=block_id,
                    )
                )
            elif existing_item.block_id != block_id:
                raise ValueError("context compression membership conflicts with existing ordinal")
            if disposition != "source" or block_id == summary_block_id:
                continue
            derivation_key = (summary_block_id, block_id, "compressed")
            if await session.get(AnsichContentBlockDerivationRow, derivation_key) is None:
                session.add(
                    AnsichContentBlockDerivationRow(
                        derived_block_id=summary_block_id,
                        source_block_id=block_id,
                        transform_kind="compressed",
                        transform_version=str(payload["algorithm_version"]),
                        source_role="source",
                        ordinal=ordinal,
                        established_obs_id=observation.obs_id,
                    )
                )

    async def _project_scopes(self, session: AsyncSession, observation: ObservationEnvelope) -> None:
        if observation.payload is None:
            return
        scopes = (
            ("owner", observation.payload.get("owner_id")),
            ("thread", observation.payload.get("thread_id")),
        )
        for scope_kind, raw_scope_value in scopes:
            if not isinstance(raw_scope_value, str) or not raw_scope_value:
                continue
            scope = await session.scalar(
                select(AnsichScopeRow).where(
                    AnsichScopeRow.scope_kind == scope_kind,
                    AnsichScopeRow.scope_value == raw_scope_value,
                )
            )
            if scope is None:
                scope_id = new_id()
                session.add(
                    AnsichEntityRow(
                        entity_id=scope_id,
                        entity_type="scope",
                        discovered_obs_id=observation.obs_id,
                    )
                )
                scope = AnsichScopeRow(
                    entity_id=scope_id,
                    scope_kind=scope_kind,
                    scope_value=raw_scope_value,
                )
                session.add(scope)
                await session.flush()
            relation = await session.scalar(
                select(AnsichRelationRow).where(
                    AnsichRelationRow.subject_id == observation.task_id,
                    AnsichRelationRow.predicate == "within_scope",
                    AnsichRelationRow.object_id == scope.entity_id,
                )
            )
            if relation is None:
                relation = AnsichRelationRow(
                    relation_id=new_id(),
                    subject_id=observation.task_id,
                    predicate="within_scope",
                    object_id=scope.entity_id,
                    asserted_obs_id=observation.obs_id,
                )
                session.add(relation)
                await session.flush()
            evidence = await session.get(
                AnsichRelationEvidenceRow,
                (relation.relation_id, observation.obs_id),
            )
            if evidence is None:
                session.add(
                    AnsichRelationEvidenceRow(
                        relation_id=relation.relation_id,
                        obs_id=observation.obs_id,
                        ordinal=0,
                    )
                )
