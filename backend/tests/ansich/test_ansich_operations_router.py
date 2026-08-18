from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from _router_auth_helpers import make_authed_test_app
from ansich import ObservationEnvelope, Producer, new_id
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from support.ansich_settle import only_test_driven_assessments

from app.gateway.auth.models import User
from app.gateway.routers import ansich as ansich_router
from deerflow.ansich import create_sql_ansich_service
from deerflow.ansich.persistence.models import (
    AnsichObservationRow,
    AnsichOperatorActionRow,
)
from deerflow.persistence.base import Base
from deerflow.runtime.runs.manager import CancelOutcome, RunRecord
from deerflow.runtime.runs.schemas import DisconnectMode, RunStatus


def _admin_user() -> User:
    return User(
        id=uuid4(),
        email="ansich-operations-admin@example.com",
        password_hash="x",
        system_role="admin",
    )


@pytest.mark.anyio
async def test_filtered_empty_active_read_does_not_refresh_ready_read_model(
    tmp_path,
):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-active-read-no-write.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(
        session_factory,
        operations_assessment_interval_ms=60_000,
    )
    only_test_driven_assessments(service)
    await service.start()
    task_id = new_id()
    observed_at = datetime.now(UTC) - timedelta(seconds=10)
    service.record_batch(
        (
            ObservationEnvelope.task_lifecycle(
                kind="task.created",
                task_id=task_id,
                source_kind="deerflow_run",
                source_id="run-active-read-no-write",
                occurred_at=observed_at,
                source_event_id="run:run-active-read-no-write:task:created",
                owner_id="owner-a",
            ),
            ObservationEnvelope.task_lifecycle(
                kind="task.started",
                task_id=task_id,
                source_kind="deerflow_run",
                source_id="run-active-read-no-write",
                occurred_at=observed_at,
                source_event_id="run:run-active-read-no-write:task:started",
                owner_id="owner-a",
            ),
        )
    )
    await service.flush_task(task_id)
    await service.assess_operations(now=observed_at + timedelta(seconds=1))
    before = (await service.list_active_tasks())[0]

    app = make_authed_test_app(user_factory=_admin_user)
    app.state.ansich_service = service
    app.include_router(ansich_router.router)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get("/api/ansich/operations/active-tasks?owner=no-match")
        after = (await service.list_active_tasks())[0]
    finally:
        await service.stop()
        await engine.dispose()

    assert response.status_code == 200
    assert response.json()["items"] == []
    assert after.updated_at == before.updated_at


@pytest.mark.anyio
async def test_budget_read_does_not_materialize_missing_health(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-budget-read-no-write.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(
        session_factory,
        operations_assessment_interval_ms=60_000,
    )
    await service.start()
    task_id = new_id()
    observed_at = datetime.now(UTC)
    service.record_batch(
        (
            ObservationEnvelope.task_lifecycle(
                kind="task.created",
                task_id=task_id,
                source_kind="deerflow_run",
                source_id="run-budget-read-no-write",
                occurred_at=observed_at,
                source_event_id="run:run-budget-read-no-write:task:created",
            ),
            ObservationEnvelope.task_lifecycle(
                kind="task.started",
                task_id=task_id,
                source_kind="deerflow_run",
                source_id="run-budget-read-no-write",
                occurred_at=observed_at,
                source_event_id="run:run-budget-read-no-write:task:started",
            ),
            ObservationEnvelope.budget_configured(
                task_id=task_id,
                run_id="run-budget-read-no-write",
                occurred_at=observed_at,
                dimension="steps",
                aggregation_scope="local",
                warning_limit=1,
                hard_limit=2,
                enforcement=False,
                source_kind="shadow",
                requested_value=None,
                effective_value=2,
                source_event_id="run:run-budget-read-no-write:budget:steps",
            ),
        )
    )
    await service.flush_task(task_id)

    app = make_authed_test_app(user_factory=_admin_user)
    app.state.ansich_service = service
    app.include_router(ansich_router.router)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get(f"/api/ansich/tasks/{task_id}/budgets")
    finally:
        await service.stop()
        await engine.dispose()

    assert response.status_code == 200
    assert response.json()["budgets"]["budgets"][0]["dimension"] == "steps"
    assert response.json()["health"] == []


@pytest.mark.anyio
async def test_operator_endpoints_return_active_usage_budgets_and_etag(
    tmp_path,
    monkeypatch,
):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-operations-router.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(session_factory)
    only_test_driven_assessments(service)
    await service.start()
    task_id = new_id()
    step_id = new_id()
    now = datetime.now(UTC)
    service.record_batch(
        (
            ObservationEnvelope.task_lifecycle(
                kind="task.created",
                task_id=task_id,
                source_kind="deerflow_run",
                source_id="run-operations-router",
                occurred_at=now,
                source_event_id="run:run-operations-router:task:created",
                owner_id="owner-router",
                thread_id="thread-router",
            ),
            ObservationEnvelope.task_lifecycle(
                kind="task.started",
                task_id=task_id,
                source_kind="deerflow_run",
                source_id="run-operations-router",
                occurred_at=now,
                source_event_id="run:run-operations-router:task:started",
                owner_id="owner-router",
                thread_id="thread-router",
            ),
            ObservationEnvelope(
                kind="step.started",
                occurred_at=now,
                task_id=task_id,
                step_id=step_id,
                subject_type="step",
                subject_id=step_id,
                producer=Producer(
                    name="operations-router-test",
                    version="1",
                    instance_id="test",
                ),
                source_event_id=f"step:{step_id}:started",
                correlation_id="run-operations-router",
                payload={"step_seq": 1, "actor_kind": "lead_agent"},
            ),
            ObservationEnvelope.task_heartbeat(
                task_id=task_id,
                run_id="run-operations-router",
                occurred_at=now,
                elapsed_ms=1,
                worker_id="worker-router",
                ownership_epoch="worker-router",
                source_event_id="run:run-operations-router:heartbeat:1",
            ),
            ObservationEnvelope.budget_configured(
                task_id=task_id,
                run_id="run-operations-router",
                occurred_at=now,
                dimension="steps",
                aggregation_scope="local",
                warning_limit=1,
                hard_limit=2,
                enforcement=False,
                source_kind="shadow",
                requested_value=None,
                effective_value=2,
                source_event_id="run:run-operations-router:budget:steps",
            ),
        )
    )
    await service.flush_task(task_id)
    await service.assess_operations(now=now)

    app = make_authed_test_app(user_factory=_admin_user)
    app.state.ansich_service = service
    app.include_router(ansich_router.router)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            active = await client.get("/api/ansich/operations/active-tasks?owner=owner-router")
            usage = await client.get(f"/api/ansich/tasks/{task_id}/usage")
            budgets = await client.get(f"/api/ansich/tasks/{task_id}/budgets")
            changed_projection_status = service.get_health().model_copy(update={"lag_ms": service.get_health().lag_ms + 1})
            monkeypatch.setattr(
                service,
                "get_health",
                lambda: changed_projection_status,
            )
            unchanged = await client.get(
                "/api/ansich/operations/active-tasks?owner=owner-router",
                headers={"If-None-Match": active.headers["etag"]},
            )
    finally:
        await service.stop()
        await engine.dispose()

    assert active.status_code == 200
    assert active.headers["etag"]
    assert active.json()["items"][0]["task_id"] == task_id
    assert active.json()["items"][0]["heartbeat"]["value"] == "fresh"
    assert usage.status_code == 200
    assert usage.json()["usage"]["inclusive_status"] == "available"
    assert usage.json()["usage"]["local"][0]["dimension"] == "steps"
    assert budgets.status_code == 200
    assert budgets.json()["budgets"]["budgets"][0]["dimension"] == "steps"
    assert budgets.json()["health"][0]["value"] == "warning"
    assert unchanged.status_code == 304


@pytest.mark.anyio
async def test_alert_endpoints_list_detail_and_enforce_workflow_version(
    tmp_path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-alert-router.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(
        session_factory,
        tool_frequency_threshold=1,
        operations_assessment_interval_ms=60_000,
    )
    only_test_driven_assessments(service)
    await service.start()
    task_id = new_id()
    step_id = new_id()
    tool_call_id = new_id()
    now = datetime.now(UTC)
    producer = Producer(
        name="alert-router-test",
        version="1",
        instance_id="test",
    )
    service.record_batch(
        (
            ObservationEnvelope.task_lifecycle(
                kind="task.created",
                task_id=task_id,
                source_kind="deerflow_run",
                source_id="run-alert-router",
                occurred_at=now,
                source_event_id="run:alert-router:task:created",
            ),
            ObservationEnvelope.task_lifecycle(
                kind="task.started",
                task_id=task_id,
                source_kind="deerflow_run",
                source_id="run-alert-router",
                occurred_at=now,
                source_event_id="run:alert-router:task:started",
            ),
            ObservationEnvelope(
                kind="step.started",
                occurred_at=now,
                task_id=task_id,
                step_id=step_id,
                subject_type="step",
                subject_id=step_id,
                producer=producer,
                source_event_id="run:alert-router:step:started",
                correlation_id=task_id,
                payload={"step_seq": 1, "actor_kind": "lead_agent"},
            ),
            ObservationEnvelope(
                kind="tool.issued",
                occurred_at=now,
                task_id=task_id,
                step_id=step_id,
                subject_type="tool_call",
                subject_id=tool_call_id,
                producer=producer,
                source_event_id="run:alert-router:tool:issued",
                correlation_id=task_id,
                payload={
                    "call_seq": 1,
                    "provider_call_id": "provider-alert-router",
                    "tool_name": "web_search",
                    "args_hash": "a" * 64,
                    "args_preview": {"query": "status"},
                    "tool_schema_block_id": None,
                },
            ),
        )
    )
    await service.flush_task(task_id)
    await service.assess_operations(now=now + timedelta(seconds=1))

    app = make_authed_test_app(user_factory=_admin_user)
    app.state.ansich_service = service
    app.include_router(ansich_router.router)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            listed = await client.get(
                "/api/ansich/operations/alerts",
                params={
                    "type": "tool_frequency",
                    "state": "open",
                    "task": task_id,
                },
            )
            deferred_type_filter = await client.get(
                "/api/ansich/operations/alerts",
                params={"type": "projection_failure"},
            )
            alert_id = listed.json()["items"][0]["alert_id"]
            detail = await client.get(f"/api/ansich/operations/alerts/{alert_id}")
            task_detail = await client.get(f"/api/ansich/tasks/{task_id}")
            acknowledged = await client.post(
                f"/api/ansich/operations/alerts/{alert_id}/acknowledge",
                json={"workflow_version": 1},
            )
            conflict = await client.post(
                f"/api/ansich/operations/alerts/{alert_id}/dismiss",
                json={
                    "workflow_version": 1,
                    "reason": "stale request",
                },
            )
            dismissed = await client.post(
                f"/api/ansich/operations/alerts/{alert_id}/dismiss",
                json={
                    "workflow_version": 2,
                    "reason": "expected maintenance traffic",
                },
            )
    finally:
        await service.stop()
        await engine.dispose()

    assert listed.status_code == 200
    assert listed.json()["next_cursor"] is None
    assert deferred_type_filter.status_code == 422
    assert detail.status_code == 200
    assert detail.json()["alert"]["source_belief"]["field_name"] == ("tool_frequency:web_search")
    assert task_detail.status_code == 200
    assert task_detail.json()["behavior"]["field_name"] == "behavior"
    assert task_detail.json()["behavior"]["value"]["value"] == "unassessed"
    assert acknowledged.status_code == 200
    assert acknowledged.json()["alert"]["workflow_version"] == 2
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["current_alert"]["workflow_version"] == 2
    assert dismissed.status_code == 200
    assert dismissed.json()["alert"]["workflow_state"] == "dismissed"


@pytest.mark.anyio
async def test_operator_actions_validate_source_and_are_idempotent(
    tmp_path,
    monkeypatch,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-action-router.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(
        session_factory,
        operations_assessment_interval_ms=60_000,
    )
    await service.start()
    task_id = new_id()
    now = datetime.now(UTC)
    service.record_batch(
        (
            ObservationEnvelope.task_lifecycle(
                kind="task.created",
                task_id=task_id,
                source_kind="deerflow_run",
                source_id="run-action-router",
                occurred_at=now,
                source_event_id="run:action-router:task:created",
                thread_id="thread-action-router",
            ),
            ObservationEnvelope.task_lifecycle(
                kind="task.started",
                task_id=task_id,
                source_kind="deerflow_run",
                source_id="run-action-router",
                occurred_at=now,
                source_event_id="run:action-router:task:started",
                thread_id="thread-action-router",
            ),
        )
    )
    await service.flush_task(task_id)

    class FakeRunManager:
        def __init__(self):
            self.calls: list[tuple[str, str]] = []
            self.cancel_outcome = CancelOutcome.cancelled
            self.record = RunRecord(
                run_id="run-action-router",
                thread_id="thread-action-router",
                assistant_id="lead-agent",
                status=RunStatus.running,
                on_disconnect=DisconnectMode.continue_,
            )

        async def get(self, run_id):
            return self.record if run_id == self.record.run_id else None

        async def cancel(self, run_id, *, action="interrupt"):
            self.calls.append((run_id, action))
            return self.cancel_outcome

    run_manager = FakeRunManager()
    app = make_authed_test_app(user_factory=_admin_user)
    app.state.ansich_service = service
    app.state.run_manager = run_manager
    app.include_router(ansich_router.router)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            interrupted = await client.post(
                f"/api/ansich/tasks/{task_id}/actions/interrupt",
                headers={"Idempotency-Key": "interrupt-once"},
            )
            repeated = await client.post(
                f"/api/ansich/tasks/{task_id}/actions/interrupt",
                headers={"Idempotency-Key": "interrupt-once"},
            )
            run_manager.record.thread_id = "wrong-thread"
            mismatched = await client.post(
                f"/api/ansich/tasks/{task_id}/actions/rollback",
                headers={"Idempotency-Key": "rollback-mismatch"},
            )
            run_manager.record.thread_id = "thread-action-router"
            run_manager.cancel_outcome = CancelOutcome.not_cancellable
            rejected = await client.post(
                f"/api/ansich/tasks/{task_id}/actions/rollback",
                headers={"Idempotency-Key": "rollback-runtime-rejected"},
            )
            run_manager.cancel_outcome = CancelOutcome.cancelled

            async def fail_requested_audit(*args, **kwargs):
                raise RuntimeError("audit storage unavailable")

            monkeypatch.setattr(
                service,
                "begin_operator_action",
                fail_requested_audit,
            )
            degraded = await client.post(
                f"/api/ansich/tasks/{task_id}/actions/rollback",
                headers={"Idempotency-Key": "rollback-degraded-audit"},
            )
    finally:
        await service.stop()
        await engine.dispose()

    assert interrupted.status_code == 200
    assert interrupted.json()["action"]["status"] == "succeeded"
    assert interrupted.json()["audit_status"] == "recorded"
    assert repeated.status_code == 200
    assert repeated.json()["idempotent_replay"] is True
    assert mismatched.status_code == 409
    assert rejected.status_code == 409
    assert rejected.json()["detail"]["action"]["status"] == "failed"
    assert rejected.json()["detail"]["audit_status"] == "recorded"
    assert degraded.status_code == 200
    assert degraded.json()["action"]["status"] == "succeeded"
    assert degraded.json()["audit_status"] == "degraded"
    assert run_manager.calls == [
        ("run-action-router", "interrupt"),
        ("run-action-router", "rollback"),
        ("run-action-router", "rollback"),
    ]


@pytest.mark.anyio
async def test_orphaned_requested_action_is_recovered_after_expiry(tmp_path) -> None:
    """A crash between begin and finish must not 409 that Idempotency-Key forever.

    Phase-6 L2 / ruling HR3: a ``requested`` row that nothing terminalized is
    only taken over once it aged past the conservative expiry window. A fresh
    in-progress row still conflicts, so a genuine duplicate network retry is
    still refused rather than executed twice.
    """

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-action-orphan.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(
        session_factory,
        operations_assessment_interval_ms=60_000,
    )
    await service.start()
    task_id = new_id()
    now = datetime.now(UTC)
    service.record_batch(
        (
            ObservationEnvelope.task_lifecycle(
                kind="task.created",
                task_id=task_id,
                source_kind="deerflow_run",
                source_id="run-action-orphan",
                occurred_at=now,
                source_event_id="run:action-orphan:task:created",
                thread_id="thread-action-orphan",
            ),
            ObservationEnvelope.task_lifecycle(
                kind="task.started",
                task_id=task_id,
                source_kind="deerflow_run",
                source_id="run-action-orphan",
                occurred_at=now,
                source_event_id="run:action-orphan:task:started",
                thread_id="thread-action-orphan",
            ),
        )
    )
    await service.flush_task(task_id)

    class FakeRunManager:
        def __init__(self):
            self.calls: list[tuple[str, str]] = []
            self.record = RunRecord(
                run_id="run-action-orphan",
                thread_id="thread-action-orphan",
                assistant_id="lead-agent",
                status=RunStatus.running,
                on_disconnect=DisconnectMode.continue_,
            )

        async def get(self, run_id):
            return self.record if run_id == self.record.run_id else None

        async def cancel(self, run_id, *, action="interrupt"):
            self.calls.append((run_id, action))
            return CancelOutcome.cancelled

    run_manager = FakeRunManager()
    app = make_authed_test_app(user_factory=_admin_user)
    app.state.ansich_service = service
    app.state.run_manager = run_manager
    app.include_router(ansich_router.router)
    headers = {"Idempotency-Key": "interrupt-orphaned"}
    try:
        # A process that dies between begin and finish leaves this row `requested`.
        orphan, created = await service.begin_operator_action(
            task_id=task_id,
            action_type="interrupt",
            idempotency_key="interrupt-orphaned",
            operator_id="operator-that-crashed",
            occurred_at=now,
        )
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            fresh_conflict = await client.post(
                f"/api/ansich/tasks/{task_id}/actions/interrupt",
                headers=headers,
            )
            async with session_factory() as session, session.begin():
                await session.execute(
                    update(AnsichOperatorActionRow)
                    .where(AnsichOperatorActionRow.action_id == orphan.action_id)
                    .values(
                        created_at=now - timedelta(minutes=6),
                        updated_at=now - timedelta(minutes=6),
                    )
                )
            recovered = await client.post(
                f"/api/ansich/tasks/{task_id}/actions/interrupt",
                headers=headers,
            )
            replayed = await client.post(
                f"/api/ansich/tasks/{task_id}/actions/interrupt",
                headers=headers,
            )
        async with session_factory() as session:
            rows = list((await session.execute(select(AnsichOperatorActionRow))).scalars())
            observations = list(
                (
                    await session.execute(
                        select(AnsichObservationRow).where(AnsichObservationRow.kind.like("operator.action_%")).order_by(AnsichObservationRow.ingest_seq),
                    )
                ).scalars()
            )
    finally:
        await service.stop()
        await engine.dispose()

    assert created is True
    assert orphan.status == "requested"
    # A fresh `requested` row is a genuine duplicate, not an orphan.
    assert fresh_conflict.status_code == 409
    assert fresh_conflict.json()["detail"]["message"] == "Operator action is already in progress"
    assert run_manager.calls == [("run-action-orphan", "interrupt")]

    recovered_action = recovered.json()["action"]
    assert recovered.status_code == 200
    assert recovered.json()["idempotent_replay"] is False
    assert recovered_action["status"] == "succeeded"
    assert recovered_action["idempotency_key"] == "interrupt-orphaned"
    assert recovered_action["action_id"] != orphan.action_id

    # The ledger keeps following this Idempotency-Key, now on the fresh attempt.
    assert replayed.status_code == 200
    assert replayed.json()["idempotent_replay"] is True
    assert replayed.json()["action"]["action_id"] == recovered_action["action_id"]
    assert len(rows) == 1
    assert rows[0].action_id == recovered_action["action_id"]
    assert rows[0].status == "succeeded"

    # Both attempts carry a terminal in the audit stream.
    by_action: dict[str, list[AnsichObservationRow]] = {}
    for observation in observations:
        by_action.setdefault(observation.payload_json["action_id"], []).append(observation)
    assert [row.kind for row in by_action[orphan.action_id]] == [
        "operator.action_requested",
        "operator.action_failed",
    ]
    assert by_action[orphan.action_id][1].payload_json["result"]["outcome"] == "stale_requested_takeover"
    assert by_action[orphan.action_id][1].payload_json["result"]["superseded_by_action_id"] == recovered_action["action_id"]
    assert [row.kind for row in by_action[recovered_action["action_id"]]] == [
        "operator.action_requested",
        "operator.action_succeeded",
    ]
