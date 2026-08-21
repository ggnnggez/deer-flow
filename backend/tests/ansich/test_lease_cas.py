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
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from ansich import AnsichService, ObservationEnvelope, Producer, RebuildOutcome, RetryOutcome, new_id
from ansich.assessment.scope_safety import SCOPE_SAFETY_ASSESSOR
from ansich.safety import scope_entity_id, scope_reference_hash
from pydantic import ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from deerflow.ansich.persistence.models import (
    AnsichAssessorErrorRow,
    AnsichAssessorJobRow,
    AnsichObservationRow,
    AnsichPayloadRow,
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


def _orphan_step(task_id: str, *, source_event_id: str) -> ObservationEnvelope:
    """A Step whose Task was never observed: a replay-safe dependency wait.

    Both of the Step's projectors (``task-step`` and ``task-usage``) wait on the
    same missing Task, so one of these leaves *two* jobs outstanding -- and no
    amount of replaying settles them until the Task's own Observation lands.
    """

    step_id = new_id()
    return ObservationEnvelope(
        kind="step.started",
        occurred_at=_OCCURRED_AT,
        task_id=task_id,
        step_id=step_id,
        subject_type="step",
        subject_id=step_id,
        producer=Producer(name="lease-cas-dependency-wait", version="1", instance_id="test"),
        producer_seq=1,
        source_event_id=source_event_id,
        correlation_id=task_id,
        payload={"step_seq": 1, "actor_kind": "lead_agent"},
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
        assert a_claim.job_id == low_job_id

        # A higher-watermark sibling lands while A is still evaluating, and A's
        # lease expires before it can finish.
        await _add_assessor_job(high_job_id, 2)
        await _expire_assessor_lease(workers.a_sessions, low_job_id)
        b_claim = await workers.b._claim_assessor_job()
        assert b_claim is not None
        assert b_claim.job_id == high_job_id

        absorbed = await _assessor_job(workers.a_sessions, low_job_id)
        assert absorbed.status == "completed"
        assert absorbed.lease_generation == a_claim.lease_generation + 1

        await workers.a._record_assessor_error(
            low_job_id,
            a_claim.attempts,
            RuntimeError("late failure on an absorbed sibling"),
            lease_generation=a_claim.lease_generation,
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
async def test_a_dependency_wait_gives_its_attempt_back_without_demoting_a_retry_row(tmp_path):
    """The other half of the same rule: giving an attempt back is not forgetting one.

    ``pending`` means "nothing has tried this yet" — the property T10's
    four-bucket health split, its panel column and its panel copy are built on.
    A dependency wait hands *its own* attempt back, which is why a fresh job
    stays ``pending`` (the case above). It does not hand back the attempts a
    hard error already spent, so a row that entered the claim as ``retry`` must
    leave it as ``retry``: writing ``pending`` there moves a live retry loop
    into the never-attempted bucket and makes three doc sites false.

    The sequence is the reachable one: hard error → ``retry`` (attempts 1) →
    re-claim (attempts 2) → the dependency is still not projected → attempts
    back to 1, and one attempt has still been spent.
    """

    async with _two_workers(tmp_path) as workers:
        task_id = new_id()
        step_id = new_id()
        # Same fixture as the test above: a Step whose Task was never projected,
        # so the real projector raises the replay-safe dependency wait.
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
                    source_event_id="lease-cas:retry-dependency:step:started",
                    correlation_id=task_id,
                    payload={"step_seq": 1, "actor_kind": "lead_agent"},
                )
            ]
        )

        project_step = workers.a._project_step
        attempts: list[int] = []

        async def explode_once(session, observation, *args, **kwargs):
            attempts.append(1)
            if len(attempts) == 1:
                raise RuntimeError("first step attempt fails hard")
            return await project_step(session, observation, *args, **kwargs)

        workers.a._project_step = explode_once  # type: ignore[method-assign]

        await workers.a.project_pending(limit=1)

        async with workers.a_sessions() as session:
            job_id = await session.scalar(select(AnsichProjectionJobRow.job_id).where(AnsichProjectionJobRow.projector_name == "task-step"))
        assert job_id is not None
        re_armed = await _projection_job(workers.a_sessions, job_id)
        assert re_armed.status == "retry"
        assert re_armed.attempts == 1
        assert re_armed.dependency_pending_since is None

        # Second claim: the hard error is spent, the dependency is still missing.
        await _make_claimable_now(workers.a_sessions, job_id)
        await workers.a.project_pending(limit=1)

        waiting = await _projection_job(workers.a_sessions, job_id)
        assert len(attempts) == 2
        assert waiting.dependency_pending_since is not None
        # The attempt came back...
        assert waiting.attempts == 1
        # ...but the row is still a re-armed one, not a never-attempted one.
        assert waiting.status == "retry"


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

        rebuild = await workers.b.rebuild_projections()

        assert stale_write["result"] is False
        assert rebuild.replayed == 2
        assert rebuild.unsettled == 0
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

        assert retried == RetryOutcome(re_armed=1, unsettled=1)
        # ``unsettled`` is the whole job space, not just what this call touched:
        # B's claim is work still owed when the retry returns, and the caller
        # asking "are the failures gone" needs to be told that.
        in_flight = await _projection_job(workers.a_sessions, b_claim[0])
        # Only ``failed`` rows are touched: a leased row keeps its owner and
        # its generation, so its worker's completion still wins.
        assert in_flight.status == "processing"
        assert in_flight.lease_owner == workers.b._lease_owner
        assert in_flight.lease_generation == b_claim[-1]
        async with workers.a_sessions() as session:
            statuses = sorted((await session.execute(select(AnsichProjectionJobRow.status))).scalars())
        assert statuses == ["completed", "processing"]


class _RecordingConnection:
    """Records the SQL the maintenance lock emits on its pinned connection.

    A connection rather than a session because that is what the lock now holds:
    an advisory lock belongs to the *database session* that took it, and a
    SQLAlchemy ``Session`` returns its connection to the pool on ``rollback()``,
    so the unlock could be issued on a different backend entirely. The real
    proof of that is the opt-in tier's (``tests/integration/
    test_postgres_multiworker.py``); what this stub still owns is the statement
    *order*, which no server is needed to state.

    ``raise_on`` makes one statement fail after it has been recorded, which is
    how the cancelled-acquire path is driven: the statement really was sent, so
    the grant may have landed server-side while the reply was in flight.
    """

    def __init__(self, statements: list[tuple[str, object]], *, raise_on: str | None = None) -> None:
        self._statements = statements
        self._raise_on = raise_on

    async def __aenter__(self) -> _RecordingConnection:
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        return None

    async def execute(self, statement: object, parameters: object = None) -> None:
        rendered = " ".join(str(statement).split())
        self._statements.append((rendered, parameters))
        if self._raise_on is not None and self._raise_on in rendered:
            raise TimeoutError(f"cancelled: {rendered}")

    async def rollback(self) -> None:
        self._statements.append(("ROLLBACK", None))


class _RecordingSession:
    """Session stand-in whose only job is to resolve the bind's dialect.

    The lock reads the dialect through a session (that is the handle the
    backend has) and then pins a connection off the same bind, so the stub
    mirrors both halves.
    """

    def __init__(self, dialect_name: str | None, statements: list[tuple[str, object]], *, raise_on: str | None = None) -> None:
        if dialect_name is None:
            self.bind = None
        else:
            self.bind = SimpleNamespace(
                dialect=SimpleNamespace(name=dialect_name),
                connect=lambda: _RecordingConnection(statements, raise_on=raise_on),
            )
        self._statements = statements

    async def __aenter__(self) -> _RecordingSession:
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        return None

    async def execute(self, statement: object, parameters: object = None) -> None:  # pragma: no cover - the lock no longer executes here
        raise AssertionError("the maintenance lock must run its statements on the pinned connection, not on a session")

    async def rollback(self) -> None:  # pragma: no cover - same
        raise AssertionError("the maintenance lock must roll back its pinned connection, not a session")


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
    # The rollback comes first on purpose -- see the ordering test below.
    assert _statement_index(statements, "ROLLBACK") < unlock_index


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


@pytest.mark.anyio
async def test_maintenance_lock_refuses_a_bind_it_cannot_pin_a_connection_on(tmp_path):
    """The other fail-closed half: a resolvable dialect with no ``connect``.

    Not a hypothetical shape — an ``AsyncSession`` bound to an
    ``AsyncConnection`` answers ``bind.dialect.name`` and has no ``connect``
    (a connection cannot hand out another connection). The advisory lock lives
    on a pinned connection, so a bind that cannot produce one leaves nothing to
    hold the lock; refusing is the same trade as the unresolvable dialect
    above, and for the same reason: a maintenance lock that quietly degraded to
    a no-op would let two operators replay the same Observations.

    **Driven by the real classes, not by a stub of them**, because the claim is
    about a production shape and a stub can only encode what its author already
    believed. Both facts the branch turns on are asserted directly off a real
    ``AsyncSession(bind=AsyncConnection)``: the dialect *is* readable through
    that bind, and ``connect`` *is* absent from it. The only thing substituted
    is the dialect's ``name``, which is the one fact this SQLite tier cannot
    supply — poked onto the throwaway engine's own dialect object, which is
    disposed with it at the end of the test and is never used for a query.
    """

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'maintenance-bind.db'}")
    try:
        async with engine.connect() as connection:
            session = AsyncSession(bind=connection)
            # The production shape, off the real objects.
            assert session.bind is connection
            assert session.bind.dialect.name == "sqlite"
            assert getattr(session.bind, "connect", None) is None

            connection.dialect.name = "postgresql"
            backend = SqlAnsichBackend(lambda: session)  # type: ignore[arg-type]

            with pytest.raises(RuntimeError, match="pin a connection"):
                async with backend._maintenance_lock():
                    pass
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_rebuild_on_an_empty_backlog_reports_nothing_replayed_and_nothing_left(tmp_path):
    """F10-26, the trivial end of the domain: zero is an honest answer."""

    async with _two_workers(tmp_path) as workers:
        rebuild = await workers.a.rebuild_projections()

        assert (rebuild.replayed, rebuild.unsettled) == (0, 0)


@pytest.mark.anyio
async def test_rebuild_reports_the_dependency_pending_job_it_could_not_settle(tmp_path):
    """F10-26: "this round claimed nothing" is not "the rebuild is done".

    A job waiting on a projection dependency parks itself 250ms in the future,
    which puts it outside the claim's ``available_at <= now`` predicate. The
    drain loop's exit condition cannot see it, so before this the rebuild
    returned a replay count that read as complete while an Observation was
    still unprojected -- and the caller's next read got a partial projection
    with nothing to say so.
    """

    async with _two_workers(tmp_path) as workers:
        task_id = new_id()
        await workers.a.persist_and_project(
            [
                _task_created(task_id, source_id="run-rebuild-unsettled"),
                _orphan_step(new_id(), source_event_id="lease-cas:rebuild-unsettled:step:started"),
            ]
        )
        while await workers.a.project_pending(limit=10):
            pass

        rebuild = await workers.a.rebuild_projections()

        assert rebuild.replayed == 2
        # Both of the Step's projectors (``task-step`` and ``task-usage``) wait
        # on the same missing Task, so both are still outstanding.
        assert rebuild.unsettled == 2
        async with workers.a_sessions() as session:
            waiting = await session.scalar(select(AnsichProjectionJobRow).where(AnsichProjectionJobRow.projector_name == "task-step"))
        assert waiting is not None
        # Still claimable, just not yet: that is exactly what the drain cannot
        # see and what the count now says out loud.
        assert waiting.status == "pending"
        assert waiting.dependency_pending_since is not None


@pytest.mark.anyio
async def test_rebuild_reports_a_job_another_worker_claimed_mid_replay(tmp_path):
    """F10-26 folded together with the ``processed == 0`` ambiguity the CAS added.

    Since Task 2 a replay round can return zero because its claims were taken
    over rather than because the queue is empty, and the drain loop treats the
    two identically. Both are the same fact to the caller -- work this pass did
    not settle -- so both are counted.

    On SQLite the interleaving is scripted (one writer, no ``skip_locked``);
    the deployment where it happens by itself is PostgreSQL, where two workers
    genuinely claim in parallel and the rebuild holds only the maintenance lock,
    which a projector loop never takes.
    """

    async with _two_workers(tmp_path) as workers:
        task_id = new_id()
        await workers.a.persist_and_project([_task_created(task_id, source_id="run-rebuild-taken-over")])
        while await workers.a.project_pending(limit=10):
            pass
        stolen: dict[str, object] = {}
        original_claim = workers.b._claim_projection_job

        async def claim_after_a_takes_one():
            if "a" not in stolen:
                # A claims one of the freshly re-pended rows before the replay
                # gets to it, and holds the lease for the rest of the rebuild.
                stolen["a"] = await workers.a._claim_projection_job()
            return await original_claim()

        workers.b._claim_projection_job = claim_after_a_takes_one  # type: ignore[method-assign]

        rebuild = await workers.b.rebuild_projections()

        assert stolen["a"] is not None
        assert rebuild.unsettled == 1
        async with workers.b_sessions() as session:
            in_flight = await session.get(AnsichProjectionJobRow, stolen["a"][0])
        assert in_flight is not None
        assert in_flight.status == "processing"
        assert in_flight.lease_owner == workers.a._lease_owner


@pytest.mark.anyio
async def test_maintenance_lock_still_unlocks_when_the_acquire_is_cancelled():
    """A cancelled acquire is not proof that no lock was taken.

    ``database.command_timeout`` cancels a pending ``pg_advisory_lock`` from the
    client side, but the grant can land on the server while the reply is in
    flight. The unlock therefore has to run on this path too; a spurious
    ``pg_advisory_unlock`` returns false and costs nothing, while a skipped one
    leaves the maintenance lock held until the connection closes.
    """

    statements: list[tuple[str, object]] = []
    backend = SqlAnsichBackend(lambda: _RecordingSession("postgresql", statements, raise_on="pg_advisory_lock"))  # type: ignore[arg-type]

    with pytest.raises(TimeoutError):
        async with backend._maintenance_lock():
            raise AssertionError("the guarded body must not run when the acquire fails")

    assert _statement_index(statements, "pg_advisory_lock") < _statement_index(statements, "ROLLBACK") < _statement_index(statements, "pg_advisory_unlock")


@pytest.mark.anyio
async def test_maintenance_lock_rolls_back_before_unlocking():
    """Ordering, not decoration: the unlock has to reach the server.

    After a DBAPI failure the session is inactive and every further ``execute``
    raises ``PendingRollbackError`` client-side -- so an unlock issued before
    the rollback would be swallowed by the guard around it and the lock would
    stay held for the life of the connection. ``ROLLBACK`` makes the connection
    usable again, and a session-level advisory lock survives it. The recording
    stub cannot reproduce the inactive state, so this test pins the *order*;
    the behaviour it protects is provable only against a real server.
    """

    statements: list[tuple[str, object]] = []
    backend = SqlAnsichBackend(lambda: _RecordingSession("postgresql", statements))  # type: ignore[arg-type]

    async with backend._maintenance_lock():
        pass

    assert _statement_index(statements, "ROLLBACK") < _statement_index(statements, "pg_advisory_unlock")


@pytest.mark.anyio
async def test_retry_counts_what_it_re_armed_and_re_reads_what_is_still_owed(tmp_path):
    """``RetryOutcome.unsettled`` is read *after* the re-arm, not before it.

    The two numbers answer different questions and the ordering is what makes
    the second one worth anything. Before the retry both of the orphan Step's
    jobs are ``failed`` -- durably, because the dependency deadline was set to
    zero for their first wait -- and ``failed`` rows are settled, badly, so the
    unsettled count is ``0``. The retry re-arms them, the drain hands each one
    straight back into a dependency wait under a real deadline, and *that* is
    the state the outcome reports. A count taken before the re-arm would have
    said ``0`` and read as "the failures are gone".
    """

    async with _two_workers(tmp_path) as workers:
        await workers.a.persist_and_project([_orphan_step(new_id(), source_event_id="lease-cas:retry-unsettled:step:started")])
        # A zero deadline makes the very first dependency wait durable, which
        # is the only thing this stanza is for; the real deadline is restored
        # before the retry so the re-armed jobs wait rather than fail again.
        workers.a._projector_dependency_timeout = timedelta(0)
        while await workers.a.project_pending(limit=10):
            pass
        workers.a._projector_dependency_timeout = timedelta(seconds=300)

        assert await workers.a._unsettled_job_count() == 0

        retried = await workers.a.retry_failed_projections()

        # The re-arm count is exact: two ``failed`` rows existed and both were
        # changed. ``unsettled`` is asserted as a floor -- it counts the whole
        # store's backlog, so a job arriving from anywhere else may only raise
        # it, and the claim being made is the ordering one (``0`` before the
        # re-arm, non-zero after it), not a census.
        assert retried.re_armed == 2
        assert retried.unsettled >= 2
        async with workers.a_sessions() as session:
            statuses = sorted((await session.execute(select(AnsichProjectionJobRow.status))).scalars())
        # Both re-armed jobs walked straight back into the dependency wait
        # rather than settling or failing again -- that is the state the
        # outcome above reported.
        assert statuses == ["pending", "pending"]


@pytest.mark.anyio
async def test_retry_with_nothing_failed_still_reports_the_backlog_it_found(tmp_path):
    """Nothing re-armed is not the same statement as nothing owed.

    The re-arm short-circuits when it changed no rows -- there is no replay to
    run -- but the caller's question ("are the failures gone?") is still about
    the store, so the honest answer keeps reading the backlog rather than
    reporting a zero it never looked for.
    """

    async with _two_workers(tmp_path) as workers:
        await workers.a.persist_and_project([_orphan_step(new_id(), source_event_id="lease-cas:retry-empty:step:started")])
        while await workers.a.project_pending(limit=10):
            pass

        retried = await workers.a.retry_failed_projections()

        assert retried == RetryOutcome(re_armed=0, unsettled=2)


@pytest.mark.anyio
async def test_rebuild_until_settled_re_runs_the_rebuild_until_nothing_is_owed(tmp_path):
    """The completeness loop F10-26 moved onto the caller (spec §5).

    ``rebuild_projections()`` reports rather than waits, so a caller that needs
    "the read model is complete" has to call again. Round one here loses the
    Task's structural projection, and the Step's own two projectors then find no
    Task to hang off and park themselves inside the 250ms dependency backoff,
    invisible to the drain's exit condition. Round two re-pends every job with
    ``available_at`` at now, projects the Task first (lower ``ingest_seq``), and
    the Step's wait resolves.

    The loop's own exit condition is ``unsettled == 0``, deliberately not "a
    round replayed nothing": every round replays the whole store, so a replay
    count is never a completion claim.

    **Neither half of this bets on a clock.** The structural failure is keyed on
    *which round is running* rather than on a call count, so round one cannot
    converge however slowly its drain runs -- a per-call trip would let a drain
    pass that outlives the 250ms park re-claim the recovered structural job and
    settle everything inside round one, and the "more than one round" assertion
    would then be red for a reason that has nothing to do with the loop. The
    round count is asserted as a floor for the mirror-image reason: under load
    round two may itself defer, and needing a third round is the loop working,
    not failing.
    """

    async with _two_workers(tmp_path) as workers:
        task_id = new_id()
        await workers.a.persist_and_project(
            [
                _task_created(task_id, source_id="run-until-settled"),
                # This Step's Task *is* observed -- the dependency it waits on
                # in round one is the projection, not the Observation.
                _orphan_step(task_id, source_event_id="lease-cas:until-settled:step:started"),
            ]
        )
        while await workers.a.project_pending(limit=10):
            pass
        service = AnsichService(workers.a)
        rounds: list[RebuildOutcome] = []
        structural = workers.a._project_structural
        original_rebuild = workers.a.rebuild_projections

        async def fail_structural_for_the_whole_first_round(*args, **kwargs):
            # ``rounds`` is appended to only after a round returns, so it is
            # empty for exactly the duration of round one.
            if not rounds:
                raise RuntimeError("structural projector lost the whole first round")
            return await structural(*args, **kwargs)

        async def recording_rebuild() -> RebuildOutcome:
            outcome = await original_rebuild()
            rounds.append(outcome)
            return outcome

        workers.a._project_structural = fail_structural_for_the_whole_first_round  # type: ignore[method-assign]
        workers.a.rebuild_projections = recording_rebuild  # type: ignore[method-assign]

        settled = await service.rebuild_until_settled()

        assert len(rounds) >= 2
        assert rounds[0].unsettled > 0
        # The last round's outcome, not a sum: each round replays the whole
        # store from scratch, so summing would count the same jobs twice.
        assert settled == rounds[-1]
        assert settled.unsettled == 0
        # Four jobs, whichever round finally settles them -- every round
        # replays the whole store, so this is a property of the store rather
        # than of the round count.
        assert settled.replayed == 4
        assert await service.list_steps(task_id)


@pytest.mark.anyio
async def test_rebuild_until_settled_reports_exhaustion_instead_of_raising(tmp_path):
    """A budget that runs out is news, not an exception.

    The dependency here never arrives, so no number of rounds converges. The
    loop spends its budget and hands back the last round it ran with
    ``unsettled`` still non-zero: the caller decides what an incomplete rebuild
    means for it, and a maintenance endpoint that raised here would turn an
    honest report into a 500.

    The round count is pinned **exactly** here, unlike its converging sibling,
    and that is safe for the same reason the test works at all: the orphan
    Step's Task is never observed, so no round can settle it however slowly the
    drain runs. ``max_rounds`` is an exact budget, and spending all of it is the
    behaviour under test.
    """

    async with _two_workers(tmp_path) as workers:
        await workers.a.persist_and_project([_orphan_step(new_id(), source_event_id="lease-cas:exhausted:step:started")])
        while await workers.a.project_pending(limit=10):
            pass
        service = AnsichService(workers.a)
        rounds = 0
        original_rebuild = workers.a.rebuild_projections

        async def counted_rebuild() -> RebuildOutcome:
            nonlocal rounds
            rounds += 1
            return await original_rebuild()

        workers.a.rebuild_projections = counted_rebuild  # type: ignore[method-assign]

        settled = await service.rebuild_until_settled(max_rounds=3)

        assert rounds == 3
        assert settled.unsettled == 2


_ENVIRONMENT_SCOPE_REF = "local:thread-lease-cas-env"
_ENVIRONMENT_SCOPE_ID = scope_entity_id("sandbox", scope_reference_hash("sandbox", _ENVIRONMENT_SCOPE_REF))


def _scope_snapshotted(task_id: str, *, source_id: str) -> ObservationEnvelope:
    return ObservationEnvelope.scope_snapshotted(
        task_id=task_id,
        run_id=source_id,
        occurred_at=_OCCURRED_AT,
        scope_kind="sandbox",
        external_ref=_ENVIRONMENT_SCOPE_REF,
        relation_role="sandbox_boundary",
        source_event_id=f"run:{source_id}:scope:{_ENVIRONMENT_SCOPE_ID}",
    )


def _externalized_environment_sample(task_id: str, *, source_id: str) -> ObservationEnvelope:
    """An ``environment.sampled`` large enough to be stored out of line.

    Nothing here lowers ``inline_payload_max_bytes``: both backends run at the
    production default (65536), and a Scope reporting several hundred metric
    readings crosses it on its own. The metric names are long but canonical
    (``^[a-z][a-z0-9_]{0,63}$``), so the size comes from a legal payload rather
    than from junk the contract would refuse.
    """

    metrics = {f"fd_open_shard_{index:04d}_" + "e" * 40: {"value": 100 + index, "limit": 1024} for index in range(800)}
    return ObservationEnvelope.environment_sampled(
        task_id=task_id,
        run_id=source_id,
        occurred_at=_OCCURRED_AT + timedelta(seconds=10),
        scope_id=_ENVIRONMENT_SCOPE_ID,
        payload={
            "environment_scope": "container",
            "coverage": "continuous",
            "provider": "local",
            "metrics": metrics,
            "window": {
                "started_at": _OCCURRED_AT.isoformat(),
                "ended_at": (_OCCURRED_AT + timedelta(seconds=10)).isoformat(),
                "sample_count": 1,
            },
        },
        source_event_id=f"run:{source_id}:env:{_ENVIRONMENT_SCOPE_ID}:1",
        producer_name="deerflow-environment-probe",
    )


@pytest.mark.anyio
async def test_an_externalized_environment_sample_is_hydrated_before_its_envelope_is_built(tmp_path):
    """F10-29 ②: the claim hydrates the payload, then builds the envelope once.

    The old order built the envelope from the raw row and hydrated afterwards,
    which handed ``ObservationEnvelope`` a ``None`` payload for an externalized
    ``environment.sampled`` and raised inside the claim transaction. That was
    worse than a durably failed job, and worse quietly: the raise rolled the
    claim back, so no attempt was ever charged and the job could never reach
    ``failed``; ``AnsichService._project_pending`` catches every exception and
    reports it to the loop as "0 processed", so the projector loop survived and
    simply re-claimed the same row forever. And the claim orders by
    ``ingest_seq``, so once that row was the lowest claimable one **every**
    projection stalled behind it, process-wide and for every Task, while health
    answered ``reachable`` with ``failed_jobs=0`` and no ``projection_failure``
    Alert could fire -- "写得进、读不出、作业永不落地", silently.

    Hydrating first also means the envelope is validated **against the payload
    the projector will actually read**, once, instead of being validated empty
    and then patched by a ``model_copy`` that re-runs no validator at all.
    """

    async with _two_workers(tmp_path) as workers:
        task_id = new_id()
        source_id = "run-f10-29-claim"
        sample = _externalized_environment_sample(task_id, source_id=source_id)
        await workers.a.persist_and_project(
            [
                _task_created(task_id, source_id=source_id),
                _scope_snapshotted(task_id, source_id=source_id),
                sample,
            ]
        )

        claims: list[tuple] = []
        original_claim = workers.a._claim_projection_job

        async def recording_claim():
            claim = await original_claim()
            if claim is not None:
                claims.append(claim)
            return claim

        workers.a._claim_projection_job = recording_claim  # type: ignore[method-assign]
        await workers.a.project_pending(limit=50)

        environment_claims = [claim for claim in claims if claim[1] == "environment-projector"]
        assert len(environment_claims) == 1
        job_id, _, claimed, _, _, _ = environment_claims[0]

        # The claimed envelope carries the payload itself, read back inside the
        # claim transaction, and no longer advertises the ref it came from.
        assert claimed.payload_ref_id is None
        assert claimed.payload is not None
        assert claimed.payload["metrics"] == sample.payload["metrics"]

        settled = await _projection_job(workers.a_sessions, job_id)
        assert settled.status == "completed"

        async with workers.a_sessions() as session:
            stored = await session.scalar(select(AnsichObservationRow).where(AnsichObservationRow.obs_id == sample.obs_id))
        # The precondition the whole scenario rests on: the row really is
        # externalized, so the claim genuinely had nothing inline to read.
        assert (stored.payload_json, stored.payload_ref_id is not None) == (None, True)
        assert await _row_count(workers.a_sessions, AnsichProjectionErrorRow) == 0


@pytest.mark.anyio
async def test_the_claim_validates_the_hydrated_payload_instead_of_patching_it_in(tmp_path):
    """The other half of F10-29 ②'s reorder: hydrate, *then* validate.

    Building the envelope from the raw row and ``model_copy``-ing the hydrated
    payload in afterwards re-runs no validator, so the contract gate the write
    path passed applied to an empty payload and the payload the projector
    actually read reached it unchecked. Hydrating first makes the single
    validation the envelope already performs cover the payload in it.

    The row is minted through the normal write path and its stored payload is
    then rewritten, because that is the only shape this is reachable in: a
    payload that no longer satisfies the contract its Observation was written
    under. ``inline_payload_max_bytes=16`` is what forces externalization here
    — this test is about the claim's order, not about the threshold.
    """

    other_scope_id = scope_entity_id("sandbox", scope_reference_hash("sandbox", "local:thread-lease-cas-other"))

    async with _two_workers(tmp_path, inline_payload_max_bytes=16) as workers:
        task_id = new_id()
        source_id = "run-f10-29-claim-validation"
        scope_observation = _scope_snapshotted(task_id, source_id=source_id)
        await workers.a.persist_and_project(
            [
                _task_created(task_id, source_id=source_id),
                scope_observation,
            ]
        )

        async with workers.a_sessions() as session, session.begin():
            row = await session.scalar(select(AnsichObservationRow).where(AnsichObservationRow.obs_id == scope_observation.obs_id))
            assert row.payload_json is None and row.payload_ref_id is not None
            stored_payload = await session.get(AnsichPayloadRow, row.payload_ref_id)
            body = json.loads(stored_payload.body.decode(stored_payload.encoding))
            body["scope"]["scope_id"] = other_scope_id
            stored_payload.body = json.dumps(body, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")

        with pytest.raises(ValidationError, match="subject must identify payload scope"):
            while await workers.a._claim_projection_job() is not None:
                pass
