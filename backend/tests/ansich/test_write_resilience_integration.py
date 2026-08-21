"""The write-resilience batch, driven end to end against real SQLite.

Tasks 1-7 each pinned one mechanism against a backend written to make that
mechanism observable: a backend that refuses exactly ``n`` writes, one that
holds a write open, one that forgets every projection job. That is the right
shape for a unit — a fake is the only way to stand the collector in the state
being described — but every one of those tests is also free to be wrong about
what a *database* does. This file closes that: the same behaviours, composed,
with ``create_sql_ansich_service`` over a real ``sqlite+aiosqlite`` file, and
with the only fake being the fault itself.

**What is injected, and where.** ``_StorageFault`` sits between the backend and
the real ``async_sessionmaker`` and takes the database's *write lock* away.
Everything downstream of it is production: a healthy collector here opens the
real session, writes the real rows, and the assertions read them back through
the real projection. The fault has three shapes because the collector is
required to tell them apart:

* **refusal** — opening a write transaction raises the ``OperationalError``
  SQLite raises when its file is locked. A refusal is an *answer*: the writer
  parks the batch and retries it on its bounded backoff (Task 2), and a
  terminal barrier, which gets a single attempt on the Agent's own call stack,
  charges what it was refused (Task 6).
* **stall** — the write transaction never opens until the fault clears. That is
  what waiting on a held lock looks like from the client side, and it is the
  only shape that can make a terminal barrier's *budget* run out. RA5② says a
  spent budget is not evidence that storage refused anything, so those rows go
  back to the head of the queue and the writer places them after the heal. That
  claim is this batch's headline and it is pinned here, on the real backend.
* **failure after the commit landed** — storage keeps the rows and the
  connection dies on the way out, so the collector charges rows that are
  actually durable. That over-report is the documented direction, and it is the
  only shape that makes the receipt ladder's rung 2 decidable (RA6).

**The accounting audit and its three preconditions.** ``sum(per-producer) ==
global`` is true only under conditions the tests below establish rather than
assert around:

1. *Envelope-only batches.* A non-``ObservationEnvelope`` item is charged
   process-wide and to nobody, because it has no producer identity to charge
   (``_record_batch_loss``). Every batch here is envelopes.
2. *No evicted producers.* The per-producer ledger is an LRU bounded at 256
   (Task 3); an evicted producer takes its counts with it, and
   ``evicted_producer_count`` is what says so. Every test here asserts it is
   zero before auditing.
3. *Accepted + dropped is not the allocated-sequence count across a
   storage_failure.* An Observation accepted at intake and later charged by a
   refused write is counted in **both**, which is the honest reading — intake
   really did accept it and the writer really did lose it — not a
   double-count to be netted out. The audit is therefore scoped to
   ``sum(accepted) == global accepted`` and ``sum(dropped) == global dropped``.
   Where the identity with the allocated sequences does hold, it holds for a
   stated reason and is asserted with that reason attached.

**Timing.** No test here sits through a real backoff or a real poll interval:
the writer knobs are set in milliseconds, and every wait is a bounded
``_wait_for`` on a fact rather than a sleep on a duration. The two places where
ordering has to be exact — the barrier reaching the queue before the writer
does, and the health status sampled at a write boundary — are made exact by
construction and are called out where they happen.
"""

from __future__ import annotations

import asyncio
import contextlib
import sqlite3
import time
from collections import Counter
from collections.abc import AsyncIterator, Callable, Iterable, Iterator
from datetime import UTC, datetime

import pytest
from ansich import AnsichService, EvaluationRecord, NamedVersion, ObservationEnvelope, Producer, new_id
from ansich.contracts import AnsichHealth, LostRange
from ansich.lifecycle import LEGAL_TRANSITIONS
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from support.ansich_settle import only_test_driven_assessments

from deerflow.ansich import create_embedded_ansich_service, create_sql_ansich_service
from deerflow.config.ansich_config import AnsichConfig
from deerflow.persistence.base import Base

_OCCURRED_AT = datetime(2026, 8, 20, 11, 0, tzinfo=UTC)
_ASSESSOR = NamedVersion(name="ansich-benchmark-runner", version="1.0.0")
# Two producer identities so "sum over producers" is a real sum rather than a
# restatement of the process-wide counter.
_PRODUCERS: tuple[tuple[str, str], ...] = (
    ("deerflow-task-control", "worker-a"),
    ("deerflow-tool-probe", "worker-b"),
)


class _StorageFault:
    """A write lock nobody releases, injected at the real session boundary.

    The fault is deliberately **write-scoped**: it fires when a caller opens a
    write transaction (``session.begin()``) and never when a caller only reads.
    That is not a convenience — it is the shape of the outage. SQLite refuses a
    writer while another connection holds the write lock and goes on serving
    readers, and ``SqlAnsichBackend`` splits along exactly that line: every
    write path is ``async with self._session_factory() as session,
    session.begin():`` and every read path is the same ``async with`` without
    the ``begin()``. A fault that also took the reads down would say nothing
    about write resilience — it would just make every assertion unanswerable.

    Three shapes, because the collector is required to tell them apart:

    * :meth:`refuse` — the write transaction raises the ``OperationalError``
      SQLite raises when its file is locked. A refusal is an *answer*.
    * :meth:`stall` — the write transaction never opens until the fault clears.
      That is what waiting on a held lock looks like, and it is the only shape
      that can make a terminal barrier's *budget* run out rather than come back
      refused.
    * :meth:`fail_after_commit` — the write commits and then the connection
      dies on the way out. The collector cannot tell that from a write that
      never happened, so it charges rows storage is actually holding. That is
      the documented direction (``_drain_writer``: a loss claimed that did not
      happen, never a loss that happened and was not claimed), and it is the
      only shape in which the receipt ladder's rung 2 is *decisive* — the row
      is durable, so rung 3 has a real and different answer available.

      **The mechanism is synthetic; the state it produces is not.** The error
      is injected at the connection's ``__aexit__``, after the real session's
      own ``__aexit__`` has already returned — not a sequence ``aiosqlite``
      produces on its own. What it reproduces is the *state* the collector is
      documented to reach honestly by other routes: a write cancelled between
      storage committing and the call returning (``_drain_writer``'s
      cancellation window), or an acknowledgement lost on the way back. Those
      are hard to script and this is not, so the fault stands in for them —
      the rows are genuinely committed to real SQLite either way, which is the
      part the receipt ladder is being asked about.

    Everything downstream of the switch is production. A healed collector opens
    the real session, runs the real statements, and commits real rows.
    """

    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._session_factory = session_factory
        self._mode = "healthy"
        # Set means "the write lock is free". A stalled write waits on it, so
        # healing releases every stalled caller at once, as an unlocked file
        # would.
        self._unlocked = asyncio.Event()
        self._unlocked.set()
        self.refusal_count = 0
        self.stall_count = 0
        self.post_commit_failure_count = 0
        # Refusals attributed to the coroutine that took them. The writer loop
        # and the projector loop are both write paths and both meet the same
        # fault, so a test that wants to count the writer's *configured* budget
        # has to be able to say which refusals were the writer's. The names are
        # the ones `AnsichService.start()` gives its tasks.
        self.refusals_by_task: Counter[str] = Counter()

    def refuse(self) -> None:
        self._mode = "refuse"
        self._unlocked.set()

    def stall(self) -> None:
        self._mode = "stall"
        self._unlocked.clear()

    def fail_after_commit(self) -> None:
        self._mode = "fail_after_commit"
        self._unlocked.set()

    def heal(self) -> None:
        self._mode = "healthy"
        self._unlocked.set()

    async def enter_write(self) -> None:
        """Whatever the armed fault does to a caller opening a write."""

        if self._mode == "refuse":
            self.refusal_count += 1
            current = asyncio.current_task()
            self.refusals_by_task[current.get_name() if current is not None else "unknown"] += 1
            raise OperationalError(
                "BEGIN IMMEDIATE",
                {},
                sqlite3.OperationalError("database is locked"),
            )
        if self._mode == "stall":
            self.stall_count += 1
            await self._unlocked.wait()

    def __call__(self) -> _FaultyConnection:
        return _FaultyConnection(self)


class _FaultyConnection:
    """The ``async_sessionmaker()`` call's result, handing back a guarded session.

    Also where ``fail_after_commit`` lands: the session closes normally — the
    commit inside it has already happened — and only then does the connection
    report itself broken, which is the one ordering that leaves storage holding
    rows the collector believes it lost.
    """

    def __init__(self, fault: _StorageFault) -> None:
        self._fault = fault
        self._session = None
        self._wrote = False

    async def __aenter__(self) -> _FaultySession:
        self._session = self._fault._session_factory()
        return _FaultySession(self._fault, await self._session.__aenter__(), self)

    async def __aexit__(self, *exc_info):
        assert self._session is not None
        suppressed = await self._session.__aexit__(*exc_info)
        if self._wrote and self._fault._mode == "fail_after_commit" and exc_info[0] is None:
            self._fault.post_commit_failure_count += 1
            raise OperationalError(
                "COMMIT",
                {},
                sqlite3.OperationalError("disk I/O error"),
            )
        return suppressed


class _FaultySession:
    """The real ``AsyncSession`` with its ``begin()`` behind the fault.

    Everything else is delegated untouched, so reads run against real SQLite
    even while writes are locked out.
    """

    def __init__(self, fault: _StorageFault, session, connection: _FaultyConnection) -> None:
        self._fault = fault
        self._session = session
        self._connection = connection

    def begin(self) -> _FaultyWriteTransaction:
        self._connection._wrote = True
        return _FaultyWriteTransaction(self._fault, self._session)

    def __getattr__(self, name: str):
        return getattr(self._session, name)


class _FaultyWriteTransaction:
    """One write transaction, opened only once the fault lets it."""

    def __init__(self, fault: _StorageFault, session) -> None:
        self._fault = fault
        self._session = session
        self._transaction = None

    async def __aenter__(self):
        await self._fault.enter_write()
        self._transaction = self._session.begin()
        return await self._transaction.__aenter__()

    async def __aexit__(self, *exc_info):
        if self._transaction is None:
            return False
        return await self._transaction.__aexit__(*exc_info)


class _StatusTrail:
    """Every lifecycle status this collector has been *seen* in, in order.

    Consecutive repeats are collapsed, so the trail is the sequence of
    transitions rather than a sampling artefact. Sampled from two places: the
    test's own bounded waits, and — through
    ``AnsichService.register_persistence_listener`` — the moment a batch
    reaches storage. The second one is what makes ``recovering`` deterministic
    instead of lucky: the listener fires inside ``_attempt_persist``, *after*
    ``_record_write_success`` has cleared the failure count and decided whether
    the writer has caught up, so it reads exactly the state a successful write
    left behind.
    """

    def __init__(self, service: AnsichService) -> None:
        self._service = service
        self.statuses: list[str] = []

    def sample(self) -> str:
        status = self._service.get_health().status
        if not self.statuses or self.statuses[-1] != status:
            self.statuses.append(status)
        return status

    def on_persisted(self, observation_ids: tuple[str, ...]) -> None:
        self.sample()

    def illegal_transitions(self) -> list[tuple[str, str]]:
        return [(before, after) for before, after in zip(self.statuses, self.statuses[1:], strict=False) if (before, after) not in LEGAL_TRANSITIONS]


def _lifecycle(task_id: str) -> ObservationEnvelope:
    producer_name, producer_instance_id = _PRODUCERS[0]
    return ObservationEnvelope.task_lifecycle(
        kind="task.created",
        task_id=task_id,
        source_kind="deerflow_run",
        source_id=task_id,
        occurred_at=_OCCURRED_AT,
        source_event_id=f"run:{task_id}:task:created",
        producer_name=producer_name,
        producer_version="1",
        producer_instance_id=producer_instance_id,
    )


def _consumption(task_id: str, index: int) -> ObservationEnvelope:
    """One repeatable, projectable Observation attributed to a rotating producer."""

    producer_name, producer_instance_id = _PRODUCERS[index % len(_PRODUCERS)]
    return ObservationEnvelope.budget_consumed(
        task_id=task_id,
        run_id=task_id,
        occurred_at=_OCCURRED_AT,
        dimension="total_tokens",
        delta=1,
        source_event_id=f"run:{task_id}:budget:total_tokens:{index}",
        producer_seq=index + 1,
        producer_name=producer_name,
        producer_version="1",
        producer_instance_id=producer_instance_id,
    )


def _workload(task_id: str, count: int) -> list[ObservationEnvelope]:
    """A Task creation followed by ``count - 1`` consumptions across producers."""

    return [_lifecycle(task_id)] + [_consumption(task_id, index) for index in range(1, count)]


def _evaluation(task_id: str, *, case_id: str) -> EvaluationRecord:
    return EvaluationRecord(
        subject_type="task",
        subject_id=task_id,
        task_id=task_id,
        evaluation_kind="benchmark_assertion",
        dimension="correctness",
        verdict="pass",
        assessor=_ASSESSOR,
        fidelity_class="hard",
        suite="ansich-write-resilience",
        suite_version="2026.08.1",
        case_id=case_id,
        run_id="write-resilience-integration",
        occurred_at=_OCCURRED_AT,
    )


async def _wait_for(
    description: str,
    predicate: Callable[[], bool],
    *,
    timeout: float = 15.0,
    sample: Callable[[], object] | None = None,
) -> None:
    """Wait on a fact, not on a duration; fail loudly rather than hang the suite."""

    deadline = time.monotonic() + timeout
    while True:
        if sample is not None:
            sample()
        if predicate():
            return
        assert time.monotonic() < deadline, f"timed out after {timeout}s waiting for {description}"
        await asyncio.sleep(0.005)


def _assert_producer_accounting_balances(health: AnsichHealth) -> None:
    """The audit, with its two structural preconditions asserted first.

    Condition 1 (envelope-only batches) is a property of the workloads in this
    file rather than of the health snapshot, so it is stated in the module
    docstring and upheld by construction. Condition 2 is checkable here and is
    checked: an evicted producer took its counts with it, and a sum that
    ignored that would be quietly wrong rather than loudly.

    Condition 3 — that ``accepted + dropped`` need not equal the number of
    allocated sequences — is why this function deliberately does *not* compare
    against ``_record_sequence``. A row accepted at intake and later charged by
    a refused write is honestly in both totals.
    """

    assert health.evicted_producer_count == 0, "the audit is only valid while no producer account has been evicted"
    assert sum(producer.accepted_count for producer in health.producers) == health.accepted_count
    assert sum(producer.dropped_count for producer in health.producers) == health.dropped_count


@contextlib.contextmanager
def _terminal_budget(service: AnsichService, milliseconds: int) -> Iterator[None]:
    """Shrink the terminal barrier's budget for the span of one call.

    ``terminal_flush_timeout_ms`` is startup-only configuration and rightly so,
    but a test that wants to watch the budget actually run out cannot wait the
    production number out — and must not leave the *closing* flush living under
    the tiny one, because that call has a read model to settle rather than a
    lock to wait on and would time out for a reason this file is not about.
    """

    original = service._terminal_flush_timeout_seconds
    service._terminal_flush_timeout_seconds = milliseconds / 1000
    try:
        yield
    finally:
        service._terminal_flush_timeout_seconds = original


def _charged_sequences(lost_ranges: Iterable[LostRange]) -> list[int]:
    """Flatten charged ranges, asserting they are disjoint and ascending."""

    ranges = list(lost_ranges)
    sequences: list[int] = []
    for lost_range in ranges:
        assert lost_range.first_sequence <= lost_range.last_sequence
        assert not sequences or lost_range.first_sequence > sequences[-1], "lost ranges must be disjoint and ascending"
        sequences.extend(range(lost_range.first_sequence, lost_range.last_sequence + 1))
    return sequences


@contextlib.asynccontextmanager
async def _collector(tmp_path, name: str, **overrides) -> AsyncIterator[tuple[AnsichService, _StorageFault]]:
    """A started ``create_sql_ansich_service`` over a real SQLite file, plus its fault.

    The knobs default to a fast, small collector: batches of five so a backlog
    is a handful of writes rather than one, and millisecond backoff so a
    bounded retry is bounded in test time too. ``writer_retry_max_attempts`` is
    deliberately generous — these tests decide when an outage ends, and a batch
    that ran out of attempts while the test was still setting up would turn a
    scripted incident into an unscripted one.
    """

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / name}.db")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    fault = _StorageFault(async_sessionmaker(engine, expire_on_commit=False))
    settings: dict[str, object] = {
        "batch_size": 5,
        "flush_interval_ms": 20,
        "projector_poll_interval_ms": 10,
        "terminal_flush_timeout_ms": 10_000,
        "writer_retry_max_attempts": 10_000,
        "writer_backoff_initial_ms": 1,
        "writer_backoff_max_ms": 5,
        "writer_item_max_attempts": 2,
        "stop_drain_timeout_ms": 5_000,
    }
    settings.update(overrides)
    service = create_sql_ansich_service(fault, **settings)  # type: ignore[arg-type]
    only_test_driven_assessments(service)
    await service.start()
    body_failed = False
    try:
        yield service, fault
    except BaseException:
        body_failed = True
        raise
    finally:
        # Always healed before the drain: a stalled backend would spend the
        # whole stop budget and charge loss the test never asked for, turning
        # every teardown into a second, silent scenario.
        fault.heal()
        try:
            await service.stop()
        except Exception:
            # A stop that raises against a healed backend is a finding about
            # the drain, not teardown noise, so it is re-raised. The one case
            # it is swallowed in is a test body that already failed: there the
            # stop failure is a consequence, and letting it replace the real
            # diagnosis would hide the thing worth reading.
            if not body_failed:
                raise
        finally:
            await engine.dispose()


@pytest.mark.anyio
async def test_transient_outage_loses_nothing_and_walks_back_to_healthy(tmp_path) -> None:
    """A refused-write outage that heals costs zero rows and ends healthy.

    The composition Tasks 2, 3 and 6 each own a piece of: the writer parks and
    retries across the outage instead of charging it, the per-producer ledger
    stays balanced against the process-wide one, and the lifecycle walks
    ``healthy -> degraded -> recovering -> healthy`` — the ``recovering`` rung
    read at a write boundary rather than sampled hopefully, and every edge
    checked against ``LEGAL_TRANSITIONS``.

    Zero loss is what makes the walk reachable at all: ``dropped_count`` is
    permanent ``degraded``, so a single charged row would pin this collector in
    degradation for the rest of its life and no heal could argue it out.
    """

    task_id = new_id()
    observations = _workload(task_id, 60)
    async with _collector(tmp_path, "transient-outage") as (service, fault):
        trail = _StatusTrail(service)
        service.register_persistence_listener(task_id, trail.on_persisted)
        assert trail.sample() == "healthy"

        fault.refuse()
        receipts = service.record_batch(tuple(observations))
        assert all(receipt.accepted for receipt in receipts)

        await _wait_for(
            "the writer to report the outage",
            lambda: service.get_health().writer.consecutive_failures > 0,
            sample=trail.sample,
        )
        assert trail.sample() == "degraded"
        # The batch is parked, not charged: a refusal costs the writer its
        # attempt, never its rows.
        assert service.get_health().writer.in_flight_count == 5
        assert service.get_health().dropped_count == 0

        fault.heal()
        await _wait_for(
            "the writer to drain the backlog the outage left",
            lambda: service.get_health().queue_depth == 0 and service.get_health().writer.in_flight_count == 0,
            sample=trail.sample,
        )
        await _wait_for(
            "the collector to report itself healthy again",
            lambda: service.get_health().status == "healthy",
            sample=trail.sample,
        )

        health = service.get_health()
        settled = await service.flush_task(task_id)
        stored = await service.list_observations(task_id)

    assert fault.refusal_count > 0, "the outage never actually refused a write"
    # Nothing lost, nothing poisoned, nothing left unreported.
    assert health.dropped_count == 0
    assert health.lost_ranges == ()
    assert health.loss_detected is False
    assert health.unreported_global_lost_range_count == 0
    assert health.writer.poison_observation_count == 0
    assert health.failed_jobs == 0
    assert health.accepted_count == len(observations)

    # Durable and complete, read back through the real backend.
    assert {observation.obs_id for observation in stored} == {observation.obs_id for observation in observations}
    task = await service.get_task(task_id)
    assert task is not None
    # Projected, not merely stored: the Task row only exists because the
    # projector replayed the lifecycle Observation the outage delayed.
    assert task.task_id == task_id
    # `persisted_through` is contiguous: every sequence the accept path handed
    # out is durable, so the barrier can name the last of them.
    assert settled.persisted_through == len(observations)
    assert settled.timed_out is False

    # The walk, edge for edge.
    assert trail.illegal_transitions() == []
    assert trail.statuses == ["healthy", "degraded", "recovering", "healthy"]

    _assert_producer_accounting_balances(health)
    accepted_by_producer = {(producer.producer_name, producer.producer_instance_id): producer.accepted_count for producer in health.producers}
    assert set(accepted_by_producer) == set(_PRODUCERS)
    # Every producer's work reached storage, which is the only thing that
    # stamps this field.
    assert all(producer.last_successful_flush_at is not None for producer in health.producers)
    assert all(producer.dropped_count == 0 for producer in health.producers)
    assert all(producer.serialization_failures == 0 for producer in health.producers)


@pytest.mark.anyio
async def test_capacity_tail_drop_under_outage_charges_a_coherent_range(tmp_path) -> None:
    """A queue that fills while storage is out drops the tail, and says so exactly.

    The writer holds one batch parked against the refusing backend, which is
    what stops it draining the queue behind it; intake then fills the remaining
    capacity and rejects the rest. The rejections are the only loss in this
    scenario, and that is what makes the strong identity available: nothing was
    charged *after* being accepted, so ``accepted + dropped`` is exactly the
    number of sequences the accept path handed out. Precondition 3 of the audit
    is therefore satisfied rather than assumed — and it is asserted with that
    reason attached, so a future change that starts charging accepted rows here
    fails this line instead of silently invalidating it.
    """

    task_id = new_id()
    capacity = 20
    async with _collector(tmp_path, "tail-drop", queue_capacity=capacity) as (service, fault):
        fault.refuse()
        parked_observations = _workload(task_id, 5)
        parked = service.record_batch(tuple(parked_observations))
        assert all(receipt.accepted for receipt in parked)
        await _wait_for(
            "the writer to park the first batch against the refusing backend",
            lambda: service.get_health().writer.in_flight_count == 5,
        )

        # From here the writer is committed to the batch it holds — a parked
        # batch is resolved before the next one is popped — so the queue below
        # it fills and then overflows, with no await to let anything drain it.
        accepted: list[ObservationEnvelope] = []
        rejected: list[ObservationEnvelope] = []
        for index in range(5, 5 + capacity + 5):
            observation = _consumption(task_id, index)
            receipt = service.record(observation)
            if receipt.accepted:
                accepted.append(observation)
            else:
                assert receipt.reason == "queue_full"
                rejected.append(observation)

        health = service.get_health()
        # An evaluation submitted into a full queue is refused at intake, so it
        # is never made durable and its receipt cannot promise a projection.
        refused_receipt = await service.record_evaluation(
            _evaluation(task_id, case_id="into-a-full-queue"),
            source_event_id="write-resilience:full-queue",
            producer=Producer(name="ansich-evaluation-api", version="1", instance_id="gateway"),
        )

        fault.heal()
        await _wait_for(
            "the collector to place everything it did accept",
            lambda: service.get_health().queue_depth == 0 and service.get_health().writer.in_flight_count == 0,
        )
        healed = service.get_health()
        stored = await service.list_observations(task_id)

    assert fault.refusal_count > 0
    assert len(accepted) == capacity
    assert len(rejected) == 5
    assert refused_receipt.projection_status == "failed"
    assert refused_receipt.idempotent_replay is False

    # Loss is charged, permanent, and Task-scoped rather than global.
    assert health.dropped_count == 5
    assert health.loss_detected is True
    assert health.unreported_global_lost_range_count == 0
    assert health.writer.poison_observation_count == 0

    # Collector-sequence contiguity: the charged sequences are exactly the tail
    # the accept path allocated, in one unbroken run, and each range names the
    # producer whose row occupied that sequence.
    allocated_before_evaluation = 5 + capacity + 5
    assert _charged_sequences(health.lost_ranges) == list(range(allocated_before_evaluation - 4, allocated_before_evaluation + 1))
    assert all(lost_range.task_id == task_id for lost_range in health.lost_ranges)
    charged_producers = [(lost_range.producer_name, lost_range.producer_instance_id) for lost_range in health.lost_ranges for _ in range(lost_range.first_sequence, lost_range.last_sequence + 1)]
    assert charged_producers == [(observation.producer.name, observation.producer.instance_id) for observation in rejected]

    _assert_producer_accounting_balances(health)
    # Precondition 3, satisfied here for a stated reason: every charge in this
    # scenario happened *at* intake, so no sequence is counted twice.
    assert health.accepted_count + health.dropped_count == allocated_before_evaluation

    # The heal places what was accepted and leaves the loss where it was: a
    # drained queue never argues a charged range back. The one addition is the
    # evaluation the full queue refused — charged at its own sequence, above
    # the tail, and attributed to the API that submitted it.
    assert healed.dropped_count == 6
    assert _charged_sequences(healed.lost_ranges) == list(range(allocated_before_evaluation - 4, allocated_before_evaluation + 2))
    assert healed.lost_ranges[:-1] == health.lost_ranges
    assert healed.lost_ranges[-1].first_sequence == allocated_before_evaluation + 1
    assert healed.lost_ranges[-1].producer_name == "ansich-evaluation-api"
    accepted_ids = {observation.obs_id for observation in parked_observations + accepted}
    stored_ids = {observation.obs_id for observation in stored}
    assert accepted_ids <= stored_ids
    # ...and the loss is reported back into the Observation stream once storage
    # can take it (RA8②: these ranges have a Task, so they have a subject).
    assert {observation.kind for observation in stored if observation.obs_id not in accepted_ids} == {"observability.degraded"}


@pytest.mark.anyio
async def test_evaluation_receipt_reads_failed_for_a_row_the_barrier_could_not_place(tmp_path) -> None:
    """RA6 rung 2 on the real path, and decisively rather than by agreement.

    Two things have to be true for this to be a test of rung 2 rather than of
    the rungs around it.

    *Not the intake short-circuit.* A rejected ``record`` returns ``failed``
    without consulting the ladder at all, so the Observation has to have been
    genuinely accepted first — ``accepted_count`` is the public witness.

    *Not rung 4 wearing rung 2's answer.* For a row that never reached storage,
    "charged" and "absent everywhere" agree, and a test built on one is
    silently a test of the other. So the fault here is the one shape where they
    disagree: storage **commits** the batch and then the connection dies on the
    way out. The collector cannot tell that from a write that never happened
    and charges the row — the deliberate over-report direction — while storage
    is holding it. Rung 3 therefore has a real answer available, and ``failed``
    can only have come from rung 2.
    """

    task_id = new_id()
    async with _collector(tmp_path, "receipt-rung-two") as (service, fault):
        fault.fail_after_commit()
        receipt = await service.record_evaluation(
            _evaluation(task_id, case_id="charged-after-the-commit-landed"),
            source_event_id="write-resilience:barrier-charge",
            producer=Producer(name="ansich-evaluation-api", version="1", instance_id="gateway"),
        )
        health = service.get_health()
        fault.heal()
        # Read back through the real backend: the row the collector charged is
        # in the database, which is what makes rung 3 a live alternative.
        durable = await service.get_evaluation_observation_payload(receipt.observation_id)

    assert fault.post_commit_failure_count > 0
    assert receipt.projection_status == "failed"
    assert receipt.idempotent_replay is False
    assert durable is not None
    # Rung 2, not the intake short-circuit: intake accepted this row before
    # anything charged it.
    assert health.accepted_count == 1
    assert health.dropped_count == 1
    assert _charged_sequences(health.lost_ranges) == [1]
    assert health.lost_ranges[0].task_id == task_id
    assert health.lost_ranges[0].producer_name == "ansich-evaluation-api"
    _assert_producer_accounting_balances(health)


@pytest.mark.anyio
async def test_barrier_timeout_under_a_stalled_backend_returns_rows_instead_of_losing_them(tmp_path) -> None:
    """The batch's headline claim, on the real backend.

    ``flush_task`` takes a prefix of the queue, is left waiting by a backend
    that will not answer, and spends its budget. RA5②: a spent budget is not a
    refusal, so it reports ``timed_out`` honestly, charges nothing, and puts
    the rows back at the head of the queue — where the writer places them once
    the stall clears.

    **Why the ordering is exact and not lucky.** ``record_batch`` wakes the
    writer through ``loop.call_soon_threadsafe``, so the wake cannot run before
    the test yields; ``flush_task`` is awaited with no suspension point in
    between, and its own first suspension is inside the stalled write — by
    which time it already holds ``persist_lock`` and has taken the rows. The
    writer therefore finds the lock held and waits, which is precisely the
    contention this test wants.

    The long ``flush_interval_ms`` is part of that: at the collector default
    the writer also wakes on its **own** timer, and a writer that took the
    batch first would leave the barrier merely waiting on a lock — taking
    nothing, returning nothing, and passing every assertion below for the wrong
    reason. The strict queue-depth assertion after the timeout is what pins
    which of the two actually held the rows.
    """

    task_id = new_id()
    observations = _workload(task_id, 12)
    async with _collector(tmp_path, "barrier-stall", flush_interval_ms=30_000) as (service, fault):
        await _wait_for("the collector to reach its first idle", lambda: service.get_health().status == "healthy")

        fault.stall()
        receipts = service.record_batch(tuple(observations))
        assert all(receipt.accepted for receipt in receipts)
        with _terminal_budget(service, 150):
            timed_out = await service.flush_task(task_id)

        health_at_timeout = service.get_health()
        assert timed_out.timed_out is True
        assert timed_out.persisted is False
        assert timed_out.reason == "terminal_flush_timeout"
        assert timed_out.processed_count == 0
        # Nothing charged, so nothing to report to the caller either.
        assert timed_out.lost_ranges == ()
        # Nothing durable underneath them yet, so there is no contiguous
        # watermark to name.
        assert timed_out.persisted_through is None
        assert health_at_timeout.dropped_count == 0
        # Every row is back in the queue and nothing is outstanding. Strict, and
        # deliberately so: this is what says the *barrier* took the rows and
        # gave them back. A writer that had taken a batch first would leave the
        # barrier holding only the remainder, and the two numbers would split.
        # The read is deterministic — releasing `persist_lock` only *schedules*
        # the waiting writer, and `flush_task` returns to this task without
        # yielding to the loop in between.
        assert health_at_timeout.queue_depth == len(observations)
        assert health_at_timeout.writer.in_flight_count == 0
        assert fault.stall_count > 0

        fault.heal()
        await _wait_for(
            "the writer to place what the barrier had to give back",
            lambda: service.get_health().queue_depth == 0 and service.get_health().writer.in_flight_count == 0,
        )
        settled = await service.flush_task(task_id)
        health = service.get_health()
        stored = await service.list_observations(task_id)

    # Zero loss across the whole incident.
    assert health.dropped_count == 0
    assert health.lost_ranges == ()
    assert health.writer.poison_observation_count == 0
    assert health.accepted_count == len(observations)
    assert {observation.obs_id for observation in stored} == {observation.obs_id for observation in observations}
    assert settled.persisted_through == len(observations)
    assert settled.timed_out is False
    _assert_producer_accounting_balances(health)


@pytest.mark.anyio
async def test_a_stalled_barrier_returns_its_rows_to_the_queue_head_not_the_tail(tmp_path) -> None:
    """The other half of RA5②: the returned rows go back *where they came from*.

    A spent budget puts the barrier's selection back at the **head** of the
    queue, below everything recorded while it was holding them. That is what
    keeps the collector sequence authoritative after an incident — and it only
    means anything if there is something in the queue for the rows to be below.
    Rows recorded *after* the return sort above them whether the return
    prepends or appends, so a test that records them afterwards is green
    against both and pins nothing. (An earlier version of this test did exactly
    that, and stayed green under a deliberate append-to-tail mutant.)

    The trailing rows therefore arrive **during the hold**. ``record_batch`` is
    a synchronous, thread-safe call by design, so the test schedules it on the
    loop with ``call_soon`` and then awaits the barrier inline: the barrier
    reaches its stall without ever yielding, so the callback can only run once
    the rows are already taken and ``persist_lock`` is already held. Nothing
    here depends on the writer's state — it can take nothing while the barrier
    holds the lock — which is what makes the setup deterministic rather than a
    race against loop startup. The state captured inside that callback is
    asserted below, so a hold that did not happen fails loudly instead of
    quietly making the ordering claim vacuous again.

    Read back through the real backend, ``list_observations`` is ordered by
    ``ingest_seq`` — the order storage accepted the rows in — so a return that
    appended shows up as a reordered replay rather than as a lost row.
    """

    task_id = new_id()
    observations = _workload(task_id, 9)
    held, trailing = observations[:6], observations[6:]
    # The long interval only keeps the writer quiet during the hold; it is not
    # load-bearing here, because the barrier takes the queue before the writer
    # can run at all.
    async with _collector(tmp_path, "barrier-order", flush_interval_ms=30_000) as (service, fault):
        during_hold: list[tuple[bool, AnsichHealth]] = []

        def record_trailing_rows() -> None:
            receipts = service.record_batch(tuple(trailing))
            # Captured rather than asserted: this runs as a loop callback, so a
            # failure here would be swallowed by the loop's exception handler
            # instead of failing the test.
            during_hold.append((all(receipt.accepted for receipt in receipts), service.get_health()))

        fault.stall()
        service.record_batch(tuple(held))
        asyncio.get_running_loop().call_soon(record_trailing_rows)
        with _terminal_budget(service, 250):
            timed_out = await service.flush_task(task_id)

        assert timed_out.timed_out is True
        assert timed_out.lost_ranges == ()
        # The precondition the ordering claim rests on: while the barrier held
        # its selection, the trailing rows were the whole of the queue — so the
        # return had something it could be placed either above or below.
        assert len(during_hold) == 1
        accepted, held_state = during_hold[0]
        assert accepted
        assert held_state.queue_depth == len(trailing)
        assert held_state.writer.in_flight_count == len(held)

        returned = service.get_health()
        assert returned.dropped_count == 0
        # Everything back in the queue, nothing outstanding: the barrier gave
        # back exactly what it took. Which *end* it gave them back to is what
        # the stored order below answers.
        assert returned.queue_depth == len(observations)
        assert returned.writer.in_flight_count == 0

        fault.heal()
        await _wait_for(
            "the whole workload to reach storage",
            lambda: service.get_health().queue_depth == 0 and service.get_health().writer.in_flight_count == 0,
        )
        settled = await service.flush_task(task_id)
        health = service.get_health()
        stored = await service.list_observations(task_id)

    assert health.dropped_count == 0
    assert settled.persisted_through == len(observations)
    # Storage accepted them in the order the accept path allocated: the six the
    # barrier gave back first, then the three recorded while it held them.
    assert [observation.obs_id for observation in stored] == [observation.obs_id for observation in observations]


@pytest.mark.anyio
async def test_writer_resilience_config_reaches_the_service_and_the_backend(tmp_path) -> None:
    """Every knob the operator can set arrives where it is read.

    Reflection rather than behaviour on purpose: what this pins is the
    *threading*, and a behavioural assertion would only cover the knobs whose
    effect is cheap to provoke. All five writer knobs carry non-default values,
    and pre-existing knobs on both sides of the assembly — service and backend —
    ride along as controls, so a factory that dropped its ``**config`` on the
    floor fails here rather than in whichever scenario happened to depend on it.

    **What this adds over
    ``test_ansich_config.py::test_writer_resilience_settings_reach_the_service_on_both_assembly_paths``**,
    which is not superseded and should not be deleted for this one: that test
    owns the five writer knobs across *both* embedded branches, including the
    ``session_factory is None`` one this file never builds. This test owns the
    three things it does not — the twelve pre-existing control knobs, the
    **backend** half of the assembly (nothing over there is asserted anywhere
    else), and the derived backoff schedule, which is what catches a threading
    bug that swapped the initial/max pair while both field reads still passed.

    The asymmetry this test used to name as open is closed (F10-27): the
    ``session_factory is None`` branch dropped ``terminal_flush_timeout_ms``,
    ``projector_poll_interval_ms`` and ``operations_assessment_interval_ms``
    because it spelled its own argument list. Both branches now splat the one
    ``service_knobs_from_config`` mapping, and
    ``tests/ansich/test_ansich_config.py`` pins that the mapping covers every
    keyword ``AnsichService.__init__`` takes.
    """

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'config-threading'}.db")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    config = AnsichConfig(
        enabled=True,
        # -- the batch's five new knobs, all non-default ---------------------
        writer_retry_max_attempts=7,
        writer_backoff_initial_ms=13,
        writer_backoff_max_ms=1_700,
        writer_item_max_attempts=3,
        stop_drain_timeout_ms=4_250,
        # -- controls: pre-existing knobs on the service side ----------------
        queue_capacity=321,
        queue_byte_capacity=1_234_567,
        batch_size=17,
        flush_interval_ms=44,
        terminal_flush_timeout_ms=3_300,
        projector_poll_interval_ms=125,
        operations_assessment_interval_ms=61_000,
        health_database_timeout_ms=1_750,
        # -- controls: pre-existing knobs on the backend side ---------------
        projector_lease_seconds=41,
        projector_max_attempts=9,
        projector_dependency_timeout_seconds=222,
        inline_payload_max_bytes=4_096,
        heartbeat_interval_seconds=11,
        heartbeat_stale_after_seconds=55,
        long_dwell_seconds=99,
        environment_sample_interval_seconds=7,
        assessors={
            "exact_repetition_window": 8,
            "tool_frequency_window_seconds": 66,
            "tool_frequency_threshold": 21,
            "environment_leak_min_samples": 4,
        },
    )

    service = create_embedded_ansich_service(config, session_factory)
    try:
        assert service is not None
        # The five.
        assert service._writer_retry_max_attempts == 7
        assert service._writer_backoff_initial_ms == 13
        assert service._writer_backoff_max_ms == 1_700
        assert service._writer_item_max_attempts == 3
        assert service._stop_drain_timeout_seconds == 4.25
        # Service-side controls.
        assert service._capacity == 321
        assert service._byte_capacity == 1_234_567
        assert service._batch_size == 17
        assert service._flush_interval_seconds == 0.044
        assert service._terminal_flush_timeout_seconds == 3.3
        assert service._projector_poll_interval_seconds == 0.125
        assert service._operations_assessment_interval_seconds == 61.0
        assert service._health_database_timeout_seconds == 1.75
        # Backend-side controls.
        backend = service._backend
        assert backend._projector_lease_seconds == 41
        assert backend._projector_max_attempts == 9
        assert backend._projector_dependency_timeout.total_seconds() == 222
        assert backend._inline_payload_max_bytes == 4_096
        assert backend._heartbeat_stale_after_seconds == 55
        assert backend._long_dwell_seconds == 99
        assert backend._exact_repetition_window == 8
        assert backend._tool_frequency_window_seconds == 66
        assert backend._tool_frequency_threshold == 21
        assert backend._environment_sample_interval_seconds == 7
        assert backend._environment_thresholds.leak_min_samples == 4
        # The knobs the writer path derives rather than reads: the backoff
        # schedule is a function of the two it was given, so a threading bug
        # that swapped them would still pass the field reads above.
        assert service._backoff_delay_seconds(1) == 0.013
        assert service._backoff_delay_seconds(None) == 1.7
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_direct_sql_factory_threads_the_same_knobs_from_its_kwargs(tmp_path) -> None:
    """The other assembly path. Same knobs, same destinations, no config object.

    ``create_sql_ansich_service`` is what the SQL suite and every direct caller
    use, so its kwargs are a public surface of their own rather than an
    implementation detail of ``create_embedded_ansich_service``. Its patient
    ``terminal_flush_timeout_ms`` default is the one place the two paths
    genuinely differ, and it is deliberate (see that factory's comment).
    """

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'direct-threading'}.db")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    service = create_sql_ansich_service(
        session_factory,
        queue_capacity=123,
        queue_byte_capacity=456_789,
        batch_size=6,
        flush_interval_ms=33,
        terminal_flush_timeout_ms=2_750,
        projector_poll_interval_ms=175,
        operations_assessment_interval_ms=2_500,
        writer_retry_max_attempts=4,
        writer_backoff_initial_ms=19,
        writer_backoff_max_ms=900,
        writer_item_max_attempts=5,
        stop_drain_timeout_ms=6_500,
        health_database_timeout_ms=1_250,
        projector_lease_seconds=23,
        projector_max_attempts=8,
        projector_dependency_timeout_seconds=111,
        inline_payload_max_bytes=2_048,
        heartbeat_stale_after_seconds=77,
        long_dwell_seconds=88,
        exact_repetition_window=9,
        tool_frequency_window_seconds=54,
        tool_frequency_threshold=12,
        environment_sample_interval_seconds=3,
    )
    try:
        assert service._writer_retry_max_attempts == 4
        assert service._writer_backoff_initial_ms == 19
        assert service._writer_backoff_max_ms == 900
        assert service._writer_item_max_attempts == 5
        assert service._stop_drain_timeout_seconds == 6.5
        assert service._capacity == 123
        assert service._byte_capacity == 456_789
        assert service._batch_size == 6
        assert service._flush_interval_seconds == 0.033
        assert service._terminal_flush_timeout_seconds == 2.75
        assert service._projector_poll_interval_seconds == 0.175
        assert service._operations_assessment_interval_seconds == 2.5
        assert service._health_database_timeout_seconds == 1.25
        backend = service._backend
        assert backend._projector_lease_seconds == 23
        assert backend._projector_max_attempts == 8
        assert backend._projector_dependency_timeout.total_seconds() == 111
        assert backend._inline_payload_max_bytes == 2_048
        assert backend._heartbeat_stale_after_seconds == 77
        assert backend._long_dwell_seconds == 88
        assert backend._exact_repetition_window == 9
        assert backend._tool_frequency_window_seconds == 54
        assert backend._tool_frequency_threshold == 12
        assert backend._environment_sample_interval_seconds == 3
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_configured_writer_knobs_govern_a_real_incident(tmp_path) -> None:
    """The threading, spent rather than reflected: a configured budget bounds the loss.

    Reflection proves a value arrived; this proves the arriving value is the
    one the writer obeys. ``writer_retry_max_attempts=2`` and
    ``writer_item_max_attempts=1`` make an outage that never heals resolve in a
    handful of attempts instead of thousands, and the shape of what is left is
    the one Task 5 specifies: the batch is bisected, each row gets its single
    attempt, and the loss is exactly the rows storage kept refusing — counted in
    ``poison_observation_count``, which is the only signal that separates "this
    row is unwritable" from "storage was down".
    """

    task_id = new_id()
    observations = _workload(task_id, 5)
    async with _collector(
        tmp_path,
        "configured-budget",
        writer_retry_max_attempts=2,
        writer_item_max_attempts=1,
        writer_backoff_initial_ms=1,
        writer_backoff_max_ms=2,
    ) as (service, fault):
        fault.refuse()
        service.record_batch(tuple(observations))
        await _wait_for(
            "the writer to exhaust its configured budgets and isolate the batch",
            lambda: service.get_health().writer.poison_observation_count == len(observations),
        )
        health = service.get_health()

    # Two batch attempts, then one attempt per row: five rows means seven
    # refusals from the writer, and no more. A budget that was not the
    # configured one would overshoot here rather than fail an equality on a
    # count nobody reads. Counted per coroutine because the projector is meeting
    # the same fault on its own schedule and its refusals are not this budget.
    assert fault.refusals_by_task["ansich-batch-writer"] == 2 + len(observations)
    assert health.dropped_count == len(observations)
    assert health.writer.poison_observation_count == len(observations)
    assert health.writer.in_flight_count == 0
    assert _charged_sequences(health.lost_ranges) == list(range(1, len(observations) + 1))
    _assert_producer_accounting_balances(health)
