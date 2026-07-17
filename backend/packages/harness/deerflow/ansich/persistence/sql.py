from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import uuid4

from ansich import (
    ContentBlockPayloadView,
    ContextSnapshotItemView,
    ContextSnapshotView,
    ControlBelief,
    LlmAttemptView,
    NamedVersion,
    ObservationEnvelope,
    Producer,
    StepView,
    TaskView,
    new_id,
)
from ansich.contracts import ControlValue
from ansich.control import should_select_control_candidate
from sqlalchemy import and_, case, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.ansich.persistence.models import (
    AnsichBeliefAssertionRow,
    AnsichBeliefEvidenceRow,
    AnsichContentBlockRow,
    AnsichContextSnapshotItemRow,
    AnsichContextSnapshotRow,
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
    AnsichTaskRow,
    AnsichTaskSummaryRow,
    AnsichTransitionRow,
)

_CONTROL_BY_KIND = {
    "task.created": "created",
    "task.started": "running",
    "task.completed": "completed",
    "task.failed": "failed",
    "task.interrupted": "interrupted",
}
#: Registration order is execution priority for jobs of one observation:
#: structural projections must land before belief/control projections, and
#: future projectors (e.g. Phase 2 steps) run after both. Claim ordering
#: derives from this tuple — never from projector_name collation.
_PROJECTORS = (("task-structural", "1"), ("task-control", "1"), ("task-step", "1"))


def _projector_priority_expression():
    priority_by_name = {name: index for index, (name, _) in enumerate(_PROJECTORS)}
    return case(priority_by_name, value=AnsichProjectionJobRow.projector_name, else_=len(priority_by_name))


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class SqlAnsichBackend:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        projector_lease_seconds: int = 30,
        projector_max_attempts: int = 5,
        inline_payload_max_bytes: int = 65_536,
    ) -> None:
        self._session_factory = session_factory
        self._projector_lease_seconds = projector_lease_seconds
        self._projector_max_attempts = projector_max_attempts
        self._inline_payload_max_bytes = inline_payload_max_bytes
        self._lease_owner = str(uuid4())
        self._watermark: int | None = None
        self._failed_jobs = 0
        self._latest_recorded_at: datetime | None = None
        self._latest_projected_at: datetime | None = None

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
                for projector_name, projector_version in _PROJECTORS:
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

    async def project_pending(self, *, limit: int = 200) -> int:
        processed = 0
        for _ in range(limit):
            claim = await self._claim_projection_job()
            if claim is None:
                break
            job_id, projector_name, observation, ingest_seq, attempt = claim
            try:
                async with self._session_factory() as session, session.begin():
                    if projector_name == "task-structural":
                        await self._project_structural(session, observation)
                    elif projector_name == "task-control":
                        await self._project_control(session, observation, ingest_seq=ingest_seq)
                    elif projector_name == "task-step":
                        await self._project_step(session, observation)
                    else:
                        raise ValueError(f"unknown Ansich projector: {projector_name}")
                    job = await session.get(AnsichProjectionJobRow, job_id)
                    if job is None:
                        raise RuntimeError("claimed Ansich projection job disappeared")
                    job.status = "completed"
                    job.lease_owner = None
                    job.lease_expires_at = None
                    job.last_error = None
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
        }

    async def has_pending_for_task(self, task_id: str) -> bool:
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            pending = await session.scalar(
                select(AnsichProjectionJobRow.job_id)
                .join(AnsichObservationRow, AnsichObservationRow.obs_id == AnsichProjectionJobRow.obs_id)
                .where(
                    AnsichObservationRow.task_id == task_id,
                    or_(
                        AnsichProjectionJobRow.status == "pending",
                        (AnsichProjectionJobRow.status == "processing") & (AnsichProjectionJobRow.lease_expires_at <= now),
                    ),
                )
                .limit(1)
            )
        return pending is not None

    async def rebuild_projections(self) -> int:
        """Delete rebuildable Phase 1 state and replay every durable job."""

        async with self._session_factory() as session, session.begin():
            for model in (
                AnsichContextSnapshotItemRow,
                AnsichContextSnapshotRow,
                AnsichContextWindowRow,
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
                return replayed

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
        from_time: datetime | None = None,
        to_time: datetime | None = None,
        cursor: tuple[datetime, str] | None = None,
    ) -> list[TaskView]:
        async with self._session_factory() as session:
            statement = select(AnsichTaskSummaryRow.task_id)
            if control is not None:
                statement = statement.where(AnsichTaskSummaryRow.control_value == control)
            if from_time is not None:
                statement = statement.where(AnsichTaskSummaryRow.last_evidence_at >= from_time)
            if to_time is not None:
                statement = statement.where(AnsichTaskSummaryRow.last_evidence_at <= to_time)
            if cursor is not None:
                cursor_time, cursor_task_id = cursor
                statement = statement.where(
                    or_(
                        AnsichTaskSummaryRow.last_evidence_at < cursor_time,
                        and_(
                            AnsichTaskSummaryRow.last_evidence_at == cursor_time,
                            AnsichTaskSummaryRow.task_id > cursor_task_id,
                        ),
                    )
                )
            task_ids = list(
                (
                    await session.execute(
                        statement.order_by(
                            AnsichTaskSummaryRow.last_evidence_at.desc(),
                            AnsichTaskSummaryRow.task_id,
                        ).limit(limit)
                    )
                ).scalars()
            )
        tasks: list[TaskView] = []
        for task_id in task_ids:
            task = await self.get_task(task_id)
            if task is not None:
                tasks.append(task)
        return tasks

    async def list_observations(self, task_id: str) -> list[ObservationEnvelope]:
        async with self._session_factory() as session:
            rows = list((await session.execute(select(AnsichObservationRow).where(AnsichObservationRow.task_id == task_id).order_by(AnsichObservationRow.ingest_seq))).scalars())
        return [self._observation_from_row(row) for row in rows]

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
                        .where(
                            AnsichLlmAttemptRow.task_id == task_id,
                            AnsichLlmAttemptRow.step_id.is_(None),
                        )
                        .order_by(AnsichLlmAttemptRow.request_obs_id, AnsichLlmAttemptRow.attempt_no)
                    )
                ).scalars()
            )
            return [self._attempt_view(row) for row in rows]

    async def get_step(self, step_id: str) -> StepView | None:
        async with self._session_factory() as session:
            row = await session.get(AnsichStepRow, step_id)
            return None if row is None else await self._step_view(session, row)

    async def get_step_context(self, step_id: str) -> ContextSnapshotView | None:
        async with self._session_factory() as session:
            step = await session.get(AnsichStepRow, step_id)
            if step is None or step.effective_context_snapshot_id is None:
                return None
            snapshot = await session.get(AnsichContextSnapshotRow, step.effective_context_snapshot_id)
            if snapshot is None:
                return None
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
            items = tuple(
                ContextSnapshotItemView(
                    ordinal=item.ordinal,
                    channel=item.channel,
                    role=item.role,
                    name=item.name,
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
            )
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
                items=items,
            )

    async def get_content_block_payload(self, block_id: str) -> ContentBlockPayloadView | None:
        async with self._session_factory() as session:
            block = await session.get(AnsichContentBlockRow, block_id)
            if block is None:
                return None
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
            usage=dict((attempt.usage_json or {}).get("usage", {})),
            response_metadata=dict((attempt.usage_json or {}).get("response_metadata", {})),
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

    async def _project_step(self, session: AsyncSession, observation: ObservationEnvelope) -> None:
        """Project logical decisions, physical LLM attempts, and request context.

        The projector is deliberately event-specific. Task lifecycle events are
        harmless no-ops, which lets every durable observation receive the same
        versioned job set and keeps rebuild behavior uniform.
        """

        if observation.kind not in {
            "step.started",
            "step.closed",
            "llm.requested",
            "llm.responded",
            "llm.failed",
            "content.produced",
            "context.snapshotted",
        }:
            return
        if observation.payload is None:
            raise ValueError(f"{observation.kind} requires inline projection payload")
        if await session.get(AnsichTaskRow, observation.task_id) is None:
            raise ValueError(f"Ansich task is not projected: {observation.task_id}")

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
            return

        if observation.kind == "step.closed":
            if observation.step_id is None:
                raise ValueError("step.closed is missing step_id")
            step = await session.get(AnsichStepRow, observation.step_id)
            if step is None:
                raise ValueError(f"step.started has not been projected: {observation.step_id}")
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
            return

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
                        byte_size=int(payload["visible_bytes"]),
                        token_estimate=int(payload["estimated_tokens"]),
                        sensitivity_flags_json=list(payload.get("sensitivity_flags", [])),
                    )
                )
            return

        if observation.kind == "context.snapshotted":
            await self._project_context_snapshot(session, observation)
            return

        attempt = await session.get(AnsichLlmAttemptRow, observation.subject_id)
        if attempt is None:
            actor_kind = "system_operation"
            if observation.step_id is not None:
                step = await session.get(AnsichStepRow, observation.step_id)
                if step is None:
                    raise ValueError(f"step.started has not been projected: {observation.step_id}")
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
            attempt.usage_json = {
                "usage": dict(payload.get("usage", {})),
                "response_metadata": dict(payload.get("response_metadata", {})),
            }
        elif observation.kind == "llm.failed":
            attempt.failure_obs_id = observation.obs_id
            attempt.status = "failed"
            attempt.latency_ms = int(payload["latency_ms"])

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
            raise ValueError(f"llm.requested has not been projected: {attempt_id}")

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
            )
            session.add(snapshot)
            await session.flush()

        for raw_item in payload.get("items", []):
            if not isinstance(raw_item, dict):
                continue
            block_id = str(raw_item["block_id"])
            if await session.get(AnsichContentBlockRow, block_id) is None:
                raise ValueError(f"content.produced has not been projected: {block_id}")
            ordinal = int(raw_item["ordinal"])
            if await session.get(AnsichContextSnapshotItemRow, (snapshot.entity_id, ordinal)) is None:
                session.add(
                    AnsichContextSnapshotItemRow(
                        snapshot_id=snapshot.entity_id,
                        ordinal=ordinal,
                        channel=str(raw_item["channel"]),
                        role=raw_item.get("role") if isinstance(raw_item.get("role"), str) else None,
                        name=raw_item.get("name") if isinstance(raw_item.get("name"), str) else None,
                        content_block_id=block_id,
                        visible_bytes=int(raw_item["visible_bytes"]),
                        estimated_tokens=int(raw_item["estimated_tokens"]),
                        metadata_json=dict(raw_item.get("metadata", {})),
                    )
                )
        attempt.context_snapshot_id = snapshot.entity_id

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
