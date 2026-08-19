"""Poison isolation: one unwritable row must not cost its batch-mates.

Batch-level retries answer the question "is storage down?". When they run out
the answer is no — storage is up and something about *this batch* is not
writable — so the writer stops asking about the batch and starts asking about
each row. Every row gets its own ``persist_and_project([obs])`` up to
``writer_item_max_attempts``; the ones storage takes land, and the one it keeps
refusing is charged as a ``poison_observation`` loss at its **collector**
sequence and left behind.

What these tests pin, beyond the counts:

* The neighbours land. That is the whole point — before this, a single
  constraint violation parked its batch indefinitely and the queue behind it
  tail-dropped new work.
* The loss is charged at the collector sequence the accept path allocated, not
  at the producer's own ``producer_seq`` (RA8①). The observations here all
  carry ``producer_seq=1``, so the two numbers can never be confused.
* The lock discipline survives the bisect: each item's attempt is taken under
  ``persist_lock``, every wait gives it back, and a terminal barrier can
  therefore write straight through the middle of an isolation phase.
* Nothing is charged twice and nothing is charged that already landed — the
  in-flight buffer shrinks as rows resolve, and it, not the batch that entered,
  is what a cancellation charges.

No test here sits through a real backoff except where the wait *is* the
fixture: ``_CapturingService`` records the schedule the production code
computed and returns immediately, and ``park_from`` makes one chosen wait real
so a test can act while the writer is held between two per-item attempts.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from ansich import AnsichService, ObservationEnvelope, new_id
from ansich.memory import InMemoryAnsichBackend

_PRODUCER = ("task-control-probe", "local")


def _observation(source_id: str, *, task_id: str | None = None) -> ObservationEnvelope:
    """One lifecycle Observation. ``producer_seq`` stays 1 on purpose (RA8①)."""

    return ObservationEnvelope.task_lifecycle(
        kind="task.created",
        task_id=task_id or new_id(),
        source_kind="deerflow_run",
        source_id=source_id,
        occurred_at=datetime(2026, 8, 19, 12, 0, tzinfo=UTC),
        source_event_id=f"run:{source_id}:task:created",
    )


class _RecordingBackend(InMemoryAnsichBackend):
    """Keeps every write it accepted, and its shape, for the tests to read."""

    def __init__(self) -> None:
        super().__init__()
        self.persisted: list[ObservationEnvelope] = []
        self.write_sizes: list[int] = []

    @property
    def landed(self) -> list[str]:
        """``source_event_id`` of the recorded work, in write order.

        Filtered on purpose: once a loss is charged the collector reports it
        back into the Observation stream as ``observability.degraded``, and that
        write lands here too. It is the collector talking *about* the incident,
        not the work under test.
        """

        return [observation.source_event_id for observation in self.persisted if observation.kind == "task.created"]


class _PoisonRowBackend(_RecordingBackend):
    """Healthy storage that permanently refuses named rows.

    This is the shape a constraint violation takes: the outage is not the
    storage, it is one row, and any write carrying it fails — alone or in
    company. Everything else is stored normally, which is exactly what makes
    "the neighbours landed" a meaningful assertion.
    """

    def __init__(self, *poison_source_event_ids: str) -> None:
        super().__init__()
        self.poison = set(poison_source_event_ids)
        self.refusals = 0

    async def persist_and_project(self, observations: list[ObservationEnvelope]) -> int:
        self.write_sizes.append(len(observations))
        if any(observation.source_event_id in self.poison for observation in observations):
            self.refusals += 1
            raise ValueError("constraint violation on this row")
        count = await super().persist_and_project(observations)
        self.persisted.extend(observations)
        return count


class _TransientOutageBackend(_RecordingBackend):
    """Refuses the first ``failures`` writes whatever they carry, then recovers.

    Sized by its caller so the outage clears *inside* the per-item phase: the
    row that failed on its way there is not poison, it was just early.
    """

    def __init__(self, failures: int) -> None:
        super().__init__()
        self.remaining_failures = failures

    async def persist_and_project(self, observations: list[ObservationEnvelope]) -> int:
        self.write_sizes.append(len(observations))
        if self.remaining_failures > 0:
            self.remaining_failures -= 1
            raise OSError("storage refused the write")
        count = await super().persist_and_project(observations)
        self.persisted.extend(observations)
        return count


class _ListenerFailure(BaseException):
    """Escapes ``_notify_persisted``'s ``except Exception`` on purpose.

    A listener that fails with an ordinary ``Exception`` is swallowed there; to
    reach the writer's own failure path — the one that decides whether to charge
    a batch as lost — the failure has to be one that path actually sees.
    """


class _CapturingService(AnsichService):
    """An ``AnsichService`` whose backoff reports its schedule instead of sleeping.

    Overriding the single sleeping point — and nothing else — keeps the retry
    and isolation paths in production shape: the delays asserted are the ones
    the service computed. ``park_from`` re-arms the real wait from the given
    wait onwards, so a test can hold the writer at a chosen point of the
    per-item phase and act while it is there.
    """

    def __init__(
        self,
        backend: object,
        *,
        park_from: int | None = None,
        **kwargs: object,
    ) -> None:
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
async def test_one_poison_row_in_a_hundred_costs_only_itself(caplog: pytest.LogCaptureFixture) -> None:
    """99 of 100 land; the row storage keeps refusing is charged, and only it.

    Also the RA8① pin: the loss is recorded at collector sequence 43 — the 43rd
    row the accept path allocated — while every one of these observations
    carries ``producer_seq=1``, so a range built from the producer's own counter
    could only ever say 1.
    """

    observations = [_observation(f"run-{index:03d}") for index in range(100)]
    poison = observations[42]
    backend = _PoisonRowBackend(poison.source_event_id)
    service = _CapturingService(backend, batch_size=100, flush_interval_ms=1)
    await service.start()
    try:
        with caplog.at_level(logging.WARNING, logger="ansich.service"):
            receipts = service.record_batch(observations)
            assert all(receipt.accepted for receipt in receipts)
            await _wait_until(lambda: len(backend.landed) == 99)
        health = service.get_health()
    finally:
        await service.stop()

    # One batch, then the bisect: the first write carried all 100 rows.
    assert backend.write_sizes[0] == 100
    assert backend.landed == [observation.source_event_id for observation in observations if observation is not poison]
    assert health.dropped_count == 1
    assert health.writer.poison_observation_count == 1
    assert health.writer.in_flight_count == 0
    (lost,) = health.lost_ranges
    assert (lost.first_sequence, lost.last_sequence) == (43, 43)
    assert lost.task_id == poison.task_id
    assert (lost.producer_name, lost.producer_instance_id) == _PRODUCER
    assert poison.producer_seq == 1

    (warning,) = _drop_warnings(caplog)
    assert warning.levelno == logging.WARNING
    assert warning.reason == "poison_observation"
    assert warning.dropped_observation_count == 1
    assert warning.lost_ranges == (
        {
            "first_sequence": 43,
            "last_sequence": 43,
            "task_id": poison.task_id,
            "producer_name": "task-control-probe",
            "producer_instance_id": "local",
        },
    )
    assert "poison_observation" in warning.getMessage()

    # One schedule, not two: the batch's exponential run, the capped wait that
    # opens the bisect, and the same exponential again for the row's own retry.
    assert service.backoff_delays == pytest.approx([0.1, 0.2, 0.4, 0.8, 5.0, 0.1])


@pytest.mark.anyio
@pytest.mark.parametrize("poison_index", [0, 4], ids=["batch-head", "batch-tail"])
async def test_a_poison_row_at_either_batch_boundary_leaves_the_rest_intact(poison_index: int) -> None:
    """The bisect has no privileged position: first row or last, four survive."""

    observations = [_observation(f"run-boundary-{index}") for index in range(5)]
    poison = observations[poison_index]
    backend = _PoisonRowBackend(poison.source_event_id)
    service = _CapturingService(backend, batch_size=5, flush_interval_ms=1)
    await service.start()
    try:
        assert all(receipt.accepted for receipt in service.record_batch(observations))
        await _wait_until(lambda: len(backend.landed) == 4)
        health = service.get_health()
    finally:
        await service.stop()

    assert backend.write_sizes[0] == 5
    # Survivors keep their batch order; the poison row is simply absent.
    assert backend.landed == [observation.source_event_id for observation in observations if observation is not poison]
    assert health.dropped_count == 1
    assert health.writer.poison_observation_count == 1
    (lost,) = health.lost_ranges
    assert (lost.first_sequence, lost.last_sequence) == (poison_index + 1, poison_index + 1)


@pytest.mark.anyio
async def test_two_poison_rows_cost_two_rows_and_one_warning(caplog: pytest.LogCaptureFixture) -> None:
    """98 of 100 land, both losses are charged, and the flurry is rate-limited.

    ``_warn_batch_loss``'s 60s window is shared with every other drop reason, so
    a batch full of poison reports the first row and counts the rest as
    suppressed rather than emitting one WARNING per row.
    """

    observations = [_observation(f"run-{index:03d}") for index in range(100)]
    first_poison = observations[7]
    second_poison = observations[73]
    backend = _PoisonRowBackend(first_poison.source_event_id, second_poison.source_event_id)
    service = _CapturingService(backend, batch_size=100, flush_interval_ms=1)
    await service.start()
    try:
        with caplog.at_level(logging.WARNING, logger="ansich.service"):
            assert all(receipt.accepted for receipt in service.record_batch(observations))
            await _wait_until(lambda: len(backend.landed) == 98)
        health = service.get_health()
    finally:
        await service.stop()

    assert health.dropped_count == 2
    assert health.writer.poison_observation_count == 2
    assert health.writer.in_flight_count == 0
    assert {(lost.first_sequence, lost.last_sequence) for lost in health.lost_ranges} == {(8, 8), (74, 74)}

    # One record, for the first row inside the window.
    (warning,) = _drop_warnings(caplog)
    assert warning.reason == "poison_observation"
    assert warning.lost_ranges[0]["first_sequence"] == 8
    assert warning.suppressed_drop_warning_count == 0
    # And the second row was *suppressed*, not skipped: the counter it raised is
    # what the next warning inside this window will carry.
    assert service._suppressed_drop_warning_count == 1


@pytest.mark.anyio
async def test_a_transient_that_clears_during_the_bisect_lands_and_is_not_poison() -> None:
    """A row that fails once on its own and then lands was never poison.

    ``writer_item_max_attempts`` is what separates the two: the row is only
    charged after storage has refused *it alone* that many times.
    """

    # Five batch attempts plus the bisect's first per-item attempt, then storage
    # is back — so exactly one row sees a failure it recovers from.
    backend = _TransientOutageBackend(failures=6)
    observations = [_observation(f"run-transient-{index}") for index in range(3)]
    service = _CapturingService(backend, batch_size=3, flush_interval_ms=1)
    await service.start()
    try:
        assert all(receipt.accepted for receipt in service.record_batch(observations))
        await _wait_until(lambda: len(backend.landed) == 3)
        health = service.get_health()
    finally:
        await service.stop()

    assert backend.write_sizes[:6] == [3, 3, 3, 3, 3, 1]
    assert backend.landed == [observation.source_event_id for observation in observations]
    assert health.dropped_count == 0
    assert health.lost_ranges == ()
    assert health.writer.poison_observation_count == 0
    assert health.writer.in_flight_count == 0
    # Nothing left to catch up on, so the collector is not stuck reporting the
    # incident's residue after the last row landed.
    assert health.writer.consecutive_failures == 0
    assert health.status == "healthy"


@pytest.mark.anyio
async def test_the_terminal_barrier_writes_through_a_per_item_isolation_phase() -> None:
    """A poison row must not cost another Task its terminal flush.

    The writer is held between the poison row's two per-item attempts, with a
    1s wait against the barrier's 200ms budget: a barrier that had to queue
    behind the writer's clock could only ever time out. It succeeds because the
    persist lock covers each attempt and never a wait.
    """

    poison_task = new_id()
    terminal_task = new_id()
    poison = _observation("poison", task_id=poison_task)
    companion = _observation("companion")
    backend = _PoisonRowBackend(poison.source_event_id)
    service = _CapturingService(
        backend,
        park_from=6,
        batch_size=2,
        flush_interval_ms=1,
        terminal_flush_timeout_ms=200,
        writer_backoff_initial_ms=1_000,
    )
    await service.start()
    try:
        assert all(receipt.accepted for receipt in service.record_batch([companion, poison]))
        # Wait #6 is the poison row's own retry wait: four batch waits, the
        # capped wait that opened the bisect, and by now the companion row is
        # already durable and this row has failed once by itself.
        await asyncio.wait_for(service.parked.wait(), timeout=10)
        parked = service.get_health()
        writes_before_barrier = len(backend.write_sizes)

        service.record(_observation("terminal", task_id=terminal_task))
        result = await service.flush_task(terminal_task)
        barrier_writes = backend.write_sizes[writes_before_barrier:]

        await _wait_until(lambda: service.get_health().writer.poison_observation_count == 1)
        health = service.get_health()
    finally:
        await service.stop()

    assert result.persisted is True
    assert result.reason is None
    # One real write, taken during the park — not a timeout dressed up as one.
    assert barrier_writes == [1]
    assert terminal_task in {observation.task_id for observation in backend.persisted}
    # And why `poison_observation_count` had to exist: the writer's own failure
    # count says 1, not 6, because the companion row landing between the batch's
    # last refusal and this one zeroed it. During a bisect every neighbour that
    # lands resets that counter, so it cannot name an incident it keeps
    # forgetting — the monotonic poison counter can.
    assert parked.writer.consecutive_failures == 1
    # The batch shrank as the bisect resolved it: one row still parked, not two.
    assert parked.writer.in_flight_count == 1
    assert parked.dropped_count == 0
    assert companion.source_event_id in backend.landed
    assert health.dropped_count == 1
    assert health.writer.poison_observation_count == 1


@pytest.mark.anyio
async def test_rows_queued_behind_an_isolating_batch_land_after_its_survivors() -> None:
    """FIFO holds across the bisect: the batch finishes before the queue moves.

    The writer coroutine resolves one batch to a conclusion before it pops the
    next, so a row recorded while the bisect is running cannot overtake a
    batch-mate that has not been attempted yet.
    """

    observations = [_observation(f"run-fifo-{index}") for index in range(3)]
    poison = observations[1]
    backend = _PoisonRowBackend(poison.source_event_id)
    service = _CapturingService(
        backend,
        park_from=6,
        batch_size=3,
        flush_interval_ms=1,
        writer_backoff_initial_ms=1_000,
    )
    await service.start()
    try:
        assert all(receipt.accepted for receipt in service.record_batch(observations))
        await asyncio.wait_for(service.parked.wait(), timeout=10)
        # The first row of the batch is already durable and the third has not
        # been attempted; these two arrive in between.
        assert backend.landed == [observations[0].source_event_id]
        tail = [_observation(f"run-tail-{index}") for index in range(2)]
        assert all(receipt.accepted for receipt in service.record_batch(tail))

        await _wait_until(lambda: len(backend.landed) == 4)
        health = service.get_health()
    finally:
        await service.stop()

    assert backend.landed == [
        observations[0].source_event_id,
        observations[2].source_event_id,
        tail[0].source_event_id,
        tail[1].source_event_id,
    ]
    assert health.dropped_count == 1
    assert health.writer.poison_observation_count == 1


@pytest.mark.anyio
async def test_a_cancelled_bisect_charges_what_is_still_parked_and_nothing_else() -> None:
    """Cancellation must charge the remainder, not the batch that entered.

    Per-item isolation shrinks the in-flight entry as rows resolve, so by the
    time the writer is cancelled the batch it started with no longer describes
    what it holds: one row is already durable. Charging that list would invent a
    loss for a row that landed.
    """

    observations = [_observation(f"run-cancel-{index}") for index in range(3)]
    poison = observations[1]
    backend = _PoisonRowBackend(poison.source_event_id)
    service = _CapturingService(
        backend,
        park_from=6,
        batch_size=3,
        flush_interval_ms=1,
        writer_backoff_initial_ms=5_000,
    )
    await service.start()
    try:
        assert all(receipt.accepted for receipt in service.record_batch(observations))
        await asyncio.wait_for(service.parked.wait(), timeout=10)
        parked = service.get_health()

        writer_task = service._writer_task
        assert writer_task is not None
        writer_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await writer_task
        health = service.get_health()
    finally:
        with contextlib.suppress(asyncio.CancelledError):
            await service.stop()

    assert backend.landed == [observations[0].source_event_id]
    assert parked.writer.in_flight_count == 2
    # Sequences 2 and 3 — the poison row and the one behind it. Sequence 1 is
    # durable and must not appear.
    assert health.dropped_count == 2
    assert {(lost.first_sequence, lost.last_sequence) for lost in health.lost_ranges} == {(2, 2), (3, 3)}
    assert health.writer.in_flight_count == 0
    # Cancelled before the verdict, so the row was never judged poison.
    assert health.writer.poison_observation_count == 0


@pytest.mark.anyio
async def test_a_listener_raising_after_a_successful_flush_charges_no_phantom_loss() -> None:
    """The write landed; a later failure must not turn it into a loss.

    Persistence listeners run after the batch is durable and after it has been
    released from the in-flight buffer. The writer's failure path charges only
    what is still parked, so a listener blowing up past that point charges
    nothing — the guard exists precisely so a post-success failure cannot invent
    a loss that never happened.
    """

    task_id = new_id()
    backend = _PoisonRowBackend()
    service = _CapturingService(backend, batch_size=1, flush_interval_ms=1)

    def _fail_after_the_write_landed(observation_ids: tuple[str, ...]) -> None:
        raise _ListenerFailure("listener failed after the batch was durable")

    await service.start()
    try:
        service.register_persistence_listener(task_id, _fail_after_the_write_landed)
        service.record(_observation("run-listener", task_id=task_id))
        writer_task = service._writer_task
        assert writer_task is not None
        with pytest.raises(_ListenerFailure):
            await asyncio.wait_for(writer_task, timeout=10)
        health = service.get_health()
    finally:
        with contextlib.suppress(_ListenerFailure):
            await service.stop()
        projector_task = service._projector_task
        if projector_task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.wait_for(projector_task, timeout=10)

    assert backend.landed == ["run:run-listener:task:created"]
    assert health.dropped_count == 0
    assert health.lost_ranges == ()
    assert health.writer.poison_observation_count == 0
    assert health.writer.in_flight_count == 0
