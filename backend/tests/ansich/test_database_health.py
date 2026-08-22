"""Database-side health truth, its route merge, and the read-model stamp it feeds.

Covers RB6 (per-projector counts, the continuity mark, the index-friendly lag),
RB7 (the additive ``database`` block, its own timeout, the route-level merge and
the unreachable fallback), RB8 (the active-task read model stamped from database
truth rather than from one worker's private counters) and controller ruling PB7
(the monotonic publish guard that keeps a staler tick from overwriting a fresher
row).

Most of these drive a bare ``SqlAnsichBackend`` rather than a started service.
That is deliberate: what is under test is a set of queries over a job ledger in a
particular state, and a running projector loop would keep settling the very jobs
the state is built out of.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from _router_auth_helpers import make_authed_test_app
from ansich import AnsichService, ObservationEnvelope, new_id
from ansich.contracts import DatabaseHealth
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from support.ansich_settle import only_test_driven_assessments

from app.gateway.auth.models import User
from app.gateway.routers import ansich as ansich_router
from deerflow.ansich import create_embedded_ansich_service, create_sql_ansich_service
from deerflow.ansich.persistence.models import (
    AnsichActiveTaskReadModelRow,
    AnsichAssessorJobRow,
    AnsichBeliefAssertionRow,
    AnsichObservationRow,
    AnsichProjectionJobRow,
    AnsichTaskSummaryRow,
)
from deerflow.ansich.persistence.sql import (
    _UNSETTLED_JOB_STATUSES,
    SqlAnsichBackend,
    _projector_health_rows,
    _projector_status_counts_statement,
    _unsettled_projector_minimum_statement,
)
from deerflow.config.ansich_config import AnsichConfig
from deerflow.persistence.base import Base

_OBSERVED_AT = datetime(2026, 7, 18, 11, tzinfo=UTC)


def admin_user() -> User:
    return User(
        id=uuid4(),
        email="ansich-health-admin@example.com",
        password_hash="x",
        system_role="admin",
    )


async def _backend(tmp_path, name: str) -> tuple[SqlAnsichBackend, async_sessionmaker, object]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / name}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return SqlAnsichBackend(session_factory), session_factory, engine


def _created(task_id: str, ordinal: int) -> ObservationEnvelope:
    return ObservationEnvelope.task_lifecycle(
        kind="task.created",
        task_id=task_id,
        source_kind="deerflow_run",
        source_id=f"run-health-{ordinal}",
        occurred_at=_OBSERVED_AT + timedelta(seconds=ordinal),
        source_event_id=f"run-health-{ordinal}:task:created",
    )


async def _ingest_seq_by_obs(session_factory, obs_ids: list[str]) -> dict[str, int]:
    async with session_factory() as session:
        rows = (await session.execute(select(AnsichObservationRow.obs_id, AnsichObservationRow.ingest_seq).where(AnsichObservationRow.obs_id.in_(obs_ids)))).all()
    return {obs_id: ingest_seq for obs_id, ingest_seq in rows}


async def _set_job_status(session_factory, *, obs_id: str, projector_name: str, status: str) -> None:
    async with session_factory() as session, session.begin():
        await session.execute(
            update(AnsichProjectionJobRow)
            .where(
                AnsichProjectionJobRow.obs_id == obs_id,
                AnsichProjectionJobRow.projector_name == projector_name,
            )
            .values(status=status)
        )


def _projector(health: DatabaseHealth, name: str):
    return next(row for row in health.projectors if row.projector_name == name)


def test_health_statements_are_bounded_by_the_unsettled_status_predicate():
    """The real condition for these reads staying indexed is the WHERE clause.

    Measured on PostgreSQL 16 at 1.2M job rows: without a status predicate the
    counts statement is a Parallel Seq Scan (201ms); with
    ``status IN _UNSETTLED_JOB_STATUSES`` it is an Index Scan on the
    status-leading ``ix_ansich_projection_jobs_claim`` (0.10ms). GROUP BY key
    order changes neither the plan nor the index -- the planner is free to
    reorder grouping keys -- so the predicate is what is pinned here, and both
    statements must carry it. Dropping it would put a full scan of a table that
    only ever grows on the 1 Hz operations tick and on every ``GET /health``.
    """

    for statement in (_projector_status_counts_statement(), _unsettled_projector_minimum_statement()):
        for dialect in (sqlite.dialect(), postgresql.dialect()):
            compiled = str(statement.compile(dialect=dialect, compile_kwargs={"literal_binds": True}))
            flattened = " ".join(compiled.split())
            assert " WHERE " in flattened, flattened
            where_clause = flattened.split(" WHERE ", 1)[1]
            assert "status IN " in where_clause, where_clause
            for status in _UNSETTLED_JOB_STATUSES:
                assert f"'{status}'" in where_clause, (status, where_clause)
            # Settled work is never counted: the DTO exposes only the four
            # unsettled buckets, so a `completed` row read here is read for
            # nothing.
            assert "'completed'" not in where_clause


def test_the_snapshot_reads_the_highest_ingest_sequence_before_the_job_tables():
    """Read order is the whole guard against an over-claiming mark (F2).

    The four reads are one transaction but not one snapshot: PostgreSQL's
    default READ COMMITTED takes a fresh snapshot per statement. If ``highest``
    were read *after* the unsettled minimum, a projector that was caught up at
    the earlier statement would be stamped complete through Observations that
    were committed in between and whose jobs are still owed -- an over-claim,
    which the PB7 guard then reads as "every later tick is staler" and freezes
    the read model behind. Reading ``highest`` first makes the mark only ever
    under-claim, which self-heals on the next tick.

    Pinned structurally because SQLite gives every statement in a transaction
    one snapshot, so the skew this defends against cannot be reproduced here.
    """

    import asyncio

    from sqlalchemy import event
    from sqlalchemy.ext.asyncio import async_sessionmaker as _maker
    from sqlalchemy.ext.asyncio import create_async_engine as _engine_factory

    async def _run() -> list[str]:
        engine = _engine_factory("sqlite+aiosqlite://")
        session_factory = _maker(engine, expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        backend = SqlAnsichBackend(session_factory)
        seen: list[str] = []

        def _capture(_connection, _cursor, statement, _parameters, _context, _executemany) -> None:
            seen.append(" ".join(statement.split()))

        event.listen(engine.sync_engine, "before_cursor_execute", _capture)
        try:
            await backend.get_database_health()
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", _capture)
            await engine.dispose()
        return seen

    statements = asyncio.run(_run())
    highest_at = next(index for index, item in enumerate(statements) if "max(ansich_observations.ingest_seq)" in item)
    first_job_read = next(index for index, item in enumerate(statements) if "ansich_projection_jobs" in item)
    assert highest_at < first_job_read, statements


def test_a_projector_seen_by_only_one_read_still_appears_in_the_block():
    """The other half of F2: the two job reads can disagree about the key set.

    Under READ COMMITTED a projector's first-ever job can land between the
    counts read and the unsettled-minimum read, so it appears in one and not the
    other. Built from the counts alone, its (low) continuity mark would drop out
    of the store-wide minimum entirely -- the same over-claim by another route.
    """

    rows = _projector_health_rows(
        registry=(("task-control", "1"),),
        counts={("task-control", "1"): {"pending": 2}},
        unsettled_minimum={("task-control", "1"): 40, ("late-projector", "1"): 7},
        highest=100,
    )

    by_name = {row.projector_name: row for row in rows}
    assert set(by_name) == {"task-control", "late-projector"}
    assert by_name["late-projector"].complete_through == 6
    assert by_name["late-projector"].pending == 0
    assert by_name["task-control"].complete_through == 39


def test_a_projector_with_nothing_outstanding_still_appears_from_the_registry():
    """The counts read no longer sees settled work, so the registry names the set."""

    rows = _projector_health_rows(
        registry=(("task-control", "1"), ("task-structural", "1")),
        counts={},
        unsettled_minimum={},
        highest=100,
    )

    assert [row.projector_name for row in rows] == ["task-control", "task-structural"]
    assert all(row.complete_through == 100 for row in rows)
    assert all((row.pending, row.retry, row.processing, row.failed) == (0, 0, 0, 0) for row in rows)


@pytest.mark.anyio
async def test_per_projector_counts_split_every_claimable_status_including_retry(tmp_path):
    """``retry`` is its own bucket, not folded into pending and not omitted.

    A hard error re-arms a job to ``retry``; a bucket-less health page would
    make that work disappear from view while it is still owed.
    """

    backend, session_factory, engine = await _backend(tmp_path, "health-counts.db")
    observations = [_created(new_id(), ordinal) for ordinal in range(4)]
    try:
        await backend.persist_and_project(list(observations))
        for observation, status in zip(observations, ("pending", "retry", "processing", "failed"), strict=True):
            await _set_job_status(
                session_factory,
                obs_id=observation.obs_id,
                projector_name="task-control",
                status=status,
            )
        health = await backend.get_database_health()
    finally:
        await engine.dispose()

    assert health.status == "reachable"
    # Ordered by identity so two reads of an unchanged ledger are diffable.
    assert [row.projector_name for row in health.projectors] == ["task-control", "task-structural"]
    control = _projector(health, "task-control")
    assert (control.pending, control.retry, control.processing, control.failed) == (1, 1, 1, 1)
    structural = _projector(health, "task-structural")
    assert (structural.pending, structural.retry, structural.processing, structural.failed) == (4, 0, 0, 0)
    assert control.projector_version == "1"


@pytest.mark.anyio
async def test_complete_through_stops_below_a_hole_however_far_past_it_the_projector_ran(tmp_path):
    """The mark is continuity, not progress: one failed job below settled work holds it down."""

    backend, session_factory, engine = await _backend(tmp_path, "health-hole.db")
    observations = [_created(new_id(), ordinal) for ordinal in range(4)]
    try:
        await backend.persist_and_project(list(observations))
        ingest = await _ingest_seq_by_obs(session_factory, [item.obs_id for item in observations])
        for index, observation in enumerate(observations):
            # task-control: everything settled except the *second* row, which is
            # durably failed, and the last row, which is still pending. The hole
            # sits below the pending job on purpose — a mark taken as "highest
            # settled" or "lowest pending" would both step over it.
            status = "failed" if index == 1 else "completed" if index < 3 else "pending"
            await _set_job_status(
                session_factory,
                obs_id=observation.obs_id,
                projector_name="task-control",
                status=status,
            )
            await _set_job_status(
                session_factory,
                obs_id=observation.obs_id,
                projector_name="task-structural",
                status="completed",
            )
        health = await backend.get_database_health()
    finally:
        await engine.dispose()

    highest = max(ingest.values())
    assert _projector(health, "task-control").complete_through == ingest[observations[1].obs_id] - 1
    # Nothing unsettled at all: complete through everything the store holds.
    assert _projector(health, "task-structural").complete_through == highest


@pytest.mark.anyio
async def test_a_re_armed_job_still_holds_the_continuity_mark_down(tmp_path):
    """The T2 carry, at the mark rather than at the counts.

    ``retry`` is unsettled work: its Observation has not been projected. A mark
    that treated it as settled would claim coverage of an Observation nothing
    has processed, which is the one thing this number must never do.
    """

    backend, session_factory, engine = await _backend(tmp_path, "health-retry-mark.db")
    observations = [_created(new_id(), ordinal) for ordinal in range(3)]
    try:
        await backend.persist_and_project(list(observations))
        ingest = await _ingest_seq_by_obs(session_factory, [item.obs_id for item in observations])
        async with session_factory() as session, session.begin():
            await session.execute(update(AnsichProjectionJobRow).values(status="completed"))
        await _set_job_status(
            session_factory,
            obs_id=observations[1].obs_id,
            projector_name="task-control",
            status="retry",
        )
        health = await backend.get_database_health()
    finally:
        await engine.dispose()

    assert _projector(health, "task-control").retry == 1
    assert _projector(health, "task-control").complete_through == ingest[observations[1].obs_id] - 1
    assert _projector(health, "task-structural").complete_through == max(ingest.values())


@pytest.mark.anyio
async def test_lag_is_the_age_of_the_oldest_unsettled_row_not_of_the_oldest_row(tmp_path):
    """Behavioural pin on RB6②'s index-friendly form.

    ``recorded_at`` carries no index, so the lag may never be found by ordering
    or filtering on it. It is read from the single row at ``MIN(ingest_seq)``
    over unsettled jobs — a primary-key lookup. The fixture makes
    ``recorded_at`` disagree with ingest order in both directions, so a scan
    over all rows (100s), or a minimum over the unsettled ones (50s), gives a
    visibly different answer from the correct one (10s).
    """

    backend, session_factory, engine = await _backend(tmp_path, "health-lag.db")
    observations = [_created(new_id(), ordinal) for ordinal in range(3)]
    now = datetime.now(UTC)
    try:
        await backend.persist_and_project(list(observations))
        ages = (timedelta(seconds=100), timedelta(seconds=10), timedelta(seconds=50))
        async with session_factory() as session, session.begin():
            for observation, age in zip(observations, ages, strict=True):
                await session.execute(update(AnsichObservationRow).where(AnsichObservationRow.obs_id == observation.obs_id).values(recorded_at=now - age))
        for projector_name in ("task-control", "task-structural"):
            await _set_job_status(
                session_factory,
                obs_id=observations[0].obs_id,
                projector_name=projector_name,
                status="completed",
            )
        health = await backend.get_database_health()
    finally:
        await engine.dispose()

    assert 9_000 <= health.lag_ms < 40_000


@pytest.mark.anyio
async def test_an_empty_backlog_reports_zero_lag_and_the_highest_ingest_sequence(tmp_path):
    backend, session_factory, engine = await _backend(tmp_path, "health-empty.db")
    observations = [_created(new_id(), ordinal) for ordinal in range(2)]
    try:
        await backend.persist_and_project(list(observations))
        ingest = await _ingest_seq_by_obs(session_factory, [item.obs_id for item in observations])
        async with session_factory() as session, session.begin():
            await session.execute(update(AnsichProjectionJobRow).values(status="completed"))
        health = await backend.get_database_health()
    finally:
        await engine.dispose()

    assert health.lag_ms == 0
    assert {row.complete_through for row in health.projectors} == {max(ingest.values())}


@pytest.mark.anyio
async def test_failed_jobs_counts_both_job_tables_and_stale_completions_are_exposed(tmp_path):
    """``database.failed_jobs`` is the authoritative count; the process one is advisory."""

    backend, session_factory, engine = await _backend(tmp_path, "health-failed.db")
    observations = [_created(new_id(), ordinal) for ordinal in range(2)]
    try:
        await backend.persist_and_project(list(observations))
        await _set_job_status(
            session_factory,
            obs_id=observations[0].obs_id,
            projector_name="task-control",
            status="failed",
        )
        async with session_factory() as session, session.begin():
            # Inserted directly: this suite leaves `PRAGMA foreign_keys` off, and
            # the assessor job's Task FK is not what is under test here.
            session.add(
                AnsichAssessorJobRow(
                    job_id=new_id(),
                    subject_id=observations[0].task_id,
                    assessor_name="absolute-limit",
                    assessor_version="1.0.0",
                    evidence_watermark=1,
                    status="failed",
                )
            )
        health = await backend.get_database_health()
    finally:
        await engine.dispose()

    assert health.failed_jobs == 2
    # Process-local, and labelled as such by being answerable rather than zero.
    assert health.stale_completion_count == backend.stale_completion_count == 0


@pytest.mark.anyio
async def test_the_database_block_reads_unreachable_when_the_query_set_fails():
    service = AnsichService.in_memory()

    async def _raise() -> DatabaseHealth:
        raise RuntimeError("storage is down")

    service._backend.get_database_health = _raise  # type: ignore[attr-defined]
    health = await service.get_database_health()

    assert health == DatabaseHealth(status="unreachable")


@pytest.mark.anyio
async def test_the_database_block_reads_unreachable_when_the_query_set_outlives_its_budget():
    import asyncio

    service = AnsichService.in_memory(batch_size=1)
    service._health_database_timeout_seconds = 0.01

    async def _hang() -> DatabaseHealth:
        await asyncio.sleep(30)
        raise AssertionError("the timeout should have fired")

    service._backend.get_database_health = _hang  # type: ignore[attr-defined]
    health = await service.get_database_health()

    assert health.status == "unreachable"


@pytest.mark.anyio
async def test_health_serves_the_process_block_in_full_when_the_database_is_unreachable():
    """``GET /health`` remains the one route readable while storage is down (RB7⑤)."""

    service = create_embedded_ansich_service(AnsichConfig(enabled=True), None)
    assert service is not None
    await service.start()
    app = make_authed_test_app(user_factory=admin_user)
    app.state.ansich_service = service
    app.include_router(ansich_router.router)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/ansich/health")
    finally:
        await service.stop()

    assert response.status_code == 200
    body = response.json()
    assert body["database"]["status"] == "unreachable"
    assert body["database"]["projectors"] == []
    # None, never 0: a block that could not be read must not render as "0ms
    # behind, 0 failed jobs" to a consumer that forgot to branch on `status`.
    assert body["database"]["failed_jobs"] is None
    assert body["database"]["lag_ms"] is None
    assert body["database"]["stale_completion_count"] is None
    # The process side is untouched by the database side's failure.
    assert body["status"] == "failed"
    assert body["queue_capacity"] == AnsichConfig().queue_capacity
    assert "writer" in body and "producers" in body


@pytest.mark.anyio
async def test_health_survives_a_database_failure_injected_under_a_working_service(tmp_path):
    """The other half of the fallback: storage that is *there* and cannot answer."""

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'health-injected.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(session_factory, operations_assessment_interval_ms=60_000)
    only_test_driven_assessments(service)
    await service.start()
    task_id = new_id()

    async def _refuse():
        raise RuntimeError("connection reset by peer")

    app = make_authed_test_app(user_factory=admin_user)
    app.state.ansich_service = service
    app.include_router(ansich_router.router)

    try:
        service.record(_created(task_id, 2))
        await service.flush_task(task_id)
        service._backend.get_database_health = _refuse
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/ansich/health")
    finally:
        await service.stop()
        await engine.dispose()

    assert response.status_code == 200
    body = response.json()
    assert body["database"]["status"] == "unreachable"
    # Process-side facts the collector really did observe are still reported.
    assert body["accepted_count"] >= 1
    assert body["storage_available"] is True
    assert body["status"] in {"healthy", "degraded", "recovering", "starting"}


@pytest.mark.anyio
async def test_health_merges_the_database_block_beside_the_process_block(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'health-route.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(session_factory, operations_assessment_interval_ms=60_000)
    only_test_driven_assessments(service)
    await service.start()
    task_id = new_id()
    app = make_authed_test_app(user_factory=admin_user)
    app.state.ansich_service = service
    app.include_router(ansich_router.router)

    try:
        service.record(_created(task_id, 1))
        await service.flush_task(task_id)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/ansich/health")
    finally:
        await service.stop()
        await engine.dispose()

    assert response.status_code == 200
    body = response.json()
    assert body["database"]["status"] == "reachable"
    names = {row["projector_name"] for row in body["database"]["projectors"]}
    assert {"task-structural", "task-control"} <= names
    assert body["database"]["failed_jobs"] == 0
    # Additive: the process block is the same document it always was.
    assert body["status"] in {"healthy", "degraded", "recovering", "starting"}
    assert "database" not in service.get_health().model_dump(mode="json")


@pytest.mark.anyio
async def test_active_task_rows_are_stamped_from_database_truth_not_the_process_counter(tmp_path):
    """RB8: two workers must read the same watermark off the same store.

    The process-local counters describe only the ticking worker's own progress,
    so under two workers whichever ticked last stamped its private numbers onto
    every Task row. This drives them apart deliberately — the counters are set
    to values no database read could produce — and pins that the row carries the
    database's answer.
    """

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'health-stamp.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(session_factory, operations_assessment_interval_ms=60_000)
    only_test_driven_assessments(service)
    await service.start()
    task_id = new_id()

    try:
        service.record_batch(
            (
                ObservationEnvelope.task_lifecycle(
                    kind="task.created",
                    task_id=task_id,
                    source_kind="deerflow_run",
                    source_id="run-health-stamp",
                    occurred_at=_OBSERVED_AT,
                    source_event_id="run-health-stamp:task:created",
                ),
                ObservationEnvelope.task_lifecycle(
                    kind="task.started",
                    task_id=task_id,
                    source_kind="deerflow_run",
                    source_id="run-health-stamp",
                    occurred_at=_OBSERVED_AT,
                    source_event_id="run-health-stamp:task:started",
                ),
            )
        )
        await service.flush_task(task_id)
        backend = service._backend
        # A process counter that disagrees with the store in both fields.
        backend._watermark = 9_999
        backend._latest_recorded_at = datetime.now(UTC) - timedelta(hours=3)
        backend._latest_projected_at = None
        process_metrics = backend.get_projection_metrics()
        database_health = await backend.get_database_health()
        await service.assess_operations(now=datetime.now(UTC))
        async with session_factory() as session:
            row = await session.scalar(select(AnsichActiveTaskReadModelRow).where(AnsichActiveTaskReadModelRow.task_id == task_id))
            watermark = row.projection_watermark
            lag_ms = row.projection_lag_ms
    finally:
        await service.stop()
        await engine.dispose()

    assert process_metrics["watermark"] == 9_999
    assert process_metrics["lag_ms"] > 3_000_000
    assert watermark == _projector(database_health, "task-control").complete_through
    assert watermark != process_metrics["watermark"]
    assert lag_ms != process_metrics["lag_ms"]


@pytest.mark.anyio
async def test_a_staler_operations_tick_does_not_publish_over_a_fresher_read_model_row(tmp_path):
    """Controller ruling PB7's two-tick inversion.

    Every input of a tick is read in earlier, already-committed sessions, so a
    tick that started first can finish last and overwrite a peer's fresher row
    with older facts — the row lock serialises the writers, not the compute. The
    guard compares the basis those facts were read against and skips.
    """

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'health-pb7.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(session_factory, operations_assessment_interval_ms=60_000)
    only_test_driven_assessments(service)
    await service.start()
    task_id = new_id()

    try:
        service.record_batch(
            (
                ObservationEnvelope.task_lifecycle(
                    kind="task.created",
                    task_id=task_id,
                    source_kind="deerflow_run",
                    source_id="run-health-pb7",
                    occurred_at=_OBSERVED_AT,
                    source_event_id="run-health-pb7:task:created",
                ),
                ObservationEnvelope.task_lifecycle(
                    kind="task.started",
                    task_id=task_id,
                    source_kind="deerflow_run",
                    source_id="run-health-pb7",
                    occurred_at=_OBSERVED_AT,
                    source_event_id="run-health-pb7:task:started",
                ),
            )
        )
        await service.flush_task(task_id)
        backend = service._backend
        # Tick one: the fresher worker publishes.
        fresh_at = datetime.now(UTC)
        await service.assess_operations(now=fresh_at)
        async with session_factory() as session:
            fresh = await session.scalar(select(AnsichActiveTaskReadModelRow).where(AnsichActiveTaskReadModelRow.task_id == task_id))
            fresh_watermark = fresh.projection_watermark
            fresh_duration_ms = fresh.duration_ms
            fresh_updated_at = fresh.updated_at
        assert fresh_watermark is not None

        # Tick two: a peer whose inputs were read against an older basis. Its
        # `now` is *later*, so without the guard its row would win on every
        # field — which is exactly the inversion being ruled out.
        snapshot = await backend._database_projection_snapshot()
        stale = snapshot._replace(complete_through=fresh_watermark - 1, lag_ms=snapshot.lag_ms + 5_000)
        backend._database_projection_snapshot = lambda: _resolved(stale)  # type: ignore[assignment]
        await service.assess_operations(now=fresh_at + timedelta(minutes=5))
        async with session_factory() as session:
            after = await session.scalar(select(AnsichActiveTaskReadModelRow).where(AnsichActiveTaskReadModelRow.task_id == task_id))
            after_watermark = after.projection_watermark
            after_duration_ms = after.duration_ms
            after_updated_at = after.updated_at
    finally:
        await service.stop()
        await engine.dispose()

    assert after_watermark == fresh_watermark
    # The skip covers the whole row, not just the watermark: publishing a mix of
    # two ticks' facts would be a state neither of them observed.
    assert after_duration_ms == fresh_duration_ms
    assert after_updated_at == fresh_updated_at


@pytest.mark.anyio
async def test_a_staler_operations_tick_does_not_delete_a_fresher_read_model_row(tmp_path):
    """PB7 has to cover the DELETE as well as the UPDATE (review F3).

    The sweep that removes rows for Tasks no longer running reads its
    ``running_task_ids`` in the same earlier, already-committed session as every
    other input, and it runs *before* the per-row guard. A staler tick could
    therefore delete a row a fresher tick had just published -- and deleting it
    also resets the very basis the guard works from to NULL, disarming the guard
    for that Task. The delete now carries the same staler-basis condition.
    """

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'health-pb7-delete.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(session_factory, operations_assessment_interval_ms=60_000)
    only_test_driven_assessments(service)
    await service.start()
    task_id = new_id()

    try:
        service.record_batch(
            (
                ObservationEnvelope.task_lifecycle(
                    kind="task.created",
                    task_id=task_id,
                    source_kind="deerflow_run",
                    source_id="run-health-pb7-delete",
                    occurred_at=_OBSERVED_AT,
                    source_event_id="run-health-pb7-delete:task:created",
                ),
                ObservationEnvelope.task_lifecycle(
                    kind="task.started",
                    task_id=task_id,
                    source_kind="deerflow_run",
                    source_id="run-health-pb7-delete",
                    occurred_at=_OBSERVED_AT,
                    source_event_id="run-health-pb7-delete:task:started",
                ),
            )
        )
        await service.flush_task(task_id)
        backend = service._backend
        fresh_at = datetime.now(UTC)
        await service.assess_operations(now=fresh_at)
        async with session_factory() as session:
            fresh = await session.scalar(select(AnsichActiveTaskReadModelRow).where(AnsichActiveTaskReadModelRow.task_id == task_id))
            fresh_watermark = fresh.projection_watermark
        assert fresh_watermark is not None

        # The Task leaves the running set, so the sweep below wants to delete
        # its row — but this tick's basis is older than the row's.
        async with session_factory() as session, session.begin():
            await session.execute(update(AnsichTaskSummaryRow).where(AnsichTaskSummaryRow.task_id == task_id).values(control_value="completed"))
        real_snapshot = backend._database_projection_snapshot
        snapshot = await real_snapshot()
        stale = snapshot._replace(complete_through=fresh_watermark - 1)
        backend._database_projection_snapshot = lambda: _resolved(stale)  # type: ignore[assignment]
        await service.assess_operations(now=fresh_at + timedelta(minutes=5))
        async with session_factory() as session:
            survived = await session.scalar(select(AnsichActiveTaskReadModelRow).where(AnsichActiveTaskReadModelRow.task_id == task_id))
            survived_watermark = None if survived is None else survived.projection_watermark

        # And the row is not leaked: a tick that is not staler sweeps it.
        backend._database_projection_snapshot = real_snapshot  # type: ignore[assignment]
        await service.assess_operations(now=fresh_at + timedelta(minutes=6))
        async with session_factory() as session:
            after_fresh_tick = await session.scalar(select(AnsichActiveTaskReadModelRow).where(AnsichActiveTaskReadModelRow.task_id == task_id))
    finally:
        await service.stop()
        await engine.dispose()

    assert survived_watermark == fresh_watermark
    assert after_fresh_tick is None


@pytest.mark.anyio
async def test_a_hole_on_the_first_observation_publishes_a_zero_mark_rather_than_raising(tmp_path):
    """The `ingest_seq == 1` boundary of the continuity mark.

    `ingest_seq` starts at 1, so `min(unsettled) - 1` is **0** whenever the
    lowest unsettled job sits on the store's very first Observation — and a
    durably failed job there makes that permanent. Zero is a legitimate value of
    this field: it says "nothing is settled yet, and nothing below 1 is owed",
    which is exactly what a continuity mark should say there. It is *not* the
    same statement as `None`, which this field reserves for "the store holds no
    Observations at all"; the publish guard reads `None` as "no basis" and would
    treat a real basis of 0 as one if the two were folded together.

    Before the fix `ActiveTaskView.projection_watermark` carried a `ge=1` bound
    left over from the field's pre-T10 meaning (this worker's highest
    *projected* sequence), so this state raised `ValidationError` out of
    `assess_operations` on **every** tick and the active-task read model was
    never published — during exactly the poison-job incident the
    `projection_failure` producer exists to report.
    """

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'health-zero-mark.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(session_factory, operations_assessment_interval_ms=60_000)
    only_test_driven_assessments(service)
    await service.start()
    task_id = new_id()

    try:
        service.record_batch(
            (
                ObservationEnvelope.task_lifecycle(
                    kind="task.created",
                    task_id=task_id,
                    source_kind="deerflow_run",
                    source_id="run-health-zero",
                    occurred_at=_OBSERVED_AT,
                    source_event_id="run-health-zero:task:created",
                ),
                ObservationEnvelope.task_lifecycle(
                    kind="task.started",
                    task_id=task_id,
                    source_kind="deerflow_run",
                    source_id="run-health-zero",
                    occurred_at=_OBSERVED_AT,
                    source_event_id="run-health-zero:task:started",
                ),
            )
        )
        await service.flush_task(task_id)
        backend = service._backend
        async with session_factory() as session:
            first_obs_id, first_ingest_seq, poisoned_projector = (
                await session.execute(
                    select(
                        AnsichObservationRow.obs_id,
                        AnsichObservationRow.ingest_seq,
                        AnsichProjectionJobRow.projector_name,
                    )
                    .join(
                        AnsichProjectionJobRow,
                        AnsichProjectionJobRow.obs_id == AnsichObservationRow.obs_id,
                    )
                    .order_by(AnsichObservationRow.ingest_seq, AnsichProjectionJobRow.projector_name)
                    .limit(1)
                )
            ).one()
        # The poison job: the store's very first Observation, durably failed.
        await _set_job_status(
            session_factory,
            obs_id=first_obs_id,
            projector_name=poisoned_projector,
            status="failed",
        )
        database_health = await backend.get_database_health()
        # No raise: this is the assertion the fix is about.
        await service.assess_operations(now=datetime.now(UTC))
        async with session_factory() as session:
            row = await session.scalar(select(AnsichActiveTaskReadModelRow).where(AnsichActiveTaskReadModelRow.task_id == task_id))
            published_watermark = None if row is None else row.projection_watermark
    finally:
        await service.stop()
        await engine.dispose()

    assert first_ingest_seq == 1
    assert _projector(database_health, poisoned_projector).complete_through == 0
    assert row is not None
    assert published_watermark == 0


def test_an_unreachable_database_block_reports_unknown_rather_than_zero():
    """None-when-unknown is a batch invariant, and it is user-visible here.

    A panel that renders `database.lag_ms` / `database.failed_jobs` without
    branching on `status` would otherwise show "0ms behind, 0 failed jobs" at
    the exact moment storage is down.
    """

    unreachable = DatabaseHealth(status="unreachable")

    assert unreachable.lag_ms is None
    assert unreachable.failed_jobs is None
    assert unreachable.stale_completion_count is None
    assert unreachable.projectors == ()
    # `None`, never `()`: a reachable store always answers with one entry per
    # component this build knows, so an empty list is not a state the block can
    # legitimately be in and rendering it as "no versions" would report an
    # outage as a configuration.
    assert unreachable.active_versions is None


@pytest.mark.anyio
async def test_the_database_block_carries_every_component_at_its_running_version(tmp_path):
    """The §9 debt: which version of what is actually running, in health.

    Absent rows are reported as code defaults rather than omitted, because an
    omitted entry is what an unreadable block looks like.
    """

    backend, _sessions, engine = await _backend(tmp_path, "active-versions.db")
    try:
        before = await backend.get_database_health()
        assert before.active_versions is not None
        assert {entry.origin for entry in before.active_versions} == {"code_default"}
        resolver_before = next(entry for entry in before.active_versions if entry.component_kind == "resolver")
        assert resolver_before.active_version == resolver_before.code_default_version

        await backend.activate_version(
            component_kind="resolver",
            component_name="ansich-default",
            version="1.0.0",
            actor="operator@example.com",
        )

        after = await backend.get_database_health()
        assert after.active_versions is not None
        resolver_after = next(entry for entry in after.active_versions if entry.component_kind == "resolver")
        assert resolver_after.active_version == "1.0.0"
        assert resolver_after.code_default_version == "2.0.0"
        assert resolver_after.origin == "activated_audited"
        assert resolver_after.activated_by == "operator@example.com"
        assert resolver_after.audit_obs_id is not None
        # Every other component is still at its default; a switch is scoped to
        # the row it names.
        assert {entry.origin for entry in after.active_versions if entry.component_kind == "projector"} == {"code_default"}
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_a_service_without_the_backend_method_answers_none_rather_than_empty():
    """The in-memory backend has no active-version row and says so honestly."""

    service = AnsichService.in_memory()

    assert await service.get_active_versions() is None
    assert await service.validate_active_versions() is None


@pytest.mark.anyio
async def test_health_carries_the_active_versions_through_the_route_merge(tmp_path):
    """The route hands the whole `database` block through, this field included."""

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'active-version-route.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(session_factory, operations_assessment_interval_ms=60_000)
    only_test_driven_assessments(service)
    await service.start()
    app = make_authed_test_app(user_factory=admin_user)
    app.state.ansich_service = service
    app.include_router(ansich_router.router)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/ansich/health")
    finally:
        await service.stop()
        await engine.dispose()

    assert response.status_code == 200
    block = response.json()["database"]
    assert block["status"] == "reachable"
    names = {(entry["component_kind"], entry["component_name"]) for entry in block["active_versions"]}
    assert ("resolver", "ansich-default") in names
    assert ("projector", "task-step") in names


def _resolved(value):
    async def _call():
        return value

    return _call()


@pytest.mark.anyio
async def test_both_budget_health_writers_store_the_same_value_shape(tmp_path):
    """F10-24's structural half: two writers, one readable shape.

    ``_assess_budget_rows`` (terminal control projection) and the
    ``absolute-limit`` assessor both write ``budget_health:<dimension>:<scope>``
    for the same Task, and the resolver separates them on ``as_of`` then
    ``asserted_at`` — two different clocks. So whichever assertion a reader gets
    has to carry the same keys, or a field's presence becomes a race:
    ``enforcement``/``shadow`` are what tells an enforced breach from a shadow
    one and were absent from exactly half of them.
    """

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'health-budget-shape.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(session_factory)
    only_test_driven_assessments(service)
    await service.start()
    task_id = new_id()
    configured = ObservationEnvelope.budget_configured(
        task_id=task_id,
        run_id="run-budget-shape",
        occurred_at=_OBSERVED_AT,
        dimension="total_tokens",
        aggregation_scope="local",
        warning_limit=80,
        hard_limit=100,
        enforcement=True,
        source_kind="release_default",
        requested_value=None,
        effective_value=100,
        source_event_id="run-budget-shape:budget:total_tokens",
    )

    try:
        service.record_batch(
            (
                ObservationEnvelope.task_lifecycle(
                    kind="task.created",
                    task_id=task_id,
                    source_kind="deerflow_run",
                    source_id="run-budget-shape",
                    occurred_at=_OBSERVED_AT,
                    source_event_id="run-budget-shape:task:created",
                ),
                ObservationEnvelope.task_lifecycle(
                    kind="task.started",
                    task_id=task_id,
                    source_kind="deerflow_run",
                    source_id="run-budget-shape",
                    occurred_at=_OBSERVED_AT,
                    source_event_id="run-budget-shape:task:started",
                ),
                configured,
                ObservationEnvelope(
                    kind="llm.responded",
                    subject_type="llm_attempt",
                    subject_id=new_id(),
                    task_id=task_id,
                    occurred_at=_OBSERVED_AT + timedelta(seconds=1),
                    producer=configured.producer,
                    source_event_id="run-budget-shape:llm:responded",
                    correlation_id="run-budget-shape",
                    payload={"attempt_no": 1, "latency_ms": 10, "usage": {"total_tokens": 107}},
                ),
                ObservationEnvelope.task_lifecycle(
                    kind="task.completed",
                    task_id=task_id,
                    source_kind="deerflow_run",
                    source_id="run-budget-shape",
                    occurred_at=_OBSERVED_AT + timedelta(seconds=2),
                    source_event_id="run-budget-shape:task:completed",
                ),
            )
        )
        # Writer one: terminal control projection.
        await service.flush_task(task_id)
        # Writer two: the assessor, replayed over the same evidence. Its
        # assertion coexists with the first — losing assertions are retained.
        await service.rebuild_until_settled()
        async with session_factory() as session:
            assertions = list(
                (
                    await session.execute(
                        select(AnsichBeliefAssertionRow).where(
                            AnsichBeliefAssertionRow.subject_id == task_id,
                            AnsichBeliefAssertionRow.field_name == "budget_health:total_tokens:local",
                        )
                    )
                ).scalars()
            )
        by_writer = {row.source_name: row.value_json for row in assertions}
        health = await service.get_task_budget_health(task_id)
    finally:
        await service.stop()
        await engine.dispose()

    assert set(by_writer) == {"budget-health", "absolute-limit"}
    terminal = by_writer["budget-health"]
    assessor = by_writer["absolute-limit"]
    # The assessor's shape is the converged shape; the terminal writer adds only
    # `as_of_known`, which the reader infers when it is absent.
    assert set(assessor) <= set(terminal)
    assert set(terminal) - set(assessor) == {"as_of_known"}
    for key in assessor:
        assert terminal[key] == assessor[key], key
    assert terminal["enforcement"] is True
    assert terminal["shadow"] is False
    # And the reader stays shape-stable whichever writer it lands on.
    assert len(health) == 1
    assert health[0].value == "exceeded"
    assert health[0].overshoot == 7
