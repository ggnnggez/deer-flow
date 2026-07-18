import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from ansich import ObservationEnvelope, new_id
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from deerflow.ansich import create_sql_ansich_service
from deerflow.ansich.persistence.models import AnsichBeliefAssertionRow
from deerflow.persistence.base import Base


@pytest.mark.anyio
async def test_sql_heartbeat_projection_returns_latest_evidence_after_rebuild(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-heartbeat.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(session_factory)
    await service.start()
    task_id = new_id()
    observed_at = datetime(2026, 7, 18, 10, 10, tzinfo=UTC)
    first = ObservationEnvelope.task_heartbeat(
        task_id=task_id,
        run_id="run-sql-heartbeat",
        occurred_at=observed_at + timedelta(seconds=10),
        elapsed_ms=10_000,
        worker_id="worker-a",
        ownership_epoch="worker-a",
        source_event_id="run:run-sql-heartbeat:task:heartbeat:1",
    )
    second = ObservationEnvelope.task_heartbeat(
        task_id=task_id,
        run_id="run-sql-heartbeat",
        occurred_at=observed_at + timedelta(seconds=20),
        elapsed_ms=20_000,
        worker_id="worker-a",
        ownership_epoch="worker-a",
        source_event_id="run:run-sql-heartbeat:task:heartbeat:2",
        producer_seq=2,
    )

    try:
        service.record(
            ObservationEnvelope.task_lifecycle(
                kind="task.created",
                task_id=task_id,
                source_kind="deerflow_run",
                source_id="run-sql-heartbeat",
                occurred_at=observed_at,
                source_event_id="run:run-sql-heartbeat:task:created",
            )
        )
        service.record(first)
        service.record(second)
        await service.flush_task(task_id)
        heartbeat = await service.get_task_heartbeat(task_id)
        usage = await service.get_task_usage(task_id)
        await service.rebuild_projections()
        rebuilt = await service.get_task_heartbeat(task_id)
        rebuilt_usage = await service.get_task_usage(task_id)
    finally:
        await service.stop()
        await engine.dispose()

    assert heartbeat == rebuilt
    assert usage == rebuilt_usage
    assert heartbeat is not None
    assert heartbeat.heartbeat_obs_id == second.obs_id
    assert heartbeat.occurred_at == second.occurred_at
    assert heartbeat.producer_instance_id == second.producer.instance_id
    assert heartbeat.ownership_epoch == "worker-a"
    assert heartbeat.elapsed_ms == 20_000
    assert [(item.dimension, item.value) for item in usage.local] == [("wall_time_ms", 20_000)]


@pytest.mark.anyio
async def test_heartbeat_assessor_persists_stale_and_recovery_without_changing_control(
    tmp_path,
):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-heartbeat-assessment.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(
        session_factory,
        heartbeat_stale_after_seconds=30,
        operations_assessment_interval_ms=60_000,
    )
    await service.start()
    task_id = new_id()
    started_at = datetime(2026, 7, 18, 11, tzinfo=UTC)

    try:
        service.record_batch(
            (
                ObservationEnvelope.task_lifecycle(
                    kind="task.created",
                    task_id=task_id,
                    source_kind="deerflow_run",
                    source_id="run-heartbeat-assessment",
                    occurred_at=started_at,
                    source_event_id="run:run-heartbeat-assessment:task:created",
                ),
                ObservationEnvelope.task_lifecycle(
                    kind="task.started",
                    task_id=task_id,
                    source_kind="deerflow_run",
                    source_id="run-heartbeat-assessment",
                    occurred_at=started_at,
                    source_event_id="run:run-heartbeat-assessment:task:started",
                ),
                ObservationEnvelope.task_heartbeat(
                    task_id=task_id,
                    run_id="run-heartbeat-assessment",
                    occurred_at=started_at + timedelta(seconds=10),
                    elapsed_ms=10_000,
                    worker_id="worker-a",
                    ownership_epoch="worker-a",
                    source_event_id="run:run-heartbeat-assessment:task:heartbeat:1",
                ),
            )
        )
        await service.flush_task(task_id)

        fresh_changes = await service.assess_operations(now=started_at + timedelta(seconds=39))
        repeated_fresh_changes = await service.assess_operations(now=started_at + timedelta(seconds=40))
        active_while_fresh = await service.list_active_tasks()
        async with session_factory() as session:
            fresh_assertions = list(
                (
                    await session.execute(
                        select(AnsichBeliefAssertionRow).where(
                            AnsichBeliefAssertionRow.subject_id == task_id,
                            AnsichBeliefAssertionRow.field_name == "heartbeat",
                        )
                    )
                ).scalars()
            )
        stale_changes = await service.assess_operations(now=started_at + timedelta(seconds=41))
        stale = await service.get_task_heartbeat_belief(task_id)
        async with session_factory() as session:
            stale_assertions = list(
                (
                    await session.execute(
                        select(AnsichBeliefAssertionRow).where(
                            AnsichBeliefAssertionRow.subject_id == task_id,
                            AnsichBeliefAssertionRow.field_name == "heartbeat",
                        )
                    )
                ).scalars()
            )

        recovery = ObservationEnvelope.task_heartbeat(
            task_id=task_id,
            run_id="run-heartbeat-assessment",
            occurred_at=started_at + timedelta(seconds=45),
            elapsed_ms=45_000,
            worker_id="worker-a",
            ownership_epoch="worker-a",
            source_event_id="run:run-heartbeat-assessment:task:heartbeat:2",
            producer_seq=2,
        )
        service.record(recovery)
        await service.flush_task(task_id)
        recovery_changes = await service.assess_operations(now=started_at + timedelta(seconds=46))
        recovered = await service.get_task_heartbeat_belief(task_id)
        task = await service.get_task(task_id)
    finally:
        await service.stop()
        await engine.dispose()

    assert fresh_changes == 1
    assert repeated_fresh_changes == 0
    assert len(fresh_assertions) == 1
    assert fresh_assertions[0].value_json == {"value": "fresh"}
    assert active_while_fresh[0].heartbeat.age_ms == 30_000
    assert stale_changes == 1
    assert len(stale_assertions) == 2
    assert [assertion.value_json for assertion in stale_assertions] == [
        {"value": "fresh"},
        {"value": "stale"},
    ]
    assert stale is not None
    assert stale.value == "stale"
    assert stale.age_ms == 31_000
    assert recovery_changes == 1
    assert recovered is not None
    assert recovered.value == "fresh"
    assert recovered.evidence_obs_ids == (recovery.obs_id,)
    assert recovered.selected_by.version == stale.selected_by.version
    assert task is not None
    assert task.control.value == "running"


@pytest.mark.anyio
async def test_background_assessor_materializes_running_task_heartbeat_belief(
    tmp_path,
):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-heartbeat-background.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(
        session_factory,
        projector_poll_interval_ms=10,
        operations_assessment_interval_ms=10,
    )
    await service.start()
    task_id = new_id()
    now = datetime.now(UTC)

    try:
        service.record_batch(
            (
                ObservationEnvelope.task_lifecycle(
                    kind="task.created",
                    task_id=task_id,
                    source_kind="deerflow_run",
                    source_id="run-heartbeat-background",
                    occurred_at=now,
                    source_event_id="run:run-heartbeat-background:task:created",
                ),
                ObservationEnvelope.task_lifecycle(
                    kind="task.started",
                    task_id=task_id,
                    source_kind="deerflow_run",
                    source_id="run-heartbeat-background",
                    occurred_at=now,
                    source_event_id="run:run-heartbeat-background:task:started",
                ),
            )
        )
        await service.flush_task(task_id)
        async with asyncio.timeout(1):
            while (await service.get_task_heartbeat_belief(task_id)) is None:
                await asyncio.sleep(0.01)
        belief = await service.get_task_heartbeat_belief(task_id)
    finally:
        await service.stop()
        await engine.dispose()

    assert belief is not None
    assert belief.value == "unknown"
