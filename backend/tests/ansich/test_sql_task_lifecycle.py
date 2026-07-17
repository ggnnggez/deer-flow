from datetime import UTC, datetime

import pytest
from ansich import AnsichService, ObservationEnvelope, new_id
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from deerflow.ansich import create_sql_ansich_service
from deerflow.ansich.persistence.models import (
    AnsichObservationRow,
    AnsichProjectionErrorRow,
    AnsichProjectionJobRow,
    AnsichRelationRow,
    AnsichScopeRow,
)
from deerflow.ansich.persistence.sql import SqlAnsichBackend
from deerflow.persistence.base import Base


@pytest.mark.anyio
async def test_task_remains_queryable_after_service_restart(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    task_id = new_id()
    observed_at = datetime(2026, 7, 17, 9, 0, tzinfo=UTC)
    first_service = create_sql_ansich_service(session_factory)
    await first_service.start()
    first_service.record(
        ObservationEnvelope.task_lifecycle(
            kind="task.created",
            task_id=task_id,
            source_kind="deerflow_run",
            source_id="run-persisted",
            occurred_at=observed_at,
            source_event_id="run:run-persisted:task:created",
            thread_id="thread-persisted",
            owner_id="owner-persisted",
        )
    )
    terminal = first_service.record(
        ObservationEnvelope.task_lifecycle(
            kind="task.completed",
            task_id=task_id,
            source_kind="deerflow_run",
            source_id="run-persisted",
            occurred_at=observed_at,
            source_event_id="run:run-persisted:task:completed",
        )
    )
    await first_service.flush_task(task_id)
    await first_service.stop()

    restarted_service = create_sql_ansich_service(session_factory)
    await restarted_service.start()
    try:
        task = await restarted_service.get_task(task_id)
    finally:
        await restarted_service.stop()
        await engine.dispose()

    assert task is not None
    assert task.source_id == "run-persisted"
    assert task.control.value == "completed"
    assert task.control.evidence_obs_ids == (terminal.obs_id,)


@pytest.mark.anyio
async def test_writer_deduplicates_observation_and_projects_owner_and_thread_scopes(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-scopes.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(session_factory)
    await service.start()
    task_id = new_id()
    observation = ObservationEnvelope.task_lifecycle(
        kind="task.created",
        task_id=task_id,
        source_kind="deerflow_run",
        source_id="run-scoped",
        occurred_at=datetime(2026, 7, 17, 10, 0, tzinfo=UTC),
        source_event_id="run:run-scoped:task:created",
        producer_seq=42,
        thread_id="thread-scoped",
        owner_id="owner-scoped",
    )

    try:
        service.record(observation)
        service.record(observation)
        await service.flush_task(task_id)
        async with session_factory() as session:
            observation_count = await session.scalar(select(func.count()).select_from(AnsichObservationRow))
            job_count = await session.scalar(select(func.count()).select_from(AnsichProjectionJobRow))
            scope_count = await session.scalar(select(func.count()).select_from(AnsichScopeRow))
            relation_count = await session.scalar(select(func.count()).select_from(AnsichRelationRow))
            stored = await session.scalar(select(AnsichObservationRow))
    finally:
        await service.stop()
        await engine.dispose()

    assert observation_count == 1
    assert job_count == 2
    assert scope_count == 2
    assert relation_count == 2
    assert stored is not None
    assert stored.producer_seq == 42


@pytest.mark.anyio
async def test_projection_failure_keeps_raw_observation_and_records_retry_evidence(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-projector-failure.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    backend = SqlAnsichBackend(session_factory, projector_max_attempts=1)

    async def fail_control_projection(*_args, **_kwargs) -> None:
        raise RuntimeError("projector exploded")

    monkeypatch.setattr(backend, "_project_control", fail_control_projection)
    service = AnsichService(backend, flush_interval_ms=60_000)
    await service.start()
    task_id = new_id()
    service.record(
        ObservationEnvelope.task_lifecycle(
            kind="task.created",
            task_id=task_id,
            source_kind="deerflow_run",
            source_id="run-projector-failure",
            occurred_at=datetime(2026, 7, 17, 11, 0, tzinfo=UTC),
            source_event_id="run:run-projector-failure:task:created",
        )
    )

    try:
        flush = await service.flush_task(task_id)
        task = await service.get_task(task_id)
        health = service.get_health()
        async with session_factory() as session:
            observation_count = await session.scalar(select(func.count()).select_from(AnsichObservationRow))
            error_count = await session.scalar(select(func.count()).select_from(AnsichProjectionErrorRow))
            statuses = list((await session.execute(select(AnsichProjectionJobRow.status))).scalars())
    finally:
        await service.stop()
        await engine.dispose()

    assert flush.persisted is True
    assert observation_count == 1
    assert error_count == 1
    assert sorted(statuses) == ["completed", "failed"]
    assert task is not None
    assert task.control.value == "unknown"
    assert task.control.evidence_obs_ids == ()
    assert health.status == "degraded"
    assert health.failed_jobs == 1


@pytest.mark.anyio
async def test_projection_tables_can_be_rebuilt_from_durable_observations(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-replay.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    backend = SqlAnsichBackend(session_factory)
    service = AnsichService(backend)
    await service.start()
    task_id = new_id()
    observed_at = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)

    try:
        for producer_seq, kind in enumerate(("task.created", "task.started", "task.completed"), start=1):
            service.record(
                ObservationEnvelope.task_lifecycle(
                    kind=kind,
                    task_id=task_id,
                    source_kind="deerflow_run",
                    source_id="run-replay",
                    occurred_at=observed_at,
                    source_event_id=f"run:run-replay:{kind}",
                    producer_seq=producer_seq,
                    thread_id="thread-replay",
                    owner_id="owner-replay",
                )
            )
        await service.flush_task(task_id)
        before = await service.get_task(task_id)

        # Rebuild must go through the service so it cannot race the
        # background projector loop over the same reset jobs (F7).
        assert await service.rebuild_projections() > 0

        after = await service.get_task(task_id)
        observations = await service.list_observations(task_id)
    finally:
        await service.stop()
        await engine.dispose()

    assert before is not None
    assert after == before
    assert len(observations) == 3


@pytest.mark.anyio
async def test_projection_claim_order_follows_registry_priority_not_alphabetical(tmp_path, monkeypatch):
    """Adding a projector whose name sorts first alphabetically must not jump the queue (F4)."""
    from deerflow.ansich.persistence import sql as sql_module

    # Simulate a Phase 2-style registry extension: "usage-rollup" sorts after
    # "task-structural" in the old projector_name.desc() ordering, so an
    # alphabetical claim would run it before both existing projectors.
    monkeypatch.setattr(sql_module, "_PROJECTORS", (*sql_module._PROJECTORS, ("usage-rollup", "1")))

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-priority.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    backend = SqlAnsichBackend(session_factory)

    try:
        await backend.persist_and_project(
            [
                ObservationEnvelope.task_lifecycle(
                    kind="task.created",
                    task_id=new_id(),
                    source_kind="deerflow_run",
                    source_id="run-priority",
                    occurred_at=datetime(2026, 7, 17, 13, 0, tzinfo=UTC),
                    source_event_id="run:run-priority:task:created",
                )
            ]
        )
        claimed_names = []
        for _ in range(3):
            claim = await backend._claim_projection_job()
            assert claim is not None
            claimed_names.append(claim[1])
    finally:
        await engine.dispose()

    assert claimed_names == ["task-structural", "task-control", "usage-rollup"]
