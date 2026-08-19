"""Lifecycle status derivation, its legal-transition clamp, and the health wiring.

``ansich.lifecycle`` is the single place that answers "what state is this
collector in". The derivation is pure, so the clamp here does not have to trust
hand-picked sequences: it enumerates the whole input space the service can
actually walk and checks what the derivation does with it.
"""

from __future__ import annotations

import asyncio
import itertools
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
#
# This is the *nominal arc*, not the whole truth: real operation also takes
# operator-recovery shortcuts, boundary failures, and restart. Those live in
# ``LEGAL_TRANSITIONS``, which must contain this arc.
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

# `unavailable_reason` is fixed at construction, so a running service cannot
# become unavailable yet and this nominal edge has no reachable input pair. It
# stays legal because spec §2 draws it and runtime-detected unavailability is
# coming with the writer's own failure accounting.
NOMINAL_ONLY_EDGES = frozenset({("degraded", "failed")})

# The four flag combinations ``AnsichService`` can be observed in.
LIFECYCLE_PHASES: dict[str, dict[str, bool]] = {
    "pre_start": {"started": False, "stopping": False, "stopped": False},
    "running": {"started": True, "stopping": False, "stopped": False},
    "stopping": {"started": True, "stopping": True, "stopped": False},
    "stopped": {"started": True, "stopping": False, "stopped": True},
}

# Every phase step the service can take, given how ``start()`` and ``stop()``
# order their flag writes: ``stop()`` marks stopping before it clears running
# and writes stopped before it clears stopping, and ``start()`` re-arms
# ``started`` first, so neither leaves a gap phase a reader could observe.
PHASE_STEPS: tuple[tuple[str, str], ...] = (
    ("pre_start", "pre_start"),  # not started yet
    ("pre_start", "running"),  # start() finished
    ("pre_start", "stopped"),  # start() raised
    ("running", "running"),  # steady state
    ("running", "stopping"),  # stop() began
    ("stopping", "stopping"),  # draining
    ("stopping", "stopped"),  # stop() finished
    ("stopped", "stopped"),  # stopped
    ("stopped", "pre_start"),  # restart re-armed the flags
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
        "writer_retry_backlog": False,
    }
    base.update(overrides)
    return LifecycleInputs(**base)  # type: ignore[arg-type]


def _reachable_status_pairs() -> dict[tuple[str, str], str]:
    """Every adjacent status change the service dynamics can actually produce.

    Enumerates each phase step against the signal space, and returns the derived
    pairs mapped to the input evidence that first produced them. Two modelling
    rules keep the space honest rather than merely large:

    * ``dropped_count`` only ever grows — the service never forgets a drop.
    * A recovery residue cannot precede its cause: ``unreported_loss_pending``
      and ``writer_retry_backlog`` are what a failure *leaves behind*, so
      either may only be set in a step whose predecessor already showed an
      active write failure or a residue itself. That is not a modelling
      convenience: both signals are raised by the service inside the same
      locked section that raises ``consecutive_write_failures``, so no reader
      can see the residue without having seen its cause.

    ``queue_depth`` is held below ``batch_size`` on purpose: PA6 removed the
    bare backlog clause from the derivation, so a deep queue is evidence the
    derivation deliberately does not key on. ``test_a_deep_queue_alone_...``
    pins that directly.
    """

    signal_space = tuple(itertools.product((0, 1), (0, 1), (0, 1), (False, True), (False, True)))
    found: dict[tuple[str, str], str] = {}
    for before_phase, after_phase in PHASE_STEPS:
        for unavailable in (None, "storage_unavailable"):  # fixed at construction
            for drops_a, jobs_a, failures_a, residue_a, backlog_a in signal_space:
                for drops_b, jobs_b, failures_b, residue_b, backlog_b in signal_space:
                    if drops_b < drops_a:
                        continue
                    if (residue_b or backlog_b) and not (failures_a or residue_a or backlog_a):
                        continue
                    before = derive_status(
                        _inputs(
                            **LIFECYCLE_PHASES[before_phase],
                            unavailable_reason=unavailable,
                            dropped_count=drops_a,
                            failed_jobs=jobs_a,
                            consecutive_write_failures=failures_a,
                            unreported_loss_pending=residue_a,
                            writer_retry_backlog=backlog_a,
                        )
                    )
                    after = derive_status(
                        _inputs(
                            **LIFECYCLE_PHASES[after_phase],
                            unavailable_reason=unavailable,
                            dropped_count=drops_b,
                            failed_jobs=jobs_b,
                            consecutive_write_failures=failures_b,
                            unreported_loss_pending=residue_b,
                            writer_retry_backlog=backlog_b,
                        )
                    )
                    if before == after:
                        continue
                    found.setdefault(
                        (before, after),
                        f"{before_phase}->{after_phase}, unavailable={unavailable}, (drops,jobs,failures,residue,backlog) {(drops_a, jobs_a, failures_a, residue_a, backlog_a)} -> {(drops_b, jobs_b, failures_b, residue_b, backlog_b)}",
                    )
    return found


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


class _RetryBacklogBackend(InMemoryAnsichBackend):
    """Refuses one write, then holds the next so the catch-up stays observable.

    The refusal is what raises the writer's retry backlog; holding the write
    that follows freezes the service in the state between "the outage ended"
    and "the queue it caused is drained".
    """

    def __init__(self) -> None:
        super().__init__()
        self.refused = False
        self.landed = asyncio.Event()
        self.holding = asyncio.Event()
        self.release = asyncio.Event()
        self._held = False

    async def persist_and_project(self, observations: list[ObservationEnvelope]) -> int:
        if not self.refused:
            self.refused = True
            raise OSError("storage refused the batch")
        if self.landed.is_set() and not self._held:
            self._held = True
            self.holding.set()
            await self.release.wait()
        count = await super().persist_and_project(observations)
        self.landed.set()
        return count


class _GatedInitBackend(InMemoryAnsichBackend):
    """Holds ``start()`` inside metric initialization so the phase is observable."""

    def __init__(self) -> None:
        super().__init__()
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()

    async def initialize_metrics(self) -> None:
        self.entered.set()
        await self.release.wait()


class _FailingInitBackend(InMemoryAnsichBackend):
    """A backend whose metric initialization never succeeds."""

    async def initialize_metrics(self) -> None:
        raise RuntimeError("metrics store unavailable")


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


def test_an_active_failure_outranks_the_recovery_residue() -> None:
    # Dropping an Observation is a fact, not a transient: a backlog draining
    # behind a lost range does not make the loss go away.
    assert derive_status(_inputs(dropped_count=2, queue_depth=500, batch_size=100)) == "degraded"
    assert derive_status(_inputs(dropped_count=2, unreported_loss_pending=True)) == "degraded"
    # Precedence, not merely presence: while the writer is still failing, the
    # residue it has already left behind must not read as recovery. `degraded`
    # and `recovering` are mutually legal transitions, so no pair-level clamp
    # can catch this ordering — only asserting the state itself does.
    assert derive_status(_inputs(consecutive_write_failures=1, unreported_loss_pending=True)) == "degraded"
    assert derive_status(_inputs(consecutive_write_failures=1, writer_retry_backlog=True)) == "degraded"
    assert derive_status(_inputs(failed_jobs=1, unreported_loss_pending=True)) == "degraded"


def test_recovering_reports_incident_residue_with_no_active_failure() -> None:
    # PA6: `recovering` needs incident evidence. Both signals are residue a
    # write failure left behind — one on the reporting side, one on the
    # writer's own retry path.
    assert derive_status(_inputs(unreported_loss_pending=True)) == "recovering"
    assert derive_status(_inputs(writer_retry_backlog=True)) == "recovering"


def test_a_deep_queue_alone_is_not_recovery_evidence() -> None:
    # PA6 removed the bare `queue_depth > batch_size` clause. A load burst is
    # not an incident: reporting it as `recovering` would both mislabel a
    # healthy collector and manufacture a `healthy -> recovering` edge that is
    # nowhere in the spec's graph. `queue_depth` stays an *input* so this
    # negative can be stated at all.
    assert derive_status(_inputs(queue_depth=10_000, batch_size=100)) == "healthy"
    assert derive_status(_inputs(queue_depth=101, batch_size=100)) == "healthy"


def test_healthy_is_the_quiet_answer() -> None:
    assert derive_status(_inputs()) == "healthy"
    assert derive_status(_inputs(queue_depth=100, batch_size=100)) == "healthy"


def test_inputs_are_frozen_and_require_every_signal() -> None:
    inputs = _inputs()

    with pytest.raises(ValidationError):
        inputs.started = False  # type: ignore[misc]

    # No field defaults: a caller that forgot to wire a signal must fail loudly
    # rather than report an unmeasured collector as a quiet one.
    assert all(field.is_required() for field in LifecycleInputs.model_fields.values())
    with pytest.raises(ValidationError):
        LifecycleInputs()  # type: ignore[call-arg]

    # An unknown signal is a mis-wire, not something to ignore quietly.
    with pytest.raises(ValidationError):
        _inputs(consecutive_write_failure=1)  # type: ignore[call-arg]


def test_legal_transitions_contain_the_spec_nominal_arc() -> None:
    assert SPEC_SECTION_2_EDGES <= LEGAL_TRANSITIONS


def test_nominal_sequences_walk_exactly_the_spec_arc() -> None:
    """Drive the state machine from inputs and clamp what it may do next."""

    write_failure_recovery = (
        _inputs(started=False),
        _inputs(),
        _inputs(consecutive_write_failures=1),
        _inputs(consecutive_write_failures=3, queue_depth=250, writer_retry_backlog=True),
        # The write landed: failures are cleared, but the writer is still
        # working through the backlog the outage left behind.
        _inputs(queue_depth=250, writer_retry_backlog=True),
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

    assert observed == SPEC_SECTION_2_EDGES


def test_legal_transitions_are_the_reachable_closure_plus_the_nominal_arc() -> None:
    """The clamp is the derivation's real reachable set, not a hand-picked walk."""

    reachable = _reachable_status_pairs()

    illegal = {pair: evidence for pair, evidence in reachable.items() if pair not in LEGAL_TRANSITIONS}
    assert not illegal, f"reachable but not legal: {illegal}"
    # And no dead edges: everything legal is either reachable today or one of
    # the nominal-only spec edges named above.
    assert LEGAL_TRANSITIONS - set(reachable) == NOMINAL_ONLY_EDGES


def test_the_illegal_complement_stays_unreachable_from_every_input_pair() -> None:
    """What the closure must NOT contain — this is what gives the clamp teeth."""

    reachable = _reachable_status_pairs()

    # A recovery residue cannot appear out of nowhere (post-PA6 semantics).
    assert ("healthy", "recovering") not in reachable
    # Shutdown is one-way: it ends in `stopped`, never back in service.
    assert ("shutting_down", "healthy") not in reachable
    assert ("shutting_down", "degraded") not in reachable
    # Unavailable storage is fixed for the life of an instance, so a running
    # service cannot recover from `failed`, and `failed` cannot skip the drain.
    assert ("failed", "healthy") not in reachable
    assert ("failed", "degraded") not in reachable
    assert ("failed", "stopped") not in reachable
    # Stopping always passes through the drain.
    assert ("healthy", "stopped") not in reachable
    assert ("degraded", "stopped") not in reachable
    # A stopped service can only come back by starting again.
    for other in ("healthy", "degraded", "recovering", "failed", "shutting_down"):
        assert ("stopped", other) not in reachable
    assert ("stopped", "starting") in reachable


def test_every_derived_status_is_a_contract_lifecycle_state() -> None:
    derived = {
        derive_status(_inputs(started=False)),
        derive_status(_inputs()),
        derive_status(_inputs(dropped_count=1)),
        derive_status(_inputs(writer_retry_backlog=True)),
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
    # PA6 moved what this pin drives, not what it pins: it used to reach
    # `recovering` through the bare `queue_depth > batch_size` clause, which is
    # gone because an ordinary load burst is not an incident. The residue it
    # drives instead is the writer's retry backlog — the only production path
    # that can put `recovering` on `AnsichHealth.status`, which is why this test
    # is kept rather than deleted.
    backend = _RetryBacklogBackend()
    service = AnsichService(backend, batch_size=1, flush_interval_ms=1, writer_backoff_initial_ms=1)
    await service.start()
    try:
        for index in range(4):
            service.record(_observation(f"run-backlog-{index}"))
        await asyncio.wait_for(backend.holding.wait(), timeout=5)

        health = service.get_health()
        # One batch already recovered, one held in the writer's hands, and the
        # rest still queued behind it.
        assert health.writer.consecutive_failures == 0
        assert health.writer.in_flight_count == 1
        assert health.queue_depth == 2
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


@pytest.mark.anyio
async def test_health_reports_stopped_when_start_never_finished() -> None:
    service = AnsichService(_FailingInitBackend())

    with pytest.raises(RuntimeError):
        await service.start()

    # A start that raised leaves the service exactly as stopped as it was
    # before the attempt; reporting `starting` forever would claim a collector
    # is on its way up when nothing is coming.
    assert service.get_health().status == "stopped"


@pytest.mark.anyio
async def test_a_restart_is_observed_as_starting_rather_than_a_jump_back() -> None:
    backend = _GatedInitBackend()
    service = AnsichService(backend)
    await service.start()
    await service.stop()
    assert service.get_health().status == "stopped"

    backend.entered.clear()
    backend.release.clear()
    restarting = asyncio.create_task(service.start())
    try:
        await asyncio.wait_for(backend.entered.wait(), timeout=5)
        # `start()` re-arms the flags before its first await, so the only way
        # out of `stopped` is `starting` — never straight back into service.
        assert service.get_health().status == "starting"
    finally:
        backend.release.set()
        await asyncio.wait_for(restarting, timeout=5)

    try:
        assert service.get_health().status == "healthy"
    finally:
        await service.stop()
