import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from ansich import AnsichService, ContextStateItem, ObservationEnvelope, Producer, new_id
from ansich.context_state import build_context_state_delta, context_state_hash
from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from sqlalchemy import create_engine, delete, event, func, inspect, select, text
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from deerflow.ansich import create_sql_ansich_service
from deerflow.ansich.execution import ANSICH_EXECUTION_CONTEXT_KEY, AnsichExecutionContext
from deerflow.ansich.middleware import AnsichAttemptMiddleware, AnsichDecisionMiddleware
from deerflow.ansich.persistence.models import (
    AnsichAssessorJobRow,
    AnsichBeliefAssertionRow,
    AnsichContentOccurrenceRow,
    AnsichContextSnapshotItemRow,
    AnsichContextStateCheckpointItemRow,
    AnsichContextStateDeltaRow,
    AnsichContextStateRow,
    AnsichLlmAttemptRow,
    AnsichObservationRow,
    AnsichPayloadRow,
    AnsichProjectionErrorRow,
    AnsichProjectionJobRow,
    AnsichRelationRow,
    AnsichScopeRow,
    AnsichTaskSummaryRow,
)
from deerflow.ansich.persistence.sql import SqlAnsichBackend, _list_task_views_statement
from deerflow.ansich.tool_middleware import AnsichRawToolMiddleware, AnsichVisibleToolMiddleware
from deerflow.persistence.base import Base


class _ObservedFinalModel(BaseChatModel):
    @property
    def _llm_type(self) -> str:
        return "ansich-sql-observed"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(
            generations=[
                ChatGeneration(
                    message=AIMessage(
                        content="done",
                        usage_metadata={"input_tokens": 4, "output_tokens": 2, "total_tokens": 6},
                        response_metadata={"finish_reason": "stop", "model_name": "observed-model"},
                    )
                )
            ]
        )

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


@tool
def _sql_observed_tool(value: str) -> str:
    """Return a value for SQL ToolCall projection tests."""
    return value


class _SqlToolThenFinalModel(_ObservedFinalModel):
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
                                    "id": "provider-reused-id",
                                    "name": "_sql_observed_tool",
                                    "args": {"value": "sql-result"},
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


@pytest.mark.anyio
async def test_context_snapshot_projects_with_sqlite_foreign_keys_enabled(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-context-foreign-keys.db'}")

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    task_id = new_id()
    service = create_sql_ansich_service(session_factory)
    await service.start()
    service.record(
        ObservationEnvelope.task_lifecycle(
            kind="task.created",
            task_id=task_id,
            source_kind="deerflow_run",
            source_id="run-context-foreign-keys",
            occurred_at=datetime.now(UTC),
            source_event_id="run:context-foreign-keys:created",
        )
    )
    await service.flush_task(task_id)
    execution = AnsichExecutionContext(task_id=task_id, service=service)
    agent = create_agent(
        model=_ObservedFinalModel(),
        tools=[],
        middleware=[AnsichDecisionMiddleware(), AnsichAttemptMiddleware()],
    )

    try:
        await agent.ainvoke(
            {"messages": [HumanMessage(content="capture this request")]},
            context={ANSICH_EXECUTION_CONTEXT_KEY: execution},
        )
        await service.flush_task(task_id)
        step = (await service.list_steps(task_id))[0]
        context = await service.get_step_context(step.step_id)
        health = service.get_health()
    finally:
        await service.stop()
        await engine.dispose()

    assert context is not None
    assert context.items[0].kind == "user_input"
    assert health.failed_jobs == 0


@pytest.mark.anyio
async def test_tool_call_projection_survives_restart_and_rebuild_without_usage_duplication(
    tmp_path,
):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-tool.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    task_id = new_id()
    service = create_sql_ansich_service(session_factory)
    await service.start()
    service.record(
        ObservationEnvelope.task_lifecycle(
            kind="task.created",
            task_id=task_id,
            source_kind="deerflow_run",
            source_id="run-tool-projection",
            occurred_at=datetime.now(UTC),
            source_event_id="run:tool-projection:created",
        )
    )
    await service.flush_task(task_id)
    execution = AnsichExecutionContext(task_id=task_id, service=service)
    agent = create_agent(
        model=_SqlToolThenFinalModel(),
        tools=[_sql_observed_tool],
        middleware=[
            AnsichDecisionMiddleware(),
            AnsichVisibleToolMiddleware(),
            AnsichRawToolMiddleware(),
            AnsichAttemptMiddleware(),
        ],
    )

    await agent.ainvoke(
        {"messages": [HumanMessage(content="use SQL tool")]},
        context={ANSICH_EXECUTION_CONTEXT_KEY: execution},
    )
    await service.flush_task(task_id)
    before_task = await service.get_task(task_id)
    before_step = (await service.list_steps(task_id))[0]
    tool_call_id = before_step.tool_calls[0].tool_call_id
    before_tool_call = await service.get_tool_call(tool_call_id)
    await service.stop()

    restarted = create_sql_ansich_service(session_factory)
    await restarted.start()
    try:
        restarted_tool_call = await restarted.get_tool_call(tool_call_id)
        assert await restarted.rebuild_projections() > 0
        rebuilt_task = await restarted.get_task(task_id)
        rebuilt_tool_call = await restarted.get_tool_call(tool_call_id)
    finally:
        await restarted.stop()
        await engine.dispose()

    assert before_task is not None
    assert before_task.tool_calls_issued == 1
    assert before_task.tool_calls_executed == 1
    assert before_tool_call is not None
    assert before_tool_call.execution.value == "returned"
    assert before_tool_call.visible_result.value == "available"
    assert restarted_tool_call == before_tool_call
    assert rebuilt_tool_call == before_tool_call
    assert rebuilt_task is not None
    assert rebuilt_task.tool_calls_issued == 1
    assert rebuilt_task.tool_calls_executed == 1


@pytest.mark.anyio
async def test_tool_projection_repairs_raw_and_visible_observations_that_arrive_before_issued(
    tmp_path,
):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-tool-out-of-order.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(session_factory)
    await service.start()
    task_id = new_id()
    step_id = new_id()
    raw_tool_id = new_id()
    visible_tool_id = new_id()
    raw_block_id = new_id()
    visible_block_id = new_id()
    producer = Producer(name="out-of-order-tool", version="1", instance_id="test")
    observed_at = datetime.now(UTC)
    service.record(
        ObservationEnvelope.task_lifecycle(
            kind="task.created",
            task_id=task_id,
            source_kind="deerflow_run",
            source_id="run-tool-out-of-order",
            occurred_at=observed_at,
            source_event_id="run:tool-out-of-order:created",
        )
    )
    await service.flush_task(task_id)
    observations = [
        ObservationEnvelope(
            kind="step.started",
            occurred_at=observed_at,
            task_id=task_id,
            step_id=step_id,
            subject_type="step",
            subject_id=step_id,
            producer=producer,
            producer_seq=1,
            source_event_id="tool-out-of-order:step",
            correlation_id=task_id,
            payload={"step_seq": 1, "actor_kind": "lead_agent"},
        ),
        _tool_content_observation(
            task_id=task_id,
            step_id=step_id,
            block_id=raw_block_id,
            producer=producer,
            producer_seq=2,
            source_event_id="tool-out-of-order:raw-content",
            kind="tool_result_raw",
            body={"content": "raw first"},
        ),
        ObservationEnvelope(
            kind="tool.returned_raw",
            occurred_at=observed_at,
            task_id=task_id,
            step_id=step_id,
            subject_type="tool_call",
            subject_id=raw_tool_id,
            producer=producer,
            producer_seq=3,
            source_event_id="tool-out-of-order:raw-terminal",
            correlation_id=task_id,
            payload={
                "call_seq": 1,
                "result_block_id": raw_block_id,
                "duration_ms": 7,
            },
        ),
        ObservationEnvelope(
            kind="tool.issued",
            occurred_at=observed_at,
            task_id=task_id,
            step_id=step_id,
            subject_type="tool_call",
            subject_id=raw_tool_id,
            producer=producer,
            producer_seq=4,
            source_event_id="tool-out-of-order:raw-issued",
            correlation_id=task_id,
            payload={
                "call_seq": 1,
                "provider_call_id": "provider-raw-first",
                "tool_name": "raw_first",
                "args_hash": "a" * 64,
                "args_preview": {"value": "safe"},
                "tool_schema_block_id": None,
            },
        ),
        ObservationEnvelope(
            kind="tool.started",
            occurred_at=observed_at,
            task_id=task_id,
            step_id=step_id,
            subject_type="tool_call",
            subject_id=raw_tool_id,
            producer=producer,
            producer_seq=5,
            source_event_id="tool-out-of-order:raw-started-late",
            correlation_id=task_id,
            payload={"call_seq": 1},
        ),
        _tool_content_observation(
            task_id=task_id,
            step_id=step_id,
            block_id=visible_block_id,
            producer=producer,
            producer_seq=6,
            source_event_id="tool-out-of-order:visible-content",
            kind="tool_result_visible",
            body={"content": "visible first"},
        ),
        ObservationEnvelope(
            kind="tool.result_visible",
            occurred_at=observed_at,
            task_id=task_id,
            step_id=step_id,
            subject_type="tool_call",
            subject_id=visible_tool_id,
            producer=producer,
            producer_seq=7,
            source_event_id="tool-out-of-order:visible-result",
            correlation_id=task_id,
            payload={
                "call_seq": 2,
                "result_block_id": visible_block_id,
                "source_block_id": None,
                "transform_kind": "unknown",
                "transform_version": "1",
            },
        ),
        ObservationEnvelope(
            kind="tool.issued",
            occurred_at=observed_at,
            task_id=task_id,
            step_id=step_id,
            subject_type="tool_call",
            subject_id=visible_tool_id,
            producer=producer,
            producer_seq=8,
            source_event_id="tool-out-of-order:visible-issued",
            correlation_id=task_id,
            payload={
                "call_seq": 2,
                "provider_call_id": "provider-visible-first",
                "tool_name": "visible_first",
                "args_hash": "b" * 64,
                "args_preview": {},
                "tool_schema_block_id": None,
            },
        ),
    ]
    for observation in observations:
        service.record(observation)

    try:
        await service.flush_task(task_id)
        step = await service.get_step(step_id)
        task = await service.get_task(task_id)
        assert await service.rebuild_projections() > 0
        rebuilt_step = await service.get_step(step_id)
        rebuilt_task = await service.get_task(task_id)
    finally:
        await service.stop()
        await engine.dispose()

    assert step is not None
    assert [item.tool_name for item in step.tool_calls] == [
        "raw_first",
        "visible_first",
    ]
    assert step.tool_calls[0].execution.value == "returned"
    assert step.tool_calls[0].raw_results[0].content_block_id == raw_block_id
    assert step.tool_calls[1].execution.value == "issued"
    assert step.tool_calls[1].visible_result.value == "available"
    assert step.tool_calls[1].visible_results[0].content_block_id == visible_block_id
    assert task is not None
    assert (task.tool_calls_issued, task.tool_calls_executed) == (2, 1)
    assert rebuilt_step == step
    assert rebuilt_task == task


def _tool_content_observation(
    *,
    task_id: str,
    step_id: str,
    block_id: str,
    producer: Producer,
    producer_seq: int,
    source_event_id: str,
    kind: str,
    body: object,
) -> ObservationEnvelope:
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return ObservationEnvelope(
        kind="content.produced",
        occurred_at=datetime.now(UTC),
        task_id=task_id,
        step_id=step_id,
        subject_type="content_block",
        subject_id=block_id,
        producer=producer,
        producer_seq=producer_seq,
        source_event_id=source_event_id,
        correlation_id=task_id,
        payload={
            "kind": kind,
            "content_hash": hashlib.sha256(encoded).hexdigest(),
            "body": body,
            "visible_bytes": len(encoded),
            "estimated_tokens": 1,
            "sensitivity_flags": [],
        },
    )


@pytest.mark.anyio
async def test_conflicting_tool_terminal_evidence_is_preserved_and_degrades_task_health(
    tmp_path,
):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-tool-conflict.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(session_factory)
    await service.start()
    task_id = new_id()
    step_id = new_id()
    tool_call_id = new_id()
    producer = Producer(name="tool-conflict", version="1", instance_id="test")
    observed_at = datetime.now(UTC)
    service.record(
        ObservationEnvelope.task_lifecycle(
            kind="task.created",
            task_id=task_id,
            source_kind="deerflow_run",
            source_id="run-tool-conflict",
            occurred_at=observed_at,
            source_event_id="run:tool-conflict:created",
        )
    )
    await service.flush_task(task_id)
    observations = [
        ObservationEnvelope(
            kind="step.started",
            occurred_at=observed_at,
            task_id=task_id,
            step_id=step_id,
            subject_type="step",
            subject_id=step_id,
            producer=producer,
            producer_seq=1,
            source_event_id="tool-conflict:step-started",
            correlation_id=task_id,
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
            producer_seq=2,
            source_event_id="tool-conflict:issued",
            correlation_id=task_id,
            payload={
                "call_seq": 1,
                "provider_call_id": "provider-conflict",
                "tool_name": "conflicting_tool",
                "args_hash": "c" * 64,
                "args_preview": {},
                "tool_schema_block_id": None,
            },
        ),
        ObservationEnvelope(
            kind="tool.failed",
            occurred_at=observed_at,
            task_id=task_id,
            step_id=step_id,
            subject_type="tool_call",
            subject_id=tool_call_id,
            producer=producer,
            producer_seq=3,
            source_event_id="tool-conflict:failed",
            correlation_id=task_id,
            payload={"call_seq": 1, "error_type": "RuntimeError"},
        ),
        ObservationEnvelope(
            kind="tool.returned_raw",
            occurred_at=observed_at,
            task_id=task_id,
            step_id=step_id,
            subject_type="tool_call",
            subject_id=tool_call_id,
            producer=producer,
            producer_seq=4,
            source_event_id="tool-conflict:returned",
            correlation_id=task_id,
            payload={"call_seq": 1, "duration_ms": 4},
        ),
    ]
    for observation in observations:
        service.record(observation)

    try:
        await service.flush_task(task_id)
        task = await service.get_task(task_id)
        tool_call = await service.get_tool_call(tool_call_id)
        durable = await service.list_observations(task_id)
        async with session_factory() as session:
            assertions = list(
                (
                    await session.execute(
                        select(AnsichBeliefAssertionRow).where(
                            AnsichBeliefAssertionRow.subject_id == tool_call_id,
                            AnsichBeliefAssertionRow.field_name == "execution",
                        )
                    )
                ).scalars()
            )
        assert await service.rebuild_projections() > 0
        rebuilt_task = await service.get_task(task_id)
        rebuilt_tool_call = await service.get_tool_call(tool_call_id)
    finally:
        await service.stop()
        await engine.dispose()

    assert task is not None
    assert task.observability_status == "degraded"
    assert (task.tool_calls_issued, task.tool_calls_executed) == (1, 1)
    assert tool_call is not None
    assert tool_call.execution.value == "returned"
    assert tool_call.execution.selected_by.name == "tool-terminal-precedence"
    assert {assertion.value_json["value"] for assertion in assertions} == {
        "failed",
        "returned",
    }
    assert {item.kind for item in durable} >= {"tool.failed", "tool.returned_raw"}
    assert rebuilt_task == task
    assert rebuilt_tool_call == tool_call


@pytest.mark.anyio
async def test_task_remains_queryable_after_service_restart(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    task_id = new_id()
    observed_at = datetime(2026, 7, 17, 9, 0, tzinfo=UTC)
    first_service = create_sql_ansich_service(session_factory)
    await first_service.start()
    first_service.record(
        ObservationEnvelope.task_lifecycle(
            kind="task.created",
            task_id=task_id,
            source_kind="deerflow_run",
            source_id="run-persisted",
            occurred_at=observed_at,
            source_event_id="run:run-persisted:task:created",
            thread_id="thread-persisted",
            owner_id="owner-persisted",
        )
    )
    terminal = first_service.record(
        ObservationEnvelope.task_lifecycle(
            kind="task.completed",
            task_id=task_id,
            source_kind="deerflow_run",
            source_id="run-persisted",
            occurred_at=observed_at,
            source_event_id="run:run-persisted:task:completed",
        )
    )
    await first_service.flush_task(task_id)
    await first_service.stop()

    restarted_service = create_sql_ansich_service(session_factory)
    await restarted_service.start()
    try:
        task = await restarted_service.get_task(task_id)
    finally:
        await restarted_service.stop()
        await engine.dispose()

    assert task is not None
    assert task.source_id == "run-persisted"
    assert task.control.value == "completed"
    assert task.control.evidence_obs_ids == (terminal.obs_id,)


@pytest.mark.anyio
async def test_writer_deduplicates_observation_and_projects_owner_and_thread_scopes(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-scopes.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(session_factory)
    await service.start()
    task_id = new_id()
    observation = ObservationEnvelope.task_lifecycle(
        kind="task.created",
        task_id=task_id,
        source_kind="deerflow_run",
        source_id="run-scoped",
        occurred_at=datetime(2026, 7, 17, 10, 0, tzinfo=UTC),
        source_event_id="run:run-scoped:task:created",
        producer_seq=42,
        thread_id="thread-scoped",
        owner_id="owner-scoped",
    )

    try:
        service.record(observation)
        service.record(observation)
        await service.flush_task(task_id)
        async with session_factory() as session:
            observation_count = await session.scalar(select(func.count()).select_from(AnsichObservationRow))
            job_count = await session.scalar(select(func.count()).select_from(AnsichProjectionJobRow))
            scope_count = await session.scalar(select(func.count()).select_from(AnsichScopeRow))
            relation_count = await session.scalar(select(func.count()).select_from(AnsichRelationRow))
            stored = await session.scalar(select(AnsichObservationRow))
    finally:
        await service.stop()
        await engine.dispose()

    assert observation_count == 1
    assert job_count == 2
    assert scope_count == 2
    assert relation_count == 2
    assert stored is not None
    assert stored.producer_seq == 42


@pytest.mark.anyio
async def test_projection_failure_keeps_raw_observation_and_records_retry_evidence(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-projector-failure.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    backend = SqlAnsichBackend(session_factory, projector_max_attempts=1)

    async def fail_control_projection(*_args, **_kwargs) -> None:
        raise RuntimeError("projector exploded")

    monkeypatch.setattr(backend, "_project_control", fail_control_projection)
    service = AnsichService(backend, flush_interval_ms=60_000)
    await service.start()
    task_id = new_id()
    service.record(
        ObservationEnvelope.task_lifecycle(
            kind="task.created",
            task_id=task_id,
            source_kind="deerflow_run",
            source_id="run-projector-failure",
            occurred_at=datetime(2026, 7, 17, 11, 0, tzinfo=UTC),
            source_event_id="run:run-projector-failure:task:created",
        )
    )

    try:
        flush = await service.flush_task(task_id)
        task = await service.get_task(task_id)
        health = service.get_health()
        async with session_factory() as session:
            observation_count = await session.scalar(select(func.count()).select_from(AnsichObservationRow))
            error_count = await session.scalar(select(func.count()).select_from(AnsichProjectionErrorRow))
            statuses = list((await session.execute(select(AnsichProjectionJobRow.status))).scalars())
    finally:
        await service.stop()
        await engine.dispose()

    assert flush.persisted is True
    assert observation_count == 1
    assert error_count == 1
    assert sorted(statuses) == ["completed", "failed"]
    assert task is not None
    assert task.control.value == "unknown"
    assert task.control.evidence_obs_ids == ()
    assert health.status == "degraded"
    assert health.failed_jobs == 1


@pytest.mark.anyio
async def test_list_tasks_uses_one_joined_query_and_keeps_page_length_with_a_missing_assertion(
    tmp_path,
):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-task-list-query.db'}")

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    backend = SqlAnsichBackend(session_factory)
    service = AnsichService(backend, flush_interval_ms=60_000)
    await service.start()
    task_ids = [new_id() for _ in range(3)]
    observed_at = datetime(2026, 7, 17, 11, 10, tzinfo=UTC)

    for index, task_id in enumerate(task_ids):
        service.record(
            ObservationEnvelope.task_lifecycle(
                kind="task.created",
                task_id=task_id,
                source_kind="deerflow_run",
                source_id=f"run-list-query-{index}",
                occurred_at=observed_at,
                source_event_id=f"run:run-list-query-{index}:task:created",
            )
        )
        await service.flush_task(task_id)
    await service.stop()

    async with session_factory() as session, session.begin():
        missing_assertion_id = await session.scalar(select(AnsichTaskSummaryRow.assertion_id).where(AnsichTaskSummaryRow.task_id == task_ids[1]))
        assert missing_assertion_id is not None
        await session.execute(delete(AnsichBeliefAssertionRow).where(AnsichBeliefAssertionRow.assertion_id == missing_assertion_id))

    select_count = 0

    def count_selects(_connection, _cursor, statement, _parameters, _context, _executemany):
        nonlocal select_count
        if statement.lstrip().upper().startswith(("SELECT", "WITH")):
            select_count += 1

    event.listen(engine.sync_engine, "before_cursor_execute", count_selects)
    try:
        tasks = await backend.list_tasks(limit=3)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", count_selects)
        await engine.dispose()

    assert len(tasks) == 3
    assert {task.task_id for task in tasks} == set(task_ids)
    assert next(task for task in tasks if task.task_id == task_ids[1]).observability_status == "degraded"
    assert select_count == 1


@pytest.mark.anyio
async def test_terminal_task_history_filters_before_limit_and_continues_with_cursor(
    tmp_path,
):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-terminal-history.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(session_factory)
    await service.start()
    expected_terminal_ids: list[str] = []
    task_specs = (
        ("task.interrupted", 5),
        (None, 4),
        ("task.failed", 3),
        (None, 2),
        ("task.completed", 1),
    )
    try:
        for index, (terminal_kind, minute) in enumerate(task_specs):
            task_id = new_id()
            if terminal_kind is not None:
                expected_terminal_ids.append(task_id)
            occurred_at = datetime(2026, 7, 18, 16, minute, tzinfo=UTC)
            observations = [
                ObservationEnvelope.task_lifecycle(
                    kind="task.created",
                    task_id=task_id,
                    source_kind="deerflow_run",
                    source_id=f"run-terminal-history-{index}",
                    occurred_at=occurred_at,
                    source_event_id=f"run:terminal-history-{index}:task:created",
                ),
                ObservationEnvelope.task_lifecycle(
                    kind="task.started",
                    task_id=task_id,
                    source_kind="deerflow_run",
                    source_id=f"run-terminal-history-{index}",
                    occurred_at=occurred_at,
                    source_event_id=f"run:terminal-history-{index}:task:started",
                ),
            ]
            if terminal_kind is not None:
                observations.append(
                    ObservationEnvelope.task_lifecycle(
                        kind=terminal_kind,
                        task_id=task_id,
                        source_kind="deerflow_run",
                        source_id=f"run-terminal-history-{index}",
                        occurred_at=occurred_at,
                        source_event_id=(f"run:terminal-history-{index}:{terminal_kind}"),
                    )
                )
            service.record_batch(tuple(observations))
            await service.flush_task(task_id)

        first_page = await service.list_tasks(
            limit=2,
            lifecycle_scope="terminal",
        )
        assert first_page[-1].control.as_of is not None
        second_page = await service.list_tasks(
            limit=2,
            lifecycle_scope="terminal",
            cursor=(first_page[-1].control.as_of, first_page[-1].task_id),
        )
    finally:
        await service.stop()
        await engine.dispose()

    assert [task.task_id for task in first_page] == expected_terminal_ids[:2]
    assert [task.task_id for task in second_page] == expected_terminal_ids[2:]
    assert all(task.control.value != "running" for task in (*first_page, *second_page))


def test_list_tasks_page_cte_compiles_before_joins_for_sqlite_and_postgres() -> None:
    statement = _list_task_views_statement(
        limit=100,
        control="running",
        lifecycle_scope="terminal",
        from_time=datetime(2026, 7, 17, 10, 0, tzinfo=UTC),
        to_time=datetime(2026, 7, 17, 12, 0, tzinfo=UTC),
        cursor=(datetime(2026, 7, 17, 11, 0, tzinfo=UTC), new_id()),
    )

    for dialect in (sqlite.dialect(), postgresql.dialect()):
        compiled = " ".join(str(statement.compile(dialect=dialect)).upper().split())
        assert compiled.startswith("WITH ANSICH_TASK_PAGE AS")
        assert compiled.index("CONTROL_VALUE IN") < compiled.index(" LIMIT ")
        assert compiled.index(" LIMIT ") < compiled.index(" LEFT OUTER JOIN ")
        assert compiled.count(" LEFT OUTER JOIN ") == 3


@pytest.mark.anyio
async def test_projection_failure_health_survives_service_restart(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-projector-failure-restart.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    failing_backend = SqlAnsichBackend(session_factory, projector_max_attempts=1)

    async def fail_control_projection(*_args, **_kwargs) -> None:
        raise RuntimeError("projector exploded")

    monkeypatch.setattr(failing_backend, "_project_control", fail_control_projection)
    service = AnsichService(failing_backend, flush_interval_ms=60_000)
    await service.start()
    task_id = new_id()
    service.record(
        ObservationEnvelope.task_lifecycle(
            kind="task.created",
            task_id=task_id,
            source_kind="deerflow_run",
            source_id="run-projector-failure-restart",
            occurred_at=datetime(2026, 7, 17, 11, 30, tzinfo=UTC),
            source_event_id="run:run-projector-failure-restart:task:created",
        )
    )

    await service.flush_task(task_id)
    await service.stop()

    restarted = AnsichService(SqlAnsichBackend(session_factory, projector_max_attempts=1))
    await restarted.start()
    try:
        health = restarted.get_health()
    finally:
        await restarted.stop()
        await engine.dispose()

    assert health.status == "degraded"
    assert health.failed_jobs == 1


def test_dependency_pending_deadline_uses_timezone_aware_sql_on_supported_dialects() -> None:
    for column_type in (
        AnsichProjectionJobRow.__table__.c.dependency_pending_since.type,
        AnsichAssessorJobRow.__table__.c.dependency_pending_since.type,
    ):
        assert column_type.compile(dialect=sqlite.dialect()) == "DATETIME"
        assert column_type.compile(dialect=postgresql.dialect()) == "TIMESTAMP WITH TIME ZONE"


def test_projection_dependency_deadline_migration_upgrades_sqlite(tmp_path) -> None:
    backend_root = Path(__file__).resolve().parents[2]
    config = AlembicConfig(str(backend_root / "packages" / "harness" / "deerflow" / "persistence" / "migrations" / "alembic.ini"))
    database_path = tmp_path / "ansich-dependency-migration.db"
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database_path}")
    # The Alembic env only applies process-wide logging.fileConfig when this
    # remains set; the integration test must not disable loggers used later.
    config.config_file_name = None

    alembic_command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{database_path}")
    try:
        column_names = {column["name"] for column in inspect(engine).get_columns("ansich_projection_jobs")}
        with engine.connect() as connection:
            revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
    finally:
        engine.dispose()

    assert "dependency_pending_since" in column_names
    assert revision == "0025_ansich_assessor_watermarks"
    assert len(revision) <= 32


def test_assessor_dependency_deadline_migration_upgrades_sqlite(tmp_path) -> None:
    backend_root = Path(__file__).resolve().parents[2]
    config = AlembicConfig(str(backend_root / "packages" / "harness" / "deerflow" / "persistence" / "migrations" / "alembic.ini"))
    database_path = tmp_path / "ansich-assessor-deadline-migration.db"
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database_path}")
    # The Alembic env only applies process-wide logging.fileConfig when this
    # remains set; the integration test must not disable loggers used later.
    config.config_file_name = None

    alembic_command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{database_path}")
    try:
        column_names = {column["name"] for column in inspect(engine).get_columns("ansich_assessor_jobs")}
        with engine.connect() as connection:
            revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
    finally:
        engine.dispose()

    assert "dependency_pending_since" in column_names
    assert revision == "0025_ansich_assessor_watermarks"
    assert len(revision) <= 32


@pytest.mark.anyio
async def test_dependency_pending_job_eventually_fails_health_and_can_be_retried(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-dependency-timeout.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    backend = SqlAnsichBackend(
        session_factory,
        projector_dependency_timeout_seconds=0,
    )
    service = AnsichService(backend, flush_interval_ms=60_000)
    await service.start()
    task_id = new_id()
    step_id = new_id()
    producer = Producer(name="dependency-timeout-test", version="1", instance_id="test")
    observed_at = datetime.now(UTC)
    service.record(
        ObservationEnvelope(
            kind="step.started",
            occurred_at=observed_at,
            task_id=task_id,
            step_id=step_id,
            subject_type="step",
            subject_id=step_id,
            producer=producer,
            producer_seq=1,
            source_event_id="dependency-timeout:step:started",
            correlation_id=task_id,
            payload={"step_seq": 1, "actor_kind": "lead_agent"},
        )
    )

    try:
        await service.flush_task(task_id)
        health_after_timeout = service.get_health()
        async with session_factory() as session:
            failed_job = await session.scalar(select(AnsichProjectionJobRow).where(AnsichProjectionJobRow.projector_name == "task-step"))
            error_count = await session.scalar(select(func.count()).select_from(AnsichProjectionErrorRow).where(AnsichProjectionErrorRow.job_id == failed_job.job_id))

        service.record(
            ObservationEnvelope.task_lifecycle(
                kind="task.created",
                task_id=task_id,
                source_kind="deerflow_run",
                source_id="run-dependency-timeout",
                occurred_at=observed_at,
                source_event_id="dependency-timeout:task:created",
            )
        )
        await service.flush_task(task_id)
        retried = await service.retry_failed_projections(task_id=task_id)
        steps = await service.list_steps(task_id)
        health_after_retry = service.get_health()
    finally:
        await service.stop()
        await engine.dispose()

    assert failed_job is not None
    assert failed_job.status == "failed"
    assert failed_job.dependency_pending_since is not None
    assert "Ansich task is not projected" in (failed_job.last_error or "")
    assert error_count == 1
    assert health_after_timeout.status == "degraded"
    assert health_after_timeout.failed_jobs == 2
    assert retried == 2
    assert [step.step_id for step in steps] == [step_id]
    assert health_after_retry.failed_jobs == 0


@pytest.mark.anyio
async def test_retry_failed_projection_restores_effective_step_context(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-context-retry.db'}")

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    backend = SqlAnsichBackend(session_factory, projector_max_attempts=1)
    project_context_snapshot = backend._project_context_snapshot

    async def fail_context_projection(*_args, **_kwargs) -> None:
        raise RuntimeError("snapshot projector exploded")

    monkeypatch.setattr(backend, "_project_context_snapshot", fail_context_projection)
    service = AnsichService(backend, flush_interval_ms=60_000)
    await service.start()
    task_id = new_id()
    service.record(
        ObservationEnvelope.task_lifecycle(
            kind="task.created",
            task_id=task_id,
            source_kind="deerflow_run",
            source_id="run-context-retry",
            occurred_at=datetime(2026, 7, 17, 11, 45, tzinfo=UTC),
            source_event_id="run:run-context-retry:task:created",
        )
    )
    await service.flush_task(task_id)
    execution = AnsichExecutionContext(task_id=task_id, service=service)
    agent = create_agent(
        model=_ObservedFinalModel(),
        tools=[],
        middleware=[AnsichDecisionMiddleware(), AnsichAttemptMiddleware()],
    )

    try:
        await agent.ainvoke(
            {"messages": [HumanMessage(content="recover this context")]},
            context={ANSICH_EXECUTION_CONTEXT_KEY: execution},
        )
        await service.flush_task(task_id)
        step_before_retry = (await service.list_steps(task_id))[0]
        context_before_retry = await service.get_step_context(step_before_retry.step_id)

        monkeypatch.setattr(backend, "_project_context_snapshot", project_context_snapshot)
        retried = await service.retry_failed_projections(task_id=task_id)

        step_after_retry = (await service.list_steps(task_id))[0]
        context_after_retry = await service.get_step_context(step_after_retry.step_id)
        health = service.get_health()
    finally:
        await service.stop()
        await engine.dispose()

    assert context_before_retry is None
    assert retried == 1
    assert step_after_retry.effective_context_snapshot_id is not None
    assert context_after_retry is not None
    assert health.failed_jobs == 0


@pytest.mark.anyio
async def test_projection_tables_can_be_rebuilt_from_durable_observations(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-replay.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    backend = SqlAnsichBackend(session_factory)
    service = AnsichService(backend)
    await service.start()
    task_id = new_id()
    observed_at = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)

    try:
        for producer_seq, kind in enumerate(("task.created", "task.started", "task.completed"), start=1):
            service.record(
                ObservationEnvelope.task_lifecycle(
                    kind=kind,
                    task_id=task_id,
                    source_kind="deerflow_run",
                    source_id="run-replay",
                    occurred_at=observed_at,
                    source_event_id=f"run:run-replay:{kind}",
                    producer_seq=producer_seq,
                    thread_id="thread-replay",
                    owner_id="owner-replay",
                )
            )
        await service.flush_task(task_id)
        before = await service.get_task(task_id)

        # Rebuild must go through the service so it cannot race the
        # background projector loop over the same reset jobs (F7).
        assert await service.rebuild_projections() > 0

        after = await service.get_task(task_id)
        observations = await service.list_observations(task_id)
    finally:
        await service.stop()
        await engine.dispose()

    assert before is not None
    assert after == before
    assert len(observations) == 3


@pytest.mark.anyio
async def test_projection_claim_order_follows_registry_priority_not_alphabetical(tmp_path, monkeypatch):
    """Adding a projector whose name sorts first alphabetically must not jump the queue (F4)."""
    from deerflow.ansich.persistence import sql as sql_module

    # Simulate a projector that consumes task.created: "usage-rollup" sorts
    # after "task-structural" in the old projector_name.desc() ordering, so an
    # alphabetical claim would run it before both existing projectors.
    monkeypatch.setattr(sql_module, "_PROJECTORS", (*sql_module._PROJECTORS, ("usage-rollup", "1")))
    monkeypatch.setattr(
        sql_module,
        "_PROJECTOR_KINDS",
        {**sql_module._PROJECTOR_KINDS, "usage-rollup": frozenset({"task.created"})},
    )

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-priority.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    backend = SqlAnsichBackend(session_factory)

    try:
        await backend.persist_and_project(
            [
                ObservationEnvelope.task_lifecycle(
                    kind="task.created",
                    task_id=new_id(),
                    source_kind="deerflow_run",
                    source_id="run-priority",
                    occurred_at=datetime(2026, 7, 17, 13, 0, tzinfo=UTC),
                    source_event_id="run:run-priority:task:created",
                )
            ]
        )
        claimed_names = []
        for _ in range(3):
            claim = await backend._claim_projection_job()
            assert claim is not None
            claimed_names.append(claim[1])
    finally:
        await engine.dispose()

    assert claimed_names == ["task-structural", "task-control", "usage-rollup"]


@pytest.mark.anyio
async def test_step_attempt_and_context_are_queryable_after_projection(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-step.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(session_factory)
    await service.start()
    task_id = new_id()
    service.record(
        ObservationEnvelope.task_lifecycle(
            kind="task.created",
            task_id=task_id,
            source_kind="deerflow_run",
            source_id="run-step",
            occurred_at=datetime.now(UTC),
            source_event_id="run:run-step:task:created",
        )
    )
    await service.flush_task(task_id)
    execution = AnsichExecutionContext(task_id=task_id, service=service)
    agent = create_agent(
        model=_ObservedFinalModel(),
        tools=[],
        middleware=[AnsichDecisionMiddleware(), AnsichAttemptMiddleware()],
    )

    try:
        await agent.ainvoke(
            {"messages": [HumanMessage(id="human-step", content="hello")]},
            context={ANSICH_EXECUTION_CONTEXT_KEY: execution},
        )
        await service.flush_task(task_id)
        steps = await service.list_steps(task_id)
        context = await service.get_step_context(steps[0].step_id)
        assert await service.rebuild_projections() > 0
        rebuilt_steps = await service.list_steps(task_id)
        rebuilt_context = await service.get_step_context(steps[0].step_id)
    finally:
        await service.stop()
        await engine.dispose()

    assert len(steps) == 1
    assert steps[0].step_seq == 1
    assert steps[0].result == "final_answer"
    assert steps[0].effective_attempt_no == 1
    assert len(steps[0].attempts) == 1
    assert steps[0].attempts[0].status == "success"
    assert steps[0].attempts[0].effective is True
    assert steps[0].attempts[0].usage == {"input_tokens": 4, "output_tokens": 2, "total_tokens": 6}
    assert steps[0].attempts[0].response_metadata == {
        "finish_reason": "stop",
        "model_name": "observed-model",
    }
    assert context is not None
    assert [(item.ordinal, item.role, item.kind) for item in context.items] == [(0, "user", "user_input")]
    assert context.items[0].payload_available is True
    assert context.items[0].body is None
    assert rebuilt_steps == steps
    assert rebuilt_context == context


@pytest.mark.anyio
async def test_large_content_payload_is_externalized_but_remains_lazy_queryable(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-large-payload.db'}")

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(session_factory, inline_payload_max_bytes=128)
    await service.start()
    task_id = new_id()
    service.record(
        ObservationEnvelope.task_lifecycle(
            kind="task.created",
            task_id=task_id,
            source_kind="deerflow_run",
            source_id="run-large-payload",
            occurred_at=datetime.now(UTC),
            source_event_id="run:run-large-payload:task:created",
        )
    )
    await service.flush_task(task_id)
    execution = AnsichExecutionContext(task_id=task_id, service=service)
    agent = create_agent(
        model=_ObservedFinalModel(),
        tools=[],
        middleware=[AnsichDecisionMiddleware(), AnsichAttemptMiddleware()],
    )
    visible_body = "x" * 500

    try:
        await agent.ainvoke(
            {"messages": [HumanMessage(id="human-large", content=visible_body)]},
            context={ANSICH_EXECUTION_CONTEXT_KEY: execution},
        )
        await service.flush_task(task_id)
        step = (await service.list_steps(task_id))[0]
        context = await service.get_step_context(step.step_id)
        assert context is not None
        raw = await service.get_content_block_payload(context.items[0].block_id)
        async with session_factory() as session:
            content_observation = await session.scalar(select(AnsichObservationRow).where(AnsichObservationRow.kind == "content.produced"))
            payload = await session.get(AnsichPayloadRow, content_observation.payload_ref_id)
    finally:
        await service.stop()
        await engine.dispose()

    assert content_observation is not None
    assert content_observation.payload_json is None
    assert content_observation.payload_ref_id is not None
    assert payload is not None
    assert payload.byte_size > 128
    assert raw is not None
    assert raw.body == visible_body


@pytest.mark.anyio
async def test_equal_content_from_distinct_occurrences_shares_one_blob(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-content-blob.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(session_factory)
    await service.start()
    task_id = new_id()
    first_block_id = new_id()
    second_block_id = new_id()
    body = "same visible value"
    producer = Producer(name="blob-test", version="1", instance_id="test")
    service.record(
        ObservationEnvelope.task_lifecycle(
            kind="task.created",
            task_id=task_id,
            source_kind="deerflow_run",
            source_id="run-content-blob",
            occurred_at=datetime.now(UTC),
            source_event_id="run:run-content-blob:created",
        )
    )
    await service.flush_task(task_id)
    for ordinal, block_id in enumerate((first_block_id, second_block_id), start=1):
        service.record(
            ObservationEnvelope(
                kind="content.produced",
                occurred_at=datetime.now(UTC),
                task_id=task_id,
                subject_type="content_block",
                subject_id=block_id,
                producer=producer,
                producer_seq=ordinal,
                source_event_id=f"blob:content:{ordinal}",
                correlation_id=task_id,
                payload={
                    "attempt_id": new_id(),
                    "occurrence_ordinal": ordinal,
                    "kind": "user_input",
                    "content_hash": hashlib.sha256(body.encode()).hexdigest(),
                    "body": body,
                    "visible_bytes": len(body.encode()),
                    "estimated_tokens": 5,
                    "sensitivity_flags": [],
                },
            )
        )

    try:
        await service.flush_task(task_id)
        first_payload = await service.get_content_block_payload(first_block_id)
        second_payload = await service.get_content_block_payload(second_block_id)
        async with session_factory() as session:
            blob_count = await session.scalar(text("SELECT count(*) FROM ansich_content_blobs"))
            block_count = await session.scalar(text("SELECT count(*) FROM ansich_content_blocks"))
            stored_payloads = list((await session.execute(select(AnsichObservationRow.payload_json).where(AnsichObservationRow.kind == "content.produced"))).scalars())
    finally:
        await service.stop()
        await engine.dispose()

    assert blob_count == 1
    assert block_count == 2
    assert first_payload is not None and first_payload.body == body
    assert second_payload is not None and second_payload.body == body
    assert all(payload is not None and "body" not in payload for payload in stored_payloads)


@pytest.mark.anyio
async def test_content_blob_upsert_is_concurrent_and_hash_collision_safe(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-content-blob-race.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    task_id = new_id()
    bootstrap = create_sql_ansich_service(session_factory)
    await bootstrap.start()
    bootstrap.record(
        ObservationEnvelope.task_lifecycle(
            kind="task.created",
            task_id=task_id,
            source_kind="deerflow_run",
            source_id="run-content-blob-race",
            occurred_at=datetime.now(UTC),
            source_event_id="run:run-content-blob-race:created",
        )
    )
    await bootstrap.flush_task(task_id)
    await bootstrap.stop()
    producer = Producer(name="blob-race", version="1", instance_id="blob-race")

    def content_observation(index: int, body: str) -> ObservationEnvelope:
        return ObservationEnvelope(
            kind="content.produced",
            occurred_at=datetime.now(UTC),
            task_id=task_id,
            subject_type="content_block",
            subject_id=new_id(),
            producer=producer,
            producer_seq=index,
            source_event_id=f"blob-race:{index}",
            correlation_id=task_id,
            payload={
                "kind": "user_input",
                "content_hash": hashlib.sha256(body.encode()).hexdigest(),
                "body": body,
                "visible_bytes": len(body.encode()),
                "estimated_tokens": 1,
                "sensitivity_flags": [],
            },
        )

    first_backend = SqlAnsichBackend(session_factory)
    second_backend = SqlAnsichBackend(session_factory)
    same_body = "concurrent value"
    await asyncio.gather(
        first_backend.persist_and_project([content_observation(1, same_body)]),
        second_backend.persist_and_project([content_observation(2, same_body)]),
    )
    async with session_factory() as session:
        assert await session.scalar(text("SELECT count(*) FROM ansich_content_blobs")) == 1
        assert await session.scalar(text("SELECT count(*) FROM ansich_observations WHERE kind='content.produced'")) == 2

    monkeypatch.setattr("deerflow.ansich.persistence.sql._content_blob_key", lambda *_args: "f" * 64)
    collision_backend = SqlAnsichBackend(session_factory)
    await collision_backend.persist_and_project([content_observation(3, "first collision value")])
    with pytest.raises(ValueError, match="ContentBlob key collision"):
        await collision_backend.persist_and_project([content_observation(4, "second collision value")])

    await engine.dispose()


@pytest.mark.anyio
async def test_content_occurrence_registry_survives_service_restart_and_reuses_block(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-occurrence-recovery.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    task_id = new_id()
    first_service = create_sql_ansich_service(session_factory)
    await first_service.start()
    first_service.record(
        ObservationEnvelope.task_lifecycle(
            kind="task.created",
            task_id=task_id,
            source_kind="deerflow_run",
            source_id="run-occurrence-recovery",
            occurred_at=datetime.now(UTC),
            source_event_id="run:run-occurrence-recovery:created",
        )
    )
    await first_service.flush_task(task_id)
    first_execution = AnsichExecutionContext(task_id=task_id, service=first_service)
    first_agent = create_agent(
        model=_ObservedFinalModel(),
        tools=[],
        middleware=[AnsichDecisionMiddleware(), AnsichAttemptMiddleware()],
    )
    await first_agent.ainvoke(
        {"messages": [HumanMessage(id="durable-user", content="same occurrence")]},
        context={ANSICH_EXECUTION_CONTEXT_KEY: first_execution},
    )
    await first_service.flush_task(task_id)
    await first_service.stop()

    restarted_service = create_sql_ansich_service(session_factory)
    await restarted_service.start()
    try:
        occurrences = await restarted_service.list_content_occurrences(task_id)
        context_state = await restarted_service.get_latest_context_state(task_id)
        next_step_seq = await restarted_service.get_max_step_seq(task_id) + 1
        recovered_execution = AnsichExecutionContext(
            task_id=task_id,
            service=restarted_service,
            next_step_seq=next_step_seq,
            content_occurrences=occurrences,
            context_state=context_state,
        )
        restarted_agent = create_agent(
            model=_ObservedFinalModel(),
            tools=[],
            middleware=[AnsichDecisionMiddleware(), AnsichAttemptMiddleware()],
        )
        await restarted_agent.ainvoke(
            {"messages": [HumanMessage(id="durable-user", content="same occurrence")]},
            context={ANSICH_EXECUTION_CONTEXT_KEY: recovered_execution},
        )
        await restarted_service.flush_task(task_id)
        steps = await restarted_service.list_steps(task_id)
        contexts = [await restarted_service.get_step_context(step.step_id) for step in steps]
        async with session_factory() as session:
            occurrence_count = await session.scalar(select(func.count()).select_from(AnsichContentOccurrenceRow))
            content_observation_count = await session.scalar(select(func.count()).select_from(AnsichObservationRow).where(AnsichObservationRow.kind == "content.produced"))
            snapshot_items = list((await session.execute(select(AnsichContextSnapshotItemRow))).scalars())
            state_items = list((await session.execute(select(AnsichContextStateCheckpointItemRow))).scalars())
            state_count = await session.scalar(select(func.count()).select_from(AnsichContextStateRow))
            state_observation_count = await session.scalar(select(func.count()).select_from(AnsichObservationRow).where(AnsichObservationRow.kind == "context.state_recorded"))
    finally:
        await restarted_service.stop()
        await engine.dispose()

    user_occurrences = [occurrence for occurrence in occurrences if occurrence.kind == "user_input"]
    assert len(user_occurrences) == 1
    assert user_occurrences[0].source_identity == "message:durable-user:occurrence:1:content:0"
    assert occurrence_count == 3
    assert content_observation_count == 3
    assert len(contexts) == 2
    assert all(context is not None for context in contexts)
    assert len({context.items[0].block_id for context in contexts if context is not None}) == 1
    assert all(context.items[0].message_id == "durable-user" for context in contexts if context is not None)
    assert all(context.items[0].source_identity == user_occurrences[0].source_identity for context in contexts if context is not None)
    assert snapshot_items == []
    assert {item.source_identity for item in state_items} == {user_occurrences[0].source_identity}
    assert state_count == 1
    assert state_observation_count == 1


@pytest.mark.anyio
async def test_append_only_context_persists_one_state_delta_instead_of_full_snapshot_membership(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-context-delta.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(session_factory)
    await service.start()
    task_id = new_id()
    service.record(
        ObservationEnvelope.task_lifecycle(
            kind="task.created",
            task_id=task_id,
            source_kind="deerflow_run",
            source_id="run-context-delta",
            occurred_at=datetime.now(UTC),
            source_event_id="run:run-context-delta:created",
        )
    )
    await service.flush_task(task_id)
    execution = AnsichExecutionContext(task_id=task_id, service=service)

    try:
        for messages in (
            [HumanMessage(id="message-a", content="a")],
            [
                HumanMessage(id="message-a", content="a"),
                HumanMessage(id="message-b", content="b"),
            ],
        ):
            agent = create_agent(
                model=_ObservedFinalModel(),
                tools=[],
                middleware=[AnsichDecisionMiddleware(), AnsichAttemptMiddleware()],
            )
            await agent.ainvoke(
                {"messages": messages},
                context={ANSICH_EXECUTION_CONTEXT_KEY: execution},
            )
            await service.flush_task(task_id)
        steps = await service.list_steps(task_id)
        contexts = [await service.get_step_context(step.step_id) for step in steps]
        assert await service.rebuild_projections() > 0
        rebuilt_contexts = [await service.get_step_context(step.step_id) for step in await service.list_steps(task_id)]
        async with session_factory() as session:
            states = list((await session.execute(select(AnsichContextStateRow).order_by(AnsichContextStateRow.chain_depth))).scalars())
            checkpoint_items = list((await session.execute(select(AnsichContextStateCheckpointItemRow))).scalars())
            deltas = list((await session.execute(select(AnsichContextStateDeltaRow))).scalars())
            snapshot_item_count = await session.scalar(select(func.count()).select_from(AnsichContextSnapshotItemRow))
    finally:
        await service.stop()
        await engine.dispose()

    assert [(state.chain_depth, state.is_checkpoint, state.item_count) for state in states] == [
        (0, True, 1),
        (1, False, 2),
    ]
    assert len(checkpoint_items) == 1
    assert [(delta.operation, delta.source_ordinal, delta.target_ordinal, delta.block_id) for delta in deltas] == [("append", None, 1, contexts[1].items[1].block_id)]
    assert snapshot_item_count == 0
    assert [len(context.items) for context in contexts if context is not None] == [1, 2]
    assert rebuilt_contexts == contexts


async def _record_incomplete_context(service: AnsichService, *, source_suffix: str) -> tuple[str, str, str, Producer]:
    task_id = new_id()
    step_id = new_id()
    attempt_id = new_id()
    snapshot_id = new_id()
    missing_block_id = new_id()
    producer = Producer(name="incomplete-test", version="1", instance_id=source_suffix)
    observed_at = datetime.now(UTC)
    service.record(
        ObservationEnvelope.task_lifecycle(
            kind="task.created",
            task_id=task_id,
            source_kind="deerflow_run",
            source_id=f"run-incomplete-context-{source_suffix}",
            occurred_at=observed_at,
            source_event_id=f"run:run-incomplete-context-{source_suffix}:created",
        )
    )
    await service.flush_task(task_id)
    started = ObservationEnvelope(
        kind="step.started",
        occurred_at=observed_at,
        task_id=task_id,
        step_id=step_id,
        subject_type="step",
        subject_id=step_id,
        producer=producer,
        producer_seq=1,
        source_event_id=f"incomplete:{source_suffix}:step:started",
        correlation_id=task_id,
        payload={"step_seq": 1, "actor_kind": "lead_agent"},
    )
    requested = ObservationEnvelope(
        kind="llm.requested",
        occurred_at=observed_at,
        task_id=task_id,
        step_id=step_id,
        subject_type="llm_attempt",
        subject_id=attempt_id,
        producer=producer,
        producer_seq=2,
        source_event_id=f"incomplete:{source_suffix}:llm:requested",
        correlation_id=task_id,
        causation_obs_id=started.obs_id,
        payload={
            "attempt_no": 1,
            "snapshot_id": snapshot_id,
            "actor_kind": "lead_agent",
            "adapter_name": "test.Adapter",
            "adapter_version": "1",
            "configured_model": "test-model",
        },
    )
    snapshotted = ObservationEnvelope(
        kind="context.snapshotted",
        occurred_at=observed_at,
        task_id=task_id,
        step_id=step_id,
        subject_type="context_snapshot",
        subject_id=snapshot_id,
        producer=producer,
        producer_seq=3,
        source_event_id=f"incomplete:{source_suffix}:context:snapshotted",
        correlation_id=task_id,
        causation_obs_id=requested.obs_id,
        payload={
            "attempt_id": attempt_id,
            "attempt_no": 1,
            "message_count": 1,
            "tool_schema_count": 0,
            "visible_bytes": 7,
            "estimated_tokens": 2,
            "estimator_name": "chars",
            "estimator_version": "1",
            "adapter_name": "test.Adapter",
            "adapter_version": "1",
            "configured_model": "test-model",
            "generation_settings": {},
            "redactions": [],
            "warnings": [],
            "items": [
                {
                    "ordinal": 0,
                    "channel": "message",
                    "role": "user",
                    "message_id": "missing-message",
                    "name": None,
                    "block_id": missing_block_id,
                    "visible_bytes": 7,
                    "estimated_tokens": 2,
                    "metadata": {"message_ordinal": 0, "part_ordinal": 0},
                }
            ],
        },
    )
    responded = ObservationEnvelope(
        kind="llm.responded",
        occurred_at=observed_at,
        task_id=task_id,
        step_id=step_id,
        subject_type="llm_attempt",
        subject_id=attempt_id,
        producer=producer,
        producer_seq=4,
        source_event_id=f"incomplete:{source_suffix}:llm:responded",
        correlation_id=task_id,
        causation_obs_id=requested.obs_id,
        payload={"attempt_no": 1, "latency_ms": 1, "usage": {}, "response_metadata": {}},
    )
    closed = ObservationEnvelope(
        kind="step.closed",
        occurred_at=observed_at,
        task_id=task_id,
        step_id=step_id,
        subject_type="step",
        subject_id=step_id,
        producer=producer,
        producer_seq=5,
        source_event_id=f"incomplete:{source_suffix}:step:closed",
        correlation_id=task_id,
        causation_obs_id=responded.obs_id,
        payload={"result": "final_answer", "effective_attempt_no": 1, "issued_tools": []},
    )

    for observation in (started, requested, snapshotted, responded, closed):
        service.record(observation)
    await service.flush_task(task_id)
    return task_id, step_id, missing_block_id, producer


@pytest.mark.anyio
async def test_snapshot_with_permanently_missing_content_remains_queryable_as_incomplete(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-incomplete-context.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(session_factory)
    await service.start()

    try:
        _, step_id, missing_block_id, _ = await _record_incomplete_context(service, source_suffix="permanent")
        context = await service.get_step_context(step_id)
        health = service.get_health()
    finally:
        await service.stop()
        await engine.dispose()

    assert context is not None
    assert context.status == "incomplete"
    assert len(context.items) == 1
    assert context.items[0].ordinal == 0
    assert context.items[0].block_id == missing_block_id
    assert context.items[0].resolution_status == "missing"
    assert context.items[0].payload_available is False
    assert health.failed_jobs == 0
    assert health.snapshot_count == 1
    assert health.snapshot_item_count == 1
    assert health.snapshot_visible_bytes == 7
    assert health.incomplete_snapshot_count == 1
    assert health.missing_content_block_count == 1


@pytest.mark.anyio
async def test_late_content_repairs_an_incomplete_snapshot(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-repaired-context.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(session_factory)
    await service.start()

    try:
        task_id, step_id, missing_block_id, producer = await _record_incomplete_context(service, source_suffix="repaired")
        service.record(
            ObservationEnvelope(
                kind="content.produced",
                occurred_at=datetime.now(UTC),
                task_id=task_id,
                step_id=step_id,
                subject_type="content_block",
                subject_id=missing_block_id,
                producer=producer,
                producer_seq=6,
                source_event_id="incomplete:repaired:content:late",
                correlation_id=task_id,
                payload={
                    "attempt_id": new_id(),
                    "occurrence_ordinal": 0,
                    "kind": "user_input",
                    "content_hash": hashlib.sha256(b"missing").hexdigest(),
                    "body": "missing",
                    "visible_bytes": 7,
                    "estimated_tokens": 2,
                    "sensitivity_flags": [],
                },
            )
        )
        await service.flush_task(task_id)
        context = await service.get_step_context(step_id)
    finally:
        await service.stop()
        await engine.dispose()

    assert context is not None
    assert context.status == "complete"
    assert len(context.items) == 1
    assert context.items[0].block_id == missing_block_id
    assert context.items[0].kind == "user_input"
    assert context.items[0].resolution_status == "available"
    assert context.items[0].payload_available is True


@pytest.mark.anyio
async def test_late_parent_state_repairs_delta_snapshot_without_projection_poison(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-late-parent-state.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(session_factory)
    await service.start()
    task_id = new_id()
    step_id = new_id()
    attempt_id = new_id()
    snapshot_id = new_id()
    parent_state_id = new_id()
    child_state_id = new_id()
    first_block_id = new_id()
    second_block_id = new_id()
    producer = Producer(name="state-gap-test", version="1", instance_id="state-gap")
    observed_at = datetime.now(UTC)
    parent_items = (
        ContextStateItem(
            ordinal=0,
            channel="message",
            role="user",
            message_id="message-a",
            source_identity="message:message-a:occurrence:1:content:0",
            block_id=first_block_id,
            visible_bytes=1,
            estimated_tokens=1,
            metadata={"message_ordinal": 0, "part_ordinal": 0},
        ),
    )
    child_items = (
        *parent_items,
        ContextStateItem(
            ordinal=1,
            channel="message",
            role="user",
            message_id="message-b",
            source_identity="message:message-b:occurrence:1:content:0",
            block_id=second_block_id,
            visible_bytes=1,
            estimated_tokens=1,
            metadata={"message_ordinal": 1, "part_ordinal": 0},
        ),
    )
    service.record(
        ObservationEnvelope.task_lifecycle(
            kind="task.created",
            task_id=task_id,
            source_kind="deerflow_run",
            source_id="run-state-gap",
            occurred_at=observed_at,
            source_event_id="run:run-state-gap:created",
        )
    )
    await service.flush_task(task_id)
    started = ObservationEnvelope(
        kind="step.started",
        occurred_at=observed_at,
        task_id=task_id,
        step_id=step_id,
        subject_type="step",
        subject_id=step_id,
        producer=producer,
        producer_seq=1,
        source_event_id="state-gap:step",
        correlation_id=task_id,
        payload={"step_seq": 1, "actor_kind": "lead_agent"},
    )
    requested = ObservationEnvelope(
        kind="llm.requested",
        occurred_at=observed_at,
        task_id=task_id,
        step_id=step_id,
        subject_type="llm_attempt",
        subject_id=attempt_id,
        producer=producer,
        producer_seq=2,
        source_event_id="state-gap:request",
        correlation_id=task_id,
        causation_obs_id=started.obs_id,
        payload={
            "attempt_no": 1,
            "snapshot_id": snapshot_id,
            "actor_kind": "lead_agent",
            "adapter_name": "test.Adapter",
            "adapter_version": "1",
            "configured_model": "test-model",
        },
    )
    content_observations = [
        ObservationEnvelope(
            kind="content.produced",
            occurred_at=observed_at,
            task_id=task_id,
            step_id=step_id,
            subject_type="content_block",
            subject_id=block_id,
            producer=producer,
            producer_seq=3 + index,
            source_event_id=f"state-gap:content:{index}",
            correlation_id=task_id,
            causation_obs_id=requested.obs_id,
            payload={
                "kind": "user_input",
                "content_hash": hashlib.sha256(body.encode()).hexdigest(),
                "body": body,
                "visible_bytes": 1,
                "estimated_tokens": 1,
                "sensitivity_flags": [],
            },
        )
        for index, (block_id, body) in enumerate(((first_block_id, "a"), (second_block_id, "b")))
    ]
    child_state = ObservationEnvelope(
        kind="context.state_recorded",
        occurred_at=observed_at,
        task_id=task_id,
        step_id=step_id,
        subject_type="context_state",
        subject_id=child_state_id,
        producer=producer,
        producer_seq=5,
        source_event_id="state-gap:child-state",
        correlation_id=task_id,
        causation_obs_id=requested.obs_id,
        payload={
            "state_hash": context_state_hash(child_items),
            "parent_state_id": parent_state_id,
            "chain_depth": 1,
            "is_checkpoint": False,
            "item_count": 2,
            "checkpoint_items": [],
            "delta": [operation.model_dump(mode="json") for operation in build_context_state_delta(parent_items, child_items)],
        },
    )
    snapshotted = ObservationEnvelope(
        kind="context.snapshotted",
        occurred_at=observed_at,
        task_id=task_id,
        step_id=step_id,
        subject_type="context_snapshot",
        subject_id=snapshot_id,
        producer=producer,
        producer_seq=6,
        source_event_id="state-gap:snapshot",
        correlation_id=task_id,
        causation_obs_id=requested.obs_id,
        payload={
            "attempt_id": attempt_id,
            "attempt_no": 1,
            "message_count": 2,
            "tool_schema_count": 0,
            "visible_bytes": 2,
            "estimated_tokens": 2,
            "estimator_name": "chars",
            "estimator_version": "1",
            "adapter_name": "test.Adapter",
            "adapter_version": "1",
            "configured_model": "test-model",
            "state_id": child_state_id,
            "generation_settings": {},
            "redactions": [],
            "warnings": [],
        },
    )
    responded = ObservationEnvelope(
        kind="llm.responded",
        occurred_at=observed_at,
        task_id=task_id,
        step_id=step_id,
        subject_type="llm_attempt",
        subject_id=attempt_id,
        producer=producer,
        producer_seq=7,
        source_event_id="state-gap:response",
        correlation_id=task_id,
        causation_obs_id=requested.obs_id,
        payload={"attempt_no": 1, "latency_ms": 1, "usage": {}, "response_metadata": {}},
    )
    closed = ObservationEnvelope(
        kind="step.closed",
        occurred_at=observed_at,
        task_id=task_id,
        step_id=step_id,
        subject_type="step",
        subject_id=step_id,
        producer=producer,
        producer_seq=8,
        source_event_id="state-gap:closed",
        correlation_id=task_id,
        causation_obs_id=responded.obs_id,
        payload={"result": "final_answer", "effective_attempt_no": 1, "issued_tools": []},
    )
    for observation in (started, requested, content_observations[0], child_state, snapshotted, responded, closed):
        service.record(observation)

    try:
        await service.flush_task(task_id)
        incomplete = await service.get_step_context(step_id)
        parent_state = ObservationEnvelope(
            kind="context.state_recorded",
            occurred_at=datetime.now(UTC),
            task_id=task_id,
            step_id=step_id,
            subject_type="context_state",
            subject_id=parent_state_id,
            producer=producer,
            producer_seq=9,
            source_event_id="state-gap:parent-state",
            correlation_id=task_id,
            causation_obs_id=requested.obs_id,
            payload={
                "state_hash": context_state_hash(parent_items),
                "parent_state_id": None,
                "chain_depth": 0,
                "is_checkpoint": True,
                "item_count": 1,
                "checkpoint_items": [item.model_dump(mode="json") for item in parent_items],
                "delta": [],
            },
        )
        service.record(parent_state)
        await service.flush_task(task_id)
        parent_repaired = await service.get_step_context(step_id)
        service.record(content_observations[1])
        await service.flush_task(task_id)
        repaired = await service.get_step_context(step_id)
        health = service.get_health()
    finally:
        await service.stop()
        await engine.dispose()

    assert incomplete is not None
    assert incomplete.status == "incomplete"
    assert incomplete.items == ()
    assert parent_repaired is not None
    assert parent_repaired.status == "incomplete"
    assert [item.resolution_status for item in parent_repaired.items] == ["available", "missing"]
    assert repaired is not None
    assert repaired.status == "complete"
    assert [item.block_id for item in repaired.items] == [first_block_id, second_block_id]
    assert health.failed_jobs == 0


@pytest.mark.anyio
async def test_system_operations_follow_observation_ingest_order_not_request_uuid(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-operation-order.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(session_factory)
    await service.start()
    task_id = new_id()
    producer = Producer(name="operation-order-test", version="1", instance_id="operation-order")
    observed_at = datetime.now(UTC)
    service.record(
        ObservationEnvelope.task_lifecycle(
            kind="task.created",
            task_id=task_id,
            source_kind="deerflow_run",
            source_id="run-operation-order",
            occurred_at=observed_at,
            source_event_id="run:run-operation-order:created",
        )
    )
    await service.flush_task(task_id)
    operation_ids = [new_id(), new_id()]
    request_obs_ids = [
        "ffffffff-ffff-4fff-bfff-ffffffffffff",
        "00000000-0000-4000-8000-000000000001",
    ]
    for index, (operation_id, obs_id) in enumerate(zip(operation_ids, request_obs_ids, strict=True), start=1):
        service.record(
            ObservationEnvelope(
                obs_id=obs_id,
                kind="llm.requested",
                occurred_at=observed_at,
                task_id=task_id,
                subject_type="llm_attempt",
                subject_id=new_id(),
                producer=producer,
                producer_seq=index,
                source_event_id=f"operation-order:requested:{index}",
                correlation_id=task_id,
                payload={
                    "attempt_no": 1,
                    "snapshot_id": new_id(),
                    "actor_kind": "system_operation",
                    "operation_id": operation_id,
                    "operation_kind": "other",
                    "adapter_name": "test.Adapter",
                    "adapter_version": "1",
                    "configured_model": "test-model",
                },
            )
        )

    try:
        await service.flush_task(task_id)
        operations = await service.list_system_operations(task_id)
    finally:
        await service.stop()
        await engine.dispose()

    assert [operation.operation_id for operation in operations] == operation_ids


@pytest.mark.anyio
async def test_late_system_request_completes_an_existing_successful_attempt(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-late-request.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(session_factory)
    await service.start()
    task_id = new_id()
    attempt_id = new_id()
    operation_id = new_id()
    producer = Producer(name="late-test", version="1", instance_id="late-instance")
    observed_at = datetime.now(UTC)
    service.record(
        ObservationEnvelope.task_lifecycle(
            kind="task.created",
            task_id=task_id,
            source_kind="deerflow_run",
            source_id="run-late-request",
            occurred_at=observed_at,
            source_event_id="run:run-late-request:created",
        )
    )
    await service.flush_task(task_id)
    service.record(
        ObservationEnvelope(
            kind="llm.responded",
            occurred_at=observed_at,
            task_id=task_id,
            subject_type="llm_attempt",
            subject_id=attempt_id,
            producer=producer,
            producer_seq=1,
            source_event_id="late:responded",
            correlation_id=task_id,
            payload={
                "attempt_no": 1,
                "latency_ms": 7,
                "usage": {"total_tokens": 3},
                "response_metadata": {"finish_reason": "stop"},
            },
        )
    )
    service.record(
        ObservationEnvelope(
            kind="llm.requested",
            occurred_at=observed_at,
            task_id=task_id,
            subject_type="llm_attempt",
            subject_id=attempt_id,
            producer=producer,
            producer_seq=2,
            source_event_id="late:requested",
            correlation_id=task_id,
            payload={
                "attempt_no": 1,
                "snapshot_id": new_id(),
                "actor_kind": "system_operation",
                "operation_id": operation_id,
                "operation_kind": "memory",
                "adapter_name": "test.Adapter",
                "adapter_version": "1",
                "configured_model": "test-model",
            },
        )
    )

    try:
        await service.flush_task(task_id)
        operations = await service.list_system_operations(task_id)
        async with session_factory() as session:
            stored_attempt = await session.get(AnsichLlmAttemptRow, attempt_id)
    finally:
        await service.stop()
        await engine.dispose()

    assert len(operations) == 1
    assert operations[0].status == "success"
    assert operations[0].request_obs_id is not None
    assert operations[0].operation_id == operation_id
    assert operations[0].operation_kind == "memory"
    assert operations[0].usage == {"total_tokens": 3}
    assert stored_attempt is not None
    assert stored_attempt.usage_json == {"total_tokens": 3}
    assert stored_attempt.response_metadata_json == {"finish_reason": "stop"}
