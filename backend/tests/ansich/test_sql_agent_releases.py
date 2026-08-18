from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from ansich import AnsichService, ObservationEnvelope, Producer, new_id
from ansich.release import AgentRuntimeDescriptor, RuntimeBuildDescriptor, build_agent_release
from sqlalchemy import create_engine, event, func, inspect, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateTable

from deerflow.ansich import create_sql_ansich_service
from deerflow.ansich.persistence.models import (
    AnsichAgentReleaseComponentRow,
    AnsichAgentReleaseRow,
    AnsichTaskAgentReleaseRow,
)
from deerflow.persistence.base import Base


def _release(*, effective_model: str = "provider/model-v1"):
    return build_agent_release(
        AgentRuntimeDescriptor(
            namespace="deerflow",
            agent_name="lead-agent",
            requested_model="requested-alias",
            effective_model=effective_model,
            model_provider="provider",
            model_behavior_parameters={"model": effective_model},
            rendered_base_prompt="You are DeerFlow.",
            prompt_template_id="lead-v1",
            effective_policies={"non_interactive": False},
            runtime_build=RuntimeBuildDescriptor(package_version="2.1.0"),
        )
    )


def _resolved_observation(task_id: str, run_id: str, *, effective_model: str = "provider/model-v1"):
    return ObservationEnvelope.agent_release_resolved(
        task_id=task_id,
        run_id=run_id,
        occurred_at=datetime.now(UTC),
        release=_release(effective_model=effective_model),
        source_event_id=f"run:{run_id}:agent-release:resolved",
    )


def test_phase7_release_models_compile_with_postgresql_constraints() -> None:
    dialect = postgresql.dialect()
    ddl = {
        model.__tablename__: str(CreateTable(model.__table__).compile(dialect=dialect))
        for model in (
            AnsichAgentReleaseRow,
            AnsichAgentReleaseComponentRow,
            AnsichTaskAgentReleaseRow,
        )
    }

    assert "UNIQUE (namespace, agent_name, release_hash)" in ddl["ansich_agent_releases"]
    assert "PRIMARY KEY (release_id, component_kind)" in ddl["ansich_agent_release_components"]
    assert "PRIMARY KEY (task_id)" in ddl["ansich_task_agent_releases"]
    assert "REFERENCES ansich_agent_releases" in ddl["ansich_task_agent_releases"]
    assert "ck_ansich_agent_release_component_kind" in ddl["ansich_agent_release_components"]
    assert "ck_ansich_task_agent_release_role" in ddl["ansich_task_agent_releases"]
    assert {
        "ix_ansich_agent_releases_model_hash",
        "ix_ansich_agent_releases_prompt_hash",
        "ix_ansich_agent_releases_tool_hash",
        "ix_ansich_agent_releases_policy_hash",
        "ix_ansich_agent_releases_runtime_build",
    } <= {index.name for index in AnsichAgentReleaseRow.__table__.indexes}


def test_phase7_release_migration_upgrades_sqlite(tmp_path) -> None:
    backend_root = Path(__file__).resolve().parents[2]
    config = AlembicConfig(str(backend_root / "packages" / "harness" / "deerflow" / "persistence" / "migrations" / "alembic.ini"))
    database_path = tmp_path / "ansich-phase7-migration.db"
    config.set_main_option("script_location", str(backend_root / "packages" / "harness" / "deerflow" / "persistence" / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database_path}")
    # Do not let Alembic's test config disable loggers already imported by
    # later integration tests in this process.
    config.config_file_name = None

    alembic_command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{database_path}")
    try:
        database_inspector = inspect(engine)
        table_names = set(database_inspector.get_table_names())
        llm_attempt_columns = {column["name"] for column in database_inspector.get_columns("ansich_llm_attempts")}
        with engine.connect() as connection:
            revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
    finally:
        engine.dispose()

    assert revision == "0025_ansich_assessor_watermarks"
    assert {
        "ansich_agent_releases",
        "ansich_agent_release_components",
        "ansich_task_agent_releases",
    } <= table_names
    assert "provider_model" in llm_attempt_columns


@pytest.mark.anyio
async def test_sql_release_projection_deduplicates_release_and_binds_each_task(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-release.db'}")

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service: AnsichService = create_sql_ansich_service(session_factory)
    await service.start()
    task_ids = (new_id(), new_id())

    try:
        for index, task_id in enumerate(task_ids):
            run_id = f"release-run-{index}"
            service.record_batch(
                (
                    ObservationEnvelope.task_lifecycle(
                        kind="task.created",
                        task_id=task_id,
                        source_kind="deerflow_run",
                        source_id=run_id,
                        occurred_at=datetime.now(UTC),
                        source_event_id=f"run:{run_id}:task:created",
                    ),
                    _resolved_observation(task_id, run_id),
                )
            )
            await service.flush_task(task_id)

        first = await service.get_task_agent_release(task_ids[0])
        releases = await service.list_agent_releases(limit=20)
        async with session_factory() as session:
            release_count = await session.scalar(select(func.count()).select_from(AnsichAgentReleaseRow))
            binding_count = await session.scalar(select(func.count()).select_from(AnsichTaskAgentReleaseRow))
    finally:
        await service.stop()
        await engine.dispose()

    assert release_count == 1
    assert binding_count == 2
    assert first is not None
    assert first.relation_role == "executed_by"
    assert first.release.manifest.model.effective == "provider/model-v1"
    assert len(releases) == 1
    assert releases[0].task_count == 2
    assert releases[0].quality_status == "unassessed"


@pytest.mark.anyio
async def test_task_starting_release_is_immutable_when_a_later_resolution_disagrees(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-release-immutable.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(session_factory, projector_max_attempts=1)
    await service.start()
    task_id = new_id()
    run_id = "immutable-release-run"

    try:
        service.record_batch(
            (
                ObservationEnvelope.task_lifecycle(
                    kind="task.created",
                    task_id=task_id,
                    source_kind="deerflow_run",
                    source_id=run_id,
                    occurred_at=datetime.now(UTC),
                    source_event_id=f"run:{run_id}:task:created",
                ),
                _resolved_observation(task_id, run_id),
            )
        )
        await service.flush_task(task_id)
        service.record(
            ObservationEnvelope.agent_release_resolved(
                task_id=task_id,
                run_id=run_id,
                occurred_at=datetime.now(UTC),
                release=_release(effective_model="provider/model-v2"),
                source_event_id=f"run:{run_id}:agent-release:conflicting",
            )
        )
        await service.flush_task(task_id)
        bound = await service.get_task_agent_release(task_id)
        health = service.get_health()
    finally:
        await service.stop()
        await engine.dispose()

    assert bound is not None
    assert bound.release.manifest.model.effective == "provider/model-v1"
    assert health.failed_jobs == 1


@pytest.mark.anyio
async def test_provider_reported_model_mismatch_creates_drift_belief_without_mutating_release(
    tmp_path,
):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-release-drift.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(session_factory)
    await service.start()
    task_id, step_id, attempt_id = new_id(), new_id(), new_id()
    run_id = "release-drift-run"
    observed_at = datetime.now(UTC)
    producer = Producer(name="release-drift-test", version="1", instance_id="test")
    release = _release()

    try:
        service.record_batch(
            (
                ObservationEnvelope.task_lifecycle(
                    kind="task.created",
                    task_id=task_id,
                    source_kind="deerflow_run",
                    source_id=run_id,
                    occurred_at=observed_at,
                    source_event_id=f"run:{run_id}:task:created",
                ),
                ObservationEnvelope.agent_release_resolved(
                    task_id=task_id,
                    run_id=run_id,
                    occurred_at=observed_at,
                    release=release,
                    source_event_id=f"run:{run_id}:agent-release:resolved",
                ),
                ObservationEnvelope(
                    kind="step.started",
                    occurred_at=observed_at,
                    task_id=task_id,
                    step_id=step_id,
                    subject_type="step",
                    subject_id=step_id,
                    producer=producer,
                    source_event_id=f"step:{step_id}:started",
                    correlation_id=task_id,
                    payload={"step_seq": 1, "actor_kind": "lead_agent"},
                ),
                ObservationEnvelope(
                    kind="llm.requested",
                    occurred_at=observed_at,
                    task_id=task_id,
                    step_id=step_id,
                    subject_type="llm_attempt",
                    subject_id=attempt_id,
                    producer=producer,
                    source_event_id=f"attempt:{attempt_id}:requested",
                    correlation_id=task_id,
                    payload={
                        "attempt_no": 1,
                        "actor_kind": "lead_agent",
                        "configured_model": "provider/model-v1",
                    },
                ),
                ObservationEnvelope(
                    kind="llm.responded",
                    occurred_at=observed_at,
                    task_id=task_id,
                    step_id=step_id,
                    subject_type="llm_attempt",
                    subject_id=attempt_id,
                    producer=producer,
                    source_event_id=f"attempt:{attempt_id}:responded",
                    correlation_id=task_id,
                    payload={
                        "attempt_no": 1,
                        "latency_ms": 12,
                        "usage": {},
                        "response_metadata": {"model_name": "provider/model-v2"},
                    },
                ),
            )
        )
        await service.flush_task(task_id)
        await service.assess_operations(now=observed_at)
        drift = await service.get_current_belief(task_id, "configuration_drift")
        alerts = await service.list_alerts(
            alert_type="configuration_drift",
            task_id=task_id,
        )
        binding = await service.get_task_agent_release(task_id)
    finally:
        await service.stop()
        await engine.dispose()

    assert drift is not None
    assert drift.value["value"] == "mismatch"
    assert len(alerts) == 1
    assert alerts[0].alert_type == "configuration_drift"
    assert binding is not None
    assert binding.release.summary.release_hash == release.fingerprint.release_hash
