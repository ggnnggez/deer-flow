import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import anyio
import pytest
from ansich import AnsichService, ObservationEnvelope, TaskView, new_id
from ansich.memory import InMemoryAnsichBackend


class UnavailableBackend:
    async def persist_and_project(self, observations: list[ObservationEnvelope]) -> int:
        raise OSError("database unavailable")

    async def get_task(self, task_id: str) -> TaskView | None:
        return None


class BlockingBackend(UnavailableBackend):
    async def persist_and_project(self, observations: list[ObservationEnvelope]) -> int:
        await anyio.sleep_forever()
        return 0


class SlowProjectionBackend:
    """Persists durably but never reports the task's projection as settled."""

    def __init__(self) -> None:
        self.inner = InMemoryAnsichBackend()

    async def persist_and_project(self, observations: list[ObservationEnvelope]) -> int:
        return await self.inner.persist_and_project(observations)

    async def project_pending(self, *, limit: int = 200) -> int:
        return 0

    async def has_pending_for_task(self, task_id: str) -> bool:
        return True

    async def get_task(self, task_id: str) -> TaskView | None:
        return await self.inner.get_task(task_id)

    async def get_task_by_source(self, source_kind: str, source_id: str) -> TaskView | None:
        return await self.inner.get_task_by_source(source_kind, source_id)

    async def list_tasks(self, **kwargs) -> list[TaskView]:
        return await self.inner.list_tasks(**kwargs)

    async def list_observations(self, task_id: str) -> list[ObservationEnvelope]:
        return await self.inner.list_observations(task_id)


class RecoveringBackend:
    def __init__(self) -> None:
        self.inner = InMemoryAnsichBackend()
        self.fail_next_write = True

    async def persist_and_project(self, observations: list[ObservationEnvelope]) -> int:
        if self.fail_next_write:
            self.fail_next_write = False
            raise OSError("temporary storage outage")
        return await self.inner.persist_and_project(observations)

    async def get_task(self, task_id: str) -> TaskView | None:
        return await self.inner.get_task(task_id)

    async def get_task_by_source(self, source_kind: str, source_id: str) -> TaskView | None:
        return await self.inner.get_task_by_source(source_kind, source_id)

    async def list_tasks(self, **kwargs) -> list[TaskView]:
        return await self.inner.list_tasks(**kwargs)

    async def list_observations(self, task_id: str) -> list[ObservationEnvelope]:
        return await self.inner.list_observations(task_id)


@pytest.mark.anyio
async def test_completed_task_is_queryable_with_evidence_backed_control_belief():
    service = AnsichService.in_memory()
    await service.start()
    task_id = new_id()
    started_at = datetime(2026, 7, 17, 8, 0, tzinfo=UTC)

    try:
        service.record(
            ObservationEnvelope.task_lifecycle(
                kind="task.created",
                task_id=task_id,
                source_kind="deerflow_run",
                source_id="run-123",
                occurred_at=started_at,
                source_event_id="run:run-123:task:created",
            )
        )
        service.record(
            ObservationEnvelope.task_lifecycle(
                kind="task.started",
                task_id=task_id,
                source_kind="deerflow_run",
                source_id="run-123",
                occurred_at=started_at + timedelta(seconds=1),
                source_event_id="run:run-123:task:started",
            )
        )
        completed = service.record(
            ObservationEnvelope.task_lifecycle(
                kind="task.completed",
                task_id=task_id,
                source_kind="deerflow_run",
                source_id="run-123",
                occurred_at=started_at + timedelta(seconds=3),
                source_event_id="run:run-123:task:completed",
            )
        )

        flush = await service.flush_task(task_id)
        task = await service.get_task(task_id)
    finally:
        await service.stop()

    assert completed.accepted is True
    assert flush.persisted is True
    assert task is not None
    assert task.source_kind == "deerflow_run"
    assert task.source_id == "run-123"
    assert task.control.value == "completed"
    assert task.control.as_of == started_at + timedelta(seconds=3)
    assert task.control.fidelity_class == "hard"
    assert task.control.source.name == "task-control"
    assert task.control.source.version == "1"
    assert task.control.selected_by.name == "control-state"
    assert task.control.selected_by.version == "1"
    assert task.control.evidence_obs_ids == (completed.obs_id,)


@pytest.mark.anyio
async def test_terminal_task_does_not_regress_when_started_evidence_arrives_late():
    service = AnsichService.in_memory()
    await service.start()
    task_id = new_id()
    completed_at = datetime(2026, 7, 17, 10, 0, tzinfo=UTC)

    try:
        completed = service.record(
            ObservationEnvelope.task_lifecycle(
                kind="task.completed",
                task_id=task_id,
                source_kind="deerflow_run",
                source_id="run-terminal",
                occurred_at=completed_at,
                source_event_id="run:run-terminal:task:completed",
            )
        )
        service.record(
            ObservationEnvelope.task_lifecycle(
                kind="task.started",
                task_id=task_id,
                source_kind="deerflow_run",
                source_id="run-terminal",
                occurred_at=completed_at + timedelta(seconds=5),
                source_event_id="run:run-terminal:task:started-late",
            )
        )
        await service.flush_task(task_id)
        task = await service.get_task(task_id)
    finally:
        await service.stop()

    assert task is not None
    assert task.control.value == "completed"
    assert task.control.as_of == completed_at
    assert task.control.evidence_obs_ids == (completed.obs_id,)


@pytest.mark.anyio
async def test_full_queue_is_fail_open_and_visible_as_a_known_lost_range():
    service = AnsichService.in_memory(queue_capacity=1)
    await service.start()
    task_id = new_id()
    observed_at = datetime(2026, 7, 17, 11, 0, tzinfo=UTC)

    try:
        accepted = service.record(
            ObservationEnvelope.task_lifecycle(
                kind="task.created",
                task_id=task_id,
                source_kind="deerflow_run",
                source_id="run-overflow",
                occurred_at=observed_at,
                source_event_id="run:run-overflow:task:created",
                producer_seq=1,
            )
        )
        dropped = service.record(
            ObservationEnvelope.task_lifecycle(
                kind="task.started",
                task_id=task_id,
                source_kind="deerflow_run",
                source_id="run-overflow",
                occurred_at=observed_at + timedelta(seconds=1),
                source_event_id="run:run-overflow:task:started",
                producer_seq=2,
            )
        )
        health = service.get_health()
    finally:
        await service.stop()

    assert accepted.accepted is True
    assert dropped.accepted is False
    assert dropped.reason == "queue_full"
    assert health.status == "degraded"
    assert health.queue_depth == 1
    assert health.dropped_count == 1
    assert health.lost_ranges[0].first_sequence == 2
    assert health.lost_ranges[0].last_sequence == 2
    assert health.lost_ranges[0].task_id == task_id


@pytest.mark.anyio
async def test_queue_drop_warning_is_structured_and_rate_bounded(caplog) -> None:
    service = AnsichService.in_memory(queue_capacity=1)
    await service.start()
    task_id = new_id()
    observed_at = datetime(2026, 8, 18, 10, tzinfo=UTC)

    try:
        service.record(
            ObservationEnvelope.task_lifecycle(
                kind="task.created",
                task_id=task_id,
                source_kind="deerflow_run",
                source_id="run-drop-warning",
                occurred_at=observed_at,
                source_event_id="run:drop-warning:task:created",
                producer_seq=1,
            )
        )
        with caplog.at_level(logging.WARNING, logger="ansich.service"):
            receipts = tuple(
                service.record(
                    ObservationEnvelope.task_lifecycle(
                        kind="task.started",
                        task_id=task_id,
                        source_kind="deerflow_run",
                        source_id="run-drop-warning",
                        occurred_at=observed_at,
                        source_event_id=f"run:drop-warning:task:started:{producer_seq}",
                        producer_seq=producer_seq,
                    )
                )
                for producer_seq in range(2, 6)
            )
        health = service.get_health()
    finally:
        await service.stop()

    warning_records = [record for record in caplog.records if getattr(record, "event", None) == "ansich.collector.observations_dropped"]
    assert all(not receipt.accepted and receipt.reason == "queue_full" for receipt in receipts)
    assert health.dropped_count == 4
    assert len(warning_records) == 1
    warning = warning_records[0]
    assert warning.levelno == logging.WARNING
    assert warning.reason == "queue_full"
    assert datetime.fromisoformat(warning.detected_at).tzinfo is not None
    assert warning.dropped_observation_count == 1
    assert warning.lost_ranges == (
        {
            "first_sequence": 2,
            "last_sequence": 2,
            "task_id": task_id,
            "producer_name": "task-control-probe",
            "producer_instance_id": "local",
        },
    )
    assert warning.queue_depth == 1
    assert warning.queue_capacity == 1
    assert "queue_full" in warning.getMessage()
    assert task_id in warning.getMessage()


@pytest.mark.anyio
async def test_queue_byte_capacity_rejects_an_observation_before_count_capacity(caplog):
    task_id = new_id()
    observed_at = datetime(2026, 7, 17, 11, 15, tzinfo=UTC)
    first = ObservationEnvelope.task_lifecycle(
        kind="task.created",
        task_id=task_id,
        source_kind="deerflow_run",
        source_id="run-byte-overflow",
        occurred_at=observed_at,
        source_event_id="run:run-byte-overflow:task:created",
        producer_seq=1,
    )
    first_size = len(first.model_dump_json().encode("utf-8"))
    service = AnsichService.in_memory(
        queue_capacity=10,
        queue_byte_capacity=first_size,
    )
    await service.start()

    try:
        accepted = service.record(first)
        with caplog.at_level(logging.WARNING, logger="ansich.service"):
            dropped = service.record(
                ObservationEnvelope.task_lifecycle(
                    kind="task.started",
                    task_id=task_id,
                    source_kind="deerflow_run",
                    source_id="run-byte-overflow",
                    occurred_at=observed_at + timedelta(seconds=1),
                    source_event_id="run:run-byte-overflow:task:started",
                    producer_seq=2,
                )
            )
        health = service.get_health()
        await service.flush_task(task_id)
        health_after_flush = service.get_health()
    finally:
        await service.stop()

    assert accepted.accepted is True
    assert dropped.accepted is False
    assert dropped.reason == "queue_bytes_full"
    assert health.queue_depth == 1
    assert health.queue_bytes == first_size
    assert health.queue_byte_capacity == first_size
    assert health.queue_byte_high_watermark == first_size
    assert health.status == "degraded"
    assert health_after_flush.queue_depth == 0
    assert health_after_flush.queue_bytes == 0
    assert health_after_flush.queue_byte_high_watermark == first_size
    warning = next(record for record in caplog.records if getattr(record, "event", None) == "ansich.collector.observations_dropped")
    assert warning.reason == "queue_bytes_full"
    assert warning.lost_ranges[0]["task_id"] == task_id


@pytest.mark.anyio
async def test_queue_drop_warning_failure_remains_fail_open(monkeypatch) -> None:
    service = AnsichService.in_memory(queue_capacity=1)
    await service.start()
    task_id = new_id()
    observed_at = datetime(2026, 8, 18, 11, tzinfo=UTC)

    def fail_warning(*args, **kwargs):
        raise OSError("log sink unavailable")

    monkeypatch.setattr("ansich.service.logger.warning", fail_warning)
    try:
        accepted = service.record(
            ObservationEnvelope.task_lifecycle(
                kind="task.created",
                task_id=task_id,
                source_kind="deerflow_run",
                source_id="run-drop-log-failure",
                occurred_at=observed_at,
                source_event_id="run:drop-log-failure:task:created",
            )
        )
        dropped = service.record(
            ObservationEnvelope.task_lifecycle(
                kind="task.started",
                task_id=task_id,
                source_kind="deerflow_run",
                source_id="run-drop-log-failure",
                occurred_at=observed_at,
                source_event_id="run:drop-log-failure:task:started",
            )
        )
        health = service.get_health()
    finally:
        await service.stop()

    assert accepted.accepted is True
    assert dropped.accepted is False
    assert dropped.reason == "queue_full"
    assert health.dropped_count == 1


@pytest.mark.anyio
async def test_queue_byte_accounting_serialization_failure_remains_fail_open():
    task_id = new_id()
    observation = ObservationEnvelope.task_lifecycle(
        kind="task.created",
        task_id=task_id,
        source_kind="deerflow_run",
        source_id="run-byte-serialization-failure",
        occurred_at=datetime(2026, 7, 17, 11, 20, tzinfo=UTC),
        source_event_id="run:run-byte-serialization-failure:task:created",
    ).model_copy(update={"payload": {"invalid_utf8": b"\xff"}})
    service = AnsichService.in_memory()
    await service.start()

    try:
        receipt = service.record(observation)
        health = service.get_health()
    finally:
        await service.stop()

    assert receipt.accepted is False
    assert receipt.reason == "serialization_failed"
    assert health.status == "degraded"
    assert health.queue_depth == 0
    assert health.queue_bytes == 0


@pytest.mark.anyio
async def test_context_snapshot_batch_is_accepted_or_dropped_atomically():
    service = AnsichService.in_memory(queue_capacity=2)
    await service.start()
    task_id = new_id()
    observed_at = datetime(2026, 7, 17, 11, 30, tzinfo=UTC)
    observations = tuple(
        ObservationEnvelope.task_lifecycle(
            kind="task.started",
            task_id=task_id,
            source_kind="deerflow_run",
            source_id="run-atomic-snapshot",
            occurred_at=observed_at,
            source_event_id=f"run:run-atomic-snapshot:item:{index}",
            producer_seq=index,
        )
        for index in range(1, 4)
    )

    try:
        receipts = service.record_batch(observations, batch_kind="context_snapshot")
        health = service.get_health()
    finally:
        await service.stop()

    assert [receipt.accepted for receipt in receipts] == [False, False, False]
    assert {receipt.reason for receipt in receipts} == {"queue_full"}
    assert health.queue_depth == 0
    assert health.snapshot_request_count == 1
    assert health.snapshot_observations_accepted == 0
    assert health.snapshot_observations_dropped == 3
    assert health.queue_high_watermark == 0


@pytest.mark.anyio
async def test_storage_failure_during_flush_is_fail_open_and_marks_task_degraded():
    service = AnsichService(UnavailableBackend())
    await service.start()
    task_id = new_id()
    observation = ObservationEnvelope.task_lifecycle(
        kind="task.completed",
        task_id=task_id,
        source_kind="deerflow_run",
        source_id="run-store-down",
        occurred_at=datetime(2026, 7, 17, 12, 0, tzinfo=UTC),
        source_event_id="run:run-store-down:task:completed",
    )

    try:
        service.record(observation)
        flush = await service.flush_task(task_id)
        health = service.get_health()
    finally:
        await service.stop()

    assert flush.persisted is False
    assert flush.processed_count == 0
    assert flush.reason == "storage_failure"
    assert health.status == "degraded"
    assert health.dropped_count == 1
    assert len(health.lost_ranges) == 1
    assert health.lost_ranges[0].first_sequence == 1
    assert health.lost_ranges[0].last_sequence == 1
    assert health.lost_ranges[0].task_id == task_id


@pytest.mark.anyio
async def test_background_writer_makes_running_task_queryable_without_explicit_flush():
    service = AnsichService.in_memory(flush_interval_ms=5)
    await service.start()
    task_id = new_id()
    observed_at = datetime(2026, 7, 17, 16, 0, tzinfo=UTC)

    try:
        for kind in ("task.created", "task.started"):
            service.record(
                ObservationEnvelope.task_lifecycle(
                    kind=kind,
                    task_id=task_id,
                    source_kind="deerflow_run",
                    source_id="run-background-writer",
                    occurred_at=observed_at,
                    source_event_id=f"run:run-background-writer:{kind}",
                )
            )

        with anyio.fail_after(0.5):
            while await service.get_task(task_id) is None:
                await anyio.sleep(0.01)
        task = await service.get_task(task_id)
    finally:
        await service.stop()

    assert task is not None
    assert task.control.value == "running"


@pytest.mark.anyio
async def test_invalid_record_input_is_rejected_without_raising_into_agent_code():
    service = AnsichService.in_memory()
    await service.start()

    try:
        receipt = service.record(object())  # type: ignore[arg-type]
    finally:
        await service.stop()

    assert receipt.accepted is False
    assert receipt.reason == "validation_failed"
    assert service.get_health().dropped_count == 1


@pytest.mark.anyio
async def test_terminal_flush_timeout_is_fail_open_and_reports_loss():
    service = AnsichService(
        BlockingBackend(),
        flush_interval_ms=60_000,
        terminal_flush_timeout_ms=10,
    )
    await service.start()
    task_id = new_id()
    service.record(
        ObservationEnvelope.task_lifecycle(
            kind="task.completed",
            task_id=task_id,
            source_kind="deerflow_run",
            source_id="run-timeout",
            occurred_at=datetime(2026, 7, 17, 17, 0, tzinfo=UTC),
            source_event_id="run:run-timeout:task:terminal:completed",
        )
    )

    try:
        result = await service.flush_task(task_id)
        health = service.get_health()
    finally:
        await service.stop()

    assert result.persisted is False
    assert result.reason == "terminal_flush_timeout"
    assert health.status == "degraded"


@pytest.mark.anyio
async def test_projection_settle_timeout_after_successful_persist_is_not_reported_as_loss():
    backend = SlowProjectionBackend()
    service = AnsichService(
        backend,
        flush_interval_ms=60_000,
        terminal_flush_timeout_ms=20,
    )
    await service.start()
    task_id = new_id()
    service.record(
        ObservationEnvelope.task_lifecycle(
            kind="task.completed",
            task_id=task_id,
            source_kind="deerflow_run",
            source_id="run-slow-projection",
            occurred_at=datetime(2026, 7, 17, 17, 30, tzinfo=UTC),
            source_event_id="run:run-slow-projection:task:terminal:completed",
        )
    )

    try:
        result = await service.flush_task(task_id)
        health = service.get_health()
        observations = await service.list_observations(task_id)
    finally:
        await service.stop()

    assert result.persisted is True
    assert result.reason == "projection_settle_timeout"
    assert [observation.kind for observation in observations] == ["task.completed"]
    assert health.dropped_count == 0
    assert health.lost_ranges == ()


@pytest.mark.anyio
async def test_storage_recovery_persists_observability_degraded_for_known_loss():
    backend = RecoveringBackend()
    service = AnsichService(backend, flush_interval_ms=60_000)
    await service.start()
    task_id = new_id()
    observed_at = datetime(2026, 7, 17, 18, 0, tzinfo=UTC)

    try:
        service.record(
            ObservationEnvelope.task_lifecycle(
                kind="task.created",
                task_id=task_id,
                source_kind="deerflow_run",
                source_id="run-recovered",
                occurred_at=observed_at,
                source_event_id="run:run-recovered:task:created",
            )
        )
        first_flush = await service.flush_task(task_id)
        service.record(
            ObservationEnvelope.task_lifecycle(
                kind="task.started",
                task_id=task_id,
                source_kind="deerflow_run",
                source_id="run-recovered",
                occurred_at=observed_at + timedelta(seconds=1),
                source_event_id="run:run-recovered:task:started",
                producer_seq=2,
            )
        )
        second_flush = await service.flush_task(task_id)
        observations = await service.list_observations(task_id)
    finally:
        await service.stop()

    assert first_flush.persisted is False
    assert second_flush.persisted is True
    assert [observation.kind for observation in observations] == [
        "task.started",
        "observability.degraded",
    ]


class RebuildProbeBackend:
    """Records whether background projection runs while a rebuild is in flight."""

    def __init__(self) -> None:
        self.rebuild_started = anyio.Event()
        self.release_rebuild = anyio.Event()
        self.in_rebuild = False
        self.project_pending_during_rebuild = 0

    async def persist_and_project(self, observations: list[ObservationEnvelope]) -> int:
        return len(observations)

    async def project_pending(self, *, limit: int = 200) -> int:
        if self.in_rebuild:
            self.project_pending_during_rebuild += 1
        return 0

    async def rebuild_projections(self) -> int:
        self.in_rebuild = True
        self.rebuild_started.set()
        await self.release_rebuild.wait()
        self.in_rebuild = False
        return 3

    async def get_task(self, task_id: str) -> TaskView | None:
        return None

    async def get_task_by_source(self, source_kind: str, source_id: str) -> TaskView | None:
        return None

    async def list_tasks(self, **kwargs) -> list[TaskView]:
        return []

    async def list_observations(self, task_id: str) -> list[ObservationEnvelope]:
        return []


@pytest.mark.anyio
async def test_rebuild_is_mutually_exclusive_with_background_projection():
    backend = RebuildProbeBackend()
    service = AnsichService(backend, projector_poll_interval_ms=1)
    await service.start()

    try:
        async with anyio.create_task_group() as task_group:

            async def run_rebuild() -> None:
                assert await service.rebuild_projections() == 3

            task_group.start_soon(run_rebuild)
            await backend.rebuild_started.wait()
            # Give the 1ms projector poll loop ample opportunity to claim
            # jobs while the rebuild is deliberately held open.
            await anyio.sleep(0.05)
            backend.release_rebuild.set()
    finally:
        await service.stop()

    assert backend.project_pending_during_rebuild == 0


@pytest.mark.anyio
async def test_record_is_safe_from_multiple_producer_threads():
    service = AnsichService.in_memory(queue_capacity=64, flush_interval_ms=60_000)
    await service.start()
    task_id = new_id()
    observed_at = datetime(2026, 7, 17, 19, 0, tzinfo=UTC)

    def record_one(index: int):
        return service.record(
            ObservationEnvelope.task_lifecycle(
                kind="task.created",
                task_id=task_id,
                source_kind="deerflow_run",
                source_id="run-threaded",
                occurred_at=observed_at,
                source_event_id=f"run:run-threaded:signal:{index}",
                producer_seq=index + 1,
            )
        )

    try:
        with ThreadPoolExecutor(max_workers=8) as executor:
            receipts = list(executor.map(record_one, range(32)))
        await service.flush_task(task_id)
        observations = await service.list_observations(task_id)
    finally:
        await service.stop()

    assert all(receipt.accepted for receipt in receipts)
    assert len(observations) == 32
