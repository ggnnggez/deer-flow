"""Lifecycle status derivation, its legal-transition clamp, and the health wiring.

``ansich.lifecycle`` is the single place that answers "what state is this
collector in". The derivation is pure, so the clamp here does not have to trust
hand-picked sequences: it enumerates the whole input space the service can
actually walk and checks what the derivation does with it.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import logging
from datetime import UTC, datetime

import pytest
from ansich import AnsichService, LeaseSweepReport, ObservationEnvelope, new_id
from ansich.contracts import ActiveVersionMismatch, AnsichHealth
from ansich.lifecycle import LEGAL_TRANSITIONS, LifecycleInputs, derive_status
from ansich.memory import InMemoryAnsichBackend
from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from support.ansich_settle import only_test_driven_assessments

from deerflow.ansich.persistence.models import AnsichBeliefAssertionRow, AnsichProjectionJobRow
from deerflow.ansich.persistence.sql import SqlAnsichBackend
from deerflow.persistence.base import Base

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
#
# The table's precondition is that the two calls never overlap, and that is
# enforced rather than assumed: ``start()`` raises while ``_stopping`` is up and
# ``stop()`` raises while ``_starting`` is (the re-entrancy guard, pinned by
# ``test_bounded_stop.py``'s two refusal tests). Without it a start landing
# inside a drain would re-arm the flags mid-``stopping``, producing the
# ``stopping -> running`` step that is missing here on purpose — and with it the
# ``shutting_down -> healthy`` transition the clamp below calls illegal.
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
      active write failure or a residue itself. This is a modelling rule about
      the caller rather than a property of the derivation, and what justifies
      it is that the service raises both signals inside the same locked section
      that raises ``consecutive_write_failures`` — so no reader can see the
      residue without having seen its cause.

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


# ---------------------------------------------------------------------------
# Startup recovery (spec §8's second half): what `start()` repairs, what it
# reports, and — RC13 — what it deliberately refuses to reconstruct.
# ---------------------------------------------------------------------------

# Past-dated under any clock (the suite-wide fixture-clock rule): a lease
# expiry decision must never be settled between a fixture and the real clock.
_EXPIRED_AT = datetime(2026, 1, 1, tzinfo=UTC)
_LIVE_UNTIL = datetime(2099, 1, 1, tzinfo=UTC)


class _ActiveVersionBackend(InMemoryAnsichBackend):
    """A backend that answers active-version validation however a test needs.

    The three answers are not two: ``None`` is "the rows could not be read",
    ``()`` is "read and clean", and a tuple is "read, and these cannot be
    executed". Collapsing the first into the second is the mistake this fixture
    exists to make expressible.
    """

    def __init__(self, answer: tuple[ActiveVersionMismatch, ...] | None, *, raises: bool = False) -> None:
        super().__init__()
        self._answer = answer
        self._raises = raises
        self.calls = 0

    async def validate_active_versions(self) -> tuple[ActiveVersionMismatch, ...] | None:
        self.calls += 1
        if self._raises:
            raise RuntimeError("active-version table unreadable")
        return self._answer


@pytest.mark.anyio
async def test_an_unhonourable_active_version_degrades_health_and_never_crashes(caplog: pytest.LogCaptureFixture) -> None:
    """Constraint 1, at the one place a rollback is discovered.

    A row naming a version this build was rolled back past is a deployment
    fact, not a corrupt store: every reader it affects already falls back to
    its code default. So it costs a typed WARNING and a health field, and the
    lifecycle status is untouched — routing it into ``derive_status`` would
    mean a new legal edge in a clamp whose illegal complement is a merge gate.
    """

    mismatch = ActiveVersionMismatch(
        component_kind="resolver",
        component_name="ansich-default",
        active_version="9.9.9",
        reason="unknown_version",
    )
    service = AnsichService(_ActiveVersionBackend((mismatch,)), flush_interval_ms=60_000)

    with caplog.at_level(logging.WARNING, logger="ansich.service"):
        await service.start()
    try:
        health = service.get_health()
    finally:
        await service.stop()

    assert health.status == "healthy"
    assert health.active_version_mismatches == (mismatch,)
    (warning,) = [record for record in caplog.records if getattr(record, "event", None) == "ansich.startup.active_version_mismatch"]
    assert warning.mismatch_count == 1
    assert warning.mismatches == [
        {
            "component_kind": "resolver",
            "component_name": "ansich-default",
            "active_version": "9.9.9",
            "reason": "unknown_version",
        }
    ]


@pytest.mark.anyio
async def test_an_unreadable_active_version_table_is_not_reported_as_a_clean_one() -> None:
    """``None`` and ``()`` are different answers and health keeps them apart.

    A store that could not answer must not render as a deployment somebody
    verified. Both directions are asserted here because the tempting bug is one
    line — ``or ()`` — and it is invisible from the clean side.
    """

    unreadable = AnsichService(_ActiveVersionBackend(None, raises=True), flush_interval_ms=60_000)
    await unreadable.start()
    try:
        assert unreadable.get_health().active_version_mismatches is None
    finally:
        await unreadable.stop()

    clean = AnsichService(_ActiveVersionBackend(()), flush_interval_ms=60_000)
    await clean.start()
    try:
        assert clean.get_health().active_version_mismatches == ()
    finally:
        await clean.stop()

    # A backend that does not implement the read at all is also "not read",
    # never "clean": the in-memory backend has no active versions to have.
    silent = AnsichService(InMemoryAnsichBackend(), flush_interval_ms=60_000)
    await silent.start()
    try:
        assert silent.get_health().active_version_mismatches is None
    finally:
        await silent.stop()


@pytest.mark.anyio
async def test_start_after_a_crash_fabricates_no_lost_range() -> None:
    """RC13/D8-4. Producer health has no durable source, so nothing is restored.

    The previous process's queue died with it. This start has no evidence about
    what was in it — that is the no-spool limitation (D8-7), stated rather than
    papered over — so it writes **no** loss range and reports none. A
    plausible-looking reconstruction here would be exactly the fabricated
    `observability.*` row spec:7 forbids readers to misread.
    """

    backend = _RecordingLossBackend()
    first = AnsichService(backend, flush_interval_ms=60_000)
    await first.start()
    # A crash: rows accepted, never flushed, and no `stop()` ever runs.
    assert all(receipt.accepted for receipt in first.record_batch([_observation(f"run-crash-{index}") for index in range(3)]))
    assert first.get_health().queue_depth == 3

    second = AnsichService(backend, flush_interval_ms=60_000)
    await second.start()
    try:
        health = second.get_health()
    finally:
        await second.stop()

    assert health.dropped_count == 0
    assert health.lost_ranges == ()
    assert health.unreported_global_lost_range_count == 0
    assert backend.loss_rows() == []


class _RecordingLossBackend(InMemoryAnsichBackend):
    """Keeps every write so a test can assert that *no* loss row was invented."""

    def __init__(self) -> None:
        super().__init__()
        self.written: list[ObservationEnvelope] = []

    async def persist_and_project(self, observations: list[ObservationEnvelope]) -> int:
        self.written.extend(observations)
        return await super().persist_and_project(observations)

    def loss_rows(self) -> list[ObservationEnvelope]:
        return [observation for observation in self.written if observation.kind in {"observability.degraded", "observability.lost"}]


class _SweepRecordingBackend(InMemoryAnsichBackend):
    """A backend that answers the startup sweep, so `start()`'s call is observable."""

    def __init__(self, report: LeaseSweepReport) -> None:
        super().__init__()
        self._report = report
        self.calls = 0

    async def sweep_expired_leases(self) -> LeaseSweepReport:
        self.calls += 1
        return self._report


class _FailingSweepBackend(InMemoryAnsichBackend):
    """A backend whose sweep raises: recovery is fail-open or it is not recovery."""

    async def sweep_expired_leases(self) -> LeaseSweepReport:
        raise RuntimeError("job table unreadable")


@contextlib.asynccontextmanager
async def _sql_backend(tmp_path, name: str):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / name}.db")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield SqlAnsichBackend(sessions), sessions
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_the_lease_sweep_buckets_expired_leases_by_attempts(tmp_path) -> None:
    """RC12, on real rows. The bucket is the row's honest one, and nothing else moves.

    ``attempts > 0`` means the row was attempted, so it re-arms to ``retry``;
    ``attempts == 0`` means nothing tried it, so it goes back to ``pending``.
    That is Global Constraint 7 (``pending ⟺ attempts == 0``) held rather than
    restated. ``attempts`` and ``lease_generation`` are untouched by design: the
    sweep is neither an attempt nor a claim, and resetting the generation would
    recreate the ABA the CAS exists to prevent.

    A lease that has **not** expired belongs to a live worker and is left
    alone — the sweep is about the dead process, not about taking work away
    from a peer.
    """

    async with _sql_backend(tmp_path, "sweep") as (backend, sessions):
        await backend.persist_and_project([_observation("run-sweep-a"), _observation("run-sweep-b")])
        async with sessions() as session:
            jobs = list(await session.scalars(select(AnsichProjectionJobRow).order_by(AnsichProjectionJobRow.job_id)))
        assert len(jobs) >= 3, "two Observations should mint at least three projection jobs"
        attempted, untried, live = jobs[0].job_id, jobs[1].job_id, jobs[2].job_id
        async with sessions() as session, session.begin():
            await session.execute(update(AnsichProjectionJobRow).where(AnsichProjectionJobRow.job_id == attempted).values(status="processing", attempts=3, lease_owner="dead-worker", lease_expires_at=_EXPIRED_AT, lease_generation=7))
            await session.execute(update(AnsichProjectionJobRow).where(AnsichProjectionJobRow.job_id == untried).values(status="processing", attempts=0, lease_owner="dead-worker", lease_expires_at=_EXPIRED_AT, lease_generation=2))
            await session.execute(update(AnsichProjectionJobRow).where(AnsichProjectionJobRow.job_id == live).values(status="processing", attempts=1, lease_owner="live-peer", lease_expires_at=_LIVE_UNTIL, lease_generation=4))

        report = await backend.sweep_expired_leases()

        assert report == LeaseSweepReport(to_retry=1, to_pending=1, truncated=False)
        async with sessions() as session:
            swept = {job.job_id: job for job in await session.scalars(select(AnsichProjectionJobRow))}
        assert swept[attempted].status == "retry"
        assert swept[attempted].attempts == 3
        assert swept[attempted].lease_generation == 7
        assert swept[untried].status == "pending"
        assert swept[untried].attempts == 0
        assert swept[untried].lease_generation == 2
        # Untouched: somebody is still working on it.
        assert swept[live].status == "processing"
        assert swept[live].lease_owner == "live-peer"


@pytest.mark.anyio
async def test_start_runs_the_lease_sweep_and_survives_one_that_fails(caplog: pytest.LogCaptureFixture) -> None:
    """The sweep is a `start()` step, and a failing one costs legibility only.

    Separated from the row-level test above on purpose: with a live projector
    loop the swept rows are claimed and projected within milliseconds, so a
    test that asserted both at once would be asserting on a race. What matters
    here is that `start()` calls it, logs the counts, and comes up either way —
    the claim path re-arms an expired lease lazily, which is why a sweep that
    raised must never be a failed startup.
    """

    swept = _SweepRecordingBackend(LeaseSweepReport(to_retry=2, to_pending=1, truncated=True))
    service = AnsichService(swept, flush_interval_ms=60_000)
    with caplog.at_level(logging.INFO, logger="ansich.service"):
        await service.start()
    await service.stop()

    assert swept.calls == 1
    (line,) = [record for record in caplog.records if getattr(record, "event", None) == "ansich.startup.lease_sweep"]
    assert (line.swept_to_retry, line.swept_to_pending, line.swept_truncated) == (2, 1, True)

    failing = AnsichService(_FailingSweepBackend(), flush_interval_ms=60_000)
    with caplog.at_level(logging.WARNING, logger="ansich.service"):
        await failing.start()
    try:
        assert failing.get_health().status == "healthy"
    finally:
        await failing.stop()


@pytest.mark.anyio
async def test_orphan_correlation_writes_unknown_evidence_and_never_a_terminal(tmp_path) -> None:
    """D8-3/spec:127. The Run's reconciliation becomes evidence, not a verdict.

    The RunManager can say a Run never reached a durable final state. It cannot
    say what the Agent did, and Ansich's control Belief is hard-fidelity
    evidence about exactly that — so this writes a degradation row naming the
    reason and leaves the control Belief where the evidence left it. Asserted on
    the Belief assertion rows rather than on the view, because the failure mode
    worth catching is a *written* terminal, and a view can only show the one
    the resolver selected.
    """

    async with _sql_backend(tmp_path, "orphan") as (backend, _sessions):
        run_id = "run-orphaned-by-a-crash"
        task_id = new_id()
        service = AnsichService(backend, flush_interval_ms=20, operations_assessment_interval_ms=60_000)
        only_test_driven_assessments(service)
        await service.start()
        try:
            assert all(
                receipt.accepted
                for receipt in service.record_batch(
                    [
                        ObservationEnvelope.task_lifecycle(
                            kind=kind,
                            task_id=task_id,
                            source_kind="deerflow_run",
                            source_id=run_id,
                            occurred_at=datetime(2026, 8, 19, 12, index, tzinfo=UTC),
                            source_event_id=f"run:{run_id}:task:{kind}",
                            producer_seq=index + 1,
                        )
                        for index, kind in enumerate(("task.created", "task.started"))
                    ]
                )
            )
            settled = await service.rebuild_until_settled()
            assert settled.unsettled == 0
            task = await service.get_task_by_source("deerflow_run", run_id)
            assert task is not None and task.control.value == "running"

            assert await service.record_orphaned_run_evidence([run_id]) == 1
            # The return is **acceptances**, not rows filed, and the second
            # call is where those two numbers legitimately part: a
            # re-recovery of the same Run is accepted by the queue — nothing on
            # the accept path knows the store already holds it — and then
            # absorbed by the producer dedupe. So this is `1` and the row count
            # below is still `1`; reading this number as "a row was written"
            # is the mistake the name and the log line both refuse to make.
            assert await service.record_orphaned_run_evidence([run_id]) == 1
            assert await service.record_orphaned_run_evidence(["a-run-ansich-never-saw"]) == 0
            await service.flush_task(task_id)
            await service.rebuild_until_settled()

            observations = await service.list_observations(task_id)
            after = await service.get_task(task_id)
        finally:
            await service.stop()

        # The durable truth beside the acceptance count above: two accepted
        # recoveries, one row.
        degraded = [observation for observation in observations if observation.kind == "observability.degraded"]
        assert len(degraded) == 1
        assert degraded[0].payload == {"component": "run_lifecycle", "reason": "orphaned_run_reconciliation"}
        assert degraded[0].subject_id == task_id
        # The Task is exactly where its own evidence left it.
        assert after is not None and after.control.value == "running"

    async with _sql_backend(tmp_path, "orphan") as (_backend, sessions):
        async with sessions() as session:
            control_values = [
                row.value_json["value"]
                for row in await session.scalars(
                    select(AnsichBeliefAssertionRow).where(
                        AnsichBeliefAssertionRow.subject_id == task_id,
                        AnsichBeliefAssertionRow.field_name == "control",
                    )
                )
            ]
        assert control_values, "the control assertions should still be there"
        assert set(control_values) == {"created", "running"}
        assert "completed" not in control_values
