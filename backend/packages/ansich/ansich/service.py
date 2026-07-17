from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime
from threading import Lock
from weakref import ReferenceType, WeakMethod, ref

from ansich.backend import AnsichBackend
from ansich.compression import ContextCompressionView
from ansich.context_state import ContextStateView
from ansich.contracts import AnsichHealth, ControlValue, FlushResult, LostRange, ObservationEnvelope, Producer, RecordReceipt, TaskView
from ansich.lineage import ContentLineageView, LineageDirection, PossibleExposureView, find_possible_exposures, traverse_content_lineage
from ansich.memory import InMemoryAnsichBackend
from ansich.step import ContentBlockPayloadView, ContentOccurrenceView, ContextSnapshotView, LlmAttemptView, StepView
from ansich.tool import ToolCallView


class AnsichService:
    """Small public interface around collection, projection, and Task queries."""

    def __init__(
        self,
        backend: AnsichBackend,
        *,
        queue_capacity: int = 10_000,
        batch_size: int = 100,
        flush_interval_ms: int = 100,
        terminal_flush_timeout_ms: int = 2_000,
        projector_poll_interval_ms: int = 250,
        unavailable_reason: str | None = None,
    ) -> None:
        if queue_capacity < 1:
            raise ValueError("queue_capacity must be positive")
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        if flush_interval_ms < 1:
            raise ValueError("flush_interval_ms must be positive")
        if terminal_flush_timeout_ms < 1:
            raise ValueError("terminal_flush_timeout_ms must be positive")
        if projector_poll_interval_ms < 1:
            raise ValueError("projector_poll_interval_ms must be positive")
        self._capacity = queue_capacity
        self._batch_size = batch_size
        self._flush_interval_seconds = flush_interval_ms / 1000
        self._terminal_flush_timeout_seconds = terminal_flush_timeout_ms / 1000
        self._projector_poll_interval_seconds = projector_poll_interval_ms / 1000
        self._queue: deque[tuple[int, ObservationEnvelope]] = deque()
        self._lock = Lock()
        self._running = False
        self._backend = backend
        self._unavailable_reason = unavailable_reason
        self._record_sequence = 0
        self._accepted_count = 0
        self._dropped_count = 0
        self._queue_high_watermark = 0
        self._snapshot_request_count = 0
        self._snapshot_observations_accepted = 0
        self._snapshot_observations_dropped = 0
        self._lost_ranges: list[LostRange] = []
        self._reported_lost_range_count = 0
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
        batch_size: int = 100,
        flush_interval_ms: int = 100,
        terminal_flush_timeout_ms: int = 2_000,
        projector_poll_interval_ms: int = 250,
    ) -> AnsichService:
        return cls(
            InMemoryAnsichBackend(),
            queue_capacity=queue_capacity,
            batch_size=batch_size,
            flush_interval_ms=flush_interval_ms,
            terminal_flush_timeout_ms=terminal_flush_timeout_ms,
            projector_poll_interval_ms=projector_poll_interval_ms,
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
        with self._lock:
            first_sequence = self._record_sequence + 1
            self._record_sequence += len(batch)
            sequences = tuple(range(first_sequence, self._record_sequence + 1))
            if batch_kind == "context_snapshot":
                self._snapshot_request_count += 1
            reason = None
            if any(not isinstance(observation, ObservationEnvelope) for observation in batch):
                reason = "validation_failed"
            elif self._unavailable_reason is not None:
                reason = self._unavailable_reason
            elif not self._running:
                reason = "service_not_running"
            elif len(self._queue) + len(batch) > self._capacity:
                reason = "queue_full"
            if reason is not None:
                self._record_batch_loss(sequences, batch)
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
            for sequence, observation in zip(sequences, batch, strict=True):
                self._queue.append((sequence, observation))
            self._accepted_count += len(batch)
            self._queue_high_watermark = max(self._queue_high_watermark, len(self._queue))
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
                    removed_count = len(self._queue) - len(retained)
                    if removed_count:
                        self._queue = retained
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

    async def get_task_by_source(self, source_kind: str, source_id: str) -> TaskView | None:
        return await self._backend.get_task_by_source(source_kind, source_id)

    async def list_tasks(
        self,
        *,
        limit: int = 100,
        control: ControlValue | None = None,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
        cursor: tuple[datetime, str] | None = None,
    ) -> list[TaskView]:
        if limit < 1:
            raise ValueError("limit must be positive")
        return await self._backend.list_tasks(
            limit=limit,
            control=control,
            from_time=from_time,
            to_time=to_time,
            cursor=cursor,
        )

    async def list_observations(self, task_id: str) -> list[ObservationEnvelope]:
        return await self._backend.list_observations(task_id)

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
            return int(await rebuild())
        # The reset-and-replay must never interleave with the background
        # projector loop claiming the same jobs (SQLite has no SKIP LOCKED).
        async with projection_lock:
            return int(await rebuild())

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
    ) -> None:
        for sequence, observation in zip(sequences, observations, strict=True):
            if isinstance(observation, ObservationEnvelope):
                self._record_loss(
                    sequence,
                    observation.task_id,
                    producer_name=observation.producer.name,
                    producer_instance_id=observation.producer.instance_id,
                )
            else:
                self._record_loss(sequence, None)

    def _record_observation_loss(self, observation: ObservationEnvelope) -> None:
        self._record_loss(
            observation.producer_seq,
            observation.task_id,
            producer_name=observation.producer.name,
            producer_instance_id=observation.producer.instance_id,
        )

    def _take_task_items(self, task_id: str) -> list[tuple[int, ObservationEnvelope]]:
        selected: list[tuple[int, ObservationEnvelope]] = []
        retained: deque[tuple[int, ObservationEnvelope]] = deque()
        while self._queue:
            sequence, observation = self._queue.popleft()
            if observation.task_id == task_id:
                selected.append((sequence, observation))
            else:
                retained.append((sequence, observation))
        self._queue = retained
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
        while self._running:
            processed = await self._project_pending()
            if processed > 0:
                continue
            try:
                await asyncio.wait_for(wake_event.wait(), timeout=self._projector_poll_interval_seconds)
            except TimeoutError:
                pass
            wake_event.clear()
        while await self._project_pending() > 0:
            pass

    async def _flush_batch(self) -> FlushResult:
        with self._lock:
            selected = [self._queue.popleft() for _ in range(min(len(self._queue), self._batch_size))]
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
