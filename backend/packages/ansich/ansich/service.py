from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict, deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Lock
from weakref import ReferenceType, WeakMethod, ref

from ansich.alerts.views import AlertDetailView, AlertSummaryView, BeliefAssertionView
from ansich.backend import AnsichBackend
from ansich.budget import BudgetHealthBelief, TaskBudgetsView
from ansich.compression import ContextCompressionSummaryView, ContextCompressionView
from ansich.context_state import ContextStateView
from ansich.contracts import AnsichHealth, ControlValue, FlushResult, LostRange, ObservationEnvelope, Producer, ProducerHealth, RecordReceipt, TaskLifecycleScope, TaskView, WriterHealth
from ansich.environment import (
    EnvironmentHistoryView,
    TaskEnvironmentView,
    TaskToolEnvSamplesView,
    ToolEnvironmentSampleView,
)
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
from ansich.lifecycle import LifecycleInputs, derive_status
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
from ansich.usage import AggregationScope, TaskUsageBreakdownView, TaskUsageByModelView, TaskUsageView

logger = logging.getLogger(__name__)
_DROP_WARNING_INTERVAL_SECONDS = 60.0
_PRODUCER_ACCOUNT_LIMIT = 256


def _serialized_observation_size(observation: ObservationEnvelope) -> int:
    try:
        return len(observation.model_dump_json().encode("utf-8"))
    except Exception:
        return -1


@dataclass
class _ProducerAccount:
    """One producer instance's running tally, kept behind ``AnsichService._lock``.

    :class:`~ansich.contracts.ProducerHealth` is the frozen report rendered from
    this; this is the mutable ledger the record and writer paths update in
    place. Every field starts at the value that means "nothing measured yet"
    rather than at a value that means "measured, and it was fine".
    """

    accepted_count: int = 0
    dropped_count: int = 0
    last_accepted_sequence: int | None = None
    serialization_failures: int = 0
    last_successful_flush_at: datetime | None = None


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
        writer_retry_max_attempts: int = 5,
        writer_backoff_initial_ms: int = 100,
        writer_backoff_max_ms: int = 5_000,
        writer_item_max_attempts: int = 2,
        stop_drain_timeout_ms: int = 10_000,
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
        if writer_retry_max_attempts < 1:
            raise ValueError("writer_retry_max_attempts must be positive")
        if writer_backoff_initial_ms < 1:
            raise ValueError("writer_backoff_initial_ms must be positive")
        if writer_backoff_max_ms < 1:
            raise ValueError("writer_backoff_max_ms must be positive")
        if writer_item_max_attempts < 1:
            raise ValueError("writer_item_max_attempts must be positive")
        if stop_drain_timeout_ms < 1:
            raise ValueError("stop_drain_timeout_ms must be positive")
        self._capacity = queue_capacity
        self._byte_capacity = queue_byte_capacity
        self._batch_size = batch_size
        self._flush_interval_seconds = flush_interval_ms / 1000
        self._terminal_flush_timeout_seconds = terminal_flush_timeout_ms / 1000
        self._projector_poll_interval_seconds = projector_poll_interval_ms / 1000
        self._operations_assessment_interval_seconds = operations_assessment_interval_ms / 1000
        self._writer_retry_max_attempts = writer_retry_max_attempts
        self._writer_backoff_initial_ms = writer_backoff_initial_ms
        self._writer_backoff_max_ms = writer_backoff_max_ms
        # Held for the tasks that consume them: per-item isolation (Task 5) and
        # the bounded stop drain (Task 7). Threaded now so the config path is
        # wired once rather than three times.
        self._writer_item_max_attempts = writer_item_max_attempts
        self._stop_drain_timeout_seconds = stop_drain_timeout_ms / 1000
        self._queue: deque[tuple[int, ObservationEnvelope, int]] = deque()
        self._queue_bytes = 0
        self._lock = Lock()
        self._running = False
        self._started = False
        self._stopping = False
        self._stopped = False
        self._backend = backend
        self._unavailable_reason = unavailable_reason
        self._record_sequence = 0
        self._accepted_count = 0
        self._dropped_count = 0
        # LRU-ordered, bounded at `_PRODUCER_ACCOUNT_LIMIT`; see `_producer_account`.
        self._producer_accounts: OrderedDict[tuple[str, str], _ProducerAccount] = OrderedDict()
        self._evicted_producer_count = 0
        self._writer_consecutive_failures = 0
        self._writer_backoff_until: datetime | None = None
        # Rows storage refused on their own, past `writer_item_max_attempts`,
        # after the batch they arrived in had already been bisected. Each one is
        # also charged as loss; this counter is what names the *reason*, which
        # `dropped_count` alone cannot — and it is monotonic, so an incident
        # stays legible while the writer oscillates between degraded and
        # recovering around it.
        self._poison_observation_count = 0
        # The batches the writer has taken off the queue and not yet placed.
        # Keyed by an opaque token so a batch can be released exactly once from
        # either the success path or the caller's `finally`, and kept whole so
        # the flush barrier (Task 6) and the stop drain (Task 7) can read both
        # its size and its collector-sequence span.
        self._in_flight: dict[int, tuple[tuple[int, ObservationEnvelope], ...]] = {}
        self._in_flight_token = 0
        # PA6's recovery evidence: raised by a write failure, lowered only once
        # the writer has caught up again. `recovering` may be derived from this
        # and never from a bare queue backlog — see `ansich.lifecycle`.
        self._writer_retry_backlog = False
        self._queue_high_watermark = 0
        self._queue_byte_high_watermark = 0
        self._snapshot_request_count = 0
        self._snapshot_observations_accepted = 0
        self._snapshot_observations_dropped = 0
        self._lost_ranges: list[LostRange] = []
        # How far the degradation-reporting pass has scanned `_lost_ranges`.
        # Deliberately *not* called a reported count (RA8②): a Task-scoped range
        # below it was written into the Observation stream, a process-wide one
        # was filed in `_unreported_global_ranges` instead, and the two must not
        # be counted as the same thing.
        self._lost_range_report_cursor = 0
        # Process-wide loss — a range with no Task to subject an
        # `observability.degraded` Observation against. Nothing in this batch
        # persists these (the subject design is P11-B's host-Scope work), so
        # they are held here, counted in health, and never claimed as reported.
        self._unreported_global_ranges: list[LostRange] = []
        # Lowest sequence ever charged as lost. A lost sequence is a permanent
        # hole: the contiguous persistence watermark can never pass it.
        self._lowest_lost_sequence: int | None = None
        self._last_drop_warning_at: float | None = None
        self._suppressed_drop_warning_count = 0
        self._loop: asyncio.AbstractEventLoop | None = None
        self._wake_event: asyncio.Event | None = None
        self._stop_event: asyncio.Event | None = None
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
        writer_retry_max_attempts: int = 5,
        writer_backoff_initial_ms: int = 100,
        writer_backoff_max_ms: int = 5_000,
        writer_item_max_attempts: int = 2,
        stop_drain_timeout_ms: int = 10_000,
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
            writer_retry_max_attempts=writer_retry_max_attempts,
            writer_backoff_initial_ms=writer_backoff_initial_ms,
            writer_backoff_max_ms=writer_backoff_max_ms,
            writer_item_max_attempts=writer_item_max_attempts,
            stop_drain_timeout_ms=stop_drain_timeout_ms,
        )

    async def start(self) -> None:
        if self._running:
            return
        # Re-arm the lifecycle flags before the first await, `_started` first:
        # a restart must be observed as stopped -> starting -> healthy, and
        # clearing `_stopped` first would let a reader see the service back in
        # service before it is. Every flag is written on the loop thread and
        # read under `_lock`, so a reader only ever sees whole assignments; the
        # ordering is what keeps the sequence of those reads legal.
        self._started = False
        self._stopping = False
        self._stopped = False
        try:
            initialize_metrics = getattr(self._backend, "initialize_metrics", None)
            if callable(initialize_metrics):
                await initialize_metrics()
            self._loop = asyncio.get_running_loop()
            self._wake_event = asyncio.Event()
            # A separate signal from `_wake_event` on purpose: new work must
            # never cut a backoff short (that would hammer a storage backend
            # that just refused a write), while shutdown always must.
            self._stop_event = asyncio.Event()
            self._projector_wake_event = asyncio.Event()
            self._persist_lock = asyncio.Lock()
            self._projection_lock = asyncio.Lock()
            self._running = True
            self._started = True
            self._writer_task = asyncio.create_task(self._writer_loop(), name="ansich-batch-writer")
            if callable(getattr(self._backend, "project_pending", None)):
                self._projector_task = asyncio.create_task(self._projector_loop(), name="ansich-projector")
        except BaseException:
            # A start that never finished leaves the service exactly as stopped
            # as it was before the attempt: reporting `starting` forever would
            # claim a collector is on its way up when nothing is coming.
            self._stopped = True
            raise

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
            # Charged before the reject decision below, and deliberately so: one
            # unserializable item rejects the whole batch, so counting these on
            # the accept path would mean nobody is ever charged for the failure
            # that caused the rejection. A non-envelope item is measured as 0
            # rather than -1 and has no producer identity to charge.
            for observation, observation_size in zip(batch, observation_sizes, strict=True):
                if observation_size < 0 and isinstance(observation, ObservationEnvelope):
                    self._producer_account(observation.producer.name, observation.producer.instance_id).serialization_failures += 1
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
                account = self._producer_account(observation.producer.name, observation.producer.instance_id)
                account.accepted_count += 1
                # Sequences are allocated and appended inside this one locked
                # section, so they only ever move forward for a given producer.
                account.last_accepted_sequence = sequence
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
                    removed = [item for item in self._queue if item[0] in sequence_set]
                    removed_bytes = sum(item[2] for item in removed)
                    removed_count = len(removed)
                    if removed_count:
                        self._queue = retained
                        self._queue_bytes -= removed_bytes
                        self._accepted_count -= removed_count
                        for _, removed_observation, _ in removed:
                            # Mirror the process-wide un-accept above: the loss
                            # recorded below charges these to their producer, so
                            # leaving them counted as accepted as well would
                            # report one observation twice. `last_accepted_sequence`
                            # is left alone — the range is reported as lost, and
                            # the producer's previous sequence is not kept.
                            self._producer_account(removed_observation.producer.name, removed_observation.producer.instance_id).accepted_count -= 1
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
            status = derive_status(
                LifecycleInputs(
                    started=self._started,
                    stopping=self._stopping,
                    stopped=self._stopped,
                    unavailable_reason=self._unavailable_reason,
                    consecutive_write_failures=self._writer_consecutive_failures,
                    # Real residue rather than a placeholder (RA8②). It changes
                    # no answer today — `dropped_count` is raised by the same
                    # `_record_loss` call that files the range, and loss is
                    # permanent `degraded`, which outranks `recovering` — but
                    # the derivation now reads the fact instead of a constant,
                    # so a future rule that separates the two has its input.
                    unreported_loss_pending=bool(self._unreported_global_ranges),
                    writer_retry_backlog=self._writer_retry_backlog,
                    dropped_count=self._dropped_count,
                    failed_jobs=failed_jobs,
                    queue_depth=len(self._queue),
                    batch_size=self._batch_size,
                )
            )
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
                # Ordered by identity rather than by arrival or LRU position, so
                # two health reads of an unchanged ledger are diffable even while
                # the map itself churns.
                producers=tuple(
                    ProducerHealth(
                        producer_name=producer_name,
                        producer_instance_id=producer_instance_id,
                        accepted_count=account.accepted_count,
                        dropped_count=account.dropped_count,
                        last_accepted_sequence=account.last_accepted_sequence,
                        serialization_failures=account.serialization_failures,
                        last_successful_flush_at=account.last_successful_flush_at,
                    )
                    for (producer_name, producer_instance_id), account in sorted(self._producer_accounts.items(), key=lambda item: item[0])
                ),
                writer=WriterHealth(
                    consecutive_failures=self._writer_consecutive_failures,
                    backoff_until=self._writer_backoff_until,
                    # Items the writer holds are out of `queue_depth` — they no
                    # longer consume queue capacity — so this is the only place
                    # they are visible.
                    in_flight_count=self._in_flight_observation_count(),
                    # The one signal that separates "a row is unwritable" from
                    # "storage was down": both charge loss, only one of them
                    # will still be charging it after the outage clears.
                    poison_observation_count=self._poison_observation_count,
                ),
                evicted_producer_count=self._evicted_producer_count,
                # Loss nothing has reported and nothing in this batch will: a
                # range with no Task has no subject to be written against.
                # Visible so an operator sees the gap instead of inferring it
                # from a reported count that used to include it (RA8②).
                unreported_global_lost_range_count=len(self._unreported_global_ranges),
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
        """Persist every queued Observation up to this Task's last one.

        RA5①. The bound is a **collector sequence**, not a Task: ``S`` is the
        highest queued sequence belonging to ``task_id`` at call time, and every
        queued row at or below it is placed, in order. Flushing one Task
        therefore places a neighbour's earlier rows — which is not a side effect
        to tolerate but what "flushed up to ``S``" means. The by-Task extraction
        this replaces lifted one Task's rows out of the middle of the queue and
        left everything recorded before them behind, a reordering of the one
        sequence every reader of these rows treats as authoritative.

        **What the two success flags each claim.** ``persisted`` keeps its
        coarse meaning: *this call's* rows reached storage. ``persisted_through``
        is the precise one — the highest sequence with nothing missing
        underneath it — and the two legitimately disagree. The barrier takes
        queued rows only; a batch the writer has parked in flight is the
        writer's to resolve, so this call can place rows recorded *after* rows
        that are not durable yet. ``persisted=True`` beside a
        ``persisted_through`` below the caller's own sequences is that
        situation, stated rather than hidden.

        **A timeout no longer kills what it took** (RA5②). A budget running out
        is not evidence that storage refused anything, so rows this call never
        managed to place go back to the head of the queue in collector order and
        the writer places them once storage answers; the result reports
        ``timed_out=True`` and how far persistence actually got — including when
        the budget was spent settling projections for rows that are already
        durable, which is a lagging read model and never loss. A *refusal* is
        the only thing charged as loss, and the ranges this call charged come
        back in ``lost_ranges`` so the caller need not diff process-wide health
        to find its own.

        The single attempt behind that refusal is deliberate: retries and their
        backoff belong to the writer loop, never to an Agent's call stack.
        """

        persist_lock = self._persist_lock
        if persist_lock is None:
            return FlushResult(persisted=False, processed_count=0, reason="service_not_running")
        # Rows this call has taken off the queue and not yet resolved. Emptied
        # the moment they are placed or charged, so the `finally` below returns
        # exactly what is still unaccounted — including under a cancellation
        # that is not this call's own timeout.
        taken: list[tuple[int, ObservationEnvelope, int]] = []
        persist_result: FlushResult | None = None
        try:
            try:
                async with asyncio.timeout(self._terminal_flush_timeout_seconds):
                    async with persist_lock:
                        with self._lock:
                            taken = self._take_barrier_items(task_id)
                        selected = [(sequence, observation) for sequence, observation, _ in taken]
                        result = await self._persist_items(selected)
                        if not result.persisted:
                            # `_persist_items` charged what it was refused, so
                            # these rows are accounted; reporting the ranges is
                            # all that is left.
                            charged = self._observation_lost_ranges(selected)
                            taken = []
                            with self._lock:
                                watermark = self._persisted_through()
                            return result.model_copy(update={"persisted_through": watermark, "lost_ranges": charged})
                        taken = []
                        with self._lock:
                            watermark = self._persisted_through()
                        persist_result = result.model_copy(update={"persisted_through": watermark})
                        await self._project_until_task_settled(task_id)
                        return persist_result
            except TimeoutError:
                if persist_result is not None:
                    # Observations are already durable; only projection settling
                    # timed out, so the read model is lagging — never data loss.
                    return persist_result.model_copy(update={"reason": "projection_settle_timeout", "timed_out": True})
                with self._lock:
                    self._return_barrier_items(taken)
                    taken = []
                    watermark = self._persisted_through()
                self._wake_writer()
                return FlushResult(
                    persisted=False,
                    processed_count=0,
                    reason="terminal_flush_timeout",
                    persisted_through=watermark,
                    timed_out=True,
                )
        finally:
            # Anything still unresolved goes back, whatever ended this call: an
            # outer cancellation, or a failure raised past the write by
            # something downstream of it. Both used to leave rows that were off
            # the queue and charged to nobody. The cost is that a failure raised
            # *after* storage accepted them returns durable rows to the queue —
            # a re-write the backends' dedupe absorbs, which is the cheaper of
            # the two mistakes.
            if taken:
                with self._lock:
                    self._return_barrier_items(taken)
                self._wake_writer()

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

    async def get_task_usage_by_model(self, task_id: str) -> list[TaskUsageByModelView]:
        """Group the Task's own LLM attempt usage by reported provider model.

        Optional backend capability: a backend that does not retain physical
        attempts answers with an empty breakdown rather than failing the read.
        """

        by_model = getattr(self._backend, "get_task_usage_by_model", None)
        if not callable(by_model):
            return []
        return list(await by_model(task_id))

    async def get_task_budgets(self, task_id: str) -> TaskBudgetsView:
        return await self._backend.get_task_budgets(task_id)

    async def get_task_environment(self, task_id: str) -> TaskEnvironmentView:
        return await self._backend.get_task_environment(task_id)

    async def get_environment_history(
        self,
        scope_id: str,
        *,
        environment_scope: str,
        metric: str,
        window_minutes: int,
        max_points: int,
    ) -> EnvironmentHistoryView:
        """One metric's bounded recent trend on one Scope (lazy, on-demand)."""

        return await self._backend.get_environment_history(
            scope_id,
            environment_scope=environment_scope,
            metric=metric,
            window_minutes=window_minutes,
            max_points=max_points,
        )

    async def get_task_tool_env_samples(self, task_id: str) -> TaskToolEnvSamplesView:
        """The Task's per-command environment samples, in execution order."""

        return await self._backend.get_task_tool_env_samples(task_id)

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

    async def get_tool_environment_sample(self, tool_call_id: str) -> ToolEnvironmentSampleView | None:
        return await self._backend.get_tool_environment_sample(tool_call_id)

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
        # The drain is its own lifecycle phase: a backlog and write retries are
        # expected while it runs, so health reports ``shutting_down`` rather
        # than degradation until the loops have joined. Each flag is set before
        # the one it replaces is cleared, so a reader on another thread never
        # observes an in-between phase: `_stopping` goes up before `_running`
        # comes down, and `_stopped` before `_stopping` is cleared below.
        self._stopping = True
        self._running = False
        try:
            if self._stop_event is not None:
                self._stop_event.set()
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
        finally:
            # The terminal state is written here so a loop that raises leaves a
            # stopped service instead of one that reports shutting down forever.
            self._stopped = True
            self._stopping = False

    def _producer_account(self, producer_name: str, producer_instance_id: str) -> _ProducerAccount:
        """Return one producer instance's account, creating it on first sighting.

        Callers must already hold ``self._lock``: this is pure dict work, which
        is what keeps it legal on ``record()``'s non-blocking path.

        The map is bounded at ``_PRODUCER_ACCOUNT_LIMIT`` and evicts the least
        recently touched entry first, so a pathological ``instance_id`` cannot
        grow it without limit. Eviction is only ever triggered by a *new*
        producer arriving — an existing producer's own traffic never costs
        anybody their entry — and always increments ``_evicted_producer_count``:
        a producer may drop out of health, but never silently (RA3).
        """

        key = (producer_name, producer_instance_id)
        account = self._producer_accounts.get(key)
        if account is not None:
            self._producer_accounts.move_to_end(key)
            return account
        while len(self._producer_accounts) >= _PRODUCER_ACCOUNT_LIMIT:
            self._producer_accounts.popitem(last=False)
            self._evicted_producer_count += 1
        account = _ProducerAccount()
        self._producer_accounts[key] = account
        return account

    def _record_successful_flush(self, observations: Iterable[ObservationEnvelope]) -> None:
        """Stamp ``last_successful_flush_at`` for every producer in a persisted batch.

        This is the only writer of that field, and it runs in the writer
        coroutine after storage accepted the batch, so the timestamp can only
        ever mean "this producer's work reached storage". The clock is read
        before the lock is taken; under it there is nothing but dict work.
        """

        flushed_at = datetime.now(UTC)
        with self._lock:
            for observation in observations:
                self._producer_account(observation.producer.name, observation.producer.instance_id).last_successful_flush_at = flushed_at

    def _record_loss(
        self,
        sequence: int,
        task_id: str | None,
        *,
        producer_name: str | None = None,
        producer_instance_id: str | None = None,
    ) -> None:
        self._dropped_count += 1
        # Every loss path in the service funnels through here, so charging the
        # producer here rather than at each call site is what keeps a later
        # caller from forgetting to. An item with no producer identity (a
        # non-envelope) is counted process-wide only — unattributable loss is
        # reported as unattributed rather than guessed onto somebody.
        if producer_name is not None and producer_instance_id is not None:
            self._producer_account(producer_name, producer_instance_id).dropped_count += 1
        # A lost sequence is a permanent hole: nothing will ever write it, so
        # the contiguous persistence watermark can never pass it. Kept as one
        # number rather than rescanned out of `_lost_ranges`, which coalesces.
        if self._lowest_lost_sequence is None or sequence < self._lowest_lost_sequence:
            self._lowest_lost_sequence = sequence
        if self._lost_ranges:
            previous = self._lost_ranges[-1]
            if previous.task_id == task_id and previous.producer_name == producer_name and previous.producer_instance_id == producer_instance_id and previous.last_sequence + 1 == sequence:
                extended = previous.model_copy(update={"last_sequence": sequence})
                self._lost_ranges[-1] = extended
                # RA8②: a process-wide range is filed unreported the moment it
                # exists, so the bucket has to follow the same coalescing. The
                # identity check is what keeps the two lists in lockstep — only
                # the range that *is* the bucket's last entry may extend it.
                if task_id is None and self._unreported_global_ranges and self._unreported_global_ranges[-1] is previous:
                    self._unreported_global_ranges[-1] = extended
                return
        lost_range = LostRange(
            first_sequence=sequence,
            last_sequence=sequence,
            task_id=task_id,
            producer_name=producer_name,
            producer_instance_id=producer_instance_id,
        )
        self._lost_ranges.append(lost_range)
        if task_id is None:
            self._unreported_global_ranges.append(lost_range)

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

    def _record_observation_loss(self, sequence: int, observation: ObservationEnvelope) -> None:
        """Charge one observation at the **collector** sequence it was accepted under.

        RA8①. The accept path allocates collector sequences, and every
        `LostRange` a reader holds is numbered in them — including the ones the
        reject path records through `_record_batch_loss`. Recording a loss at
        `producer_seq` instead described the same gap in a *different*
        numbering: that field is a producer's own per-producer counter, so two
        producers legitimately share values and one producer's counter says
        nothing about where its rows landed in the collector's order. Nothing
        needed to change to fix it — every caller already carries the collector
        sequence beside the observation in its `(sequence, observation)` tuple.

        Callers must already hold ``self._lock``.
        """

        self._record_loss(
            sequence,
            observation.task_id,
            producer_name=observation.producer.name,
            producer_instance_id=observation.producer.instance_id,
        )

    def _take_barrier_items(self, task_id: str) -> list[tuple[int, ObservationEnvelope, int]]:
        """Take every queued row up to this Task's highest queued sequence.

        RA5①. The predecessor took the Task's own rows and left their queue
        neighbours behind, which reordered the collector sequence — the one
        order every reader of these rows is entitled to rely on — on the
        ordinary terminal path, with nothing wrong at all. The barrier is
        defined against that sequence instead: ``S`` is the highest queued
        sequence this Task owns right now, and everything at or below it goes,
        whoever recorded it.

        A Task with nothing queued returns an empty selection rather than
        searching the writer's hands: rows already in flight belong to the
        writer, and a barrier that took them back would be a second writer for
        the same batch.

        Callers must already hold ``self._lock``.
        """

        barrier_sequence: int | None = None
        for sequence, observation, _ in self._queue:
            # The highest sequence, not the last one seen: RA5① defines the
            # bound on the sequence itself, so it holds without leaning on the
            # queue's ordering.
            if observation.task_id == task_id and (barrier_sequence is None or sequence > barrier_sequence):
                barrier_sequence = sequence
        if barrier_sequence is None:
            return []
        taken: list[tuple[int, ObservationEnvelope, int]] = []
        retained: deque[tuple[int, ObservationEnvelope, int]] = deque()
        retained_bytes = 0
        for item in self._queue:
            if item[0] <= barrier_sequence:
                taken.append(item)
            else:
                retained.append(item)
                retained_bytes += item[2]
        self._queue = retained
        self._queue_bytes = retained_bytes
        return taken

    def _return_barrier_items(self, taken: list[tuple[int, ObservationEnvelope, int]]) -> None:
        """Put an unplaced barrier selection back at the head of the queue.

        RA5②. A budget running out says nothing about whether storage would
        have taken these rows — it was never asked, or had not answered — so
        charging them as lost invents an incident. They go back where they came
        from: at the head, in collector order, which is still ahead of
        everything left in the queue because they were taken as a prefix of it.

        The queue watermarks are re-raised here on purpose: these rows were
        counted into them when they were accepted, but anything recorded while
        this call held them was counted against a queue that was missing them,
        so the restored depth can be a peak no reader has seen yet. For the same
        reason the return may briefly carry the queue past its capacity — rows
        accepted in the gap took the space these had. That overshoot is bounded
        by the selection itself and drains with the next flush; enforcing the
        cap here would mean dropping rows nothing has refused, which is the loss
        this method exists to prevent.

        Callers must already hold ``self._lock``.
        """

        if not taken:
            return
        for item in reversed(taken):
            self._queue.appendleft(item)
        self._queue_bytes += sum(item[2] for item in taken)
        self._queue_high_watermark = max(self._queue_high_watermark, len(self._queue))
        self._queue_byte_high_watermark = max(self._queue_byte_high_watermark, self._queue_bytes)

    def _wake_writer(self) -> None:
        """Nudge the writer loop. Safe only on the event loop's own thread."""

        wake_event = self._wake_event
        if wake_event is not None:
            wake_event.set()

    def _persisted_through(self) -> int | None:
        """Highest collector sequence with nothing missing underneath it.

        "Contiguous" is the whole of it: ``persisted_through=N`` claims that
        every sequence up to ``N`` is durable, so the answer stops *below* the
        first sequence that is not — whether it is still queued, still in the
        writer's hands, or lost for good.

        Derived rather than accumulated. Every sequence the accept path handed
        out is in exactly one of four states, and three of them are already
        tracked: queued, held in flight, or charged as lost. A sequence in none
        of them, at or below the last one allocated, has been persisted — so
        the lowest sequence across those three answers the question, and no
        separate watermark can drift away from the facts it summarises.

        Two of the three are what keeps it honest where a simpler rule lies.
        "One below the lowest row the writer is holding" survives a parked
        batch but not a poison verdict: once the unwritable row is charged the
        writer holds nothing, and that rule would happily claim the *lost*
        sequence as persisted. Consulting the lowest charged sequence is what
        makes the hole permanent — which is what a hole in this stream is.

        Callers must already hold ``self._lock``, and must have resolved their
        own selection first: rows taken off the queue and not yet placed are in
        none of the three states and would read as durable.
        """

        # One past the last allocated sequence: with nothing outstanding, every
        # sequence the accept path handed out is durable.
        boundary = self._record_sequence + 1
        if self._queue:
            # Scanned rather than read off the head: the queue is kept in
            # sequence order, but an over-claim is exactly what this field
            # exists to prevent, so the answer does not rest on that invariant.
            boundary = min(boundary, min(item[0] for item in self._queue))
        in_flight_bounds = self._in_flight_sequence_bounds()
        if in_flight_bounds is not None:
            boundary = min(boundary, in_flight_bounds[0])
        if self._lowest_lost_sequence is not None:
            boundary = min(boundary, self._lowest_lost_sequence)
        watermark = boundary - 1
        return watermark if watermark > 0 else None

    @staticmethod
    def _observation_lost_ranges(selected: list[tuple[int, ObservationEnvelope]]) -> tuple[LostRange, ...]:
        """Coalesce a charged selection into the ranges its caller is handed.

        Reports only what *this* call lost. Process-wide health accumulates
        every range the collector ever charged and coalesces across calls, so a
        caller diffing it could not tell its own loss from a neighbour's.
        """

        ranges: list[LostRange] = []
        for sequence, observation in selected:
            producer_name = observation.producer.name
            producer_instance_id = observation.producer.instance_id
            if ranges:
                previous = ranges[-1]
                if previous.task_id == observation.task_id and previous.producer_name == producer_name and previous.producer_instance_id == producer_instance_id and previous.last_sequence + 1 == sequence:
                    ranges[-1] = previous.model_copy(update={"last_sequence": sequence})
                    continue
            ranges.append(
                LostRange(
                    first_sequence=sequence,
                    last_sequence=sequence,
                    task_id=observation.task_id,
                    producer_name=producer_name,
                    producer_instance_id=producer_instance_id,
                )
            )
        return tuple(ranges)

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
            # `_flush_batch` takes `persist_lock` per attempt rather than for
            # the whole batch: its retries wait, and a wait must never be held
            # against the terminal barrier. See its docstring for the ordering
            # contract that buys.
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
        """Place one queued batch, retrying a refused write on a bounded backoff.

        This is the writer loop's path, and the only one allowed to wait: spec
        §2 keeps backoff inside the writer coroutine so it can never sit on an
        Agent call stack. A refused batch leaves the queue but is *not* charged
        as loss — it is parked in flight and retried until storage takes it, the
        batch-level attempts run out (`_isolate_poison_batch` then places it row
        by row), or the service starts draining.

        **The persist lock covers taking the batch and writing it, and is given
        back before every wait.** Both halves of that are load-bearing:

        * Taking the batch off the queue and its *first* write happen under one
          lock acquisition. A barrier that slipped in between a pop and its
          write would place later rows while earlier ones sat unwritten in the
          writer's hands — on the ordinary healthy path, where nothing is wrong
          at all — and would return "persisted" for a Task whose earlier
          observations are still in flight.
        * A **retry** releases it. Holding the lock across a backoff would
          serialize the terminal barrier behind the writer's own clock: an Agent
          flushing a healthy Task would spend its whole budget waiting for a
          lock, never reach storage, and charge its rows as lost — one
          unwritable row would take the write path down with it.

        **Ordering contract.** The writer coroutine keeps FIFO for its own
        processing: a parked batch is always resolved to a conclusion — placed,
        bisected, or charged — before the next batch is popped. The terminal
        barrier may interleave ahead of a writer that is *waiting* — backing off
        or between two attempts of an isolated row — so during an incident rows
        can reach storage in a different order than the collector sequence
        assigned them. That is the system's existing
        late-arrival shape, not a new one: the assessor watermark exists
        precisely because evidence can be ingested after evidence that logically
        follows it, and collector sequence remains the authoritative order for
        everything that reads these rows. Buying ordering during an incident by
        blocking the barrier is the trade PA11 rejected — an Agent's terminal
        flush must not depend on another Task's bad row.
        """

        persist_lock = self._persist_lock
        if persist_lock is None:
            return FlushResult(persisted=False, processed_count=0, reason="service_not_running")
        token: int | None = None
        selected: list[tuple[int, ObservationEnvelope]] = []
        try:
            async with persist_lock:
                with self._lock:
                    queued = [self._queue.popleft() for _ in range(min(len(self._queue), self._batch_size))]
                    self._queue_bytes -= sum(item[2] for item in queued)
                    selected = [(sequence, observation) for sequence, observation, _ in queued]
                if not selected:
                    return FlushResult(persisted=True, processed_count=0)
                token = self._enter_in_flight(selected)
                result = await self._attempt_persist(selected, in_flight_token=token)
            attempt = 1
            while result is None:
                if not self._running:
                    # Draining. Retrying here would hold `stop()` open for as
                    # long as storage stays down, so the drain keeps today's
                    # semantics — one attempt, then the range is charged and
                    # reported. Task 7 gives that drain its own time budget.
                    return self._charge_batch_loss(selected, in_flight_token=token)
                if attempt >= self._writer_retry_max_attempts:
                    return await self._isolate_poison_batch(selected, in_flight_token=token)
                await self._wait_before_retry(self._backoff_delay_seconds(attempt))
                attempt += 1
                result = await self._attempt_persist_locked(selected, in_flight_token=token)
            return result
        except BaseException:
            # Cancellation is how an event loop shuts a writer down, and by then
            # this batch is out of the queue: if it left with the coroutine it
            # would be lost with nobody ever told. Charged only if still parked,
            # so a batch that already landed is not invented as a loss.
            if token is not None:
                self._charge_lost_batch(selected, in_flight_token=token, only_if_parked=True)
            raise
        finally:
            if token is not None:
                self._exit_in_flight(token)

    async def _isolate_poison_batch(
        self,
        selected: list[tuple[int, ObservationEnvelope]],
        *,
        in_flight_token: int,
    ) -> FlushResult:
        """Place the exhausted batch row by row, charging only what stays unwritable.

        Batch-level retries answer one question: *is storage down?* Once they
        run out the answer is no — storage is up and something about this batch
        is not writable — so the writer stops asking about the batch and starts
        asking about each row. Each row gets its own
        ``persist_and_project([obs])`` up to ``writer_item_max_attempts``; the
        rows storage takes land, and a row it keeps refusing on its own is
        declared poison: charged as loss at its **collector** sequence, counted
        in ``WriterHealth.poison_observation_count``, warned about once, and
        left behind so its batch-mates still reach storage.

        This is what removes the interim's real cost. A parked batch used to be
        retried whole, forever, and the queue behind it filled to capacity and
        tail-dropped — one unwritable row bought its neighbours' loss *plus*
        every observation recorded during the park. Now the loss is exactly one
        row wide.

        The properties that hold through the bisect:

        * **Lock discipline is unchanged** (PA11): each row's attempt is taken
          under ``persist_lock`` and every wait gives it back, so a terminal
          barrier writes straight through an isolation phase rather than
          spending its budget waiting for a lock.
        * **One backoff schedule, not two.** The capped delay opens the phase —
          the batch attempt that preceded it did just fail — and a row's own
          retry uses the same exponential-from-initial schedule as the batch
          path. A row that lands costs no wait at all, and neither does the row
          after a poison verdict: that verdict *is* the finding that storage is
          healthy.
        * **Warnings are rate-limited**, sharing ``_warn_batch_loss``'s 60s
          window with every other drop reason. A batch full of poison reports
          the first row and counts the rest as suppressed rather than emitting
          one WARNING per row.
        * **The in-flight buffer shrinks as rows resolve**, so health, the flush
          barrier and the stop drain never see the writer holding rows that are
          already durable — or already charged.
        * **Draining still wins.** A wait cut short by ``stop()`` charges the
          remainder rather than holding shutdown open; Task 7 gives that drain
          its own budget.
        """

        remaining = list(selected)
        processed = 0
        poison_count = 0
        # The batch attempt that sent us here failed, so the first per-item
        # attempt is a retry like any other and waits like one.
        delay = self._backoff_delay_seconds(None)
        while remaining:
            item = remaining[0]
            attempt = 0
            result: FlushResult | None = None
            while True:
                if delay > 0:
                    await self._wait_before_retry(delay)
                    if not self._running:
                        # Draining, and this row has already refused a write.
                        # Retrying the rest would hold `stop()` open for as long
                        # as storage stays unhappy, so the remainder is charged
                        # and reported instead — the same trade `_flush_batch`
                        # makes, and the same one Task 7 gives a budget to.
                        self._charge_lost_batch(remaining, in_flight_token=in_flight_token)
                        return FlushResult(persisted=False, processed_count=processed, reason="storage_failure")
                attempt += 1
                result = await self._attempt_persist_locked([item])
                if result is not None or attempt >= self._writer_item_max_attempts:
                    break
                delay = self._backoff_delay_seconds(attempt)
            remaining.pop(0)
            if result is not None:
                processed += result.processed_count
            else:
                self._charge_poison_observation(*item)
                poison_count += 1
            self._release_isolated_item(in_flight_token, remaining)
            # Storage just answered about this row — it took it, or it refused
            # this row alone every time it was asked while taking others. Either
            # way the next row starts without a wait; only a failure buys one.
            delay = 0.0
        if poison_count:
            return FlushResult(persisted=False, processed_count=processed, reason="poison_observation")
        return FlushResult(persisted=True, processed_count=processed)

    def _charge_poison_observation(self, sequence: int, observation: ObservationEnvelope) -> None:
        """Charge one unwritable row, count it, and say so once per window.

        The charge itself is the ordinary loss path — every loss in the service
        funnels through ``_record_loss`` so the producer ledger cannot be
        forgotten — at the collector sequence the accept path allocated for this
        row (RA8①). ``poison_observation_count`` is the part loss accounting
        cannot express: ``dropped_count`` says how much was lost, not that the
        cause was one row rather than an outage, and during an incident the
        writer's own failure count keeps being zeroed by every neighbour that
        lands. The counter is monotonic, so it names the incident even while the
        derived status oscillates between ``degraded`` and ``recovering``.

        The WARNING reuses ``_warn_batch_loss`` verbatim, rate limit included:
        a poison flurry must not become one log line per row.
        """

        lost_range = LostRange(
            first_sequence=sequence,
            last_sequence=sequence,
            task_id=observation.task_id,
            producer_name=observation.producer.name,
            producer_instance_id=observation.producer.instance_id,
        )
        with self._lock:
            self._poison_observation_count += 1
            self._record_observation_loss(sequence, observation)
            self._warn_batch_loss(
                reason="poison_observation",
                observation_count=1,
                lost_ranges=(lost_range,),
            )

    def _release_isolated_item(
        self,
        in_flight_token: int,
        remaining: list[tuple[int, ObservationEnvelope]],
    ) -> None:
        """Shrink the in-flight entry to what the bisect still holds.

        The batch entered isolation as one in-flight unit and is resolved one
        row at a time, so the buffer has to shrink with it: an entry still
        naming rows that are already durable would report them as held, and a
        cancellation reading that entry would charge them as lost.

        The per-item attempts deliberately do **not** carry the batch's token —
        `_record_write_success` releases the whole token, so the first row to
        land would release its still-held neighbours — which is why the
        caught-up rule that normally lives there is applied here instead, once
        the last row has resolved.

        It is applied whatever that last row's verdict was, poison included. The
        latch means "still catching up on what a write failure left behind", and
        a finished bisect is not catching up on anything: the writer holds
        nothing and the queue is short. Nothing is hidden by clearing it either
        — a bisect that charged a row leaves `dropped_count > 0`, which reports
        ``degraded`` permanently, so the incident outlives the residue that was
        evidence of it.
        """

        with self._lock:
            if remaining:
                if in_flight_token in self._in_flight:
                    self._in_flight[in_flight_token] = tuple(remaining)
                return
            self._in_flight.pop(in_flight_token, None)
            if not self._in_flight and len(self._queue) <= self._batch_size:
                self._writer_retry_backlog = False

    async def _attempt_persist_locked(
        self,
        selected: list[tuple[int, ObservationEnvelope]],
        *,
        in_flight_token: int | None = None,
    ) -> FlushResult | None:
        """One attempt, holding ``persist_lock`` for exactly that attempt.

        The lock serializes writes against the terminal barrier; it is not the
        writer's to keep while it is waiting to try again.
        """

        persist_lock = self._persist_lock
        if persist_lock is None:
            return await self._attempt_persist(selected, in_flight_token=in_flight_token)
        async with persist_lock:
            return await self._attempt_persist(selected, in_flight_token=in_flight_token)

    async def _persist_items(self, selected: list[tuple[int, ObservationEnvelope]]) -> FlushResult:
        """Place a batch with a single attempt; a refusal is charged as loss.

        The terminal flush barrier runs here, on the Agent's own call stack and
        inside its own timeout budget, which is exactly where spec §2 forbids a
        backoff wait. Retries therefore belong to `_flush_batch`; what a failure
        means for this caller is unchanged.
        """

        if not selected:
            return FlushResult(persisted=True, processed_count=0)
        result = await self._attempt_persist(selected)
        if result is not None:
            return result
        return self._charge_batch_loss(selected)

    async def _attempt_persist(
        self,
        selected: list[tuple[int, ObservationEnvelope]],
        *,
        in_flight_token: int | None = None,
    ) -> FlushResult | None:
        """One write attempt. ``None`` means storage refused this batch.

        Returning rather than raising is what lets the caller decide between
        retrying and charging the loss; the accounting either outcome needs is
        already done by the time it answers.
        """

        try:
            processed = await self._backend.persist_and_project([observation for _, observation in selected])
        except Exception:
            self._record_write_failure()
            return None
        self._record_write_success(in_flight_token=in_flight_token)
        # The only writer of `ProducerHealth.last_successful_flush_at`: every
        # success path has to keep coming through here.
        self._record_successful_flush(observation for _, observation in selected)
        self._notify_persisted(selected)
        if self._projector_wake_event is not None:
            self._projector_wake_event.set()
        await self._report_degradation_if_storage_recovered()
        return FlushResult(persisted=True, processed_count=processed)

    def _record_write_failure(self) -> None:
        with self._lock:
            self._writer_consecutive_failures += 1
            # PA6's incident evidence. Raised in the same locked section as the
            # failure count, which is what upholds the derivation's modelling
            # rule: a reader cannot see this residue without having already seen
            # its cause reported as `degraded`. Splitting these two writes would
            # open the `healthy -> recovering` edge the derivation assumes away.
            self._writer_retry_backlog = True

    def _record_write_success(self, *, in_flight_token: int | None = None) -> None:
        with self._lock:
            self._writer_consecutive_failures = 0
            self._writer_backoff_until = None
            if in_flight_token is not None:
                self._in_flight.pop(in_flight_token, None)
            # Caught up: nothing held, and no more than the one batch the next
            # flush empties. Until then the collector is still `recovering`.
            if not self._in_flight and len(self._queue) <= self._batch_size:
                self._writer_retry_backlog = False

    def _charge_batch_loss(
        self,
        selected: list[tuple[int, ObservationEnvelope]],
        *,
        in_flight_token: int | None = None,
    ) -> FlushResult:
        self._charge_lost_batch(selected, in_flight_token=in_flight_token)
        return FlushResult(persisted=False, processed_count=0, reason="storage_failure")

    def _charge_lost_batch(
        self,
        selected: list[tuple[int, ObservationEnvelope]],
        *,
        in_flight_token: int | None = None,
        only_if_parked: bool = False,
    ) -> bool:
        """Account a batch the collector could not place, releasing it in flight.

        Charged and released in one locked section: a batch that is both counted
        as lost and still reported as held would report the same observations
        twice to whoever is reading health at that moment.

        ``only_if_parked`` is the cancellation path's guard, and it decides two
        things at once. A batch that already landed and was released has nothing
        to charge, and charging it anyway would invent a loss that never
        happened. And what a still-parked batch may be charged is **what the
        buffer says it holds**, not the list that entered: per-item isolation
        shrinks that entry as rows resolve, so `selected` there names rows that
        are already durable and rows already charged as poison. Reading the
        released tuple keeps the charge exactly as wide as the remainder.
        """

        charged: tuple[tuple[int, ObservationEnvelope], ...] | list[tuple[int, ObservationEnvelope]] = selected
        with self._lock:
            if in_flight_token is not None:
                released = self._in_flight.pop(in_flight_token, None)
                if only_if_parked:
                    if released is None:
                        return False
                    charged = released
            for sequence, observation in charged:
                self._record_observation_loss(sequence, observation)
            self._writer_backoff_until = None
        return True

    def _enter_in_flight(self, selected: list[tuple[int, ObservationEnvelope]]) -> int:
        with self._lock:
            self._in_flight_token += 1
            token = self._in_flight_token
            self._in_flight[token] = tuple(selected)
            return token

    def _exit_in_flight(self, token: int) -> None:
        with self._lock:
            self._in_flight.pop(token, None)

    def _in_flight_observation_count(self) -> int:
        """Observations the writer holds. Callers must already hold ``_lock``."""

        return sum(len(batch) for batch in self._in_flight.values())

    def _in_flight_sequence_bounds(self) -> tuple[int, int] | None:
        """Lowest and highest collector sequence held, or ``None`` if nothing is.

        The flush barrier (Task 6) and the stop drain (Task 7) both need to know
        which sequences are in the writer's hands rather than in the queue, so
        the buffer answers that here instead of each of them reaching into it.
        Callers must already hold ``_lock``.
        """

        sequences = [sequence for batch in self._in_flight.values() for sequence, _ in batch]
        if not sequences:
            return None
        return min(sequences), max(sequences)

    def _backoff_delay_seconds(self, attempt: int | None) -> float:
        """Exponential from the initial delay, capped. ``None`` asks for the cap."""

        if attempt is None:
            return self._writer_backoff_max_ms / 1000
        # Bounded exponent: the multiplier is capped anyway, and an unbounded
        # shift on a long-lived retry would build a pointlessly huge integer.
        delay_ms = self._writer_backoff_initial_ms * (2 ** min(attempt - 1, 32))
        return min(delay_ms, self._writer_backoff_max_ms) / 1000

    async def _wait_before_retry(self, delay_seconds: float) -> None:
        """Back off before the next attempt, publishing the deadline in health."""

        with self._lock:
            self._writer_backoff_until = datetime.now(UTC) + timedelta(seconds=delay_seconds)
        try:
            await self._sleep_before_retry(delay_seconds)
        finally:
            with self._lock:
                self._writer_backoff_until = None

    async def _sleep_before_retry(self, delay_seconds: float) -> None:
        """The single sleeping point of the retry path, cut short by ``stop()``.

        Kept alone in its own method for two reasons: the interruption is the
        whole mechanism (a shutdown must never wait out a 5s backoff), and a
        test can drive the schedule through it without spending real time.
        """

        stop_event = self._stop_event
        if stop_event is None:
            await asyncio.sleep(delay_seconds)
            return
        waiter = asyncio.ensure_future(stop_event.wait())
        try:
            await asyncio.wait({waiter}, timeout=delay_seconds)
        finally:
            waiter.cancel()

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
        """Write the loss the collector charged back into the Observation stream.

        RA8②. An ``observability.degraded`` Observation is subjected to the lost
        range's Task, so a **process-wide** range — one charged for something
        that never was an Observation, and so has no Task — cannot be written
        at all. The cursor used to walk past those anyway, which marked as
        reported ranges nothing had ever written; they are instead filed in
        ``_unreported_global_ranges`` when they are charged, counted in health,
        and left for P11-B's host-Scope subject work to report.

        The cursor advances only after storage accepted the write, so a refused
        report is retried whole rather than skipped.
        """

        with self._lock:
            ranges = tuple(self._lost_ranges[self._lost_range_report_cursor :])
        if not ranges:
            return
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
        if observations:
            try:
                await self._backend.persist_and_project(observations)
            except Exception:
                # Nothing is consumed: the Task-scoped ranges in this window
                # must be offered again, and advancing past them here would be
                # the same lie in the other direction.
                return
        # The process-wide ranges in this window are already in the unreported
        # bucket, so advancing past them consumes nothing and claims nothing —
        # it only stops the pass re-scanning ranges it can never write.
        with self._lock:
            self._lost_range_report_cursor += len(ranges)
        if observations and self._projector_wake_event is not None:
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
