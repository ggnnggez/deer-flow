"""Two-worker lease interleavings: generation CAS, ``retry`` status, maintenance.

Every scenario here is an explicit, deterministic interleaving script rather
than a race the scheduler might or might not produce. That is possible because
SQLite renders ``skip_locked`` as empty and lets both backends see the same
row, which makes it the exact substrate the completion-side CAS needs: worker A
claims, its lease is expired *by injection*, worker B claims the same row, and
A's late write must be dropped. What SQLite cannot prove is claim-side
exclusion (two workers claiming the same row at once) or a READ COMMITTED lost
update -- those need a real PostgreSQL server and live in the opt-in tier.

Clock discipline (global rule): every timestamp in this module is past-dated on
purpose. A lease-expiry decision must never be settled between a simulated
clock and the real one, so expiry is injected as a timestamp that is in the
past under any clock rather than by moving a fake clock forward.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from ansich import ObservationEnvelope, Producer, new_id
from ansich.assessment.scope_safety import SCOPE_SAFETY_ASSESSOR
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from deerflow.ansich.persistence.models import (
    AnsichAssessorErrorRow,
    AnsichAssessorJobRow,
    AnsichProjectionErrorRow,
    AnsichProjectionJobRow,
)
from deerflow.ansich.persistence.sql import _PG_MAINTENANCE_LOCK_KEY, SqlAnsichBackend
from deerflow.persistence.base import Base
from deerflow.persistence.bootstrap import _PG_LOCK_KEY as _PG_BOOTSTRAP_LOCK_KEY

# Past-dated fixture timestamps (see the module docstring's clock discipline).
# Comfortably past, not merely yesterday: a one-day margin is close enough to
# the real clock that a slow machine, a timezone slip, or a suite that runs
# overnight could put a "past" fixture in the future.
_OCCURRED_AT = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
_EXPIRED_AT = datetime(2026, 1, 1, tzinfo=UTC)


class _Workers:
    """Two independent workers over one database, plus a read handle each."""

    def __init__(
        self,
        first: SqlAnsichBackend,
        second: SqlAnsichBackend,
        first_sessions: async_sessionmaker,
        second_sessions: async_sessionmaker,
    ) -> None:
        self.a = first
        self.b = second
        self.a_sessions = first_sessions
        self.b_sessions = second_sessions


@contextlib.asynccontextmanager
async def _two_workers(tmp_path: Path, **backend_kwargs: object) -> AsyncIterator[_Workers]:
    """Two engines and two backends over ONE SQLite file.

    Separate engines (not one shared session factory) because the thing under
    test is two *workers*: each mints its own process-lifetime ``lease_owner``
    and holds its own connections, exactly as two Gateway processes would.
    """

    database_path = tmp_path / "ansich-lease-cas.db"
    engines = [create_async_engine(f"sqlite+aiosqlite:///{database_path}") for _ in range(2)]
    async with engines[0].begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = [async_sessionmaker(engine, expire_on_commit=False) for engine in engines]
    workers = _Workers(
        SqlAnsichBackend(sessions[0], **backend_kwargs),  # type: ignore[arg-type]
        SqlAnsichBackend(sessions[1], **backend_kwargs),  # type: ignore[arg-type]
        sessions[0],
        sessions[1],
    )
    try:
        yield workers
    finally:
        for engine in engines:
            await engine.dispose()


def _task_created(task_id: str, *, source_id: str) -> ObservationEnvelope:
    return ObservationEnvelope.task_lifecycle(
        kind="task.created",
        task_id=task_id,
        source_kind="deerflow_run",
        source_id=source_id,
        occurred_at=_OCCURRED_AT,
        source_event_id=f"run:{source_id}:task:created",
    )


async def _projection_job(sessions: async_sessionmaker, job_id: str) -> AnsichProjectionJobRow:
    async with sessions() as session:
        row = await session.get(AnsichProjectionJobRow, job_id)
    assert row is not None
    return row


async def _assessor_job(sessions: async_sessionmaker, job_id: str) -> AnsichAssessorJobRow:
    async with sessions() as session:
        row = await session.get(AnsichAssessorJobRow, job_id)
    assert row is not None
    return row


async def _expire_projection_lease(sessions: async_sessionmaker, job_id: str) -> None:
    async with sessions() as session, session.begin():
        await session.execute(update(AnsichProjectionJobRow).where(AnsichProjectionJobRow.job_id == job_id).values(lease_expires_at=_EXPIRED_AT))


async def _expire_assessor_lease(sessions: async_sessionmaker, job_id: str) -> None:
    async with sessions() as session, session.begin():
        await session.execute(update(AnsichAssessorJobRow).where(AnsichAssessorJobRow.job_id == job_id).values(lease_expires_at=_EXPIRED_AT))


async def _make_claimable_now(sessions: async_sessionmaker, job_id: str) -> None:
    """Bring a backed-off job forward without moving any clock."""

    async with sessions() as session, session.begin():
        await session.execute(update(AnsichProjectionJobRow).where(AnsichProjectionJobRow.job_id == job_id).values(available_at=_OCCURRED_AT))


async def _row_count(sessions: async_sessionmaker, model: type) -> int:
    async with sessions() as session:
        return int(await session.scalar(select(func.count()).select_from(model)) or 0)


def _take_over_between_claim_and_completion(workers: _Workers, record: dict[str, object]):
    """Patch A's claim so B takes the row over before A can finish it.

    The takeover has to land *between* the two transactions ``project_pending``
    uses -- the claim and the projection+completion -- because SQLite has one
    writer: B cannot claim anything while A holds an open write transaction.
    """

    original_claim = workers.a._claim_projection_job

    async def claim_then_lose_the_lease():
        claim = await original_claim()
        if claim is not None and "a" not in record:
            record["a"] = claim
            await _expire_projection_lease(workers.a_sessions, claim[0])
            record["b"] = await workers.b._claim_projection_job()
        return claim

    workers.a._claim_projection_job = claim_then_lose_the_lease  # type: ignore[method-assign]


@pytest.mark.anyio
async def test_completion_after_takeover_is_dropped_and_the_new_owner_settles_the_job(tmp_path):
    async with _two_workers(tmp_path) as workers:
        task_id = new_id()
        await workers.a.persist_and_project([_task_created(task_id, source_id="run-cas-complete")])
        record: dict[str, object] = {}
        _take_over_between_claim_and_completion(workers, record)

        await workers.a.project_pending(limit=1)

        a_claim = record["a"]
        b_claim = record["b"]
        assert b_claim is not None
        assert b_claim[0] == a_claim[0]
        job_id = b_claim[0]
        after_stale_write = await _projection_job(workers.a_sessions, job_id)
        # The row still belongs to B: A's completion never reached it.
        assert after_stale_write.status == "processing"
        assert after_stale_write.lease_owner == workers.b._lease_owner
        assert after_stale_write.lease_generation == b_claim[-1] == a_claim[-1] + 1
        assert workers.a.stale_completion_count == 1

        async with workers.b_sessions() as session, session.begin():
            settled = await workers.b._complete_projection_job(
                session,
                job_id=job_id,
                lease_generation=b_claim[-1],
            )

        assert settled is True
        assert workers.b.stale_completion_count == 0
        after_owner_write = await _projection_job(workers.a_sessions, job_id)
        assert after_owner_write.status == "completed"
        assert after_owner_write.lease_owner is None
        assert after_owner_write.lease_generation == b_claim[-1]


@pytest.mark.anyio
async def test_same_owner_reclaim_still_invalidates_the_earlier_attempt(tmp_path):
    """The ABA the generation column exists for (RB4(2)).

    ``lease_owner`` is one uuid per *process*, so a worker whose lease expired
    mid-work re-claims its own job and reads its own id back out of the column.
    An owner-only CAS would accept the stale write; the generation must not.
    """

    async with _two_workers(tmp_path) as workers:
        task_id = new_id()
        await workers.a.persist_and_project([_task_created(task_id, source_id="run-cas-aba")])
        first = await workers.a._claim_projection_job()
        assert first is not None
        await _expire_projection_lease(workers.a_sessions, first[0])
        second = await workers.a._claim_projection_job()
        assert second is not None
        assert second[0] == first[0]

        claimed = await _projection_job(workers.a_sessions, first[0])
        # Same owner across both claims: only the generation tells them apart.
        assert claimed.lease_owner == workers.a._lease_owner
        assert second[-1] == first[-1] + 1

        async with workers.a_sessions() as session, session.begin():
            stale = await workers.a._complete_projection_job(
                session,
                job_id=first[0],
                lease_generation=first[-1],
            )
            fresh = await workers.a._complete_projection_job(
                session,
                job_id=first[0],
                lease_generation=second[-1],
            )

        assert (stale, fresh) == (False, True)
        assert workers.a.stale_completion_count == 1


@pytest.mark.anyio
async def test_error_write_after_takeover_cannot_re_arm_the_new_owner_s_job(tmp_path):
    async with _two_workers(tmp_path) as workers:
        task_id = new_id()
        await workers.a.persist_and_project([_task_created(task_id, source_id="run-cas-error")])

        async def explode(*_args, **_kwargs) -> None:
            raise RuntimeError("projector exploded after the takeover")

        workers.a._project_structural = explode  # type: ignore[method-assign]
        record: dict[str, object] = {}
        _take_over_between_claim_and_completion(workers, record)

        await workers.a.project_pending(limit=1)

        b_claim = record["b"]
        assert b_claim is not None
        after_stale_error = await _projection_job(workers.a_sessions, b_claim[0])
        assert after_stale_error.status == "processing"
        assert after_stale_error.lease_owner == workers.b._lease_owner
        assert after_stale_error.last_error is None
        assert after_stale_error.lease_generation == b_claim[-1]
        # No durable error evidence and no health charge for a write nobody owned.
        assert await _row_count(workers.a_sessions, AnsichProjectionErrorRow) == 0
        assert workers.a._failed_jobs == 0
        assert workers.a.stale_completion_count == 1


@pytest.mark.anyio
async def test_dependency_wait_re_arm_after_takeover_is_dropped(tmp_path):
    """The third error branch: a dependency wait re-arming a job it lost.

    It writes different values than a hard error — it keeps ``pending``, hands
    its attempt back, and stamps ``dependency_pending_since`` — so a guard that
    covered only the hard branch would still let this one re-open a row the new
    owner is working on, and reset the attempt count it is working under.
    """

    async with _two_workers(tmp_path) as workers:
        task_id = new_id()
        step_id = new_id()
        # A Step whose Task was never projected: the projection raises the
        # replay-safe dependency wait rather than a hard error.
        await workers.a.persist_and_project(
            [
                ObservationEnvelope(
                    kind="step.started",
                    occurred_at=_OCCURRED_AT,
                    task_id=task_id,
                    step_id=step_id,
                    subject_type="step",
                    subject_id=step_id,
                    producer=Producer(name="lease-cas-dependency-takeover", version="1", instance_id="test"),
                    producer_seq=1,
                    source_event_id="lease-cas:dependency-takeover:step:started",
                    correlation_id=task_id,
                    payload={"step_seq": 1, "actor_kind": "lead_agent"},
                )
            ]
        )
        record: dict[str, object] = {}
        _take_over_between_claim_and_completion(workers, record)

        await workers.a.project_pending(limit=1)

        b_claim = record["b"]
        assert b_claim is not None
        after_stale_wait = await _projection_job(workers.a_sessions, b_claim[0])
        assert after_stale_wait.status == "processing"
        assert after_stale_wait.lease_owner == workers.b._lease_owner
        assert after_stale_wait.lease_generation == b_claim[-1]
        # The two fields only this branch writes.
        assert after_stale_wait.dependency_pending_since is None
        assert after_stale_wait.attempts == b_claim[-2]
        assert workers.a.stale_completion_count == 1


@pytest.mark.anyio
async def test_dropped_completion_still_refreshes_the_global_context_metrics(tmp_path):
    """A dropped write costs this worker the job, not the database-wide counts.

    ``_refresh_context_metrics`` is a recount of whole tables, not a report of
    this worker's progress: the rows it counts were committed by the projection
    that just ran regardless of who ends up owning the job row.
    """

    async with _two_workers(tmp_path) as workers:
        task_id = new_id()
        step_id = new_id()
        await workers.a.persist_and_project(
            [
                ObservationEnvelope(
                    kind="step.started",
                    occurred_at=_OCCURRED_AT,
                    task_id=task_id,
                    step_id=step_id,
                    subject_type="step",
                    subject_id=step_id,
                    producer=Producer(name="lease-cas-metrics", version="1", instance_id="test"),
                    producer_seq=1,
                    source_event_id="lease-cas:metrics:step:started",
                    correlation_id=task_id,
                    payload={"step_seq": 1, "actor_kind": "lead_agent"},
                )
            ]
        )

        async def project_step_touching_context(*_args, **_kwargs) -> bool:
            return True

        workers.a._project_step = project_step_touching_context  # type: ignore[method-assign]
        refreshes: list[int] = []
        original_refresh = workers.a._refresh_context_metrics

        async def counting_refresh() -> None:
            refreshes.append(1)
            await original_refresh()

        workers.a._refresh_context_metrics = counting_refresh  # type: ignore[method-assign]
        record: dict[str, object] = {}
        _take_over_between_claim_and_completion(workers, record)

        await workers.a.project_pending(limit=1)

        assert record["b"] is not None
        assert workers.a.stale_completion_count == 1
        assert refreshes == [1]


@pytest.mark.anyio
async def test_absorbed_sibling_cannot_be_re_armed_by_the_previous_owner(tmp_path):
    """Assessor absorption is a takeover too, so it must move the generation.

    Absorption completes the group's lower jobs inside the claim transaction.
    The worker that had one of those jobs leased is still running, and its
    error write would otherwise re-arm a job the new claim has already settled.
    """

    async with _two_workers(tmp_path) as workers:
        task_id = new_id()
        await workers.a.persist_and_project([_task_created(task_id, source_id="run-cas-absorb")])
        while await workers.a.project_pending(limit=10):
            pass
        low_job_id = new_id()
        high_job_id = new_id()

        async def _add_assessor_job(job_id: str, watermark: int) -> None:
            async with workers.a_sessions() as session, session.begin():
                session.add(
                    AnsichAssessorJobRow(
                        job_id=job_id,
                        subject_id=task_id,
                        assessor_name=SCOPE_SAFETY_ASSESSOR.name,
                        assessor_version=SCOPE_SAFETY_ASSESSOR.version,
                        evidence_watermark=watermark,
                        status="pending",
                        available_at=_OCCURRED_AT,
                    )
                )

        await _add_assessor_job(low_job_id, 1)
        a_claim = await workers.a._claim_assessor_job()
        assert a_claim is not None
        assert a_claim[0] == low_job_id

        # A higher-watermark sibling lands while A is still evaluating, and A's
        # lease expires before it can finish.
        await _add_assessor_job(high_job_id, 2)
        await _expire_assessor_lease(workers.a_sessions, low_job_id)
        b_claim = await workers.b._claim_assessor_job()
        assert b_claim is not None
        assert b_claim[0] == high_job_id

        absorbed = await _assessor_job(workers.a_sessions, low_job_id)
        assert absorbed.status == "completed"
        assert absorbed.lease_generation == a_claim[-1] + 1

        await workers.a._record_assessor_error(
            low_job_id,
            a_claim[-2],
            RuntimeError("late failure on an absorbed sibling"),
            lease_generation=a_claim[-1],
        )

        after_stale_error = await _assessor_job(workers.a_sessions, low_job_id)
        assert after_stale_error.status == "completed"
        assert after_stale_error.last_error is None
        assert await _row_count(workers.a_sessions, AnsichAssessorErrorRow) == 0
        assert workers.a.stale_completion_count == 1


@pytest.mark.anyio
async def test_hard_error_re_arms_to_retry_which_stays_claimable_until_it_completes(tmp_path):
    async with _two_workers(tmp_path) as workers:
        task_id = new_id()
        await workers.a.persist_and_project([_task_created(task_id, source_id="run-retry-status")])
        structural = workers.a._project_structural
        attempts: list[int] = []

        async def explode_once(session, observation, *args, **kwargs):
            attempts.append(1)
            if len(attempts) == 1:
                raise RuntimeError("first structural attempt fails")
            return await structural(session, observation, *args, **kwargs)

        workers.a._project_structural = explode_once  # type: ignore[method-assign]

        await workers.a.project_pending(limit=1)

        async with workers.a_sessions() as session:
            job_id = await session.scalar(select(AnsichProjectionJobRow.job_id).where(AnsichProjectionJobRow.projector_name == "task-structural"))
        assert job_id is not None
        re_armed = await _projection_job(workers.a_sessions, job_id)
        # ``pending`` is reserved for never-attempted work; this consumed one.
        assert re_armed.status == "retry"
        assert re_armed.attempts == 1
        assert re_armed.lease_owner is None
        assert await workers.a.has_pending_for_task(task_id) is True

        await _make_claimable_now(workers.a_sessions, job_id)
        await workers.a.project_pending(limit=1)

        settled = await _projection_job(workers.a_sessions, job_id)
        assert settled.status == "completed"
        assert settled.attempts == 2
        assert settled.lease_generation == 2
        assert workers.a.stale_completion_count == 0


@pytest.mark.anyio
async def test_dependency_wait_re_arms_to_pending_because_it_consumed_no_attempt(tmp_path):
    async with _two_workers(tmp_path) as workers:
        task_id = new_id()
        step_id = new_id()
        # A Step whose Task was never projected: a replay-safe dependency wait,
        # which is not a retry -- it never spent an attempt.
        await workers.a.persist_and_project(
            [
                ObservationEnvelope(
                    kind="step.started",
                    occurred_at=_OCCURRED_AT,
                    task_id=task_id,
                    step_id=step_id,
                    subject_type="step",
                    subject_id=step_id,
                    producer=Producer(name="lease-cas-dependency", version="1", instance_id="test"),
                    producer_seq=1,
                    source_event_id="lease-cas:dependency:step:started",
                    correlation_id=task_id,
                    payload={"step_seq": 1, "actor_kind": "lead_agent"},
                )
            ]
        )

        await workers.a.project_pending(limit=1)

        async with workers.a_sessions() as session:
            job_id = await session.scalar(select(AnsichProjectionJobRow.job_id).where(AnsichProjectionJobRow.projector_name == "task-step"))
        assert job_id is not None
        waiting = await _projection_job(workers.a_sessions, job_id)
        assert waiting.status == "pending"
        assert waiting.attempts == 0
        assert waiting.dependency_pending_since is not None


@pytest.mark.anyio
async def test_rebuild_re_pend_bumps_generations_so_an_in_flight_completion_cannot_settle_a_job(tmp_path):
    """Without the re-pend bump the replay would silently skip a job.

    A holds a claim when the rebuild starts. The rebuild re-pends every row and
    then replays; if the re-pend left the generation alone, A's completion --
    landing between those two steps -- would mark the job settled and the
    replay would never re-project that Observation.
    """

    async with _two_workers(tmp_path) as workers:
        task_id = new_id()
        await workers.a.persist_and_project([_task_created(task_id, source_id="run-rebuild-cas")])
        a_claim = await workers.a._claim_projection_job()
        assert a_claim is not None
        stale_write: dict[str, bool] = {}
        original_project_pending = workers.b.project_pending

        async def stale_write_then_replay(*args, **kwargs):
            if "result" not in stale_write:
                async with workers.a_sessions() as session, session.begin():
                    stale_write["result"] = await workers.a._complete_projection_job(
                        session,
                        job_id=a_claim[0],
                        lease_generation=a_claim[-1],
                    )
            return await original_project_pending(*args, **kwargs)

        workers.b.project_pending = stale_write_then_replay  # type: ignore[method-assign]

        replayed = await workers.b.rebuild_projections()

        assert stale_write["result"] is False
        assert replayed == 2
        rebuilt = await _projection_job(workers.a_sessions, a_claim[0])
        assert rebuilt.status == "completed"
        # Claim (1) -> rebuild re-pend (2) -> the replay's own claim (3).
        assert rebuilt.lease_generation == 3
        assert await workers.b.get_task(task_id) is not None


@pytest.mark.anyio
async def test_retry_reports_the_rows_it_re_armed_and_leaves_an_in_flight_job_alone(tmp_path):
    async with _two_workers(tmp_path, projector_max_attempts=1) as workers:
        task_id = new_id()
        await workers.a.persist_and_project([_task_created(task_id, source_id="run-retry-scope")])
        structural = workers.a._project_structural

        async def explode(*_args, **_kwargs) -> None:
            raise RuntimeError("structural projector exploded")

        workers.a._project_structural = explode  # type: ignore[method-assign]
        await workers.a.project_pending(limit=1)
        workers.a._project_structural = structural  # type: ignore[method-assign]

        b_claim = await workers.b._claim_projection_job()
        assert b_claim is not None
        assert b_claim[1] == "task-control"

        retried = await workers.a.retry_failed_projections()

        assert retried == 1
        in_flight = await _projection_job(workers.a_sessions, b_claim[0])
        # Only ``failed`` rows are touched: a leased row keeps its owner and
        # its generation, so its worker's completion still wins.
        assert in_flight.status == "processing"
        assert in_flight.lease_owner == workers.b._lease_owner
        assert in_flight.lease_generation == b_claim[-1]
        async with workers.a_sessions() as session:
            statuses = sorted((await session.execute(select(AnsichProjectionJobRow.status))).scalars())
        assert statuses == ["completed", "processing"]


class _RecordingSession:
    """Minimal session stand-in that records the SQL a maintenance lock emits."""

    def __init__(self, dialect_name: str | None, statements: list[tuple[str, object]]) -> None:
        self.bind = None if dialect_name is None else SimpleNamespace(dialect=SimpleNamespace(name=dialect_name))
        self._statements = statements

    async def __aenter__(self) -> _RecordingSession:
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        return None

    async def execute(self, statement: object, parameters: object = None) -> None:
        self._statements.append((" ".join(str(statement).split()), parameters))

    async def rollback(self) -> None:
        self._statements.append(("ROLLBACK", None))


def _statement_index(statements: list[tuple[str, object]], needle: str) -> int:
    for index, (sql, _parameters) in enumerate(statements):
        if needle in sql:
            return index
    raise AssertionError(f"no statement containing {needle!r} in {[sql for sql, _ in statements]}")


@pytest.mark.anyio
@pytest.mark.parametrize("dialect_name", ["postgresql", "sqlite"])
async def test_maintenance_lock_serialises_on_postgres_and_no_ops_elsewhere(dialect_name):
    statements: list[tuple[str, object]] = []
    backend = SqlAnsichBackend(lambda: _RecordingSession(dialect_name, statements))  # type: ignore[arg-type]

    async with backend._maintenance_lock():
        inside = list(statements)

    if dialect_name == "sqlite":
        assert statements == []
        return

    lock_index = _statement_index(inside, "pg_advisory_lock")
    # The kill-switch must precede the acquire, not merely accompany it: a slow
    # acquire on a contended cluster is itself time spent idle in transaction,
    # which is what the timeout would kill (bootstrap.py says the same).
    assert _statement_index(inside, "idle_in_transaction_session_timeout") < lock_index
    # The lock is a documented contract, not an implementation detail: the key
    # value identifies this lock across processes and releases, and it must not
    # collide with the schema bootstrap's, or a rebuild would queue behind a
    # startup migration (and vice versa).
    assert inside[lock_index][1] == {"key": _PG_MAINTENANCE_LOCK_KEY}
    assert _PG_MAINTENANCE_LOCK_KEY == 0x0DEE_A115_C4A5_0027
    assert _PG_MAINTENANCE_LOCK_KEY != _PG_BOOTSTRAP_LOCK_KEY
    assert not any("pg_advisory_unlock" in sql for sql, _ in inside)
    unlock_index = _statement_index(statements, "pg_advisory_unlock")
    assert statements[unlock_index][1] == {"key": _PG_MAINTENANCE_LOCK_KEY}


@pytest.mark.anyio
async def test_maintenance_lock_refuses_to_run_when_the_dialect_is_unresolvable():
    """A lock that cannot tell which backend it is on must fail closed.

    Unreachable through the ordinary session factory, and that is exactly why
    it is pinned: a safety lock silently degrading to a no-op would let two
    operators replay the same Observations while every log stayed quiet.
    """

    statements: list[tuple[str, object]] = []
    backend = SqlAnsichBackend(lambda: _RecordingSession(None, statements))  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="dialect"):
        async with backend._maintenance_lock():
            pass

    assert statements == []
