"""``stop()`` drains on a budget, and the budget bounds the attempt (RA7).

Shutdown used to be unbounded in the one way that matters: ``stop()`` awaits the
writer task, and the writer can be sitting inside ``persist_and_project``. A
backend that never answers therefore held shutdown open forever — not a
hypothetical, it hung a real run in this batch once RA5② started handing
timed-out rows back to the queue for the writer to pick up.

``stop_drain_timeout_ms`` is the whole of the writer's remaining work: place
what it can, and when the budget is gone, charge the rest and say so once.
Counting *attempts* would not have been enough, because the attempt itself is
what wedges — the budget has to be able to take the attempt away.

What is on trial here:

* the drain returns inside its budget against a write that never answers, and
  against a per-item phase that has no stop check left to reach (the legal
  ``writer_item_max_attempts=1`` removes every one of them);
* what the drain could not place is charged **exactly once** — never twice,
  never for a row that already landed — and the queue does not keep holding it;
* the budget is a ceiling, not a schedule: a drain that finishes early places
  everything and warns about nothing;
* the drain is the *writer* finishing its own work. Its rows are registered as
  outstanding with ``barrier=False``, so the caught-up latch still counts them.

``start()`` and ``stop()``'s mutual exclusion lives here too: it is the same
subject, since the only way to observe the missing guard is to reach for one
while the other is mid-flight.

No test here sits through a real backoff except where the wait *is* the
fixture: ``_ParkingService`` records the schedule the production code computed
and returns immediately, and ``park_from`` makes one chosen wait real so a test
can call ``stop()`` while the writer is held inside the per-item phase.

**P11-C extends this file to the whole of spec §8's sequence**, of which the
writer drain is now one step of seven. What the new tests are for:

* the seven steps and their order are a contract — the lifespan logs them and
  an operator reads them, so a rename or a reordering must go red;
* a step that freezes must **not** take the steps after it with it. That is not
  a nicety: the last step is the one that writes process-wide loss down, so
  "abort on first timeout" would lose exactly the evidence a bad shutdown
  produces;
* the post-loop projection drain is bounded now. It used to be
  ``while await self._project_pending() > 0: pass`` with nothing able to end
  it, so a store that always had claimable work held the process open forever;
* FC-5: the process-loss bucket is drained at stop, and a range that can still
  grow is left in it — the first real exercise of the drain's ``live`` guard,
  which existed for this caller and had never had one.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from ansich import AnsichService, ObservationEnvelope, new_id
from ansich.memory import InMemoryAnsichBackend

# Generous against a loaded machine and still an order of magnitude below "the
# drain waited for the wedged write": every budget configured here is <= 2s.
_STOP_CEILING_SECONDS = 10.0

# Spec §8's ordering, step for step (spec:122), as `stop()` reports it. The
# spec's seventh step is "close DB", which is deliberately **not** the
# collector's: the engine belongs to the Gateway and several components share
# it, so the lifespan closes it after this sequence. What takes its place here
# is the process-loss drain (FC-5), the one shutdown-time write nothing else
# performs.
_SHUTDOWN_STEP_ORDER = (
    "stop_new_records",
    "stop_assessor_cadence",
    "drain_terminal_barriers",
    "drain_writer",
    "stop_projection_claiming",
    "join_projector",
    "drain_unreported_loss",
)


def _observation(source_id: str, *, task_id: str | None = None) -> ObservationEnvelope:
    return ObservationEnvelope.task_lifecycle(
        kind="task.created",
        task_id=task_id or new_id(),
        source_kind="deerflow_run",
        source_id=source_id,
        occurred_at=datetime(2026, 8, 20, 12, 0, tzinfo=UTC),
        source_event_id=f"run:{source_id}:task:created",
    )


class _RecordingBackend(InMemoryAnsichBackend):
    """Keeps every write it accepted, for the tests to read."""

    def __init__(self) -> None:
        super().__init__()
        self.persisted: list[ObservationEnvelope] = []

    async def persist_and_project(self, observations: list[ObservationEnvelope]) -> int:
        count = await super().persist_and_project(observations)
        self.persisted.extend(observations)
        return count

    @property
    def landed(self) -> list[str]:
        """``source_event_id`` of the work, in write order.

        Filtered: a charged loss is reported back into the stream as
        ``observability.degraded`` and lands here too. That is the collector
        talking about the incident, not the work under test.
        """

        return [observation.source_event_id for observation in self.persisted if observation.kind == "task.created"]


class _WedgedBackend:
    """A backend whose write never answers. Every read is duck-typed and absent.

    The gate is for teardown only — no test releases it before ``stop()`` has
    already had to decide.
    """

    def __init__(self) -> None:
        self.released = asyncio.Event()
        self.attempts = 0

    async def persist_and_project(self, observations: list[ObservationEnvelope]) -> int:
        self.attempts += 1
        await self.released.wait()
        return len(observations)


class _WedgedItemBackend:
    """Refuses any multi-row write outright; a single-row write never answers.

    Exactly the shape that walks the writer into per-item isolation and then
    wedges it there, which is where ``writer_item_max_attempts=1`` leaves no
    stop check between one row and the next.
    """

    def __init__(self) -> None:
        self.released = asyncio.Event()
        self.batch_attempts = 0
        self.item_attempts = 0

    async def persist_and_project(self, observations: list[ObservationEnvelope]) -> int:
        if len(observations) > 1:
            self.batch_attempts += 1
            raise OSError("storage refused the batch")
        self.item_attempts += 1
        await self.released.wait()
        return len(observations)


class _PoisonRowBackend(_RecordingBackend):
    """Healthy storage that permanently refuses named rows."""

    def __init__(self, *poison_source_event_ids: str) -> None:
        super().__init__()
        self.poison = set(poison_source_event_ids)

    async def persist_and_project(self, observations: list[ObservationEnvelope]) -> int:
        if any(observation.source_event_id in self.poison for observation in observations):
            raise ValueError("constraint violation on this row")
        return await super().persist_and_project(observations)


class _SlowStartBackend(_RecordingBackend):
    """A backend whose metrics bootstrap holds ``start()`` open until released."""

    def __init__(self) -> None:
        super().__init__()
        self.initializing = asyncio.Event()
        self.release = asyncio.Event()

    async def initialize_metrics(self) -> None:
        self.initializing.set()
        await self.release.wait()


class _ParkingService(AnsichService):
    """An ``AnsichService`` whose backoff reports its schedule instead of sleeping.

    Overriding the single sleeping point — and nothing else — keeps the retry
    and isolation paths in production shape. ``park_from`` re-arms the real wait
    from the given wait onwards, so a test can hold the writer inside the
    per-item phase and call ``stop()`` while it is there.
    """

    def __init__(self, backend: object, *, park_from: int | None = None, **kwargs: object) -> None:
        super().__init__(backend, **kwargs)  # type: ignore[arg-type]
        self.backoff_delays: list[float] = []
        self.parked = asyncio.Event()
        self._park_from = park_from

    async def _sleep_before_retry(self, delay_seconds: float) -> None:
        self.backoff_delays.append(delay_seconds)
        if self._park_from is not None and len(self.backoff_delays) >= self._park_from:
            self.parked.set()
            await super()._sleep_before_retry(delay_seconds)
            return
        await asyncio.sleep(0)


async def _wait_until(predicate: Callable[[], bool], *, timeout: float = 10.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        assert loop.time() < deadline, "condition was not reached in time"
        await asyncio.sleep(0.01)


def _drop_warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [record for record in caplog.records if getattr(record, "event", None) == "ansich.collector.observations_dropped"]


@pytest.mark.anyio
async def test_a_wedged_write_cannot_hold_shutdown_open(caplog: pytest.LogCaptureFixture) -> None:
    """The budget bounds the attempt, not the attempt count.

    One row is inside a write that will never answer and two more are queued
    behind it. Every one of them is the drain's to resolve, and none of them can
    be resolved by waiting, so the budget expires, takes the attempt away, and
    the whole remainder is charged. A drain that only counted attempts would
    still be inside the first one.
    """

    backend = _WedgedBackend()
    service = AnsichService(backend, batch_size=1, flush_interval_ms=1, stop_drain_timeout_ms=100)
    await service.start()
    try:
        for index in range(3):
            assert service.record(_observation(f"run-wedged-{index}")).accepted
        await _wait_until(lambda: service.get_health().writer.in_flight_count == 1)
        draining = service.get_health()
        # The drain is the writer finishing its own work, so its outstanding
        # rows are the writer's: no barrier token, and the caught-up latch
        # counts them (a barrier's write is the one thing it must not count).
        with service._lock:
            assert service._barrier_in_flight_tokens == set()
            assert service._writer_holds_nothing() is False

        loop = asyncio.get_running_loop()
        started_at = loop.time()
        with caplog.at_level(logging.WARNING, logger="ansich.service"):
            await asyncio.wait_for(service.stop(), timeout=30)
        elapsed = loop.time() - started_at
        health = service.get_health()
    finally:
        backend.released.set()

    assert elapsed < _STOP_CEILING_SECONDS, f"stop() waited for the wedged write: {elapsed:.2f}s"
    assert draining.writer.in_flight_count == 1
    assert draining.queue_depth == 2
    assert health.status == "stopped"
    # Nothing is quietly held: the parked row and the queue behind it are both
    # charged, and the queue does not keep reporting rows it no longer owns.
    assert health.dropped_count == 3
    assert health.queue_depth == 0
    assert health.writer.in_flight_count == 0
    assert {(lost.first_sequence, lost.last_sequence) for lost in health.lost_ranges} == {(1, 1), (2, 2), (3, 3)}

    (warning,) = _drop_warnings(caplog)
    assert warning.levelno == logging.WARNING
    assert warning.reason == "stop_drain_timeout"
    assert warning.dropped_observation_count == 3
    assert len(warning.lost_ranges) == 3


@pytest.mark.anyio
async def test_a_wedged_per_item_phase_with_one_attempt_still_stops(caplog: pytest.LogCaptureFixture) -> None:
    """``writer_item_max_attempts=1`` leaves the budget as the only bound.

    It is a legal setting, and it removes every stop check the per-item phase
    has after its opening wait: a row that resolves in one attempt never reaches
    another wait, so nothing between two rows asks whether the service is still
    running. Here the row does not resolve at all — the write never answers —
    which is the same gap seen from inside a single attempt.
    """

    backend = _WedgedItemBackend()
    service = AnsichService(
        backend,
        batch_size=3,
        flush_interval_ms=1,
        # Straight into the per-item phase, with an opening wait short enough
        # that it is not what the elapsed time measures.
        writer_retry_max_attempts=1,
        writer_backoff_initial_ms=1,
        writer_backoff_max_ms=1,
        writer_item_max_attempts=1,
        stop_drain_timeout_ms=100,
    )
    await service.start()
    try:
        assert all(receipt.accepted for receipt in service.record_batch([_observation(f"run-item-{index}") for index in range(3)]))
        await _wait_until(lambda: backend.item_attempts >= 1)
        draining = service.get_health()

        loop = asyncio.get_running_loop()
        started_at = loop.time()
        with caplog.at_level(logging.WARNING, logger="ansich.service"):
            await asyncio.wait_for(service.stop(), timeout=30)
        elapsed = loop.time() - started_at
        health = service.get_health()
    finally:
        backend.released.set()

    assert elapsed < _STOP_CEILING_SECONDS, f"stop() waited for the wedged row: {elapsed:.2f}s"
    # One refusal is all it took to reach the per-item phase, and the row it
    # started on is the one the budget had to take away.
    assert backend.batch_attempts == 1
    assert backend.item_attempts == 1
    # The batch entered isolation whole and never got a row back out of it.
    assert draining.writer.in_flight_count == 3
    assert health.status == "stopped"
    assert health.dropped_count == 3
    assert health.writer.in_flight_count == 0
    assert health.queue_depth == 0

    (warning,) = _drop_warnings(caplog)
    assert warning.reason == "stop_drain_timeout"
    assert warning.dropped_observation_count == 3


@pytest.mark.anyio
async def test_stopping_mid_isolation_charges_the_remainder_exactly_once(caplog: pytest.LogCaptureFixture) -> None:
    """The per-item phase's own drain branch, asserted rather than merely executed.

    The writer is held between the poison row's two attempts with one row of the
    batch already durable. ``stop()`` cuts the wait short, and what is left —
    the row that refused and the row behind it that was never attempted — is
    charged once. The row that landed is not charged at all, and the buffer does
    not go on reporting rows it has accounted for.
    """

    observations = [_observation(f"run-isolating-{index}") for index in range(3)]
    poison = observations[1]
    backend = _PoisonRowBackend(poison.source_event_id)
    service = _ParkingService(
        backend,
        # Wait #6 is the poison row's own retry: four batch waits, the capped
        # wait that opens the per-item phase, and by then the first row is
        # already durable and this one has refused once on its own.
        park_from=6,
        batch_size=3,
        flush_interval_ms=1,
        writer_backoff_initial_ms=5_000,
    )
    await service.start()
    assert all(receipt.accepted for receipt in service.record_batch(observations))
    await asyncio.wait_for(service.parked.wait(), timeout=10)
    parked = service.get_health()

    loop = asyncio.get_running_loop()
    started_at = loop.time()
    with caplog.at_level(logging.WARNING, logger="ansich.service"):
        # No teardown guard: `stop()` is the subject here, and the backend needs
        # no release — the stop event is what ends the wait the writer is in.
        await asyncio.wait_for(service.stop(), timeout=30)
    elapsed = loop.time() - started_at
    health = service.get_health()

    assert elapsed < _STOP_CEILING_SECONDS, f"stop() sat through the backoff: {elapsed:.2f}s"
    assert backend.landed == [observations[0].source_event_id]
    assert parked.writer.in_flight_count == 2
    # Sequences 2 and 3, once each. Sequence 1 is durable and must not appear,
    # and neither may a second charge for the two that did not land.
    assert health.dropped_count == 2
    assert {(lost.first_sequence, lost.last_sequence) for lost in health.lost_ranges} == {(2, 2), (3, 3)}
    assert health.writer.in_flight_count == 0
    assert health.queue_depth == 0
    # The drain resolved everything it held inside its budget, so the budget
    # never expired: no timeout warning, and no poison verdict either — the row
    # was never asked the second time that would have judged it.
    assert _drop_warnings(caplog) == []
    assert health.writer.poison_observation_count == 0


@pytest.mark.anyio
async def test_a_drain_that_finishes_early_places_everything_and_charges_nothing() -> None:
    """The budget is a ceiling, not a schedule.

    Every row recorded before ``stop()`` is the drain's work, including the ones
    the flush interval had not woken the writer for yet.
    """

    backend = _RecordingBackend()
    service = AnsichService(backend, batch_size=2, flush_interval_ms=60_000, stop_drain_timeout_ms=10_000)
    await service.start()
    observations = [_observation(f"run-drain-{index}") for index in range(5)]
    assert all(receipt.accepted for receipt in service.record_batch(observations))

    await asyncio.wait_for(service.stop(), timeout=30)
    health = service.get_health()

    assert backend.landed == [observation.source_event_id for observation in observations]
    assert health.dropped_count == 0
    assert health.lost_ranges == ()
    assert health.queue_depth == 0
    assert health.writer.in_flight_count == 0
    assert health.status == "stopped"


@pytest.mark.anyio
async def test_a_start_during_a_stop_is_refused() -> None:
    """The two lifecycle calls exclude each other, and the drain is the window.

    A ``start()`` landing in the middle of a drain re-arms the flags a drain is
    still using: health would walk ``shutting_down -> healthy``, which is not a
    legal transition, and the drain would go on charging rows behind a service
    that reports itself up. There is no ordering of the flag writes that makes
    that safe, so the call is refused instead.
    """

    backend = _WedgedBackend()
    service = AnsichService(backend, batch_size=1, flush_interval_ms=1, stop_drain_timeout_ms=200)
    await service.start()
    try:
        assert service.record(_observation("run-restart")).accepted
        await _wait_until(lambda: service.get_health().writer.in_flight_count == 1)

        stop_task = asyncio.create_task(service.stop())
        await _wait_until(lambda: service._stopping)
        with pytest.raises(RuntimeError):
            await service.start()

        await asyncio.wait_for(stop_task, timeout=30)
    finally:
        backend.released.set()

    assert service.get_health().status == "stopped"


@pytest.mark.anyio
async def test_a_stop_during_a_start_is_refused() -> None:
    """The other direction: a stop cannot drain loops that do not exist yet.

    ``start()`` awaits the backend's metrics bootstrap before it creates the
    writer, so a ``stop()`` arriving there would see nothing running, return
    immediately, and leave the half-built service to finish coming up behind it.
    """

    backend = _SlowStartBackend()
    service = AnsichService(backend, flush_interval_ms=60_000)
    start_task = asyncio.create_task(service.start())
    try:
        await asyncio.wait_for(backend.initializing.wait(), timeout=10)
        with pytest.raises(RuntimeError):
            await service.stop()
    finally:
        backend.release.set()
        await asyncio.wait_for(start_task, timeout=10)

    assert service.get_health().status == "healthy"
    await asyncio.wait_for(service.stop(), timeout=30)
    assert service.get_health().status == "stopped"


class _ScopeAwareBackend(_RecordingBackend):
    """Storage that declares Scopes real, so the host mint lands and loss can be written.

    ``projects_scope_entities`` is what makes ``_mint_host_scope`` write, which
    is what gives ``AnsichService.host_scope_id`` a value, which is the gate on
    the process-loss drain: a range with no Task is only writable against a
    host ``Scope`` that actually exists. ``refuse_kinds`` is how a test stands
    the collector in "the report could not be written" without a database.
    """

    projects_scope_entities = True

    def __init__(self) -> None:
        super().__init__()
        self.refuse_kinds: set[str] = set()

    async def persist_and_project(self, observations: list[ObservationEnvelope]) -> int:
        if any(observation.kind in self.refuse_kinds for observation in observations):
            raise RuntimeError("storage refused this batch")
        return await super().persist_and_project(observations)

    def lost_rows(self) -> list[ObservationEnvelope]:
        return [observation for observation in self.persisted if observation.kind == "observability.lost"]


class _EndlessProjectorBackend(_RecordingBackend):
    """A store whose projection queue never empties.

    Not a pathology: it is what a busy multi-worker store looks like from one
    worker at the moment it shuts down. The point is that the post-loop drain
    has to stop *itself* — nothing else ever will.
    """

    def __init__(self) -> None:
        super().__init__()
        self.rounds = 0

    async def project_pending(self, *, limit: int = 100) -> int:
        self.rounds += 1
        await asyncio.sleep(0)
        return 1


class _FrozenBarrierService(AnsichService):
    """A service whose terminal-barrier step never returns.

    The freeze is injected at the step rather than at a backend, because the
    claim under test is about the *sequence* — one step wedging must not cost
    the six around it — and a step that hangs for its own budget is the
    cheapest honest way to say so.
    """

    async def _drain_terminal_barriers(self, budget_seconds: float) -> str | None:
        await asyncio.Event().wait()
        return None


def _steps(report) -> dict[str, object]:
    return {step.name: step for step in report.steps}


@pytest.mark.anyio
async def test_the_report_names_the_seven_steps_in_spec_order() -> None:
    """Structural. The order is spec §8's and the names are what the lifespan logs.

    Pinned rather than left to the code because both halves are read by
    somebody: the order is the *argument* — barriers before the writer drain,
    claim-stop before the join — and the names end up in an operator's log.
    """

    backend = _RecordingBackend()
    service = AnsichService(backend, batch_size=2, flush_interval_ms=10, shutdown_budget_ms=5_000)
    await service.start()
    assert service.record(_observation("run-report-shape")).accepted

    report = await asyncio.wait_for(service.stop(), timeout=30)

    assert tuple(step.name for step in report.steps) == _SHUTDOWN_STEP_ORDER
    assert report.completed is True
    assert report.budget_ms == 5_000
    assert report.total_ms <= report.budget_ms
    assert all(step.ok and not step.timed_out for step in report.steps)
    # `stop()` is idempotent, and a second one has no steps to run: an empty
    # report is complete rather than a shutdown that failed every step.
    again = await asyncio.wait_for(service.stop(), timeout=30)
    assert again.steps == ()
    assert again.completed is True


@pytest.mark.anyio
async def test_an_active_task_and_a_writer_backlog_stop_inside_the_budget() -> None:
    """§10's shutdown case: a live Task, a full queue, one budget, one report.

    The flush interval is longer than the test, so every row is still queued
    when ``stop()`` is called: the drain step is what places them, and the
    report is what says it did.
    """

    backend = _RecordingBackend()
    task_id = new_id()
    service = AnsichService(backend, batch_size=10, flush_interval_ms=60_000, shutdown_budget_ms=5_000)
    await service.start()
    # An active Task — created and started, never terminal — plus a backlog
    # behind it.
    assert service.record(_observation("run-active", task_id=task_id)).accepted
    backlog = [_observation(f"run-backlog-{index}") for index in range(50)]
    assert all(receipt.accepted for receipt in service.record_batch(backlog))
    assert service.get_health().queue_depth == 51

    loop = asyncio.get_running_loop()
    started_at = loop.time()
    report = await asyncio.wait_for(service.stop(), timeout=30)
    elapsed = loop.time() - started_at
    health = service.get_health()

    assert elapsed < _STOP_CEILING_SECONDS
    assert report.completed is True
    assert report.total_ms <= report.budget_ms
    assert len(backend.landed) == 51
    assert health.status == "stopped"
    assert health.queue_depth == 0
    assert health.dropped_count == 0
    # The one step that had work to report says what it inherited; nothing was
    # charged, so the drain step reports nothing.
    assert _steps(report)["stop_new_records"].detail == "queued=51"
    assert _steps(report)["drain_writer"].detail is None


@pytest.mark.anyio
async def test_a_frozen_step_times_out_and_every_later_step_still_runs() -> None:
    """A step's timeout is its own. It never aborts the sequence.

    The barrier step is frozen outright. Under an abort-on-first-failure
    shutdown the writer would never drain (rows charged as lost that storage
    would have taken) and the process-loss bucket would never be written — the
    two things this sequence exists to do. So the report must show one step
    timed out and the four after it having run anyway.
    """

    backend = _RecordingBackend()
    service = _FrozenBarrierService(backend, batch_size=10, flush_interval_ms=60_000, shutdown_budget_ms=600)
    await service.start()
    assert all(receipt.accepted for receipt in service.record_batch([_observation(f"run-frozen-{index}") for index in range(4)]))

    loop = asyncio.get_running_loop()
    started_at = loop.time()
    report = await asyncio.wait_for(service.stop(), timeout=30)
    elapsed = loop.time() - started_at

    assert elapsed < _STOP_CEILING_SECONDS
    frozen = _steps(report)["drain_terminal_barriers"]
    assert frozen.timed_out is True
    assert frozen.ok is False
    assert report.completed is False
    # Every later step ran, and ran cleanly.
    later = [step for step in report.steps if step.name in _SHUTDOWN_STEP_ORDER[3:]]
    assert [step.name for step in later] == list(_SHUTDOWN_STEP_ORDER[3:])
    assert all(step.ok for step in later)
    # Not merely recorded — the work behind them happened: the backlog is
    # durable rather than charged as loss.
    assert len(backend.landed) == 4
    assert service.get_health().dropped_count == 0


@pytest.mark.anyio
async def test_the_post_stop_projection_drain_stops_claiming_at_its_deadline() -> None:
    """The unbounded post-loop drain is bounded, and by its own signal.

    ``_running`` cannot express this: the drain runs with ``_running`` already
    false, which is precisely why it used to spin forever against a store that
    always had claimable work. The claim-stop step writes a deadline the loop
    reads before every round, and reports that the deadline — not an empty
    store — is why it stopped.
    """

    backend = _EndlessProjectorBackend()
    service = AnsichService(backend, batch_size=10, flush_interval_ms=60_000, projector_poll_interval_ms=5, shutdown_budget_ms=500)
    await service.start()
    await _wait_until(lambda: backend.rounds > 0)

    loop = asyncio.get_running_loop()
    started_at = loop.time()
    report = await asyncio.wait_for(service.stop(), timeout=30)
    elapsed = loop.time() - started_at

    assert elapsed < _STOP_CEILING_SECONDS
    claim_stop = _steps(report)["stop_projection_claiming"]
    assert claim_stop.ok is True
    assert claim_stop.detail == "claim_stop_deadline_reached"
    # The loop is joined, not abandoned: a projector still running here would
    # project into a store the Gateway lifespan is about to close.
    assert _steps(report)["join_projector"].ok is True
    assert service._projector_task is None
    assert service.get_health().status == "stopped"


@pytest.mark.anyio
async def test_stop_writes_the_process_loss_bucket_down(caplog: pytest.LogCaptureFixture) -> None:
    """FC-5, the regression. Loss with no Task became durable at stop, or never.

    The range is charged, then frozen by the ordinary reporting seam (the
    cursor walks past it) while the drain is refused, so it is sitting in the
    bucket with nobody left to write it — exactly the state a shutdown finds
    after a bad last minute. Before this batch ``stop()`` never called the
    drain, so that range died with the process and the
    ``observability_degradation`` producer never saw it.
    """

    backend = _ScopeAwareBackend()
    service = AnsichService(backend, batch_size=1, flush_interval_ms=10, shutdown_budget_ms=5_000, hostname="bounded-stop-host")
    await service.start()
    assert service.host_scope_id is not None

    # A non-envelope item is charged process-wide: no envelope, so no Task and
    # no producer to attribute it to.
    assert service.record_batch((object(),))[0].accepted is False  # type: ignore[arg-type]
    assert service.get_health().unreported_global_lost_range_count == 1

    # Freeze the range without letting it out of the bucket: the seam advances
    # the report cursor, the drain it ends with is refused.
    backend.refuse_kinds = {"observability.lost"}
    assert service.record(_observation("run-loss-seam")).accepted
    await _wait_until(lambda: "task.created" in [observation.kind for observation in backend.persisted])
    assert service.get_health().unreported_global_lost_range_count == 1
    assert backend.lost_rows() == []
    backend.refuse_kinds = set()

    report = await asyncio.wait_for(service.stop(), timeout=30)
    health = service.get_health()

    lost_rows = backend.lost_rows()
    assert len(lost_rows) == 1
    assert lost_rows[0].subject_type == "scope"
    assert lost_rows[0].subject_id == service.host_scope_id
    assert health.unreported_global_lost_range_count == 0
    # Reported is not un-charged: the loss is still loss.
    assert health.dropped_count == 1
    assert health.lost_ranges != ()
    drain = _steps(report)["drain_unreported_loss"]
    assert drain.ok is True
    assert drain.detail is None


@pytest.mark.anyio
async def test_stop_leaves_a_still_growing_range_in_the_bucket() -> None:
    """The ``live`` guard's first real caller, and it declines to write.

    A range the report cursor has not walked past can still be *extended* in
    place, so writing it at stop would report the same loss twice if anything
    extended it afterwards. The honest answer is to leave it — and to keep
    counting it, which is what makes the omission visible rather than silent.
    """

    backend = _ScopeAwareBackend()
    service = AnsichService(backend, batch_size=1, flush_interval_ms=10, shutdown_budget_ms=5_000, hostname="bounded-stop-host")
    await service.start()
    assert service.host_scope_id is not None

    assert service.record_batch((object(),))[0].accepted is False  # type: ignore[arg-type]
    assert service.get_health().unreported_global_lost_range_count == 1

    report = await asyncio.wait_for(service.stop(), timeout=30)
    health = service.get_health()

    assert backend.lost_rows() == []
    assert health.unreported_global_lost_range_count == 1
    # Not a failure: the step did what it could and says what is left, which is
    # the same thing its own timeout would leave behind.
    drain = _steps(report)["drain_unreported_loss"]
    assert drain.ok is True
    assert drain.detail == "unreported_global_lost_ranges=1"
