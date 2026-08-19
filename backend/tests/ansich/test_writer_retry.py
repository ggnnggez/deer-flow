"""Bounded backoff retry, the in-flight buffer, and the lifecycle signals they feed.

A write that storage refuses is no longer a loss: the batch leaves the queue,
stays parked in the writer's in-flight buffer, and is retried on a bounded
exponential backoff. These tests drive that from the writer loop itself — the
only place a backoff wait is allowed to happen (spec §2: never on the Agent
call stack) — with a backend that can be programmed to refuse a given number of
writes.

Where the batch budget runs out this file hands over: ``_isolate_poison_batch``
then places the batch row by row, and what that costs a row storage will never
take is ``test_poison_isolation.py``'s subject. The two tests here that reach
that seam stay on this side of it — one lands the row inside the bisect, the
other only asks whether the persist lock was held across the wait.

No test here sits through a real backoff. ``_CapturingService`` overrides the
single sleeping point of the retry path, so the schedule is asserted from the
delays the production code computed rather than from wall-clock time. The one
test that does enter the real wait is the shutdown pin, and its whole point is
that the wait is cut short.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from ansich import AnsichService, ObservationEnvelope, new_id
from ansich.contracts import AnsichHealth
from ansich.lifecycle import LEGAL_TRANSITIONS
from ansich.memory import InMemoryAnsichBackend


def _observation(source_id: str, *, task_id: str | None = None) -> ObservationEnvelope:
    return ObservationEnvelope.task_lifecycle(
        kind="task.created",
        task_id=task_id or new_id(),
        source_kind="deerflow_run",
        source_id=source_id,
        occurred_at=datetime(2026, 8, 19, 12, 0, tzinfo=UTC),
        source_event_id=f"run:{source_id}:task:created",
    )


class _RefusingBackend(InMemoryAnsichBackend):
    """Refuses the first ``failures`` writes, then stores normally."""

    def __init__(self, failures: int) -> None:
        super().__init__()
        self.remaining_failures = failures
        self.attempts = 0
        self.persisted: list[ObservationEnvelope] = []

    async def persist_and_project(self, observations: list[ObservationEnvelope]) -> int:
        self.attempts += 1
        if self.remaining_failures > 0:
            self.remaining_failures -= 1
            raise OSError("storage refused the batch")
        count = await super().persist_and_project(observations)
        self.persisted.extend(observations)
        return count


class _OutageThenBacklogBackend(_RefusingBackend):
    """Refuses ``failures`` writes, then holds the *next* write open.

    Holding the write after the outage cleared is what makes the catch-up
    observable: the recovered batch is already durable, the backlog it left
    behind is still queued, and the service sits in exactly the state spec §2
    calls ``recovering``.
    """

    def __init__(self, failures: int) -> None:
        super().__init__(failures)
        self.landed = asyncio.Event()
        self.holding = asyncio.Event()
        self.release = asyncio.Event()
        self._held = False

    async def persist_and_project(self, observations: list[ObservationEnvelope]) -> int:
        if self.remaining_failures <= 0 and self.landed.is_set() and not self._held:
            self._held = True
            self.holding.set()
            await self.release.wait()
        count = await super().persist_and_project(observations)
        self.landed.set()
        return count


class _PoisonTaskBackend(InMemoryAnsichBackend):
    """Healthy storage that permanently refuses one Task's rows.

    This is the shape a constraint violation takes: the outage is not the
    storage, it is one row, so every other write must keep working while the
    writer is stuck on it.
    """

    def __init__(self, poison_task_id: str) -> None:
        super().__init__()
        self.poison_task_id = poison_task_id
        self.refusals = 0
        self.persisted: list[ObservationEnvelope] = []

    async def persist_and_project(self, observations: list[ObservationEnvelope]) -> int:
        if any(observation.task_id == self.poison_task_id for observation in observations):
            self.refusals += 1
            raise ValueError("constraint violation on this row")
        count = await super().persist_and_project(observations)
        self.persisted.extend(observations)
        return count


class _DeadBackend:
    """Never accepts a write; every read is duck-typed and safely absent."""

    async def persist_and_project(self, observations: list[ObservationEnvelope]) -> int:
        raise OSError("database unavailable")


class _CapturingService(AnsichService):
    """An ``AnsichService`` whose backoff records its schedule instead of sleeping.

    Overriding ``_sleep_before_retry`` — and nothing else — keeps every other
    part of the retry path in production shape: the delay under test is the one
    the service computed, and ``WriterHealth`` is read from inside the wait, so
    what the hook sees is what an operator polling health during a backoff sees.
    """

    def __init__(
        self,
        backend: object,
        *,
        on_backoff: Callable[[_CapturingService], None] | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(backend, **kwargs)  # type: ignore[arg-type]
        self.backoff_delays: list[float] = []
        self.backoff_health: list[AnsichHealth] = []
        self._on_backoff = on_backoff

    async def _sleep_before_retry(self, delay_seconds: float) -> None:
        self.backoff_delays.append(delay_seconds)
        self.backoff_health.append(self.get_health())
        if self._on_backoff is not None:
            self._on_backoff(self)
        await asyncio.sleep(0)


async def _wait_until(predicate: Callable[[], bool], *, timeout: float = 5.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        assert loop.time() < deadline, "condition was not reached in time"
        await asyncio.sleep(0.01)


def test_in_memory_accepts_the_same_writer_policy_as_the_real_constructor() -> None:
    # The convenience constructor is what tests and embedded callers reach for;
    # a writer policy it cannot express is a policy they cannot exercise.
    service = AnsichService.in_memory(
        writer_retry_max_attempts=2,
        writer_backoff_initial_ms=7,
        writer_backoff_max_ms=11,
        writer_item_max_attempts=3,
        stop_drain_timeout_ms=1_500,
    )

    assert service._writer_retry_max_attempts == 2
    assert service._writer_backoff_initial_ms == 7
    assert service._writer_backoff_max_ms == 11
    assert service._writer_item_max_attempts == 3
    assert service._stop_drain_timeout_seconds == 1.5


@pytest.mark.anyio
async def test_a_transient_outage_is_retried_until_it_lands_and_nothing_is_lost() -> None:
    backend = _RefusingBackend(failures=2)
    service = _CapturingService(backend, batch_size=1, flush_interval_ms=1)
    await service.start()
    try:
        for index in range(3):
            service.record(_observation(f"run-transient-{index}"))

        await _wait_until(lambda: len(backend.persisted) >= 3)
        health = service.get_health()
    finally:
        await service.stop()

    # Two refusals, zero loss: the batch was retried, not charged.
    assert backend.attempts == 5
    assert health.dropped_count == 0
    assert health.lost_ranges == ()
    assert len(service.backoff_delays) == 2
    # The failures were real while they lasted, and the count is cleared by the
    # write that finally landed rather than decayed on a timer.
    assert [entry.writer.consecutive_failures for entry in service.backoff_health] == [1, 2]
    assert health.writer.consecutive_failures == 0
    assert health.writer.in_flight_count == 0


@pytest.mark.anyio
async def test_the_writer_walks_degraded_recovering_healthy_across_an_outage() -> None:
    """The end-to-end reachability proof for ``recovering`` (reviewer finding N2).

    Post-PA6 the only production path that can put ``recovering`` on
    ``AnsichHealth.status`` is the writer's own retry backlog, so this is the
    test that says spec §2's middle state exists at all.
    """

    backend = _OutageThenBacklogBackend(failures=2)
    statuses: list[str] = []

    def _queue_a_backlog_behind_the_writer(service: _CapturingService) -> None:
        if len(service.backoff_delays) == 1:
            for index in range(1, 5):
                service.record(_observation(f"run-walk-{index}"))

    service = _CapturingService(
        backend,
        on_backoff=_queue_a_backlog_behind_the_writer,
        batch_size=1,
        flush_interval_ms=1,
    )
    await service.start()
    try:
        statuses.append(service.get_health().status)
        service.record(_observation("run-walk-0"))

        await asyncio.wait_for(backend.holding.wait(), timeout=5)
        statuses.extend(entry.status for entry in service.backoff_health)
        catching_up = service.get_health()
        statuses.append(catching_up.status)

        backend.release.set()
        await _wait_until(lambda: service.get_health().status == "healthy")
        statuses.append(service.get_health().status)
    finally:
        backend.release.set()
        await service.stop()

    # The write that ended the outage is already durable; what is left is the
    # backlog it caused, and the in-flight batch is out of `queue_depth`.
    assert catching_up.writer.consecutive_failures == 0
    assert catching_up.writer.in_flight_count == 1
    assert catching_up.queue_depth == 3
    assert catching_up.dropped_count == 0

    walk = [status for index, status in enumerate(statuses) if index == 0 or status != statuses[index - 1]]
    assert walk == ["healthy", "degraded", "recovering", "healthy"]
    for previous, current in zip(walk, walk[1:], strict=False):
        assert (previous, current) in LEGAL_TRANSITIONS, f"{previous} -> {current} is not a legal transition"


@pytest.mark.anyio
async def test_the_backoff_doubles_until_the_configured_cap() -> None:
    backend = _RefusingBackend(failures=5)
    service = _CapturingService(backend, batch_size=1, flush_interval_ms=1)
    await service.start()
    try:
        service.record(_observation("run-schedule"))
        await _wait_until(lambda: len(backend.persisted) >= 1)
    finally:
        await service.stop()

    # 100ms doubling, then the cap once the batch-level attempts are exhausted.
    assert service.backoff_delays == pytest.approx([0.1, 0.2, 0.4, 0.8, 5.0])


@pytest.mark.anyio
async def test_the_backoff_cap_is_configurable_and_clamps_the_whole_schedule() -> None:
    backend = _RefusingBackend(failures=4)
    service = _CapturingService(
        backend,
        batch_size=1,
        flush_interval_ms=1,
        writer_backoff_initial_ms=100,
        writer_backoff_max_ms=250,
    )
    await service.start()
    try:
        service.record(_observation("run-capped"))
        await _wait_until(lambda: len(backend.persisted) >= 1)
    finally:
        await service.stop()

    assert service.backoff_delays == pytest.approx([0.1, 0.2, 0.25, 0.25])


@pytest.mark.anyio
async def test_the_backoff_deadline_is_visible_while_the_writer_waits() -> None:
    backend = _RefusingBackend(failures=1)
    service = _CapturingService(backend, batch_size=1, flush_interval_ms=1)
    await service.start()
    try:
        service.record(_observation("run-visible"))
        await _wait_until(lambda: len(backend.persisted) >= 1)
        settled = service.get_health()
    finally:
        await service.stop()

    (waiting,) = service.backoff_health
    assert waiting.writer.backoff_until is not None
    assert waiting.writer.consecutive_failures == 1
    assert waiting.writer.in_flight_count == 1
    assert waiting.status == "degraded"
    # The deadline is a property of the wait, not a sticky field: once the
    # write lands there is nothing to wait for.
    assert settled.writer.backoff_until is None


@pytest.mark.anyio
async def test_records_keep_queueing_during_a_backoff_and_the_full_queue_tail_drops() -> None:
    backend = _RefusingBackend(failures=1)
    observed: list[AnsichHealth] = []

    def _fill_the_queue(service: _CapturingService) -> None:
        if len(service.backoff_delays) != 1:
            return
        for index in range(3):
            assert service.record(_observation(f"run-during-{index}")).accepted is True
        observed.append(service.get_health())
        # The queue is full while one batch is parked in flight, so this one is
        # tail-dropped and charged as loss — the pre-existing capacity rule.
        rejected = service.record(_observation("run-during-overflow"))
        observed.append(service.get_health())
        assert rejected.accepted is False
        assert rejected.reason == "queue_full"

    service = _CapturingService(
        backend,
        on_backoff=_fill_the_queue,
        queue_capacity=3,
        batch_size=1,
        flush_interval_ms=1,
    )
    await service.start()
    try:
        service.record(_observation("run-during-first"))
        await _wait_until(lambda: len(backend.persisted) >= 4)
    finally:
        await service.stop()

    accepted_during_backoff, after_overflow = observed
    # The parked batch left the queue but is still accounted for: it does not
    # consume queue capacity, and it is not invisible either.
    assert accepted_during_backoff.queue_depth == 3
    assert accepted_during_backoff.writer.in_flight_count == 1
    assert accepted_during_backoff.dropped_count == 0
    assert after_overflow.dropped_count == 1
    assert after_overflow.queue_depth == 3


@pytest.mark.anyio
async def test_an_exhausted_batch_is_handed_to_per_item_isolation_not_charged_whole() -> None:
    """Past ``writer_retry_max_attempts`` the batch is bisected, never charged.

    Exhausting the batch budget is a change of question, not a verdict: the
    writer stops asking "is storage down?" and starts asking about each row
    (``_isolate_poison_batch``). A row that lands there was never poison, so an
    outage lasting one attempt longer than the batch budget still costs nothing
    — what it costs when the row really is unwritable is
    ``test_poison_isolation.py``'s subject.
    """

    # Five batch attempts, then the bisect's first per-item attempt, and storage
    # is back for the row's second one.
    backend = _RefusingBackend(failures=6)
    service = _CapturingService(backend, batch_size=1, flush_interval_ms=1)
    await service.start()
    try:
        service.record(_observation("run-exhausted"))
        await _wait_until(lambda: len(backend.persisted) >= 1)
        health = service.get_health()
    finally:
        await service.stop()

    assert backend.attempts == 7
    # One schedule, not two: the batch's exponential run, the capped wait that
    # opens the bisect, then the same exponential again for the row itself.
    assert service.backoff_delays == pytest.approx([0.1, 0.2, 0.4, 0.8, 5.0, 0.1])
    # Every read taken while the writer was past its batch budget still shows
    # the work held, not lost.
    for entry in service.backoff_health[4:]:
        assert entry.dropped_count == 0
        assert entry.writer.in_flight_count == 1
        assert entry.writer.poison_observation_count == 0
    assert health.dropped_count == 0
    assert health.lost_ranges == ()
    assert health.writer.poison_observation_count == 0
    assert len(backend.persisted) == 1


@pytest.mark.anyio
async def test_a_parked_poison_batch_does_not_block_the_terminal_barrier() -> None:
    """One unwritable row must not stop every other Task from being persisted.

    The writer is inside ``_isolate_poison_batch``, holding the capped wait that
    opens the bisect. If it held ``persist_lock`` across that wait, every
    terminal barrier after it would spend its whole budget waiting for a lock,
    never reach storage, and charge its own rows as lost — a single constraint
    violation would take the collector's write path down with it. What the
    bisect then does with the row is ``test_poison_isolation.py``'s subject;
    here it is only the lock that is on trial, so the capped wait is left long
    enough that the row is still held when the barrier's own budget expires.
    """

    poison_task = new_id()
    healthy_task = new_id()
    backend = _PoisonTaskBackend(poison_task)
    service = AnsichService(
        backend,
        batch_size=1,
        flush_interval_ms=1,
        terminal_flush_timeout_ms=200,
        writer_retry_max_attempts=3,
        writer_backoff_initial_ms=1,
        writer_backoff_max_ms=5_000,
    )
    await service.start()
    try:
        service.record(_observation("poison", task_id=poison_task))
        # Batch attempts exhausted and the row parked on the bisect's opening
        # wait, which is where the writer now spends its (capped) waits.
        await _wait_until(lambda: service.get_health().writer.consecutive_failures >= 3 and service.get_health().writer.in_flight_count == 1)
        before = service.get_health()

        service.record(_observation("healthy", task_id=healthy_task))
        result = await service.flush_task(healthy_task)
        after = service.get_health()
    finally:
        await service.stop()

    assert result.persisted is True
    assert result.reason is None
    assert [observation.task_id for observation in backend.persisted] == [healthy_task]
    assert before.dropped_count == 0
    assert after.dropped_count == 0
    assert after.lost_ranges == ()
    # And the barrier did not "unblock" itself by discarding the parked batch.
    assert after.writer.in_flight_count == 1


@pytest.mark.anyio
async def test_the_barrier_writes_while_the_writer_sleeps_out_its_backoff() -> None:
    """Storage recovered; the writer is still asleep. The barrier must not wait.

    The backoff here is 5s against a 200ms terminal budget, so a barrier that
    had to wait for the writer's clock could only ever time out. It succeeds
    because the writer holds the persist lock for its attempts, never for its
    waits.
    """

    backend = _RefusingBackend(failures=1)
    terminal_task = new_id()
    service = AnsichService(
        backend,
        batch_size=1,
        flush_interval_ms=1,
        terminal_flush_timeout_ms=200,
        writer_backoff_initial_ms=5_000,
        writer_backoff_max_ms=5_000,
    )
    await service.start()
    try:
        service.record(_observation("outage"))
        await _wait_until(lambda: service.get_health().writer.backoff_until is not None)
        attempts_before = backend.attempts

        service.record(_observation("terminal", task_id=terminal_task))
        result = await service.flush_task(terminal_task)
        # Captured before the drain: `stop()` interrupts the writer's wait, and
        # its own next attempt would otherwise be counted here too.
        attempts_after = backend.attempts
        persisted_after = [observation.task_id for observation in backend.persisted]
        health = service.get_health()
    finally:
        await service.stop()

    assert result.persisted is True
    assert result.reason is None
    # A real storage attempt, not a timeout dressed up as one.
    assert attempts_after == attempts_before + 1
    assert persisted_after == [terminal_task]
    assert health.dropped_count == 0


@pytest.mark.anyio
async def test_a_cancelled_writer_charges_its_parked_batch_instead_of_dropping_it() -> None:
    """A batch the writer is holding must never vanish without being accounted.

    Cancellation is how an event loop shuts a writer down, and the parked batch
    is out of the queue by then — nothing else would ever report it. Full
    shutdown semantics (a drain budget) remain Task 7's; this is the guarantee
    that the in-flight buffer cannot swallow work in the meantime.
    """

    service = AnsichService(
        _DeadBackend(),
        batch_size=1,
        flush_interval_ms=1,
        writer_backoff_initial_ms=5_000,
    )
    await service.start()
    try:
        service.record(_observation("cancelled"))
        await _wait_until(lambda: service.get_health().writer.in_flight_count == 1)

        writer_task = service._writer_task
        assert writer_task is not None
        writer_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await writer_task

        health = service.get_health()
    finally:
        # `stop()` awaits the writer task again, which re-raises the cancellation.
        with contextlib.suppress(asyncio.CancelledError):
            await service.stop()

    assert health.dropped_count == 1
    assert len(health.lost_ranges) == 1
    assert health.lost_ranges[0].first_sequence == 1
    assert health.writer.in_flight_count == 0


@pytest.mark.anyio
async def test_stop_cuts_a_pending_backoff_short_instead_of_waiting_it_out() -> None:
    """Shutdown interrupts the wait; the retry loop cannot wedge ``stop()``.

    The backoff is configured at five seconds and the backend never recovers,
    so a ``stop()`` that had to sit through the pending wait would take that
    long. Task 7 gives the drain its own budget on top of this; what is pinned
    here is that the wait itself is interruptible.
    """

    service = AnsichService(
        _DeadBackend(),
        batch_size=1,
        flush_interval_ms=1,
        writer_backoff_initial_ms=5_000,
    )
    await service.start()
    service.record(_observation("run-dead"))
    await _wait_until(lambda: service.get_health().writer.backoff_until is not None)

    loop = asyncio.get_running_loop()
    started_at = loop.time()
    await asyncio.wait_for(service.stop(), timeout=30)
    elapsed = loop.time() - started_at

    health = service.get_health()
    assert elapsed < 2.0, f"stop() sat through the backoff: {elapsed:.2f}s"
    assert health.status == "stopped"
    # Nothing is quietly held: the batch the drain could not place is charged.
    assert health.dropped_count == 1
    assert health.writer.in_flight_count == 0
