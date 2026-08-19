"""The terminal flush barrier, bounded by collector sequence instead of by Task.

``flush_task`` used to *extract* one Task's rows from the middle of the queue
and place them, leaving everything recorded before them behind. That is a
reordering nothing downstream can explain: collector sequence is the
authoritative order for every reader of these rows, and the barrier was the one
writer allowed to violate it. RA5① replaces the extraction with a barrier:
persist **every** queued row up to this Task's highest queued sequence ``S``, in
order. A neighbour Task's earlier rows landing is not a side effect to be
tolerated — it is what "flushed up to S" means.

Three further properties are on trial here:

* **A timeout no longer kills the rows it took** (RA5②). They go back to the
  head of the queue, in order, and the writer places them when storage is back.
  The result says ``timed_out=True`` and reports how far persistence actually
  got, instead of charging a range as lost that nothing had even refused.
* **``persisted_through`` is contiguous, and it does not lie across a hole.**
  A row that is still parked in the writer's hands, or one charged as poison,
  stops the watermark *below* it. The barrier can legitimately answer
  ``persisted=True`` while an earlier row of the same Task is still in flight —
  ``persisted`` keeps its coarse "this call's rows landed" meaning — so
  ``persisted_through`` is where that gap has to be visible.
* **The barrier never steals the writer's parked batch.** Its selection is
  taken from the queue; rows the writer holds belong to the writer, and the
  honest report of that is a capped watermark, not a second writer.

RA8② rides along: a process-wide (``task_id is None``) lost range has no
subject to write an ``observability.degraded`` Observation against, and the
reporting pass used to walk past it anyway — marking as reported something it
had never written. Those ranges now sit in an explicit unreported bucket that
health counts.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from ansich import AnsichService, FlushResult, ObservationEnvelope, new_id
from ansich.lifecycle import LifecycleInputs, derive_status
from ansich.memory import InMemoryAnsichBackend


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
    """Keeps every write it accepted, and its shape, for the tests to read."""

    def __init__(self) -> None:
        super().__init__()
        self.persisted: list[ObservationEnvelope] = []
        self.write_sizes: list[int] = []

    async def persist_and_project(self, observations: list[ObservationEnvelope]) -> int:
        self.write_sizes.append(len(observations))
        count = await super().persist_and_project(observations)
        self.persisted.extend(observations)
        return count

    @property
    def landed(self) -> list[str]:
        """``source_event_id`` of the work, in write order.

        Filtered on purpose: a charged loss is reported back into the
        Observation stream as ``observability.degraded`` and lands here too.
        That is the collector talking about the incident, not the work.
        """

        return [observation.source_event_id for observation in self.persisted if observation.kind == "task.created"]

    @property
    def degradation_reports(self) -> list[ObservationEnvelope]:
        return [observation for observation in self.persisted if observation.kind == "observability.degraded"]


class _RowRefusingBackend(_RecordingBackend):
    """Healthy storage that permanently refuses writes carrying named rows."""

    def __init__(self, *refused_source_event_ids: str) -> None:
        super().__init__()
        self.refused = set(refused_source_event_ids)

    async def persist_and_project(self, observations: list[ObservationEnvelope]) -> int:
        if any(observation.source_event_id in self.refused for observation in observations):
            self.write_sizes.append(len(observations))
            raise ValueError("constraint violation on this row")
        return await super().persist_and_project(observations)


class _GatedBackend(_RecordingBackend):
    """Storage that can be made to hold a write open until the test lets go.

    A held write is how a barrier is made to spend its whole budget inside
    ``persist_and_project``: the timeout then lands on a call that has already
    taken rows off the queue, which is the case RA5② is about.
    """

    def __init__(self) -> None:
        super().__init__()
        self._gate = asyncio.Event()
        self._gate.set()
        self.holding = asyncio.Event()

    def hold_writes(self) -> None:
        self._gate.clear()

    def release_writes(self) -> None:
        self._gate.set()

    async def persist_and_project(self, observations: list[ObservationEnvelope]) -> int:
        if not self._gate.is_set():
            self.holding.set()
            await self._gate.wait()
        return await super().persist_and_project(observations)


class _AlwaysRefusingBackend(_RecordingBackend):
    """Storage that refuses everything, so the barrier's one attempt fails."""

    async def persist_and_project(self, observations: list[ObservationEnvelope]) -> int:
        self.write_sizes.append(len(observations))
        raise OSError("storage refused the write")


class _DegradationRefusingBackend(_RecordingBackend):
    """Storage that takes ordinary work but refuses the first loss report."""

    def __init__(self, refusals: int) -> None:
        super().__init__()
        self.remaining_refusals = refusals
        self.refused_reports = 0

    async def persist_and_project(self, observations: list[ObservationEnvelope]) -> int:
        if self.remaining_refusals > 0 and all(observation.kind == "observability.degraded" for observation in observations):
            self.remaining_refusals -= 1
            self.refused_reports += 1
            self.write_sizes.append(len(observations))
            raise OSError("storage refused the degradation report")
        return await super().persist_and_project(observations)


class _NeverSettlingBackend(_RecordingBackend):
    """Storage that takes every write and never finishes projecting it."""

    async def has_pending_for_task(self, task_id: str) -> bool:
        return True

    async def project_pending(self, *, limit: int) -> int:
        return 0


class _HeldWriterService(AnsichService):
    """A service whose writer loop is held until the test releases it.

    The writer and the barrier take work off the same queue under the same
    persist lock, so *which of them* takes a given row is otherwise a race with
    the flush interval. Holding the writer keeps the queue exactly as the test
    recorded it, which is what makes "the barrier took these rows" an assertion
    rather than a coin flip. ``stop()`` drains through the same method, so every
    test releases the writer before stopping.
    """

    def __init__(self, backend: object, **kwargs: object) -> None:
        super().__init__(backend, **kwargs)  # type: ignore[arg-type]
        self._writer_gate = asyncio.Event()

    def release_writer(self) -> None:
        self._writer_gate.set()

    async def _flush_batch(self):  # type: ignore[no-untyped-def]
        await self._writer_gate.wait()
        return await super()._flush_batch()


class _CapturingService(AnsichService):
    """Reports the backoff schedule instead of sleeping it."""

    def __init__(self, backend: object, **kwargs: object) -> None:
        super().__init__(backend, **kwargs)  # type: ignore[arg-type]
        self.backoff_delays: list[float] = []

    async def _sleep_before_retry(self, delay_seconds: float) -> None:
        self.backoff_delays.append(delay_seconds)
        await asyncio.sleep(0)


async def _wait_until(predicate: Callable[[], bool], *, timeout: float = 10.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        assert loop.time() < deadline, "condition was not reached in time"
        await asyncio.sleep(0.01)


@pytest.mark.anyio
async def test_the_barrier_places_every_queued_row_up_to_this_tasks_last_one() -> None:
    """RA5①: the bound is a collector sequence, not a Task filter.

    Two Tasks interleave in the queue. Flushing A must place B's rows that were
    recorded *before* A's last one — they are below the barrier — and must leave
    B's later row queued, because it is above it. The old by-Task extraction
    placed exactly A's two rows and silently reordered the stream around them.
    """

    task_a = new_id()
    task_b = new_id()
    rows = [
        _observation("b-first", task_id=task_b),
        _observation("a-first", task_id=task_a),
        _observation("b-second", task_id=task_b),
        _observation("a-last", task_id=task_a),
        _observation("b-after", task_id=task_b),
    ]
    backend = _GatedBackend()
    service = _HeldWriterService(backend, batch_size=10, flush_interval_ms=1)
    await service.start()
    try:
        assert all(receipt.accepted for receipt in service.record_batch(rows))
        result = await service.flush_task(task_a)
        after_barrier = service.get_health()

        service.release_writer()
        await _wait_until(lambda: len(backend.landed) == len(rows))
        health = service.get_health()
    finally:
        service.release_writer()
        await service.stop()

    assert result.persisted is True
    assert result.reason is None
    assert result.processed_count == 4
    assert result.timed_out is False
    assert result.lost_ranges == ()
    # Everything up to A's last row (collector sequence 4) is durable.
    assert result.persisted_through == 4
    # One write, in collector order, carrying both Tasks' rows.
    assert backend.write_sizes[0] == 4
    assert backend.landed[:4] == [
        "run:b-first:task:created",
        "run:a-first:task:created",
        "run:b-second:task:created",
        "run:a-last:task:created",
    ]
    # And the row above the barrier stayed queued for the writer.
    assert after_barrier.queue_depth == 1
    assert backend.landed[4] == "run:b-after:task:created"
    assert health.dropped_count == 0
    assert health.lost_ranges == ()


@pytest.mark.anyio
async def test_a_barrier_that_times_out_returns_its_rows_to_the_queue_head() -> None:
    """RA5②: a budget running out is not evidence that anything was refused.

    Today's barrier charged everything it had taken as lost the moment its
    timeout fired — storage had not refused those rows, it had merely not
    answered yet. The rows now go back to the head of the queue in collector
    order and the writer places them when storage answers. Zero loss, and the
    caller is told the call timed out rather than being told a range died.
    """

    task_id = new_id()
    rows = [
        _observation("timeout-first", task_id=task_id),
        _observation("timeout-second", task_id=task_id),
    ]
    trailing = _observation("timeout-trailing")
    backend = _GatedBackend()
    service = _HeldWriterService(
        backend,
        batch_size=10,
        flush_interval_ms=1,
        terminal_flush_timeout_ms=100,
    )
    await service.start()
    try:
        assert all(receipt.accepted for receipt in service.record_batch(rows))
        assert service.record(trailing).accepted
        queued_bytes = service.get_health().queue_bytes
        backend.hold_writes()

        result = await service.flush_task(task_id)
        after_timeout = service.get_health()

        backend.release_writes()
        service.release_writer()
        await _wait_until(lambda: len(backend.landed) == 3)
        health = service.get_health()
    finally:
        backend.release_writes()
        service.release_writer()
        await service.stop()

    assert result.timed_out is True
    assert result.persisted is False
    assert result.processed_count == 0
    assert result.reason == "terminal_flush_timeout"
    # Nothing was refused, so nothing is reported lost.
    assert result.lost_ranges == ()
    assert result.persisted_through is None
    # The rows are back where they were, ahead of the row recorded after them,
    # and their bytes are back on the queue's account with them.
    assert after_timeout.queue_depth == 3
    assert after_timeout.queue_bytes == queued_bytes
    assert after_timeout.dropped_count == 0
    assert after_timeout.lost_ranges == ()
    assert health.dropped_count == 0
    assert health.lost_ranges == ()
    assert backend.landed == [
        "run:timeout-first:task:created",
        "run:timeout-second:task:created",
        "run:timeout-trailing:task:created",
    ]


@pytest.mark.anyio
async def test_rows_a_barrier_is_writing_are_outstanding_not_durable() -> None:
    """A barrier's own selection is a fifth state, and it must be counted.

    Rows the barrier has taken are off the queue and not yet in storage. If
    nothing tracks them they are in none of the states ``persisted_through``
    reads, so they read as *durable* — the one direction that field must never
    lie in — and ``in_flight_count`` reports 0 while two rows are outstanding.
    Registering the selection for the duration of the write is what makes both
    answers honest, and it costs nothing once the call resolves.
    """

    task_id = new_id()
    backend = _GatedBackend()
    service = _HeldWriterService(
        backend,
        batch_size=10,
        flush_interval_ms=1,
        terminal_flush_timeout_ms=10_000,
    )
    await service.start()
    barrier: asyncio.Task[FlushResult] | None = None
    try:
        assert all(
            receipt.accepted
            for receipt in service.record_batch(
                [
                    _observation("outstanding-first", task_id=task_id),
                    _observation("outstanding-second", task_id=task_id),
                ]
            )
        )
        assert service.record(_observation("outstanding-trailing")).accepted
        backend.hold_writes()

        barrier = asyncio.create_task(service.flush_task(task_id))
        await asyncio.wait_for(backend.holding.wait(), timeout=5)
        held = service.get_health()

        backend.release_writes()
        result = await asyncio.wait_for(barrier, timeout=5)
        after = service.get_health()
    finally:
        backend.release_writes()
        service.release_writer()
        if barrier is not None:
            await asyncio.gather(barrier, return_exceptions=True)
        await service.stop()

    # Two rows in the barrier's hands, one still queued behind the barrier.
    assert held.queue_depth == 1
    assert held.writer.in_flight_count == 2
    assert held.dropped_count == 0
    assert result.persisted is True
    assert result.persisted_through == 2
    # And the registration is released with the call, not left behind.
    assert after.writer.in_flight_count == 0


def test_a_barriers_outstanding_rows_are_not_the_writers_backlog() -> None:
    """A barrier's write is outstanding work, but it is not writer backlog.

    ``_writer_retry_backlog`` means "still working through what a write failure
    left behind", and ``recovering`` is derived from it. A barrier's in-progress
    write has refused nothing, so the writer reaching the end of *its own* work
    must clear the latch even while barrier rows are outstanding — otherwise an
    ordinary terminal flush would hold the collector in ``recovering`` for as
    long as its write takes. Every other reader of the buffer sees those rows,
    which is the whole point of tracking them.

    Driven at the rule rather than through the loops on purpose. The persist
    lock currently serializes a barrier's write against every writer attempt, so
    the two cannot overlap today and no scenario reaches this branch; the guard
    is a precondition for the writes that will happen outside the writer loop
    (the stop drain), and this pins the rule it encodes instead of today's
    locking coincidence.
    """

    service = AnsichService.in_memory(batch_size=10)
    rows = [(1, _observation("outstanding"))]

    writer_token = service._enter_in_flight(rows)
    barrier_token = service._enter_in_flight(rows, barrier=True)
    with service._lock:
        assert service._writer_holds_nothing() is False
        assert service._in_flight_observation_count() == 2
        assert service._in_flight_sequence_bounds() == (1, 1)

    service._exit_in_flight(writer_token)
    with service._lock:
        # The writer is caught up; the rows are still outstanding for everyone.
        assert service._writer_holds_nothing() is True
        assert service._in_flight_observation_count() == 1

    service._writer_retry_backlog = True
    service._record_write_success()
    assert service._writer_retry_backlog is False

    service._exit_in_flight(barrier_token)
    with service._lock:
        assert service._in_flight_observation_count() == 0
        assert service._in_flight_sequence_bounds() is None


@pytest.mark.anyio
async def test_a_second_barrier_on_a_shorter_budget_cannot_claim_the_first_ones_rows() -> None:
    """Two barriers, two deadlines: the shorter one must not over-claim.

    The budget is per service today, so the second caller can only read the
    watermark after the first's deadline has already fired — a coincidence, and
    Task 7's per-call drain budget plus a driver that unwinds a cancelled write
    on its own schedule both end it. Diverging the deadlines here is what tests
    the invariant rather than the coincidence: while the first barrier still
    holds sequences 1-2, no other caller may be told they are durable.
    """

    task_a = new_id()
    task_b = new_id()
    backend = _GatedBackend()
    service = _HeldWriterService(
        backend,
        batch_size=10,
        flush_interval_ms=1,
        terminal_flush_timeout_ms=10_000,
    )
    await service.start()
    first: asyncio.Task[FlushResult] | None = None
    try:
        assert all(
            receipt.accepted
            for receipt in service.record_batch(
                [
                    _observation("slow-first", task_id=task_a),
                    _observation("slow-second", task_id=task_a),
                ]
            )
        )
        assert service.record(_observation("fast", task_id=task_b)).accepted
        backend.hold_writes()

        first = asyncio.create_task(service.flush_task(task_a))
        await asyncio.wait_for(backend.holding.wait(), timeout=5)
        # Per-call deadline divergence, simulated: the second caller's budget
        # expires while the first still holds the persist lock and its rows.
        service._terminal_flush_timeout_seconds = 0.05
        second = await service.flush_task(task_b)

        backend.release_writes()
        first_result = await asyncio.wait_for(first, timeout=5)
        health = service.get_health()
    finally:
        backend.release_writes()
        service.release_writer()
        if first is not None:
            await asyncio.gather(first, return_exceptions=True)
        await service.stop()

    assert second.timed_out is True
    assert second.reason == "terminal_flush_timeout"
    # Sequences 1-2 were in the other barrier's hands, so nothing below them is
    # durable either: the honest answer is "no contiguous prefix yet".
    assert second.persisted_through is None
    assert second.lost_ranges == ()
    # The first call's own answer, once its rows really did land.
    assert first_result.persisted is True
    assert first_result.persisted_through == 2
    assert health.dropped_count == 0


@pytest.mark.anyio
async def test_persisted_through_stops_below_a_charged_poison_row() -> None:
    """A charged row is a permanent hole, and a watermark may not cross it.

    The in-flight buffer alone cannot answer this: once the poison row has been
    charged the writer holds nothing, so "one below the lowest row I am holding"
    would happily claim the *lost* sequence as persisted. ``persisted_through``
    is contiguous, so it stops at the last sequence with nothing missing under
    it — here, one below the poison row.
    """

    poison_task = new_id()
    terminal_task = new_id()
    poison = _observation("poison", task_id=poison_task)
    backend = _RowRefusingBackend(poison.source_event_id)
    service = _CapturingService(backend, batch_size=1, flush_interval_ms=1)
    await service.start()
    try:
        assert service.record(_observation("healthy-first")).accepted
        assert service.record(_observation("healthy-second")).accepted
        assert service.record(poison).accepted
        await _wait_until(lambda: service.get_health().writer.poison_observation_count == 1)
        charged = service.get_health()

        assert service.record(_observation("terminal", task_id=terminal_task)).accepted
        result = await service.flush_task(terminal_task)
    finally:
        await service.stop()

    (lost,) = charged.lost_ranges
    assert (lost.first_sequence, lost.last_sequence) == (3, 3)
    assert result.persisted is True
    assert result.processed_count == 1
    # Sequence 4 is durable, but 3 never will be: the claim stops at 2.
    assert result.persisted_through == 2
    assert result.persisted_through < lost.first_sequence


@pytest.mark.anyio
async def test_persisted_through_stops_below_a_batch_the_writer_still_holds() -> None:
    """T4's carry: ``persisted=True`` beside an earlier row still in flight.

    The barrier may not take the writer's parked batch — those rows are the
    writer's to resolve — so it legitimately places rows recorded *after* rows
    that are not durable yet. ``persisted`` keeps its coarse meaning ("this
    call's rows landed"); the precise claim lives in ``persisted_through``,
    which stops below the parked batch.
    """

    parked_task = new_id()
    terminal_task = new_id()
    parked = _observation("parked", task_id=parked_task)
    backend = _RowRefusingBackend(parked.source_event_id)
    service = AnsichService(
        backend,
        batch_size=1,
        flush_interval_ms=1,
        terminal_flush_timeout_ms=500,
        writer_backoff_initial_ms=5_000,
        writer_backoff_max_ms=5_000,
    )
    await service.start()
    try:
        assert service.record(_observation("healthy-first")).accepted
        assert service.record(_observation("healthy-second")).accepted
        assert service.record(parked).accepted
        # The writer has taken the third row, been refused, and is asleep on its
        # backoff — the row is out of the queue and in its hands.
        await _wait_until(lambda: service.get_health().writer.backoff_until is not None and service.get_health().writer.in_flight_count == 1)

        assert service.record(_observation("terminal", task_id=terminal_task)).accepted
        result = await service.flush_task(terminal_task)
        after = service.get_health()
    finally:
        await service.stop()

    assert result.persisted is True
    assert result.reason is None
    assert result.processed_count == 1
    # Sequence 4 landed; sequence 3 is still parked, so the contiguous claim
    # stops at 2 rather than swallowing the gap.
    assert result.persisted_through == 2
    # And the barrier did not help itself to the writer's batch.
    assert after.writer.in_flight_count == 1
    assert after.dropped_count == 0
    assert "run:parked:task:created" not in backend.landed


@pytest.mark.anyio
async def test_a_process_wide_lost_range_is_never_counted_as_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RA8②: a range with no subject cannot be written, so it stays unreported.

    ``observability.degraded`` is written against the lost range's Task. A
    process-wide range has none — the subject design for those is P11-B's
    host-Scope work — and the reporting pass used to walk its cursor past them
    anyway, so a range that was never written was permanently marked reported.
    They are now kept in an explicit unreported bucket, counted in health, and
    handed to the lifecycle derivation as pending loss residue.
    """

    task_id = new_id()
    lifecycle_inputs: list[LifecycleInputs] = []

    def _spy(inputs: LifecycleInputs) -> str:
        lifecycle_inputs.append(inputs)
        return derive_status(inputs)

    monkeypatch.setattr("ansich.service.derive_status", _spy)

    backend = _RecordingBackend()
    service = _HeldWriterService(backend, queue_capacity=2, batch_size=10, flush_interval_ms=1)
    await service.start()
    try:
        # Sequence 1: not an Observation at all, so nothing owns the loss.
        assert not service.record_batch(["not-an-envelope"])[0].accepted  # type: ignore[list-item]
        # Sequences 2 and 3 fill the queue; sequence 4 is a Task-scoped drop.
        assert service.record(_observation("kept-first", task_id=task_id)).accepted
        assert service.record(_observation("kept-second", task_id=task_id)).accepted
        assert not service.record(_observation("dropped", task_id=task_id)).accepted

        service.release_writer()
        await _wait_until(lambda: len(backend.landed) == 2)
        await _wait_until(lambda: bool(backend.degradation_reports))
        health = service.get_health()
    finally:
        service.release_writer()
        await service.stop()

    assert health.dropped_count == 2
    # The Task-scoped range was reported; the process-wide one was not.
    (report,) = backend.degradation_reports
    assert report.payload["first_sequence"] == 4
    assert health.unreported_global_lost_range_count == 1
    # And the derivation is told about the residue rather than a hardcoded False.
    assert any(inputs.unreported_loss_pending for inputs in lifecycle_inputs)
    # Loss is permanent evidence, so it still outranks the residue signal.
    assert health.status == "degraded"


@pytest.mark.anyio
async def test_a_refused_loss_report_is_offered_again_rather_than_skipped() -> None:
    """The other half of RA8②: the cursor may not outrun the writes.

    Filing an unwritable range in a bucket is only honest if a range that *is*
    writable, and whose write was refused, is offered again. The cursor moves
    on storage's answer, not on having tried.
    """

    task_id = new_id()
    backend = _DegradationRefusingBackend(refusals=1)
    service = _HeldWriterService(backend, queue_capacity=1, batch_size=10, flush_interval_ms=1)
    await service.start()
    try:
        assert service.record(_observation("kept", task_id=task_id)).accepted
        # The queue is full, so this one is charged — a Task-scoped range with a
        # subject to be reported against.
        assert not service.record(_observation("dropped", task_id=task_id)).accepted

        service.release_writer()
        await _wait_until(lambda: backend.refused_reports == 1)
        assert backend.degradation_reports == []

        assert service.record(_observation("later", task_id=task_id)).accepted
        await _wait_until(lambda: bool(backend.degradation_reports))
        health = service.get_health()
    finally:
        service.release_writer()
        await service.stop()

    # Offered again after the refusal, and exactly once after it landed.
    (report,) = backend.degradation_reports
    assert report.payload["first_sequence"] == 2
    assert health.dropped_count == 1
    assert health.unreported_global_lost_range_count == 0


@pytest.mark.anyio
async def test_a_loss_contiguous_with_a_reported_range_gets_its_own_report() -> None:
    """The third way the cursor could lie: coalescing across the boundary.

    ``_record_loss`` merges a loss into the last range when it continues it —
    same Task, same producer, next sequence — which is what keeps an outage from
    filing one range per row. But a range that has *already been written* into
    the Observation stream is finished: extending it in place hides the
    extension below the reporting cursor, where the pass can never see it again,
    and the ranges the pass did write claim less loss than the collector
    charged. Under-reporting loss is the one direction that is never allowed.

    So coalescing stops at the boundary: a loss that continues a reported range
    opens a new one, which is reported in its own right on the next pass.

    Driven at the rule's own level. Reaching it end to end needs a successful
    write — the only thing that runs the reporting pass — to land *between* two
    losses that are contiguous in the collector sequence and share a producer,
    and the incident shapes that charge contiguous rows charge them without an
    intervening write. The two seams are called here in exactly the order the
    service calls them in.
    """

    task_id = new_id()
    backend = _RecordingBackend()
    service = AnsichService(backend, flush_interval_ms=60_000)

    with service._lock:
        service._record_loss(1, task_id, producer_name="probe", producer_instance_id="local")
    await service._report_degradation_if_storage_recovered()
    with service._lock:
        service._record_loss(2, task_id, producer_name="probe", producer_instance_id="local")
    await service._report_degradation_if_storage_recovered()

    assert [(report.payload["first_sequence"], report.payload["last_sequence"]) for report in backend.degradation_reports] == [(1, 1), (2, 2)]
    # Two ranges, not one extended one: the second is what carries the second
    # report, and health shows the same two the stream was told about.
    assert [(lost.first_sequence, lost.last_sequence) for lost in service.get_health().lost_ranges] == [(1, 1), (2, 2)]


@pytest.mark.anyio
async def test_a_barrier_on_a_task_with_nothing_queued_reports_the_known_watermark() -> None:
    """Old-field clamp: an empty selection is still a successful flush."""

    task_id = new_id()
    backend = _GatedBackend()
    service = _HeldWriterService(backend, batch_size=10, flush_interval_ms=1)
    await service.start()
    try:
        assert service.record(_observation("other-task")).accepted
        service.release_writer()
        await _wait_until(lambda: len(backend.landed) == 1)

        result = await service.flush_task(task_id)
    finally:
        service.release_writer()
        await service.stop()

    assert result.persisted is True
    assert result.processed_count == 0
    assert result.reason is None
    assert result.timed_out is False
    assert result.lost_ranges == ()
    # Nothing of this Task's was queued, but the collector still knows how far
    # persistence has got overall.
    assert result.persisted_through == 1


@pytest.mark.anyio
async def test_a_refused_barrier_reports_the_ranges_it_charged() -> None:
    """Old-field clamp for the storage-failure path, plus the new range report.

    The barrier gets one attempt — retries and backoff belong to the writer
    loop, never to an Agent's call stack — so a refusal is charged here exactly
    as it was before. What is new is that the caller is handed the ranges this
    call charged instead of having to diff process-wide health to find them.
    """

    task_id = new_id()
    backend = _AlwaysRefusingBackend()
    service = _HeldWriterService(backend, batch_size=10, flush_interval_ms=1)
    await service.start()
    try:
        assert service.record(_observation("refused-first", task_id=task_id)).accepted
        assert service.record(_observation("refused-second", task_id=task_id)).accepted
        result = await service.flush_task(task_id)
        health = service.get_health()
    finally:
        service.release_writer()
        await service.stop()

    assert result.persisted is False
    assert result.processed_count == 0
    assert result.reason == "storage_failure"
    assert result.timed_out is False
    assert len(backend.write_sizes) >= 1
    (charged,) = result.lost_ranges
    assert (charged.first_sequence, charged.last_sequence) == (1, 2)
    assert charged.task_id == task_id
    # Nothing under sequence 1 ever landed, so there is no honest watermark.
    assert result.persisted_through is None
    assert health.dropped_count == 2


@pytest.mark.anyio
async def test_a_settle_that_outlives_the_budget_still_reports_durable_rows() -> None:
    """Old-field clamp: spending the budget on projection is not data loss.

    The rows are in storage before the settle wait starts, so the budget
    expiring there leaves a lagging read model and nothing else. ``persisted``
    and ``processed_count`` keep saying so, the reason still names the settle,
    and ``timed_out`` says the call did hit its budget — which is the honest
    reading of both facts at once.
    """

    task_id = new_id()
    backend = _NeverSettlingBackend()
    service = _HeldWriterService(
        backend,
        batch_size=10,
        flush_interval_ms=1,
        terminal_flush_timeout_ms=100,
    )
    await service.start()
    try:
        assert service.record(_observation("settled-late", task_id=task_id)).accepted
        result = await service.flush_task(task_id)
        health = service.get_health()
    finally:
        service.release_writer()
        await service.stop()

    assert result.persisted is True
    assert result.processed_count == 1
    assert result.reason == "projection_settle_timeout"
    assert result.timed_out is True
    assert result.persisted_through == 1
    assert result.lost_ranges == ()
    assert health.dropped_count == 0
    assert backend.landed == ["run:settled-late:task:created"]


@pytest.mark.anyio
async def test_a_barrier_before_start_still_reports_service_not_running() -> None:
    """Old-field clamp: the unstarted path is unchanged, new fields defaulted."""

    service = AnsichService(_RecordingBackend())
    result = await service.flush_task(new_id())

    assert result.persisted is False
    assert result.processed_count == 0
    assert result.reason == "service_not_running"
    assert result.persisted_through is None
    assert result.lost_ranges == ()
    assert result.timed_out is False
