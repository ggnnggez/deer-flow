"""Lifecycle status derivation, its legal-transition clamp, and the health wiring.

``ansich.lifecycle`` is the single place that answers "what state is this
collector in". The derivation is pure so the state machine can be driven from
representative input sequences here instead of only through a live service.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from ansich import AnsichService, ObservationEnvelope, new_id
from ansich.contracts import AnsichHealth
from ansich.lifecycle import LEGAL_TRANSITIONS, LifecycleInputs, derive_status
from ansich.memory import InMemoryAnsichBackend
from pydantic import ValidationError

# Spec 11 §2, enumerated edge for edge:
#
#   starting -> healthy -> degraded -> recovering -> healthy
#                            \-> failed
#   healthy/degraded -> shutting_down -> stopped
SPEC_SECTION_2_EDGES = frozenset(
    {
        ("starting", "healthy"),
        ("healthy", "degraded"),
        ("degraded", "recovering"),
        ("recovering", "healthy"),
        ("degraded", "failed"),
        ("healthy", "shutting_down"),
        ("degraded", "shutting_down"),
        ("shutting_down", "stopped"),
    }
)


def _inputs(**overrides: object) -> LifecycleInputs:
    """A quiet, running collector; each test states only what it changes."""

    base: dict[str, object] = {
        "started": True,
        "stopping": False,
        "stopped": False,
        "unavailable_reason": None,
        "consecutive_write_failures": 0,
        "dropped_count": 0,
        "failed_jobs": 0,
        "queue_depth": 0,
        "batch_size": 100,
        "unreported_loss_pending": False,
    }
    base.update(overrides)
    return LifecycleInputs(**base)  # type: ignore[arg-type]


def _observation(source_id: str) -> ObservationEnvelope:
    return ObservationEnvelope.task_lifecycle(
        kind="task.created",
        task_id=new_id(),
        source_kind="deerflow_run",
        source_id=source_id,
        occurred_at=datetime(2026, 8, 19, 12, 0, tzinfo=UTC),
        source_event_id=f"run:{source_id}:task:created",
    )


class _GatedBackend(InMemoryAnsichBackend):
    """Holds the writer inside one flush so shutdown/backlog states are observable."""

    def __init__(self) -> None:
        super().__init__()
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def persist_and_project(self, observations: list[ObservationEnvelope]) -> int:
        self.entered.set()
        await self.release.wait()
        return await super().persist_and_project(observations)


def test_stopped_wins_over_every_other_signal() -> None:
    assert derive_status(_inputs(started=False, stopped=True)) == "stopped"
    assert (
        derive_status(
            _inputs(
                stopped=True,
                stopping=True,
                unavailable_reason="storage_unavailable",
                dropped_count=9,
                failed_jobs=3,
            )
        )
        == "stopped"
    )


def test_shutting_down_wins_over_start_and_failure_signals() -> None:
    assert derive_status(_inputs(stopping=True)) == "shutting_down"
    assert (
        derive_status(
            _inputs(
                started=False,
                stopping=True,
                unavailable_reason="storage_unavailable",
                dropped_count=4,
            )
        )
        == "shutting_down"
    )


def test_starting_covers_everything_before_start() -> None:
    assert derive_status(_inputs(started=False)) == "starting"
    # A collector that has not started yet is not failed, degraded or backlogged:
    # nothing has had a chance to run.
    assert derive_status(_inputs(started=False, unavailable_reason="storage_unavailable")) == "starting"
    assert derive_status(_inputs(started=False, dropped_count=7, failed_jobs=2, queue_depth=500)) == "starting"


def test_failed_reports_an_unavailable_backend() -> None:
    assert derive_status(_inputs(unavailable_reason="storage_unavailable")) == "failed"
    # Unavailable storage outranks the ordinary degradation signals.
    assert derive_status(_inputs(unavailable_reason="memory_backend", dropped_count=3, failed_jobs=1)) == "failed"


def test_degraded_reports_each_active_failure_signal() -> None:
    assert derive_status(_inputs(consecutive_write_failures=1)) == "degraded"
    assert derive_status(_inputs(dropped_count=1)) == "degraded"
    assert derive_status(_inputs(failed_jobs=1)) == "degraded"


def test_loss_stays_degraded_and_never_reads_as_recovering() -> None:
    # Dropping an Observation is a fact, not a transient: a backlog draining
    # behind a lost range does not make the loss go away.
    assert derive_status(_inputs(dropped_count=2, queue_depth=500, batch_size=100)) == "degraded"
    assert derive_status(_inputs(dropped_count=2, unreported_loss_pending=True)) == "degraded"


def test_recovering_reports_a_backlog_with_no_active_failure() -> None:
    assert derive_status(_inputs(queue_depth=101, batch_size=100)) == "recovering"
    assert derive_status(_inputs(unreported_loss_pending=True)) == "recovering"


def test_healthy_is_the_quiet_answer_and_one_batch_is_not_a_backlog() -> None:
    assert derive_status(_inputs()) == "healthy"
    # A queue the next flush empties in one batch is not a backlog.
    assert derive_status(_inputs(queue_depth=100, batch_size=100)) == "healthy"


def test_inputs_are_frozen_and_require_every_signal() -> None:
    inputs = _inputs()

    with pytest.raises(ValidationError):
        inputs.started = False  # type: ignore[misc]

    # No field defaults: a caller that forgot to wire a signal must fail loudly
    # rather than report an unmeasured collector as a quiet one.
    with pytest.raises(ValidationError):
        LifecycleInputs()  # type: ignore[call-arg]


def test_legal_transitions_match_the_spec_graph_edge_for_edge() -> None:
    assert LEGAL_TRANSITIONS == SPEC_SECTION_2_EDGES


def test_representative_sequences_only_take_legal_transitions() -> None:
    """Drive the state machine from inputs and clamp what it may do next."""

    write_failure_recovery = (
        _inputs(started=False),
        _inputs(),
        _inputs(consecutive_write_failures=1),
        _inputs(consecutive_write_failures=3, queue_depth=250),
        _inputs(queue_depth=250),
        _inputs(queue_depth=100),
        _inputs(stopping=True),
        _inputs(stopped=True),
    )
    unreported_loss_recovery = (
        _inputs(started=False),
        _inputs(),
        _inputs(consecutive_write_failures=2),
        _inputs(unreported_loss_pending=True),
        _inputs(),
        _inputs(stopping=True),
        _inputs(stopped=True),
    )
    storage_outage = (
        _inputs(started=False),
        _inputs(),
        _inputs(dropped_count=5),
        _inputs(dropped_count=5, unavailable_reason="storage_unavailable"),
    )
    shutdown_while_degraded = (
        _inputs(started=False),
        _inputs(),
        _inputs(failed_jobs=1),
        _inputs(failed_jobs=1, stopping=True),
        _inputs(failed_jobs=1, stopped=True),
    )

    observed: set[tuple[str, str]] = set()
    for sequence in (write_failure_recovery, unreported_loss_recovery, storage_outage, shutdown_while_degraded):
        statuses = [derive_status(inputs) for inputs in sequence]
        for previous, current in zip(statuses, statuses[1:], strict=False):
            if previous == current:
                continue
            assert (previous, current) in LEGAL_TRANSITIONS, f"{previous} -> {current} is not a legal transition"
            observed.add((previous, current))

    assert observed == LEGAL_TRANSITIONS


def test_every_derived_status_is_a_contract_lifecycle_state() -> None:
    derived = {
        derive_status(_inputs(started=False)),
        derive_status(_inputs()),
        derive_status(_inputs(dropped_count=1)),
        derive_status(_inputs(queue_depth=101)),
        derive_status(_inputs(unavailable_reason="storage_unavailable")),
        derive_status(_inputs(stopping=True)),
        derive_status(_inputs(stopped=True)),
    }

    assert len(derived) == 7
    for status in derived:
        assert (
            AnsichHealth(
                status=status,  # type: ignore[arg-type]
                queue_depth=0,
                queue_capacity=8,
                accepted_count=0,
                dropped_count=0,
                lost_ranges=(),
            ).status
            == status
        )


@pytest.mark.anyio
async def test_health_reports_starting_before_the_service_starts() -> None:
    service = AnsichService.in_memory()

    assert service.get_health().status == "starting"


@pytest.mark.anyio
async def test_health_reports_healthy_then_stopped_across_the_normal_lifecycle() -> None:
    service = AnsichService.in_memory()
    await service.start()
    try:
        assert service.get_health().status == "healthy"
    finally:
        await service.stop()

    assert service.get_health().status == "stopped"


@pytest.mark.anyio
async def test_health_reports_failed_while_storage_is_unavailable() -> None:
    service = AnsichService(InMemoryAnsichBackend(), unavailable_reason="storage_unavailable")
    await service.start()
    try:
        assert service.get_health().status == "failed"
    finally:
        await service.stop()


@pytest.mark.anyio
async def test_health_reports_degraded_after_a_dropped_batch() -> None:
    service = AnsichService.in_memory(queue_capacity=1)
    await service.start()
    try:
        receipts = service.record_batch([_observation("run-drop-1"), _observation("run-drop-2")])
        assert [receipt.accepted for receipt in receipts] == [False, False]

        assert service.get_health().status == "degraded"
    finally:
        await service.stop()


@pytest.mark.anyio
async def test_health_reports_recovering_while_a_backlog_waits_behind_the_writer() -> None:
    backend = _GatedBackend()
    service = AnsichService(backend, batch_size=1, flush_interval_ms=1)
    await service.start()
    try:
        service.record(_observation("run-backlog-0"))
        await asyncio.wait_for(backend.entered.wait(), timeout=5)
        for index in range(1, 4):
            service.record(_observation(f"run-backlog-{index}"))

        health = service.get_health()
        assert health.queue_depth == 3
        assert health.status == "recovering"
    finally:
        backend.release.set()
        await service.stop()


@pytest.mark.anyio
async def test_health_reports_shutting_down_while_the_writer_drains() -> None:
    backend = _GatedBackend()
    service = AnsichService(backend, batch_size=1, flush_interval_ms=1)
    await service.start()
    service.record(_observation("run-shutdown-0"))
    await asyncio.wait_for(backend.entered.wait(), timeout=5)

    stopping = asyncio.create_task(service.stop())
    try:
        await asyncio.sleep(0)
        assert service.get_health().status == "shutting_down"
    finally:
        backend.release.set()
        await asyncio.wait_for(stopping, timeout=5)

    assert service.get_health().status == "stopped"
