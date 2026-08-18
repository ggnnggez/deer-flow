from datetime import UTC, datetime, timedelta

import pytest
from ansich import ObservationEnvelope, Producer, new_id
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from deerflow.ansich import create_sql_ansich_service
from deerflow.persistence.base import Base


@pytest.mark.anyio
async def test_sql_usage_is_idempotent_and_preserves_unknown_token_dimensions(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-usage.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(session_factory)
    await service.start()
    task_id = new_id()
    attempt_id = new_id()
    started_at = datetime(2026, 7, 18, 10, 0, tzinfo=UTC)
    request = ObservationEnvelope(
        kind="llm.requested",
        occurred_at=started_at + timedelta(milliseconds=500),
        task_id=task_id,
        subject_type="llm_attempt",
        subject_id=attempt_id,
        producer=Producer(name="sql-usage-test", version="1", instance_id="test"),
        source_event_id=f"attempt:{attempt_id}:requested",
        correlation_id=task_id,
        payload={
            "attempt_no": 1,
            "actor_kind": "system_operation",
            "operation_id": new_id(),
            "operation_kind": "other",
        },
    )
    response = ObservationEnvelope(
        kind="llm.responded",
        occurred_at=started_at + timedelta(seconds=1),
        task_id=task_id,
        subject_type="llm_attempt",
        subject_id=attempt_id,
        producer=Producer(name="sql-usage-test", version="1", instance_id="test"),
        source_event_id=f"attempt:{attempt_id}:responded",
        correlation_id=task_id,
        payload={
            "attempt_no": 1,
            "latency_ms": 20,
            "usage": {"total_tokens": 41},
        },
    )

    try:
        service.record(
            ObservationEnvelope.task_lifecycle(
                kind="task.created",
                task_id=task_id,
                source_kind="deerflow_run",
                source_id="run-sql-usage",
                occurred_at=started_at,
                source_event_id="run:run-sql-usage:task:created",
            )
        )
        await service.flush_task(task_id)
        service.record(request)
        service.record(response)
        service.record(response)
        await service.flush_task(task_id)

        usage = await service.get_task_usage(task_id)
        await service.rebuild_projections()
        rebuilt = await service.get_task_usage(task_id)
    finally:
        await service.stop()
        await engine.dispose()

    assert usage == rebuilt
    assert usage.inclusive_status == "available"
    assert [(item.dimension, item.value) for item in usage.local] == [
        ("total_tokens", 41),
        ("llm_attempts", 1),
    ]
    assert usage.local[0].as_of == response.occurred_at
    assert usage.local[0].complete_through_ingest_seq > 0
    assert [(item.dimension, item.value) for item in usage.inclusive] == [
        ("total_tokens", 41),
        ("llm_attempts", 1),
    ]


def _attempt_observations(
    *,
    task_id: str,
    attempt_id: str,
    occurred_at: datetime,
    terminal: str,
    provider_model: str | None = None,
    usage: dict[str, object] | None = None,
) -> tuple[ObservationEnvelope, ...]:
    """Build one physical LLM attempt: always requested, optionally terminal."""

    producer = Producer(name="sql-usage-by-model-test", version="1", instance_id="test")

    def envelope(kind: str, payload: dict[str, object]) -> ObservationEnvelope:
        return ObservationEnvelope(
            kind=kind,
            occurred_at=occurred_at,
            task_id=task_id,
            subject_type="llm_attempt",
            subject_id=attempt_id,
            producer=producer,
            source_event_id=f"attempt:{attempt_id}:{kind}",
            correlation_id=task_id,
            payload=payload,
        )

    request = envelope(
        "llm.requested",
        {
            "attempt_no": 1,
            "actor_kind": "system_operation",
            "operation_id": new_id(),
            "operation_kind": "other",
        },
    )
    if terminal == "requested":
        return (request,)
    if terminal == "failed":
        return (request, envelope("llm.failed", {"attempt_no": 1, "latency_ms": 12}))
    responded: dict[str, object] = {
        "attempt_no": 1,
        "latency_ms": 20,
        "usage": dict(usage or {}),
    }
    if provider_model is not None:
        responded["provider_model"] = provider_model
    return (request, envelope("llm.responded", responded))


@pytest.mark.anyio
async def test_sql_usage_by_model_groups_attempts_and_keeps_the_unknown_provider_bucket(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-usage-by-model.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(session_factory)
    await service.start()
    task_id = new_id()
    empty_task_id = new_id()
    observed_at = datetime(2026, 8, 18, 10, 0, tzinfo=UTC)

    try:
        service.record_batch(
            (
                ObservationEnvelope.task_lifecycle(
                    kind="task.created",
                    task_id=task_id,
                    source_kind="deerflow_run",
                    source_id="run-usage-by-model",
                    occurred_at=observed_at,
                    source_event_id="run:run-usage-by-model:task:created",
                ),
                ObservationEnvelope.task_lifecycle(
                    kind="task.created",
                    task_id=empty_task_id,
                    source_kind="deerflow_run",
                    source_id="run-usage-by-model-empty",
                    occurred_at=observed_at,
                    source_event_id="run:run-usage-by-model-empty:task:created",
                ),
            )
        )
        await service.flush_task(task_id)
        await service.flush_task(empty_task_id)
        service.record_batch(
            (
                *_attempt_observations(
                    task_id=task_id,
                    attempt_id=new_id(),
                    occurred_at=observed_at,
                    terminal="responded",
                    provider_model="model-a",
                    usage={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                ),
                *_attempt_observations(
                    task_id=task_id,
                    attempt_id=new_id(),
                    occurred_at=observed_at,
                    terminal="responded",
                    provider_model="model-a",
                    usage={"input_tokens": 20, "output_tokens": 7, "total_tokens": 27},
                ),
                *_attempt_observations(
                    task_id=task_id,
                    attempt_id=new_id(),
                    occurred_at=observed_at,
                    terminal="responded",
                    provider_model="model-b",
                    usage={"input_tokens": 3, "output_tokens": 1, "total_tokens": 4},
                ),
                *_attempt_observations(
                    task_id=task_id,
                    attempt_id=new_id(),
                    occurred_at=observed_at,
                    terminal="requested",
                ),
                *_attempt_observations(
                    task_id=task_id,
                    attempt_id=new_id(),
                    occurred_at=observed_at,
                    terminal="failed",
                ),
            )
        )
        await service.flush_task(task_id)

        by_model = await service.get_task_usage_by_model(task_id)
        empty = await service.get_task_usage_by_model(empty_task_id)
    finally:
        await service.stop()
        await engine.dispose()

    assert [item.model_dump(mode="json") for item in by_model] == [
        {
            "provider_model": "model-a",
            "attempt_count": 2,
            "attempts_with_usage": 2,
            "input_tokens": 30,
            "output_tokens": 12,
            "total_tokens": 42,
        },
        {
            "provider_model": "model-b",
            "attempt_count": 1,
            "attempts_with_usage": 1,
            "input_tokens": 3,
            "output_tokens": 1,
            "total_tokens": 4,
        },
        {
            "provider_model": None,
            "attempt_count": 2,
            "attempts_with_usage": 0,
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
        },
    ]
    assert empty == []


@pytest.mark.anyio
async def test_sql_usage_by_model_reports_unrecorded_token_dimensions_as_unknown(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-usage-by-model-null.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(session_factory)
    await service.start()
    task_id = new_id()
    observed_at = datetime(2026, 8, 18, 10, 5, tzinfo=UTC)

    try:
        service.record(
            ObservationEnvelope.task_lifecycle(
                kind="task.created",
                task_id=task_id,
                source_kind="deerflow_run",
                source_id="run-usage-by-model-null",
                occurred_at=observed_at,
                source_event_id="run:run-usage-by-model-null:task:created",
            )
        )
        await service.flush_task(task_id)
        service.record_batch(
            (
                *_attempt_observations(
                    task_id=task_id,
                    attempt_id=new_id(),
                    occurred_at=observed_at,
                    terminal="responded",
                    provider_model="model-c",
                    usage={"total_tokens": 9},
                ),
                *_attempt_observations(
                    task_id=task_id,
                    attempt_id=new_id(),
                    occurred_at=observed_at,
                    terminal="responded",
                    provider_model="model-c",
                    usage={},
                ),
            )
        )
        await service.flush_task(task_id)

        by_model = await service.get_task_usage_by_model(task_id)
    finally:
        await service.stop()
        await engine.dispose()

    assert [item.model_dump(mode="json") for item in by_model] == [
        {
            "provider_model": "model-c",
            "attempt_count": 2,
            "attempts_with_usage": 1,
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": 9,
        }
    ]


@pytest.mark.anyio
async def test_sql_usage_counts_one_tool_execution_across_started_and_terminal_evidence(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-tool-usage.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(session_factory)
    await service.start()
    task_id = new_id()
    step_id = new_id()
    tool_call_id = new_id()
    observed_at = datetime(2026, 7, 18, 10, 5, tzinfo=UTC)

    def observation(kind: str, payload: dict[str, object]) -> ObservationEnvelope:
        return ObservationEnvelope(
            kind=kind,
            occurred_at=observed_at,
            task_id=task_id,
            step_id=step_id,
            subject_type="tool_call",
            subject_id=tool_call_id,
            producer=Producer(name="sql-tool-usage-test", version="1", instance_id="test"),
            source_event_id=f"tool:{tool_call_id}:{kind}",
            correlation_id=task_id,
            payload=payload,
        )

    try:
        service.record(
            ObservationEnvelope.task_lifecycle(
                kind="task.created",
                task_id=task_id,
                source_kind="deerflow_run",
                source_id="run-tool-usage",
                occurred_at=observed_at,
                source_event_id="run:run-tool-usage:task:created",
            )
        )
        service.record(
            ObservationEnvelope(
                kind="step.started",
                occurred_at=observed_at,
                task_id=task_id,
                step_id=step_id,
                subject_type="step",
                subject_id=step_id,
                producer=Producer(name="sql-tool-usage-test", version="1", instance_id="test"),
                source_event_id=f"step:{step_id}:started",
                correlation_id=task_id,
                payload={"step_seq": 1, "actor_kind": "lead_agent"},
            )
        )
        service.record(
            observation(
                "tool.issued",
                {
                    "call_seq": 1,
                    "provider_call_id": "provider-tool-1",
                    "tool_name": "task",
                    "args_hash": "a" * 64,
                    "args_preview": {},
                    "tool_schema_block_id": None,
                },
            )
        )
        service.record(observation("tool.started", {"call_seq": 1}))
        service.record(
            observation(
                "tool.returned_raw",
                {"call_seq": 1, "duration_ms": 10, "result_block_id": None},
            )
        )
        await service.flush_task(task_id)
        usage = await service.get_task_usage(task_id)
        await service.rebuild_projections()
        rebuilt = await service.get_task_usage(task_id)
    finally:
        await service.stop()
        await engine.dispose()

    assert usage == rebuilt
    assert {item.dimension: item.value for item in usage.local} == {
        "steps": 1,
        "tool_calls_issued": 1,
        "tool_calls_executed": 1,
        "child_tasks_spawned": 1,
    }
