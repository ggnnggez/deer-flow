from __future__ import annotations

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
from sqlalchemy import create_engine, event, func, inspect, select, text
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
    AnsichRelationRow,
    AnsichScopeConclusionRow,
    AnsichScopeRow,
    AnsichTaskSummaryRow,
    AnsichToolCallAuthorizationRow,
    AnsichToolEffectRow,
)
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
        replayed = await service.rebuild_projections()
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
    assert replayed > 0
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
    assert final_watermark == trigger_seq
