from __future__ import annotations

from datetime import UTC, datetime

import pytest
from ansich.contracts import AnsichHealth, FlushResult, LostRange, ProducerHealth, WriterHealth
from pydantic import ValidationError


def _health(**overrides: object) -> AnsichHealth:
    base: dict[str, object] = {
        "status": "healthy",
        "queue_depth": 0,
        "queue_capacity": 128,
        "accepted_count": 0,
        "dropped_count": 0,
        "lost_ranges": (),
    }
    base.update(overrides)
    return AnsichHealth(**base)  # type: ignore[arg-type]


def _producer_health(**overrides: object) -> ProducerHealth:
    base: dict[str, object] = {
        "producer_name": "run-worker",
        "producer_instance_id": "worker-1",
        "accepted_count": 12,
        "dropped_count": 0,
        "last_accepted_sequence": 12,
        "serialization_failures": 0,
        "last_successful_flush_at": datetime(2026, 8, 19, 12, 0, 0, tzinfo=UTC),
    }
    base.update(overrides)
    return ProducerHealth(**base)  # type: ignore[arg-type]


def test_lifecycle_status_accepts_extended_states_without_regressing_existing_ones() -> None:
    for status in ("healthy", "degraded", "failed", "stopped"):
        assert _health(status=status).status == status

    for status in ("starting", "recovering", "shutting_down"):
        assert _health(status=status).status == status

    with pytest.raises(ValidationError):
        _health(status="not_a_lifecycle_state")


def test_producer_health_carries_per_producer_accounting_and_is_frozen() -> None:
    producer = _producer_health()

    assert producer.producer_name == "run-worker"
    assert producer.producer_instance_id == "worker-1"
    assert producer.accepted_count == 12
    assert producer.dropped_count == 0
    assert producer.last_accepted_sequence == 12
    assert producer.serialization_failures == 0
    assert producer.last_successful_flush_at == datetime(2026, 8, 19, 12, 0, 0, tzinfo=UTC)

    unflushed = _producer_health(last_accepted_sequence=None, last_successful_flush_at=None)
    assert unflushed.last_accepted_sequence is None
    assert unflushed.last_successful_flush_at is None

    with pytest.raises(ValidationError):
        producer.accepted_count = 13  # type: ignore[misc]


def test_writer_health_defaults_to_a_quiet_writer_and_is_frozen() -> None:
    writer = WriterHealth()

    assert writer.consecutive_failures == 0
    assert writer.backoff_until is None
    assert writer.in_flight_count == 0
    assert writer.poison_observation_count == 0

    backing_off = WriterHealth(
        consecutive_failures=3,
        backoff_until=datetime(2026, 8, 19, 12, 0, 5, tzinfo=UTC),
        in_flight_count=2,
        poison_observation_count=1,
    )
    assert backing_off.consecutive_failures == 3
    assert backing_off.backoff_until == datetime(2026, 8, 19, 12, 0, 5, tzinfo=UTC)
    assert backing_off.in_flight_count == 2
    assert backing_off.poison_observation_count == 1

    with pytest.raises(ValidationError):
        writer.in_flight_count = 1  # type: ignore[misc]


def test_flush_result_legacy_construction_still_compiles_with_barrier_defaults() -> None:
    result = FlushResult(persisted=True, processed_count=3)

    assert result.persisted is True
    assert result.processed_count == 3
    assert result.reason is None
    assert result.persisted_through is None
    assert result.lost_ranges == ()
    assert result.timed_out is False


def test_flush_result_accepts_barrier_evidence() -> None:
    lost = LostRange(first_sequence=7, last_sequence=9, task_id="task-1")
    result = FlushResult(
        persisted=False,
        processed_count=2,
        reason="terminal_flush_timeout",
        persisted_through=6,
        lost_ranges=(lost,),
        timed_out=True,
    )

    assert result.persisted_through == 6
    assert result.lost_ranges == (lost,)
    assert result.timed_out is True


def test_ansich_health_legacy_construction_still_compiles_with_resilience_defaults() -> None:
    health = _health()

    assert health.producers == ()
    assert health.writer == WriterHealth()
    assert health.evicted_producer_count == 0
    assert health.unreported_global_lost_range_count == 0


def test_ansich_health_carries_producer_and_writer_health() -> None:
    producer = _producer_health()
    writer = WriterHealth(consecutive_failures=2, in_flight_count=1)
    health = _health(
        status="recovering",
        producers=(producer,),
        writer=writer,
        evicted_producer_count=4,
        unreported_global_lost_range_count=2,
    )

    assert health.producers == (producer,)
    assert health.writer == writer
    assert health.evicted_producer_count == 4
    assert health.unreported_global_lost_range_count == 2
