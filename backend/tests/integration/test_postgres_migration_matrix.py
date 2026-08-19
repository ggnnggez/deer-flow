"""Opt-in PostgreSQL migration matrix + one end-to-end service smoke.

Everything DeerFlow persists is developed against SQLite, but ``database.backend:
postgres`` is a supported production shape and the whole ``versions/`` chain has
never executed against a real server. This module is that gate: it runs the real
migrations, the real ``bootstrap_schema`` branches, and one real Ansich service
against a live PostgreSQL.

Opt-in and self-skipping, mirroring the redis tier in
``tests/test_sandbox_ownership_store.py``: every test carries
``@pytest.mark.integration`` and the module skips itself unless
``DEER_FLOW_TEST_POSTGRES_URL`` points at a reachable server. Unlike the redis
tier there is deliberately **no** default URL -- these tests ``CREATE DATABASE``
/ ``DROP DATABASE`` on the server they are pointed at, so falling back to a
conventional localhost address would let a bare ``pytest`` run touch a developer's
real cluster. No env var means no postgres, full stop.

Spin one up::

    docker run --rm -d --name deerflow-pg-test -p 5433:5432 \\
        -e POSTGRES_PASSWORD=deerflow-test postgres:16
    export DEER_FLOW_TEST_POSTGRES_URL=postgresql+asyncpg://postgres:deerflow-test@localhost:5433/postgres
    cd backend && make test-postgres

Isolation idiom: the redis tier keeps its runs re-runnable with a per-factory
random key prefix; the equivalent unit here is a whole database. Each test
``CREATE DATABASE``s a uniquely-named one on the configured server, runs against
it, and drops it in ``finally`` -- so a crashed run leaves at most one stray
database rather than a half-migrated schema the next run would inherit.
``CREATE``/``DROP DATABASE`` cannot run inside a transaction block, hence the
``isolation_level="AUTOCOMMIT"`` admin engine.

Scope is the migration matrix, the bootstrap branches, and a single end-to-end
service smoke. Running the *whole* suite against postgres is a separate,
much larger question and is deliberately not attempted here.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from alembic import command as alembic_command
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

# Pre-import models so ``Base.metadata`` is populated before anything reads it.
import deerflow.persistence.models  # noqa: F401
from deerflow.persistence.base import Base
from deerflow.persistence.bootstrap import (
    _get_alembic_config,
    _get_head_revision,
    bootstrap_schema,
)

POSTGRES_TEST_URL = os.environ.get("DEER_FLOW_TEST_POSTGRES_URL")

# The last revision before the first Ansich revision. Downgrading here walks
# every Ansich migration's ``downgrade`` (both 0005 branches and the 0006
# merge included); re-upgrading walks every ``upgrade`` a second time.
PRE_ANSICH_REVISION = "0004_run_ownership"


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
# Per-test database isolation
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _postgres_engine() -> AsyncIterator[AsyncEngine]:
    """Yield an engine bound to a fresh, uniquely-named database.

    The database is dropped on the way out even when the test fails, so the
    tier stays re-runnable against a long-lived server.
    """
    server_url = make_url(POSTGRES_TEST_URL)
    db_name = f"deerflow_pg_matrix_{uuid.uuid4().hex[:16]}"
    # ``CREATE``/``DROP DATABASE`` are refused inside a transaction block, and
    # SQLAlchemy opens one implicitly on first execute -- AUTOCOMMIT is what
    # keeps these two statements legal.
    admin = create_async_engine(_connect_url(server_url), isolation_level="AUTOCOMMIT", poolclass=NullPool)
    try:
        async with admin.connect() as conn:
            await conn.execute(sa.text(f'CREATE DATABASE "{db_name}"'))
        engine = create_async_engine(_connect_url(server_url.set(database=db_name)))
        try:
            yield engine
        finally:
            await engine.dispose()
            async with admin.connect() as conn:
                # Any connection still open on the database blocks the drop;
                # a test that failed mid-flight can easily leave one behind.
                await conn.execute(
                    sa.text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = :name AND pid <> pg_backend_pid()"),
                    {"name": db_name},
                )
                await conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{db_name}"'))
    finally:
        await admin.dispose()


# ---------------------------------------------------------------------------
# Alembic + reflection helpers
# ---------------------------------------------------------------------------


async def _upgrade(engine: AsyncEngine, revision: str = "head") -> None:
    # ``migrations/env.py`` calls ``asyncio.run`` itself, so alembic must not be
    # invoked from a thread that already owns a running loop.
    await asyncio.to_thread(alembic_command.upgrade, _get_alembic_config(engine), revision)


async def _downgrade(engine: AsyncEngine, revision: str) -> None:
    await asyncio.to_thread(alembic_command.downgrade, _get_alembic_config(engine), revision)


async def _stamp(engine: AsyncEngine, revision: str) -> None:
    await asyncio.to_thread(alembic_command.stamp, _get_alembic_config(engine), revision)


async def _table_names(engine: AsyncEngine) -> set[str]:
    async with engine.connect() as conn:
        return await conn.run_sync(lambda c: set(sa.inspect(c).get_table_names()))


async def _alembic_version(engine: AsyncEngine) -> str | None:
    async with engine.connect() as conn:
        return (await conn.execute(sa.text("SELECT version_num FROM alembic_version"))).scalar()


def _expected_ansich_tables() -> set[str]:
    tables = {name for name in Base.metadata.tables if name.startswith("ansich_")}
    # Every ansich assertion below is a set difference, so an empty expectation
    # would make all of them pass vacuously.
    assert tables, "no ansich_* tables in Base.metadata -- the assertions below would prove nothing"
    return tables


# ---------------------------------------------------------------------------
# 1. Empty database -> upgrade head
# ---------------------------------------------------------------------------


async def test_upgrade_head_on_an_empty_postgres_database() -> None:
    """The whole chain applies to a virgin postgres and lands on head.

    ``alembic_version`` is compared against ``_get_head_revision()`` rather than
    a literal so a revision added after this test was written still gates.
    """
    async with _postgres_engine() as engine:
        await _upgrade(engine)

        tables = await _table_names(engine)
        assert await _alembic_version(engine) == _get_head_revision()

        missing_ansich = _expected_ansich_tables() - tables
        assert not missing_ansich, f"migrations did not create these ansich tables on postgres: {sorted(missing_ansich)}"

        # The DeerFlow-owned baseline tables have to arrive too -- an ansich-only
        # assertion would pass on a chain that never created ``runs``.
        for required in ("runs", "threads_meta", "feedback", "users", "run_events"):
            assert required in tables, f"missing table: {required}"


# ---------------------------------------------------------------------------
# 2. Reversibility: head -> 0004 -> head
# ---------------------------------------------------------------------------


async def test_downgrade_to_pre_ansich_and_re_upgrade_to_head() -> None:
    """Every Ansich revision's ``downgrade`` runs, then every ``upgrade`` again.

    A downgrade that cannot execute on postgres is a real defect even though
    production never runs one automatically: it is the only rollback path an
    operator has when an upgrade goes wrong on a live database.
    """
    async with _postgres_engine() as engine:
        await _upgrade(engine)
        assert await _alembic_version(engine) == _get_head_revision()

        await _downgrade(engine, PRE_ANSICH_REVISION)

        assert await _alembic_version(engine) == PRE_ANSICH_REVISION
        leftover = _expected_ansich_tables() & await _table_names(engine)
        assert not leftover, f"downgrade to {PRE_ANSICH_REVISION} left ansich tables behind: {sorted(leftover)}"

        await _upgrade(engine)

        assert await _alembic_version(engine) == _get_head_revision()
        assert not (_expected_ansich_tables() - await _table_names(engine))


# ---------------------------------------------------------------------------
# 3. Idempotence: a second upgrade is a no-op
# ---------------------------------------------------------------------------


async def test_second_upgrade_head_is_a_no_op() -> None:
    """Gateway startup runs ``upgrade head`` on every boot; the second must be free."""
    async with _postgres_engine() as engine:
        await _upgrade(engine)
        tables_before = await _table_names(engine)

        await _upgrade(engine)

        assert await _alembic_version(engine) == _get_head_revision()
        assert await _table_names(engine) == tables_before


# ---------------------------------------------------------------------------
# 4. bootstrap_schema branches on postgres
# ---------------------------------------------------------------------------


async def test_bootstrap_schema_branches_on_postgres() -> None:
    """The three-branch bootstrap, including the postgres advisory lock path.

    * empty -- ``create_all`` + ``stamp head``. This is the branch that renders
      ``Base.metadata`` through the postgres dialect (JSONB, partial indexes),
      so it is also the check that the ORM models compile as DDL here at all.
    * versioned -- an existing ``alembic_version`` at an older revision must be
      upgraded rather than stamped over.
    * legacy -- DeerFlow tables but no ``alembic_version``: baseline backfill,
      stamp ``0001_baseline``, then upgrade head across every guarded
      ``create_table`` in the chain.
    """
    # -- empty branch -------------------------------------------------------
    async with _postgres_engine() as engine:
        await bootstrap_schema(engine, backend="postgres")

        tables = await _table_names(engine)
        assert await _alembic_version(engine) == _get_head_revision()
        assert "runs" in tables
        missing = _expected_ansich_tables() - tables
        assert not missing, f"empty-branch create_all missed ansich tables: {sorted(missing)}"

    # -- versioned branch ---------------------------------------------------
    async with _postgres_engine() as engine:
        await _upgrade(engine, PRE_ANSICH_REVISION)
        assert await _alembic_version(engine) == PRE_ANSICH_REVISION

        await bootstrap_schema(engine, backend="postgres")

        assert await _alembic_version(engine) == _get_head_revision()
        assert not (_expected_ansich_tables() - await _table_names(engine))

    # -- legacy branch ------------------------------------------------------
    # Not skipped as SQLite-specific: the seeding here is a plain ``create_all``
    # plus dropping ``alembic_version``, which is exactly what a pre-alembic
    # postgres deployment looks like. It is the branch that drives every
    # revision's "already exists" guard on this dialect.
    async with _postgres_engine() as engine:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        assert "alembic_version" not in await _table_names(engine)

        await bootstrap_schema(engine, backend="postgres")

        assert await _alembic_version(engine) == _get_head_revision()
        assert not (_expected_ansich_tables() - await _table_names(engine))


# ---------------------------------------------------------------------------
# 5. End-to-end service smoke on the migrated schema
# ---------------------------------------------------------------------------


async def test_ansich_service_records_and_projects_on_postgres() -> None:
    """One real service, on a real migrated postgres, end to end.

    Deliberately narrow -- a Task, a Step, an evaluation, a projection read, a
    Belief read and a replay. Its job is to prove the migrated schema is usable
    by the code that owns it (types, FKs, ``SELECT ... FOR UPDATE`` on the
    release-stats cell), not to re-run the Ansich suite on another backend.
    """
    from ansich import (
        EvaluationRecord,
        NamedVersion,
        ObservationEnvelope,
        Producer,
        ScoreScale,
        build_evaluation_observation,
        new_id,
    )
    from ansich.release import AgentRuntimeDescriptor, RuntimeBuildDescriptor, build_agent_release

    from deerflow.ansich import create_sql_ansich_service
    from deerflow.ansich.persistence.models import (
        AnsichEvaluationIndexRow,
        AnsichProjectionErrorRow,
        AnsichReleaseQualityStatsRow,
    )

    occurred_at = datetime(2026, 8, 18, 9, tzinfo=UTC)
    producer = Producer(name="ansich-postgres-smoke", version="1", instance_id="test")
    assessor = NamedVersion(name="ansich-benchmark-runner", version="1.0.0")
    task_id, step_id, run_id = new_id(), new_id(), "pg-smoke-run"

    release = build_agent_release(
        AgentRuntimeDescriptor(
            namespace="deerflow",
            agent_name="lead-agent",
            requested_model="requested-alias",
            effective_model="provider/model-v1",
            model_provider="provider",
            model_behavior_parameters={"model": "provider/model-v1"},
            rendered_base_prompt="You are DeerFlow.",
            prompt_template_id="lead-v1",
            effective_policies={"non_interactive": False},
            runtime_build=RuntimeBuildDescriptor(package_version="2.1.0"),
        )
    )
    observations = (
        ObservationEnvelope.task_lifecycle(
            kind="task.created",
            task_id=task_id,
            source_kind="deerflow_run",
            source_id=run_id,
            occurred_at=occurred_at,
            source_event_id=f"run:{run_id}:task:created",
        ),
        ObservationEnvelope.agent_release_resolved(
            task_id=task_id,
            run_id=run_id,
            occurred_at=occurred_at,
            release=release,
            source_event_id=f"run:{run_id}:agent-release:resolved",
        ),
        ObservationEnvelope(
            kind="step.started",
            occurred_at=occurred_at,
            task_id=task_id,
            step_id=step_id,
            subject_type="step",
            subject_id=step_id,
            producer=producer,
            source_event_id=f"step:{step_id}:started",
            correlation_id=task_id,
            payload={"step_seq": 1, "actor_kind": "lead_agent"},
        ),
        build_evaluation_observation(
            EvaluationRecord(
                subject_type="task",
                subject_id=task_id,
                task_id=task_id,
                evaluation_kind="benchmark_assertion",
                dimension="correctness",
                verdict="pass",
                score=1.0,
                scale=ScoreScale(min=0.0, max=1.0, higher_is_better=True),
                assessor=assessor,
                fidelity_class="hard",
                suite="ansich-regression",
                suite_version="2026.08.1",
                case_id="pg-smoke-case",
                run_id="bench-pg-smoke",
                occurred_at=occurred_at,
            ),
            producer=producer,
        ),
    )
    evaluation_obs_id = observations[-1].obs_id

    async with _postgres_engine() as engine:
        await _upgrade(engine)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        service = create_sql_ansich_service(
            session_factory,
            flush_interval_ms=60_000,
            projector_poll_interval_ms=5,
            operations_assessment_interval_ms=60_000,
        )
        await service.start()
        try:
            service.record_batch(observations)
            await service.flush_task(task_id)

            task = await service.get_task(task_id)
            step_views = await service.list_steps(task_id)
            belief = await service.get_current_belief(task_id, "quality.correctness")
            async with session_factory() as session:
                index_row = await session.get(AnsichEvaluationIndexRow, evaluation_obs_id)
                stats = (await session.execute(sa.select(AnsichReleaseQualityStatsRow))).scalars().all()
                failures = await session.scalar(sa.select(sa.func.count()).select_from(AnsichProjectionErrorRow))

            assert failures == 0
            assert task is not None and task.task_id == task_id
            assert [view.step_seq for view in step_views] == [1]
            assert index_row is not None
            assert (index_row.dimension, index_row.verdict, index_row.score) == ("correctness", "pass", 1.0)
            assert index_row.cohort_key == "ansich-regression@2026.08.1"
            assert belief is not None
            assert belief.value["verdict"] == "pass"
            # The release-stats cell is the one write that takes an explicit
            # ``SELECT ... FOR UPDATE``, which is a no-op on SQLite and real here.
            assert len(stats) == 1
            assert (stats[0].assessed_count, stats[0].pass_count) == (1, 1)

            replayed = await service.rebuild_projections()

            assert replayed > 0
            assert await service.get_current_belief(task_id, "quality.correctness") is not None
            async with session_factory() as session:
                assert await session.get(AnsichEvaluationIndexRow, evaluation_obs_id) is not None
                assert await session.scalar(sa.select(sa.func.count()).select_from(AnsichProjectionErrorRow)) == 0
        finally:
            await service.stop()
