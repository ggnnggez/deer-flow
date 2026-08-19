"""Per-producer accounting: whose work was accepted, dropped, or reached storage.

``AnsichHealth.accepted_count`` / ``dropped_count`` are process totals — they
say *that* something was lost, never *whose*. These tests pin the per-producer
ledger that answers "whose", and the bound that keeps a pathological
``instance_id`` from growing that ledger without limit (RA3).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from ansich import AnsichService, ObservationEnvelope, new_id
from ansich.contracts import AnsichHealth, ProducerHealth
from ansich.memory import InMemoryAnsichBackend

# RA3's bound, written here as a literal on purpose: it is the contract, not
# whatever the implementation currently happens to hold.
PRODUCER_LIMIT = 256


def _observation(
    source_id: str,
    *,
    producer_name: str = "task-control-probe",
    producer_instance_id: str = "local",
    task_id: str | None = None,
    attributes: dict[str, object] | None = None,
) -> ObservationEnvelope:
    return ObservationEnvelope.task_lifecycle(
        kind="task.created",
        task_id=task_id or new_id(),
        source_kind="deerflow_run",
        source_id=source_id,
        occurred_at=datetime(2026, 8, 19, 12, 0, tzinfo=UTC),
        source_event_id=f"run:{source_id}:task:created",
        producer_name=producer_name,
        producer_instance_id=producer_instance_id,
        attributes=attributes,
    )


def _unserializable_observation(source_id: str, *, producer_name: str, producer_instance_id: str) -> ObservationEnvelope:
    """A valid envelope whose payload cannot be rendered as JSON.

    This is the real production signal — ``_serialized_observation_size``
    returns ``-1`` for exactly this — rather than a patched-in sentinel.
    """

    return _observation(
        source_id,
        producer_name=producer_name,
        producer_instance_id=producer_instance_id,
        attributes={"unserializable": object()},
    )


def _producer(health: AnsichHealth, producer_name: str, producer_instance_id: str) -> ProducerHealth:
    matches = [entry for entry in health.producers if (entry.producer_name, entry.producer_instance_id) == (producer_name, producer_instance_id)]
    assert len(matches) == 1, f"expected exactly one {producer_name}/{producer_instance_id} entry, got {health.producers}"
    return matches[0]


def _identities(health: AnsichHealth) -> list[tuple[str, str]]:
    return [(entry.producer_name, entry.producer_instance_id) for entry in health.producers]


class _GatedBackend(InMemoryAnsichBackend):
    """Holds the writer inside one flush so queued-but-unflushed state is observable."""

    def __init__(self) -> None:
        super().__init__()
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def persist_and_project(self, observations: list[ObservationEnvelope]) -> int:
        self.entered.set()
        await self.release.wait()
        return await super().persist_and_project(observations)


async def _wait_until(predicate: Callable[[], bool], *, timeout: float = 5.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        assert loop.time() < deadline, "condition was not reached in time"
        await asyncio.sleep(0.01)


@pytest.mark.anyio
async def test_accepted_observations_are_counted_against_their_own_producer() -> None:
    service = AnsichService.in_memory()
    await service.start()
    try:
        service.record_batch(
            [
                _observation("run-a-1", producer_name="run-worker", producer_instance_id="worker-1"),
                _observation("run-a-2", producer_name="run-worker", producer_instance_id="worker-1"),
                _observation("run-b-1", producer_name="tool-probe", producer_instance_id="worker-2"),
            ]
        )

        health = service.get_health()
        worker = _producer(health, "run-worker", "worker-1")
        probe = _producer(health, "tool-probe", "worker-2")

        assert (worker.accepted_count, worker.dropped_count) == (2, 0)
        # Collector sequences, not the producers' own `producer_seq`: this is
        # the collector's ledger of what it took from whom.
        assert worker.last_accepted_sequence == 2
        assert worker.serialization_failures == 0
        assert (probe.accepted_count, probe.dropped_count) == (1, 0)
        assert probe.last_accepted_sequence == 3

        # Audit: the per-producer ledger must add up to the process total.
        assert sum(entry.accepted_count for entry in health.producers) == health.accepted_count == 3
    finally:
        await service.stop()


@pytest.mark.anyio
async def test_a_rejected_batch_is_counted_against_the_producers_that_sent_it() -> None:
    # Capacity 4 with a 5-item batch rejects regardless of how far the writer
    # has drained, so the drop is a property of the test, not of its timing.
    service = AnsichService.in_memory(queue_capacity=4)
    await service.start()
    try:
        service.record(_observation("run-kept", producer_name="run-worker", producer_instance_id="worker-1"))
        receipts = service.record_batch([_observation(f"run-dropped-{index}", producer_name="noisy-probe", producer_instance_id="worker-9") for index in range(5)])
        assert [receipt.reason for receipt in receipts] == ["queue_full"] * 5

        health = service.get_health()
        worker = _producer(health, "run-worker", "worker-1")
        noisy = _producer(health, "noisy-probe", "worker-9")

        assert (worker.accepted_count, worker.dropped_count) == (1, 0)
        assert (noisy.accepted_count, noisy.dropped_count) == (0, 5)
        # Nothing of this producer's was ever taken, so there is no sequence to
        # report — `0` would read as "sequence zero was accepted".
        assert noisy.last_accepted_sequence is None

        assert sum(entry.dropped_count for entry in health.producers) == health.dropped_count == 5
    finally:
        await service.stop()


@pytest.mark.anyio
async def test_a_serialization_failure_is_counted_against_the_producer_that_sent_it() -> None:
    service = AnsichService.in_memory()
    await service.start()
    try:
        receipts = service.record_batch(
            [
                _observation("run-good", producer_name="run-worker", producer_instance_id="worker-1"),
                _unserializable_observation("run-bad", producer_name="broken-probe", producer_instance_id="worker-7"),
            ]
        )
        assert [receipt.reason for receipt in receipts] == ["serialization_failed"] * 2

        health = service.get_health()
        worker = _producer(health, "run-worker", "worker-1")
        broken = _producer(health, "broken-probe", "worker-7")

        # The failure is charged before the batch-wide reject decision, so it
        # names the one producer that actually could not be serialized.
        assert broken.serialization_failures == 1
        assert worker.serialization_failures == 0
        # Rejection is all-or-nothing, so the innocent producer still lost this
        # observation and its ledger has to say so.
        assert (worker.accepted_count, worker.dropped_count) == (0, 1)
        assert (broken.accepted_count, broken.dropped_count) == (0, 1)
    finally:
        await service.stop()


@pytest.mark.anyio
async def test_a_successful_flush_stamps_every_producer_in_that_batch() -> None:
    backend = _GatedBackend()
    service = AnsichService(backend, batch_size=1, flush_interval_ms=1)
    await service.start()
    try:
        # Park the writer inside a flush of somebody else's observation, so the
        # two producers below are queued but provably not yet persisted.
        service.record(_observation("run-gate", producer_name="gate-holder", producer_instance_id="worker-0"))
        await asyncio.wait_for(backend.entered.wait(), timeout=5)

        service.record_batch(
            [
                _observation("run-c-1", producer_name="run-worker", producer_instance_id="worker-1"),
                _observation("run-c-2", producer_name="tool-probe", producer_instance_id="worker-2"),
            ]
        )
        queued = service.get_health()
        assert _producer(queued, "run-worker", "worker-1").last_successful_flush_at is None
        assert _producer(queued, "tool-probe", "worker-2").last_successful_flush_at is None

        before_flush = datetime.now(UTC)
        backend.release.set()
        await _wait_until(lambda: all(entry.last_successful_flush_at is not None for entry in service.get_health().producers))
        after_flush = datetime.now(UTC)

        flushed = service.get_health()
        for producer_name, producer_instance_id in (("run-worker", "worker-1"), ("tool-probe", "worker-2")):
            stamp = _producer(flushed, producer_name, producer_instance_id).last_successful_flush_at
            assert stamp is not None
            assert before_flush <= stamp <= after_flush
    finally:
        backend.release.set()
        await service.stop()


@pytest.mark.anyio
async def test_the_producer_map_is_bounded_and_counts_every_eviction() -> None:
    backend = _GatedBackend()
    service = AnsichService(backend)
    await service.start()
    try:
        for index in range(PRODUCER_LIMIT):
            service.record(_observation(f"run-{index:03d}", producer_name="probe", producer_instance_id=f"worker-{index:03d}"))

        filled = service.get_health()
        assert len(filled.producers) == PRODUCER_LIMIT
        assert filled.evicted_producer_count == 0

        # An observation from a producer already in the map is not an arrival:
        # it must not evict anybody.
        service.record(_observation("run-again", producer_name="probe", producer_instance_id="worker-000"))
        unchanged = service.get_health()
        assert len(unchanged.producers) == PRODUCER_LIMIT
        assert unchanged.evicted_producer_count == 0

        service.record(_observation("run-new", producer_name="probe", producer_instance_id="worker-999"))
        evicted = service.get_health()

        assert len(evicted.producers) == PRODUCER_LIMIT
        # Eviction is bounded loss of *detail*, never silent: the counter is the
        # only thing that keeps a shrinking list honest.
        assert evicted.evicted_producer_count == 1
        identities = _identities(evicted)
        assert ("probe", "worker-999") in identities
        # `worker-000` was touched again above, so the least recently used entry
        # is `worker-001` — the eviction order is LRU, not insertion order.
        assert ("probe", "worker-000") in identities
        assert ("probe", "worker-001") not in identities
    finally:
        backend.release.set()
        await service.stop()


@pytest.mark.anyio
async def test_health_lists_producers_in_a_stable_order() -> None:
    service = AnsichService.in_memory()
    await service.start()
    try:
        scrambled = (
            ("beta", "worker-2"),
            ("alpha", "worker-9"),
            ("beta", "worker-1"),
            ("alpha", "worker-1"),
        )
        for index, (producer_name, producer_instance_id) in enumerate(scrambled):
            service.record(_observation(f"run-{index}", producer_name=producer_name, producer_instance_id=producer_instance_id))

        expected = [
            ("alpha", "worker-1"),
            ("alpha", "worker-9"),
            ("beta", "worker-1"),
            ("beta", "worker-2"),
        ]
        # Sorted by (name, instance) rather than by arrival or by LRU position,
        # so two health reads are diffable even while the map churns.
        assert _identities(service.get_health()) == expected

        service.record(_observation("run-touch", producer_name="beta", producer_instance_id="worker-2"))
        assert _identities(service.get_health()) == expected
    finally:
        await service.stop()


def test_a_batch_rolled_back_by_a_closed_loop_is_un_accepted_for_its_producer() -> None:
    async def _start() -> AnsichService:
        service = AnsichService.in_memory()
        await service.start()
        return service

    # `asyncio.run` closes the loop under a still-running service, which is the
    # production shape of the `event_loop_closed` path: a probe thread records
    # after the loop that owned the writer is gone.
    service = asyncio.run(_start())

    receipts = service.record_batch([_observation("run-orphan", producer_name="run-worker", producer_instance_id="worker-1")])
    assert [receipt.reason for receipt in receipts] == ["event_loop_closed"]

    health = service.get_health()
    worker = _producer(health, "run-worker", "worker-1")

    # The append was undone process-wide, so it has to be undone per producer
    # too: counting the same observation as both accepted and dropped would
    # report one observation twice.
    assert (worker.accepted_count, worker.dropped_count) == (0, 1)
    assert health.accepted_count == 0
    assert health.dropped_count == 1
