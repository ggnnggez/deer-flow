from __future__ import annotations

from datetime import UTC, datetime
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

from deerflow.ansich import create_sql_ansich_service
from deerflow.ansich.persistence.models import (
    AnsichAssessorErrorRow,
    AnsichAssessorJobRow,
    AnsichAuthorizationPermissionRow,
    AnsichAuthorizationSnapshotRow,
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

    assert revision == "0024_ansich_wall_time_watermarks"
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
        stored_payload_state = {row.obs_id: (row.payload_json, row.payload_ref_id is not None) for row in stored_rows}

        timeline = await service.list_timeline(task_id, limit=50)
        observations = await service.list_observations(task_id)
    finally:
        await service.stop()
        await engine.dispose()

    assert stored_payload_state == {obs_id: (None, True) for obs_id in externalized_obs_ids}
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
