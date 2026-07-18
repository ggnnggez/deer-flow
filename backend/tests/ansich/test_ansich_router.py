from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from _router_auth_helpers import make_authed_test_app
from ansich import AnsichService, ObservationEnvelope, new_id
from httpx import ASGITransport, AsyncClient
from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool

from app.gateway.auth.models import User
from app.gateway.routers import ansich as ansich_router
from deerflow.agents.middlewares.summarization_middleware import DeerFlowSummarizationMiddleware
from deerflow.ansich import create_embedded_ansich_service
from deerflow.ansich.execution import ANSICH_EXECUTION_CONTEXT_KEY, AnsichExecutionContext
from deerflow.ansich.middleware import AnsichAttemptMiddleware, AnsichDecisionMiddleware
from deerflow.ansich.tool_middleware import AnsichRawToolMiddleware, AnsichVisibleToolMiddleware
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


class _ApiObservedModel(BaseChatModel):
    @property
    def _llm_type(self) -> str:
        return "ansich-api-observed"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="done"))])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


@tool
def _api_observed_tool(value: str) -> str:
    """Return a value for the Ansich ToolCall API test."""
    return value


class _ApiToolThenFinalModel(_ApiObservedModel):
    call_count: int = 0

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.call_count += 1
        if self.call_count == 1:
            return ChatResult(
                generations=[
                    ChatGeneration(
                        message=AIMessage(
                            content="",
                            tool_calls=[
                                {
                                    "id": "api-tool-provider-id",
                                    "name": "_api_observed_tool",
                                    "args": {"value": "api-tool-result"},
                                }
                            ],
                        )
                    )
                ]
            )
        return super()._generate(
            messages,
            stop=stop,
            run_manager=run_manager,
            **kwargs,
        )


async def _record_observed_call(
    service: AnsichService,
    task_id: str,
    *,
    actor_kind: str = "lead_agent",
    operation_kind: str | None = None,
    execution: AnsichExecutionContext | None = None,
) -> AnsichExecutionContext:
    execution = execution or AnsichExecutionContext(task_id=task_id, service=service)
    agent = create_agent(
        model=_ApiObservedModel(),
        tools=[],
        middleware=[
            AnsichDecisionMiddleware(actor_kind=actor_kind, operation_kind=operation_kind),
            AnsichAttemptMiddleware(),
        ],
    )
    await agent.ainvoke(
        {"messages": [HumanMessage(id="api-user", content="inspect me")]},
        context={ANSICH_EXECUTION_CONTEXT_KEY: execution},
    )
    await service.flush_task(task_id)
    return execution


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
async def test_timeline_cursor_is_stable_when_events_share_occurred_at():
    service = AnsichService.in_memory()
    await service.start()
    task_id = new_id()
    occurred_at = datetime(2026, 7, 17, 15, 30, tzinfo=UTC)
    for kind in ("task.created", "task.started", "task.completed"):
        service.record(
            ObservationEnvelope.task_lifecycle(
                kind=kind,
                task_id=task_id,
                source_kind="deerflow_run",
                source_id="run-cursor",
                occurred_at=occurred_at,
                source_event_id=f"run:run-cursor:{kind}",
            )
        )
    await service.flush_task(task_id)
    app = make_authed_test_app(user_factory=admin_user)
    app.state.ansich_service = service
    app.include_router(ansich_router.router)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            first = await client.get(f"/api/ansich/tasks/{task_id}/timeline?limit=2")
            second = await client.get(f"/api/ansich/tasks/{task_id}/timeline?limit=2&cursor={first.json()['next_cursor']}")
    finally:
        await service.stop()

    assert [item["kind"] for item in first.json()["items"]] == ["task.created", "task.started"]
    assert [item["kind"] for item in second.json()["items"]] == ["task.completed"]
    assert first.json()["items"][0]["ingest_seq"] < first.json()["items"][1]["ingest_seq"]


@pytest.mark.anyio
async def test_step_context_inventory_and_raw_payload_are_separate(caplog):
    caplog.set_level("INFO", logger=ansich_router.__name__)
    service = AnsichService.in_memory()
    await service.start()
    task_id = new_id()
    service.record(
        ObservationEnvelope.task_lifecycle(
            kind="task.created",
            task_id=task_id,
            source_kind="deerflow_run",
            source_id="run-step-api",
            occurred_at=datetime.now(UTC),
            source_event_id="run:run-step-api:created",
        )
    )
    await service.flush_task(task_id)
    execution = await _record_observed_call(service, task_id)
    await _record_observed_call(
        service,
        task_id,
        actor_kind="system_operation",
        operation_kind="summarization",
        execution=execution,
    )
    app = make_authed_test_app(user_factory=admin_user)
    app.state.ansich_service = service
    app.include_router(ansich_router.router)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            steps_response = await client.get(f"/api/ansich/tasks/{task_id}/steps")
            step_id = steps_response.json()["items"][0]["step_id"]
            step_response = await client.get(f"/api/ansich/steps/{step_id}")
            context_response = await client.get(f"/api/ansich/steps/{step_id}/context")
            snapshot_id = context_response.json()["context"]["snapshot_id"]
            snapshot_response = await client.get(f"/api/ansich/context-snapshots/{snapshot_id}")
            context_item = context_response.json()["context"]["items"][0]
            payload_response = await client.get(f"/api/ansich/content-blocks/{context_item['block_id']}/payload")
    finally:
        await service.stop()

    assert steps_response.status_code == 200
    assert len(steps_response.json()["items"]) == 1
    assert len(steps_response.json()["system_operations"]) == 1
    assert steps_response.json()["system_operations"][0]["operation_kind"] == "summarization"
    assert step_response.json()["step"]["attempts"][0]["effective"] is True
    assert snapshot_response.status_code == 200
    assert snapshot_response.json()["context"]["snapshot_id"] == snapshot_id
    assert all(item["body"] is None for item in snapshot_response.json()["context"]["items"])
    assert context_item["body"] is None
    assert payload_response.json()["payload"]["body"] == "inspect me"
    assert payload_response.headers["cache-control"] == "no-store"
    assert "Ansich raw content payload accessed" in caplog.text


@pytest.mark.anyio
async def test_tool_call_inventory_and_raw_visible_payloads_use_separate_endpoints(
    caplog,
):
    caplog.set_level("INFO", logger=ansich_router.__name__)
    service = AnsichService.in_memory()
    await service.start()
    task_id = new_id()
    service.record(
        ObservationEnvelope.task_lifecycle(
            kind="task.created",
            task_id=task_id,
            source_kind="deerflow_run",
            source_id="run-tool-api",
            occurred_at=datetime.now(UTC),
            source_event_id="run:run-tool-api:created",
        )
    )
    await service.flush_task(task_id)
    execution = AnsichExecutionContext(task_id=task_id, service=service)
    agent = create_agent(
        model=_ApiToolThenFinalModel(),
        tools=[_api_observed_tool],
        middleware=[
            AnsichDecisionMiddleware(),
            AnsichVisibleToolMiddleware(),
            AnsichRawToolMiddleware(),
            AnsichAttemptMiddleware(),
        ],
    )
    await agent.ainvoke(
        {"messages": [HumanMessage(content="inspect tool accountability")]},
        context={ANSICH_EXECUTION_CONTEXT_KEY: execution},
    )
    await service.flush_task(task_id)
    tool_call_id = (await service.list_steps(task_id))[0].tool_calls[0].tool_call_id
    app = make_authed_test_app(user_factory=admin_user)
    app.state.ansich_service = service
    app.include_router(ansich_router.router)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            inventory = await client.get(f"/api/ansich/tool-calls/{tool_call_id}")
            raw = await client.get(f"/api/ansich/tool-calls/{tool_call_id}/raw-result")
            visible = await client.get(f"/api/ansich/tool-calls/{tool_call_id}/visible-result")
    finally:
        await service.stop()

    assert inventory.status_code == 200
    assert inventory.json()["tool_call"]["execution"]["value"] == "returned"
    assert "body" not in inventory.text
    assert raw.status_code == 200
    assert raw.json()["raw_payload"]["body"]["content"] == "api-tool-result"
    assert raw.headers["cache-control"] == "no-store"
    assert visible.status_code == 200
    assert visible.json()["visible_payload"]["body"]["content"] == "api-tool-result"
    assert visible.headers["cache-control"] == "no-store"
    assert "Ansich raw tool result accessed" in caplog.text
    assert "Ansich visible tool result accessed" in caplog.text


@pytest.mark.anyio
async def test_admin_can_lazy_load_backward_content_lineage_without_raw_payloads() -> None:
    service = AnsichService.in_memory()
    await service.start()
    task_id = new_id()
    service.record(
        ObservationEnvelope.task_lifecycle(
            kind="task.created",
            task_id=task_id,
            source_kind="deerflow_run",
            source_id="run-lineage-api",
            occurred_at=datetime.now(UTC),
            source_event_id="run:run-lineage-api:created",
        )
    )
    await service.flush_task(task_id)
    execution = AnsichExecutionContext(task_id=task_id, service=service)
    agent = create_agent(
        model=_ApiToolThenFinalModel(),
        tools=[_api_observed_tool],
        middleware=[
            AnsichDecisionMiddleware(),
            AnsichVisibleToolMiddleware(),
            AnsichRawToolMiddleware(),
            AnsichAttemptMiddleware(),
        ],
    )
    await agent.ainvoke(
        {"messages": [HumanMessage(content="inspect lineage lazily")]},
        context={ANSICH_EXECUTION_CONTEXT_KEY: execution},
    )
    await service.flush_task(task_id)
    tool_call = (await service.list_steps(task_id))[0].tool_calls[0]
    visible_block_id = tool_call.visible_results[-1].content_block_id
    raw_block_id = tool_call.raw_results[-1].content_block_id
    app = make_authed_test_app(user_factory=admin_user)
    app.state.ansich_service = service
    app.include_router(ansich_router.router)

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get(
                f"/api/ansich/content-blocks/{visible_block_id}/lineage",
                params={"direction": "backward", "depth": 8, "nodes": 500},
            )
            exposures_response = await client.get(
                f"/api/ansich/content-blocks/{raw_block_id}/exposures",
                params={"depth": 8, "nodes": 500},
            )
    finally:
        await service.stop()

    assert response.status_code == 200
    lineage = response.json()["lineage"]
    assert lineage["semantic"] == "provenance"
    assert [node["block_id"] for node in lineage["nodes"]] == [
        visible_block_id,
        raw_block_id,
    ]
    assert lineage["truncated"] is False
    assert "body" not in response.text
    assert exposures_response.status_code == 200
    exposures = exposures_response.json()["exposures"]
    assert exposures["semantic"] == "possible_exposure"
    assert exposures["items"]
    assert all(item["descendant_depth"] == 2 for item in exposures["items"])
    assert any(edge["derived_block_id"] == visible_block_id and edge["source_block_id"] == raw_block_id for edge in exposures["edges"])
    assert all(item["ordering"] in {"later", "unknown"} for item in exposures["items"])
    assert "body" not in exposures_response.text


@pytest.mark.anyio
async def test_admin_can_lazy_load_typed_context_compression_without_raw_payloads() -> None:
    service = AnsichService.in_memory()
    await service.start()
    task_id = new_id()
    execution = AnsichExecutionContext(task_id=task_id, service=service)
    model = MagicMock()
    model.with_config.return_value = model
    model.invoke.return_value = SimpleNamespace(text="compressed for operations")
    middleware = DeerFlowSummarizationMiddleware(
        model=model,
        trigger=("messages", 4),
        keep=("messages", 2),
        token_counter=len,
    )
    result = middleware.compact_state(
        {
            "messages": [
                HumanMessage(id="compression-old-user", content="old user"),
                AIMessage(id="compression-old-ai", content="old answer"),
                HumanMessage(id="compression-new-user", content="new user"),
                AIMessage(id="compression-new-ai", content="new answer"),
            ]
        },
        SimpleNamespace(
            context={ANSICH_EXECUTION_CONTEXT_KEY: execution},
        ),
        force=True,
    )
    assert result is not None
    await service.flush_task(task_id)
    compression_id = next(observation.subject_id for observation in await service.list_observations(task_id) if observation.kind == "context.compressed")
    app = make_authed_test_app(user_factory=admin_user)
    app.state.ansich_service = service
    app.include_router(ansich_router.router)

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get(f"/api/ansich/context-compressions/{compression_id}")
    finally:
        await service.stop()

    assert response.status_code == 200
    compression = response.json()["compression"]
    assert compression["compression_id"] == compression_id
    assert compression["summary_block"]["kind"] == "summary"
    assert [item["disposition"] for item in compression["items"]] == [
        "source",
        "source",
        "preserved",
        "preserved",
        "removed",
        "removed",
    ]
    assert "body" not in response.text


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
        raw_response = await client.get(f"/api/ansich/content-blocks/{new_id()}/payload")
        tool_response = await client.get(f"/api/ansich/tool-calls/{new_id()}")
        tool_raw_response = await client.get(f"/api/ansich/tool-calls/{new_id()}/raw-result")
        tool_visible_response = await client.get(f"/api/ansich/tool-calls/{new_id()}/visible-result")
        compression_response = await client.get(f"/api/ansich/context-compressions/{new_id()}")
        exposures_response = await client.get(f"/api/ansich/content-blocks/{new_id()}/exposures")
        snapshot_response = await client.get(f"/api/ansich/context-snapshots/{new_id()}")
        active_response = await client.get("/api/ansich/operations/active-tasks")
        usage_response = await client.get(f"/api/ansich/tasks/{new_id()}/usage")
        budgets_response = await client.get(f"/api/ansich/tasks/{new_id()}/budgets")

    assert response.status_code == 403
    assert raw_response.status_code == 403
    assert tool_response.status_code == 403
    assert tool_raw_response.status_code == 403
    assert tool_visible_response.status_code == 403
    assert compression_response.status_code == 403
    assert exposures_response.status_code == 403
    assert snapshot_response.status_code == 403
    assert active_response.status_code == 403
    assert usage_response.status_code == 403
    assert budgets_response.status_code == 403


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


@pytest.mark.anyio
async def test_timeline_polling_response_never_carries_raw_content_bodies():
    """Raw ContentBlock bodies must only leave through the logged raw-payload endpoint (H1)."""
    service = AnsichService.in_memory()
    await service.start()
    task_id = new_id()
    service.record(
        ObservationEnvelope.task_lifecycle(
            kind="task.created",
            task_id=task_id,
            source_kind="deerflow_run",
            source_id="run-timeline-bodies",
            occurred_at=datetime.now(UTC),
            source_event_id="run:run-timeline-bodies:created",
        )
    )
    await service.flush_task(task_id)
    await _record_observed_call(service, task_id)
    app = make_authed_test_app(user_factory=admin_user)
    app.state.ansich_service = service
    app.include_router(ansich_router.router)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/ansich/tasks/{task_id}/timeline")
    finally:
        await service.stop()

    assert response.status_code == 200
    content_items = [item for item in response.json()["items"] if item["kind"] == "content.produced"]
    assert content_items
    for item in content_items:
        assert item["payload"] is not None
        assert "body" not in item["payload"]
        assert "content_hash" in item["payload"]
    assert "inspect me" not in response.text
