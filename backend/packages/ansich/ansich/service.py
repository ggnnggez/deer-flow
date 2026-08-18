from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime
from threading import Lock
from weakref import ReferenceType, WeakMethod, ref

from ansich.alerts.views import AlertDetailView, AlertSummaryView, BeliefAssertionView
from ansich.backend import AnsichBackend
from ansich.budget import BudgetHealthBelief, TaskBudgetsView
from ansich.compression import ContextCompressionSummaryView, ContextCompressionView
from ansich.context_state import ContextStateView
from ansich.contracts import AnsichHealth, ControlValue, FlushResult, LostRange, ObservationEnvelope, Producer, RecordReceipt, TaskLifecycleScope, TaskView
from ansich.evaluation import (
    QUALITY_DIMENSIONS,
    EvaluationProjectionStatus,
    EvaluationRecord,
    EvaluationRecordReceipt,
    EvaluationView,
    QualityBeliefView,
    build_evaluation_observation,
    unassessed_quality_belief,
)
from ansich.heartbeat import TaskHeartbeatView
from ansich.jobs import FailedJobDetailView, FailedJobKind, FailedJobSummaryView
from ansich.lineage import ContentLineageView, LineageDirection, PossibleExposureView, find_possible_exposures, traverse_content_lineage
from ansich.memory import InMemoryAnsichBackend
from ansich.operations import ActiveStepView, ActiveTaskView, HeartbeatBelief
from ansich.operator import OperatorActionView, TaskActionTarget
from ansich.quality import ReleaseQualityView
from ansich.release import AgentReleaseDetailView, AgentReleaseSummaryView, TaskAgentReleaseView
from ansich.safety import TaskScopesView, ToolAuthorizationView, ToolEffectsView
from ansich.step import ContentBlockPayloadView, ContentOccurrenceView, ContextSnapshotView, LlmAttemptView, StepView
from ansich.task_tree import (
    TaskSpawnView,
    TaskTreeDirection,
    TaskTreeNodeView,
    TaskTreeView,
)
from ansich.tool import ToolCallView
from ansich.usage import AggregationScope, TaskUsageBreakdownView, TaskUsageView

logger = logging.getLogger(__name__)
_DROP_WARNING_INTERVAL_SECONDS = 60.0


def _serialized_observation_size(observation: ObservationEnvelope) -> int:
    try:
        return len(observation.model_dump_json().encode("utf-8"))
    except Exception:
        return -1


class AnsichService:
    """Small public interface around collection, projection, and Task queries."""

    def __init__(
        self,
        backend: AnsichBackend,
        *,
        queue_capacity: int = 10_000,
        queue_byte_capacity: int = 64 * 1024 * 1024,
        batch_size: int = 100,
        flush_interval_ms: int = 100,
        terminal_flush_timeout_ms: int = 2_000,
        projector_poll_interval_ms: int = 250,
        operations_assessment_interval_ms: int = 1_000,
        unavailable_reason: str | None = None,
    ) -> None:
        if queue_capacity < 1:
            raise ValueError("queue_capacity must be positive")
        if queue_byte_capacity < 1:
            raise ValueError("queue_byte_capacity must be positive")
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        if flush_interval_ms < 1:
            raise ValueError("flush_interval_ms must be positive")
        if terminal_flush_timeout_ms < 1:
            raise ValueError("terminal_flush_timeout_ms must be positive")
        if projector_poll_interval_ms < 1:
            raise ValueError("projector_poll_interval_ms must be positive")
        if operations_assessment_interval_ms < 1:
            raise ValueError("operations_assessment_interval_ms must be positive")
        self._capacity = queue_capacity
        self._byte_capacity = queue_byte_capacity
        self._batch_size = batch_size
        self._flush_interval_seconds = flush_interval_ms / 1000
        self._terminal_flush_timeout_seconds = terminal_flush_timeout_ms / 1000
        self._projector_poll_interval_seconds = projector_poll_interval_ms / 1000
        self._operations_assessment_interval_seconds = operations_assessment_interval_ms / 1000
        self._queue: deque[tuple[int, ObservationEnvelope, int]] = deque()
        self._queue_bytes = 0
        self._lock = Lock()
        self._running = False
        self._backend = backend
        self._unavailable_reason = unavailable_reason
        self._record_sequence = 0
        self._accepted_count = 0
        self._dropped_count = 0
        self._queue_high_watermark = 0
        self._queue_byte_high_watermark = 0
        self._snapshot_request_count = 0
        self._snapshot_observations_accepted = 0
        self._snapshot_observations_dropped = 0
        self._lost_ranges: list[LostRange] = []
        self._reported_lost_range_count = 0
        self._last_drop_warning_at: float | None = None
        self._suppressed_drop_warning_count = 0
        self._loop: asyncio.AbstractEventLoop | None = None
        self._wake_event: asyncio.Event | None = None
        self._projector_wake_event: asyncio.Event | None = None
        self._persist_lock: asyncio.Lock | None = None
        self._projection_lock: asyncio.Lock | None = None
        self._writer_task: asyncio.Task[None] | None = None
        self._projector_task: asyncio.Task[None] | None = None
        self._persistence_listeners: dict[str, list[ReferenceType[object]]] = {}

    @classmethod
    def in_memory(
        cls,
        *,
        queue_capacity: int = 10_000,
        queue_byte_capacity: int = 64 * 1024 * 1024,
        batch_size: int = 100,
        flush_interval_ms: int = 100,
        terminal_flush_timeout_ms: int = 2_000,
        projector_poll_interval_ms: int = 250,
        operations_assessment_interval_ms: int = 1_000,
    ) -> AnsichService:
        return cls(
            InMemoryAnsichBackend(),
            queue_capacity=queue_capacity,
            queue_byte_capacity=queue_byte_capacity,
            batch_size=batch_size,
            flush_interval_ms=flush_interval_ms,
            terminal_flush_timeout_ms=terminal_flush_timeout_ms,
            projector_poll_interval_ms=projector_poll_interval_ms,
            operations_assessment_interval_ms=operations_assessment_interval_ms,
        )

    async def start(self) -> None:
        if self._running:
            return
        initialize_metrics = getattr(self._backend, "initialize_metrics", None)
        if callable(initialize_metrics):
            await initialize_metrics()
        self._loop = asyncio.get_running_loop()
        self._wake_event = asyncio.Event()
        self._projector_wake_event = asyncio.Event()
        self._persist_lock = asyncio.Lock()
        self._projection_lock = asyncio.Lock()
        self._running = True
        self._writer_task = asyncio.create_task(self._writer_loop(), name="ansich-batch-writer")
        if callable(getattr(self._backend, "project_pending", None)):
            self._projector_task = asyncio.create_task(self._projector_loop(), name="ansich-projector")

    def record(self, observation: ObservationEnvelope) -> RecordReceipt:
        return self.record_batch((observation,))[0]

    def record_batch(
        self,
        observations: tuple[ObservationEnvelope, ...] | list[ObservationEnvelope],
        *,
        batch_kind: str | None = None,
    ) -> tuple[RecordReceipt, ...]:
        batch = tuple(observations)
        if not batch:
            return ()
        observation_sizes = tuple(_serialized_observation_size(observation) if isinstance(observation, ObservationEnvelope) else 0 for observation in batch)
        batch_bytes = sum(max(0, observation_size) for observation_size in observation_sizes)
        with self._lock:
            first_sequence = self._record_sequence + 1
            self._record_sequence += len(batch)
            sequences = tuple(range(first_sequence, self._record_sequence + 1))
            if batch_kind == "context_snapshot":
                self._snapshot_request_count += 1
            reason = None
            if any(not isinstance(observation, ObservationEnvelope) for observation in batch):
                reason = "validation_failed"
            elif any(observation_size < 0 for observation_size in observation_sizes):
                reason = "serialization_failed"
            elif self._unavailable_reason is not None:
                reason = self._unavailable_reason
            elif not self._running:
                reason = "service_not_running"
            elif len(self._queue) + len(batch) > self._capacity:
                reason = "queue_full"
            elif self._queue_bytes + batch_bytes > self._byte_capacity:
                reason = "queue_bytes_full"
            if reason is not None:
                batch_lost_ranges = self._record_batch_loss(sequences, batch)
                if reason in {"queue_full", "queue_bytes_full"}:
                    self._warn_batch_loss(
                        reason=reason,
                        observation_count=len(batch),
                        lost_ranges=batch_lost_ranges,
                    )
                if batch_kind == "context_snapshot":
                    self._snapshot_observations_dropped += len(batch)
                return tuple(
                    RecordReceipt(
                        obs_id=observation.obs_id if isinstance(observation, ObservationEnvelope) else None,
                        accepted=False,
                        reason=reason,
                    )
                    for observation in batch
                )
            for sequence, observation, observation_size in zip(
                sequences,
                batch,
                observation_sizes,
                strict=True,
            ):
                self._queue.append((sequence, observation, observation_size))
            self._queue_bytes += batch_bytes
            self._accepted_count += len(batch)
            self._queue_high_watermark = max(self._queue_high_watermark, len(self._queue))
            self._queue_byte_high_watermark = max(
                self._queue_byte_high_watermark,
                self._queue_bytes,
            )
            if batch_kind == "context_snapshot":
                self._snapshot_observations_accepted += len(batch)
            loop = self._loop
            wake_event = self._wake_event
        if loop is not None and wake_event is not None:
            try:
                loop.call_soon_threadsafe(wake_event.set)
            except RuntimeError:
                with self._lock:
                    sequence_set = set(sequences)
                    retained = deque(item for item in self._queue if item[0] not in sequence_set)
                    removed_bytes = sum(item[2] for item in self._queue if item[0] in sequence_set)
                    removed_count = len(self._queue) - len(retained)
                    if removed_count:
                        self._queue = retained
                        self._queue_bytes -= removed_bytes
                        self._accepted_count -= removed_count
                        self._record_batch_loss(sequences, batch)
                        if batch_kind == "context_snapshot":
                            self._snapshot_observations_accepted -= removed_count
                            self._snapshot_observations_dropped += removed_count
                return tuple(RecordReceipt(obs_id=observation.obs_id, accepted=False, reason="event_loop_closed") for observation in batch)
        return tuple(RecordReceipt(obs_id=observation.obs_id, accepted=True) for observation in batch)

    def get_health(self) -> AnsichHealth:
        with self._lock:
            metrics_provider = getattr(self._backend, "get_projection_metrics", None)
            metrics = metrics_provider() if callable(metrics_provider) else {}
            failed_jobs = int(metrics.get("failed_jobs", 0))
            status = "stopped" if not self._running else "failed" if self._unavailable_reason is not None else "degraded" if self._dropped_count or failed_jobs else "healthy"
            return AnsichHealth(
                status=status,
                queue_depth=len(self._queue),
                queue_capacity=self._capacity,
                queue_bytes=self._queue_bytes,
                queue_byte_capacity=self._byte_capacity,
                accepted_count=self._accepted_count,
                dropped_count=self._dropped_count,
                lost_ranges=tuple(self._lost_ranges),
                watermark=metrics.get("watermark"),
                lag_ms=int(metrics.get("lag_ms", 0)),
                failed_jobs=failed_jobs,
                loss_detected=self._dropped_count > 0,
                range_known=True,
                storage_available=self._unavailable_reason is None,
                queue_high_watermark=self._queue_high_watermark,
                queue_byte_high_watermark=self._queue_byte_high_watermark,
                snapshot_request_count=self._snapshot_request_count,
                snapshot_observations_accepted=self._snapshot_observations_accepted,
                snapshot_observations_dropped=self._snapshot_observations_dropped,
                snapshot_count=int(metrics.get("snapshot_count", 0)),
                snapshot_item_count=int(metrics.get("snapshot_item_count", 0)),
                snapshot_visible_bytes=int(metrics.get("snapshot_visible_bytes", 0)),
                incomplete_snapshot_count=int(metrics.get("incomplete_snapshot_count", 0)),
                missing_content_block_count=int(metrics.get("missing_content_block_count", 0)),
            )

    def register_persistence_listener(
        self,
        task_id: str,
        listener: Callable[[tuple[str, ...]], None],
    ) -> None:
        try:
            listener_ref: ReferenceType[object] = WeakMethod(listener)  # type: ignore[arg-type]
        except TypeError:
            listener_ref = ref(listener)
        with self._lock:
            self._persistence_listeners.setdefault(task_id, []).append(listener_ref)

    async def flush_task(self, task_id: str) -> FlushResult:
        persist_lock = self._persist_lock
        if persist_lock is None:
            return FlushResult(persisted=False, processed_count=0, reason="service_not_running")
        selected: list[tuple[int, ObservationEnvelope]] = []
        persist_result: FlushResult | None = None
        try:
            async with asyncio.timeout(self._terminal_flush_timeout_seconds):
                async with persist_lock:
                    with self._lock:
                        selected = self._take_task_items(task_id)
                    result = await self._persist_items(selected)
                    if result.persisted:
                        persist_result = result
                        await self._project_until_task_settled(task_id)
                    return result
        except TimeoutError:
            if persist_result is not None:
                # Observations are already durable; only projection settling
                # timed out, so the read model is lagging — never data loss.
                return persist_result.model_copy(update={"reason": "projection_settle_timeout"})
            with self._lock:
                if not selected:
                    selected = self._take_task_items(task_id)
                for _, observation in selected:
                    self._record_observation_loss(observation)
            return FlushResult(persisted=False, processed_count=0, reason="terminal_flush_timeout")

    async def get_task(self, task_id: str) -> TaskView | None:
        return await self._backend.get_task(task_id)

    async def get_task_agent_release(
        self,
        task_id: str,
    ) -> TaskAgentReleaseView | None:
        return await self._backend.get_task_agent_release(task_id)

    async def get_agent_release(
        self,
        release_id: str,
    ) -> AgentReleaseDetailView | None:
        return await self._backend.get_agent_release(release_id)

    async def list_agent_releases(
        self,
        *,
        limit: int = 100,
        agent_name: str | None = None,
        component_hash: str | None = None,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
    ) -> list[AgentReleaseSummaryView]:
        if limit < 1:
            raise ValueError("limit must be positive")
        return await self._backend.list_agent_releases(
            limit=limit,
            agent_name=agent_name,
            component_hash=component_hash,
            from_time=from_time,
            to_time=to_time,
        )

    async def get_current_belief(
        self,
        subject_id: str,
        field_name: str,
    ) -> BeliefAssertionView | None:
        get_current_belief = getattr(self._backend, "get_current_belief", None)
        if not callable(get_current_belief):
            return None
        return await get_current_belief(subject_id, field_name)

    async def record_evaluation(
        self,
        record: EvaluationRecord,
        *,
        source_event_id: str | None,
        producer: Producer,
    ) -> EvaluationRecordReceipt:
        """Record one evaluation and report where its projection currently is.

        Intake is synchronous and projection is not: the receipt reports the
        state after one bounded settle attempt rather than blocking until every
        projector finishes. A replayed intake never records a second
        Observation — it reports the stored one and the status it has now.
        """

        # The envelope resolves the replay identity: a benchmark evaluation
        # derives its stable source_event_id from its suite/case/run tuple, so
        # the lookup key only exists once the envelope has been built. A replay
        # discards this envelope without recording it.
        observation = build_evaluation_observation(
            record,
            producer=producer,
            source_event_id=source_event_id,
        )
        find_observation = getattr(self._backend, "find_evaluation_observation", None)
        existing_obs_id = await find_observation(observation.source_event_id) if callable(find_observation) else None
        if existing_obs_id is not None:
            return EvaluationRecordReceipt(
                observation_id=existing_obs_id,
                projection_status=await self._evaluation_projection_status(existing_obs_id),
                idempotent_replay=True,
            )
        if not self.record(observation).accepted:
            # A rejected intake (storage unavailable, stopped service, queue
            # overflow) was never made durable, so its projection can never
            # land; the loss is already accounted as a lost range.
            return EvaluationRecordReceipt(
                observation_id=observation.obs_id,
                projection_status="failed",
                idempotent_replay=False,
            )
        if not (await self.flush_task(record.task_id)).persisted:
            # The same reasoning one branch up, for the write rather than the
            # intake: a terminal-flush timeout before persistence, or a storage
            # failure, drops the Observation and records it as a lost range.
            # There is no job to poll, so reporting "pending" would leave the
            # caller waiting on a projection that can never arrive. A settle
            # timeout AFTER a successful write keeps ``persisted=True`` and
            # correctly falls through to the real job status below.
            return EvaluationRecordReceipt(
                observation_id=observation.obs_id,
                projection_status="failed",
                idempotent_replay=False,
            )
        return EvaluationRecordReceipt(
            observation_id=observation.obs_id,
            projection_status=await self._evaluation_projection_status(observation.obs_id),
            idempotent_replay=False,
        )

    async def _evaluation_projection_status(self, obs_id: str) -> EvaluationProjectionStatus:
        if not self.get_health().storage_available:
            return "failed"
        read_status = getattr(self._backend, "get_observation_projection_status", None)
        if not callable(read_status):
            return "pending"
        status = await read_status(obs_id)
        return "pending" if status is None else status

    async def get_evaluation_subject(self, subject_id: str) -> str | None:
        """Return the Entity type an evaluation subject id resolves to."""

        get_subject = getattr(self._backend, "get_evaluation_subject", None)
        if not callable(get_subject):
            return None
        return await get_subject(subject_id)

    async def list_evaluations(
        self,
        *,
        subject_type: str | None = None,
        subject_id: str | None = None,
        task_id: str | None = None,
        limit: int = 100,
    ) -> list[EvaluationView]:
        """List recorded evaluations newest first, metadata only."""

        if limit < 1:
            raise ValueError("limit must be positive")
        list_evaluations = getattr(self._backend, "list_evaluations", None)
        if not callable(list_evaluations):
            return []
        return list(
            await list_evaluations(
                subject_type=subject_type,
                subject_id=subject_id,
                task_id=task_id,
                limit=limit,
            )
        )

    async def get_evaluation_observation_payload(self, obs_id: str) -> dict | None:
        """Return one evaluation Observation's full payload, or ``None``.

        The evaluation index is metadata only; ``expected``/``actual``/
        ``rationale`` live in the Observation payload and are read here, one
        Observation at a time, after an explicit request. A backend without
        this capability reports absence rather than an error.
        """

        get_payload = getattr(self._backend, "get_evaluation_observation_payload", None)
        if not callable(get_payload):
            return None
        return await get_payload(obs_id)

    async def get_quality_beliefs(self, subject_id: str) -> list[QualityBeliefView]:
        """Return the subject's quality Beliefs, unassessed dimensions included.

        Every named dimension is always reported. A dimension nothing asserted
        is synthesized as ``unassessed`` with no evidence, because a completed
        Task is not proof of a pass. Dimensions outside that set — currently
        ``earliest_erroneous_step`` — appear only when a Belief exists for them.
        """

        list_quality_beliefs = getattr(self._backend, "list_quality_beliefs", None)
        persisted: dict[str, QualityBeliefView] = {}
        if callable(list_quality_beliefs):
            for belief in await list_quality_beliefs(subject_id):
                persisted[belief.dimension] = belief
        beliefs = [persisted[dimension] if dimension in persisted else unassessed_quality_belief(dimension) for dimension in QUALITY_DIMENSIONS]
        beliefs.extend(persisted[dimension] for dimension in sorted(set(persisted) - set(QUALITY_DIMENSIONS)))
        return beliefs

    async def get_release_quality(
        self,
        release_id: str,
        *,
        cohort_key: str | None = None,
    ) -> ReleaseQualityView | None:
        """Return one AgentRelease's quality cells, or ``None`` if it is unknown.

        A known release with no evaluated Task returns an empty cohort tuple —
        no evaluation is not the same fact as no release.
        """

        get_release_quality = getattr(self._backend, "get_release_quality", None)
        if not callable(get_release_quality):
            return None
        return await get_release_quality(release_id, cohort_key=cohort_key)

    async def get_task_by_source(self, source_kind: str, source_id: str) -> TaskView | None:
        return await self._backend.get_task_by_source(source_kind, source_id)

    async def list_tasks(
        self,
        *,
        limit: int = 100,
        control: ControlValue | None = None,
        lifecycle_scope: TaskLifecycleScope = "all",
        from_time: datetime | None = None,
        to_time: datetime | None = None,
        cursor: tuple[datetime, str] | None = None,
        root_only: bool = False,
    ) -> list[TaskView]:
        if limit < 1:
            raise ValueError("limit must be positive")
        return await self._backend.list_tasks(
            limit=limit,
            control=control,
            lifecycle_scope=lifecycle_scope,
            from_time=from_time,
            to_time=to_time,
            cursor=cursor,
            root_only=root_only,
        )

    async def list_observations(self, task_id: str) -> list[ObservationEnvelope]:
        return await self._backend.list_observations(task_id)

    async def list_task_children(self, task_id: str) -> list[TaskSpawnView]:
        return await self._backend.list_task_children(task_id)

    async def get_task_tree(
        self,
        task_id: str,
        *,
        direction: TaskTreeDirection = "both",
        depth: int = 4,
    ) -> TaskTreeView | None:
        if depth < 1 or depth > 32:
            raise ValueError("Task tree depth must be between 1 and 32")
        root = await self._backend.get_task(task_id)
        if root is None:
            return None
        edges, truncated = await self._backend.list_task_tree_spawns(
            task_id,
            direction=direction,
            depth=depth,
        )
        node_ids = {task_id}
        for edge in edges:
            node_ids.add(edge.parent_task_id)
            node_ids.add(edge.child_task_id)

        async def load_node(node_id: str) -> TaskTreeNodeView | None:
            task, release, heartbeat, usage, steps = await asyncio.gather(
                self.get_task(node_id),
                self.get_task_agent_release(node_id),
                self.get_task_heartbeat_belief(node_id),
                self.get_task_usage(node_id),
                self.list_steps(node_id),
            )
            if task is None:
                return None
            current_step = max(
                (step for step in steps if step.status not in {"closed", "model_failed"}),
                key=lambda step: step.step_seq,
                default=None,
            )
            return TaskTreeNodeView(
                task=task,
                agent_release=release,
                heartbeat=heartbeat,
                current_step=(
                    None
                    if current_step is None
                    else ActiveStepView(
                        step_id=current_step.step_id,
                        step_seq=current_step.step_seq,
                        actor_kind=current_step.actor_kind,
                        status=current_step.status,
                    )
                ),
                usage=usage,
            )

        loaded = await asyncio.gather(*(load_node(node_id) for node_id in sorted(node_ids)))
        nodes = tuple(node for node in loaded if node is not None)
        return TaskTreeView(
            root_task_id=task_id,
            direction=direction,
            depth=depth,
            nodes=nodes,
            edges=tuple(edges),
            truncated=truncated,
        )

    async def list_alerts(
        self,
        *,
        limit: int = 100,
        alert_type: str | None = None,
        workflow_state: str | None = None,
        task_id: str | None = None,
        severity: str | None = None,
        shadow: bool | None = None,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
        cursor: tuple[datetime, str] | None = None,
    ) -> list[AlertSummaryView]:
        if limit < 1:
            raise ValueError("limit must be positive")
        list_alerts = getattr(self._backend, "list_alerts", None)
        if not callable(list_alerts):
            return []
        return list(
            await list_alerts(
                limit=limit,
                alert_type=alert_type,
                workflow_state=workflow_state,
                task_id=task_id,
                severity=severity,
                shadow=shadow,
                from_time=from_time,
                to_time=to_time,
                cursor=cursor,
            )
        )

    async def get_alert_detail(
        self,
        alert_id: str,
    ) -> AlertDetailView | None:
        get_detail = getattr(self._backend, "get_alert_detail", None)
        if not callable(get_detail):
            return None
        return await get_detail(alert_id)

    async def acknowledge_alert(
        self,
        alert_id: str,
        *,
        expected_workflow_version: int,
        operator_id: str,
        occurred_at: datetime | None = None,
    ) -> AlertSummaryView | None:
        return await self._change_alert_workflow(
            alert_id,
            action="acknowledge",
            expected_workflow_version=expected_workflow_version,
            operator_id=operator_id,
            reason=None,
            occurred_at=occurred_at,
        )

    async def dismiss_alert(
        self,
        alert_id: str,
        *,
        expected_workflow_version: int,
        operator_id: str,
        reason: str,
        occurred_at: datetime | None = None,
    ) -> AlertSummaryView | None:
        return await self._change_alert_workflow(
            alert_id,
            action="dismiss",
            expected_workflow_version=expected_workflow_version,
            operator_id=operator_id,
            reason=reason,
            occurred_at=occurred_at,
        )

    async def _change_alert_workflow(
        self,
        alert_id: str,
        *,
        action: str,
        expected_workflow_version: int,
        operator_id: str,
        reason: str | None,
        occurred_at: datetime | None,
    ) -> AlertSummaryView | None:
        change = getattr(self._backend, "change_alert_workflow", None)
        if not callable(change):
            return None
        return await change(
            alert_id,
            action=action,
            expected_workflow_version=expected_workflow_version,
            operator_id=operator_id,
            reason=reason,
            occurred_at=(datetime.now(UTC) if occurred_at is None else occurred_at),
        )

    async def get_task_action_target(
        self,
        task_id: str,
    ) -> TaskActionTarget | None:
        get_target = getattr(self._backend, "get_task_action_target", None)
        if not callable(get_target):
            return None
        return await get_target(task_id)

    async def get_operator_action(
        self,
        *,
        task_id: str,
        action_type: str,
        idempotency_key: str,
    ) -> OperatorActionView | None:
        get_action = getattr(self._backend, "get_operator_action", None)
        if not callable(get_action):
            return None
        return await get_action(
            task_id=task_id,
            action_type=action_type,
            idempotency_key=idempotency_key,
        )

    async def begin_operator_action(
        self,
        *,
        task_id: str,
        action_type: str,
        idempotency_key: str,
        operator_id: str,
        occurred_at: datetime | None = None,
    ) -> tuple[OperatorActionView, bool]:
        begin = getattr(self._backend, "begin_operator_action", None)
        if not callable(begin):
            raise RuntimeError("Ansich operator action audit is unavailable")
        return await begin(
            task_id=task_id,
            action_type=action_type,
            idempotency_key=idempotency_key,
            operator_id=operator_id,
            occurred_at=(datetime.now(UTC) if occurred_at is None else occurred_at),
        )

    async def finish_operator_action(
        self,
        action_id: str,
        *,
        succeeded: bool,
        operator_id: str,
        result: dict[str, object],
        occurred_at: datetime | None = None,
    ) -> OperatorActionView | None:
        finish = getattr(self._backend, "finish_operator_action", None)
        if not callable(finish):
            raise RuntimeError("Ansich operator action audit is unavailable")
        return await finish(
            action_id,
            succeeded=succeeded,
            operator_id=operator_id,
            result=result,
            occurred_at=(datetime.now(UTC) if occurred_at is None else occurred_at),
        )

    async def get_task_usage(self, task_id: str) -> TaskUsageView:
        return await self._backend.get_task_usage(task_id)

    async def get_task_usage_breakdown(
        self,
        task_id: str,
        *,
        scope: AggregationScope,
    ) -> TaskUsageBreakdownView:
        return await self._backend.get_task_usage_breakdown(task_id, scope=scope)

    async def get_task_budgets(self, task_id: str) -> TaskBudgetsView:
        return await self._backend.get_task_budgets(task_id)

    async def get_task_budget_health(
        self,
        task_id: str,
    ) -> tuple[BudgetHealthBelief, ...]:
        get_health = getattr(self._backend, "get_task_budget_health", None)
        if not callable(get_health):
            return ()
        return tuple(await get_health(task_id))

    async def get_task_heartbeat(self, task_id: str) -> TaskHeartbeatView | None:
        return await self._backend.get_task_heartbeat(task_id)

    async def assess_operations(self, *, now: datetime | None = None) -> int:
        projection_lock = self._projection_lock
        if projection_lock is None:
            return await self._assess_operations_unlocked(now=now)
        async with projection_lock:
            return await self._assess_operations_unlocked(now=now)

    async def _assess_operations_unlocked(
        self,
        *,
        now: datetime | None = None,
    ) -> int:
        assess = getattr(self._backend, "assess_operations", None)
        if not callable(assess):
            return 0
        with self._lock:
            incomplete_task_ids = tuple(sorted({lost_range.task_id for lost_range in self._lost_ranges if lost_range.task_id is not None}))
            global_loss = any(lost_range.task_id is None for lost_range in self._lost_ranges)
            lost_ranges = tuple(self._lost_ranges)
        return int(
            await assess(
                now=now,
                incomplete_task_ids=incomplete_task_ids,
                global_loss=global_loss,
                lost_ranges=lost_ranges,
            )
        )

    async def get_task_heartbeat_belief(
        self,
        task_id: str,
    ) -> HeartbeatBelief | None:
        get_belief = getattr(self._backend, "get_task_heartbeat_belief", None)
        if not callable(get_belief):
            return None
        return await get_belief(task_id)

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
        list_active = getattr(self._backend, "list_active_tasks", None)
        if not callable(list_active):
            return []
        return list(
            await list_active(
                limit=limit,
                owner_id=owner_id,
                agent_id=agent_id,
                control=control,
                heartbeat_status=heartbeat_status,
                budget_status=budget_status,
                min_duration_ms=min_duration_ms,
                max_duration_ms=max_duration_ms,
                observability_status=observability_status,
                cursor=cursor,
            )
        )

    async def list_timeline(
        self,
        task_id: str,
        *,
        limit: int,
        cursor: tuple[datetime, int] | None = None,
    ) -> list[tuple[int, ObservationEnvelope]]:
        return await self._backend.list_timeline(task_id, limit=limit, cursor=cursor)

    async def get_max_step_seq(self, task_id: str) -> int:
        """Return the projected maximum after callers have flushed the task.

        This is used for Step sequence allocation, so reading while task-step
        projection lags durable observations can allocate a duplicate value.
        """
        get_max = getattr(self._backend, "get_max_step_seq", None)
        if not callable(get_max):
            return 0
        return max(0, int(await get_max(task_id)))

    async def list_content_occurrences(self, task_id: str) -> list[ContentOccurrenceView]:
        list_occurrences = getattr(self._backend, "list_content_occurrences", None)
        if not callable(list_occurrences):
            return []
        return list(await list_occurrences(task_id))

    async def get_latest_context_state(self, task_id: str) -> ContextStateView | None:
        get_latest = getattr(self._backend, "get_latest_context_state", None)
        if not callable(get_latest):
            return None
        return await get_latest(task_id)

    async def list_steps(self, task_id: str) -> list[StepView]:
        return await self._backend.list_steps(task_id)

    async def list_system_operations(self, task_id: str) -> list[LlmAttemptView]:
        return await self._backend.list_system_operations(task_id)

    async def get_step(self, step_id: str) -> StepView | None:
        return await self._backend.get_step(step_id)

    async def get_tool_call(self, tool_call_id: str) -> ToolCallView | None:
        return await self._backend.get_tool_call(tool_call_id)

    async def get_task_scopes(self, task_id: str) -> TaskScopesView:
        return await self._backend.get_task_scopes(task_id)

    async def get_tool_authorization(
        self,
        tool_call_id: str,
    ) -> ToolAuthorizationView | None:
        return await self._backend.get_tool_authorization(tool_call_id)

    async def get_tool_effects(
        self,
        tool_call_id: str,
    ) -> ToolEffectsView | None:
        return await self._backend.get_tool_effects(tool_call_id)

    async def get_step_context(self, step_id: str) -> ContextSnapshotView | None:
        return await self._backend.get_step_context(step_id)

    async def get_context_snapshot(
        self,
        snapshot_id: str,
    ) -> ContextSnapshotView | None:
        return await self._backend.get_context_snapshot(snapshot_id)

    async def get_content_block_payload(self, block_id: str) -> ContentBlockPayloadView | None:
        return await self._backend.get_content_block_payload(block_id)

    async def get_context_compression(
        self,
        compression_id: str,
    ) -> ContextCompressionView | None:
        return await self._backend.get_context_compression(compression_id)

    async def list_context_compressions(
        self,
        task_id: str,
        *,
        limit: int = 100,
        cursor: tuple[datetime, str] | None = None,
    ) -> list[ContextCompressionSummaryView]:
        if limit < 1:
            raise ValueError("limit must be positive")
        return list(
            await self._backend.list_context_compressions(
                task_id,
                limit=limit,
                cursor=cursor,
            )
        )

    async def get_content_lineage(
        self,
        block_id: str,
        *,
        direction: LineageDirection = "backward",
        max_depth: int = 8,
        max_nodes: int = 500,
    ) -> ContentLineageView | None:
        return await traverse_content_lineage(
            block_id,
            direction=direction,
            max_depth=max_depth,
            max_nodes=max_nodes,
            get_blocks=self._backend.get_content_blocks,
            get_derivations=self._backend.list_content_derivations,
        )

    async def get_possible_exposures(
        self,
        block_id: str,
        *,
        max_depth: int = 8,
        max_nodes: int = 500,
    ) -> PossibleExposureView | None:
        return await find_possible_exposures(
            block_id,
            max_depth=max_depth,
            max_nodes=max_nodes,
            get_blocks=self._backend.get_content_blocks,
            get_derivations=self._backend.list_content_derivations,
            list_snapshot_exposures=self._backend.list_snapshot_exposures,
        )

    async def rebuild_projections(self) -> int:
        rebuild = getattr(self._backend, "rebuild_projections", None)
        if not callable(rebuild):
            return 0
        projection_lock = self._projection_lock
        if projection_lock is None:
            rebuilt = int(await rebuild())
            await self._assess_operations_unlocked()
            return rebuilt
        # The reset-and-replay must never interleave with the background
        # projector loop claiming the same jobs (SQLite has no SKIP LOCKED).
        async with projection_lock:
            rebuilt = int(await rebuild())
            await self._assess_operations_unlocked()
            return rebuilt

    async def retry_failed_projections(self, *, task_id: str | None = None) -> int:
        retry_failed = getattr(self._backend, "retry_failed_projections", None)
        if not callable(retry_failed):
            return 0
        projection_lock = self._projection_lock
        if projection_lock is None:
            return int(await retry_failed(task_id=task_id))
        async with projection_lock:
            return int(await retry_failed(task_id=task_id))

    async def list_failed_jobs(
        self,
        *,
        task_id: str | None = None,
        limit: int = 100,
    ) -> list[FailedJobSummaryView]:
        list_failed = getattr(self._backend, "list_failed_jobs", None)
        if not callable(list_failed):
            return []
        return list(await list_failed(task_id=task_id, limit=limit))

    async def get_failed_job_detail(
        self,
        *,
        job_id: str,
        kind: FailedJobKind,
    ) -> FailedJobDetailView | None:
        get_detail = getattr(self._backend, "get_failed_job_detail", None)
        if not callable(get_detail):
            return None
        return await get_detail(job_id=job_id, kind=kind)

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._wake_event is not None:
            self._wake_event.set()
        writer_task = self._writer_task
        if writer_task is not None:
            await writer_task
        self._writer_task = None
        if self._projector_wake_event is not None:
            self._projector_wake_event.set()
        projector_task = self._projector_task
        if projector_task is not None:
            await projector_task
        self._projector_task = None

    def _record_loss(
        self,
        sequence: int,
        task_id: str | None,
        *,
        producer_name: str | None = None,
        producer_instance_id: str | None = None,
    ) -> None:
        self._dropped_count += 1
        if self._lost_ranges:
            previous = self._lost_ranges[-1]
            if previous.task_id == task_id and previous.producer_name == producer_name and previous.producer_instance_id == producer_instance_id and previous.last_sequence + 1 == sequence:
                self._lost_ranges[-1] = previous.model_copy(update={"last_sequence": sequence})
                return
        self._lost_ranges.append(
            LostRange(
                first_sequence=sequence,
                last_sequence=sequence,
                task_id=task_id,
                producer_name=producer_name,
                producer_instance_id=producer_instance_id,
            )
        )

    def _record_batch_loss(
        self,
        sequences: tuple[int, ...],
        observations: tuple[object, ...],
    ) -> tuple[LostRange, ...]:
        batch_ranges: list[LostRange] = []
        for sequence, observation in zip(sequences, observations, strict=True):
            if isinstance(observation, ObservationEnvelope):
                task_id = observation.task_id
                producer_name = observation.producer.name
                producer_instance_id = observation.producer.instance_id
                self._record_loss(
                    sequence,
                    task_id,
                    producer_name=producer_name,
                    producer_instance_id=producer_instance_id,
                )
            else:
                task_id = None
                producer_name = None
                producer_instance_id = None
                self._record_loss(sequence, task_id)
            if batch_ranges:
                previous = batch_ranges[-1]
                if previous.task_id == task_id and previous.producer_name == producer_name and previous.producer_instance_id == producer_instance_id and previous.last_sequence + 1 == sequence:
                    batch_ranges[-1] = previous.model_copy(update={"last_sequence": sequence})
                    continue
            batch_ranges.append(
                LostRange(
                    first_sequence=sequence,
                    last_sequence=sequence,
                    task_id=task_id,
                    producer_name=producer_name,
                    producer_instance_id=producer_instance_id,
                )
            )
        return tuple(batch_ranges)

    def _warn_batch_loss(
        self,
        *,
        reason: str,
        observation_count: int,
        lost_ranges: tuple[LostRange, ...],
    ) -> None:
        warning_at = time.monotonic()
        if self._last_drop_warning_at is not None and warning_at - self._last_drop_warning_at < _DROP_WARNING_INTERVAL_SECONDS:
            self._suppressed_drop_warning_count += 1
            return
        detected_at = datetime.now(UTC).isoformat()
        serialized_ranges = tuple(item.model_dump(mode="json") for item in lost_ranges)
        suppressed_warning_count = self._suppressed_drop_warning_count
        try:
            logger.warning(
                "Ansich collector dropped %d observation(s): reason=%s detected_at=%s lost_ranges=%s suppressed_drop_warnings=%d",
                observation_count,
                reason,
                detected_at,
                serialized_ranges,
                suppressed_warning_count,
                extra={
                    "event": "ansich.collector.observations_dropped",
                    "reason": reason,
                    "detected_at": detected_at,
                    "dropped_observation_count": observation_count,
                    "lost_ranges": serialized_ranges,
                    "queue_depth": len(self._queue),
                    "queue_capacity": self._capacity,
                    "queue_bytes": self._queue_bytes,
                    "queue_byte_capacity": self._byte_capacity,
                    "suppressed_drop_warning_count": suppressed_warning_count,
                },
            )
        except Exception:
            return
        self._last_drop_warning_at = warning_at
        self._suppressed_drop_warning_count = 0

    def _record_observation_loss(self, observation: ObservationEnvelope) -> None:
        self._record_loss(
            observation.producer_seq,
            observation.task_id,
            producer_name=observation.producer.name,
            producer_instance_id=observation.producer.instance_id,
        )

    def _take_task_items(self, task_id: str) -> list[tuple[int, ObservationEnvelope]]:
        selected: list[tuple[int, ObservationEnvelope]] = []
        retained: deque[tuple[int, ObservationEnvelope, int]] = deque()
        retained_bytes = 0
        while self._queue:
            sequence, observation, observation_size = self._queue.popleft()
            if observation.task_id == task_id:
                selected.append((sequence, observation))
            else:
                retained.append((sequence, observation, observation_size))
                retained_bytes += observation_size
        self._queue = retained
        self._queue_bytes = retained_bytes
        return selected

    async def _writer_loop(self) -> None:
        wake_event = self._wake_event
        persist_lock = self._persist_lock
        if wake_event is None or persist_lock is None:
            return
        while self._running or self._queue:
            if not self._queue:
                try:
                    await asyncio.wait_for(wake_event.wait(), timeout=self._flush_interval_seconds)
                except TimeoutError:
                    pass
            wake_event.clear()
            async with persist_lock:
                await self._flush_batch()

    async def _projector_loop(self) -> None:
        wake_event = self._projector_wake_event
        if wake_event is None:
            return
        loop = asyncio.get_running_loop()
        next_assessment = loop.time()
        while self._running:
            processed = await self._project_pending()
            current_time = loop.time()
            if current_time >= next_assessment:
                try:
                    await self.assess_operations()
                except Exception:
                    pass
                next_assessment = current_time + self._operations_assessment_interval_seconds
            if processed > 0:
                continue
            try:
                await asyncio.wait_for(
                    wake_event.wait(),
                    timeout=min(
                        self._projector_poll_interval_seconds,
                        max(0.001, next_assessment - loop.time()),
                    ),
                )
            except TimeoutError:
                pass
            wake_event.clear()
        while await self._project_pending() > 0:
            pass
        try:
            await self.assess_operations()
        except Exception:
            pass

    async def _flush_batch(self) -> FlushResult:
        with self._lock:
            queued = [self._queue.popleft() for _ in range(min(len(self._queue), self._batch_size))]
            self._queue_bytes -= sum(item[2] for item in queued)
            selected = [(sequence, observation) for sequence, observation, _ in queued]
        return await self._persist_items(selected)

    async def _persist_items(self, selected: list[tuple[int, ObservationEnvelope]]) -> FlushResult:
        if not selected:
            return FlushResult(persisted=True, processed_count=0)
        try:
            processed = await self._backend.persist_and_project([observation for _, observation in selected])
        except Exception:
            with self._lock:
                for _, observation in selected:
                    self._record_observation_loss(observation)
            return FlushResult(persisted=False, processed_count=0, reason="storage_failure")
        self._notify_persisted(selected)
        if self._projector_wake_event is not None:
            self._projector_wake_event.set()
        await self._report_degradation_if_storage_recovered()
        return FlushResult(persisted=True, processed_count=processed)

    def _notify_persisted(self, selected: list[tuple[int, ObservationEnvelope]]) -> None:
        observation_ids_by_task: dict[str, list[str]] = {}
        for _, observation in selected:
            observation_ids_by_task.setdefault(observation.task_id, []).append(observation.obs_id)
        callbacks: list[tuple[Callable[[tuple[str, ...]], None], tuple[str, ...]]] = []
        with self._lock:
            for task_id, observation_ids in observation_ids_by_task.items():
                retained: list[ReferenceType[object]] = []
                for listener_ref in self._persistence_listeners.get(task_id, []):
                    listener = listener_ref()
                    if listener is None:
                        continue
                    retained.append(listener_ref)
                    callbacks.append((listener, tuple(observation_ids)))  # type: ignore[arg-type]
                if retained:
                    self._persistence_listeners[task_id] = retained
                else:
                    self._persistence_listeners.pop(task_id, None)
        for listener, observation_ids in callbacks:
            try:
                listener(observation_ids)
            except Exception:
                continue

    async def _report_degradation_if_storage_recovered(self) -> None:
        with self._lock:
            ranges = tuple(self._lost_ranges[self._reported_lost_range_count :])
        observations = [
            ObservationEnvelope(
                kind="observability.degraded",
                occurred_at=datetime.now(UTC),
                task_id=lost_range.task_id,
                subject_id=lost_range.task_id,
                producer=Producer(
                    name="ansich-collector",
                    version="1",
                    instance_id=lost_range.producer_instance_id or "local",
                ),
                producer_seq=lost_range.last_sequence,
                source_event_id=(f"loss:{lost_range.task_id}:{lost_range.first_sequence}:{lost_range.last_sequence}"),
                correlation_id=lost_range.task_id,
                payload={
                    "first_sequence": lost_range.first_sequence,
                    "last_sequence": lost_range.last_sequence,
                    "producer_name": lost_range.producer_name or "unknown",
                    "producer_instance_id": lost_range.producer_instance_id or "unknown",
                },
            )
            for lost_range in ranges
            if lost_range.task_id is not None
        ]
        if not observations:
            return
        try:
            await self._backend.persist_and_project(observations)
        except Exception:
            return
        with self._lock:
            self._reported_lost_range_count += len(ranges)
        if self._projector_wake_event is not None:
            self._projector_wake_event.set()

    async def _project_pending(self) -> int:
        project_pending = getattr(self._backend, "project_pending", None)
        if not callable(project_pending):
            return 0
        projection_lock = self._projection_lock
        if projection_lock is None:
            return 0
        try:
            async with projection_lock:
                return int(await project_pending(limit=self._batch_size * 2))
        except Exception:
            return 0

    async def _project_until_task_settled(self, task_id: str) -> None:
        has_pending_for_task = getattr(self._backend, "has_pending_for_task", None)
        if not callable(has_pending_for_task):
            return
        while await has_pending_for_task(task_id):
            processed = await self._project_pending()
            if processed == 0:
                await asyncio.sleep(min(self._projector_poll_interval_seconds, 0.01))
