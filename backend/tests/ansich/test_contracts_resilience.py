from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from ansich.contracts import ANSICH_BOOTSTRAP_TASK_ID, AnsichHealth, FlushResult, LostRange, ObservationEnvelope, Producer, ProducerHealth, WriterHealth
from ansich.ids import new_id
from ansich.safety import host_scope_id
from pydantic import ValidationError

_LOST_AT = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)


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


def test_producer_health_has_no_defaults_so_a_producer_must_be_fully_accounted() -> None:
    # Unlike ``WriterHealth``, every ``ProducerHealth`` field is a fact about one
    # producer instance; defaulting any of them would report a producer that was
    # never measured as a quiet one. Asserted field by field, so adding a
    # defaulted field later fails here rather than passing on the first missing
    # required one.
    assert all(field.is_required() for field in ProducerHealth.model_fields.values())
    with pytest.raises(ValidationError):
        ProducerHealth()  # type: ignore[call-arg]


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


def _lost(**overrides: object) -> ObservationEnvelope:
    """One ``observability.lost`` envelope, built the way the collector builds it."""

    base: dict[str, object] = {
        "host_scope_id": host_scope_id("ansich-test-host"),
        "occurred_at": _LOST_AT,
        "first_sequence": 7,
        "last_sequence": 9,
        "lost_producer_name": "deerflow-task-control",
        "lost_producer_instance_id": "worker-a",
        "source_event_id": "loss:global:7:9",
    }
    base.update(overrides)
    return ObservationEnvelope.observability_lost(**base)  # type: ignore[arg-type]


def test_bootstrap_task_sentinel_is_a_canonical_uuid4_the_envelope_accepts() -> None:
    """RB1②. The sentinel has to survive the envelope's own identity validator.

    ``task_id`` is UUID4-validated, so a readable-but-invalid sentinel (all
    zeros, a word) would be rejected at construction and the whole bootstrap
    path would be unreachable. It is also pinned by value: it is a *stable*
    statement about which rows are bootstrap records, so changing it would
    silently orphan every row already written under the old one.
    """

    assert ANSICH_BOOTSTRAP_TASK_ID == "00000000-0000-4000-8000-000000000001"
    parsed = UUID(ANSICH_BOOTSTRAP_TASK_ID)
    assert parsed.version == 4
    assert str(parsed) == ANSICH_BOOTSTRAP_TASK_ID


def test_observability_lost_subjects_the_host_scope_under_the_bootstrap_sentinel() -> None:
    """RB2②. Subject is the host Scope; the Task field carries the sentinel."""

    observation = _lost()

    assert observation.kind == "observability.lost"
    assert observation.subject_type == "scope"
    assert observation.subject_id == host_scope_id("ansich-test-host")
    assert observation.task_id == ANSICH_BOOTSTRAP_TASK_ID
    # Same payload shape as `observability.degraded`: the range, and the
    # identity of the producer whose rows were charged.
    assert observation.payload == {
        "first_sequence": 7,
        "last_sequence": 9,
        "producer_name": "deerflow-task-control",
        "producer_instance_id": "worker-a",
    }
    # The reporting producer is the collector, not the producer that lost rows;
    # that one is named in the payload above and nowhere else.
    assert observation.producer.name == "ansich-collector"
    assert observation.correlation_id == host_scope_id("ansich-test-host")


def test_observability_lost_requires_a_scope_subject_and_the_sentinel_task() -> None:
    """A dangling or Task-shaped subject is refused at the contract, not later."""

    with pytest.raises(ValidationError):
        ObservationEnvelope(
            kind="observability.lost",
            occurred_at=_LOST_AT,
            task_id=ANSICH_BOOTSTRAP_TASK_ID,
            subject_type="task",
            subject_id=ANSICH_BOOTSTRAP_TASK_ID,
            producer=Producer(name="ansich-collector", version="1", instance_id="local"),
            source_event_id="loss:global:7:9",
            correlation_id="c",
            payload={
                "first_sequence": 7,
                "last_sequence": 9,
                "producer_name": "p",
                "producer_instance_id": "i",
            },
        )

    # A real Task id is refused too: this kind exists precisely because the loss
    # it reports has no Task, and `observability.degraded` is the kind for loss
    # that has one. The constructor cannot produce this shape — it pins the
    # sentinel — so the envelope is built by hand, which is also what a stored
    # row reads back as.
    with pytest.raises(ValidationError):
        ObservationEnvelope(
            kind="observability.lost",
            occurred_at=_LOST_AT,
            task_id=new_id(),
            subject_type="scope",
            subject_id=host_scope_id("ansich-test-host"),
            producer=Producer(name="ansich-collector", version="1", instance_id="local"),
            source_event_id="loss:global:7:9",
            correlation_id="c",
            payload={
                "first_sequence": 7,
                "last_sequence": 9,
                "producer_name": "p",
                "producer_instance_id": "i",
            },
        )


def test_observability_lost_validates_its_payload_only_when_it_has_one() -> None:
    """F10-29's lesson, applied at birth rather than discovered later.

    An externalized payload reads back as ``payload_json IS NULL`` plus a
    ``payload_ref_id``; ``_observation_from_row`` hands that straight to this
    model. A branch that validated unconditionally — as ``environment.sampled``
    still does — would make its own rows unreadable. So the payload rules are
    real, and every one of them is skipped when there is no payload to check.
    """

    for broken in (
        {"first_sequence": 0, "last_sequence": 9, "producer_name": "p", "producer_instance_id": "i"},
        {"first_sequence": 9, "last_sequence": 7, "producer_name": "p", "producer_instance_id": "i"},
        {"first_sequence": True, "last_sequence": 9, "producer_name": "p", "producer_instance_id": "i"},
        {"first_sequence": 7, "last_sequence": 9, "producer_name": "", "producer_instance_id": "i"},
        {"first_sequence": 7, "last_sequence": 9, "producer_name": "p"},
    ):
        with pytest.raises(ValidationError):
            ObservationEnvelope(
                kind="observability.lost",
                occurred_at=_LOST_AT,
                task_id=ANSICH_BOOTSTRAP_TASK_ID,
                subject_type="scope",
                subject_id=host_scope_id("ansich-test-host"),
                producer=Producer(name="ansich-collector", version="1", instance_id="local"),
                source_event_id="loss:global:7:9",
                correlation_id="c",
                payload=broken,
            )

    externalized = ObservationEnvelope(
        kind="observability.lost",
        occurred_at=_LOST_AT,
        task_id=ANSICH_BOOTSTRAP_TASK_ID,
        subject_type="scope",
        subject_id=host_scope_id("ansich-test-host"),
        producer=Producer(name="ansich-collector", version="1", instance_id="local"),
        source_event_id="loss:global:7:9",
        correlation_id="c",
        payload=None,
        payload_ref_id=new_id(),
    )
    assert externalized.payload is None


def test_observability_degraded_contract_is_untouched_by_the_new_kind() -> None:
    """RB2①. The Task-subjected kind keeps its exact rules, sentinel included."""

    task_id = new_id()
    degraded = ObservationEnvelope(
        kind="observability.degraded",
        occurred_at=_LOST_AT,
        task_id=task_id,
        subject_id=task_id,
        producer=Producer(name="ansich-collector", version="1", instance_id="local"),
        source_event_id=f"loss:{task_id}:7:9",
        correlation_id=task_id,
        payload={
            "first_sequence": 7,
            "last_sequence": 9,
            "producer_name": "p",
            "producer_instance_id": "i",
        },
    )
    assert degraded.subject_type == "task"

    # Still Task-subjected: a scope subject is refused, and so is the sentinel
    # standing in for a Task.
    with pytest.raises(ValidationError):
        ObservationEnvelope(
            kind="observability.degraded",
            occurred_at=_LOST_AT,
            task_id=task_id,
            subject_type="scope",
            subject_id=host_scope_id("ansich-test-host"),
            producer=Producer(name="ansich-collector", version="1", instance_id="local"),
            source_event_id=f"loss:{task_id}:7:9",
            correlation_id=task_id,
            payload={
                "first_sequence": 7,
                "last_sequence": 9,
                "producer_name": "p",
                "producer_instance_id": "i",
            },
        )
