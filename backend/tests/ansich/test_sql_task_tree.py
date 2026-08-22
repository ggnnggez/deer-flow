from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from ansich import ObservationEnvelope, Producer, new_id
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateTable
from support.ansich_settle import only_test_driven_assessments

from deerflow.ansich import create_sql_ansich_service
from deerflow.ansich.persistence.models import (
    AnsichRelationRow,
    AnsichScopeRow,
    AnsichStepRow,
    AnsichTaskAncestryRow,
    AnsichTaskSpawnRow,
    AnsichToolCallRow,
)
from deerflow.persistence.base import Base


def _task_created(
    task_id: str,
    source_id: str,
    observed_at: datetime,
    *,
    source_kind: str = "deerflow_run",
    attributes: dict[str, object] | None = None,
) -> ObservationEnvelope:
    return ObservationEnvelope.task_lifecycle(
        kind="task.created",
        task_id=task_id,
        source_kind=source_kind,
        source_id=source_id,
        occurred_at=observed_at,
        source_event_id=f"{source_kind}:{source_id}:task:created:{new_id()}",
        attributes=attributes,
    )


def _step_started(task_id: str, step_id: str, observed_at: datetime) -> ObservationEnvelope:
    return ObservationEnvelope(
        kind="step.started",
        occurred_at=observed_at,
        task_id=task_id,
        step_id=step_id,
        subject_type="step",
        subject_id=step_id,
        producer=Producer(name="task-tree-test", version="1", instance_id="test"),
        source_event_id=f"step:{step_id}:started",
        correlation_id=task_id,
        payload={"step_seq": 1, "actor_kind": "subagent"},
    )


def _tool_issued(
    task_id: str,
    step_id: str,
    tool_call_id: str,
    observed_at: datetime,
) -> ObservationEnvelope:
    return ObservationEnvelope(
        kind="tool.issued",
        occurred_at=observed_at,
        task_id=task_id,
        step_id=step_id,
        subject_type="tool_call",
        subject_id=tool_call_id,
        producer=Producer(name="task-tree-test", version="1", instance_id="test"),
        source_event_id=f"tool:{tool_call_id}:issued",
        correlation_id=task_id,
        payload={
            "call_seq": 1,
            "provider_call_id": f"provider-{tool_call_id}",
            "tool_name": "task",
            "args_hash": "a" * 64,
            "args_preview": {},
            "tool_schema_block_id": None,
        },
    )


def test_phase8_task_tree_models_compile_with_postgresql_constraints() -> None:
    dialect = postgresql.dialect()
    spawn_ddl = str(CreateTable(AnsichTaskSpawnRow.__table__).compile(dialect=dialect))
    ancestry_ddl = str(CreateTable(AnsichTaskAncestryRow.__table__).compile(dialect=dialect))

    assert "PRIMARY KEY (child_task_id)" in spawn_ddl
    assert "FOREIGN KEY(spawning_step_id, parent_task_id)" in spawn_ddl
    assert "FOREIGN KEY(spawning_tool_call_id, spawning_step_id, parent_task_id)" in spawn_ddl
    assert "PRIMARY KEY (ancestor_task_id, descendant_task_id)" in ancestry_ddl
    assert "ck_ansich_task_ancestry_self_free" in ancestry_ddl
    assert "ck_ansich_task_ancestry_positive_depth" in ancestry_ddl
    assert {"entity_id", "task_id"} <= {column.name for column in next(constraint for constraint in AnsichStepRow.__table__.constraints if getattr(constraint, "name", None) == "uq_ansich_step_entity_task").columns}


def test_phase8_task_tree_migration_upgrades_sqlite(tmp_path) -> None:
    backend_root = Path(__file__).resolve().parents[2]
    config = AlembicConfig(str(backend_root / "packages" / "harness" / "deerflow" / "persistence" / "migrations" / "alembic.ini"))
    database_path = tmp_path / "ansich-phase8-migration.db"
    config.set_main_option(
        "script_location",
        str(backend_root / "packages" / "harness" / "deerflow" / "persistence" / "migrations"),
    )
    config.set_main_option(
        "sqlalchemy.url",
        f"sqlite+aiosqlite:///{database_path}",
    )
    config.config_file_name = None

    alembic_command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{database_path}")
    try:
        database_inspector = inspect(engine)
        table_names = set(database_inspector.get_table_names())
        contribution_columns = {column["name"] for column in database_inspector.get_columns("ansich_usage_contributions")}
        with engine.connect() as connection:
            revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
    finally:
        engine.dispose()

    assert revision == "0027_ansich_lease_generation"
    assert {"ansich_task_spawns", "ansich_task_ancestry"} <= table_names
    assert "aggregate_task_id" in contribution_columns
    assert "task_id" not in contribution_columns
    assert {"entity_id", "step_id", "task_id"} <= {column.name for column in next(constraint for constraint in AnsichToolCallRow.__table__.constraints if getattr(constraint, "name", None) == "uq_ansich_tool_call_entity_step_task").columns}


def test_phase8_migration_preserves_local_usage_and_backfills_inclusive_summary(
    tmp_path,
) -> None:
    backend_root = Path(__file__).resolve().parents[2]
    config = AlembicConfig(str(backend_root / "packages" / "harness" / "deerflow" / "persistence" / "migrations" / "alembic.ini"))
    database_path = tmp_path / "ansich-phase8-existing.db"
    config.set_main_option(
        "script_location",
        str(backend_root / "packages" / "harness" / "deerflow" / "persistence" / "migrations"),
    )
    config.set_main_option(
        "sqlalchemy.url",
        f"sqlite+aiosqlite:///{database_path}",
    )
    config.config_file_name = None
    alembic_command.upgrade(config, "0018_ansich_agent_releases")

    task_id = "00000000-0000-4000-8000-000000000801"
    obs_id = "00000000-0000-4000-8000-000000000802"
    timestamp = "2026-07-20 09:00:00+00:00"
    engine = create_engine(f"sqlite:///{database_path}")
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO ansich_observations (
                        obs_id, schema_version, kind, occurred_at, recorded_at,
                        task_id, step_id, subject_type, subject_id,
                        fidelity_class, producer_name, producer_version,
                        producer_instance_id, producer_seq, source_event_id,
                        correlation_id, causation_obs_id, payload_json,
                        payload_ref_id
                    ) VALUES (
                        :obs_id, 1, 'step.started', :timestamp, :timestamp,
                        :task_id, NULL, 'task', :task_id, 'hard', 'migration-test',
                        '1', 'test', 1, 'migration:usage', :task_id, NULL,
                        '{}', NULL
                    )
                    """
                ),
                {"obs_id": obs_id, "task_id": task_id, "timestamp": timestamp},
            )
            connection.execute(
                text("INSERT INTO ansich_entities (entity_id, entity_type, discovered_obs_id) VALUES (:task_id, 'task', :obs_id)"),
                {"task_id": task_id, "obs_id": obs_id},
            )
            connection.execute(
                text("INSERT INTO ansich_tasks (entity_id, source_kind, source_id, trigger_obs_id) VALUES (:task_id, 'deerflow_run', 'migration-run', :obs_id)"),
                {"task_id": task_id, "obs_id": obs_id},
            )
            connection.execute(
                text("INSERT INTO ansich_usage_contributions (task_id, source_task_id, dimension, source_obs_id, delta, as_of) VALUES (:task_id, :task_id, 'steps', :obs_id, 3, :timestamp)"),
                {"task_id": task_id, "obs_id": obs_id, "timestamp": timestamp},
            )
            connection.execute(
                text("INSERT INTO ansich_task_usage (task_id, dimension, aggregation_scope, value, as_of, complete_through_ingest_seq, updated_at) VALUES (:task_id, 'steps', 'local', 3, :timestamp, 1, :timestamp)"),
                {"task_id": task_id, "timestamp": timestamp},
            )
    finally:
        engine.dispose()

    alembic_command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{database_path}")
    try:
        with engine.connect() as connection:
            contribution = connection.execute(text("SELECT aggregate_task_id, source_task_id, delta FROM ansich_usage_contributions")).one()
            usage_rows = connection.execute(
                text("SELECT aggregation_scope, value FROM ansich_task_usage WHERE task_id = :task_id AND dimension = 'steps' ORDER BY aggregation_scope"),
                {"task_id": task_id},
            ).all()
    finally:
        engine.dispose()

    assert contribution == (task_id, task_id, 3)
    assert usage_rows == [("inclusive", 3), ("local", 3)]


@pytest.mark.anyio
async def test_child_task_created_projects_typed_spawn_and_direct_ancestry(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'task-tree.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(session_factory)
    await service.start()
    parent_task_id = new_id()
    child_task_id = new_id()
    step_id = new_id()
    tool_call_id = new_id()
    observed_at = datetime(2026, 7, 20, 10, 0, tzinfo=UTC)
    producer = Producer(name="task-tree-test", version="1", instance_id="test")

    try:
        service.record_batch(
            (
                ObservationEnvelope.task_lifecycle(
                    kind="task.created",
                    task_id=parent_task_id,
                    source_kind="deerflow_run",
                    source_id="parent-run",
                    occurred_at=observed_at,
                    source_event_id="run:parent-run:task:created",
                ),
                ObservationEnvelope(
                    kind="step.started",
                    occurred_at=observed_at,
                    task_id=parent_task_id,
                    step_id=step_id,
                    subject_type="step",
                    subject_id=step_id,
                    producer=producer,
                    source_event_id=f"step:{step_id}:started",
                    correlation_id=parent_task_id,
                    payload={"step_seq": 1, "actor_kind": "lead_agent"},
                ),
                ObservationEnvelope(
                    kind="tool.issued",
                    occurred_at=observed_at,
                    task_id=parent_task_id,
                    step_id=step_id,
                    subject_type="tool_call",
                    subject_id=tool_call_id,
                    producer=producer,
                    source_event_id=f"tool:{tool_call_id}:issued",
                    correlation_id=parent_task_id,
                    payload={
                        "call_seq": 1,
                        "provider_call_id": "provider-task-call",
                        "tool_name": "task",
                        "args_hash": "a" * 64,
                        "args_preview": {},
                        "tool_schema_block_id": None,
                    },
                ),
            )
        )
        await service.flush_task(parent_task_id)
        child_created = ObservationEnvelope.task_lifecycle(
            kind="task.created",
            task_id=child_task_id,
            source_kind="deerflow_subagent",
            source_id="provider-task-call",
            occurred_at=observed_at,
            source_event_id="deerflow_subagent:provider-task-call:task:created",
            thread_id="thread-1",
            owner_id="operator-1",
            trigger_kind="subagent",
            attributes={
                "parent_task_id": parent_task_id,
                "spawning_step_id": step_id,
                "spawning_tool_call_id": tool_call_id,
                "subagent_name": "researcher",
                "scope_inheritance_source": "parent_task",
                "workspace_ref": "/workspace/thread-1",
                "sandbox_ref": "sandbox-thread-1",
            },
        )
        service.record(child_created)
        await service.flush_task(child_task_id)

        children = await service.list_task_children(parent_task_id)
        async with session_factory() as session:
            spawn = await session.get(AnsichTaskSpawnRow, child_task_id)
            ancestry = await session.get(
                AnsichTaskAncestryRow,
                (parent_task_id, child_task_id),
            )
            scopes = set(
                (
                    await session.execute(
                        select(
                            AnsichScopeRow.scope_kind,
                            AnsichScopeRow.display_label,
                            AnsichRelationRow.relation_role,
                        )
                        .join(
                            AnsichRelationRow,
                            AnsichRelationRow.object_id == AnsichScopeRow.entity_id,
                        )
                        .where(
                            AnsichRelationRow.subject_id == child_task_id,
                            AnsichRelationRow.predicate == "within_scope",
                        )
                    )
                ).all()
            )
    finally:
        await service.stop()
        await engine.dispose()

    assert spawn is not None
    assert ancestry is not None
    assert ancestry.depth == 1
    assert len(children) == 1
    assert children[0].parent_task_id == parent_task_id
    assert children[0].child_task_id == child_task_id
    assert children[0].spawning_step_id == step_id
    assert children[0].spawning_tool_call_id == tool_call_id
    assert children[0].established_obs_id == child_created.obs_id
    assert children[0].subagent_name == "researcher"
    assert scopes == {
        ("owner", "operator-1", "owner"),
        ("thread", "thread-1", "conversation"),
        ("workspace", "thread-1", "execution_workspace"),
        ("sandbox", "sandbox-thread-1", "sandbox_boundary"),
    }


@pytest.mark.anyio
async def test_usage_rolls_up_two_levels_and_backfills_a_late_spawn_without_double_counting(
    tmp_path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'usage-tree.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(session_factory)
    only_test_driven_assessments(service)
    await service.start()
    root_id, child_id, grandchild_id = new_id(), new_id(), new_id()
    root_step, child_step, grandchild_step = new_id(), new_id(), new_id()
    root_tool, child_tool = new_id(), new_id()
    observed_at = datetime(2026, 7, 20, 11, 0, tzinfo=UTC)

    try:
        # The child already has local usage when its typed spawn evidence
        # arrives. Projection must backfill it into the root exactly once.
        service.record_batch(
            (
                _task_created(root_id, "root", observed_at),
                _step_started(root_id, root_step, observed_at),
                _tool_issued(root_id, root_step, root_tool, observed_at),
                _task_created(child_id, "child-before-relation", observed_at),
                _step_started(child_id, child_step, observed_at),
                _tool_issued(child_id, child_step, child_tool, observed_at),
            )
        )
        await service.flush_task(root_id)
        await service.flush_task(child_id)
        service.record(
            _task_created(
                child_id,
                "child-executor",
                observed_at,
                source_kind="deerflow_subagent",
                attributes={
                    "parent_task_id": root_id,
                    "spawning_step_id": root_step,
                    "spawning_tool_call_id": root_tool,
                    "subagent_name": "researcher",
                },
            )
        )
        await service.flush_task(child_id)

        service.record(
            _task_created(
                grandchild_id,
                "grandchild-executor",
                observed_at,
                source_kind="deerflow_subagent",
                attributes={
                    "parent_task_id": child_id,
                    "spawning_step_id": child_step,
                    "spawning_tool_call_id": child_tool,
                    "subagent_name": "writer",
                },
            )
        )
        service.record(_step_started(grandchild_id, grandchild_step, observed_at))
        await service.flush_task(grandchild_id)
        for task_id, source_kind, source_id in (
            (root_id, "deerflow_run", "root"),
            (child_id, "deerflow_subagent", "child-executor"),
            (grandchild_id, "deerflow_subagent", "grandchild-executor"),
        ):
            service.record(
                ObservationEnvelope.task_lifecycle(
                    kind="task.started",
                    task_id=task_id,
                    source_kind=source_kind,
                    source_id=source_id,
                    occurred_at=observed_at.replace(second=1),
                    source_event_id=f"{source_kind}:{source_id}:task:started",
                )
            )
            await service.flush_task(task_id)
        await service.assess_operations(now=observed_at)

        root_usage = await service.get_task_usage(root_id)
        root_breakdown = await service.get_task_usage_breakdown(
            root_id,
            scope="inclusive",
        )
        child_usage = await service.get_task_usage(child_id)
        grandchild_usage = await service.get_task_usage(grandchild_id)
        shallow_tree = await service.get_task_tree(
            root_id,
            direction="descendants",
            depth=1,
        )
        full_tree = await service.get_task_tree(
            root_id,
            direction="both",
            depth=2,
        )
        root_tasks = await service.list_tasks(root_only=True)
        active_tasks = await service.list_active_tasks()
        await service.rebuild_until_settled()
        rebuilt = await service.get_task_usage(root_id)
    finally:
        await service.stop()
        await engine.dispose()

    assert root_usage == rebuilt
    assert root_usage.inclusive_status == "available"
    assert {item.dimension: item.value for item in root_usage.local} == {
        "steps": 1,
        "tool_calls_issued": 1,
    }
    assert {item.dimension: item.value for item in root_usage.inclusive} == {
        "steps": 3,
        "tool_calls_issued": 2,
    }
    assert {source.source_task_id for source in root_breakdown.sources} == {
        root_id,
        child_id,
        grandchild_id,
    }
    assert sum(next(item.value for item in source.values if item.dimension == "steps") for source in root_breakdown.sources) == 3
    assert {item.dimension: item.value for item in child_usage.inclusive} == {
        "steps": 2,
        "tool_calls_issued": 1,
    }
    assert {item.dimension: item.value for item in grandchild_usage.inclusive} == {
        "steps": 1,
    }
    assert {node.task.task_id for node in shallow_tree.nodes} == {root_id, child_id}
    shallow_nodes = {node.task.task_id: node for node in shallow_tree.nodes}
    assert shallow_nodes[root_id].current_step is not None
    assert shallow_nodes[root_id].current_step.step_id == root_step
    assert shallow_nodes[child_id].current_step is not None
    assert shallow_nodes[child_id].current_step.step_id == child_step
    assert shallow_tree.truncated is True
    assert {node.task.task_id for node in full_tree.nodes} == {
        root_id,
        child_id,
        grandchild_id,
    }
    assert full_tree.truncated is False
    assert [edge.child_task_id for edge in full_tree.edges] == [
        child_id,
        grandchild_id,
    ]
    assert root_id in {task.task_id for task in root_tasks}
    assert child_id not in {task.task_id for task in root_tasks}
    assert grandchild_id not in {task.task_id for task in root_tasks}
    active_by_id = {task.task_id: task for task in active_tasks}
    assert active_by_id[root_id].active_child_count == 1
    assert active_by_id[child_id].active_child_count == 1
    assert active_by_id[grandchild_id].active_child_count == 0
    assert {item.dimension: item.value for item in active_by_id[root_id].usage.inclusive}["steps"] == 3


@pytest.mark.anyio
async def test_task_tree_rejects_a_second_parent_and_marks_the_child_degraded(
    tmp_path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'unique-parent.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(session_factory, projector_max_attempts=1)
    await service.start()
    first_parent, second_parent, child_id = new_id(), new_id(), new_id()
    first_step, second_step = new_id(), new_id()
    first_tool, second_tool = new_id(), new_id()
    observed_at = datetime(2026, 7, 20, 13, 0, tzinfo=UTC)

    try:
        service.record_batch(
            (
                _task_created(first_parent, "first-parent", observed_at),
                _step_started(first_parent, first_step, observed_at),
                _tool_issued(first_parent, first_step, first_tool, observed_at),
                _task_created(second_parent, "second-parent", observed_at),
                _step_started(second_parent, second_step, observed_at),
                _tool_issued(second_parent, second_step, second_tool, observed_at),
                _task_created(child_id, "child", observed_at),
            )
        )
        for task_id in (first_parent, second_parent, child_id):
            await service.flush_task(task_id)
        service.record(
            _task_created(
                child_id,
                "child-first-spawn",
                observed_at,
                source_kind="deerflow_subagent",
                attributes={
                    "parent_task_id": first_parent,
                    "spawning_step_id": first_step,
                    "spawning_tool_call_id": first_tool,
                },
            )
        )
        await service.flush_task(child_id)
        service.record(
            _task_created(
                child_id,
                "child-second-spawn",
                observed_at,
                source_kind="deerflow_subagent",
                attributes={
                    "parent_task_id": second_parent,
                    "spawning_step_id": second_step,
                    "spawning_tool_call_id": second_tool,
                },
            )
        )
        await service.flush_task(child_id)

        first_children = await service.list_task_children(first_parent)
        second_children = await service.list_task_children(second_parent)
        child = await service.get_task(child_id)
        health = service.get_health()
    finally:
        await service.stop()
        await engine.dispose()

    assert [item.child_task_id for item in first_children] == [child_id]
    assert second_children == []
    assert child is not None
    assert child.observability_status == "degraded"
    assert health.failed_jobs >= 1


@pytest.mark.anyio
async def test_task_tree_rejects_a_cycle_and_preserves_the_existing_tree(
    tmp_path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'cycle.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(session_factory, projector_max_attempts=1)
    await service.start()
    root_id, child_id = new_id(), new_id()
    root_step, child_step = new_id(), new_id()
    root_tool, child_tool = new_id(), new_id()
    observed_at = datetime(2026, 7, 20, 14, 0, tzinfo=UTC)

    try:
        service.record_batch(
            (
                _task_created(root_id, "root", observed_at),
                _step_started(root_id, root_step, observed_at),
                _tool_issued(root_id, root_step, root_tool, observed_at),
                _task_created(child_id, "child", observed_at),
                _step_started(child_id, child_step, observed_at),
                _tool_issued(child_id, child_step, child_tool, observed_at),
            )
        )
        await service.flush_task(root_id)
        await service.flush_task(child_id)
        service.record(
            _task_created(
                child_id,
                "child-spawn",
                observed_at,
                source_kind="deerflow_subagent",
                attributes={
                    "parent_task_id": root_id,
                    "spawning_step_id": root_step,
                    "spawning_tool_call_id": root_tool,
                },
            )
        )
        await service.flush_task(child_id)
        service.record(
            _task_created(
                root_id,
                "cycle-spawn",
                observed_at,
                source_kind="deerflow_subagent",
                attributes={
                    "parent_task_id": child_id,
                    "spawning_step_id": child_step,
                    "spawning_tool_call_id": child_tool,
                },
            )
        )
        await service.flush_task(root_id)

        root_children = await service.list_task_children(root_id)
        child_children = await service.list_task_children(child_id)
        root = await service.get_task(root_id)
    finally:
        await service.stop()
        await engine.dispose()

    assert [item.child_task_id for item in root_children] == [child_id]
    assert child_children == []
    assert root is not None
    assert root.observability_status == "degraded"


@pytest.mark.anyio
async def test_inclusive_wall_time_uses_each_running_descendants_latest_heartbeat(
    tmp_path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'inclusive-heartbeat.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(
        session_factory,
        operations_assessment_interval_ms=60_000,
    )
    only_test_driven_assessments(service)
    await service.start()
    root_id, child_id = new_id(), new_id()
    root_step, root_tool = new_id(), new_id()
    observed_at = datetime(2026, 7, 20, 15, 0, tzinfo=UTC)

    try:
        service.record_batch(
            (
                _task_created(root_id, "root", observed_at),
                ObservationEnvelope.task_lifecycle(
                    kind="task.started",
                    task_id=root_id,
                    source_kind="deerflow_run",
                    source_id="root",
                    occurred_at=observed_at,
                    source_event_id="root:task:started",
                ),
                _step_started(root_id, root_step, observed_at),
                _tool_issued(root_id, root_step, root_tool, observed_at),
                ObservationEnvelope.budget_configured(
                    task_id=root_id,
                    run_id="root",
                    occurred_at=observed_at,
                    dimension="wall_time_ms",
                    aggregation_scope="inclusive",
                    warning_limit=1_000,
                    hard_limit=1_500,
                    enforcement=False,
                    source_kind="shadow",
                    requested_value=1_500,
                    effective_value=1_500,
                    source_event_id="root:inclusive-wall-time-budget",
                ),
            )
        )
        await service.flush_task(root_id)
        service.record(
            _task_created(
                child_id,
                "child",
                observed_at,
                source_kind="deerflow_subagent",
                attributes={
                    "parent_task_id": root_id,
                    "spawning_step_id": root_step,
                    "spawning_tool_call_id": root_tool,
                },
            )
        )
        await service.flush_task(child_id)
        service.record_batch(
            (
                ObservationEnvelope.task_heartbeat(
                    task_id=child_id,
                    run_id="child",
                    occurred_at=observed_at.replace(second=1),
                    elapsed_ms=1_000,
                    worker_id="child-worker",
                    ownership_epoch="child-epoch",
                    source_event_id="child:heartbeat:1",
                ),
                ObservationEnvelope.task_heartbeat(
                    task_id=child_id,
                    run_id="child",
                    occurred_at=observed_at.replace(second=2),
                    elapsed_ms=2_000,
                    worker_id="child-worker",
                    ownership_epoch="child-epoch",
                    source_event_id="child:heartbeat:2",
                    producer_seq=2,
                ),
            )
        )
        await service.flush_task(child_id)
        await service.assess_operations(now=observed_at.replace(second=3))

        usage = await service.get_task_usage(root_id)
        health = await service.get_task_budget_health(root_id)
    finally:
        await service.stop()
        await engine.dispose()

    assert {item.dimension: item.value for item in usage.inclusive}["wall_time_ms"] == 2_000
    wall_time_health = next(item for item in health if item.dimension == "wall_time_ms" and item.aggregation_scope == "inclusive")
    assert wall_time_health.value == "exceeded"
    assert wall_time_health.usage_value == 2_000
