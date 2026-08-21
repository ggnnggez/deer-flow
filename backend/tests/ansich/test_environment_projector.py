"""SQL projection tests for ``environment-projector@1``.

Covers the coverage/state/per-command rows the projector materializes from
``environment.sampled`` Observations, its dependency wait on the subject Scope
entity, and the replay discipline (same-obs redelivery, late samples and
``rebuild_projections()`` all converge on the same rows).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import anyio
import pytest
from ansich import AnsichService, ObservationEnvelope, new_id
from ansich.safety import scope_entity_id, scope_reference_hash
from sqlalchemy import event, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from deerflow.ansich import create_sql_ansich_service
from deerflow.ansich.persistence.models import (
    AnsichEnvironmentCoverageRow,
    AnsichEnvironmentStateRow,
    AnsichObservationRow,
    AnsichProjectionErrorRow,
    AnsichProjectionJobRow,
    AnsichRelationRow,
    AnsichToolEnvSampleRow,
)
from deerflow.persistence.base import Base

_OCCURRED_AT = datetime(2026, 8, 19, 9, tzinfo=UTC)
_SCOPE_KIND = "sandbox"
_SCOPE_REF = "local:thread-env"
_SCOPE_REF_HASH = scope_reference_hash(_SCOPE_KIND, _SCOPE_REF)
_SCOPE_ID = scope_entity_id(_SCOPE_KIND, _SCOPE_REF_HASH)


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


@asynccontextmanager
async def _environment_service(
    tmp_path: Path,
    database_name: str,
    **overrides: object,
) -> AsyncIterator[tuple[AnsichService, async_sessionmaker[AsyncSession]]]:
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / database_name}",
        # The dependency-wait test polls the job table while the projector loop
        # writes to it; without a busy timeout SQLite reports "database is
        # locked" instead of waiting for the writer.
        connect_args={"timeout": 30},
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    settings: dict[str, object] = {
        "flush_interval_ms": 60_000,
        "terminal_flush_timeout_ms": 10_000,
        "projector_poll_interval_ms": 5,
        "operations_assessment_interval_ms": 60_000,
    }
    settings.update(overrides)
    service = create_sql_ansich_service(session_factory, **settings)
    await service.start()
    try:
        yield service, session_factory
    finally:
        await service.stop()
        await engine.dispose()


def _task_created(task_id: str, run_id: str) -> ObservationEnvelope:
    return ObservationEnvelope.task_lifecycle(
        kind="task.created",
        task_id=task_id,
        source_kind="deerflow_run",
        source_id=run_id,
        occurred_at=_OCCURRED_AT,
        source_event_id=f"run:{run_id}:task:created",
    )


def _scope_snapshotted(task_id: str, run_id: str) -> ObservationEnvelope:
    return ObservationEnvelope.scope_snapshotted(
        task_id=task_id,
        run_id=run_id,
        occurred_at=_OCCURRED_AT,
        scope_kind=_SCOPE_KIND,
        external_ref=_SCOPE_REF,
        relation_role="sandbox_boundary",
        source_event_id=f"run:{run_id}:scope:{_SCOPE_ID}",
    )


def _environment_sampled(
    task_id: str,
    run_id: str,
    *,
    tick: int,
    occurred_at: datetime,
    metrics: dict[str, dict[str, int | None]] | None = None,
    coverage: str = "continuous",
    environment_scope: str = "container",
    provider: str = "local",
    sample_count: int = 1,
    window_started_at: datetime | None = None,
    tool_call_id: str | None = None,
) -> ObservationEnvelope:
    payload: dict[str, object] = {
        "environment_scope": environment_scope,
        "coverage": coverage,
        "provider": provider,
        "metrics": metrics or {},
        "window": {
            "started_at": (window_started_at or _OCCURRED_AT).isoformat(),
            "ended_at": occurred_at.isoformat(),
            "sample_count": sample_count,
        },
    }
    if tool_call_id is not None:
        payload["tool_call_id"] = tool_call_id
    return ObservationEnvelope.environment_sampled(
        task_id=task_id,
        run_id=run_id,
        occurred_at=occurred_at,
        scope_id=_SCOPE_ID,
        payload=payload,
        source_event_id=f"run:{run_id}:env:{_SCOPE_ID}:{tick}",
        producer_seq=tick,
        producer_name="deerflow-environment-probe",
    )


def _fd(value: int, limit: int | None = 1024) -> dict[str, dict[str, int | None]]:
    return {"fd_open": {"value": value, "limit": limit}}


async def _requeue_environment_jobs(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Re-arm every ``environment-projector`` job for a same-obs redelivery."""

    async with session_factory() as session, session.begin():
        await session.execute(
            update(AnsichProjectionJobRow)
            .where(AnsichProjectionJobRow.projector_name == "environment-projector")
            .values(
                status="pending",
                attempts=0,
                available_at=datetime.now(UTC),
                dependency_pending_since=None,
                lease_owner=None,
                lease_expires_at=None,
                last_error=None,
            )
        )


async def _environment_job_statuses(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[str, ...]:
    statuses: tuple[str, ...] = ()
    for _ in range(200):
        async with session_factory() as session:
            statuses = tuple(
                (
                    await session.execute(
                        select(AnsichProjectionJobRow.status).where(
                            AnsichProjectionJobRow.projector_name == "environment-projector",
                        )
                    )
                ).scalars()
            )
        if statuses and all(status in {"completed", "failed"} for status in statuses):
            return statuses
        await anyio.sleep(0.05)
    return statuses


async def _wait_for_dependency_pending_job(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    reason: str,
) -> AnsichProjectionJobRow | None:
    """Sample the environment job once it has parked on its dependency wait."""

    job = None
    for _ in range(200):
        async with session_factory() as session:
            job = await session.scalar(
                select(AnsichProjectionJobRow).where(
                    AnsichProjectionJobRow.projector_name == "environment-projector",
                )
            )
        if job is not None and job.status == "pending" and reason in (job.last_error or ""):
            return job
        await anyio.sleep(0.05)
    return job


async def _projection_snapshot(
    session_factory: async_sessionmaker[AsyncSession],
) -> dict[str, tuple[tuple[object, ...], ...]]:
    async with session_factory() as session:
        coverage_rows = tuple(
            (
                row.scope_id,
                row.environment_scope,
                row.coverage,
                row.provider,
                _utc(row.as_of),
                row.last_obs_id,
            )
            for row in (
                await session.execute(
                    select(AnsichEnvironmentCoverageRow).order_by(
                        AnsichEnvironmentCoverageRow.scope_id,
                        AnsichEnvironmentCoverageRow.environment_scope,
                    )
                )
            ).scalars()
        )
        state_rows = tuple(
            (
                row.scope_id,
                row.environment_scope,
                row.metric,
                row.latest_value,
                row.limit_value,
                _utc(row.as_of),
                _utc(row.window_started_at),
                row.window_min_value,
                row.sample_count,
                row.consecutive_growth_count,
                _utc(row.growth_started_at),
                row.last_obs_id,
                row.provider,
            )
            for row in (
                await session.execute(
                    select(AnsichEnvironmentStateRow).order_by(
                        AnsichEnvironmentStateRow.scope_id,
                        AnsichEnvironmentStateRow.environment_scope,
                        AnsichEnvironmentStateRow.metric,
                    )
                )
            ).scalars()
        )
        sample_rows = tuple(
            (
                row.tool_call_id,
                row.task_id,
                row.scope_id,
                row.io_read_bytes,
                row.io_write_bytes,
                row.fd_peak,
                row.sample_count,
                _utc(row.started_at),
                _utc(row.ended_at),
                row.obs_id,
            )
            for row in (await session.execute(select(AnsichToolEnvSampleRow).order_by(AnsichToolEnvSampleRow.tool_call_id))).scalars()
        )
    return {
        "coverage": coverage_rows,
        "state": state_rows,
        "samples": sample_rows,
    }


@pytest.mark.anyio
async def test_environment_sample_projects_coverage_state_and_scope_relation(tmp_path) -> None:
    task_id, run_id = new_id(), "env-happy-run"
    scope_observation = _scope_snapshotted(task_id, run_id)
    sample = _environment_sampled(
        task_id,
        run_id,
        tick=1,
        occurred_at=_OCCURRED_AT + timedelta(seconds=10),
        metrics=_fd(100),
    )

    async with _environment_service(tmp_path, "ansich-env-happy.db") as (
        service,
        session_factory,
    ):
        service.record_batch((_task_created(task_id, run_id), scope_observation, sample))
        await service.flush_task(task_id)

        async with session_factory() as session:
            coverage = await session.get(AnsichEnvironmentCoverageRow, (_SCOPE_ID, "container"))
            state = await session.get(AnsichEnvironmentStateRow, (_SCOPE_ID, "container", "fd_open"))
            relation = await session.scalar(
                select(AnsichRelationRow).where(
                    AnsichRelationRow.subject_id == task_id,
                    AnsichRelationRow.predicate == "within_scope",
                    AnsichRelationRow.object_id == _SCOPE_ID,
                )
            )
            errors = await session.scalar(select(func.count()).select_from(AnsichProjectionErrorRow))

    assert coverage is not None
    assert (coverage.coverage, coverage.provider) == ("continuous", "local")
    assert _utc(coverage.as_of) == _OCCURRED_AT + timedelta(seconds=10)
    assert coverage.last_obs_id == sample.obs_id
    assert state is not None
    assert (state.latest_value, state.limit_value) == (100, 1024)
    assert state.window_min_value == 100
    assert state.sample_count == 1
    assert state.consecutive_growth_count == 0
    assert state.growth_started_at is None
    assert state.last_obs_id == sample.obs_id
    assert _utc(state.window_started_at) == _OCCURRED_AT
    assert relation is not None
    assert relation.relation_role == "sandbox_boundary"
    assert errors == 0


@pytest.mark.anyio
async def test_consecutive_growth_accumulates_then_resets_on_a_drop(tmp_path) -> None:
    task_id, run_id = new_id(), "env-growth-run"
    growth = tuple(
        _environment_sampled(
            task_id,
            run_id,
            tick=tick,
            occurred_at=_OCCURRED_AT + timedelta(seconds=10 * tick),
            metrics=_fd(value),
        )
        for tick, value in ((1, 100), (2, 110), (3, 120))
    )
    drop = _environment_sampled(
        task_id,
        run_id,
        tick=4,
        occurred_at=_OCCURRED_AT + timedelta(seconds=40),
        metrics=_fd(90),
    )

    async with _environment_service(tmp_path, "ansich-env-growth.db") as (
        service,
        session_factory,
    ):
        service.record_batch((_task_created(task_id, run_id), _scope_snapshotted(task_id, run_id), *growth))
        await service.flush_task(task_id)

        async with session_factory() as session:
            grown = await session.get(AnsichEnvironmentStateRow, (_SCOPE_ID, "container", "fd_open"))
            grown_snapshot = (
                grown.latest_value,
                grown.window_min_value,
                grown.sample_count,
                grown.consecutive_growth_count,
                _utc(grown.growth_started_at),
                grown.last_obs_id,
            )

        service.record(drop)
        await service.flush_task(task_id)

        async with session_factory() as session:
            dropped = await session.get(AnsichEnvironmentStateRow, (_SCOPE_ID, "container", "fd_open"))
            dropped_snapshot = (
                dropped.latest_value,
                dropped.window_min_value,
                dropped.sample_count,
                dropped.consecutive_growth_count,
                dropped.growth_started_at,
            )
            errors = await session.scalar(select(func.count()).select_from(AnsichProjectionErrorRow))

    assert grown_snapshot == (
        120,
        100,
        3,
        2,
        _OCCURRED_AT + timedelta(seconds=20),
        growth[2].obs_id,
    )
    assert dropped_snapshot == (90, 90, 4, 0, None)
    assert errors == 0


@pytest.mark.anyio
async def test_window_min_reanchors_to_the_dip_when_the_growth_streak_breaks(tmp_path) -> None:
    """``window_min_value`` is the minimum since the current run began.

    A lifetime minimum would leave the leak rule comparing ``latest`` against a
    dip nobody is growing away from any more (fd=50 at container start, steady
    working set 400), so any later wobble would read as suspected. The dip here
    (115) is deliberately *above* the historical minimum (100): only a
    re-anchoring projector records it.
    """

    task_id, run_id = new_id(), "env-reanchor-run"
    samples = tuple(
        _environment_sampled(
            task_id,
            run_id,
            tick=tick,
            occurred_at=_OCCURRED_AT + timedelta(seconds=10 * tick),
            metrics=_fd(value),
        )
        # grow 100 -> 110 -> 120, dip to 115 (streak resets), then grow again.
        for tick, value in ((1, 100), (2, 110), (3, 120), (4, 115), (5, 118), (6, 121))
    )

    async with _environment_service(tmp_path, "ansich-env-reanchor.db") as (
        service,
        session_factory,
    ):
        service.record_batch((_task_created(task_id, run_id), _scope_snapshotted(task_id, run_id), *samples[:4]))
        await service.flush_task(task_id)

        async with session_factory() as session:
            dipped = await session.get(AnsichEnvironmentStateRow, (_SCOPE_ID, "container", "fd_open"))
            dipped_snapshot = (dipped.latest_value, dipped.window_min_value, dipped.consecutive_growth_count)

        service.record_batch(samples[4:])
        await service.flush_task(task_id)

        async with session_factory() as session:
            regrown = await session.get(AnsichEnvironmentStateRow, (_SCOPE_ID, "container", "fd_open"))
            regrown_snapshot = (
                regrown.latest_value,
                regrown.window_min_value,
                regrown.consecutive_growth_count,
                _utc(regrown.growth_started_at),
            )
            errors = await session.scalar(select(func.count()).select_from(AnsichProjectionErrorRow))

    # The dip itself becomes the new baseline, not the run's historical 100.
    assert dipped_snapshot == (115, 115, 0)
    # The new run keeps tracking its own starting baseline (the dip value).
    assert regrown_snapshot == (121, 115, 2, _OCCURRED_AT + timedelta(seconds=50))
    assert errors == 0


@pytest.mark.anyio
async def test_same_observation_redelivery_leaves_the_state_row_unchanged(tmp_path) -> None:
    task_id, run_id = new_id(), "env-redelivery-run"
    samples = tuple(
        _environment_sampled(
            task_id,
            run_id,
            tick=tick,
            occurred_at=_OCCURRED_AT + timedelta(seconds=10 * tick),
            metrics=_fd(value),
        )
        for tick, value in ((1, 100), (2, 110))
    )

    async with _environment_service(tmp_path, "ansich-env-redelivery.db") as (
        service,
        session_factory,
    ):
        service.record_batch((_task_created(task_id, run_id), _scope_snapshotted(task_id, run_id), *samples))
        await service.flush_task(task_id)
        before = await _projection_snapshot(session_factory)

        await _requeue_environment_jobs(session_factory)
        statuses = await _environment_job_statuses(session_factory)
        after = await _projection_snapshot(session_factory)

        async with session_factory() as session:
            errors = await session.scalar(select(func.count()).select_from(AnsichProjectionErrorRow))

    assert set(statuses) == {"completed"}
    assert before["state"] and before["state"][0][8] == 2  # sample_count
    assert after == before
    assert errors == 0


@pytest.mark.anyio
async def test_environment_sample_waits_for_the_subject_scope_entity(tmp_path) -> None:
    task_id, run_id = new_id(), "env-dependency-run"
    sample = _environment_sampled(
        task_id,
        run_id,
        tick=1,
        occurred_at=_OCCURRED_AT + timedelta(seconds=10),
        metrics=_fd(100),
    )

    async with _environment_service(
        tmp_path,
        "ansich-env-dependency.db",
        # flush_task is deliberately unused while the dependency is unmet: its
        # terminal timeout would cancel a claim mid-transaction. The background
        # writer and projector loops drive the wait instead.
        flush_interval_ms=20,
    ) as (service, session_factory):
        service.record_batch((_task_created(task_id, run_id), sample))
        waiting_job = await _wait_for_dependency_pending_job(
            session_factory,
            reason=f"waiting for Scope {_SCOPE_ID}",
        )

        async with session_factory() as session:
            pending_errors = await session.scalar(select(func.count()).select_from(AnsichProjectionErrorRow))
            orphan_coverage = await session.scalar(select(func.count()).select_from(AnsichEnvironmentCoverageRow))

        assert waiting_job is not None
        assert waiting_job.status == "pending"
        assert waiting_job.attempts == 0
        assert waiting_job.dependency_pending_since is not None
        assert pending_errors == 0
        assert orphan_coverage == 0

        service.record(_scope_snapshotted(task_id, run_id))
        statuses = await _environment_job_statuses(session_factory)

        async with session_factory() as session:
            state = await session.get(AnsichEnvironmentStateRow, (_SCOPE_ID, "container", "fd_open"))
            healed_errors = await session.scalar(select(func.count()).select_from(AnsichProjectionErrorRow))

    assert statuses == ("completed",)
    assert healed_errors == 0
    assert state is not None
    assert state.latest_value == 100


@pytest.mark.anyio
async def test_per_command_sample_writes_one_tool_row_and_no_state_row(tmp_path) -> None:
    task_id, run_id, tool_call_id = new_id(), "env-per-command-run", new_id()
    sample = _environment_sampled(
        task_id,
        run_id,
        tick=1,
        occurred_at=_OCCURRED_AT + timedelta(seconds=10),
        coverage="per_command",
        environment_scope="process_group",
        sample_count=7,
        window_started_at=_OCCURRED_AT + timedelta(seconds=5),
        metrics={
            "fd_open": {"value": 42, "limit": None},
            "io_read_bytes": {"value": 2048, "limit": None},
            "io_write_bytes": {"value": 512, "limit": None},
        },
        tool_call_id=tool_call_id,
    )

    async with _environment_service(tmp_path, "ansich-env-per-command.db") as (
        service,
        session_factory,
    ):
        service.record_batch((_task_created(task_id, run_id), _scope_snapshotted(task_id, run_id), sample))
        await service.flush_task(task_id)
        before = await _projection_snapshot(session_factory)

        await _requeue_environment_jobs(session_factory)
        statuses = await _environment_job_statuses(session_factory)
        after = await _projection_snapshot(session_factory)

        async with session_factory() as session:
            row = await session.get(AnsichToolEnvSampleRow, tool_call_id)
            state_count = await session.scalar(select(func.count()).select_from(AnsichEnvironmentStateRow))
            coverage = await session.get(AnsichEnvironmentCoverageRow, (_SCOPE_ID, "process_group"))
            errors = await session.scalar(select(func.count()).select_from(AnsichProjectionErrorRow))

    assert set(statuses) == {"completed"}
    assert row is not None
    assert (row.task_id, row.scope_id) == (task_id, _SCOPE_ID)
    assert (row.io_read_bytes, row.io_write_bytes, row.fd_peak) == (2048, 512, 42)
    assert row.sample_count == 7
    assert _utc(row.started_at) == _OCCURRED_AT + timedelta(seconds=5)
    assert _utc(row.ended_at) == _OCCURRED_AT + timedelta(seconds=10)
    assert row.obs_id == sample.obs_id
    assert state_count == 0
    assert coverage is not None
    assert coverage.coverage == "per_command"
    assert len(before["samples"]) == 1
    assert after == before
    assert errors == 0


@pytest.mark.anyio
async def test_uninstrumented_declaration_projects_coverage_only(tmp_path) -> None:
    task_id, run_id = new_id(), "env-uninstrumented-run"
    declaration = _environment_sampled(
        task_id,
        run_id,
        tick=1,
        occurred_at=_OCCURRED_AT + timedelta(seconds=10),
        coverage="uninstrumented",
        sample_count=0,
        metrics={},
    )

    async with _environment_service(tmp_path, "ansich-env-uninstrumented.db") as (
        service,
        session_factory,
    ):
        service.record_batch((_task_created(task_id, run_id), _scope_snapshotted(task_id, run_id), declaration))
        await service.flush_task(task_id)

        async with session_factory() as session:
            coverage = await session.get(AnsichEnvironmentCoverageRow, (_SCOPE_ID, "container"))
            state_count = await session.scalar(select(func.count()).select_from(AnsichEnvironmentStateRow))
            sample_count = await session.scalar(select(func.count()).select_from(AnsichToolEnvSampleRow))
            errors = await session.scalar(select(func.count()).select_from(AnsichProjectionErrorRow))

    assert coverage is not None
    assert coverage.coverage == "uninstrumented"
    assert coverage.last_obs_id == declaration.obs_id
    assert state_count == 0
    assert sample_count == 0
    assert errors == 0


@pytest.mark.anyio
async def test_rebuild_projections_reconstructs_identical_environment_rows(tmp_path) -> None:
    task_id, run_id, tool_call_id = new_id(), "env-rebuild-run", new_id()
    growth = tuple(
        _environment_sampled(
            task_id,
            run_id,
            tick=tick,
            occurred_at=_OCCURRED_AT + timedelta(seconds=10 * tick),
            metrics=_fd(value),
        )
        for tick, value in ((1, 100), (2, 110), (3, 105))
    )
    per_command = _environment_sampled(
        task_id,
        run_id,
        tick=4,
        occurred_at=_OCCURRED_AT + timedelta(seconds=40),
        coverage="per_command",
        environment_scope="process_group",
        sample_count=3,
        window_started_at=_OCCURRED_AT + timedelta(seconds=35),
        metrics={"fd_open": {"value": 11, "limit": None}},
        tool_call_id=tool_call_id,
    )

    async with _environment_service(tmp_path, "ansich-env-rebuild.db") as (
        service,
        session_factory,
    ):
        service.record_batch(
            (
                _task_created(task_id, run_id),
                _scope_snapshotted(task_id, run_id),
                *growth,
                per_command,
            )
        )
        await service.flush_task(task_id)
        before = await _projection_snapshot(session_factory)

        await service.rebuild_projections()
        after = await _projection_snapshot(session_factory)

        async with session_factory() as session:
            errors = await session.scalar(select(func.count()).select_from(AnsichProjectionErrorRow))

    assert before["coverage"] and before["state"] and before["samples"]
    assert after == before
    assert errors == 0


def _oversized_metrics(count: int = 800) -> dict[str, dict[str, int | None]]:
    """Metrics whose canonical JSON puts one sample over 65536 bytes.

    Nothing here lowers ``inline_payload_max_bytes``: the threshold is the
    production default, and the point of F10-29 is that nothing exempts
    ``environment.sampled`` from it. Environment payloads are *usually* small,
    which is why all three instances of the class stayed unnoticed -- but a
    Scope reporting a few hundred per-metric readings crosses the line, and
    from there the sample is stored in ``ansich_payloads`` with
    ``payload_json IS NULL`` like any other externalized payload.
    """

    # Long but canonical metric names (`^[a-z][a-z0-9_]{0,63}$`), so the size
    # comes from the payload's own legal shape rather than from junk.
    padding = "_" + "e" * 40
    return {f"fd_open_shard_{index:04d}{padding}": {"value": 100 + index, "limit": 1024} for index in range(count)}


@pytest.mark.anyio
async def test_an_externalized_environment_sample_projects_reads_back_and_keeps_its_history(tmp_path) -> None:
    """F10-29: the whole reader class, on one row nothing exempted from the threshold.

    Red before the fix in three separate places: the claim built the envelope
    *before* hydrating, so ``environment-projector@1`` could not even claim the
    job; ``list_observations`` handed the contract a ``None`` payload it raised
    on unconditionally; and the history reader guard-and-skipped the row, so
    the sample dropped out of the trend series without a trace.
    """

    task_id, run_id = new_id(), "env-externalized-run"
    metrics = _oversized_metrics()
    probe_metric = sorted(metrics)[0]
    occurred_at = datetime.now(UTC) - timedelta(seconds=5)
    sample = _environment_sampled(
        task_id,
        run_id,
        tick=1,
        occurred_at=occurred_at,
        metrics=metrics,
    )

    async with _environment_service(tmp_path, "ansich-env-externalized.db") as (
        service,
        session_factory,
    ):
        service.record_batch((_task_created(task_id, run_id), _scope_snapshotted(task_id, run_id), sample))
        await service.flush_task(task_id)
        statuses = await _environment_job_statuses(session_factory)

        async with session_factory() as session:
            stored = await session.scalar(select(AnsichObservationRow).where(AnsichObservationRow.obs_id == sample.obs_id))
            stored_state = (stored.payload_json, stored.payload_ref_id is not None)
            state_row_count = await session.scalar(select(func.count()).select_from(AnsichEnvironmentStateRow).where(AnsichEnvironmentStateRow.scope_id == _SCOPE_ID))
            coverage = await session.get(AnsichEnvironmentCoverageRow, (_SCOPE_ID, "container"))
            projected = await session.get(AnsichEnvironmentStateRow, (_SCOPE_ID, "container", probe_metric))
            errors = await session.scalar(select(func.count()).select_from(AnsichProjectionErrorRow))

        observations = await service.list_observations(task_id)
        history = await service.get_environment_history(
            _SCOPE_ID,
            environment_scope="container",
            metric=probe_metric,
            window_minutes=60,
            max_points=100,
        )

    # The row really is externalized -- this is the precondition every leg below
    # depends on, so it is asserted rather than inferred from the byte count.
    assert stored_state == (None, True)

    # (b) claim + project: the job lands instead of failing on its own claim.
    assert statuses == ("completed",)
    assert errors == 0
    assert coverage is not None and coverage.coverage == "continuous"
    assert projected is not None
    assert (projected.latest_value, projected.limit_value) == (metrics[probe_metric]["value"], 1024)
    assert state_row_count == len(metrics)

    # (a) public read-back: the envelope validates, carrying the ref rather than
    # a hydrated payload (this read is deliberately cheap and does not hydrate).
    read_back = [item for item in observations if item.kind == "environment.sampled"]
    assert [item.obs_id for item in read_back] == [sample.obs_id]
    assert read_back[0].payload is None
    assert read_back[0].payload_ref_id is not None

    # (c) history: the point is present with full content, not silently dropped.
    assert history.truncated is False
    assert [(point.value, point.limit) for point in history.points] == [(metrics[probe_metric]["value"], 1024)]
