from datetime import UTC, datetime
from uuid import uuid4

import pytest
from _router_auth_helpers import make_authed_test_app
from ansich import AnsichService, ObservationEnvelope, new_id
from httpx import ASGITransport, AsyncClient

from app.gateway.auth.models import User
from app.gateway.routers import ansich as ansich_router
from deerflow.ansich import create_embedded_ansich_service
from deerflow.config.ansich_config import AnsichConfig


def admin_user() -> User:
    return User(
        id=uuid4(),
        email="ansich-admin@example.com",
        password_hash="x",
        system_role="admin",
    )


def regular_user() -> User:
    return User(
        id=uuid4(),
        email="ansich-user@example.com",
        password_hash="x",
        system_role="user",
    )


@pytest.mark.anyio
async def test_admin_can_list_observed_tasks_with_belief_and_projection_health():
    service = AnsichService.in_memory()
    task_id = new_id()

    async def seed() -> None:
        await service.start()
        service.record(
            ObservationEnvelope.task_lifecycle(
                kind="task.created",
                task_id=task_id,
                source_kind="deerflow_run",
                source_id="run-api",
                occurred_at=datetime(2026, 7, 17, 14, 0, tzinfo=UTC),
                source_event_id="run:run-api:task:created",
            )
        )
        service.record(
            ObservationEnvelope.task_lifecycle(
                kind="task.completed",
                task_id=task_id,
                source_kind="deerflow_run",
                source_id="run-api",
                occurred_at=datetime(2026, 7, 17, 14, 1, tzinfo=UTC),
                source_event_id="run:run-api:task:completed",
            )
        )
        await service.flush_task(task_id)

    await seed()
    app = make_authed_test_app(user_factory=admin_user)
    app.state.ansich_service = service
    app.include_router(ansich_router.router)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/ansich/tasks")
    finally:
        await service.stop()

    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["task_id"] == task_id
    assert body["items"][0]["control"]["value"] == "completed"
    assert body["items"][0]["control"]["fidelity_class"] == "hard"
    assert body["items"][0]["control"]["evidence_obs_ids"]
    assert body["projection_status"]["status"] == "healthy"


@pytest.mark.anyio
async def test_admin_can_read_task_lifecycle_timeline_in_ingest_order():
    service = AnsichService.in_memory()
    task_id = new_id()

    async def seed() -> None:
        await service.start()
        for kind in ("task.created", "task.started", "task.completed"):
            service.record(
                ObservationEnvelope.task_lifecycle(
                    kind=kind,
                    task_id=task_id,
                    source_kind="deerflow_run",
                    source_id="run-timeline",
                    occurred_at=datetime(2026, 7, 17, 15, 0, tzinfo=UTC),
                    source_event_id=f"run:run-timeline:{kind}",
                )
            )
        await service.flush_task(task_id)

    await seed()
    app = make_authed_test_app(user_factory=admin_user)
    app.state.ansich_service = service
    app.include_router(ansich_router.router)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/ansich/tasks/{task_id}/timeline")
    finally:
        await service.stop()

    assert response.status_code == 200
    assert [item["kind"] for item in response.json()["items"]] == [
        "task.created",
        "task.started",
        "task.completed",
    ]


@pytest.mark.anyio
async def test_task_list_filters_control_and_returns_an_opaque_cursor():
    service = AnsichService.in_memory()
    await service.start()
    observed_at = datetime(2026, 7, 17, 16, 0, tzinfo=UTC)
    for index, terminal_kind in enumerate(("task.completed", "task.failed", "task.completed")):
        task_id = new_id()
        service.record(
            ObservationEnvelope.task_lifecycle(
                kind=terminal_kind,
                task_id=task_id,
                source_kind="deerflow_run",
                source_id=f"run-filter-{index}",
                occurred_at=observed_at,
                source_event_id=f"run:run-filter-{index}:task:terminal:{terminal_kind.removeprefix('task.')}",
            )
        )
        await service.flush_task(task_id)

    app = make_authed_test_app(user_factory=admin_user)
    app.state.ansich_service = service
    app.include_router(ansich_router.router)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            first = await client.get("/api/ansich/tasks?control=completed&limit=1")
            cursor = first.json()["next_cursor"]
            second = await client.get(f"/api/ansich/tasks?control=completed&limit=1&cursor={cursor}")
    finally:
        await service.stop()

    assert first.status_code == 200
    assert [item["control"]["value"] for item in first.json()["items"]] == ["completed"]
    assert cursor
    assert [item["control"]["value"] for item in second.json()["items"]] == ["completed"]
    assert second.json()["items"][0]["task_id"] != first.json()["items"][0]["task_id"]


@pytest.mark.anyio
async def test_regular_user_is_forbidden_from_ansich_operations():
    app = make_authed_test_app(user_factory=regular_user)
    app.state.ansich_service = AnsichService.in_memory()
    app.include_router(ansich_router.router)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/ansich/tasks")

    assert response.status_code == 403


@pytest.mark.anyio
async def test_health_remains_readable_but_task_query_is_503_when_storage_is_unavailable():
    service = create_embedded_ansich_service(AnsichConfig(enabled=True), None)
    assert service is not None
    await service.start()
    app = make_authed_test_app(user_factory=admin_user)
    app.state.ansich_service = service
    app.include_router(ansich_router.router)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            health = await client.get("/api/ansich/health")
            tasks = await client.get("/api/ansich/tasks")
    finally:
        await service.stop()

    assert health.status_code == 200
    assert health.json()["status"] == "failed"
    assert tasks.status_code == 503
    assert tasks.json()["detail"]["projection_status"]["status"] == "failed"
