"""What an evaluation receipt is allowed to claim, resolved from state (RA6).

``pending`` is a promise: it says a projection job exists and polling it will
eventually answer. F10-7 pinned the half of that which is about a *rejected*
intake — no Observation, so no job, so never ``pending``. This file owns the
other half, which the receipt used to get from one boolean: it read
``flush_task(...).persisted`` and called anything else ``failed``.

That boolean stopped being the truth under RA5②. A terminal budget running out
is not a refusal — the rows go back to the head of the queue and the writer
places them seconds later — so a receipt built on it reported ``failed`` for an
Observation that was alive and on its way to storage. It also had nothing to say
after a restart, where an accepted ``obs_id`` that is in no queue, no writer's
hands, and no database is not pending anything: it is gone.

The receipt is therefore resolved from the four states an accepted Observation
can be in, in this order:

1. queued, or in a writer's hands -> ``pending`` (it may still land)
2. in the bounded lost-observation set -> ``failed`` (something refused it)
3. durable -> whatever its projection jobs say
4. nowhere at all -> ``failed`` (presumed lost; nothing will ever poll)

The ordering is what makes each rung honest, so most tests here pick a backend
that would answer *differently* on a later rung: an outstanding row is asserted
against storage that reports no job (rung 3 would say ``failed``), and a charged
row against storage with no status reader at all (rung 3 would say ``pending``).

Two tests reach the resolver directly. They say so, and why: the writer's parked
batch and an evicted tracking entry are both states ``record_evaluation``'s own
path cannot be steered into without racing the writer.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from ansich import AnsichService, EvaluationRecord, NamedVersion, ObservationEnvelope, Producer, new_id

_OCCURRED_AT = datetime(2026, 8, 20, 9, tzinfo=UTC)
_ASSESSOR = NamedVersion(name="ansich-benchmark-runner", version="1.0.0")


def _producer() -> Producer:
    return Producer(name="ansich-evaluation-api", version="1", instance_id="gateway")


def _evaluation(task_id: str) -> EvaluationRecord:
    return EvaluationRecord(
        subject_type="task",
        subject_id=task_id,
        task_id=task_id,
        evaluation_kind="benchmark_assertion",
        dimension="correctness",
        verdict="pass",
        assessor=_ASSESSOR,
        fidelity_class="hard",
        suite="ansich-regression",
        suite_version="2026.08.1",
        case_id="case-1",
        run_id="receipt-terminality",
        occurred_at=_OCCURRED_AT,
    )


def _observation(source_id: str, *, task_id: str | None = None) -> ObservationEnvelope:
    return ObservationEnvelope.task_lifecycle(
        kind="task.created",
        task_id=task_id or new_id(),
        source_kind="deerflow_run",
        source_id=source_id,
        occurred_at=_OCCURRED_AT,
        source_event_id=f"run:{source_id}:task:created",
    )


class _AmnesiacBackend:
    """Takes every write and remembers no projection job for any Observation.

    The shape a restarted process presents to a receipt built from an old
    ``obs_id``, and the reason rungs 1 and 2 have to come first: this backend
    answers ``failed`` on rung 3 for *everything*, so a test that expects
    ``pending`` here is asserting that the earlier rung actually decided.
    """

    def __init__(self) -> None:
        self.persisted: list[ObservationEnvelope] = []

    async def persist_and_project(self, observations: list[ObservationEnvelope]) -> int:
        self.persisted.extend(observations)
        return len(observations)

    async def get_observation_projection_status(self, obs_id: str) -> str | None:
        return None


class _ProjectedBackend(_AmnesiacBackend):
    """Takes every write and reports its projection as applied."""

    async def get_observation_projection_status(self, obs_id: str) -> str | None:
        return "applied"


class _RefusingBackend:
    """Never accepts a write. Every read is duck-typed and safely absent.

    Deliberately without ``get_observation_projection_status``: rung 3 cannot
    answer at all here, and an unanswerable rung 3 reports ``pending``. So a
    ``failed`` receipt against this backend can only have come from rung 2.
    """

    def __init__(self) -> None:
        self.attempts = 0

    async def persist_and_project(self, observations: list[ObservationEnvelope]) -> int:
        self.attempts += 1
        raise OSError("storage refused the batch")


class _StalledBackend:
    """A backend whose write cannot answer inside the terminal window.

    The gate lets the test release the pending write at teardown instead of
    leaving a coroutine parked forever.
    """

    def __init__(self) -> None:
        self.released = asyncio.Event()
        self.attempts = 0

    async def persist_and_project(self, observations: list[ObservationEnvelope]) -> int:
        self.attempts += 1
        await self.released.wait()
        return len(observations)


@pytest.mark.anyio
async def test_a_refused_write_reports_failed_rather_than_pending() -> None:
    """F10-7's registration scenario, verbatim: nothing was written, so nothing polls.

    Storage refused the terminal write and the collector charged the row as
    lost, which puts its ``obs_id`` in the tracking set — rung 2. Rung 3 cannot
    answer against this backend, so the receipt would read ``pending`` without
    that rung, which is exactly the promise F10-7 forbids.
    """

    task_id = new_id()
    backend = _RefusingBackend()
    service = AnsichService(backend, flush_interval_ms=60_000, terminal_flush_timeout_ms=10_000)
    await service.start()
    try:
        receipt = await service.record_evaluation(
            _evaluation(task_id),
            source_event_id="evaluation:receipt:refused",
            producer=_producer(),
        )
        health = service.get_health()
    finally:
        await service.stop()

    assert receipt.projection_status == "failed"
    assert receipt.idempotent_replay is False
    # The refusal is a real charge, not an inference: the row is accounted.
    assert health.dropped_count == 1
    assert len(health.lost_ranges) == 1
    assert health.queue_depth == 0
    assert health.writer.in_flight_count == 0


@pytest.mark.anyio
async def test_a_terminal_timeout_reports_pending_because_the_row_is_still_alive() -> None:
    """The T6-conservative case, flipped by RA6.

    The terminal budget closed while the write was in flight. Under RA5② that
    is not a refusal: the selection went back to the head of the queue and the
    writer will place it. The receipt used to read ``flush_task(...).persisted``
    and call that ``failed`` — a row that is queued, and a row that is gone, are
    not the same fact, and only one of them is terminal.
    """

    task_id = new_id()
    backend = _StalledBackend()
    service = AnsichService(
        backend,
        # Long enough that the writer does not pick the returned row up before
        # the assertions read the queue, and short enough that the barrier's own
        # write is still in flight when its budget closes.
        flush_interval_ms=60_000,
        terminal_flush_timeout_ms=50,
    )
    await service.start()
    try:
        receipt = await service.record_evaluation(
            _evaluation(task_id),
            source_event_id="evaluation:receipt:timeout",
            producer=_producer(),
        )
        health = service.get_health()
    finally:
        backend.released.set()
        await service.stop()

    assert backend.attempts >= 1
    assert receipt.projection_status == "pending"
    assert receipt.idempotent_replay is False
    # Nothing refused the write, so nothing is charged: the Observation is in
    # the queue or in the writer's hands, never nowhere.
    assert health.dropped_count == 0
    assert health.lost_ranges == ()
    assert health.queue_depth + health.writer.in_flight_count == 1


@pytest.mark.anyio
async def test_an_accepted_observation_that_is_nowhere_is_presumed_lost() -> None:
    """Rung 4: the write landed as far as this process knows, and storage has no job.

    This is the post-restart shape. The tracking set is process-local and
    bounded, so it cannot be the only evidence of loss: an ``obs_id`` that is in
    no queue, in no writer's hands and in no database has nothing left to poll,
    and reporting ``pending`` for it would be a promise nobody can keep.
    """

    task_id = new_id()
    backend = _AmnesiacBackend()
    service = AnsichService(backend, flush_interval_ms=60_000, terminal_flush_timeout_ms=10_000)
    await service.start()
    try:
        receipt = await service.record_evaluation(
            _evaluation(task_id),
            source_event_id="evaluation:receipt:absent",
            producer=_producer(),
        )
        health = service.get_health()
    finally:
        await service.stop()

    assert receipt.projection_status == "failed"
    assert receipt.idempotent_replay is False
    # Presumption, not accounting: nothing refused this row, so nothing is
    # charged as lost and the collector reports no incident.
    assert health.dropped_count == 0
    assert health.lost_ranges == ()
    assert len(backend.persisted) == 1


@pytest.mark.anyio
async def test_a_durable_observation_reports_the_status_of_its_jobs() -> None:
    """Rung 3 still decides for a row that reached storage."""

    task_id = new_id()
    backend = _ProjectedBackend()
    service = AnsichService(backend, flush_interval_ms=60_000, terminal_flush_timeout_ms=10_000)
    await service.start()
    try:
        receipt = await service.record_evaluation(
            _evaluation(task_id),
            source_event_id="evaluation:receipt:applied",
            producer=_producer(),
        )
    finally:
        await service.stop()

    assert receipt.projection_status == "applied"
    assert receipt.idempotent_replay is False


@pytest.mark.anyio
async def test_an_outstanding_observation_is_never_reported_failed() -> None:
    """Rung 1, both halves, at the rule's own level.

    A queued row is reachable from ``record_evaluation``; a row in the *writer's*
    hands is not, without racing the writer for the moment between its pop and
    its write. Both are the same rung and the same claim — an Observation that
    is still on its way to storage may not be called terminal — so the rule is
    driven directly rather than approximated with a sleep.

    The backend is the amnesiac one on purpose: rung 3 would answer ``failed``
    for both of these rows, so the assertion is about which rung decides.
    """

    backend = _AmnesiacBackend()
    service = AnsichService(backend, flush_interval_ms=60_000)
    queued = _observation("run-queued")
    parked = _observation("run-parked")
    await service.start()
    try:
        assert service.record(queued).accepted
        with service._lock:
            # `barrier=False`: this is the shape the writer's own parked batch
            # has. A barrier's selection is tracked in the same map and answers
            # the same way, which is the point — outstanding is outstanding.
            service._register_in_flight([(99, parked)])

        assert await service._resolve_evaluation_receipt_status(queued.obs_id) == "pending"
        assert await service._resolve_evaluation_receipt_status(parked.obs_id) == "pending"
        # And the same backend, asked about anything it is not holding, is the
        # discriminator: these two answers are rung 1's, not rung 3's.
        assert await service._resolve_evaluation_receipt_status(new_id()) == "failed"
    finally:
        await service.stop()


@pytest.mark.anyio
async def test_the_lost_observation_set_is_bounded_and_eviction_keeps_the_answer() -> None:
    """The tracking set is a bounded FIFO, and losing an entry loses no honesty.

    A process that charged more than ``_LOST_OBSERVATION_ID_LIMIT`` losses must
    not grow a set for the rest of its life, so the oldest entries go. What that
    costs is only *which rung* answers: an evicted row is in no queue and in no
    database either, so rung 4 presumes it lost and the receipt is unchanged.
    """

    from ansich.service import _LOST_OBSERVATION_ID_LIMIT

    backend = _AmnesiacBackend()
    service = AnsichService(backend)
    charged = [_observation(f"run-lost-{index}") for index in range(_LOST_OBSERVATION_ID_LIMIT + 4)]
    with service._lock:
        for sequence, observation in enumerate(charged, start=1):
            service._record_observation_loss(sequence, observation)

    assert len(service._lost_observation_ids) == _LOST_OBSERVATION_ID_LIMIT
    assert charged[0].obs_id not in service._lost_observation_ids
    assert charged[-1].obs_id in service._lost_observation_ids
    # Rung 2 forgot it; rung 4 still refuses to call it pending.
    assert await service._resolve_evaluation_receipt_status(charged[0].obs_id) == "failed"
    assert await service._resolve_evaluation_receipt_status(charged[-1].obs_id) == "failed"
