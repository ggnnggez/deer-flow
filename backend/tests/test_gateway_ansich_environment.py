"""Gateway API read side for Task 10: task environment, alert filter, ToolCall additive field.

Assembly idiom copied from ``tests/ansich/test_ansich_operations_router.py``:
a real SQL-backed ``AnsichService`` (the environment read joins projected
coverage/state/belief/alert rows, which the in-memory backend does not
materialize) driving a bare FastAPI app that mounts only the Ansich router,
with ``make_authed_test_app`` stamping a fake admin/non-admin user.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from _router_auth_helpers import make_authed_test_app
from ansich import ObservationEnvelope, Producer, new_id
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from support.ansich_settle import only_test_driven_assessments

from app.gateway.auth.models import User
from app.gateway.routers import ansich as ansich_router
from deerflow.ansich import create_sql_ansich_service
from deerflow.persistence.base import Base

_STARTED_AT = datetime(2026, 8, 19, 10, tzinfo=UTC)
_SCOPE_KIND = "sandbox"


def _admin_user() -> User:
    return User(id=uuid4(), email="ansich-env-admin@example.com", password_hash="x", system_role="admin")


def _regular_user() -> User:
    return User(id=uuid4(), email="ansich-env-user@example.com", password_hash="x", system_role="user")


async def _service(tmp_path, database_name: str, **overrides: object):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / database_name}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    settings: dict[str, object] = {
        "flush_interval_ms": 60_000,
        "terminal_flush_timeout_ms": 10_000,
        "projector_poll_interval_ms": 5,
        "operations_assessment_interval_ms": 60_000,
    }
    settings.update(overrides)
    service = create_sql_ansich_service(session_factory, **settings)
    only_test_driven_assessments(service)
    await service.start()
    return service, engine


def _task_created(task_id: str, run_id: str) -> ObservationEnvelope:
    return ObservationEnvelope.task_lifecycle(
        kind="task.created",
        task_id=task_id,
        source_kind="deerflow_run",
        source_id=run_id,
        occurred_at=_STARTED_AT,
        source_event_id=f"run:{run_id}:task:created",
    )


def _task_started(task_id: str, run_id: str) -> ObservationEnvelope:
    return ObservationEnvelope.task_lifecycle(
        kind="task.started",
        task_id=task_id,
        source_kind="deerflow_run",
        source_id=run_id,
        occurred_at=_STARTED_AT,
        source_event_id=f"run:{run_id}:task:started",
    )


def _scope_snapshotted(task_id: str, run_id: str, *, external_ref: str) -> ObservationEnvelope:
    return ObservationEnvelope.scope_snapshotted(
        task_id=task_id,
        run_id=run_id,
        occurred_at=_STARTED_AT,
        scope_kind=_SCOPE_KIND,
        external_ref=external_ref,
        relation_role="sandbox_boundary",
        source_event_id=f"run:{run_id}:scope:{external_ref}",
    )


def _environment_sampled(
    task_id: str,
    run_id: str,
    *,
    scope_id: str,
    tick: int,
    occurred_at: datetime,
    metrics: dict[str, dict[str, int | None]] | None = None,
    coverage: str = "continuous",
    environment_scope: str = "container",
    sample_count: int = 1,
    tool_call_id: str | None = None,
) -> ObservationEnvelope:
    payload: dict[str, object] = {
        "environment_scope": environment_scope,
        "coverage": coverage,
        "provider": "local",
        "metrics": metrics or {},
        "window": {
            "started_at": _STARTED_AT.isoformat(),
            "ended_at": occurred_at.isoformat(),
            "sample_count": sample_count,
        },
    }
    if tool_call_id is not None:
        payload["tool_call_id"] = tool_call_id
    return ObservationEnvelope.environment_sampled(
        task_id=task_id,
        run_id=run_id,
        occurred_at=occurred_at,
        scope_id=scope_id,
        payload=payload,
        source_event_id=f"run:{run_id}:env:{scope_id}:{tick}",
        producer_seq=tick,
        producer_name="deerflow-environment-probe",
    )


def _fd(value: int, limit: int | None = 1024) -> dict[str, dict[str, int | None]]:
    return {"fd_open": {"value": value, "limit": limit}}


@pytest.mark.anyio
async def test_task_environment_returns_scope_card_end_to_end(tmp_path) -> None:
    task_id, run_id = new_id(), "env-e2e-run"
    scope_id = ObservationEnvelope.scope_snapshotted(
        task_id=task_id,
        run_id=run_id,
        occurred_at=_STARTED_AT,
        scope_kind=_SCOPE_KIND,
        external_ref="local:thread-e2e",
        relation_role="sandbox_boundary",
        source_event_id=f"run:{run_id}:scope",
    ).subject_id

    service, engine = await _service(tmp_path, "ansich-env-e2e.db")
    try:
        service.record_batch(
            (
                _task_created(task_id, run_id),
                _task_started(task_id, run_id),
                _scope_snapshotted(task_id, run_id, external_ref="local:thread-e2e"),
                _environment_sampled(
                    task_id,
                    run_id,
                    scope_id=scope_id,
                    tick=1,
                    occurred_at=_STARTED_AT + timedelta(seconds=10),
                    metrics=_fd(100),
                ),
            )
        )
        await service.flush_task(task_id)
        await service.assess_operations(now=_STARTED_AT + timedelta(seconds=11))

        app = make_authed_test_app(user_factory=_admin_user)
        app.state.ansich_service = service
        app.include_router(ansich_router.router)
        empty_task_id = new_id()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            populated = await client.get(f"/api/ansich/tasks/{task_id}/environment")
            empty = await client.get(f"/api/ansich/tasks/{empty_task_id}/environment")
    finally:
        await service.stop()
        await engine.dispose()

    assert populated.status_code == 200
    body = populated.json()
    assert body["task_id"] == task_id
    assert len(body["scopes"]) == 1
    card = body["scopes"][0]
    assert card["scope_id"] == scope_id
    assert card["environment_scope"] == "container"
    assert card["coverage"] == "continuous"
    assert card["provider"] == "local"
    assert len(card["metrics"]) == 1
    metric = card["metrics"][0]
    assert metric["metric"] == "fd_open"
    assert metric["latest_value"] == 100
    assert metric["limit"] == 1024
    beliefs_by_field = {belief["field_name"]: belief for belief in card["beliefs"]}
    pressure = beliefs_by_field["environment_pressure:fd_open"]
    assert pressure["value"]["value"] == "ok"
    assert pressure["source"] == {"name": "environment-pressure", "version": "1"}
    assert pressure["evidence_obs_ids"]

    assert empty.status_code == 200
    assert empty.json() == {"task_id": empty_task_id, "scopes": []}


@pytest.mark.anyio
async def test_uninstrumented_scope_belief_synthesizes_full_unknown(tmp_path) -> None:
    task_id, run_id = new_id(), "env-unknown-run"
    scope_id = ObservationEnvelope.scope_snapshotted(
        task_id=task_id,
        run_id=run_id,
        occurred_at=_STARTED_AT,
        scope_kind=_SCOPE_KIND,
        external_ref="local:thread-unknown",
        relation_role="sandbox_boundary",
        source_event_id=f"run:{run_id}:scope",
    ).subject_id

    service, engine = await _service(tmp_path, "ansich-env-unknown.db")
    try:
        service.record_batch(
            (
                _task_created(task_id, run_id),
                _task_started(task_id, run_id),
                _scope_snapshotted(task_id, run_id, external_ref="local:thread-unknown"),
                _environment_sampled(
                    task_id,
                    run_id,
                    scope_id=scope_id,
                    tick=1,
                    occurred_at=_STARTED_AT + timedelta(seconds=10),
                    metrics=None,
                    coverage="uninstrumented",
                    sample_count=0,
                ),
            )
        )
        await service.flush_task(task_id)
        # Deliberately no assess_operations() call: the Belief must be
        # synthesized from the coverage row alone, not read from a real
        # Assertion.

        app = make_authed_test_app(user_factory=_admin_user)
        app.state.ansich_service = service
        app.include_router(ansich_router.router)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/ansich/tasks/{task_id}/environment")
    finally:
        await service.stop()
        await engine.dispose()

    assert response.status_code == 200
    card = response.json()["scopes"][0]
    assert card["coverage"] == "uninstrumented"
    assert card["metrics"] == []
    assert len(card["beliefs"]) == 1
    belief = card["beliefs"][0]
    assert belief["field_name"] == "environment_pressure:fd_open"
    assert belief["value"] == {
        "value": "unknown",
        "metric": "fd_open",
        "environment_scope": "container",
        "coverage": "uninstrumented",
    }
    assert belief["evidence_obs_ids"] == []
    assert belief["source"] == {"name": "none", "version": "1"}
    assert belief["authority_class"] == "unknown"
    assert belief["fidelity_class"] == "unknown"
    assert belief["as_of"] is None
    assert belief["asserted_at"] is None


@pytest.mark.anyio
async def test_alert_filter_accepts_environment_types_and_rejects_unknown(tmp_path) -> None:
    task_id, run_id = new_id(), "env-alert-run"
    scope_id = ObservationEnvelope.scope_snapshotted(
        task_id=task_id,
        run_id=run_id,
        occurred_at=_STARTED_AT,
        scope_kind=_SCOPE_KIND,
        external_ref="local:thread-alert",
        relation_role="sandbox_boundary",
        source_event_id=f"run:{run_id}:scope",
    ).subject_id

    service, engine = await _service(tmp_path, "ansich-env-alert.db")
    try:
        service.record_batch(
            (
                _task_created(task_id, run_id),
                _task_started(task_id, run_id),
                _scope_snapshotted(task_id, run_id, external_ref="local:thread-alert"),
                _environment_sampled(
                    task_id,
                    run_id,
                    scope_id=scope_id,
                    tick=1,
                    occurred_at=_STARTED_AT + timedelta(seconds=10),
                    metrics=_fd(990),
                ),
            )
        )
        await service.flush_task(task_id)
        await service.assess_operations(now=_STARTED_AT + timedelta(seconds=11))

        app = make_authed_test_app(user_factory=_admin_user)
        app.state.ansich_service = service
        app.include_router(ansich_router.router)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            filtered = await client.get("/api/ansich/operations/alerts?type=environment_pressure")
            invalid = await client.get("/api/ansich/operations/alerts?type=not_a_real_alert_type")
    finally:
        await service.stop()
        await engine.dispose()

    assert filtered.status_code == 200
    items = filtered.json()["items"]
    assert items
    assert all(item["alert_type"] == "environment_pressure" for item in items)
    assert invalid.status_code == 422


@pytest.mark.anyio
async def test_tool_call_detail_has_additive_environment_sample_with_and_without_data(tmp_path) -> None:
    task_id, run_id = new_id(), "env-toolcall-run"
    step_id = new_id()
    sampled_tool_call_id = new_id()
    bare_tool_call_id = new_id()
    producer = Producer(name="env-toolcall-test", version="1", instance_id="test")
    scope_id = ObservationEnvelope.scope_snapshotted(
        task_id=task_id,
        run_id=run_id,
        occurred_at=_STARTED_AT,
        scope_kind=_SCOPE_KIND,
        external_ref="local:thread-toolcall",
        relation_role="sandbox_boundary",
        source_event_id=f"run:{run_id}:scope",
    ).subject_id

    def _tool_issued(tool_call_id: str, call_seq: int) -> ObservationEnvelope:
        return ObservationEnvelope(
            kind="tool.issued",
            occurred_at=_STARTED_AT,
            task_id=task_id,
            step_id=step_id,
            subject_type="tool_call",
            subject_id=tool_call_id,
            producer=producer,
            source_event_id=f"run:{run_id}:tool:issued:{call_seq}",
            correlation_id=task_id,
            payload={
                "call_seq": call_seq,
                "provider_call_id": f"provider-{call_seq}",
                "tool_name": "bash",
                "args_hash": "a" * 64,
                "args_preview": {"command": "ls"},
                "tool_schema_block_id": None,
            },
        )

    sample = _environment_sampled(
        task_id,
        run_id,
        scope_id=scope_id,
        tick=1,
        occurred_at=_STARTED_AT + timedelta(seconds=5),
        coverage="per_command",
        environment_scope="process_group",
        sample_count=3,
        tool_call_id=sampled_tool_call_id,
        metrics={
            "fd_open": {"value": 12, "limit": None},
            "io_read_bytes": {"value": 2048, "limit": None},
            "io_write_bytes": {"value": 256, "limit": None},
        },
    )

    service, engine = await _service(tmp_path, "ansich-env-toolcall.db")
    try:
        service.record_batch(
            (
                _task_created(task_id, run_id),
                _task_started(task_id, run_id),
                _scope_snapshotted(task_id, run_id, external_ref="local:thread-toolcall"),
                ObservationEnvelope(
                    kind="step.started",
                    occurred_at=_STARTED_AT,
                    task_id=task_id,
                    step_id=step_id,
                    subject_type="step",
                    subject_id=step_id,
                    producer=producer,
                    source_event_id=f"run:{run_id}:step:started",
                    correlation_id=task_id,
                    payload={"step_seq": 1, "actor_kind": "lead_agent"},
                ),
                _tool_issued(sampled_tool_call_id, 1),
                _tool_issued(bare_tool_call_id, 2),
                sample,
            )
        )
        await service.flush_task(task_id)

        app = make_authed_test_app(user_factory=_admin_user)
        app.state.ansich_service = service
        app.include_router(ansich_router.router)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            with_sample = await client.get(f"/api/ansich/tool-calls/{sampled_tool_call_id}")
            without_sample = await client.get(f"/api/ansich/tool-calls/{bare_tool_call_id}")
    finally:
        await service.stop()
        await engine.dispose()

    assert with_sample.status_code == 200
    body = with_sample.json()
    assert body["tool_call"]["tool_call_id"] == sampled_tool_call_id
    env_sample = body["environment_sample"]
    assert env_sample is not None
    assert env_sample["tool_call_id"] == sampled_tool_call_id
    assert env_sample["task_id"] == task_id
    assert env_sample["scope_id"] == scope_id
    assert env_sample["io_read_bytes"] == 2048
    assert env_sample["io_write_bytes"] == 256
    assert env_sample["fd_peak"] == 12
    assert env_sample["sample_count"] == 3
    assert env_sample["obs_id"] == sample.obs_id

    assert without_sample.status_code == 200
    assert without_sample.json()["environment_sample"] is None
    # Additive: the pre-existing field is untouched.
    assert without_sample.json()["tool_call"]["tool_call_id"] == bare_tool_call_id


@pytest.mark.anyio
async def test_regular_user_is_forbidden_from_task_environment(tmp_path) -> None:
    service, engine = await _service(tmp_path, "ansich-env-forbidden.db")
    try:
        app = make_authed_test_app(user_factory=_regular_user)
        app.state.ansich_service = service
        app.include_router(ansich_router.router)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/ansich/tasks/{new_id()}/environment")
    finally:
        await service.stop()
        await engine.dispose()

    assert response.status_code == 403
