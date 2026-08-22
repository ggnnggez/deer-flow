"""Two workers, one PostgreSQL: the multiworker semantics SQLite cannot prove.

Everything P11-B added to the lease, rollup and maintenance paths was designed
against a substrate that renders ``skip_locked`` as empty, lets both "workers"
see the same uncommitted-free view, and serialises every writer. That made
SQLite the exact right base for the *completion-side* compare-and-set
(``tests/ansich/test_lease_cas.py`` scripts those interleavings deterministically)
and for the *statement order* of the four rollups
(``tests/ansich/test_rollup_serialization.py``). It cannot answer three
questions, and every one of them is a claim the batch actually makes:

* does ``FOR UPDATE ... SKIP LOCKED`` really hand two concurrent claimers
  disjoint jobs, or is the disjointness an artefact of one writer at a time?
* does an unlocked read-modify-write really lose a sibling's update under READ
  COMMITTED -- i.e. is the lock-then-read conversion (F10-6/F10-20) load-bearing
  rather than decorative?
* does ``pg_advisory_lock`` really exclude a second operator, and is it really
  released after a mid-rebuild DBAPI failure (the rollback-then-unlock ordering)?

This module answers them on a real server. It is the debt-settlement tier the
rest of the batch kept pointing at: five in-code comments in
``deerflow/ansich/persistence/sql.py`` and one test-module docstring name this
file by path, so the name is load-bearing.

Opt-in and self-skipping, the same shape (and for the same reasons) as
``tests/integration/test_postgres_migration_matrix.py``: every test carries
``@pytest.mark.integration`` and the module skips itself unless
``DEER_FLOW_TEST_POSTGRES_URL`` points at a reachable server. There is
deliberately no default URL -- these tests ``CREATE DATABASE`` / ``DROP
DATABASE`` on whatever server they are pointed at. No env var means no
postgres, full stop, which is what keeps ``make test`` SQLite-only.

Spin one up::

    docker run --rm -d --name deerflow-pg-test -p 5433:5432 \\
        -e POSTGRES_PASSWORD=deerflow-test postgres:16
    export DEER_FLOW_TEST_POSTGRES_URL=postgresql+asyncpg://postgres:deerflow-test@localhost:5433/postgres
    cd backend && make test-postgres

**Two workers means two engines over one database.** Not one session factory
handed to two backends: what is under test is two *processes*, and the two
things that differ between a process pair and a session pair are exactly the
two that matter here -- a separate connection pool (so one worker's open
transaction genuinely blocks the other's statement rather than being serialised
by a shared connection) and a separate ``SqlAnsichBackend._lease_owner`` (one
``uuid4`` per process, the reason the lease CAS keys on a generation and not on
the owner id).

**Bare backends, not services, for everything except the alert scenario.** A
``SqlAnsichBackend`` *is* the worker for every claim/complete/rollup question
below, and driving it directly is what makes these scripts deterministic
interleavings rather than races against two projector loops. The one scenario
that has to go through ``AnsichService`` is the periodic ``assess_operations``
collision, and there both services carry ``only_test_driven_assessments`` --
per-service, since the gate rebinds one instance's method -- while the test
drives the two concurrent assessments through the *pre-gate* bound methods it
captured. Silencing the loops and driving the calls are separate concerns and
the gate cannot tell them apart (it keys on the calling task, and
``asyncio.gather`` makes new ones).

**Every assertion lands on database rows.** ``_project_pending`` swallows its
exceptions by design, so a service or backend return value says nothing about
what happened; the job rows, the summary rows and ``pg_locks`` do.

**Clock discipline.** Fixture timestamps are past-dated and lease expiry is
*injected* as a past timestamp rather than produced by waiting or by moving a
fake clock, so no decision here is ever settled between a simulated clock and
the real one.

Scope: the multiworker semantics plus the one migration assertion that belongs
with them (``0027``'s columns and index on a real server). The migration matrix,
the bootstrap branches and the end-to-end service smoke stay in the sibling
module; running the *whole* suite against postgres remains a separate, much
larger question and is deliberately not attempted here.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import uuid
from collections import Counter
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from alembic import command as alembic_command
from ansich import AnsichService, AuthorizationSnapshot, ObservationEnvelope, Producer, ReplayReport, ReplaySelector, new_id
from ansich.assessment.scope_safety import SCOPE_SAFETY_ASSESSOR
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from support.ansich_settle import only_test_driven_assessments

# Pre-import models so ``Base.metadata`` is populated before anything reads it.
import deerflow.persistence.models  # noqa: F401
from deerflow.ansich import create_sql_ansich_service
from deerflow.ansich.persistence import sql as ansich_sql
from deerflow.ansich.persistence.models import (
    AnsichAlertRow,
    AnsichAssessorErrorRow,
    AnsichAssessorJobRow,
    AnsichAssessorWatermarkRow,
    AnsichObservationRow,
    AnsichProjectionJobRow,
    AnsichScopeConclusionRow,
    AnsichTaskHeartbeatRow,
    AnsichTaskUsageRow,
    AnsichUsageContributionRow,
)
from deerflow.ansich.persistence.sql import _PG_MAINTENANCE_LOCK_KEY, SqlAnsichBackend
from deerflow.ansich.replay import execute_replay
from deerflow.persistence.base import Base
from deerflow.persistence.bootstrap import _get_alembic_config, _get_head_revision

POSTGRES_TEST_URL = os.environ.get("DEER_FLOW_TEST_POSTGRES_URL")

# Past-dated on purpose (the clock discipline in the module docstring): nothing
# below may be decided between a fixture timestamp and the real clock.
_OCCURRED_AT = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
_EXPIRED_AT = datetime(2026, 1, 1, tzinfo=UTC)
_LIVE_LEASE_AT = datetime(2099, 1, 1, tzinfo=UTC)

# How long one side of an injected interleaving waits for the other. In the
# scripts below the *green* half is expected to time this out -- that is the
# lock doing its job -- so it is a rendezvous budget, not a failure threshold.
_INTERLEAVE_TIMEOUT_SECONDS = 2.0
# Outer bound on any single concurrent script, so a wedge fails the test
# instead of hanging the tier.
_SCRIPT_TIMEOUT_SECONDS = 60.0

_PRODUCER = Producer(name="pg-multiworker-test", version="1", instance_id="test")

# Bounded attempts for the opportunistic episode-collision observation.
_COLLISION_ROUNDS = 8
_TASKS_PER_COLLISION_ROUND = 6

# Consecutive empty claims that mean the backlog really is drained rather than
# momentarily all-locked by the peer's in-flight claim.
_CLAIM_MISSES_BEFORE_DRAINED = 3


# ---------------------------------------------------------------------------
# Availability probe (shape borrowed verbatim from the migration matrix)
# ---------------------------------------------------------------------------


def _safe_url(url: str | URL) -> str:
    """Render *url* with the password masked, for skip reasons and messages."""
    return make_url(url).render_as_string(hide_password=True)


def _connect_url(url: URL) -> str:
    """Render *url* with the password intact, for actually connecting."""
    return url.render_as_string(hide_password=False)


async def _ping(url: str) -> None:
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            await conn.execute(sa.text("SELECT 1"))
    finally:
        await engine.dispose()


def _postgres_availability() -> tuple[bool, str]:
    if not POSTGRES_TEST_URL:
        return False, "DEER_FLOW_TEST_POSTGRES_URL is not set (opt-in postgres tier)"
    try:
        import asyncpg  # noqa: F401
    except ImportError:
        return False, "asyncpg is not installed (uv sync installs it via the dev group)"
    try:
        asyncio.run(_ping(POSTGRES_TEST_URL))
    except Exception as exc:  # noqa: BLE001 -- any connect failure means "skip"
        return False, f"Postgres not reachable at {_safe_url(POSTGRES_TEST_URL)}: {exc}"
    return True, ""


_POSTGRES_AVAILABLE, _SKIP_REASON = _postgres_availability()

requires_postgres = pytest.mark.skipif(not _POSTGRES_AVAILABLE, reason=_SKIP_REASON)

pytestmark = [pytest.mark.integration, requires_postgres, pytest.mark.asyncio]


# ---------------------------------------------------------------------------
# Per-test database, two engines over it
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _postgres_database() -> AsyncIterator[URL]:
    """Yield the URL of a fresh, uniquely-named database, dropped on the way out.

    Same isolation unit as the migration matrix -- a whole database per test --
    so a crashed run leaves at most one stray database rather than a half-built
    schema the next run inherits. ``CREATE``/``DROP DATABASE`` are refused
    inside a transaction block, hence the AUTOCOMMIT admin engine.
    """

    server_url = make_url(POSTGRES_TEST_URL)
    db_name = f"deerflow_pg_mw_{uuid.uuid4().hex[:16]}"
    admin = create_async_engine(_connect_url(server_url), isolation_level="AUTOCOMMIT", poolclass=NullPool)
    try:
        async with admin.connect() as conn:
            await conn.execute(sa.text(f'CREATE DATABASE "{db_name}"'))
        try:
            yield server_url.set(database=db_name)
        finally:
            async with admin.connect() as conn:
                # Any connection still open on the database blocks the drop; a
                # test that failed mid-flight can easily leave one behind.
                await conn.execute(
                    sa.text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = :name AND pid <> pg_backend_pid()"),
                    {"name": db_name},
                )
                await conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{db_name}"'))
    finally:
        await admin.dispose()


def _statement_text(statement: object) -> str:
    """Render an ORM statement for the table-name predicates the hooks use."""

    try:
        return str(statement.compile(dialect=postgresql.dialect())).lower()  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover - defensive, a statement we cannot render
        return str(statement).lower()


def _scripted_session_class(label: str) -> type[AsyncSession]:
    """One ``AsyncSession`` subclass per worker, carrying that worker's script.

    An interleaving script has to pause a worker *between* two statements of a
    production method, and the statement stream is the only seam for that which
    does not transcribe the method into the test -- a transcription rots the
    moment the method changes, and would prove the copy rather than the code.

    A fresh subclass per worker (rather than one class with a registry) is what
    keeps a hook installed on worker A invisible to worker B, which is the whole
    point of the two-worker shape. It is also what makes the pre-fix
    ``_lock_rollup_targets`` patch dispatchable by ``isinstance``.
    """

    return type(f"_ScriptedSession_{label}", (_ScriptedSessionBase,), {"after_execute": None})


class _ScriptedSessionBase(AsyncSession):
    """Base for the per-worker session classes; see ``_scripted_session_class``."""

    # Overridden on each subclass by ``_scripted_session_class``.
    after_execute: Callable[[object], object] | None = None

    async def execute(self, statement, *args, **kwargs):  # type: ignore[override]
        result = await super().execute(statement, *args, **kwargs)
        hook = type(self).after_execute
        if hook is not None:
            await hook(statement)
        return result


@dataclass
class _Worker:
    """One simulated Gateway process: its own engine, pool, sessions and backend."""

    engine: AsyncEngine
    sessions: async_sessionmaker
    backend: SqlAnsichBackend
    session_class: type[AsyncSession]


@asynccontextmanager
async def _two_workers(**backend_kwargs: object) -> AsyncIterator[tuple[URL, _Worker, _Worker]]:
    """Two independent workers over one freshly-created database."""

    async with _postgres_database() as url:
        workers: list[_Worker] = []
        for label in ("a", "b"):
            engine = create_async_engine(_connect_url(url))
            session_class = _scripted_session_class(label)
            sessions = async_sessionmaker(engine, class_=session_class, expire_on_commit=False)
            workers.append(
                _Worker(
                    engine=engine,
                    sessions=sessions,
                    backend=SqlAnsichBackend(sessions, **backend_kwargs),  # type: ignore[arg-type]
                    session_class=session_class,
                )
            )
        async with workers[0].engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        try:
            yield url, workers[0], workers[1]
        finally:
            for worker in workers:
                await worker.engine.dispose()


# ---------------------------------------------------------------------------
# Observation fixtures
# ---------------------------------------------------------------------------


def _task_created(task_id: str, *, source_id: str) -> ObservationEnvelope:
    return ObservationEnvelope.task_lifecycle(
        kind="task.created",
        task_id=task_id,
        source_kind="deerflow_run",
        source_id=source_id,
        occurred_at=_OCCURRED_AT,
        source_event_id=f"run:{source_id}:task:created",
    )


def _task_started(task_id: str, *, source_id: str) -> ObservationEnvelope:
    return ObservationEnvelope.task_lifecycle(
        kind="task.started",
        task_id=task_id,
        source_kind="deerflow_run",
        source_id=source_id,
        occurred_at=_OCCURRED_AT,
        source_event_id=f"run:{source_id}:task:started",
    )


def _attempt(task_id: str, attempt_id: str, *, offset_seconds: int, total_tokens: int) -> tuple[ObservationEnvelope, ...]:
    occurred_at = _OCCURRED_AT + timedelta(seconds=offset_seconds)
    return (
        ObservationEnvelope(
            kind="llm.requested",
            occurred_at=occurred_at,
            task_id=task_id,
            subject_type="llm_attempt",
            subject_id=attempt_id,
            producer=_PRODUCER,
            source_event_id=f"attempt:{attempt_id}:requested",
            correlation_id=task_id,
            payload={
                "attempt_no": 1,
                "actor_kind": "system_operation",
                "operation_id": new_id(),
                "operation_kind": "other",
            },
        ),
        ObservationEnvelope(
            kind="llm.responded",
            occurred_at=occurred_at + timedelta(seconds=1),
            task_id=task_id,
            subject_type="llm_attempt",
            subject_id=attempt_id,
            producer=_PRODUCER,
            source_event_id=f"attempt:{attempt_id}:responded",
            correlation_id=task_id,
            payload={"attempt_no": 1, "latency_ms": 20, "usage": {"total_tokens": total_tokens}},
        ),
    )


def _authorized_tool_call(task_id: str, step_id: str, tool_call_id: str, snapshot_id: str) -> tuple[ObservationEnvelope, ...]:
    """A Step plus an authorized ToolCall -- the only evidence scope-safety reads.

    Recording this is what makes the backend queue a ``scope-safety`` assessor
    job at all, which is what the PB4 rollback scenario needs to take over.
    """

    authorization = AuthorizationSnapshot(
        snapshot_id=snapshot_id,
        tool_call_id=tool_call_id,
        policy_id="pg-multiworker-policy",
        policy_version="1",
        policy_hash="a" * 64,
        decision="allowed",
        details_available=False,
        evaluated_at=_OCCURRED_AT,
    )
    return (
        ObservationEnvelope(
            kind="step.started",
            occurred_at=_OCCURRED_AT,
            task_id=task_id,
            step_id=step_id,
            subject_type="step",
            subject_id=step_id,
            producer=_PRODUCER,
            source_event_id=f"step:{step_id}:started",
            correlation_id=task_id,
            payload={"step_seq": 1, "actor_kind": "lead_agent"},
        ),
        ObservationEnvelope(
            kind="tool.issued",
            occurred_at=_OCCURRED_AT,
            task_id=task_id,
            step_id=step_id,
            subject_type="tool_call",
            subject_id=tool_call_id,
            producer=_PRODUCER,
            source_event_id=f"tool:{tool_call_id}:issued",
            correlation_id=task_id,
            payload={
                "call_seq": 1,
                "provider_call_id": f"provider-{tool_call_id}",
                "tool_name": "write_file",
                "args_hash": "b" * 64,
                "args_preview": {"path": "workspace/pg-multiworker.md"},
                "tool_schema_block_id": None,
            },
        ),
        ObservationEnvelope(
            kind="authorization.allowed",
            occurred_at=_OCCURRED_AT,
            task_id=task_id,
            step_id=step_id,
            subject_type="authorization_snapshot",
            subject_id=snapshot_id,
            producer=_PRODUCER,
            source_event_id=f"authorization:{snapshot_id}:allowed",
            correlation_id=task_id,
            payload={"snapshot": authorization.model_dump(mode="json")},
        ),
    )


# ---------------------------------------------------------------------------
# Row helpers (every assertion below lands on rows, not on return values)
# ---------------------------------------------------------------------------


async def _projection_jobs(worker: _Worker) -> list[AnsichProjectionJobRow]:
    async with worker.sessions() as session:
        return list((await session.execute(sa.select(AnsichProjectionJobRow).order_by(AnsichProjectionJobRow.job_id))).scalars())


async def _projection_job(worker: _Worker, job_id: str) -> AnsichProjectionJobRow:
    async with worker.sessions() as session:
        row = await session.get(AnsichProjectionJobRow, job_id)
    assert row is not None
    return row


async def _set_projection_lease(worker: _Worker, job_id: str, expires_at: datetime) -> None:
    async with worker.sessions() as session, session.begin():
        await session.execute(sa.update(AnsichProjectionJobRow).where(AnsichProjectionJobRow.job_id == job_id).values(lease_expires_at=expires_at))


async def _set_assessor_lease(worker: _Worker, job_id: str, expires_at: datetime) -> None:
    async with worker.sessions() as session, session.begin():
        await session.execute(sa.update(AnsichAssessorJobRow).where(AnsichAssessorJobRow.job_id == job_id).values(lease_expires_at=expires_at))


async def _assessor_marks(worker: _Worker) -> dict[tuple[str, str, str], int]:
    """Every durable ``(subject, assessor, version) -> evidence watermark`` mark."""

    async with worker.sessions() as session:
        return {(row.subject_id, row.assessor_name, row.assessor_version): row.evidence_watermark for row in (await session.execute(sa.select(AnsichAssessorWatermarkRow))).scalars()}


async def _row_count(worker: _Worker, model: type) -> int:
    async with worker.sessions() as session:
        return int(await session.scalar(sa.select(sa.func.count()).select_from(model)) or 0)


async def _projection_errors(worker: _Worker) -> list[tuple[str, int, str, str]]:
    """Durable projection-error evidence, carried into the assertion message.

    A bare count says "something failed"; the type and message say *what*, which
    is the difference between a concurrency defect and a documented one-attempt
    contention cost.
    """

    async with worker.sessions() as session:
        return [
            (row.job_id, row.attempt, row.error_type, " ".join(row.message.split())[:600])
            for row in (await session.execute(sa.select(ansich_sql.AnsichProjectionErrorRow).order_by(ansich_sql.AnsichProjectionErrorRow.occurred_at))).scalars()
        ]


def _unsettled(rows: list[AnsichProjectionJobRow]) -> list[tuple[str, str, str, int, str | None]]:
    """Jobs that did not end ``completed``, with the evidence to explain why."""

    return [(row.job_id, row.projector_name, row.status, row.attempts, row.last_error) for row in rows if row.status != "completed"]


async def _drain_projections(*workers: _Worker, rounds: int = 200) -> None:
    """Project everything, one worker at a time -- a deterministic setup step."""

    for _ in range(rounds):
        moved = 0
        for worker in workers:
            moved += await worker.backend.project_pending(limit=50)
        if not moved:
            return
    raise AssertionError("projection did not settle within the bounded drain")


async def _settle_projections(*workers: _Worker, nudges: int = 10) -> None:
    """Drain, then pull any backed-off job forward and drain again.

    A job re-armed to ``retry`` carries an ``available_at`` in the future, so a
    plain drain stops with it still outstanding -- the backlog is not finished,
    it is merely not claimable *yet*. Waiting out the backoff would put a real
    clock in the middle of the assertion; bringing ``available_at`` forward is
    the same injection the lease tests use for expiry, and it keeps "did this
    backlog settle?" a question about the work rather than about how long the
    test was willing to sit there.
    """

    for _ in range(nudges):
        await _drain_projections(*workers)
        rows = await _projection_jobs(workers[0])
        if not _unsettled(rows):
            return
        async with workers[0].sessions() as session, session.begin():
            await session.execute(
                sa.update(AnsichProjectionJobRow).where(AnsichProjectionJobRow.status.in_(("pending", "retry"))).values(available_at=_OCCURRED_AT),
            )
    await _drain_projections(*workers)


async def _advisory_lock_holders(engine: AsyncEngine) -> int:
    """How many backends hold the Ansich maintenance advisory lock right now.

    ``pg_advisory_lock(bigint)`` splits its key across ``pg_locks.classid`` (the
    high 32 bits) and ``pg_locks.objid`` (the low 32), which is why this cannot
    just compare one column.
    """

    async with engine.connect() as connection:
        return int(
            (
                await connection.execute(
                    sa.text("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND classid = :classid AND objid = :objid AND granted"),
                    {
                        "classid": _PG_MAINTENANCE_LOCK_KEY >> 32,
                        "objid": _PG_MAINTENANCE_LOCK_KEY & 0xFFFFFFFF,
                    },
                )
            ).scalar()
            or 0
        )


# ===========================================================================
# 1. Claim exclusion under a real SKIP LOCKED
# ===========================================================================


async def test_two_workers_claiming_concurrently_never_share_a_job() -> None:
    """No job is handed to two workers, and the rows say so, not a return value.

    This is the half SQLite structurally cannot answer. ``skip_locked`` renders
    as nothing there and one writer at a time makes disjointness free, so the
    claim predicate has only ever been proven by reading it. Here two workers
    with independent pools run their claim loops against one backlog for real.

    **Nothing projects while the claiming happens, and that is the design of
    the test rather than a simplification.** With projection in the loop a
    second claim of one job is *legal* -- a job re-armed by a dependency wait or
    a spent attempt is released and then legitimately claimed again, possibly by
    the peer -- and an overlap assertion could no longer tell that apart from
    two owners at once. Claiming alone has no such ambiguity: a claim takes a
    30-second lease and nothing here releases it, so every job is claimable
    exactly once and a duplicate could only be ``skip_locked`` failing. Each
    worker then settles precisely what it claimed, which is the completion half
    on rows: every job ``completed``, every generation exactly 1, every claim
    owned by the worker the log says claimed it, and no dropped write on either
    side.
    """

    async with _two_workers() as (_url, worker_a, worker_b):
        observations = [_task_created(new_id(), source_id=f"run-claim-exclusion-{index}") for index in range(12)]
        await worker_a.backend.persist_and_project(observations)
        all_job_ids = {row.job_id for row in await _projection_jobs(worker_a)}
        assert len(all_job_ids) >= len(observations), "fixture produced fewer jobs than Observations"

        async def claim_everything(worker: _Worker) -> list[tuple[str, int]]:
            """Claim until the backlog is really empty, not until one claim misses.

            ``None`` means "nothing claimable **at this instant**", and under two
            concurrent claimers that is not the same as "the backlog is empty":
            every remaining row can be locked by the peer's in-flight claim
            transaction, which ``skip_locked`` correctly steps over. Treating the
            first miss as the end lets both loops walk away from a job neither
            took. Retrying past a miss cannot manufacture a duplicate -- once the
            peer's claim commits, the row is ``processing`` under a live lease
            and the claim predicate excludes it -- so the retry costs nothing the
            assertions care about.
            """

            taken: list[tuple[str, int]] = []
            misses = 0
            while misses < _CLAIM_MISSES_BEFORE_DRAINED:
                claim = await worker.backend._claim_projection_job()
                if claim is None:
                    misses += 1
                    # Long enough for a peer claim that is mid-round-trip to
                    # commit; a genuinely empty backlog just costs this thrice.
                    await asyncio.sleep(0.05)
                    continue
                misses = 0
                taken.append((claim[0], claim[-1]))
                assert len(taken) <= len(all_job_ids), "a claim loop took more jobs than exist"
                # Yield so the peer's loop genuinely interleaves rather than
                # running to completion inside one scheduling slice.
                await asyncio.sleep(0)
            return taken

        claimed_a, claimed_b = await asyncio.wait_for(
            asyncio.gather(claim_everything(worker_a), claim_everything(worker_b)),
            timeout=_SCRIPT_TIMEOUT_SECONDS,
        )

        ids_a = [job_id for job_id, _generation in claimed_a]
        ids_b = [job_id for job_id, _generation in claimed_b]
        assert claimed_a and claimed_b, "one worker claimed nothing; the run proves no exclusion"
        duplicates = [job_id for job_id, count in Counter(ids_a + ids_b).items() if count > 1]
        assert not duplicates, f"skip_locked handed the same job out more than once: {sorted(duplicates)}"
        assert set(ids_a + ids_b) == all_job_ids, "the two loops did not between them drain the backlog"

        # Rows, not the claim log: each job is held once, by the worker the log
        # names, at generation 1.
        held = {row.job_id: (row.status, row.lease_owner, row.lease_generation) for row in await _projection_jobs(worker_b)}
        for label, worker, ids in (("a", worker_a, ids_a), ("b", worker_b, ids_b)):
            wrong = [(job_id, held[job_id]) for job_id in ids if held[job_id] != ("processing", worker.backend._lease_owner, 1)]
            assert not wrong, f"worker {label}'s claims are not what the rows say: {wrong}"

        # The completion half: each worker settles exactly its own claims, and
        # neither has a write dropped -- which is what a shared job would cause.
        for worker, claims in ((worker_a, claimed_a), (worker_b, claimed_b)):
            async with worker.sessions() as session, session.begin():
                for job_id, generation in claims:
                    assert await worker.backend._complete_projection_job(session, job_id=job_id, lease_generation=generation) is True

        assert (worker_a.backend.stale_completion_count, worker_b.backend.stale_completion_count) == (0, 0)
        assert not _unsettled(await _projection_jobs(worker_a))


# ===========================================================================
# 2. Completion CAS under a real takeover
# ===========================================================================


async def test_a_completion_after_a_real_takeover_is_dropped_on_postgres() -> None:
    """The dialect-independent half was T2's; this is the real-server half.

    ``_complete_projection_job``'s guard is a rowcount on ``WHERE job_id = :id
    AND lease_generation = :claimed``. Rowcount semantics for a no-match UPDATE
    are a driver/dialect property, and the whole drop-silently contract rests on
    them, so the guard is exercised here against asyncpg rather than aiosqlite.
    """

    async with _two_workers() as (_url, worker_a, worker_b):
        task_id = new_id()
        await worker_a.backend.persist_and_project([_task_created(task_id, source_id="run-cas-takeover")])

        a_claim = await worker_a.backend._claim_projection_job()
        assert a_claim is not None
        job_id = a_claim[0]

        # Leave exactly one claimable job so B is forced onto A's row rather
        # than picking up a sibling projector's job for the same Observation.
        async with worker_b.sessions() as session, session.begin():
            await session.execute(sa.update(AnsichProjectionJobRow).where(AnsichProjectionJobRow.job_id != job_id).values(status="completed"))
        await _set_projection_lease(worker_b, job_id, _EXPIRED_AT)

        b_claim = await worker_b.backend._claim_projection_job()
        assert b_claim is not None
        assert b_claim[0] == job_id
        assert b_claim[-1] == a_claim[-1] + 1

        async with worker_a.sessions() as session, session.begin():
            stale = await worker_a.backend._complete_projection_job(session, job_id=job_id, lease_generation=a_claim[-1])

        assert stale is False
        assert worker_a.backend.stale_completion_count == 1
        after_stale = await _projection_job(worker_b, job_id)
        assert after_stale.status == "processing"
        assert after_stale.lease_owner == worker_b.backend._lease_owner
        assert after_stale.lease_generation == b_claim[-1]

        async with worker_b.sessions() as session, session.begin():
            settled = await worker_b.backend._complete_projection_job(session, job_id=job_id, lease_generation=b_claim[-1])

        assert settled is True
        assert worker_b.backend.stale_completion_count == 0
        after_owner = await _projection_job(worker_a, job_id)
        assert (after_owner.status, after_owner.lease_owner, after_owner.lease_generation) == ("completed", None, b_claim[-1])


# ===========================================================================
# 3. The maintenance advisory lock
# ===========================================================================


async def test_the_maintenance_lock_excludes_a_second_operator() -> None:
    """``pg_advisory_lock`` really serialises two operators (RB5).

    T2 could only prove *dispatch* -- a recording stub saw the acquire and the
    release go out. Whether the acquire actually excludes anybody is a server
    property, and this is where it is checked: worker B enters the guarded
    region only after worker A has left it, and while A holds it exactly one
    backend shows up in ``pg_locks``.
    """

    async with _two_workers() as (_url, worker_a, worker_b):
        order: list[str] = []
        a_holding = asyncio.Event()
        holders_while_a_holds: list[int] = []

        async def hold(worker: _Worker) -> None:
            async with worker.backend._maintenance_lock():
                order.append("a-enter")
                a_holding.set()
                holders_while_a_holds.append(await _advisory_lock_holders(worker.engine))
                await asyncio.sleep(0.5)
                order.append("a-exit")

        async def queue(worker: _Worker) -> None:
            await a_holding.wait()
            # Give A's hold a real head start so "B ran second" is a statement
            # about the lock rather than about scheduling luck.
            await asyncio.sleep(0.1)
            async with worker.backend._maintenance_lock():
                order.append("b-enter")
            order.append("b-exit")

        await asyncio.wait_for(asyncio.gather(hold(worker_a), queue(worker_b)), timeout=_SCRIPT_TIMEOUT_SECONDS)

        assert order == ["a-enter", "a-exit", "b-enter", "b-exit"]
        assert holders_while_a_holds == [1]
        assert await _advisory_lock_holders(worker_a.engine) == 0

        # And the boundary, stated rather than assumed: a *claim* is not gated
        # by this lock. Claims stay exclusive through `skip_locked` and the
        # generation CAS; the advisory lock is what makes rebuild/retry
        # single-operator. Documenting the boundary keeps the next reader from
        # expecting the lock to quiesce the projectors.
        claim = await worker_b.backend._claim_projection_job()
        assert claim is None  # nothing pending; the point is that it returned.


async def test_the_maintenance_lock_is_released_after_a_mid_operation_dbapi_failure() -> None:
    """Rollback-then-unlock: the unlock still reaches the holder (T2 carry).

    ``_maintenance_lock``'s ``finally`` rolls its pinned connection back *before*
    it unlocks, because after a DBAPI error every further ``execute`` on that
    connection raises client-side before reaching PostgreSQL -- so an unlock
    issued first would be swallowed by the handler and the advisory lock would be
    held until the connection closed. A session-level advisory lock survives
    ``ROLLBACK``, so the ordering works.

    The staging has to reach **the lock's own connection**, which is the whole
    point: an error on any other connection proves nothing about this one. The
    lock takes it from ``bind.connect()``, and an ``AsyncEngine``'s ``connect``
    is read-only per instance, so it is captured with a restored class-level
    patch that only records for this worker's engine. The recording stub in
    ``tests/ansich/test_lease_cas.py`` owns the statement *order*; what needs a
    server is that the unlock lands on the holder and that the lock is then
    genuinely free for a second operator.
    """

    async with _two_workers() as (_url, worker_a, worker_b):
        pinned: list[object] = []
        original_connect = AsyncEngine.connect

        # NOT PARALLEL-SAFE WITHIN ONE PROCESS. The patch below replaces
        # ``connect`` on the *class*, so it is process-global for as long as it
        # is installed: every ``AsyncEngine`` in this interpreter — including
        # any other test's, and the projector loops of both workers here — goes
        # through it. It is filtered by identity (`self is worker_a.engine`) so
        # it only *records* for this engine, and it is undone in a ``finally``,
        # but a second test running concurrently in the same process would
        # still execute this wrapper on its own connects. This tier must
        # therefore not be run with an in-process parallel runner
        # (``pytest-xdist``'s process workers are fine — each has its own
        # interpreter); the class attribute is the only handle available,
        # because ``AsyncEngine.connect`` is read-only per instance.
        def recording_connect(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            connection = original_connect(self, *args, **kwargs)
            if self is worker_a.engine:
                pinned.append(connection)
            return connection

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(AsyncEngine, "connect", recording_connect)
        try:
            with pytest.raises(RuntimeError, match="rebuild exploded"):
                async with worker_a.backend._maintenance_lock():
                    assert len(pinned) == 1, "the lock did not take exactly one connection off worker A's engine"
                    lock_connection = pinned[0]
                    assert await _advisory_lock_holders(worker_b.engine) == 1

                    with pytest.raises(DBAPIError):
                        await lock_connection.execute(sa.text("SELECT 1 / 0"))  # type: ignore[attr-defined]
                    # The connection is now inactive: this is the state that
                    # makes the rollback-first ordering necessary, and without
                    # it the unlock below would never reach the server.
                    with pytest.raises(Exception):  # noqa: B017 - PendingRollbackError family
                        await lock_connection.execute(sa.text("SELECT 1"))  # type: ignore[attr-defined]
                    raise RuntimeError("rebuild exploded mid-flight")
        finally:
            monkeypatch.undo()

        assert await _advisory_lock_holders(worker_b.engine) == 0
        # The lock is genuinely free, not merely absent from a stale view.
        async with worker_b.backend._maintenance_lock():
            assert await _advisory_lock_holders(worker_a.engine) == 1


async def test_a_second_rebuild_waits_for_the_first_and_both_leave_jobs_settled() -> None:
    """Two concurrent rebuilds serialise and converge (RB5, end to end)."""

    async with _two_workers() as (_url, worker_a, worker_b):
        for index in range(4):
            await worker_a.backend.persist_and_project([_task_created(new_id(), source_id=f"run-rebuild-{index}")])
        await _drain_projections(worker_a)

        results = await asyncio.wait_for(
            asyncio.gather(worker_a.backend.rebuild_projections(), worker_b.backend.rebuild_projections()),
            timeout=_SCRIPT_TIMEOUT_SECONDS,
        )
        assert all(outcome.replayed >= 0 for outcome in results)

        await _settle_projections(worker_a, worker_b)
        rows = await _projection_jobs(worker_a)
        assert not _unsettled(rows)
        assert await _row_count(worker_a, ansich_sql.AnsichProjectionErrorRow) == 0


# ===========================================================================
# 4. F10-6 / F10-20: the lost update, falsified
# ===========================================================================


# The three attempts the fixture below projects. The first stays durable and is
# what the summary is already correct for; the other two are the contributions
# the two workers land concurrently. Distinct, non-summing values so no wrong
# outcome can coincide with a right one.
_SETTLED_TOKENS = 7
_A_TOKENS = 41
_B_TOKENS = 59


@asynccontextmanager
async def _a_settled_summary_and_two_late_contributions(worker_a: _Worker, worker_b: _Worker) -> AsyncIterator[tuple[str, dict, dict]]:
    """A correct ``total_tokens`` summary, plus two contributions about to land.

    All three contributions are produced by the real usage projector, so their
    Observation joins, ingest sequences and ``as_of`` values are genuine; two are
    then lifted back out and the summary recomputed. That reconstructs exactly
    the state the two-worker script starts from and nothing else: a summary that
    is *correct* for everything committed, with two new contributions inbound.

    Two of them, not one, and that matters. If only one contribution were new,
    the worker holding it would read the summary, recompute the same number and
    write nothing at all -- SQLAlchemy emits no ``SET value`` for an unchanged
    attribute -- so the interleaving could not lose anything and the comparison
    would prove nothing. Two concurrent arrivals is also the production shape:
    ``_project_usage`` stores a contribution and refreshes the summary in one
    transaction, and two leased workers do that for sibling Observations at once.
    """

    task_id = new_id()
    await worker_a.backend.persist_and_project(
        [
            _task_created(task_id, source_id="run-lost-update"),
            _task_started(task_id, source_id="run-lost-update"),
            *_attempt(task_id, new_id(), offset_seconds=1, total_tokens=_SETTLED_TOKENS),
            *_attempt(task_id, new_id(), offset_seconds=5, total_tokens=_A_TOKENS),
            *_attempt(task_id, new_id(), offset_seconds=9, total_tokens=_B_TOKENS),
        ]
    )
    await _drain_projections(worker_a)

    async with worker_a.sessions() as session:
        contributions = list(
            (
                await session.execute(
                    sa.select(AnsichUsageContributionRow)
                    .where(
                        AnsichUsageContributionRow.aggregate_task_id == task_id,
                        AnsichUsageContributionRow.dimension == "total_tokens",
                    )
                    .order_by(AnsichUsageContributionRow.as_of)
                )
            ).scalars()
        )
    assert [row.delta for row in contributions] == [_SETTLED_TOKENS, _A_TOKENS, _B_TOKENS], f"fixture did not produce the three contributions: {contributions}"

    def _values(row: AnsichUsageContributionRow) -> dict:
        return {
            "aggregate_task_id": row.aggregate_task_id,
            "source_task_id": row.source_task_id,
            "dimension": row.dimension,
            "source_obs_id": row.source_obs_id,
            "delta": row.delta,
            "as_of": row.as_of,
        }

    late = [_values(row) for row in contributions[1:]]
    async with worker_a.sessions() as session, session.begin():
        for values in late:
            await session.execute(
                sa.delete(AnsichUsageContributionRow).where(
                    AnsichUsageContributionRow.aggregate_task_id == values["aggregate_task_id"],
                    AnsichUsageContributionRow.source_task_id == values["source_task_id"],
                    AnsichUsageContributionRow.dimension == values["dimension"],
                    AnsichUsageContributionRow.source_obs_id == values["source_obs_id"],
                )
            )
    async with worker_a.sessions() as session, session.begin():
        await worker_a.backend._refresh_usage_summary(
            session,
            task_id=task_id,
            dimension="total_tokens",
            aggregation_scope="local",
            updated_at=_OCCURRED_AT,
        )
    assert await _local_total_tokens(worker_b, task_id) == _SETTLED_TOKENS
    yield task_id, late[0], late[1]


async def _local_total_tokens(worker: _Worker, task_id: str) -> int | None:
    async with worker.sessions() as session:
        return await session.scalar(
            sa.select(AnsichTaskUsageRow.value).where(
                AnsichTaskUsageRow.task_id == task_id,
                AnsichTaskUsageRow.dimension == "total_tokens",
                AnsichTaskUsageRow.aggregation_scope == "local",
            )
        )


async def _run_sibling_rollup_script(worker_a: _Worker, worker_b: _Worker, task_id: str, a_values: dict, b_values: dict) -> None:
    """One interleaving, run identically against both shapes.

    Each worker does what ``_project_usage`` does for a sibling Observation --
    store its contribution and refresh the summary, in one transaction. Worker A
    is paused right after it has read the contribution set, and worker B runs its
    whole transaction inside that pause. The *only* thing that differs between
    the red and green runs is whether A's target read carried ``FOR UPDATE`` --
    precisely the conversion F10-6/F10-20 made -- so a difference in outcome is
    attributable to the lock and to nothing else.
    """

    a_read_done = asyncio.Event()
    b_done = asyncio.Event()
    state = {"paused": False}

    async def pause_after_reading_the_contributions(statement: object) -> None:
        if state["paused"] or "ansich_usage_contributions" not in _statement_text(statement):
            return
        state["paused"] = True
        a_read_done.set()
        # In the green run B is blocked on A's row lock and never finishes, so
        # this budget is expected to elapse. That is the lock working, not a
        # failure, which is why it is suppressed rather than asserted on.
        with contextlib.suppress(TimeoutError, asyncio.TimeoutError):
            await asyncio.wait_for(b_done.wait(), timeout=_INTERLEAVE_TIMEOUT_SECONDS)

    worker_a.session_class.after_execute = staticmethod(pause_after_reading_the_contributions)  # type: ignore[assignment]
    try:

        async def store_and_refresh(worker: _Worker, values: dict, offset: int) -> None:
            async with worker.sessions() as session, session.begin():
                session.add(AnsichUsageContributionRow(**values))
                await worker.backend._refresh_usage_summary(
                    session,
                    task_id=task_id,
                    dimension="total_tokens",
                    aggregation_scope="local",
                    updated_at=_OCCURRED_AT + timedelta(seconds=offset),
                )

        async def run_a() -> None:
            await store_and_refresh(worker_a, a_values, 30)

        async def run_b() -> None:
            await a_read_done.wait()
            try:
                await store_and_refresh(worker_b, b_values, 31)
            finally:
                b_done.set()

        await asyncio.wait_for(asyncio.gather(run_a(), run_b()), timeout=_SCRIPT_TIMEOUT_SECONDS)
    finally:
        worker_a.session_class.after_execute = None  # type: ignore[assignment]
    assert state["paused"], "the script never reached the interleaving point"


async def test_the_pre_fix_unlocked_read_loses_a_sibling_workers_update() -> None:
    """RED on the pre-fix shape: the lost update F10-6/F10-20 was about.

    The pre-fix shape is restored on ONE worker only, by monkeypatching
    ``_lock_rollup_targets`` to drop the ``FOR UPDATE`` for that worker's
    sessions. ``monkeypatch`` restores the module attribute afterwards, and the
    dispatch keeps worker B on the committed code -- so this is a two-shape
    comparison inside one process, not a global regression of the module.

    The loss is concrete and is a *number*, not a status: both contributions are
    durable rows afterwards, so the true local total is 7 + 41 + 59 = 107. B
    computes 7 + 59 (A's row is not committed yet, and without A's lock nothing
    made B wait for it) and A then overwrites that with 7 + 41, taking ``as_of``
    and ``complete_through_ingest_seq`` down with it. Every rollup in the
    F10-6/F10-20 family is this same read-modify-write, which is why one
    falsification settles the class rather than one call site.
    """

    async with _two_workers() as (_url, worker_a, worker_b):
        async with _a_settled_summary_and_two_late_contributions(worker_a, worker_b) as (task_id, a_values, b_values):
            original = ansich_sql._lock_rollup_targets

            async def unlocked_for_worker_a(session, statement):
                if isinstance(session, worker_a.session_class) and "ansich_task_usage" in _statement_text(statement):
                    return list((await session.execute(statement)).scalars())
                return await original(session, statement)

            monkeypatch = pytest.MonkeyPatch()
            monkeypatch.setattr(ansich_sql, "_lock_rollup_targets", unlocked_for_worker_a)
            try:
                await _run_sibling_rollup_script(worker_a, worker_b, task_id, a_values, b_values)
            finally:
                monkeypatch.undo()

            lost = await _local_total_tokens(worker_a, task_id)
            assert lost != _SETTLED_TOKENS + _A_TOKENS + _B_TOKENS, "the pre-fix shape did not lose the update; the falsification is inconclusive"
            assert lost == _SETTLED_TOKENS + _A_TOKENS
            # And the contribution really is durable -- the summary is wrong
            # about rows that are sitting right there, which is what makes this
            # a lost update rather than a missing input.
            assert await _row_count(worker_b, AnsichUsageContributionRow) >= 3


async def test_the_committed_lock_then_read_survives_the_same_interleaving() -> None:
    """GREEN on the committed shape: same script, the lock is the only change."""

    async with _two_workers() as (_url, worker_a, worker_b):
        async with _a_settled_summary_and_two_late_contributions(worker_a, worker_b) as (task_id, a_values, b_values):
            await _run_sibling_rollup_script(worker_a, worker_b, task_id, a_values, b_values)
            assert await _local_total_tokens(worker_a, task_id) == _SETTLED_TOKENS + _A_TOKENS + _B_TOKENS


# ===========================================================================
# 5. The usage fan-out lock ordering
# ===========================================================================


async def test_two_workers_fanning_over_overlapping_ancestors_both_complete() -> None:
    """The ordered traversal's real proof: overlapping fan-outs do not deadlock.

    A parent Task and its spawned child both carry usage, so a contribution for
    the child locks ``{child, parent}`` while one for the parent locks
    ``{parent}`` -- overlapping target sets taken by two independent workers
    inside their own transactions. ``sorted(...)`` in ``_project_usage`` is what
    makes the two orders agree; the companion test below shows what a
    disagreement costs on this server.
    """

    async with _two_workers() as (_url, worker_a, worker_b):
        parent_id, child_id = new_id(), new_id()
        step_id, tool_call_id = new_id(), new_id()
        await worker_a.backend.persist_and_project(
            [
                _task_created(parent_id, source_id="run-fanout-parent"),
                _task_started(parent_id, source_id="run-fanout-parent"),
                ObservationEnvelope(
                    kind="step.started",
                    occurred_at=_OCCURRED_AT,
                    task_id=parent_id,
                    step_id=step_id,
                    subject_type="step",
                    subject_id=step_id,
                    producer=_PRODUCER,
                    source_event_id=f"step:{step_id}:started",
                    correlation_id=parent_id,
                    payload={"step_seq": 1, "actor_kind": "lead_agent"},
                ),
                ObservationEnvelope(
                    kind="tool.issued",
                    occurred_at=_OCCURRED_AT,
                    task_id=parent_id,
                    step_id=step_id,
                    subject_type="tool_call",
                    subject_id=tool_call_id,
                    producer=_PRODUCER,
                    source_event_id=f"tool:{tool_call_id}:issued",
                    correlation_id=parent_id,
                    payload={
                        "call_seq": 1,
                        "provider_call_id": f"provider-{tool_call_id}",
                        "tool_name": "task",
                        "args_hash": "c" * 64,
                        "args_preview": {},
                        "tool_schema_block_id": None,
                    },
                ),
                ObservationEnvelope.task_lifecycle(
                    kind="task.created",
                    task_id=child_id,
                    source_kind="deerflow_subagent",
                    source_id="provider-task-call",
                    occurred_at=_OCCURRED_AT + timedelta(seconds=2),
                    source_event_id=f"deerflow_subagent:{child_id}:task:created",
                    attributes={
                        "parent_task_id": parent_id,
                        "spawning_step_id": step_id,
                        "spawning_tool_call_id": tool_call_id,
                        "subagent_name": "researcher",
                    },
                ),
            ]
        )
        await _drain_projections(worker_a)

        # Both workers now project usage for the two Tasks concurrently.
        await worker_a.backend.persist_and_project(
            [
                *_attempt(parent_id, new_id(), offset_seconds=10, total_tokens=7),
                *_attempt(child_id, new_id(), offset_seconds=11, total_tokens=13),
                *_attempt(parent_id, new_id(), offset_seconds=12, total_tokens=17),
                *_attempt(child_id, new_id(), offset_seconds=13, total_tokens=23),
            ]
        )

        async def project(worker: _Worker) -> None:
            for _ in range(200):
                if not await worker.backend.project_pending(limit=2):
                    return
                await asyncio.sleep(0)
            raise AssertionError("a worker's projection loop did not settle")

        await asyncio.wait_for(asyncio.gather(project(worker_a), project(worker_b)), timeout=_SCRIPT_TIMEOUT_SECONDS)

        await _settle_projections(worker_a, worker_b)
        rows = await _projection_jobs(worker_a)
        assert not _unsettled(rows)

        # The claim under test is "no deadlock", and that is asserted by name.
        #
        # "No contention at all" is a different and *false* claim, so it is not
        # made: this run intermittently records a first-writer
        # ``UniqueViolationError`` on ``ansich_llm_attempts_pkey`` (roughly one
        # run in ten here). Both Observations of one attempt (``llm.requested``
        # and ``llm.responded``) are separate jobs, two workers can hold them at
        # once, and neither can lock an ``attempt_id`` row that does not exist
        # yet -- so both insert it and one loses.
        # That is the same shape the four rollups closed with
        # ``INSERT … ON CONFLICT DO NOTHING`` (F10-6/F10-20) at a call site
        # outside that scope; it is not corrupting (the loser re-arms to
        # ``retry`` and the next claim converges, which is what the settled
        # backlog and the exact sums below say), and closing it belongs to
        # whoever owns that projector, not to this tier. Tolerated by *shape*
        # rather than by count, so a different error still fails here.
        errors = await _projection_errors(worker_a)
        deadlocked = [item for item in errors if "deadlock" in item[3].lower()]
        assert not deadlocked, f"the ordered fan-out still deadlocked: {deadlocked}"
        # Typed by CONSTRAINT IDENTITY, not just error class: only the known
        # F10-31 first-writer race on the attempt row is tolerated. A duplicate
        # on any OTHER constraint (a re-opened rollup conflict, an episode
        # collision leaking here) must fail this test, not be absorbed.
        unexpected = [item for item in errors if item[2] != "IntegrityError" or "ansich_llm_attempts_pkey" not in item[3]]
        assert not unexpected, f"unexpected projection errors under concurrent fan-out: {unexpected}"

        async with worker_b.sessions() as session:
            summaries = {(row.task_id, row.aggregation_scope): row.value for row in (await session.execute(sa.select(AnsichTaskUsageRow).where(AnsichTaskUsageRow.dimension == "total_tokens"))).scalars()}
        assert summaries[(parent_id, "local")] == 24
        assert summaries[(child_id, "local")] == 36
        assert summaries[(parent_id, "inclusive")] == 60


async def test_reversing_the_lock_traversal_order_deadlocks_on_postgres() -> None:
    """What the ordering buys, demonstrated by removing it.

    Two workers take the same two rollup targets in opposite orders and
    PostgreSQL aborts one of them; taking them in the same (sorted) order lets
    both through. This is the pre-fix evidence for the traversal ordering the
    usage fan-out, the read-model refresh and the spawn backfill all carry --
    the ordering is not an aesthetic choice, it is the difference between these
    two outcomes on this server.
    """

    async with _two_workers() as (_url, worker_a, worker_b):
        task_id = new_id()
        await worker_a.backend.persist_and_project(
            [
                _task_created(task_id, source_id="run-deadlock"),
                _task_started(task_id, source_id="run-deadlock"),
                *_attempt(task_id, new_id(), offset_seconds=1, total_tokens=11),
            ]
        )
        await _drain_projections(worker_a)

        async with worker_a.sessions() as session:
            dimensions = sorted({row.dimension for row in (await session.execute(sa.select(AnsichTaskUsageRow).where(AnsichTaskUsageRow.task_id == task_id, AnsichTaskUsageRow.aggregation_scope == "local"))).scalars()})
        assert len(dimensions) >= 2, f"need two lockable summary rows, got {dimensions}"
        first, second = dimensions[0], dimensions[1]

        def _target(dimension: str):
            return sa.select(AnsichTaskUsageRow).where(
                AnsichTaskUsageRow.task_id == task_id,
                AnsichTaskUsageRow.dimension == dimension,
                AnsichTaskUsageRow.aggregation_scope == "local",
            )

        async def lock_in_order(worker: _Worker, order: tuple[str, str], mine: asyncio.Event, theirs: asyncio.Event) -> None:
            async with worker.sessions() as session, session.begin():
                rows = await ansich_sql._lock_rollup_targets(session, _target(order[0]))
                assert rows, f"{order[0]} summary row is missing; the script would prove nothing"
                mine.set()
                # In the same-order run the peer is blocked on the row this
                # worker just took and will never signal, so the budget elapses.
                with contextlib.suppress(TimeoutError, asyncio.TimeoutError):
                    await asyncio.wait_for(theirs.wait(), timeout=_INTERLEAVE_TIMEOUT_SECONDS)
                await ansich_sql._lock_rollup_targets(session, _target(order[1]))

        async def run(order_b: tuple[str, str]) -> list[BaseException | None]:
            a_ready, b_ready = asyncio.Event(), asyncio.Event()
            return await asyncio.wait_for(
                asyncio.gather(
                    lock_in_order(worker_a, (first, second), a_ready, b_ready),
                    lock_in_order(worker_b, order_b, b_ready, a_ready),
                    return_exceptions=True,
                ),
                timeout=_SCRIPT_TIMEOUT_SECONDS,
            )

        crossed = await run((second, first))
        deadlocks = [item for item in crossed if isinstance(item, DBAPIError) and "deadlock" in str(item).lower()]
        assert len(deadlocks) == 1, f"crossed lock orders did not produce exactly one deadlock abort: {crossed}"

        agreed = await run((first, second))
        assert [item for item in agreed if isinstance(item, BaseException)] == [], f"the sorted order still aborted: {agreed}"


# ===========================================================================
# 6. PB4 / PB5: a stale assessor completion rolls its whole evaluation back
# ===========================================================================


async def test_a_stale_assessor_completion_rolls_the_whole_evaluation_back() -> None:
    """The assessor path's drop costs the evaluation, not just the settlement.

    Projection idempotency is the backstop that makes a dropped *projection*
    completion safe. An assessor evaluation also advances
    ``ansich_assessor_watermarks``, which is a claim about what has been judged
    and which the next owner reads as its own window's lower bound -- so
    committing it while dropping the job status would tell the new owner a band
    nobody judged is covered. ``_complete_assessor_job`` returning ``False``
    therefore raises ``_StaleAssessorClaim`` inside the evaluation's transaction.

    The reasoning behind that ruling talked about PostgreSQL specifically (READ
    COMMITTED, and a rollback that has to discard everything the session's
    identity map accumulated), so it is checked here rather than only on SQLite:
    after the drop the mark, the conclusions and the alert episodes are all
    absent, and nothing is charged as a failure.
    """

    async with _two_workers() as (_url, worker_a, worker_b):
        task_id, step_id = new_id(), new_id()
        tool_call_id, snapshot_id = new_id(), new_id()
        await worker_a.backend.persist_and_project(
            [
                _task_created(task_id, source_id="run-assessor-rollback"),
                _task_started(task_id, source_id="run-assessor-rollback"),
                *_authorized_tool_call(task_id, step_id, tool_call_id, snapshot_id),
            ]
        )
        await _drain_projections(worker_a)

        async with worker_a.sessions() as session:
            pending = list((await session.execute(sa.select(AnsichAssessorJobRow).where(AnsichAssessorJobRow.assessor_name == SCOPE_SAFETY_ASSESSOR.name))).scalars())
        assert pending, "the fixture queued no scope-safety assessor job"

        record: dict[str, object] = {}
        original_claim = worker_a.backend._claim_assessor_job

        async def claim_then_lose_the_lease():
            if "a" in record:
                # One evaluation only. ``_process_assessor_jobs`` drains, and a
                # second job settling normally would write a mark of its own --
                # which says nothing about whether the *stale* evaluation's mark
                # rolled back, the single thing this script is about.
                return None
            claim = await original_claim()
            if claim is not None:
                record["a"] = claim
                await _set_assessor_lease(worker_a, claim.job_id, _EXPIRED_AT)
                record["b"] = await worker_b.backend._claim_assessor_job()
                # The mark as it stands once both claims have committed. Claim
                # *widening* is deliberately written in the claim's own
                # transaction (it has to survive an evaluation rollback, or an
                # absorbed sibling's evidence would be re-derivable by nobody),
                # so "the evaluation rolled back" is not "no mark row exists" --
                # it is "the mark did not move past what the claims set".
                record["marks"] = await _assessor_marks(worker_b)
            return claim

        worker_a.backend._claim_assessor_job = claim_then_lose_the_lease  # type: ignore[method-assign]

        await worker_a.backend._process_assessor_jobs(now=_OCCURRED_AT + timedelta(minutes=1), incomplete_tasks=frozenset(), global_loss=False)

        a_claim = record["a"]
        b_claim = record["b"]
        assert b_claim is not None
        assert b_claim.job_id == a_claim.job_id  # type: ignore[union-attr]
        assert b_claim.lease_generation == a_claim.lease_generation + 1  # type: ignore[union-attr]

        assert worker_a.backend.stale_completion_count == 1
        # The whole evaluation went back: the mark stands where the claims left
        # it, and nothing the evaluation would have written is durable.
        assert await _assessor_marks(worker_b) == record["marks"]
        assert await _row_count(worker_b, AnsichScopeConclusionRow) == 0
        assert await _row_count(worker_b, AnsichAlertRow) == 0
        # And it is not charged as a failure: a change of owner, not a fault.
        assert await _row_count(worker_b, AnsichAssessorErrorRow) == 0
        assert worker_a.backend._failed_jobs == 0
        async with worker_b.sessions() as session:
            held = await session.get(AnsichAssessorJobRow, b_claim.job_id)
        assert held is not None
        assert (held.status, held.lease_owner) == ("processing", worker_b.backend._lease_owner)

        # The new owner redoes the work in full, and only then does the
        # evaluation's own conclusion become durable.
        await _set_assessor_lease(worker_b, b_claim.job_id, _EXPIRED_AT)
        await worker_b.backend._process_assessor_jobs(now=_OCCURRED_AT + timedelta(minutes=2), incomplete_tasks=frozenset(), global_loss=False)
        assert await _row_count(worker_b, AnsichScopeConclusionRow) >= 1
        assert await _assessor_marks(worker_b) != record["marks"]
        async with worker_b.sessions() as session:
            settled = await session.get(AnsichAssessorJobRow, b_claim.job_id)
        assert settled is not None
        assert settled.status == "completed"


# ===========================================================================
# 7. The reconcile gate's real interleaving
# ===========================================================================


async def test_the_reconcile_gate_defers_to_a_live_lease_and_proceeds_past_an_expired_one() -> None:
    """``_reconcile_spawn_usage``'s gate, exercised across two workers (T6 carry).

    The gate waits on *live* claims only, and the docstring is explicit that an
    expired one is deliberately not waited on -- waiting would trade a bounded
    residual for an unbounded wait on a worker that may be gone. Both halves of
    that statement are checked here against a real server: worker A holds a
    ``task-usage`` job in ``processing`` with a live lease and worker B's
    reconciliation defers; once the lease is past-dated, the same call proceeds.
    """

    async with _two_workers() as (_url, worker_a, worker_b):
        parent_id, child_id = new_id(), new_id()
        step_id, tool_call_id = new_id(), new_id()
        spawn = ObservationEnvelope.task_lifecycle(
            kind="task.created",
            task_id=child_id,
            source_kind="deerflow_subagent",
            source_id="provider-task-call",
            occurred_at=_OCCURRED_AT + timedelta(seconds=2),
            source_event_id=f"deerflow_subagent:{child_id}:task:created",
            attributes={
                "parent_task_id": parent_id,
                "spawning_step_id": step_id,
                "spawning_tool_call_id": tool_call_id,
                "subagent_name": "researcher",
            },
        )
        await worker_a.backend.persist_and_project(
            [
                _task_created(parent_id, source_id="run-reconcile-gate"),
                _task_started(parent_id, source_id="run-reconcile-gate"),
                ObservationEnvelope(
                    kind="step.started",
                    occurred_at=_OCCURRED_AT,
                    task_id=parent_id,
                    step_id=step_id,
                    subject_type="step",
                    subject_id=step_id,
                    producer=_PRODUCER,
                    source_event_id=f"step:{step_id}:started",
                    correlation_id=parent_id,
                    payload={"step_seq": 1, "actor_kind": "lead_agent"},
                ),
                ObservationEnvelope(
                    kind="tool.issued",
                    occurred_at=_OCCURRED_AT,
                    task_id=parent_id,
                    step_id=step_id,
                    subject_type="tool_call",
                    subject_id=tool_call_id,
                    producer=_PRODUCER,
                    source_event_id=f"tool:{tool_call_id}:issued",
                    correlation_id=parent_id,
                    payload={
                        "call_seq": 1,
                        "provider_call_id": f"provider-{tool_call_id}",
                        "tool_name": "task",
                        "args_hash": "d" * 64,
                        "args_preview": {},
                        "tool_schema_block_id": None,
                    },
                ),
                spawn,
                *_attempt(child_id, new_id(), offset_seconds=5, total_tokens=29),
            ]
        )
        await _drain_projections(worker_a)

        # Worker A is mid-flight on one of the child's usage projections.
        async with worker_a.sessions() as session, session.begin():
            usage_job_id = await session.scalar(
                sa.select(AnsichProjectionJobRow.job_id)
                .join(ansich_sql.AnsichObservationRow, ansich_sql.AnsichObservationRow.obs_id == AnsichProjectionJobRow.obs_id)
                .where(
                    AnsichProjectionJobRow.projector_name == "task-usage",
                    ansich_sql.AnsichObservationRow.task_id == child_id,
                )
                .limit(1)
            )
            assert usage_job_id is not None
            await session.execute(sa.update(AnsichProjectionJobRow).where(AnsichProjectionJobRow.job_id == usage_job_id).values(status="processing", lease_owner=worker_a.backend._lease_owner, lease_expires_at=_LIVE_LEASE_AT))

        with pytest.raises(ansich_sql._ProjectionDependencyPending):
            async with worker_b.sessions() as session, session.begin():
                await worker_b.backend._reconcile_spawn_usage(session, spawn)

        # Past-dated lease: the gate deliberately does not wait on it.
        async with worker_b.sessions() as session, session.begin():
            await session.execute(sa.update(AnsichProjectionJobRow).where(AnsichProjectionJobRow.job_id == usage_job_id).values(lease_expires_at=_EXPIRED_AT))
        async with worker_b.sessions() as session, session.begin():
            await worker_b.backend._reconcile_spawn_usage(session, spawn)

        # The re-fan is idempotent, so the parent's inclusive total is the
        # child's own -- proof the pass ran rather than merely not raising.
        async with worker_a.sessions() as session:
            inclusive = await session.scalar(
                sa.select(AnsichTaskUsageRow.value).where(
                    AnsichTaskUsageRow.task_id == parent_id,
                    AnsichTaskUsageRow.dimension == "total_tokens",
                    AnsichTaskUsageRow.aggregation_scope == "inclusive",
                )
            )
        assert inclusive == 29


# ===========================================================================
# 8. Health counts cross-worker (a smoke on the raw inputs, not the DTO)
# ===========================================================================


async def test_per_projector_status_counts_agree_from_either_worker() -> None:
    """The inputs of the health merge read identically from both connections.

    The DB-merged health DTO lands after this task, so what is proven here is
    deliberately narrow: the per-``(projector_name, status)`` counts the merge
    reads are a property of the database, not of which worker asked -- including
    at a mid-backlog point (both drives have returned and their sessions are
    closed; this is a smoke over the raw count queries, not a read taken while
    a transaction is still open). If this
    ever disagreed, the merged DTO would be worker-local fiction before it was
    ever assembled.
    """

    async with _two_workers() as (_url, worker_a, worker_b):
        for index in range(6):
            task_id = new_id()
            await worker_a.backend.persist_and_project(
                [
                    _task_created(task_id, source_id=f"run-health-{index}"),
                    _task_started(task_id, source_id=f"run-health-{index}"),
                    *_attempt(task_id, new_id(), offset_seconds=index + 1, total_tokens=index * 3),
                ]
            )

        counts_statement = sa.select(AnsichProjectionJobRow.projector_name, AnsichProjectionJobRow.status, sa.func.count()).group_by(
            AnsichProjectionJobRow.projector_name,
            AnsichProjectionJobRow.status,
        )

        async def read_counts(worker: _Worker) -> dict[tuple[str, str], int]:
            async with worker.sessions() as session:
                return {(name, status): int(count) for name, status, count in (await session.execute(counts_statement)).all()}

        # Mid-load: both workers projecting, then both read.
        async def project(worker: _Worker) -> None:
            for _ in range(6):
                await worker.backend.project_pending(limit=2)
                await asyncio.sleep(0)

        await asyncio.wait_for(asyncio.gather(project(worker_a), project(worker_b)), timeout=_SCRIPT_TIMEOUT_SECONDS)
        mid_a, mid_b = await asyncio.gather(read_counts(worker_a), read_counts(worker_b))
        assert mid_a == mid_b, f"per-projector counts disagreed mid-load: {mid_a} vs {mid_b}"
        assert sum(mid_a.values()) > 0

        await _settle_projections(worker_a, worker_b)
        end_a, end_b = await asyncio.gather(read_counts(worker_a), read_counts(worker_b))
        assert end_a == end_b
        assert not _unsettled(await _projection_jobs(worker_a))
        assert {status for _name, status in end_a} == {"completed"}


# ===========================================================================
# 9. The 0027 migration on a real server
# ===========================================================================


async def test_the_lease_generation_migration_and_its_index_land_on_real_postgres() -> None:
    """``0027`` executes as part of the real chain, and its index exists.

    The migration matrix already walks the whole chain both ways; what belongs
    *here* is the specific shape this batch's multiworker semantics depend on --
    the two ``lease_generation`` columns the completion CAS compares, and the
    ``(projector_name, status)`` index the health merge's grouped counts need --
    checked on the server that actually has to plan against them.
    """

    async with _postgres_database() as url:
        engine = create_async_engine(_connect_url(url))
        try:
            # ``migrations/env.py`` calls ``asyncio.run`` itself, so alembic
            # must not be invoked from a thread that already owns a loop.
            await asyncio.to_thread(alembic_command.upgrade, _get_alembic_config(engine), "head")

            async with engine.connect() as connection:
                head = (await connection.execute(sa.text("SELECT version_num FROM alembic_version"))).scalar()
                columns = {
                    (table, column)
                    for table, column in (
                        await connection.execute(
                            sa.text("SELECT table_name, column_name FROM information_schema.columns WHERE column_name = 'lease_generation'"),
                        )
                    ).all()
                }
                indexes = {
                    name
                    for (name,) in (
                        await connection.execute(
                            sa.text("SELECT indexname FROM pg_indexes WHERE tablename = 'ansich_projection_jobs'"),
                        )
                    ).all()
                }
                nullability = {
                    table: nullable
                    for table, nullable in (
                        await connection.execute(
                            sa.text("SELECT table_name, is_nullable FROM information_schema.columns WHERE column_name = 'lease_generation'"),
                        )
                    ).all()
                }

            assert head == _get_head_revision()
            assert columns == {("ansich_projection_jobs", "lease_generation"), ("ansich_assessor_jobs", "lease_generation")}
            assert set(nullability.values()) == {"NO"}, f"lease_generation must be NOT NULL: {nullability}"
            assert "ix_ansich_projection_jobs_projector_status" in indexes, sorted(indexes)
        finally:
            await engine.dispose()


# ===========================================================================
# 10. Episode collision between two workers' assessment ticks (opportunistic)
# ===========================================================================


async def test_two_workers_assessing_the_same_task_never_duplicate_an_episode() -> None:
    """The uq_ansich_alert_episode collision: loud if it happens, never corrupting.

    Several workers on one host each run their own periodic
    ``assess_operations``, and two of them opening the same Alert episode
    concurrently collide on ``uq_ansich_alert_episode``. That collision is not
    corrupting -- one tick's whole transaction is discarded and the next tick
    redoes it a second later -- but it is not free either: the blast radius is
    the entire tick.

    Provoking it is genuinely racy, so this test is written to prove the
    invariant unconditionally and to *observe* the collision opportunistically
    across a bounded number of rounds. What is always asserted: at most one
    episode row per ``(alert_key, episode)``; never more than one
    ``heartbeat_missing`` Alert per Task (and exactly one on a round where no
    tick was discarded -- a discarded tick takes its whole batch with it, which
    is the blast radius, not something to demand of the losing side); no
    exception other than the unique violation; and a following single-worker
    tick that succeeds. Whether the collision was reached in this run is
    reported, not required.

    Note on the WARNING: ``AnsichService._report_assessment_failure`` is what
    turns this into a rate-limited log line, and it lives in
    ``_projector_loop``. These calls are direct, so the exception surfaces to
    the caller here instead -- which is the same event, one frame earlier.
    """

    async with _postgres_database() as url:
        engines = [create_async_engine(_connect_url(url)) for _ in range(2)]
        factories = [async_sessionmaker(engine, expire_on_commit=False) for engine in engines]
        async with engines[0].begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        services: list[AnsichService] = []
        driven: list = []
        try:
            for factory in factories:
                service = create_sql_ansich_service(
                    factory,
                    heartbeat_stale_after_seconds=5,
                    long_dwell_seconds=5,
                    operations_assessment_interval_ms=60_000,
                    hostname="pg-multiworker-host",
                )
                # Capture the real method BEFORE the gate rebinds it: the gate
                # silences calls made from tasks other than this one, and
                # `asyncio.gather` below makes new ones. Per-service, both.
                driven.append(service.assess_operations)
                only_test_driven_assessments(service)
                services.append(service)
                await service.start()

            collisions = 0
            for round_index in range(_COLLISION_ROUNDS):
                # Several Tasks per round: one tick is one transaction over
                # every running Task, so more Tasks means a longer transaction
                # and a wider window for the peer's tick to be inside it.
                task_ids = [new_id() for _ in range(_TASKS_PER_COLLISION_ROUND)]
                for index, task_id in enumerate(task_ids):
                    source_id = f"run-episode-collision-{round_index}-{index}"
                    # The heartbeat matters: without any heartbeat evidence the
                    # liveness rule answers ``unknown`` (an honest gap, no
                    # episode), so evidence has to exist before "missing" is
                    # even reachable.
                    services[0].record_batch(
                        (
                            _task_created(task_id, source_id=source_id),
                            _task_started(task_id, source_id=source_id),
                            ObservationEnvelope.task_heartbeat(
                                task_id=task_id,
                                run_id=source_id,
                                occurred_at=_OCCURRED_AT,
                                elapsed_ms=0,
                                worker_id=f"{source_id}-worker",
                                ownership_epoch=f"{source_id}-epoch",
                                source_event_id=f"{source_id}:heartbeat:1",
                            ),
                        )
                    )
                for task_id in task_ids:
                    await services[0].flush_task(task_id)
                now = _OCCURRED_AT + timedelta(seconds=10 + round_index)
                outcomes = await asyncio.wait_for(
                    asyncio.gather(driven[0](now=now), driven[1](now=now), return_exceptions=True),
                    timeout=_SCRIPT_TIMEOUT_SECONDS,
                )
                raised = [item for item in outcomes if isinstance(item, BaseException)]
                for item in raised:
                    assert isinstance(item, IntegrityError), f"an assessment tick failed for something other than the episode collision: {item!r}"
                collisions += len(raised)

                async with factories[0]() as session:
                    opened = {
                        task_id: int(count)
                        for task_id, count in (
                            await session.execute(
                                sa.select(AnsichAlertRow.subject_id, sa.func.count())
                                .where(
                                    AnsichAlertRow.subject_id.in_(task_ids),
                                    AnsichAlertRow.alert_type == "heartbeat_missing",
                                )
                                .group_by(AnsichAlertRow.subject_id)
                            )
                        ).all()
                    }
                if raised:
                    # A discarded tick takes its whole batch with it. That is
                    # the blast radius, and it is what the next tick repairs --
                    # not something to demand of the losing one.
                    assert set(opened.values()) <= {1}
                else:
                    assert opened == dict.fromkeys(task_ids, 1), f"round {round_index} did not open one episode per Task: {opened}"

                if collisions:
                    break

            # Whatever happened above, the next tick succeeds.
            assert await driven[0](now=_OCCURRED_AT + timedelta(seconds=30)) >= 0

            async with factories[1]() as session:
                duplicates = list((await session.execute(sa.select(AnsichAlertRow.alert_key, AnsichAlertRow.episode, sa.func.count()).group_by(AnsichAlertRow.alert_key, AnsichAlertRow.episode).having(sa.func.count() > 1))).all())
            assert duplicates == [], f"an episode was written twice: {duplicates}"
            print(f"\n[episode-collision] provoked {collisions} unique-violation collision(s) in the bounded rounds")
        finally:
            for service in services:
                with contextlib.suppress(Exception):
                    await service.stop()
            for engine in engines:
                await engine.dispose()


# ===========================================================================
# 11. Versioned replay and `--replace` on a real server
# ===========================================================================


def _heartbeat(task_id: str, *, run_id: str, ordinal: int, offset_seconds: int) -> ObservationEnvelope:
    return ObservationEnvelope.task_heartbeat(
        task_id=task_id,
        run_id=run_id,
        occurred_at=_OCCURRED_AT + timedelta(seconds=offset_seconds),
        elapsed_ms=1000 * (offset_seconds + 1),
        worker_id=f"{run_id}-worker",
        ownership_epoch=f"{run_id}-epoch",
        source_event_id=f"run:{run_id}:heartbeat:{ordinal}",
        producer_seq=ordinal,
    )


async def _settle_everything(*workers: _Worker) -> None:
    """Drain projections, run one assessment, drain again -- until nothing is owed.

    An assessment pass is not optional here: a re-projected Observation enqueues
    assessor jobs and only ``assess_operations`` settles them, so a drain-only
    settle would leave the store permanently unsettled and the digest below
    permanently ``None``. Same shape the replay's own drive loop uses.
    """

    for _ in range(10):
        await _settle_projections(*workers)
        await workers[0].backend.assess_operations()
        if await workers[0].backend.unsettled_job_count() == 0:
            return
    raise AssertionError("the store did not settle within the bounded loop")


async def test_replay_and_replace_hold_on_postgres_with_a_second_worker_live() -> None:
    """The replay path's real-server half: the digest, the mint's window, the re-pend.

    Four claims this file is the only place that can answer, in one script
    because they are one pass -- splitting them would run the same expensive
    setup four times and still not show them interacting.

    **(a) The digest computes, and computes the same thing twice.**
    ``_canonical_digest_value`` exists *because* dialects disagree: SQLite hands
    back naive datetimes and PostgreSQL aware ones, and some columns are
    ``bytes``. Until this test it had never run against the dialect it was
    written for, so "it does not raise on asyncpg" was an assumption. Two
    replays of one Observation set must agree, on this dialect, over a non-empty
    row set -- and ``task-safety``'s owned tables are digested too, unreplayed,
    purely to widen the column types that reach the canonicaliser here (JSON,
    aware timestamps) beyond the heartbeat table's three.

    **(b) A second worker assesses across the mint's commit window.** The mint
    is one transaction under ``_maintenance_lock`` that re-pends jobs and then
    deletes active-Task read-model rows (ruling RC3). The configuration in which
    that delete, the PB7 publish guard and the guarded sweep genuinely contend
    is a *peer's* 1 Hz ``assess_operations`` running while the mint is open --
    which needs two pools, so SQLite cannot express it. Worker B's tick is
    driven from inside worker A's paused mint transaction.

    **(c) The bulk ``UPDATE ... WHERE obs_id IN (subquery)`` re-pend against a
    live claimer.** The re-pend takes row locks over its whole target set in one
    statement, in an order the planner picks; a claimer takes them one at a time
    with ``FOR UPDATE SKIP LOCKED``. The claim is therefore expected to come
    back **empty and promptly** rather than to block or to abort as a deadlock,
    and "promptly" is asserted with a budget so a lock-order cycle would fail
    the test rather than hang the tier.

    **(d) ``--replace`` on PostgreSQL, and the §11 acceptance taken through it.**
    The replace deletes ``task-heartbeat``'s owned table whole inside that same
    transaction and re-derives it; the digest afterwards must equal the digest
    before, which is what makes "these rows are what this history produces" a
    claim rather than a hope. A row nothing in the Observation stream produces
    is planted first, so the delete is told apart from an overwrite.

    Plus the invariant those four rest on: a job claimed **before** the replay
    cannot settle it afterwards. Worker B's claim is taken first and completed
    last, and its compare-and-set has to fail against the generation the
    re-pend raised -- the property ``mint_replay_jobs``' docstring asserts and
    that no single-worker test can reach.
    """

    async with _two_workers() as (_url, worker_a, worker_b):
        task_id = new_id()
        step_id = new_id()
        run_id = "run-pg-replay"
        await worker_a.backend.persist_and_project(
            [
                _task_created(task_id, source_id=run_id),
                _task_started(task_id, source_id=run_id),
                *(_heartbeat(task_id, run_id=run_id, ordinal=index, offset_seconds=index) for index in range(1, 4)),
                *_authorized_tool_call(task_id, step_id, new_id(), new_id()),
            ]
        )
        await _settle_everything(worker_a, worker_b)

        # (a) The digest, on this dialect, over rows that exist.
        heartbeats_before = await _row_count(worker_a, AnsichTaskHeartbeatRow)
        assert heartbeats_before == 3
        safety_digest = await worker_a.backend.read_model_digest("task-safety")
        assert safety_digest is not None
        assert await worker_b.backend.read_model_digest("task-safety") == safety_digest

        first = await execute_replay(worker_a.backend, projector_name="task-heartbeat", projector_version="1", selector=ReplaySelector())
        second = await execute_replay(worker_a.backend, projector_name="task-heartbeat", projector_version="1", selector=ReplaySelector())
        assert (first.unsettled, first.failed) == (0, 0)
        assert (second.unsettled, second.failed) == (0, 0)
        assert first.digest is not None
        assert first.digest == second.digest

        # The live claimer, taken before the replace so the re-pend has a real
        # in-flight claim to invalidate. Its job has to be the *heartbeat* one
        # -- that is the projector the replace re-pends -- so the sibling jobs
        # this Observation also mints are settled out of the claim's way first,
        # the same narrowing the takeover test above uses. Their read models are
        # not what this test reads.
        late = _heartbeat(task_id, run_id=run_id, ordinal=9, offset_seconds=9)
        await worker_a.backend.persist_and_project([late])
        async with worker_a.sessions() as session, session.begin():
            await session.execute(
                sa.update(AnsichProjectionJobRow)
                .where(
                    AnsichProjectionJobRow.status.in_(("pending", "retry")),
                    AnsichProjectionJobRow.projector_name != "task-heartbeat",
                )
                .values(status="completed", lease_owner=None, lease_expires_at=None)
            )
        stale_claim = await worker_b.backend._claim_projection_job()
        assert stale_claim is not None
        assert stale_claim[1] == "task-heartbeat"
        stale_job_id = stale_claim[0]
        stale_generation = stale_claim[-1]

        # A row no Observation produces: it must not survive the replace, which
        # is how a whole-table delete is distinguished from an overwrite. Its
        # key is a real Observation of the *wrong kind* -- the foreign key here
        # is enforced for real, and `task-heartbeat` would never build a
        # heartbeat row from a `task.created`.
        async with worker_a.sessions() as session, session.begin():
            wrong_kind_obs_id = await session.scalar(sa.select(AnsichObservationRow.obs_id).where(AnsichObservationRow.kind == "task.created").limit(1))
            assert wrong_kind_obs_id is not None
            session.add(
                AnsichTaskHeartbeatRow(
                    heartbeat_obs_id=wrong_kind_obs_id,
                    task_id=task_id,
                    occurred_at=_OCCURRED_AT,
                    producer_instance_id="planted-by-nothing",
                    ownership_epoch="planted",
                    elapsed_ms=999_999,
                )
            )

        mint_open = asyncio.Event()
        peer_done = asyncio.Event()
        state: dict[str, object] = {"paused": False, "peer_claim": "not-run", "claim_seconds": None}

        async def pause_inside_the_open_mint(statement: object) -> None:
            text = _statement_text(statement)
            if state["paused"] or "update ansich_projection_jobs" not in text or "in (select" not in text:
                return
            state["paused"] = True
            mint_open.set()
            # The peer is expected to finish inside this budget -- its claim
            # skips the locked rows rather than waiting on them. A budget that
            # elapsed here would mean the two lock orders had cycled, which is
            # asserted on below rather than suppressed.
            with contextlib.suppress(TimeoutError, asyncio.TimeoutError):
                await asyncio.wait_for(peer_done.wait(), timeout=_INTERLEAVE_TIMEOUT_SECONDS)

        worker_a.session_class.after_execute = staticmethod(pause_inside_the_open_mint)  # type: ignore[assignment]
        try:

            async def run_replace() -> ReplayReport:
                return await execute_replay(
                    worker_a.backend,
                    projector_name="task-heartbeat",
                    projector_version="1",
                    selector=ReplaySelector(),
                    replace=True,
                )

            async def run_peer() -> None:
                await mint_open.wait()
                try:
                    # (b) the peer's operations tick, inside the open mint.
                    await worker_b.backend.assess_operations()
                    # (c) the peer's claim against the re-pend's locked set.
                    started = asyncio.get_running_loop().time()
                    claimed = await asyncio.wait_for(worker_b.backend._claim_projection_job(), timeout=_INTERLEAVE_TIMEOUT_SECONDS)
                    state["claim_seconds"] = asyncio.get_running_loop().time() - started
                    state["peer_claim"] = "empty" if claimed is None else "claimed"
                finally:
                    peer_done.set()

            replace_report, _ = await asyncio.wait_for(asyncio.gather(run_replace(), run_peer()), timeout=_SCRIPT_TIMEOUT_SECONDS)
        finally:
            worker_a.session_class.after_execute = None  # type: ignore[assignment]

        assert state["paused"], "the script never reached the open mint transaction"
        # (b)/(c): the peer neither raised nor cycled. `assess_operations`
        # returning at all is the assertion for (b) -- it commits or it raises.
        assert state["peer_claim"] == "empty", f"the peer's claim came back {state['peer_claim']!r} against the re-pend's locked set"
        assert float(state["claim_seconds"]) < _INTERLEAVE_TIMEOUT_SECONDS

        # (d) the replace landed, and the planted row is gone -- the table was
        # emptied, not written over.
        assert (replace_report.unsettled, replace_report.failed) == (0, 0), _unsettled(await _projection_jobs(worker_a))
        assert await _row_count(worker_a, AnsichTaskHeartbeatRow) == heartbeats_before + 1
        async with worker_a.sessions() as session:
            planted = await session.scalar(sa.select(sa.func.count()).select_from(AnsichTaskHeartbeatRow).where(AnsichTaskHeartbeatRow.ownership_epoch == "planted"))
        assert int(planted or 0) == 0

        # §11 taken through the replace, on this dialect: delete the table
        # whole a second time, re-derive it, and the digest must not move. It
        # must also *differ* from the three-heartbeat digest above, or the
        # comparison would be insensitive to the row set it is about.
        replayed_again = await execute_replay(
            worker_a.backend,
            projector_name="task-heartbeat",
            projector_version="1",
            selector=ReplaySelector(),
            replace=True,
        )
        assert (replayed_again.unsettled, replayed_again.failed) == (0, 0), _unsettled(await _projection_jobs(worker_a))
        assert replace_report.digest is not None
        assert replayed_again.digest == replace_report.digest
        assert replace_report.digest != first.digest

        # The invariant underneath all four: the pre-replay claim cannot settle
        # the job the re-pend took back.
        async with worker_b.sessions() as session, session.begin():
            settled = await worker_b.backend._complete_projection_job(session, job_id=stale_job_id, lease_generation=stale_generation)
        assert settled is False
        assert worker_b.backend.stale_completion_count == 1
        after = await _projection_job(worker_a, stale_job_id)
        assert after.status == "completed"
        assert after.lease_generation > stale_generation
