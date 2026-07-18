from datetime import UTC, datetime
from uuid import uuid4

import pytest
from _router_auth_helpers import make_authed_test_app
from ansich import ObservationEnvelope, Producer, new_id
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.gateway.auth.models import User
from app.gateway.routers import ansich as ansich_router
from deerflow.ansich import create_sql_ansich_service
from deerflow.persistence.base import Base


def _admin_user() -> User:
    return User(
        id=uuid4(),
        email="ansich-operations-admin@example.com",
        password_hash="x",
        system_role="admin",
    )


@pytest.mark.anyio
async def test_operator_endpoints_return_active_usage_budgets_and_etag(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-operations-router.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(session_factory)
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
    assert usage.json()["usage"]["inclusive_status"] == "not_available"
    assert usage.json()["usage"]["local"][0]["dimension"] == "steps"
    assert budgets.status_code == 200
    assert budgets.json()["budgets"]["budgets"][0]["dimension"] == "steps"
    assert budgets.json()["health"][0]["value"] == "warning"
    assert unchanged.status_code == 304
