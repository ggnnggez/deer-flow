from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from ansich import ObservationEnvelope, Producer, new_id
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateTable

from deerflow.ansich import create_sql_ansich_service
from deerflow.ansich.persistence.models import (
    AnsichActiveTaskReadModelRow,
    AnsichTaskBudgetRow,
    AnsichTaskHeartbeatRow,
    AnsichTaskUsageRow,
    AnsichUsageContributionRow,
)
from deerflow.persistence.base import Base


@pytest.mark.anyio
async def test_unchanged_active_task_refresh_does_not_write_read_model_row(
    tmp_path,
):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-active-task-unchanged.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(
        session_factory,
        operations_assessment_interval_ms=60_000,
    )
    await service.start()
    task_id = new_id()
    observed_at = datetime(2026, 7, 18, 9, tzinfo=UTC)
    assessment_at = observed_at + timedelta(seconds=1)
    service.record_batch(
        (
            ObservationEnvelope.task_lifecycle(
                kind="task.created",
                task_id=task_id,
                source_kind="deerflow_run",
                source_id="run-active-task-unchanged",
                occurred_at=observed_at,
                source_event_id="run:run-active-task-unchanged:task:created",
            ),
            ObservationEnvelope.task_lifecycle(
                kind="task.started",
                task_id=task_id,
                source_kind="deerflow_run",
                source_id="run-active-task-unchanged",
                occurred_at=observed_at,
                source_event_id="run:run-active-task-unchanged:task:started",
            ),
        )
    )
    read_model_updates: list[str] = []

    def capture_read_model_update(
        _connection,
        _cursor,
        statement,
        _parameters,
        _context,
        _executemany,
    ) -> None:
        normalized = " ".join(statement.upper().split())
        if normalized.startswith("UPDATE ANSICH_ACTIVE_TASK_READ_MODEL"):
            read_model_updates.append(normalized)

    try:
        await service.flush_task(task_id)
        await service.assess_operations(now=assessment_at)
        event.listen(
            engine.sync_engine,
            "before_cursor_execute",
            capture_read_model_update,
        )

        await service.assess_operations(now=assessment_at)
    finally:
        event.remove(
            engine.sync_engine,
            "before_cursor_execute",
            capture_read_model_update,
        )
        await service.stop()
        await engine.dispose()

    assert read_model_updates == []


@pytest.mark.anyio
async def test_active_task_read_model_materializes_current_action_and_operations_data(
    tmp_path,
):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-active-tasks.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(session_factory, long_dwell_seconds=120)
    await service.start()
    task_id = new_id()
    step_id = new_id()
    tool_call_id = new_id()
    started_at = datetime(2026, 7, 18, 14, tzinfo=UTC)
    producer = Producer(name="active-task-test", version="1", instance_id="test")

    def tool_observation(
        kind: str,
        *,
        occurred_at: datetime,
        payload: dict[str, object],
    ) -> ObservationEnvelope:
        return ObservationEnvelope(
            kind=kind,
            occurred_at=occurred_at,
            task_id=task_id,
            step_id=step_id,
            subject_type="tool_call",
            subject_id=tool_call_id,
            producer=producer,
            source_event_id=f"tool:{tool_call_id}:{kind}",
            correlation_id="run-active-task",
            payload=payload,
        )

    started_tool = tool_observation(
        "tool.started",
        occurred_at=started_at + timedelta(seconds=3),
        payload={"call_seq": 1},
    )
    try:
        service.record_batch(
            (
                ObservationEnvelope.task_lifecycle(
                    kind="task.created",
                    task_id=task_id,
                    source_kind="deerflow_run",
                    source_id="run-active-task",
                    occurred_at=started_at,
                    source_event_id="run:run-active-task:task:created",
                    thread_id="thread-active",
                    owner_id="owner-active",
                ),
                ObservationEnvelope.task_lifecycle(
                    kind="task.started",
                    task_id=task_id,
                    source_kind="deerflow_run",
                    source_id="run-active-task",
                    occurred_at=started_at + timedelta(seconds=1),
                    source_event_id="run:run-active-task:task:started",
                    thread_id="thread-active",
                    owner_id="owner-active",
                ),
                ObservationEnvelope(
                    kind="step.started",
                    occurred_at=started_at + timedelta(seconds=2),
                    task_id=task_id,
                    step_id=step_id,
                    subject_type="step",
                    subject_id=step_id,
                    producer=producer,
                    source_event_id=f"step:{step_id}:started",
                    correlation_id="run-active-task",
                    payload={"step_seq": 1, "actor_kind": "lead_agent"},
                ),
                tool_observation(
                    "tool.issued",
                    occurred_at=started_at + timedelta(seconds=2),
                    payload={
                        "call_seq": 1,
                        "provider_call_id": "provider-tool-active",
                        "tool_name": "long_running_tool",
                        "args_hash": "a" * 64,
                        "args_preview": {},
                        "tool_schema_block_id": None,
                    },
                ),
                started_tool,
                ObservationEnvelope.task_heartbeat(
                    task_id=task_id,
                    run_id="run-active-task",
                    occurred_at=started_at + timedelta(seconds=5),
                    elapsed_ms=5_000,
                    worker_id="worker-active",
                    ownership_epoch="worker-active",
                    source_event_id="run:run-active-task:heartbeat:1",
                ),
                ObservationEnvelope.budget_configured(
                    task_id=task_id,
                    run_id="run-active-task",
                    occurred_at=started_at,
                    dimension="tool_calls_executed",
                    aggregation_scope="local",
                    warning_limit=1,
                    hard_limit=2,
                    enforcement=False,
                    source_kind="shadow",
                    requested_value=None,
                    effective_value=2,
                    source_event_id="run:run-active-task:budget:tools",
                ),
            )
        )
        await service.flush_task(task_id)
        await service.assess_operations(now=started_at + timedelta(seconds=10))
        active = await service.list_active_tasks(owner_id="owner-active")
        await service.rebuild_projections()
        rebuilt_active = await service.list_active_tasks(owner_id="owner-active")

        service.record(
            ObservationEnvelope.task_lifecycle(
                kind="task.completed",
                task_id=task_id,
                source_kind="deerflow_run",
                source_id="run-active-task",
                occurred_at=started_at + timedelta(seconds=12),
                source_event_id="run:run-active-task:task:completed",
            )
        )
        await service.flush_task(task_id)
        await service.assess_operations(now=started_at + timedelta(seconds=13))
        after_terminal = await service.list_active_tasks()
    finally:
        await service.stop()
        await engine.dispose()

    assert len(active) == 1
    assert len(rebuilt_active) == 1
    assert rebuilt_active[0].task_id == active[0].task_id
    assert rebuilt_active[0].current_tool == active[0].current_tool
    assert rebuilt_active[0].usage == active[0].usage
    item = active[0]
    assert item.task_id == task_id
    assert item.run_id == "run-active-task"
    assert item.owner_id == "owner-active"
    assert item.thread_id == "thread-active"
    assert item.control.value == "running"
    assert item.current_step is not None
    assert item.current_step.step_id == step_id
    assert item.current_tool is not None
    assert item.current_tool.tool_call_id == tool_call_id
    assert item.current_tool.status == "acting"
    assert item.dwell.duration_ms == 7_000
    assert item.dwell.evidence_obs_ids == (started_tool.obs_id,)
    assert item.heartbeat.value == "fresh"
    assert item.heartbeat.age_ms == 5_000
    assert {usage.dimension: usage.value for usage in item.usage.local} == {
        "steps": 1,
        "tool_calls_issued": 1,
        "tool_calls_executed": 1,
        "wall_time_ms": 5_000,
    }
    assert item.budget_health[0].value == "warning"
    assert after_terminal == []


@pytest.mark.anyio
async def test_active_task_filters_and_cursor_use_stable_evidence_order(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-active-task-cursor.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(session_factory)
    await service.start()
    started_at = datetime(2026, 7, 18, 15, tzinfo=UTC)
    task_ids = (new_id(), new_id())
    try:
        for index, task_id in enumerate(task_ids):
            run_id = f"run-active-cursor-{index}"
            service.record_batch(
                (
                    ObservationEnvelope.task_lifecycle(
                        kind="task.created",
                        task_id=task_id,
                        source_kind="deerflow_run",
                        source_id=run_id,
                        occurred_at=started_at + timedelta(seconds=index),
                        source_event_id=f"run:{run_id}:task:created",
                        owner_id="owner-cursor",
                    ),
                    ObservationEnvelope.task_lifecycle(
                        kind="task.started",
                        task_id=task_id,
                        source_kind="deerflow_run",
                        source_id=run_id,
                        occurred_at=started_at + timedelta(seconds=index),
                        source_event_id=f"run:{run_id}:task:started",
                        owner_id="owner-cursor",
                    ),
                    ObservationEnvelope.task_heartbeat(
                        task_id=task_id,
                        run_id=run_id,
                        occurred_at=started_at + timedelta(seconds=5 + index),
                        elapsed_ms=(5 + index) * 1_000,
                        worker_id="worker-cursor",
                        ownership_epoch="worker-cursor",
                        source_event_id=f"run:{run_id}:heartbeat:1",
                    ),
                )
            )
            await service.flush_task(task_id)
        await service.assess_operations(now=started_at + timedelta(seconds=10))

        first = await service.list_active_tasks(
            owner_id="owner-cursor",
            heartbeat_status="fresh",
            budget_status="unknown",
            min_duration_ms=5_000,
            limit=1,
        )
        second = await service.list_active_tasks(
            limit=1,
            cursor=(first[0].last_evidence_at, first[0].task_id),
        )
    finally:
        await service.stop()
        await engine.dispose()

    assert len(first) == 1
    assert len(second) == 1
    assert first[0].task_id != second[0].task_id


def test_phase5_operations_models_compile_with_postgresql_semantics():
    dialect = postgresql.dialect()
    statements = {
        model.__tablename__: str(CreateTable(model.__table__).compile(dialect=dialect))
        for model in (
            AnsichTaskHeartbeatRow,
            AnsichTaskBudgetRow,
            AnsichTaskUsageRow,
            AnsichUsageContributionRow,
            AnsichActiveTaskReadModelRow,
        )
    }

    assert "TIMESTAMP WITH TIME ZONE" in statements["ansich_task_heartbeats"]
    assert "BOOLEAN NOT NULL" in statements["ansich_task_budgets"]
    assert "PRIMARY KEY (task_id, dimension, aggregation_scope)" in statements["ansich_task_usage"]
    assert "JSON NOT NULL" in statements["ansich_active_task_read_model"]


def test_phase5_operations_migration_upgrades_sqlite(tmp_path):
    backend_root = Path(__file__).resolve().parents[2]
    config = AlembicConfig(str(backend_root / "packages" / "harness" / "deerflow" / "persistence" / "migrations" / "alembic.ini"))
    database_path = tmp_path / "ansich-phase5-migration.db"
    config.set_main_option(
        "sqlalchemy.url",
        f"sqlite+aiosqlite:///{database_path}",
    )
    config.config_file_name = None

    alembic_command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{database_path}")
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        with engine.connect() as connection:
            revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
    finally:
        engine.dispose()

    assert {
        "ansich_task_heartbeats",
        "ansich_task_budgets",
        "ansich_task_usage",
        "ansich_usage_contributions",
        "ansich_active_task_read_model",
    } <= tables
    assert revision == "0017_ansich_alerts"
