from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import anyio
import pytest
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from ansich import (
    AuthorizationPermission,
    AuthorizationSnapshot,
    ObservationEnvelope,
    Producer,
    ScopeDescriptor,
    ToolEffect,
    new_id,
)
from sqlalchemy import create_engine, event, func, inspect, select, text, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import Pool
from sqlalchemy.schema import CreateTable
from support.ansich_settle import only_test_driven_assessments

from deerflow.ansich import create_sql_ansich_service
from deerflow.ansich.persistence import sql as sql_module
from deerflow.ansich.persistence.models import (
    AnsichAssessorErrorRow,
    AnsichAssessorJobRow,
    AnsichAssessorWatermarkRow,
    AnsichAuthorizationPermissionRow,
    AnsichAuthorizationSnapshotRow,
    AnsichBeliefAssertionRow,
    AnsichCurrentBeliefRow,
    AnsichEntityRow,
    AnsichObservationRow,
    AnsichProjectionJobRow,
    AnsichRelationRow,
    AnsichScopeConclusionRow,
    AnsichScopeRow,
    AnsichTaskSummaryRow,
    AnsichToolCallAuthorizationRow,
    AnsichToolEffectRow,
)
from deerflow.ansich.persistence.sql import SCOPE_SAFETY_ASSESSOR, SqlAnsichBackend
from deerflow.persistence.base import Base


def test_phase9_safety_models_compile_with_postgresql_constraints_and_indexes() -> None:
    dialect = postgresql.dialect()
    ddl = {
        model.__tablename__: str(CreateTable(model.__table__).compile(dialect=dialect))
        for model in (
            AnsichAuthorizationSnapshotRow,
            AnsichAuthorizationPermissionRow,
            AnsichToolCallAuthorizationRow,
            AnsichToolEffectRow,
            AnsichScopeConclusionRow,
        )
    }

    assert "FOREIGN KEY(tool_call_id)" in ddl["ansich_authorization_snapshots"]
    assert "FOREIGN KEY(snapshot_id)" in ddl["ansich_authorization_permissions"]
    assert "PRIMARY KEY (tool_call_id, snapshot_id)" in ddl["ansich_tool_call_authorizations"]
    assert "ck_ansich_authorization_decision" in ddl["ansich_authorization_snapshots"]
    assert "ck_ansich_tool_effect_phase" in ddl["ansich_tool_effects"]
    assert "ck_ansich_tool_effect_class" in ddl["ansich_tool_effects"]
    assert {
        "ix_ansich_authorization_tool_evaluated",
        "ix_ansich_authorization_decision_policy",
    } <= {index.name for index in AnsichAuthorizationSnapshotRow.__table__.indexes}
    assert {
        "ix_ansich_tool_effect_class_phase_scope",
        "ix_ansich_tool_effect_scope_tool",
    } <= {index.name for index in AnsichToolEffectRow.__table__.indexes}


def test_phase9_safety_migration_upgrades_sqlite(tmp_path) -> None:
    backend_root = Path(__file__).resolve().parents[2]
    config = AlembicConfig(str(backend_root / "packages" / "harness" / "deerflow" / "persistence" / "migrations" / "alembic.ini"))
    database_path = tmp_path / "ansich-phase9-migration.db"
    config.set_main_option(
        "script_location",
        str(backend_root / "packages" / "harness" / "deerflow" / "persistence" / "migrations"),
    )
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database_path}")
    config.config_file_name = None

    def _enable_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    event.listen(Pool, "connect", _enable_foreign_keys)
    try:
        alembic_command.upgrade(config, "head")
    finally:
        event.remove(Pool, "connect", _enable_foreign_keys)

    engine = create_engine(f"sqlite:///{database_path}")

    @event.listens_for(engine, "connect")
    def _enable_verification_foreign_keys(
        dbapi_connection,
        _connection_record,
    ):
        _enable_foreign_keys(dbapi_connection, _connection_record)

    try:
        database_inspector = inspect(engine)
        table_names = set(database_inspector.get_table_names())
        scope_columns = {column["name"] for column in database_inspector.get_columns("ansich_scopes")}
        relation_columns = {column["name"] for column in database_inspector.get_columns("ansich_relations")}
        summary_columns = {column["name"]: column for column in database_inspector.get_columns("ansich_task_summaries")}
        summary_assertion_fk = next(foreign_key for foreign_key in database_inspector.get_foreign_keys("ansich_task_summaries") if foreign_key["constrained_columns"] == ["assertion_id"])
        with engine.connect() as connection:
            revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
        with engine.begin() as connection:
            observed_at = datetime(2026, 7, 23, tzinfo=UTC)
            connection.execute(
                AnsichObservationRow.__table__.insert(),
                (
                    {
                        "obs_id": "00000000-0000-4000-8000-000000000201",
                        "schema_version": 1,
                        "kind": "task.created",
                        "occurred_at": observed_at,
                        "recorded_at": observed_at,
                        "task_id": "00000000-0000-4000-8000-000000000301",
                        "step_id": None,
                        "subject_type": "task",
                        "subject_id": "00000000-0000-4000-8000-000000000301",
                        "fidelity_class": "hard",
                        "producer_name": "migration-test",
                        "producer_version": "1",
                        "producer_instance_id": "migration-test",
                        "producer_seq": 1,
                        "source_event_id": "migration-test:scope-a",
                        "correlation_id": "migration-test",
                        "causation_obs_id": None,
                        "payload_json": {},
                        "payload_ref_id": None,
                    },
                    {
                        "obs_id": "00000000-0000-4000-8000-000000000202",
                        "schema_version": 1,
                        "kind": "task.created",
                        "occurred_at": observed_at,
                        "recorded_at": observed_at,
                        "task_id": "00000000-0000-4000-8000-000000000302",
                        "step_id": None,
                        "subject_type": "task",
                        "subject_id": "00000000-0000-4000-8000-000000000302",
                        "fidelity_class": "hard",
                        "producer_name": "migration-test",
                        "producer_version": "1",
                        "producer_instance_id": "migration-test",
                        "producer_seq": 2,
                        "source_event_id": "migration-test:scope-b",
                        "correlation_id": "migration-test",
                        "causation_obs_id": None,
                        "payload_json": {},
                        "payload_ref_id": None,
                    },
                ),
            )
            connection.execute(
                AnsichEntityRow.__table__.insert(),
                (
                    {
                        "entity_id": "00000000-0000-4000-8000-000000000101",
                        "entity_type": "scope",
                        "discovered_obs_id": "00000000-0000-4000-8000-000000000201",
                    },
                    {
                        "entity_id": "00000000-0000-4000-8000-000000000102",
                        "entity_type": "scope",
                        "discovered_obs_id": "00000000-0000-4000-8000-000000000202",
                    },
                ),
            )
            connection.execute(
                text(
                    """
                    INSERT INTO ansich_scopes (
                        entity_id, scope_kind, scope_value, external_ref_hash,
                        display_label, parent_scope_id, created_obs_id
                    ) VALUES (
                        :entity_id, 'workspace', NULL, :external_ref_hash,
                        'same-leaf', NULL, :created_obs_id
                    )
                    """
                ),
                (
                    {
                        "entity_id": "00000000-0000-4000-8000-000000000101",
                        "external_ref_hash": "a" * 64,
                        "created_obs_id": "00000000-0000-4000-8000-000000000201",
                    },
                    {
                        "entity_id": "00000000-0000-4000-8000-000000000102",
                        "external_ref_hash": "b" * 64,
                        "created_obs_id": "00000000-0000-4000-8000-000000000202",
                    },
                ),
            )
    finally:
        engine.dispose()

    assert revision == "0027_ansich_lease_generation"
    assert {
        "ansich_authorization_snapshots",
        "ansich_authorization_scopes",
        "ansich_authorization_permissions",
        "ansich_tool_call_authorizations",
        "ansich_tool_effects",
        "ansich_scope_conclusions",
    } <= table_names
    assert {"external_ref_hash", "display_label", "parent_scope_id", "created_obs_id"} <= scope_columns
    assert {"relation_role", "inherited_from_task_id"} <= relation_columns
    assert summary_columns[AnsichTaskSummaryRow.assertion_id.name]["nullable"] is True
    assert summary_assertion_fk["options"]["ondelete"] == "SET NULL"

    event.listen(Pool, "connect", _enable_foreign_keys)
    try:
        alembic_command.downgrade(config, "0019_ansich_task_tree_usage")
    finally:
        event.remove(Pool, "connect", _enable_foreign_keys)
    engine = create_engine(f"sqlite:///{database_path}")
    try:
        downgraded_scope_columns = {column["name"] for column in inspect(engine).get_columns("ansich_scopes")}
        with engine.connect() as connection:
            downgraded_revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
            downgraded_values = tuple(
                connection.scalars(
                    text(
                        """
                        SELECT scope_value
                        FROM ansich_scopes
                        WHERE entity_id IN (
                            '00000000-0000-4000-8000-000000000101',
                            '00000000-0000-4000-8000-000000000102'
                        )
                        ORDER BY entity_id
                        """
                    )
                )
            )
    finally:
        engine.dispose()

    assert downgraded_revision == "0019_ansich_task_tree_usage"
    assert "external_ref_hash" not in downgraded_scope_columns
    assert downgraded_values == ("a" * 64, "b" * 64)


@pytest.mark.anyio
async def test_scope_safety_waits_for_subject_entity_then_self_heals(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'scope-safety-subject-dependency.db'}")

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(
        session_factory,
        flush_interval_ms=60_000,
        terminal_flush_timeout_ms=100,
        projector_poll_interval_ms=5,
        operations_assessment_interval_ms=60_000,
    )
    only_test_driven_assessments(service)
    await service.start()
    task_id, step_id, tool_call_id = new_id(), new_id(), new_id()
    observed_at = datetime(2026, 8, 18, 9, tzinfo=UTC)
    producer = Producer(name="scope-dependency-test", version="1", instance_id="test")
    authorization_obs_id = new_id()
    snapshot = AuthorizationSnapshot(
        snapshot_id=new_id(),
        tool_call_id=tool_call_id,
        policy_id="scope-dependency-policy",
        policy_version="1",
        policy_hash="a" * 64,
        decision="allowed",
        details_available=False,
        evaluated_at=observed_at,
        evidence_obs_ids=(authorization_obs_id,),
    )
    scope_obs_id = new_id()
    scope = ScopeDescriptor(
        scope_id=new_id(),
        scope_kind="workspace",
        external_ref_hash="b" * 64,
        display_label="workspace",
        created_obs_id=scope_obs_id,
    )

    try:
        service.record(
            ObservationEnvelope.task_lifecycle(
                kind="task.created",
                task_id=task_id,
                source_kind="deerflow_run",
                source_id="scope-dependency-run",
                occurred_at=observed_at,
                source_event_id="scope-dependency:task:created",
            )
        )
        await service.flush_task(task_id)
        service.record_batch(
            (
                ObservationEnvelope(
                    obs_id=authorization_obs_id,
                    kind="authorization.evaluated",
                    occurred_at=observed_at,
                    task_id=task_id,
                    step_id=step_id,
                    subject_type="authorization_snapshot",
                    subject_id=snapshot.snapshot_id,
                    producer=producer,
                    source_event_id="scope-dependency:authorization:evaluated",
                    correlation_id="scope-dependency-run",
                    payload={"snapshot": snapshot.model_dump(mode="json")},
                ),
                ObservationEnvelope(
                    obs_id=scope_obs_id,
                    kind="scope.snapshotted",
                    occurred_at=observed_at,
                    task_id=task_id,
                    subject_type="scope",
                    subject_id=scope.scope_id,
                    producer=producer,
                    source_event_id="scope-dependency:scope:snapshotted",
                    correlation_id="scope-dependency-run",
                    payload={"scope": scope.model_dump(mode="json")},
                ),
            )
        )
        await service.flush_task(task_id)
        await service.assess_operations(now=observed_at)

        async with session_factory() as session:
            waiting_job = await session.scalar(select(AnsichAssessorJobRow).where(AnsichAssessorJobRow.assessor_name == "scope-safety"))
            error_count = await session.scalar(select(func.count()).select_from(AnsichAssessorErrorRow))
            missing_subject = await session.get(AnsichEntityRow, tool_call_id)

        assert waiting_job is not None
        assert waiting_job.status == "pending"
        assert waiting_job.attempts == 0
        assert "waiting for subject Entity" in (waiting_job.last_error or "")
        assert error_count == 0
        assert missing_subject is None

        await anyio.sleep(0.3)
        service.record_batch(
            (
                ObservationEnvelope(
                    kind="step.started",
                    occurred_at=observed_at,
                    task_id=task_id,
                    step_id=step_id,
                    subject_type="step",
                    subject_id=step_id,
                    producer=producer,
                    source_event_id="scope-dependency:step:started",
                    correlation_id="scope-dependency-run",
                    payload={"step_seq": 1, "actor_kind": "lead_agent"},
                ),
                ObservationEnvelope(
                    kind="tool.issued",
                    occurred_at=observed_at,
                    task_id=task_id,
                    step_id=step_id,
                    subject_type="tool_call",
                    subject_id=tool_call_id,
                    producer=producer,
                    source_event_id="scope-dependency:tool:issued",
                    correlation_id="scope-dependency-run",
                    payload={
                        "call_seq": 1,
                        "provider_call_id": "provider-scope-dependency",
                        "tool_name": "write_file",
                        "args_hash": "c" * 64,
                        "args_preview": {"path": "workspace/result.md"},
                        "tool_schema_block_id": None,
                    },
                ),
            )
        )
        await service.flush_task(task_id)
        await anyio.sleep(0.3)
        await service.assess_operations(now=observed_at)

        async with session_factory() as session:
            recovered_subject = await session.get(AnsichEntityRow, tool_call_id)
            recovered_statuses = tuple((await session.execute(select(AnsichAssessorJobRow.status).where(AnsichAssessorJobRow.assessor_name == "scope-safety"))).scalars())
            error_count_after_recovery = await session.scalar(select(func.count()).select_from(AnsichAssessorErrorRow))
        belief = await service.get_current_belief(
            tool_call_id,
            "scope_safety:policy_denial",
        )
    finally:
        await service.stop()
        await engine.dispose()

    assert recovered_subject is not None
    assert recovered_statuses
    assert set(recovered_statuses) == {"completed"}
    assert error_count_after_recovery == 0
    assert belief is not None


@pytest.mark.anyio
async def test_scope_safety_dependency_wait_crosses_deadline_into_failed_job_and_retry(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'scope-safety-dependency-deadline.db'}")

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(
        session_factory,
        flush_interval_ms=60_000,
        terminal_flush_timeout_ms=100,
        projector_poll_interval_ms=5,
        operations_assessment_interval_ms=60_000,
        projector_dependency_timeout_seconds=0,
    )
    only_test_driven_assessments(service)
    await service.start()
    task_id, step_id, tool_call_id = new_id(), new_id(), new_id()
    observed_at = datetime(2026, 8, 18, 9, tzinfo=UTC)
    producer = Producer(name="scope-dependency-deadline-test", version="1", instance_id="test")
    authorization_obs_id = new_id()
    snapshot = AuthorizationSnapshot(
        snapshot_id=new_id(),
        tool_call_id=tool_call_id,
        policy_id="scope-dependency-deadline-policy",
        policy_version="1",
        policy_hash="a" * 64,
        decision="allowed",
        details_available=False,
        evaluated_at=observed_at,
        evidence_obs_ids=(authorization_obs_id,),
    )
    scope_obs_id = new_id()
    scope = ScopeDescriptor(
        scope_id=new_id(),
        scope_kind="workspace",
        external_ref_hash="b" * 64,
        display_label="workspace",
        created_obs_id=scope_obs_id,
    )

    try:
        service.record(
            ObservationEnvelope.task_lifecycle(
                kind="task.created",
                task_id=task_id,
                source_kind="deerflow_run",
                source_id="scope-dependency-deadline-run",
                occurred_at=observed_at,
                source_event_id="scope-dependency-deadline:task:created",
            )
        )
        await service.flush_task(task_id)
        service.record_batch(
            (
                ObservationEnvelope(
                    obs_id=authorization_obs_id,
                    kind="authorization.evaluated",
                    occurred_at=observed_at,
                    task_id=task_id,
                    step_id=step_id,
                    subject_type="authorization_snapshot",
                    subject_id=snapshot.snapshot_id,
                    producer=producer,
                    source_event_id="scope-dependency-deadline:authorization:evaluated",
                    correlation_id="scope-dependency-deadline-run",
                    payload={"snapshot": snapshot.model_dump(mode="json")},
                ),
                ObservationEnvelope(
                    obs_id=scope_obs_id,
                    kind="scope.snapshotted",
                    occurred_at=observed_at,
                    task_id=task_id,
                    subject_type="scope",
                    subject_id=scope.scope_id,
                    producer=producer,
                    source_event_id="scope-dependency-deadline:scope:snapshotted",
                    correlation_id="scope-dependency-deadline-run",
                    payload={"scope": scope.model_dump(mode="json")},
                ),
            )
        )
        await service.flush_task(task_id)
        await service.assess_operations(now=observed_at)

        async with session_factory() as session:
            timed_out_job = await session.scalar(select(AnsichAssessorJobRow).where(AnsichAssessorJobRow.assessor_name == "scope-safety"))
            timed_out_error_count = await session.scalar(select(func.count()).select_from(AnsichAssessorErrorRow).where(AnsichAssessorErrorRow.job_id == timed_out_job.job_id))
        health_after_timeout = service.get_health()

        assert timed_out_job.status == "failed"
        assert timed_out_job.dependency_pending_since is not None
        assert "waiting for subject Entity" in (timed_out_job.last_error or "")
        assert timed_out_error_count == 1
        assert health_after_timeout.failed_jobs >= 1

        service.record_batch(
            (
                ObservationEnvelope(
                    kind="step.started",
                    occurred_at=observed_at,
                    task_id=task_id,
                    step_id=step_id,
                    subject_type="step",
                    subject_id=step_id,
                    producer=producer,
                    source_event_id="scope-dependency-deadline:step:started",
                    correlation_id="scope-dependency-deadline-run",
                    payload={"step_seq": 1, "actor_kind": "lead_agent"},
                ),
                ObservationEnvelope(
                    kind="tool.issued",
                    occurred_at=observed_at,
                    task_id=task_id,
                    step_id=step_id,
                    subject_type="tool_call",
                    subject_id=tool_call_id,
                    producer=producer,
                    source_event_id="scope-dependency-deadline:tool:issued",
                    correlation_id="scope-dependency-deadline-run",
                    payload={
                        "call_seq": 1,
                        "provider_call_id": "provider-scope-dependency-deadline",
                        "tool_name": "write_file",
                        "args_hash": "c" * 64,
                        "args_preview": {"path": "workspace/result.md"},
                        "tool_schema_block_id": None,
                    },
                ),
            )
        )
        await service.flush_task(task_id)
        retried = await service.retry_failed_projections(task_id=task_id)
        await service.assess_operations(now=observed_at)

        async with session_factory() as session:
            recovered_statuses = tuple((await session.execute(select(AnsichAssessorJobRow.status).where(AnsichAssessorJobRow.assessor_name == "scope-safety"))).scalars())
        belief = await service.get_current_belief(
            tool_call_id,
            "scope_safety:policy_denial",
        )
        health_after_retry = service.get_health()
    finally:
        await service.stop()
        await engine.dispose()

    assert retried >= 1
    assert recovered_statuses
    assert set(recovered_statuses) == {"completed"}
    assert belief is not None
    assert health_after_retry.failed_jobs == 0


@pytest.mark.anyio
async def test_sql_projects_scopes_authorization_and_effects_as_typed_rows(
    tmp_path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'safety.db'}")

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(session_factory)
    only_test_driven_assessments(service)
    await service.start()
    task_id, step_id, tool_call_id = new_id(), new_id(), new_id()
    observed_at = datetime.now(UTC)
    producer = Producer(name="safety-test", version="1", instance_id="test")
    workspace_path = "/srv/tenants/acme/private-project"

    try:
        service.record_batch(
            (
                ObservationEnvelope.task_lifecycle(
                    kind="task.created",
                    task_id=task_id,
                    source_kind="deerflow_run",
                    source_id="safety-run",
                    occurred_at=observed_at,
                    source_event_id="safety:task:created",
                    owner_id="owner-acme",
                    attributes={"workspace_ref": workspace_path},
                ),
                ObservationEnvelope(
                    kind="step.started",
                    occurred_at=observed_at,
                    task_id=task_id,
                    step_id=step_id,
                    subject_type="step",
                    subject_id=step_id,
                    producer=producer,
                    source_event_id="safety:step:started",
                    correlation_id="safety-run",
                    payload={"step_seq": 1, "actor_kind": "lead_agent"},
                ),
                ObservationEnvelope(
                    kind="tool.issued",
                    occurred_at=observed_at,
                    task_id=task_id,
                    step_id=step_id,
                    subject_type="tool_call",
                    subject_id=tool_call_id,
                    producer=producer,
                    source_event_id="safety:tool:issued",
                    correlation_id="safety-run",
                    payload={
                        "call_seq": 1,
                        "provider_call_id": "provider-safety",
                        "tool_name": "write_file",
                        "args_hash": "a" * 64,
                        "args_preview": {"path": "workspace/report.md"},
                        "tool_schema_block_id": None,
                    },
                ),
            )
        )
        await service.flush_task(task_id)
        async with session_factory() as session:
            scope_rows = list((await session.execute(select(AnsichScopeRow).order_by(AnsichScopeRow.scope_kind))).scalars())
        scopes = {row.scope_kind: row for row in scope_rows}
        snapshot_id = new_id()
        evaluated_obs_id = new_id()
        snapshot = AuthorizationSnapshot(
            snapshot_id=snapshot_id,
            tool_call_id=tool_call_id,
            principal_scope_ids=(scopes["owner"].entity_id,),
            policy_id="workspace-policy",
            policy_version="1",
            policy_hash="b" * 64,
            decision="allowed",
            details_available=True,
            effective_permissions=(
                AuthorizationPermission(
                    resource="workspace/report.md",
                    action="write",
                    scope_id=scopes["workspace"].entity_id,
                    effect="filesystem_write",
                ),
            ),
            resource_scope_ids=(scopes["workspace"].entity_id,),
            reason_codes=("within_workspace",),
            evaluated_at=observed_at,
            evidence_obs_ids=(evaluated_obs_id,),
        )
        decision_obs_id = new_id()
        effect_obs_id = new_id()
        effect = ToolEffect(
            effect_id=new_id(),
            tool_call_id=tool_call_id,
            effect_class="filesystem_write",
            phase="observed",
            scope_id=scopes["workspace"].entity_id,
            target_hash="c" * 64,
            target_preview="workspace/report.md",
            fidelity_class="hard",
            source_obs_id=effect_obs_id,
            result_metadata={"status": "written"},
        )
        service.record_batch(
            (
                ObservationEnvelope(
                    obs_id=evaluated_obs_id,
                    kind="authorization.evaluated",
                    occurred_at=observed_at,
                    task_id=task_id,
                    step_id=step_id,
                    subject_type="authorization_snapshot",
                    subject_id=snapshot_id,
                    producer=producer,
                    source_event_id="safety:authorization:evaluated",
                    correlation_id="safety-run",
                    payload={"snapshot": snapshot.model_dump(mode="json")},
                ),
                ObservationEnvelope(
                    obs_id=decision_obs_id,
                    kind="authorization.allowed",
                    occurred_at=observed_at,
                    task_id=task_id,
                    step_id=step_id,
                    subject_type="authorization_snapshot",
                    subject_id=snapshot_id,
                    producer=producer,
                    source_event_id="safety:authorization:allowed",
                    correlation_id="safety-run",
                    causation_obs_id=evaluated_obs_id,
                    payload={"snapshot": snapshot.model_dump(mode="json")},
                ),
                ObservationEnvelope(
                    obs_id=effect_obs_id,
                    kind="effect.observed",
                    occurred_at=observed_at,
                    task_id=task_id,
                    step_id=step_id,
                    subject_type="effect",
                    subject_id=effect.effect_id,
                    producer=producer,
                    source_event_id="safety:effect:observed",
                    correlation_id="safety-run",
                    causation_obs_id=decision_obs_id,
                    payload={"effect": effect.model_dump(mode="json")},
                ),
            )
        )
        await service.flush_task(task_id)
        await service.assess_operations(now=observed_at)

        task_scopes = await service.get_task_scopes(task_id)
        authorization = await service.get_tool_authorization(tool_call_id)
        effects = await service.get_tool_effects(tool_call_id)

        async with session_factory() as session:
            snapshot_row = await session.get(AnsichAuthorizationSnapshotRow, snapshot_id)
            permission_count = await session.scalar(select(func.count()).select_from(AnsichAuthorizationPermissionRow))
            binding = await session.get(AnsichToolCallAuthorizationRow, (tool_call_id, snapshot_id))
            effect_row = await session.get(AnsichToolEffectRow, effect.effect_id)
            relation_roles = set(
                (
                    await session.execute(
                        select(AnsichRelationRow.relation_role).where(
                            AnsichRelationRow.subject_id == task_id,
                            AnsichRelationRow.predicate == "within_scope",
                        )
                    )
                ).scalars()
            )
        rebuild = await service.rebuild_projections()
        rebuilt_scopes = await service.get_task_scopes(task_id)
        rebuilt_authorization = await service.get_tool_authorization(tool_call_id)
        rebuilt_effects = await service.get_tool_effects(tool_call_id)
        async with session_factory() as session:
            conclusion_count = await session.scalar(select(func.count()).select_from(AnsichScopeConclusionRow))
            unverified_current = await session.get(
                AnsichCurrentBeliefRow,
                (tool_call_id, "scope_safety:unverified_effect"),
            )
    finally:
        await service.stop()
        await engine.dispose()

    assert scopes["workspace"].scope_value is None
    assert scopes["workspace"].display_label == "private-project"
    assert workspace_path not in scopes["workspace"].display_label
    assert relation_roles == {"owner", "execution_workspace"}
    assert snapshot_row is not None and snapshot_row.decision == "allowed"
    assert permission_count == 1
    assert binding is not None and binding.relation_obs_id == decision_obs_id
    assert effect_row is not None and effect_row.phase == "observed"
    assert {item.relation_role for item in task_scopes.scopes} == {
        "owner",
        "execution_workspace",
    }
    assert authorization is not None
    assert authorization.current_decision == "allowed"
    assert authorization.snapshots[0].effective_permissions[0].action == "write"
    assert effects is not None
    assert effects.coverage == "partial"
    assert effects.effects == (effect,)
    assert conclusion_count >= 4
    assert unverified_current is not None
    assert rebuild.replayed > 0
    assert rebuild.unsettled == 0
    assert rebuilt_scopes == task_scopes
    assert rebuilt_authorization == authorization
    assert rebuilt_effects == effects


@pytest.mark.anyio
async def test_sql_projects_delete_and_permission_effects_as_typed_rows(tmp_path) -> None:
    """`filesystem_delete`/`permission_change` survive record -> project -> read."""

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'safety-new-classes.db'}")

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(session_factory)
    only_test_driven_assessments(service)
    await service.start()
    task_id, step_id = new_id(), new_id()
    observed_at = datetime.now(UTC)
    producer = Producer(name="safety-test", version="1", instance_id="test")
    cases = (
        ("filesystem_delete", "rm", new_id()),
        ("permission_change", "chmod", new_id()),
    )

    try:
        service.record_batch(
            (
                ObservationEnvelope.task_lifecycle(
                    kind="task.created",
                    task_id=task_id,
                    source_kind="deerflow_run",
                    source_id="safety-run",
                    occurred_at=observed_at,
                    source_event_id="safety:task:created",
                    owner_id="owner-acme",
                    attributes={"workspace_ref": "/srv/tenants/acme/private-project"},
                ),
                ObservationEnvelope(
                    kind="step.started",
                    occurred_at=observed_at,
                    task_id=task_id,
                    step_id=step_id,
                    subject_type="step",
                    subject_id=step_id,
                    producer=producer,
                    source_event_id="safety:step:started",
                    correlation_id="safety-run",
                    payload={"step_seq": 1, "actor_kind": "lead_agent"},
                ),
                *(
                    ObservationEnvelope(
                        kind="tool.issued",
                        occurred_at=observed_at,
                        task_id=task_id,
                        step_id=step_id,
                        subject_type="tool_call",
                        subject_id=tool_call_id,
                        producer=producer,
                        source_event_id=f"safety:tool:issued:{label}",
                        correlation_id="safety-run",
                        payload={
                            "call_seq": index + 1,
                            "provider_call_id": f"provider-{label}",
                            "tool_name": "bash",
                            "args_hash": "a" * 64,
                            "args_preview": {"command": f"{label} workspace/report.md"},
                            "tool_schema_block_id": None,
                        },
                    )
                    for index, (_, label, tool_call_id) in enumerate(cases)
                ),
            )
        )
        await service.flush_task(task_id)
        async with session_factory() as session:
            scope_rows = list((await session.execute(select(AnsichScopeRow))).scalars())
        scopes = {row.scope_kind: row for row in scope_rows}

        recorded_effects: dict[str, tuple[ToolEffect, ...]] = {}
        for effect_class, label, tool_call_id in cases:
            snapshot_id, evaluated_obs_id, decision_obs_id = new_id(), new_id(), new_id()
            snapshot = AuthorizationSnapshot(
                snapshot_id=snapshot_id,
                tool_call_id=tool_call_id,
                principal_scope_ids=(scopes["owner"].entity_id,),
                policy_id="workspace-policy",
                policy_version="1",
                policy_hash="b" * 64,
                decision="allowed",
                details_available=True,
                effective_permissions=(
                    AuthorizationPermission(
                        resource="workspace/report.md",
                        action=label,
                        scope_id=scopes["workspace"].entity_id,
                        effect=effect_class,
                    ),
                ),
                resource_scope_ids=(scopes["workspace"].entity_id,),
                reason_codes=("within_workspace",),
                evaluated_at=observed_at,
                evidence_obs_ids=(evaluated_obs_id,),
            )
            intended_obs_id, observed_obs_id, companion_obs_id = new_id(), new_id(), new_id()
            intended = ToolEffect(
                effect_id=new_id(),
                tool_call_id=tool_call_id,
                effect_class=effect_class,
                phase="intended",
                scope_id=scopes["workspace"].entity_id,
                target_hash="c" * 64,
                target_preview="workspace/report.md",
                fidelity_class="inferred",
                source_obs_id=intended_obs_id,
            )
            observed = intended.model_copy(
                update={
                    "effect_id": new_id(),
                    "phase": "observed",
                    "source_obs_id": observed_obs_id,
                }
            )
            # Mirrors what the bash probe actually emits: the argv-derived class
            # plus the honest `unknown` companion for the rest of the command's
            # unobservable effect surface.
            companion = ToolEffect(
                effect_id=new_id(),
                tool_call_id=tool_call_id,
                effect_class="unknown",
                phase="observed",
                scope_id=None,
                target_hash="c" * 64,
                target_preview="bash internal effects",
                fidelity_class="unknown",
                source_obs_id=companion_obs_id,
            )
            recorded_effects[tool_call_id] = (intended, observed, companion)
            service.record_batch(
                (
                    ObservationEnvelope(
                        obs_id=evaluated_obs_id,
                        kind="authorization.evaluated",
                        occurred_at=observed_at,
                        task_id=task_id,
                        step_id=step_id,
                        subject_type="authorization_snapshot",
                        subject_id=snapshot_id,
                        producer=producer,
                        source_event_id=f"safety:authorization:evaluated:{label}",
                        correlation_id="safety-run",
                        payload={"snapshot": snapshot.model_dump(mode="json")},
                    ),
                    ObservationEnvelope(
                        obs_id=decision_obs_id,
                        kind="authorization.allowed",
                        occurred_at=observed_at,
                        task_id=task_id,
                        step_id=step_id,
                        subject_type="authorization_snapshot",
                        subject_id=snapshot_id,
                        producer=producer,
                        source_event_id=f"safety:authorization:allowed:{label}",
                        correlation_id="safety-run",
                        causation_obs_id=evaluated_obs_id,
                        payload={"snapshot": snapshot.model_dump(mode="json")},
                    ),
                    ObservationEnvelope(
                        obs_id=intended_obs_id,
                        kind="effect.intended",
                        occurred_at=observed_at,
                        task_id=task_id,
                        step_id=step_id,
                        subject_type="effect",
                        subject_id=intended.effect_id,
                        producer=producer,
                        source_event_id=f"safety:effect:intended:{label}",
                        correlation_id="safety-run",
                        causation_obs_id=decision_obs_id,
                        payload={"effect": intended.model_dump(mode="json")},
                    ),
                    ObservationEnvelope(
                        obs_id=observed_obs_id,
                        kind="effect.observed",
                        occurred_at=observed_at,
                        task_id=task_id,
                        step_id=step_id,
                        subject_type="effect",
                        subject_id=observed.effect_id,
                        producer=producer,
                        source_event_id=f"safety:effect:observed:{label}",
                        correlation_id="safety-run",
                        causation_obs_id=decision_obs_id,
                        payload={"effect": observed.model_dump(mode="json")},
                    ),
                    ObservationEnvelope(
                        obs_id=companion_obs_id,
                        kind="effect.observed",
                        occurred_at=observed_at,
                        task_id=task_id,
                        step_id=step_id,
                        subject_type="effect",
                        subject_id=companion.effect_id,
                        producer=producer,
                        source_event_id=f"safety:effect:observed-companion:{label}",
                        correlation_id="safety-run",
                        causation_obs_id=decision_obs_id,
                        payload={"effect": companion.model_dump(mode="json")},
                    ),
                )
            )
        await service.flush_task(task_id)
        await service.assess_operations(now=observed_at)

        read_back = {tool_call_id: await service.get_tool_effects(tool_call_id) for _, _, tool_call_id in cases}
        async with session_factory() as session:
            row_classes = {
                tool_call_id: sorted(
                    (
                        await session.execute(
                            select(AnsichToolEffectRow.effect_class).where(AnsichToolEffectRow.tool_call_id == tool_call_id),
                        )
                    )
                    .scalars()
                    .all()
                )
                for _, _, tool_call_id in cases
            }
            unverified = {
                tool_call_id: await session.scalar(
                    select(AnsichBeliefAssertionRow.value_json)
                    .join(
                        AnsichCurrentBeliefRow,
                        AnsichCurrentBeliefRow.assertion_id == AnsichBeliefAssertionRow.assertion_id,
                    )
                    .where(
                        AnsichCurrentBeliefRow.subject_id == tool_call_id,
                        AnsichCurrentBeliefRow.field_name == "scope_safety:unverified_effect",
                    )
                )
                for _, _, tool_call_id in cases
            }
    finally:
        await service.stop()
        await engine.dispose()

    def _sort_key(item: ToolEffect) -> tuple[str, str]:
        return (item.phase, item.effect_class)

    for effect_class, _, tool_call_id in cases:
        assert row_classes[tool_call_id] == [effect_class, effect_class, "unknown"]
        view = read_back[tool_call_id]
        assert view is not None
        assert sorted(view.effects, key=_sort_key) == sorted(recorded_effects[tool_call_id], key=_sort_key)
        # The argv-derived class is recorded, but the retained `unknown`
        # companion keeps the call honestly unverified: nothing observed
        # whether the delete or chmod actually happened.
        assert unverified[tool_call_id] is not None
        assert unverified[tool_call_id]["value"] == "present"


@pytest.mark.anyio
async def test_externalized_scope_authorization_and_effect_payloads_read_back(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'safety-externalized-payloads.db'}")

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(
        session_factory,
        flush_interval_ms=60_000,
        terminal_flush_timeout_ms=100,
        projector_poll_interval_ms=5,
        operations_assessment_interval_ms=60_000,
        # An Observation is only ever read back with payload=None when its
        # payload was externalized into ansich_payloads, so drive every payload
        # in this test over the inline threshold instead of padding a field.
        inline_payload_max_bytes=16,
    )
    await service.start()
    task_id, step_id, tool_call_id = new_id(), new_id(), new_id()
    observed_at = datetime(2026, 8, 18, 11, tzinfo=UTC)
    producer = Producer(name="externalized-payload-test", version="1", instance_id="test")
    scope_obs_id, authorization_obs_id, effect_obs_id = new_id(), new_id(), new_id()
    scope = ScopeDescriptor(
        scope_id=new_id(),
        scope_kind="workspace",
        external_ref_hash="a" * 64,
        display_label="workspace",
        created_obs_id=scope_obs_id,
    )
    snapshot = AuthorizationSnapshot(
        snapshot_id=new_id(),
        tool_call_id=tool_call_id,
        policy_id="externalized-payload-policy",
        policy_version="1",
        policy_hash="b" * 64,
        decision="allowed",
        details_available=False,
        evaluated_at=observed_at,
        evidence_obs_ids=(authorization_obs_id,),
    )
    effect = ToolEffect(
        effect_id=new_id(),
        tool_call_id=tool_call_id,
        effect_class="filesystem_write",
        phase="observed",
        scope_id=scope.scope_id,
        target_hash="c" * 64,
        target_preview="workspace/report.md",
        fidelity_class="hard",
        source_obs_id=effect_obs_id,
        result_metadata={"status": "written"},
    )
    externalized_obs_ids = (scope_obs_id, authorization_obs_id, effect_obs_id)

    try:
        service.record(
            ObservationEnvelope.task_lifecycle(
                kind="task.created",
                task_id=task_id,
                source_kind="deerflow_run",
                source_id="externalized-payload-run",
                occurred_at=observed_at,
                source_event_id="externalized-payload:task:created",
            )
        )
        await service.flush_task(task_id)
        service.record_batch(
            (
                ObservationEnvelope(
                    obs_id=scope_obs_id,
                    kind="scope.snapshotted",
                    occurred_at=observed_at,
                    task_id=task_id,
                    subject_type="scope",
                    subject_id=scope.scope_id,
                    producer=producer,
                    source_event_id="externalized-payload:scope:snapshotted",
                    correlation_id="externalized-payload-run",
                    payload={"scope": scope.model_dump(mode="json")},
                ),
                ObservationEnvelope(
                    obs_id=authorization_obs_id,
                    kind="authorization.allowed",
                    occurred_at=observed_at,
                    task_id=task_id,
                    step_id=step_id,
                    subject_type="authorization_snapshot",
                    subject_id=snapshot.snapshot_id,
                    producer=producer,
                    source_event_id="externalized-payload:authorization:allowed",
                    correlation_id="externalized-payload-run",
                    payload={"snapshot": snapshot.model_dump(mode="json")},
                ),
                ObservationEnvelope(
                    obs_id=effect_obs_id,
                    kind="effect.observed",
                    occurred_at=observed_at,
                    task_id=task_id,
                    step_id=step_id,
                    subject_type="effect",
                    subject_id=effect.effect_id,
                    producer=producer,
                    source_event_id="externalized-payload:effect:observed",
                    correlation_id="externalized-payload-run",
                    payload={"effect": effect.model_dump(mode="json")},
                ),
            )
        )
        await service.flush_task(task_id)

        async with session_factory() as session:
            stored_rows = list((await session.execute(select(AnsichObservationRow).where(AnsichObservationRow.obs_id.in_(externalized_obs_ids)))).scalars())
            # Pin the claim path too, not just the read path: `_project_pending`
            # swallows projection exceptions, so a claim-time envelope validator
            # that rejects an externalized payload loses the projection in
            # silence. `scope.snapshotted` is the probe because it waits on no
            # ToolCall - its row is either here or the claim dropped it.
            projected_scope = await session.get(AnsichScopeRow, scope.scope_id)
            projected_scope_state = None if projected_scope is None else (projected_scope.scope_kind, projected_scope.created_obs_id)
        stored_payload_state = {row.obs_id: (row.payload_json, row.payload_ref_id is not None) for row in stored_rows}

        timeline = await service.list_timeline(task_id, limit=50)
        observations = await service.list_observations(task_id)
    finally:
        await service.stop()
        await engine.dispose()

    assert stored_payload_state == {obs_id: (None, True) for obs_id in externalized_obs_ids}
    assert projected_scope_state == ("workspace", scope_obs_id)
    for read_back in (dict((observation.obs_id, observation) for _, observation in timeline), {observation.obs_id: observation for observation in observations}):
        assert set(externalized_obs_ids) <= set(read_back)
        assert read_back[scope_obs_id].kind == "scope.snapshotted"
        assert read_back[scope_obs_id].subject_id == scope.scope_id
        assert read_back[authorization_obs_id].kind == "authorization.allowed"
        assert read_back[authorization_obs_id].subject_id == snapshot.snapshot_id
        assert read_back[effect_obs_id].kind == "effect.observed"
        assert read_back[effect_obs_id].subject_id == effect.effect_id
        for obs_id in externalized_obs_ids:
            assert read_back[obs_id].payload is None
            assert read_back[obs_id].payload_ref_id is not None


def _scope_safety_tool_call_batch(
    *,
    task_id: str,
    step_id: str,
    tool_call_id: str,
    call_seq: int,
    producer: Producer,
    observed_at: datetime,
    label: str,
) -> tuple[ObservationEnvelope, ...]:
    """The ToolCall projection a scope-safety conclusion needs as its subject."""

    return (
        ObservationEnvelope(
            kind="tool.issued",
            occurred_at=observed_at,
            task_id=task_id,
            step_id=step_id,
            subject_type="tool_call",
            subject_id=tool_call_id,
            producer=producer,
            source_event_id=f"{label}:tool:issued",
            correlation_id=label,
            payload={
                "call_seq": call_seq,
                "provider_call_id": f"provider-{label}",
                "tool_name": "write_file",
                "args_hash": f"{call_seq:064d}",
                "args_preview": {"path": f"workspace/{label}.md"},
                "tool_schema_block_id": None,
            },
        ),
    )


def _scope_safety_evidence_batch(
    *,
    task_id: str,
    step_id: str,
    tool_call_id: str,
    producer: Producer,
    observed_at: datetime,
    label: str,
    with_observed_effect: bool,
) -> tuple[ObservationEnvelope, ...]:
    """Authorization plus effect evidence for one ToolCall.

    ``with_observed_effect=False`` leaves the call with a declared intent and no
    concrete observed effect, which is exactly the ``unverified_effect``
    ``present`` state that a later ``effect.observed`` clears.
    """

    snapshot_id = new_id()
    evaluated_obs_id = new_id()
    decision_obs_id = new_id()
    snapshot = AuthorizationSnapshot(
        snapshot_id=snapshot_id,
        tool_call_id=tool_call_id,
        policy_id="incremental-policy",
        policy_version="1",
        policy_hash="d" * 64,
        decision="allowed",
        details_available=True,
        reason_codes=("allowed",),
        evaluated_at=observed_at,
        evidence_obs_ids=(evaluated_obs_id, decision_obs_id),
    )
    intended_obs_id = new_id()
    intended = ToolEffect(
        effect_id=new_id(),
        tool_call_id=tool_call_id,
        effect_class="filesystem_write",
        phase="intended",
        scope_id=None,
        target_hash="e" * 64,
        target_preview=f"workspace/{label}.md",
        fidelity_class="inferred",
        source_obs_id=intended_obs_id,
    )
    observations = [
        ObservationEnvelope(
            obs_id=evaluated_obs_id,
            kind="authorization.evaluated",
            occurred_at=observed_at,
            task_id=task_id,
            step_id=step_id,
            subject_type="authorization_snapshot",
            subject_id=snapshot_id,
            producer=producer,
            source_event_id=f"{label}:authorization:evaluated",
            correlation_id=label,
            payload={"snapshot": snapshot.model_dump(mode="json")},
        ),
        ObservationEnvelope(
            obs_id=decision_obs_id,
            kind="authorization.allowed",
            occurred_at=observed_at,
            task_id=task_id,
            step_id=step_id,
            subject_type="authorization_snapshot",
            subject_id=snapshot_id,
            producer=producer,
            source_event_id=f"{label}:authorization:allowed",
            correlation_id=label,
            payload={"snapshot": snapshot.model_dump(mode="json")},
        ),
        ObservationEnvelope(
            obs_id=intended_obs_id,
            kind="effect.intended",
            occurred_at=observed_at,
            task_id=task_id,
            step_id=step_id,
            subject_type="effect",
            subject_id=intended.effect_id,
            producer=producer,
            source_event_id=f"{label}:effect:intended",
            correlation_id=label,
            payload={"effect": intended.model_dump(mode="json")},
        ),
    ]
    if with_observed_effect:
        observations.append(
            _scope_safety_observed_effect(
                task_id=task_id,
                step_id=step_id,
                tool_call_id=tool_call_id,
                producer=producer,
                observed_at=observed_at,
                label=label,
            )
        )
    return tuple(observations)


def _scope_safety_observed_effect(
    *,
    task_id: str,
    step_id: str,
    tool_call_id: str,
    producer: Producer,
    observed_at: datetime,
    label: str,
) -> ObservationEnvelope:
    observed_obs_id = new_id()
    observed = ToolEffect(
        effect_id=new_id(),
        tool_call_id=tool_call_id,
        effect_class="filesystem_write",
        phase="observed",
        scope_id=None,
        target_hash="f" * 64,
        target_preview=f"workspace/{label}.md",
        fidelity_class="hard",
        source_obs_id=observed_obs_id,
        result_metadata={"status": "written"},
    )
    return ObservationEnvelope(
        obs_id=observed_obs_id,
        kind="effect.observed",
        occurred_at=observed_at,
        task_id=task_id,
        step_id=step_id,
        subject_type="effect",
        subject_id=observed.effect_id,
        producer=producer,
        source_event_id=f"{label}:effect:observed",
        correlation_id=label,
        payload={"effect": observed.model_dump(mode="json")},
    )


def _scope_safety_service(tmp_path, name: str):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / name}")

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return engine, session_factory


async def _start_scope_safety_task(service, *, task_id: str, step_id: str, observed_at: datetime, producer: Producer, label: str) -> None:
    service.record_batch(
        (
            ObservationEnvelope.task_lifecycle(
                kind="task.created",
                task_id=task_id,
                source_kind="deerflow_run",
                source_id=label,
                occurred_at=observed_at,
                source_event_id=f"{label}:task:created",
            ),
            ObservationEnvelope(
                kind="step.started",
                occurred_at=observed_at,
                task_id=task_id,
                step_id=step_id,
                subject_type="step",
                subject_id=step_id,
                producer=producer,
                source_event_id=f"{label}:step:started",
                correlation_id=label,
                payload={"step_seq": 1, "actor_kind": "lead_agent"},
            ),
        )
    )
    await service.flush_task(task_id)


@pytest.mark.anyio
async def test_scope_safety_reassessment_work_does_not_grow_with_tool_call_count(
    tmp_path,
    monkeypatch,
) -> None:
    """P9-M2: one new ToolCall's evidence must not re-judge the whole Task.

    Each scope-safety conclusion is decided from one ``tool_call_id``'s own
    snapshots and effects, so a trigger carrying evidence for exactly one
    ToolCall has exactly one converged conclusion to move. The domain-call
    counter pins the re-judged subject count at 1, and the
    ``ansich_scope_conclusions`` statement counter pins that no per-subject
    write fan-out replaced it — together they keep the cumulative cost linear
    in the ToolCall count instead of quadratic.
    """

    tool_calls = 5
    engine, session_factory = _scope_safety_service(tmp_path, "scope-safety-incremental-cost.db")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(
        session_factory,
        flush_interval_ms=60_000,
        projector_poll_interval_ms=60_000,
        operations_assessment_interval_ms=60_000,
    )
    only_test_driven_assessments(service)
    await service.start()
    task_id, step_id = new_id(), new_id()
    observed_at = datetime(2026, 8, 19, 10, tzinfo=UTC)
    producer = Producer(name="scope-safety-cost", version="1", instance_id="test")

    assessed_subjects: list[str] = []
    real_assess_scope_safety = sql_module.assess_scope_safety

    def counting_assess_scope_safety(**kwargs):
        assessed_subjects.append(kwargs["tool_call_id"])
        return real_assess_scope_safety(**kwargs)

    monkeypatch.setattr(sql_module, "assess_scope_safety", counting_assess_scope_safety)

    conclusion_statements = {"count": 0}

    def capture_conclusion_sql(
        _connection,
        _cursor,
        statement,
        _parameters,
        _context,
        _executemany,
    ) -> None:
        if "ansich_scope_conclusions" in " ".join(statement.lower().split()):
            conclusion_statements["count"] += 1

    subjects_per_round: list[int] = []
    statements_per_round: list[int] = []
    try:
        await _start_scope_safety_task(
            service,
            task_id=task_id,
            step_id=step_id,
            observed_at=observed_at,
            producer=producer,
            label="cost",
        )
        event.listen(engine.sync_engine, "before_cursor_execute", capture_conclusion_sql)
        try:
            for index in range(tool_calls):
                label = f"cost-{index}"
                tool_call_id = new_id()
                service.record_batch(
                    _scope_safety_tool_call_batch(
                        task_id=task_id,
                        step_id=step_id,
                        tool_call_id=tool_call_id,
                        call_seq=index + 1,
                        producer=producer,
                        observed_at=observed_at,
                        label=label,
                    )
                )
                await service.flush_task(task_id)
                service.record_batch(
                    _scope_safety_evidence_batch(
                        task_id=task_id,
                        step_id=step_id,
                        tool_call_id=tool_call_id,
                        producer=producer,
                        observed_at=observed_at,
                        label=label,
                        with_observed_effect=True,
                    )
                )
                await service.flush_task(task_id)
                assessed_subjects.clear()
                conclusion_statements["count"] = 0
                await service.assess_operations(now=observed_at + timedelta(minutes=index + 1))
                subjects_per_round.append(len(assessed_subjects))
                statements_per_round.append(conclusion_statements["count"])
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", capture_conclusion_sql)
    finally:
        await service.stop()
        await engine.dispose()

    # Every trigger carries evidence for exactly one ToolCall, so exactly one
    # scope-safety conclusion set is recomputed no matter how long the Task is.
    assert subjects_per_round == [1] * tool_calls
    # And the conclusion write path did not grow to replace the wide re-judge.
    assert max(statements_per_round) == min(statements_per_round)


@pytest.mark.anyio
async def test_late_scope_evidence_reassesses_only_its_own_tool_call(tmp_path) -> None:
    """P9-M2: a converged ToolCall keeps its conclusions with no rewrite.

    ``scope-safety`` stamps ``as_of``/``asserted_at`` with the assessment time,
    so a re-judged conclusion is never absorbed by ``_persist_assessment``'s
    dedupe even when nothing changed: it appends a fresh assertion and a fresh
    ``ansich_scope_conclusions`` row every trigger. Counting those rows is
    therefore a direct read of whether the untouched subject was re-judged.
    """

    engine, session_factory = _scope_safety_service(tmp_path, "scope-safety-incremental-window.db")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(
        session_factory,
        flush_interval_ms=60_000,
        projector_poll_interval_ms=60_000,
        operations_assessment_interval_ms=60_000,
    )
    only_test_driven_assessments(service)
    await service.start()
    task_id, step_id = new_id(), new_id()
    converged_id, late_id = new_id(), new_id()
    observed_at = datetime(2026, 8, 19, 11, tzinfo=UTC)
    producer = Producer(name="scope-safety-window", version="1", instance_id="test")

    async def _scope_safety_state(session, tool_call_id: str) -> tuple[int, int, tuple[str, ...]]:
        assertions = await session.scalar(
            select(func.count())
            .select_from(AnsichBeliefAssertionRow)
            .where(
                AnsichBeliefAssertionRow.subject_id == tool_call_id,
                AnsichBeliefAssertionRow.field_name.like("scope_safety:%"),
            )
        )
        conclusions = await session.scalar(select(func.count()).select_from(AnsichScopeConclusionRow).where(AnsichScopeConclusionRow.tool_call_id == tool_call_id))
        current = tuple(
            (
                await session.execute(
                    select(AnsichCurrentBeliefRow.assertion_id)
                    .where(
                        AnsichCurrentBeliefRow.subject_id == tool_call_id,
                        AnsichCurrentBeliefRow.field_name.like("scope_safety:%"),
                    )
                    .order_by(AnsichCurrentBeliefRow.field_name)
                )
            ).scalars()
        )
        return int(assertions or 0), int(conclusions or 0), current

    try:
        await _start_scope_safety_task(
            service,
            task_id=task_id,
            step_id=step_id,
            observed_at=observed_at,
            producer=producer,
            label="window",
        )
        for index, (tool_call_id, label) in enumerate(((converged_id, "window-converged"), (late_id, "window-late"))):
            service.record_batch(
                _scope_safety_tool_call_batch(
                    task_id=task_id,
                    step_id=step_id,
                    tool_call_id=tool_call_id,
                    call_seq=index + 1,
                    producer=producer,
                    observed_at=observed_at,
                    label=label,
                )
            )
            await service.flush_task(task_id)
            service.record_batch(
                _scope_safety_evidence_batch(
                    task_id=task_id,
                    step_id=step_id,
                    tool_call_id=tool_call_id,
                    producer=producer,
                    observed_at=observed_at,
                    label=label,
                    # The late subject stays unverified until its observed
                    # effect lands in a later watermark window.
                    with_observed_effect=tool_call_id == converged_id,
                )
            )
            await service.flush_task(task_id)
        await service.assess_operations(now=observed_at)

        async with session_factory() as session:
            converged_before = await _scope_safety_state(session, converged_id)
            late_before = await _scope_safety_state(session, late_id)
        unverified_before = await service.get_current_belief(late_id, "scope_safety:unverified_effect")

        service.record(
            _scope_safety_observed_effect(
                task_id=task_id,
                step_id=step_id,
                tool_call_id=late_id,
                producer=producer,
                observed_at=observed_at,
                label="window-late",
            )
        )
        await service.flush_task(task_id)
        await service.assess_operations(now=observed_at + timedelta(minutes=5))

        async with session_factory() as session:
            converged_after = await _scope_safety_state(session, converged_id)
            late_after = await _scope_safety_state(session, late_id)
        unverified_after = await service.get_current_belief(late_id, "scope_safety:unverified_effect")
    finally:
        await service.stop()
        await engine.dispose()

    # The converged subject received no new evidence: same assertion count,
    # same conclusion rows, same selected assertions.
    assert converged_before == (4, 4, converged_before[2])
    assert converged_after == converged_before
    # The subject the new evidence belongs to is re-judged and its conclusion
    # actually moves.
    assert late_before[0] == 4
    assert late_after[0] > late_before[0]
    assert late_after[2] != late_before[2]
    assert unverified_before is not None and unverified_before.value["value"] == "present"
    assert unverified_after is not None and unverified_after.value["value"] == "cleared"


@pytest.mark.anyio
async def test_first_scope_safety_assessment_and_replay_assess_every_tool_call(tmp_path) -> None:
    """P9-M2: the incremental window must reset with the conclusions it guards.

    A Task whose first assessment happens after several ToolCalls already
    carry evidence has no previous window, so the cold-start path judges all of
    them. ``rebuild_projections()`` deletes the conclusions, so whatever records
    the previous window has to be deleted with them or the replay would rebuild
    an empty projection.
    """

    engine, session_factory = _scope_safety_service(tmp_path, "scope-safety-cold-start.db")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(
        session_factory,
        flush_interval_ms=60_000,
        projector_poll_interval_ms=60_000,
        operations_assessment_interval_ms=60_000,
    )
    only_test_driven_assessments(service)
    await service.start()
    task_id, step_id = new_id(), new_id()
    first_id, second_id = new_id(), new_id()
    observed_at = datetime(2026, 8, 19, 12, tzinfo=UTC)
    producer = Producer(name="scope-safety-cold", version="1", instance_id="test")

    async def _conclusion_counts(session) -> dict[str, int]:
        return {tool_call_id: int(await session.scalar(select(func.count()).select_from(AnsichScopeConclusionRow).where(AnsichScopeConclusionRow.tool_call_id == tool_call_id)) or 0) for tool_call_id in (first_id, second_id)}

    try:
        await _start_scope_safety_task(
            service,
            task_id=task_id,
            step_id=step_id,
            observed_at=observed_at,
            producer=producer,
            label="cold",
        )
        for index, (tool_call_id, label) in enumerate(((first_id, "cold-first"), (second_id, "cold-second"))):
            service.record_batch(
                _scope_safety_tool_call_batch(
                    task_id=task_id,
                    step_id=step_id,
                    tool_call_id=tool_call_id,
                    call_seq=index + 1,
                    producer=producer,
                    observed_at=observed_at,
                    label=label,
                )
            )
            await service.flush_task(task_id)
            service.record_batch(
                _scope_safety_evidence_batch(
                    task_id=task_id,
                    step_id=step_id,
                    tool_call_id=tool_call_id,
                    producer=producer,
                    observed_at=observed_at,
                    label=label,
                    with_observed_effect=True,
                )
            )
            await service.flush_task(task_id)
        # Nothing has been assessed yet: this is the cold-start path.
        await service.assess_operations(now=observed_at)
        async with session_factory() as session:
            cold_start_counts = await _conclusion_counts(session)

        await service.rebuild_projections()
        async with session_factory() as session:
            replayed_counts = await _conclusion_counts(session)
    finally:
        await service.stop()
        await engine.dispose()

    assert cold_start_counts == {first_id: 4, second_id: 4}
    assert replayed_counts == cold_start_counts


@pytest.mark.anyio
async def test_absorbed_low_watermark_window_survives_an_evaluation_rollback(tmp_path) -> None:
    """P9-M2 fix round 1: the widened window must outlive a rolled-back evaluation.

    Claim-time absorption flips the group's lower jobs to ``completed`` before
    the evaluation runs, so a rollback leaves them unclaimable. If the widening
    that pulled their evidence into the window lived only in the evaluation, the
    retry — which now claims the high sibling alone — would compute a narrower
    window and skip that evidence permanently. That is the same hole that
    disqualified "max completed job watermark" as the lower bound, one size
    smaller.

    Reaching it needs an Observation that committed *after* a higher watermark
    was already settled, which a single in-process writer cannot produce: it
    assigns ``ingest_seq`` at insert and commits in that order. The durable mark
    is therefore seeded directly to the value a concurrent writer's late commit
    would have left behind; everything after that is the ordinary pipeline.
    """

    engine, session_factory = _scope_safety_service(tmp_path, "scope-safety-rollback-window.db")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(
        session_factory,
        flush_interval_ms=60_000,
        # The blocking subject's projection never settles, so every later flush
        # spends this whole budget waiting. It still has to comfortably exceed
        # the persist step itself, which shares the same deadline - a budget
        # tight enough to expire mid-persist drops the taken items outright.
        terminal_flush_timeout_ms=2_000,
        projector_poll_interval_ms=5,
        operations_assessment_interval_ms=60_000,
    )
    # This test choreographs exactly which evidence window each scope-safety
    # evaluation sees: it seeds the durable mark by hand and asserts on the
    # conclusions and the mark afterwards. The projector loop's first-iteration
    # assessment ignores the 60s cadence, so under suite load it can claim the
    # assessor jobs mid-choreography and evaluate a window the test never
    # arranged. Every assessment here is the test's own.
    only_test_driven_assessments(service)
    await service.start()
    task_id, step_id = new_id(), new_id()
    settled_id, late_id, blocking_id = new_id(), new_id(), new_id()
    observed_at = datetime(2026, 8, 19, 13, tzinfo=UTC)
    producer = Producer(name="scope-safety-rollback", version="1", instance_id="test")

    async def _ingest_seq(session, obs_id: str) -> int:
        ingest_seq = await session.scalar(select(AnsichObservationRow.ingest_seq).where(AnsichObservationRow.obs_id == obs_id))
        assert ingest_seq is not None, f"Observation {obs_id} was never persisted"
        return int(ingest_seq)

    try:
        await _start_scope_safety_task(
            service,
            task_id=task_id,
            step_id=step_id,
            observed_at=observed_at,
            producer=producer,
            label="rollback",
        )
        # Both the settled and the late ToolCall exist up front, so the late
        # subject's own evidence projects and earns its own assessor jobs -
        # the ones the claim will absorb.
        service.record_batch(
            _scope_safety_tool_call_batch(
                task_id=task_id,
                step_id=step_id,
                tool_call_id=settled_id,
                call_seq=1,
                producer=producer,
                observed_at=observed_at,
                label="rollback-settled",
            )
            + _scope_safety_tool_call_batch(
                task_id=task_id,
                step_id=step_id,
                tool_call_id=late_id,
                call_seq=2,
                producer=producer,
                observed_at=observed_at,
                label="rollback-late",
            )
        )
        await service.flush_task(task_id)
        service.record_batch(
            _scope_safety_evidence_batch(
                task_id=task_id,
                step_id=step_id,
                tool_call_id=settled_id,
                producer=producer,
                observed_at=observed_at,
                label="rollback-settled",
                with_observed_effect=True,
            )
        )
        await service.flush_task(task_id)
        await service.assess_operations(now=observed_at)

        late_batch = _scope_safety_evidence_batch(
            task_id=task_id,
            step_id=step_id,
            tool_call_id=late_id,
            producer=producer,
            observed_at=observed_at,
            label="rollback-late",
            with_observed_effect=True,
        )
        service.record_batch(late_batch)
        await service.flush_task(task_id)
        # The blocking subject has no ToolCall projection yet, so assessing it
        # raises _ProjectionDependencyPending and rolls the evaluation back.
        service.record_batch(
            _scope_safety_evidence_batch(
                task_id=task_id,
                step_id=step_id,
                tool_call_id=blocking_id,
                producer=producer,
                observed_at=observed_at,
                label="rollback-blocking",
                with_observed_effect=False,
            )
        )
        await service.flush_task(task_id)
        await anyio.sleep(0.3)
        trigger = _scope_safety_observed_effect(
            task_id=task_id,
            step_id=step_id,
            tool_call_id=settled_id,
            producer=producer,
            observed_at=observed_at,
            label="rollback-trigger",
        )
        service.record(trigger)
        await service.flush_task(task_id)
        await anyio.sleep(0.3)

        async with session_factory() as session:
            late_last_seq = await _ingest_seq(session, late_batch[-1].obs_id)
            trigger_seq = await _ingest_seq(session, trigger.obs_id)
        # Simulate the concurrent writer: the mark already covers the late
        # subject's evidence, which was invisible when it advanced.
        async with session_factory() as session, session.begin():
            mark = await session.get(
                AnsichAssessorWatermarkRow,
                (task_id, "scope-safety", "1.0.0"),
            )
            assert mark is not None and mark.evidence_watermark < late_last_seq
            mark.evidence_watermark = late_last_seq

        await service.assess_operations(now=observed_at + timedelta(minutes=1))
        async with session_factory() as session:
            rolled_back_conclusions = await session.scalar(select(func.count()).select_from(AnsichScopeConclusionRow).where(AnsichScopeConclusionRow.tool_call_id == late_id))

        # Self-heal: the blocking subject's ToolCall lands, so the retry can
        # commit.
        service.record_batch(
            _scope_safety_tool_call_batch(
                task_id=task_id,
                step_id=step_id,
                tool_call_id=blocking_id,
                call_seq=3,
                producer=producer,
                observed_at=observed_at,
                label="rollback-blocking",
            )
        )
        await service.flush_task(task_id)
        await anyio.sleep(0.5)
        await service.assess_operations(now=observed_at + timedelta(minutes=2))

        async with session_factory() as session:
            late_conclusions = await session.scalar(select(func.count()).select_from(AnsichScopeConclusionRow).where(AnsichScopeConclusionRow.tool_call_id == late_id))
            settled_conclusions = await session.scalar(select(func.count()).select_from(AnsichScopeConclusionRow).where(AnsichScopeConclusionRow.tool_call_id == settled_id))
            final_mark = await session.get(
                AnsichAssessorWatermarkRow,
                (task_id, "scope-safety", "1.0.0"),
            )
            final_watermark = None if final_mark is None else final_mark.evidence_watermark
    finally:
        await service.stop()
        await engine.dispose()

    # The first evaluation rolled back, so nothing was written for the late
    # subject yet - that is the state the retry has to recover from.
    assert rolled_back_conclusions == 0
    # The retry claims the high sibling alone; the absorbed low siblings are
    # already completed, so only a durable widening can still cover them.
    assert late_conclusions == 4
    # F10-10 hypothesis (c)'s named tooth: count the *converged* subject too,
    # not just the late one. Eight is the honest number here and it refutes the
    # hypothesis in this shape -- the settled ToolCall carries the trigger's own
    # ``effect.observed``, so the retry's window names it for a real reason and
    # judges it a second time. What this test cannot exhibit is a converged
    # ToolCall pulled into the window by nothing but a lowered mark; that needs
    # a job whose watermark lands *under* an already-advanced mark, which is
    # ``test_a_dependency_deferred_job_below_the_mark_re_judges_its_band_once``.
    assert settled_conclusions == 8
    assert final_watermark == trigger_seq


def _scope_snapshot_observation(
    *,
    task_id: str,
    scope_id: str,
    obs_id: str,
    producer: Producer,
    observed_at: datetime,
    label: str,
    external_ref_hash: str,
    parent_scope_id: str | None = None,
) -> ObservationEnvelope:
    """A ``scope.snapshotted`` that names no ToolCall and no ``within_scope``.

    Two properties make it a convenient carrier for the "late job below the
    mark" shape. It is scope-safety evidence, so projecting it mints a
    scope-safety assessor job at its own ``ingest_seq``; and it names no
    ToolCall, so while it sits unprojected it does *not* poison the evidence
    windows that span it. It is NOT the only carrier: an ``authorization.*``/
    ``effect.*`` row deferred on its *Scope* (its ToolCall Entity present)
    commits in every spanning evaluation just the same -- see
    ``_scope_deferred_authorization`` below, the PB5 test's fixture, and the
    corrected F10-10 addendum. Only a row deferred on its *ToolCall* rolls
    spanning evaluations back.
    """

    scope = ScopeDescriptor(
        scope_id=scope_id,
        scope_kind="workspace",
        external_ref_hash=external_ref_hash,
        display_label=label,
        parent_scope_id=parent_scope_id,
        created_obs_id=obs_id,
    )
    return ObservationEnvelope(
        obs_id=obs_id,
        kind="scope.snapshotted",
        occurred_at=observed_at,
        task_id=task_id,
        subject_type="scope",
        subject_id=scope_id,
        producer=producer,
        source_event_id=f"{label}:scope:snapshotted",
        correlation_id=label,
        payload={"scope": scope.model_dump(mode="json")},
    )


#: Availability injections. Both are fixture constants rather than offsets from
#: a live clock, so no decision in these tests can land between a simulated and
#: a real ``now``: ``_UNAVAILABLE_AT`` is far enough ahead that nothing can make
#: a held job claimable by accident, ``_AVAILABLE_AT`` far enough behind that
#: nothing can keep a released one held.
_UNAVAILABLE_AT = datetime(2099, 1, 1, tzinfo=UTC)
_AVAILABLE_AT = datetime(2026, 1, 1, tzinfo=UTC)


async def _await_scope_safety_job(session_factory, watermark: int, *, timeout: float = 10.0) -> None:
    """Wait until the scope-safety job at ``watermark`` has been minted.

    The projector's dependency retry is a 250ms backoff, not a completion
    signal, so a fixed sleep here turns suite load into a test failure -- the
    exact shape F10-10 keeps re-diagnosing. The condition itself is
    deterministic (the durable job row either exists or does not); only its
    arrival time is not, so poll the row and keep the wait a lower bound.
    """

    deadline = anyio.current_time() + timeout
    while True:
        async with session_factory() as session:
            found = await session.scalar(
                select(AnsichAssessorJobRow.job_id).where(
                    AnsichAssessorJobRow.assessor_name == "scope-safety",
                    AnsichAssessorJobRow.evidence_watermark == watermark,
                )
            )
        if found is not None:
            return
        if anyio.current_time() >= deadline:
            raise AssertionError(f"no scope-safety job at watermark {watermark} after {timeout}s")
        await anyio.sleep(0.02)


@pytest.mark.anyio
async def test_a_dependency_deferred_job_below_the_mark_re_judges_its_band_once(tmp_path) -> None:
    """F10-10 hypothesis (c) plus PB5: settle the band once, then close it.

    The mechanism, on the ordinary self-heal path. A Scope observation whose
    parent Scope has not landed is deferred by ``_project_safety``, so its
    scope-safety job is minted only once the parent arrives -- and by then a
    higher watermark has settled the mark above it. Claiming that lone job
    widens the mark down below its own watermark (which absorption requires).

    Three behaviours are separable here and the assertions below pin all three:

    * Without the pre-claim restore the advance raises the mark back only to
      the job's own low watermark, so the mark ends a whole band below the
      evidence it has actually judged and *every* later trigger re-opens that
      band -- an extra Assertion and an extra ``ansich_scope_conclusions`` row
      per converged ToolCall each time, because scope-safety stamps ``as_of``
      with the assessment time and ``_persist_assessment``'s dedupe cannot
      absorb it.
    * With the restore alone the band closes, but this evaluation has still
      read only up to its own watermark. That truncation is what PB5 names: the
      conclusions it derives are missing every piece of evidence above the low
      watermark, and now nothing ever revisits them.
    * With PB5 the evaluation reads up to the pre-claim mark instead, so the
      band is re-judged **once**, on complete evidence, by the job that lowered
      it -- and then stays closed.

    Domain: a dependency-deferred arrival below an advanced mark. Ordinary
    absorption plus an evaluation rollback is
    ``test_absorbed_low_watermark_window_survives_an_evaluation_rollback``; the
    truncated-conclusion damage PB5 prevents is
    ``test_a_truncated_late_evaluation_cannot_leave_a_belief_regressed``; the
    stale-claim drop is ``test_a_dropped_assessor_completion_rolls_back_...``.

    A ``scope.snapshotted`` carrier is used because it names no ToolCall, which
    keeps this test's arithmetic about the *band* rather than about the late
    job's own subject. It is **not** the only carrier for the shape: a row
    deferred on its Scope rather than its ToolCall (``_project_authorization_snapshot``
    checks the ToolCall first) also commits in every assessment that spans it,
    so the mark advances over it too -- that is the carrier the PB5 test uses.
    """

    engine, session_factory = _scope_safety_service(tmp_path, "scope-safety-deferred-below-mark.db")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(
        session_factory,
        flush_interval_ms=60_000,
        # The deferred Scope observation cannot settle until its parent lands,
        # so every flush until then spends this whole budget waiting.
        terminal_flush_timeout_ms=2_000,
        projector_poll_interval_ms=5,
        operations_assessment_interval_ms=60_000,
    )
    # Every assessment here is the test's own: the choreography depends on
    # exactly which evidence window each evaluation sees.
    only_test_driven_assessments(service)
    await service.start()
    task_id, step_id = new_id(), new_id()
    converged_id, trigger_id = new_id(), new_id()
    parent_scope_id, child_scope_id = new_id(), new_id()
    child_scope_obs_id, parent_scope_obs_id = new_id(), new_id()
    # Past-dated on purpose (global clock rule).
    observed_at = datetime(2026, 7, 1, 13, tzinfo=UTC)
    producer = Producer(name="scope-safety-deferred", version="1", instance_id="test")

    async def _ingest_seq(obs_id: str) -> int:
        async with session_factory() as session:
            ingest_seq = await session.scalar(select(AnsichObservationRow.ingest_seq).where(AnsichObservationRow.obs_id == obs_id))
        assert ingest_seq is not None, f"Observation {obs_id} was never persisted"
        return int(ingest_seq)

    async def _mark() -> int | None:
        async with session_factory() as session:
            row = await session.get(AnsichAssessorWatermarkRow, (task_id, "scope-safety", "1.0.0"))
        return None if row is None else row.evidence_watermark

    async def _conclusions(tool_call_id: str) -> int:
        async with session_factory() as session:
            return int(await session.scalar(select(func.count()).select_from(AnsichScopeConclusionRow).where(AnsichScopeConclusionRow.tool_call_id == tool_call_id)) or 0)

    async def _set_availability(watermark: int, available_at: datetime) -> None:
        async with session_factory() as session, session.begin():
            result = await session.execute(
                update(AnsichAssessorJobRow)
                .where(
                    AnsichAssessorJobRow.assessor_name == "scope-safety",
                    AnsichAssessorJobRow.evidence_watermark == watermark,
                )
                .values(available_at=available_at)
            )
        assert result.rowcount == 1, f"expected exactly one scope-safety job at watermark {watermark}"

    try:
        await _start_scope_safety_task(
            service,
            task_id=task_id,
            step_id=step_id,
            observed_at=observed_at,
            producer=producer,
            label="deferred",
        )
        service.record_batch(
            _scope_safety_tool_call_batch(
                task_id=task_id,
                step_id=step_id,
                tool_call_id=converged_id,
                call_seq=1,
                producer=producer,
                observed_at=observed_at,
                label="deferred-converged",
            )
            + _scope_safety_tool_call_batch(
                task_id=task_id,
                step_id=step_id,
                tool_call_id=trigger_id,
                call_seq=2,
                producer=producer,
                observed_at=observed_at,
                label="deferred-trigger",
            )
        )
        await service.flush_task(task_id)

        # (1) The Scope observation whose parent has not landed. It stays
        # ``pending`` and mints no assessor job at all while it waits.
        service.record(
            _scope_snapshot_observation(
                task_id=task_id,
                scope_id=child_scope_id,
                obs_id=child_scope_obs_id,
                producer=producer,
                observed_at=observed_at,
                label="deferred-child",
                external_ref_hash="c" * 64,
                parent_scope_id=parent_scope_id,
            )
        )
        await service.flush_task(task_id)
        await anyio.sleep(0.3)
        async with session_factory() as session:
            assert await session.scalar(select(func.count()).select_from(AnsichAssessorJobRow).where(AnsichAssessorJobRow.assessor_name == "scope-safety")) == 0

        # (2) Evidence at higher sequences, then the parent Scope, which frees
        # the deferred child to project and mint its own low-watermark job.
        converged_batch = _scope_safety_evidence_batch(
            task_id=task_id,
            step_id=step_id,
            tool_call_id=converged_id,
            producer=producer,
            observed_at=observed_at,
            label="deferred-converged",
            with_observed_effect=True,
        )
        service.record_batch(converged_batch)
        await service.flush_task(task_id)
        service.record(
            _scope_snapshot_observation(
                task_id=task_id,
                scope_id=parent_scope_id,
                obs_id=parent_scope_obs_id,
                producer=producer,
                observed_at=observed_at,
                label="deferred-parent",
                external_ref_hash="d" * 64,
            )
        )
        await service.flush_task(task_id)

        deferred_seq = await _ingest_seq(child_scope_obs_id)
        converged_seq = await _ingest_seq(converged_batch[-1].obs_id)
        parent_seq = await _ingest_seq(parent_scope_obs_id)
        assert deferred_seq < converged_seq < parent_seq
        await _await_scope_safety_job(session_factory, deferred_seq)

        # (3) Hold the late job back for one assessment. Without this the claim
        # would absorb it into the parent Scope's own higher-watermark job and
        # never evaluate it alone -- which is the arrangement, not the bug: the
        # real system separates them by the projector's own retry timing.
        await _set_availability(deferred_seq, _UNAVAILABLE_AT)
        await service.assess_operations(now=observed_at)
        assert await _mark() == parent_seq
        assert await _conclusions(converged_id) == 4

        # (4) The late job is claimed alone, at a watermark below the mark. Its
        # own evidence names no ToolCall, but the window its widening opened
        # does -- and PB5 makes this evaluation read to the pre-claim mark, so
        # the band is settled here, on complete evidence.
        await _set_availability(deferred_seq, _AVAILABLE_AT)
        await service.assess_operations(now=observed_at + timedelta(minutes=1))
        mark_after_late_job = await _mark()
        converged_after_late_job = await _conclusions(converged_id)

        # (5) One new trigger, on a ToolCall of its own.
        trigger = _scope_safety_observed_effect(
            task_id=task_id,
            step_id=step_id,
            tool_call_id=trigger_id,
            producer=producer,
            observed_at=observed_at,
            label="deferred-trigger",
        )
        service.record(trigger)
        await service.flush_task(task_id)
        await anyio.sleep(0.3)
        trigger_seq = await _ingest_seq(trigger.obs_id)
        await service.assess_operations(now=observed_at + timedelta(minutes=2))

        converged_after_first_trigger = await _conclusions(converged_id)
        trigger_conclusions = await _conclusions(trigger_id)
        mark_after_first_trigger = await _mark()

        # (6) A second trigger on the same subject. Nothing re-opens the band
        # again: the re-judge in (4) is one, not one per trigger.
        second_trigger = _scope_safety_observed_effect(
            task_id=task_id,
            step_id=step_id,
            tool_call_id=trigger_id,
            producer=producer,
            observed_at=observed_at,
            label="deferred-trigger-again",
        )
        service.record(second_trigger)
        await service.flush_task(task_id)
        await anyio.sleep(0.3)
        second_trigger_seq = await _ingest_seq(second_trigger.obs_id)
        await service.assess_operations(now=observed_at + timedelta(minutes=3))

        converged_final = await _conclusions(converged_id)
        final_mark = await _mark()
    finally:
        await service.stop()
        await engine.dispose()

    # The (c) mechanism: the late job settles the mark at the watermark it
    # evaluated *or* the one the claim found, whichever is higher. Without the
    # restore this is ``deferred_seq`` and the mark has un-judged the band above
    # it.
    assert mark_after_late_job == parent_seq
    # PB5: the band the widening opened is judged by the job that opened it,
    # with evidence complete to the pre-claim mark. Without PB5 this stays at
    # four -- the band is closed by the restore while nothing ever looked at it.
    assert converged_after_late_job == 8
    # The safe half, unchanged: the trigger's own subject is judged.
    assert trigger_conclusions == 4
    # Bounded, and that is the whole difference from the pre-fix behaviour:
    # neither the first trigger nor the second re-opens the band, so the
    # converged ToolCall is re-judged exactly once, not once per trigger.
    assert converged_after_first_trigger == 8
    assert converged_final == 8
    assert (mark_after_first_trigger, final_mark) == (trigger_seq, second_trigger_seq)


class _AssessorWorkers:
    """Two independent backends over one SQLite file, plus a read handle each."""

    def __init__(self, first: SqlAnsichBackend, second: SqlAnsichBackend, sessions: async_sessionmaker) -> None:
        self.a = first
        self.b = second
        self.sessions = sessions


@contextlib.asynccontextmanager
async def _two_assessor_workers(tmp_path: Path, name: str) -> AsyncIterator[_AssessorWorkers]:
    """Two engines, two backends, one database -- two real workers.

    Separate engines rather than a shared session factory, because the subject
    is two *workers*: each mints its own process-lifetime ``lease_owner``, which
    is precisely what a completion CAS has to see through. SQLite renders
    ``skip_locked`` as empty and shows both backends the same row, which makes
    it the deterministic substrate for a takeover script (the same reasoning as
    ``tests/ansich/test_lease_cas.py``).
    """

    database_path = tmp_path / name
    engines = [create_async_engine(f"sqlite+aiosqlite:///{database_path}") for _ in range(2)]
    for engine in engines:

        @event.listens_for(engine.sync_engine, "connect")
        def _enable_foreign_keys(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    async with engines[0].begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = [async_sessionmaker(engine, expire_on_commit=False) for engine in engines]
    try:
        yield _AssessorWorkers(
            SqlAnsichBackend(sessions[0]),
            SqlAnsichBackend(sessions[1]),
            sessions[0],
        )
    finally:
        for engine in engines:
            await engine.dispose()


def _take_over_the_scope_safety_claim(workers: _AssessorWorkers, record: dict[str, object], *, before_takeover=None):
    """Splice a takeover between A's assessor claim and A's evaluation.

    The claim and the evaluation are two transactions, and SQLite has one
    writer, so B cannot claim anything while A holds the evaluation open. The
    takeover therefore rides on A's own claim call, exactly as the projection
    side does in ``test_lease_cas.py``.

    ``before_takeover`` runs in that same gap, which is where a scenario puts
    work that must land *after* A claimed and *before* B did -- a new low job
    arriving is the case this exists for.
    """

    original_claim = workers.a._claim_assessor_job

    async def claim_then_lose_the_lease():
        claim = await original_claim()
        if claim is not None and claim.assessor_name == "scope-safety" and "a" not in record:
            record["a"] = claim
            if before_takeover is not None:
                await before_takeover()
            async with workers.sessions() as session, session.begin():
                await session.execute(update(AnsichAssessorJobRow).where(AnsichAssessorJobRow.job_id == claim.job_id).values(lease_expires_at=_EXPIRED_LEASE_AT))
            record["b"] = await workers.b._claim_assessor_job()
        return claim

    workers.a._claim_assessor_job = claim_then_lose_the_lease  # type: ignore[method-assign]
    return record


#: Injected lease expiry (global clock rule): a lease is expired by writing a
#: timestamp that is in the past under any clock, never by moving a fake one.
_EXPIRED_LEASE_AT = datetime(2026, 1, 1, tzinfo=UTC)
_ASSESSOR_TASK_OBSERVED_AT = datetime(2026, 7, 1, 14, tzinfo=UTC)


async def _drain_projections(backend: SqlAnsichBackend) -> None:
    while await backend.project_pending(limit=50):
        pass


async def _run_assessors(backend: SqlAnsichBackend, *, now: datetime, limit: int = 500) -> int:
    return await backend._process_assessor_jobs(
        now=now,
        incomplete_tasks=frozenset(),
        global_loss=False,
        limit=limit,
    )


async def _scope_safety_mark(sessions: async_sessionmaker, task_id: str) -> int | None:
    async with sessions() as session:
        row = await session.get(AnsichAssessorWatermarkRow, (task_id, "scope-safety", "1.0.0"))
    return None if row is None else row.evidence_watermark


async def _scope_conclusion_count(sessions: async_sessionmaker, tool_call_id: str) -> int:
    async with sessions() as session:
        return int(await session.scalar(select(func.count()).select_from(AnsichScopeConclusionRow).where(AnsichScopeConclusionRow.tool_call_id == tool_call_id)) or 0)


@pytest.mark.anyio
async def test_a_dropped_assessor_completion_rolls_back_its_whole_evaluation(tmp_path) -> None:
    """Controller ruling PB4: on the assessor path the drop costs everything.

    A dropped completion means the lease expired and somebody else owns the job
    now. On the projection path that is safe to leave committed -- projectors
    are idempotent and the new owner converges on the same rows (RB4(5)). The
    assessor path has one write idempotency cannot repair: the evidence mark,
    which is not a projection but a *claim about what has been judged*, and
    which the new owner reads as the lower bound of its own window. So the
    whole evaluation goes back and the new owner redoes it in full.

    Domain: the stale-drop half of the assessor watermark work. The composed
    case, where the stale advance also erases the new owner's claim-time
    widening, is ``test_a_stale_evaluation_cannot_erase_the_new_owners_window``.
    """

    async with _two_assessor_workers(tmp_path, "scope-safety-pb4-drop.db") as workers:
        task_id, step_id, tool_call_id = new_id(), new_id(), new_id()
        producer = Producer(name="scope-safety-pb4", version="1", instance_id="test")
        await workers.a.persist_and_project(
            [
                ObservationEnvelope.task_lifecycle(
                    kind="task.created",
                    task_id=task_id,
                    source_kind="deerflow_run",
                    source_id="pb4-drop",
                    occurred_at=_ASSESSOR_TASK_OBSERVED_AT,
                    source_event_id="pb4-drop:task:created",
                ),
                ObservationEnvelope(
                    kind="step.started",
                    occurred_at=_ASSESSOR_TASK_OBSERVED_AT,
                    task_id=task_id,
                    step_id=step_id,
                    subject_type="step",
                    subject_id=step_id,
                    producer=producer,
                    source_event_id="pb4-drop:step:started",
                    correlation_id="pb4-drop",
                    payload={"step_seq": 1, "actor_kind": "lead_agent"},
                ),
                *_scope_safety_tool_call_batch(
                    task_id=task_id,
                    step_id=step_id,
                    tool_call_id=tool_call_id,
                    call_seq=1,
                    producer=producer,
                    observed_at=_ASSESSOR_TASK_OBSERVED_AT,
                    label="pb4-drop",
                ),
            ]
        )
        await _drain_projections(workers.a)
        # Drain the assessors ``tool.issued`` mints (repetition/frequency) so the
        # only claimable jobs left are scope-safety and the takeover below is
        # unambiguous about which row it is racing.
        await _run_assessors(workers.a, now=_ASSESSOR_TASK_OBSERVED_AT)

        evidence = _scope_safety_evidence_batch(
            task_id=task_id,
            step_id=step_id,
            tool_call_id=tool_call_id,
            producer=producer,
            observed_at=_ASSESSOR_TASK_OBSERVED_AT,
            label="pb4-drop",
            with_observed_effect=True,
        )
        await workers.a.persist_and_project(list(evidence))
        await _drain_projections(workers.a)

        record: dict[str, object] = {}
        _take_over_the_scope_safety_claim(workers, record)
        await _run_assessors(workers.a, now=_ASSESSOR_TASK_OBSERVED_AT, limit=1)

        a_claim = record["a"]
        b_claim = record["b"]
        assert b_claim is not None
        assert b_claim.job_id == a_claim.job_id
        assert b_claim.lease_generation == a_claim.lease_generation + 1

        # Nothing A's evaluation wrote may survive: not the conclusions, not the
        # Assertions behind them, and above all not the mark.
        assert await _scope_conclusion_count(workers.sessions, tool_call_id) == 0
        assert await _scope_safety_mark(workers.sessions, task_id) is None
        async with workers.sessions() as session:
            assertion_count = await session.scalar(select(func.count()).select_from(AnsichBeliefAssertionRow).where(AnsichBeliefAssertionRow.assessor_name == "scope-safety"))
            error_count = await session.scalar(select(func.count()).select_from(AnsichAssessorErrorRow))
            job = await session.get(AnsichAssessorJobRow, b_claim.job_id)
        assert assertion_count == 0
        # A drop is a change of owner, not a failure of the work: no durable
        # error row, no re-arm, and no attempt charged beyond the two claims.
        assert error_count == 0
        assert job is not None
        assert job.status == "processing"
        assert job.lease_owner == workers.b._lease_owner
        assert job.lease_generation == b_claim.lease_generation
        assert workers.a.stale_completion_count == 1

        # The new owner then produces the outcome, in full and exactly once.
        async with workers.sessions() as session, session.begin():
            await session.execute(update(AnsichAssessorJobRow).where(AnsichAssessorJobRow.job_id == b_claim.job_id).values(lease_expires_at=_EXPIRED_LEASE_AT))
        await _run_assessors(workers.b, now=_ASSESSOR_TASK_OBSERVED_AT, limit=1)

        assert await _scope_conclusion_count(workers.sessions, tool_call_id) == 4
        assert await _scope_safety_mark(workers.sessions, task_id) == a_claim.evidence_watermark
        async with workers.sessions() as session:
            settled = await session.get(AnsichAssessorJobRow, b_claim.job_id)
        assert settled is not None
        assert settled.status == "completed"


@pytest.mark.anyio
async def test_a_stale_evaluation_cannot_erase_the_new_owners_window(tmp_path) -> None:
    """PB4 composed with the pre-claim restore: the reviewer's five steps.

    The interleaving Task 2's review constructed. (i) A claims a group whose
    lowest member sits under the mark, so the claim widens the mark down over
    it. (ii) A's lease expires and B re-claims the surviving job, inheriting
    that widened window as its own lower bound. (iii) A's evaluation finishes
    anyway and its advance -- ``max(its watermark, the mark it found at claim
    time)``, which the hypothesis-(c) restore makes *higher*, not lower --
    would raise the mark back over the band B is about to judge. (iv) B then
    reads its window start from that mark and finds it empty, so the band the
    widening opened is judged by nobody: A left the job to B, and B was told
    there was nothing to do.

    PB4 closes it at the source. A's completion fails its compare-and-set, so
    A's whole transaction goes back -- including the advance -- and the mark B
    inherited from its own claim is still there when B reads it. The two fixes
    have to be checked together precisely because the restore makes a stale
    advance reach further.

    One residual is deliberate and visible in the numbers below: the widening
    itself lives in the *claim's* transaction and survives the rollback (P9-M2
    -- absorption completes the group's lower jobs there too, so a widening
    that rolled back would strand them), while the pre-claim mark A was
    carrying goes back with A's transaction. B's own pre-claim mark is
    therefore the widened value, so B settles at its own low watermark and the
    band re-opens on the next trigger instead of being covered by B. That costs
    one wide re-judge, once -- asserted at the end here so the residual stays a
    measured trade rather than an assumption.

    The absorption variant of this interleaving, where the erased widening
    costs a *first* judgement rather than a re-judge, is
    ``test_a_stale_advance_cannot_settle_a_band_the_new_owner_absorbed``.
    """

    async with _two_assessor_workers(tmp_path, "scope-safety-pb4-window.db") as workers:
        task_id, step_id, tool_call_id = new_id(), new_id(), new_id()
        parent_scope_id, child_scope_id = new_id(), new_id()
        child_scope_obs_id, parent_scope_obs_id = new_id(), new_id()
        producer = Producer(name="scope-safety-pb4-window", version="1", instance_id="test")

        async def _ingest_seq(obs_id: str) -> int:
            async with workers.sessions() as session:
                ingest_seq = await session.scalar(select(AnsichObservationRow.ingest_seq).where(AnsichObservationRow.obs_id == obs_id))
            assert ingest_seq is not None, f"Observation {obs_id} was never persisted"
            return int(ingest_seq)

        async def _set_assessor_availability(watermark: int, available_at: datetime) -> None:
            async with workers.sessions() as session, session.begin():
                result = await session.execute(
                    update(AnsichAssessorJobRow)
                    .where(
                        AnsichAssessorJobRow.assessor_name == "scope-safety",
                        AnsichAssessorJobRow.evidence_watermark == watermark,
                    )
                    .values(available_at=available_at)
                )
            assert result.rowcount == 1, f"expected exactly one scope-safety job at watermark {watermark}"

        await workers.a.persist_and_project(
            [
                ObservationEnvelope.task_lifecycle(
                    kind="task.created",
                    task_id=task_id,
                    source_kind="deerflow_run",
                    source_id="pb4-window",
                    occurred_at=_ASSESSOR_TASK_OBSERVED_AT,
                    source_event_id="pb4-window:task:created",
                ),
                ObservationEnvelope(
                    kind="step.started",
                    occurred_at=_ASSESSOR_TASK_OBSERVED_AT,
                    task_id=task_id,
                    step_id=step_id,
                    subject_type="step",
                    subject_id=step_id,
                    producer=producer,
                    source_event_id="pb4-window:step:started",
                    correlation_id="pb4-window",
                    payload={"step_seq": 1, "actor_kind": "lead_agent"},
                ),
                *_scope_safety_tool_call_batch(
                    task_id=task_id,
                    step_id=step_id,
                    tool_call_id=tool_call_id,
                    call_seq=1,
                    producer=producer,
                    observed_at=_ASSESSOR_TASK_OBSERVED_AT,
                    label="pb4-window",
                ),
            ]
        )
        await _drain_projections(workers.a)
        await _run_assessors(workers.a, now=_ASSESSOR_TASK_OBSERVED_AT)

        # The dependency-deferred Scope observation: invisible to every window
        # while it waits (it names no ToolCall), and the source of the low
        # watermark that makes the later claim widen the mark at all.
        await workers.a.persist_and_project(
            [
                _scope_snapshot_observation(
                    task_id=task_id,
                    scope_id=child_scope_id,
                    obs_id=child_scope_obs_id,
                    producer=producer,
                    observed_at=_ASSESSOR_TASK_OBSERVED_AT,
                    label="pb4-window-child",
                    external_ref_hash="c" * 64,
                    parent_scope_id=parent_scope_id,
                )
            ]
        )
        await _drain_projections(workers.a)
        evidence = _scope_safety_evidence_batch(
            task_id=task_id,
            step_id=step_id,
            tool_call_id=tool_call_id,
            producer=producer,
            observed_at=_ASSESSOR_TASK_OBSERVED_AT,
            label="pb4-window",
            with_observed_effect=True,
        )
        await workers.a.persist_and_project(list(evidence))
        await workers.a.persist_and_project(
            [
                _scope_snapshot_observation(
                    task_id=task_id,
                    scope_id=parent_scope_id,
                    obs_id=parent_scope_obs_id,
                    producer=producer,
                    observed_at=_ASSESSOR_TASK_OBSERVED_AT,
                    label="pb4-window-parent",
                    external_ref_hash="d" * 64,
                )
            ]
        )
        await _drain_projections(workers.a)
        # The deferred projection's own backoff is brought forward rather than
        # waited out: there is no projector loop behind a bare backend.
        async with workers.sessions() as session, session.begin():
            await session.execute(update(AnsichProjectionJobRow).where(AnsichProjectionJobRow.obs_id == child_scope_obs_id).values(available_at=_AVAILABLE_AT))
        await _drain_projections(workers.a)

        deferred_seq = await _ingest_seq(child_scope_obs_id)
        parent_seq = await _ingest_seq(parent_scope_obs_id)

        # The mark settles above the late job, which is held back for exactly
        # one round so it is claimed on its own rather than absorbed here.
        await _set_assessor_availability(deferred_seq, _UNAVAILABLE_AT)
        await _run_assessors(workers.a, now=_ASSESSOR_TASK_OBSERVED_AT)
        assert await _scope_safety_mark(workers.sessions, task_id) == parent_seq
        assert await _scope_conclusion_count(workers.sessions, tool_call_id) == 4

        # A claims the late job **alone**, so its own watermark really is below
        # the mark it found. That is what makes the pre-claim restore
        # load-bearing here rather than arithmetic that happens to agree: A's
        # advance is max(deferred_seq, parent_seq) = parent_seq, and PB5 raises
        # its evaluation watermark to the same value, so a committed stale
        # evaluation would both re-judge the band and settle the mark on it.
        await _set_assessor_availability(deferred_seq, _AVAILABLE_AT)
        record: dict[str, object] = {}
        _take_over_the_scope_safety_claim(workers, record)
        # Each round assesses at its own ``now``: scope-safety stamps ``as_of``
        # with the assessment time, so a round that reuses an earlier one is
        # absorbed by ``_persist_assessment``'s dedupe and writes nothing --
        # which would make "the new owner redid the work" unobservable.
        await _run_assessors(workers.a, now=_ASSESSOR_TASK_OBSERVED_AT + timedelta(minutes=1), limit=1)

        a_claim = record["a"]
        b_claim = record["b"]
        # (i) A claimed the lone late job, which widened the mark down below it.
        assert a_claim.evidence_watermark == deferred_seq
        assert a_claim.pre_claim_watermark == parent_seq
        assert a_claim.evidence_watermark < a_claim.pre_claim_watermark
        assert b_claim is not None
        assert b_claim.job_id == a_claim.job_id
        assert b_claim.pre_claim_watermark == deferred_seq - 1

        # (iv) with PB4: A's advance never lands, so the window B inherited is
        # still open when B reads it, and the band A would have re-judged is
        # still unwritten.
        assert await _scope_safety_mark(workers.sessions, task_id) == deferred_seq - 1
        async with workers.sessions() as session:
            b_window_start = await workers.b._scope_safety_window_start(session, task_id=task_id)
            job = await session.get(AnsichAssessorJobRow, b_claim.job_id)
            error_count = await session.scalar(select(func.count()).select_from(AnsichAssessorErrorRow))
        assert b_window_start == deferred_seq - 1
        assert await _scope_conclusion_count(workers.sessions, tool_call_id) == 4
        assert job is not None
        assert job.status == "processing"
        assert job.lease_owner == workers.b._lease_owner
        assert error_count == 0
        assert workers.a.stale_completion_count == 1

        # The new owner settles the job. Its own pre-claim mark is the widened
        # value -- A's rollback took the higher one with it -- so B's window is
        # the one its own claim opened and nothing above it. That residual is
        # the P9-M2 trade: the widening lives in the claim transaction because
        # absorption does, so a rolled-back evaluation cannot take it back.
        async with workers.sessions() as session, session.begin():
            await session.execute(update(AnsichAssessorJobRow).where(AnsichAssessorJobRow.job_id == b_claim.job_id).values(lease_expires_at=_EXPIRED_LEASE_AT))
        await _run_assessors(workers.b, now=_ASSESSOR_TASK_OBSERVED_AT + timedelta(minutes=2), limit=1)

        assert await _scope_conclusion_count(workers.sessions, tool_call_id) == 4
        assert await _scope_safety_mark(workers.sessions, task_id) == deferred_seq
        async with workers.sessions() as session:
            settled = await session.get(AnsichAssessorJobRow, b_claim.job_id)
        assert settled is not None
        assert settled.status == "completed"

        # And the band re-opens exactly once on the next trigger, then closes:
        # the residual above costs one wide re-judge, not a permanent gap.
        trigger = _scope_safety_observed_effect(
            task_id=task_id,
            step_id=step_id,
            tool_call_id=tool_call_id,
            producer=producer,
            observed_at=_ASSESSOR_TASK_OBSERVED_AT,
            label="pb4-window-trigger",
        )
        await workers.a.persist_and_project([trigger])
        await _drain_projections(workers.a)
        trigger_seq = await _ingest_seq(trigger.obs_id)
        await _run_assessors(workers.a, now=_ASSESSOR_TASK_OBSERVED_AT + timedelta(minutes=3), limit=1)

        assert await _scope_conclusion_count(workers.sessions, tool_call_id) == 8
        assert await _scope_safety_mark(workers.sessions, task_id) == trigger_seq


def _scope_deferred_authorization(
    *,
    task_id: str,
    step_id: str,
    tool_call_id: str,
    scope_id: str,
    obs_id: str,
    producer: Producer,
    observed_at: datetime,
    label: str,
) -> ObservationEnvelope:
    """An ``authorization.evaluated`` whose *Scope* has not been projected.

    ``_project_authorization_snapshot`` checks the ToolCall first and the
    referenced Scopes second, so this row's projection waits while its
    assessment does not: ``_persist_assessment`` only needs the ToolCall
    Entity, which exists. That is what makes it a carrier for "a job minted
    below an already-advanced mark" -- unlike a ToolCall-deferred row, every
    evaluation whose window spans it commits, so the mark really does move past
    it before its own job is ever created.
    """

    snapshot = AuthorizationSnapshot(
        snapshot_id=new_id(),
        tool_call_id=tool_call_id,
        policy_id="incremental-policy",
        policy_version="1",
        policy_hash="d" * 64,
        decision="allowed",
        details_available=True,
        reason_codes=("allowed",),
        resource_scope_ids=(scope_id,),
        evaluated_at=observed_at,
        evidence_obs_ids=(obs_id,),
    )
    return ObservationEnvelope(
        obs_id=obs_id,
        kind="authorization.evaluated",
        occurred_at=observed_at,
        task_id=task_id,
        step_id=step_id,
        subject_type="authorization_snapshot",
        subject_id=snapshot.snapshot_id,
        producer=producer,
        source_event_id=f"{label}:authorization:evaluated",
        correlation_id=label,
        payload={"snapshot": snapshot.model_dump(mode="json")},
    )


@pytest.mark.anyio
async def test_a_truncated_late_evaluation_cannot_leave_a_belief_regressed(tmp_path) -> None:
    """Controller ruling PB5: a late job must not judge on a truncated prefix.

    A job whose watermark sits below the mark reads evidence only up to that
    watermark. For its own subject that is not a narrower window, it is a
    *wrong* one: the ``effect.observed`` that cleared the ToolCall was recorded
    above the low watermark, so the evaluation sees an intended effect with no
    concrete observation and concludes ``unverified_effect: present`` -- a
    verdict that was true once and is not true now. Scope-safety stamps
    ``as_of`` with the assessment time, so that stale verdict is the newest
    assertion and the resolver selects it.

    Before the pre-claim restore this repaired itself by accident: the mark was
    dragged down to the low watermark, so the next trigger re-opened the band
    and re-judged the ToolCall on complete evidence. Restoring the mark closes
    that band, which turns an accidental repair into a permanent regression --
    the reason PB5 exists. Reading to the pre-claim mark instead makes the
    late job's own evaluation complete, and the Belief never moves.

    Domain: the truncation half of a dependency-deferred arrival below an
    advanced mark. Its band-cost half is
    ``test_a_dependency_deferred_job_below_the_mark_re_judges_its_band_once``.
    """

    engine, session_factory = _scope_safety_service(tmp_path, "scope-safety-pb5-truncation.db")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(
        session_factory,
        flush_interval_ms=60_000,
        terminal_flush_timeout_ms=2_000,
        projector_poll_interval_ms=5,
        operations_assessment_interval_ms=60_000,
    )
    only_test_driven_assessments(service)
    await service.start()
    task_id, step_id = new_id(), new_id()
    subject_id, trigger_id = new_id(), new_id()
    scope_id, scope_obs_id = new_id(), new_id()
    deferred_obs_id = new_id()
    observed_at = datetime(2026, 7, 1, 15, tzinfo=UTC)
    producer = Producer(name="scope-safety-pb5", version="1", instance_id="test")

    async def _ingest_seq(obs_id: str) -> int:
        async with session_factory() as session:
            ingest_seq = await session.scalar(select(AnsichObservationRow.ingest_seq).where(AnsichObservationRow.obs_id == obs_id))
        assert ingest_seq is not None, f"Observation {obs_id} was never persisted"
        return int(ingest_seq)

    async def _mark() -> int | None:
        async with session_factory() as session:
            row = await session.get(AnsichAssessorWatermarkRow, (task_id, "scope-safety", "1.0.0"))
        return None if row is None else row.evidence_watermark

    async def _unverified_effect_belief() -> str | None:
        async with session_factory() as session:
            belief = await session.get(AnsichCurrentBeliefRow, (subject_id, "scope_safety:unverified_effect"))
            if belief is None:
                return None
            assertion = await session.get(AnsichBeliefAssertionRow, belief.assertion_id)
        assert assertion is not None
        return str(assertion.value_json["value"])

    async def _set_availability(watermark: int, available_at: datetime) -> None:
        async with session_factory() as session, session.begin():
            result = await session.execute(
                update(AnsichAssessorJobRow)
                .where(
                    AnsichAssessorJobRow.assessor_name == "scope-safety",
                    AnsichAssessorJobRow.evidence_watermark == watermark,
                )
                .values(available_at=available_at)
            )
        assert result.rowcount == 1, f"expected exactly one scope-safety job at watermark {watermark}"

    try:
        await _start_scope_safety_task(
            service,
            task_id=task_id,
            step_id=step_id,
            observed_at=observed_at,
            producer=producer,
            label="pb5",
        )
        service.record_batch(
            _scope_safety_tool_call_batch(
                task_id=task_id,
                step_id=step_id,
                tool_call_id=subject_id,
                call_seq=1,
                producer=producer,
                observed_at=observed_at,
                label="pb5-subject",
            )
            + _scope_safety_tool_call_batch(
                task_id=task_id,
                step_id=step_id,
                tool_call_id=trigger_id,
                call_seq=2,
                producer=producer,
                observed_at=observed_at,
                label="pb5-trigger",
            )
        )
        await service.flush_task(task_id)

        # (1) An intended effect, then the Scope-deferred authorization, then
        # the observed effect that clears the call. Only the middle row waits.
        intended = ToolEffect(
            effect_id=new_id(),
            tool_call_id=subject_id,
            effect_class="filesystem_write",
            phase="intended",
            scope_id=None,
            target_hash="e" * 64,
            target_preview="workspace/pb5.md",
            fidelity_class="inferred",
            source_obs_id=(intended_obs_id := new_id()),
        )
        service.record(
            ObservationEnvelope(
                obs_id=intended_obs_id,
                kind="effect.intended",
                occurred_at=observed_at,
                task_id=task_id,
                step_id=step_id,
                subject_type="effect",
                subject_id=intended.effect_id,
                producer=producer,
                source_event_id="pb5-subject:effect:intended",
                correlation_id="pb5-subject",
                payload={"effect": intended.model_dump(mode="json")},
            )
        )
        service.record(
            _scope_deferred_authorization(
                task_id=task_id,
                step_id=step_id,
                tool_call_id=subject_id,
                scope_id=scope_id,
                obs_id=deferred_obs_id,
                producer=producer,
                observed_at=observed_at,
                label="pb5-subject",
            )
        )
        observed = _scope_safety_observed_effect(
            task_id=task_id,
            step_id=step_id,
            tool_call_id=subject_id,
            producer=producer,
            observed_at=observed_at,
            label="pb5-subject",
        )
        service.record(observed)
        await service.flush_task(task_id)
        await anyio.sleep(0.3)

        # (2) The first assessment sees the whole stream and clears the call.
        await service.assess_operations(now=observed_at)
        deferred_seq = await _ingest_seq(deferred_obs_id)
        observed_seq = await _ingest_seq(observed.obs_id)
        assert deferred_seq < observed_seq
        assert await _mark() == observed_seq
        assert await _unverified_effect_belief() == "cleared"

        # (3) The Scope lands; the deferred row projects and mints its job at
        # its own low sequence. Its Scope observation's higher-watermark job is
        # drained first so the low one is later claimed alone.
        service.record(
            _scope_snapshot_observation(
                task_id=task_id,
                scope_id=scope_id,
                obs_id=scope_obs_id,
                producer=producer,
                observed_at=observed_at,
                label="pb5-scope",
                external_ref_hash="e" * 64,
            )
        )
        await service.flush_task(task_id)
        scope_seq = await _ingest_seq(scope_obs_id)
        await _await_scope_safety_job(session_factory, deferred_seq)
        await _set_availability(deferred_seq, _UNAVAILABLE_AT)
        await service.assess_operations(now=observed_at + timedelta(minutes=1))
        assert await _mark() == scope_seq

        # (4) The low job is claimed alone. Its own watermark predates the
        # observed effect; reading only that far concludes the call is
        # unverified again.
        await _set_availability(deferred_seq, _AVAILABLE_AT)
        await service.assess_operations(now=observed_at + timedelta(minutes=2))
        belief_after_late_job = await _unverified_effect_belief()
        mark_after_late_job = await _mark()

        # (5) A later trigger on another ToolCall. With the mark restored,
        # nothing re-opens the subject's band -- so whatever (4) concluded is
        # what the Belief says from here on.
        trigger = _scope_safety_observed_effect(
            task_id=task_id,
            step_id=step_id,
            tool_call_id=trigger_id,
            producer=producer,
            observed_at=observed_at,
            label="pb5-trigger",
        )
        service.record(trigger)
        await service.flush_task(task_id)
        await anyio.sleep(0.3)
        trigger_seq = await _ingest_seq(trigger.obs_id)
        await service.assess_operations(now=observed_at + timedelta(minutes=3))

        belief_final = await _unverified_effect_belief()
        final_mark = await _mark()
    finally:
        await service.stop()
        await engine.dispose()

    # The late job read to the pre-claim mark, so its conclusion is the same one
    # complete evidence supports. Without PB5 this is ``present``.
    assert belief_after_late_job == "cleared"
    assert mark_after_late_job == scope_seq
    # And it stays wrong if it was wrong: the restore closes the band, so no
    # later trigger repairs it. This is the assertion that makes the regression
    # permanent rather than transient.
    assert belief_final == "cleared"
    assert final_mark == trigger_seq


@pytest.mark.anyio
async def test_a_stale_advance_cannot_settle_a_band_the_new_owner_absorbed(tmp_path) -> None:
    """PB4's sharpest case: a band that would be judged by nobody, permanently.

    Absorption is what turns a lost widening into lost evidence. When B claims,
    it completes the group's lower jobs in its own claim transaction and widens
    the mark below them, because its evaluation is now the only thing that will
    ever cover their evidence. If A -- whose lease expired between its claim and
    its commit -- then commits an advance back over that band, B reads its
    window start from the raised mark, computes an empty window, and the
    absorbed job's evidence is judged by no evaluation at all. Nothing re-opens
    it: the job says ``completed`` and the mark says covered.

    The unjudged sequence is produced the way this file already simulates a
    concurrent writer's late commit (see
    ``test_absorbed_low_watermark_window_survives_an_evaluation_rollback``): the
    durable mark is seeded to a value that claims evidence which no evaluation
    ever read. A single in-process writer cannot produce it otherwise, because
    it assigns ``ingest_seq`` at insert and commits in that order -- but two
    workers on one database can, which is the deployment this whole slice is
    about.

    **What SQLite cannot execute, and what is therefore injected.** The damage
    needs A to read its window start *before* B's claim widens the mark and to
    commit *after* -- an ordinary stale read under READ COMMITTED, and the whole
    reason A's advance is wrong. SQLite cannot run it: A's evaluation takes a
    snapshot at its first SELECT, so a B that commits inside that window makes
    A's later write fail with a busy-snapshot error instead of proceeding. So
    B's claim is executed for real (it really does absorb and widen between A's
    two transactions) while A's stale *read* is injected -- A is handed the
    value the mark actually held a moment earlier. Everything downstream of that
    read is the production code path. The executed proof belongs to the
    PostgreSQL tier.

    Domain: the stale-drop half of the assessor watermark work, absorption
    variant. The non-absorbing variant, where the erased widening costs a
    re-judge rather than a first judgement, is
    ``test_a_stale_evaluation_cannot_erase_the_new_owners_window``.
    """

    async with _two_assessor_workers(tmp_path, "scope-safety-pb4-absorbed.db") as workers:
        task_id, step_id = new_id(), new_id()
        bootstrap_id, victim_id, trigger_id = new_id(), new_id(), new_id()
        producer = Producer(name="scope-safety-pb4-absorbed", version="1", instance_id="test")

        async def _ingest_seq(obs_id: str) -> int:
            async with workers.sessions() as session:
                ingest_seq = await session.scalar(select(AnsichObservationRow.ingest_seq).where(AnsichObservationRow.obs_id == obs_id))
            assert ingest_seq is not None, f"Observation {obs_id} was never persisted"
            return int(ingest_seq)

        async def _set_assessor_availability(watermark: int, available_at: datetime) -> None:
            async with workers.sessions() as session, session.begin():
                result = await session.execute(
                    update(AnsichAssessorJobRow)
                    .where(
                        AnsichAssessorJobRow.assessor_name == "scope-safety",
                        AnsichAssessorJobRow.evidence_watermark == watermark,
                    )
                    .values(available_at=available_at)
                )
            assert result.rowcount == 1, f"expected exactly one scope-safety job at watermark {watermark}"

        await workers.a.persist_and_project(
            [
                ObservationEnvelope.task_lifecycle(
                    kind="task.created",
                    task_id=task_id,
                    source_kind="deerflow_run",
                    source_id="pb4-absorbed",
                    occurred_at=_ASSESSOR_TASK_OBSERVED_AT,
                    source_event_id="pb4-absorbed:task:created",
                ),
                ObservationEnvelope(
                    kind="step.started",
                    occurred_at=_ASSESSOR_TASK_OBSERVED_AT,
                    task_id=task_id,
                    step_id=step_id,
                    subject_type="step",
                    subject_id=step_id,
                    producer=producer,
                    source_event_id="pb4-absorbed:step:started",
                    correlation_id="pb4-absorbed",
                    payload={"step_seq": 1, "actor_kind": "lead_agent"},
                ),
                *_scope_safety_tool_call_batch(
                    task_id=task_id,
                    step_id=step_id,
                    tool_call_id=bootstrap_id,
                    call_seq=1,
                    producer=producer,
                    observed_at=_ASSESSOR_TASK_OBSERVED_AT,
                    label="pb4-absorbed-bootstrap",
                ),
                *_scope_safety_tool_call_batch(
                    task_id=task_id,
                    step_id=step_id,
                    tool_call_id=victim_id,
                    call_seq=2,
                    producer=producer,
                    observed_at=_ASSESSOR_TASK_OBSERVED_AT,
                    label="pb4-absorbed-victim",
                ),
                *_scope_safety_tool_call_batch(
                    task_id=task_id,
                    step_id=step_id,
                    tool_call_id=trigger_id,
                    call_seq=3,
                    producer=producer,
                    observed_at=_ASSESSOR_TASK_OBSERVED_AT,
                    label="pb4-absorbed-trigger",
                ),
            ]
        )
        await _drain_projections(workers.a)
        await _run_assessors(workers.a, now=_ASSESSOR_TASK_OBSERVED_AT)

        bootstrap_evidence = _scope_safety_evidence_batch(
            task_id=task_id,
            step_id=step_id,
            tool_call_id=bootstrap_id,
            producer=producer,
            observed_at=_ASSESSOR_TASK_OBSERVED_AT,
            label="pb4-absorbed-bootstrap",
            with_observed_effect=True,
        )
        await workers.a.persist_and_project(list(bootstrap_evidence))
        await _drain_projections(workers.a)
        await _run_assessors(workers.a, now=_ASSESSOR_TASK_OBSERVED_AT)
        bootstrap_seq = await _ingest_seq(bootstrap_evidence[-1].obs_id)
        assert await _scope_safety_mark(workers.sessions, task_id) == bootstrap_seq

        # The victim's evidence, and a mark that claims it was judged. The mark
        # is written by hand for the reason the module docstring of the rollback
        # test gives: only a second worker's late commit produces a settled mark
        # above evidence no evaluation read, and one in-process writer cannot.
        victim_effect = _scope_safety_observed_effect(
            task_id=task_id,
            step_id=step_id,
            tool_call_id=victim_id,
            producer=producer,
            observed_at=_ASSESSOR_TASK_OBSERVED_AT,
            label="pb4-absorbed-victim",
        )
        await workers.a.persist_and_project([victim_effect])
        await _drain_projections(workers.a)
        victim_seq = await _ingest_seq(victim_effect.obs_id)
        async with workers.sessions() as session, session.begin():
            mark = await session.get(AnsichAssessorWatermarkRow, (task_id, "scope-safety", "1.0.0"))
            assert mark is not None and mark.evidence_watermark < victim_seq
            mark.evidence_watermark = victim_seq

        trigger = _scope_safety_observed_effect(
            task_id=task_id,
            step_id=step_id,
            tool_call_id=trigger_id,
            producer=producer,
            observed_at=_ASSESSOR_TASK_OBSERVED_AT,
            label="pb4-absorbed-trigger",
        )
        await workers.a.persist_and_project([trigger])
        await _drain_projections(workers.a)
        trigger_seq = await _ingest_seq(trigger.obs_id)

        # A claims the trigger alone: the victim's job is held back so it lands
        # only *after* A's claim, which is what makes it a job A never judged.
        await _set_assessor_availability(victim_seq, _UNAVAILABLE_AT)
        record: dict[str, object] = {}
        stale_read: dict[str, object] = {}
        original_window_start = workers.a._scope_safety_window_start

        async def _stale_window_start(session, *, task_id: str):
            # A reads its window once, and it reads it before B widened (see the
            # docstring). Every later call is the real one.
            if "value" in stale_read and "used" not in stale_read:
                stale_read["used"] = True
                return stale_read["value"]
            return await original_window_start(session, task_id=task_id)

        workers.a._scope_safety_window_start = _stale_window_start  # type: ignore[method-assign]

        async def _the_low_job_lands():
            stale_read["value"] = await _scope_safety_mark(workers.sessions, task_id)
            await _set_assessor_availability(victim_seq, _AVAILABLE_AT)

        _take_over_the_scope_safety_claim(workers, record, before_takeover=_the_low_job_lands)
        await _run_assessors(workers.a, now=_ASSESSOR_TASK_OBSERVED_AT + timedelta(minutes=1), limit=1)

        # The read A actually worked from: the mark as it stood after A's own
        # claim, above the victim's evidence.
        assert stale_read == {"value": victim_seq, "used": True}

        a_claim = record["a"]
        b_claim = record["b"]
        assert a_claim.evidence_watermark == trigger_seq
        assert b_claim is not None
        assert b_claim.job_id == a_claim.job_id
        # B's claim absorbed the low job and widened below it: from here, B's
        # evaluation is the only thing that can ever judge that evidence.
        assert b_claim.pre_claim_watermark == victim_seq
        async with workers.sessions() as session:
            absorbed = await session.scalar(select(AnsichAssessorJobRow).where(AnsichAssessorJobRow.evidence_watermark == victim_seq))
        assert absorbed is not None
        assert absorbed.status == "completed"

        # PB4: A's advance never lands, so the widened window survives for B.
        assert await _scope_safety_mark(workers.sessions, task_id) == victim_seq - 1
        assert workers.a.stale_completion_count == 1

        # The new owner settles it.
        async with workers.sessions() as session, session.begin():
            await session.execute(update(AnsichAssessorJobRow).where(AnsichAssessorJobRow.job_id == b_claim.job_id).values(lease_expires_at=_EXPIRED_LEASE_AT))
        await _run_assessors(workers.b, now=_ASSESSOR_TASK_OBSERVED_AT + timedelta(minutes=2), limit=1)

        # Without PB4 this is zero and stays zero: the absorbed job is
        # ``completed`` and the mark claims its evidence was covered, so no
        # later window ever names this ToolCall again.
        assert await _scope_conclusion_count(workers.sessions, victim_id) == 4
        assert await _scope_safety_mark(workers.sessions, task_id) == trigger_seq


@pytest.mark.anyio
async def test_the_mark_never_settles_below_what_an_earlier_evaluation_reached(tmp_path) -> None:
    """The restore is the mark's own invariant, not one caller's arithmetic.

    On the scope-safety path PB5 already raises the evaluation watermark to the
    same maximum, so the guard inside ``_advance_assessor_watermark`` is
    numerically redundant *there* -- no integration test can kill it. It is kept
    because the invariant belongs to the row's writer: whatever watermark a
    caller arrives with, the mark may not come out below a value some earlier
    evaluation already established by judging everything under it. This test is
    what gives that guard teeth, by calling the writer directly with the shape a
    caller that skipped PB5's arithmetic would produce.
    """

    async with _two_assessor_workers(tmp_path, "scope-safety-mark-invariant.db") as workers:
        task_id = new_id()
        await workers.a.persist_and_project(
            [
                ObservationEnvelope.task_lifecycle(
                    kind="task.created",
                    task_id=task_id,
                    source_kind="deerflow_run",
                    source_id="mark-invariant",
                    occurred_at=_ASSESSOR_TASK_OBSERVED_AT,
                    source_event_id="mark-invariant:task:created",
                )
            ]
        )
        await _drain_projections(workers.a)

        # No row yet: the first settle takes the maximum too, so a cold start
        # cannot mint a mark below the one the claim found.
        async with workers.sessions() as session, session.begin():
            await workers.a._advance_assessor_watermark(
                session,
                task_id=task_id,
                assessor=SCOPE_SAFETY_ASSESSOR,
                evidence_watermark=4,
                pre_claim_watermark=9,
            )
        assert await _scope_safety_mark(workers.sessions, task_id) == 9

        # A widening lowers it; a later evaluation whose own watermark is under
        # the pre-claim mark must still settle at the pre-claim mark.
        async with workers.sessions() as session, session.begin():
            await workers.a._widen_assessor_watermark(
                session,
                subject_id=task_id,
                assessor_name=SCOPE_SAFETY_ASSESSOR.name,
                assessor_version=SCOPE_SAFETY_ASSESSOR.version,
                window_start_exclusive=3,
            )
        assert await _scope_safety_mark(workers.sessions, task_id) == 3
        async with workers.sessions() as session, session.begin():
            await workers.a._advance_assessor_watermark(
                session,
                task_id=task_id,
                assessor=SCOPE_SAFETY_ASSESSOR,
                evidence_watermark=4,
                pre_claim_watermark=9,
            )
        assert await _scope_safety_mark(workers.sessions, task_id) == 9

        # And it still never lowers: a caller arriving under the stored mark
        # leaves the row alone, with or without a pre-claim value.
        async with workers.sessions() as session, session.begin():
            await workers.a._advance_assessor_watermark(
                session,
                task_id=task_id,
                assessor=SCOPE_SAFETY_ASSESSOR,
                evidence_watermark=5,
                pre_claim_watermark=None,
            )
        assert await _scope_safety_mark(workers.sessions, task_id) == 9
