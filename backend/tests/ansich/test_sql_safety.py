from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from ansich import (
    AuthorizationPermission,
    AuthorizationSnapshot,
    ObservationEnvelope,
    Producer,
    ToolEffect,
    new_id,
)
from sqlalchemy import create_engine, event, func, inspect, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateTable

from deerflow.ansich import create_sql_ansich_service
from deerflow.ansich.persistence.models import (
    AnsichAuthorizationPermissionRow,
    AnsichAuthorizationSnapshotRow,
    AnsichCurrentBeliefRow,
    AnsichRelationRow,
    AnsichScopeConclusionRow,
    AnsichScopeRow,
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

    alembic_command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{database_path}")
    try:
        database_inspector = inspect(engine)
        table_names = set(database_inspector.get_table_names())
        scope_columns = {column["name"] for column in database_inspector.get_columns("ansich_scopes")}
        relation_columns = {column["name"] for column in database_inspector.get_columns("ansich_relations")}
        with engine.connect() as connection:
            revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
        with engine.begin() as connection:
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

    assert revision == "0020_ansich_scope_safety"
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

    alembic_command.downgrade(config, "0019_ansich_task_tree_usage")
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
