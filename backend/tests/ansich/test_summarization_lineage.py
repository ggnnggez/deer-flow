from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from ansich import AnsichService, ObservationEnvelope, new_id
from langchain_core.messages import AIMessage, HumanMessage, trim_messages
from sqlalchemy import insert
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from deerflow.agents.middlewares.summarization_middleware import DeerFlowSummarizationMiddleware
from deerflow.ansich import create_sql_ansich_service
from deerflow.ansich.compression import freeze_context_compression, record_context_compression
from deerflow.ansich.execution import ANSICH_EXECUTION_CONTEXT_KEY, AnsichExecutionContext
from deerflow.ansich.persistence.models import AnsichContextCompressionRow
from deerflow.ansich.persistence.sql import (
    _list_context_compression_summaries_statement,
)
from deerflow.persistence.base import Base


@pytest.mark.anyio
async def test_successful_compaction_records_exact_ordered_source_preserved_and_removed_occurrences() -> None:
    service = AnsichService.in_memory()
    await service.start()
    task_id = new_id()
    execution = AnsichExecutionContext(task_id=task_id, service=service)
    runtime = SimpleNamespace(context={ANSICH_EXECUTION_CONTEXT_KEY: execution})
    model = MagicMock()
    model.with_config.return_value = model
    model.invoke.return_value = SimpleNamespace(text="compressed summary")
    middleware = DeerFlowSummarizationMiddleware(
        model=model,
        trigger=("messages", 4),
        keep=("messages", 2),
        token_counter=len,
    )
    messages = [
        HumanMessage(id="human-old", content="same text"),
        AIMessage(id="assistant-old", content="old answer"),
        HumanMessage(id="human-new", content="same text"),
        AIMessage(id="assistant-new", content="new answer"),
    ]

    result = middleware.compact_state({"messages": messages}, runtime, force=True)
    assert result is not None
    await service.flush_task(task_id)
    observations = await service.list_observations(task_id)
    await service.stop()

    compression = next(observation for observation in observations if observation.kind == "context.compressed")
    assert compression.payload is not None
    content_identity_by_block = {observation.subject_id: observation.payload.get("source_identity") for observation in observations if observation.kind == "content.produced" and observation.payload is not None}

    def identities(disposition: str) -> list[str | None]:
        return [content_identity_by_block[str(item["block_id"])] for item in compression.payload["items"] if item["disposition"] == disposition]

    assert identities("source") == [
        "message:human-old:occurrence:1:content:0",
        "message:assistant-old:occurrence:1:content:0",
    ]
    assert identities("preserved") == [
        "message:human-new:occurrence:1:content:0",
        "message:assistant-new:occurrence:1:content:0",
    ]
    assert identities("removed") == identities("source")
    assert compression.payload["summary_operation_id"]
    assert compression.payload["summary_block_id"] in content_identity_by_block
    assert compression.causation_obs_id is not None


@pytest.mark.anyio
async def test_partial_list_content_trim_records_an_incomplete_compression_inventory(
    tmp_path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-partial-trim-compression.db'}")
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
            source_id="run-partial-trim-compression",
            occurred_at=datetime.now(UTC),
            source_event_id="partial-trim-compression:task",
        )
    )
    await service.flush_task(task_id)
    execution = AnsichExecutionContext(task_id=task_id, service=service)
    boundary = HumanMessage(
        id="trim-boundary",
        content=[
            {"type": "text", "text": "one"},
            {"type": "text", "text": "two"},
            {"type": "text", "text": "three"},
        ],
    )
    tail = AIMessage(id="trim-tail", content="answer")
    messages = [boundary, tail]

    def count_parts(value) -> int:
        selected = value if isinstance(value, list) else [value]
        return sum(len(message.content) if isinstance(message.content, list) else 1 for message in selected)

    trimmed = trim_messages(
        messages,
        max_tokens=2,
        token_counter=count_parts,
        start_on="human",
        strategy="last",
        allow_partial=True,
        include_system=True,
    )
    assert trimmed[0].id == boundary.id
    assert trimmed[0] is not boundary

    frozen = freeze_context_compression(
        execution=execution,
        messages=messages,
        source_messages=trimmed,
        preserved_messages=(),
        removed_messages=messages,
        before_tokens=count_parts(messages),
        previous_summary=None,
        runtime_context=None,
    )
    assert record_context_compression(
        frozen,
        summary_text="partial trim summary",
        summary_call=None,
        after_tokens=1,
    )
    await service.flush_task(task_id)
    compression = await service.get_context_compression(frozen.compression_id)
    compression_list = await service.list_context_compressions(task_id)
    replayed = await service.rebuild_projections()
    rebuilt_compression = await service.get_context_compression(frozen.compression_id)
    rebuilt_compression_list = await service.list_context_compressions(task_id)
    observations = await service.list_observations(task_id)
    await service.stop()
    await engine.dispose()

    assert compression is not None
    assert compression.status == "incomplete"
    assert replayed > 0
    assert rebuilt_compression is not None
    assert rebuilt_compression.status == "incomplete"
    assert [item.compression_id for item in compression_list] == [frozen.compression_id]
    assert rebuilt_compression_list == compression_list
    source_items = [item for item in compression.items if item.disposition == "source"]
    assert len(source_items) == 1
    source_observation = next(observation for observation in observations if observation.subject_id == source_items[0].block.block_id)
    assert source_observation.payload is not None
    assert source_observation.payload["source_identity"] == ("message:trim-tail:occurrence:1:content:0")


def test_incomplete_compression_status_insert_compiles_for_sqlite_and_postgres() -> None:
    statement = insert(AnsichContextCompressionRow).values(
        entity_id=new_id(),
        task_id=new_id(),
        operation_id=None,
        summary_block_id=new_id(),
        before_tokens=10,
        after_tokens=3,
        before_visible_bytes=40,
        after_visible_bytes=12,
        algorithm="test",
        algorithm_version="1",
        source_obs_id=new_id(),
        status="incomplete",
    )

    for dialect in (sqlite.dialect(), postgresql.dialect()):
        compiled = statement.compile(dialect=dialect)
        assert compiled.params["status"] == "incomplete"
        assert "status" in str(compiled).lower()


def test_compression_list_cursor_compiles_for_sqlite_and_postgres() -> None:
    statement = _list_context_compression_summaries_statement(
        task_id=new_id(),
        limit=101,
        cursor=(datetime(2026, 7, 18, 15, 0, tzinfo=UTC), new_id()),
    )

    for dialect in (sqlite.dialect(), postgresql.dialect()):
        compiled = " ".join(str(statement.compile(dialect=dialect)).upper().split())
        assert "JOIN ANSICH_OBSERVATIONS" in compiled
        assert "ANSICH_CONTEXT_COMPRESSIONS.TASK_ID =" in compiled
        assert "ANSICH_OBSERVATIONS.OCCURRED_AT <" in compiled
        assert "ORDER BY ANSICH_OBSERVATIONS.OCCURRED_AT DESC" in compiled


@pytest.mark.anyio
async def test_sql_compression_query_reads_typed_ordered_memberships(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-context-compression.db'}")
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
            source_id="run-context-compression",
            occurred_at=datetime.now(UTC),
            source_event_id="context-compression:task",
        )
    )
    await service.flush_task(task_id)
    execution = AnsichExecutionContext(task_id=task_id, service=service)
    runtime = SimpleNamespace(context={ANSICH_EXECUTION_CONTEXT_KEY: execution})
    model = MagicMock()
    model.with_config.return_value = model
    model.invoke.return_value = SimpleNamespace(text="SQL compressed summary")
    middleware = DeerFlowSummarizationMiddleware(
        model=model,
        trigger=("messages", 4),
        keep=("messages", 2),
        token_counter=len,
    )
    messages = [
        HumanMessage(id="sql-human-old", content="old question"),
        AIMessage(id="sql-assistant-old", content="old answer"),
        HumanMessage(id="sql-human-new", content="new question"),
        AIMessage(id="sql-assistant-new", content="new answer"),
    ]

    result = middleware.compact_state({"messages": messages}, runtime, force=True)
    assert result is not None
    await service.flush_task(task_id)
    observations = await service.list_observations(task_id)
    compression_id = next(observation.subject_id for observation in observations if observation.kind == "context.compressed")

    try:
        compression = await service.get_context_compression(compression_id)
        replayed = await service.rebuild_projections()
        rebuilt_compression = await service.get_context_compression(compression_id)
    finally:
        await service.stop()
        await engine.dispose()

    assert compression is not None
    assert compression.task_id == task_id
    assert compression.status == "complete"
    assert compression.summary_operation_id is not None
    assert compression.summary_block.kind == "summary"
    assert [item.disposition for item in compression.items] == [
        "source",
        "source",
        "preserved",
        "preserved",
        "removed",
        "removed",
    ]
    assert [item.ordinal for item in compression.items] == [0, 1, 0, 1, 0, 1]
    assert replayed > 0
    assert rebuilt_compression == compression


@pytest.mark.anyio
async def test_consecutive_compaction_links_the_new_summary_to_the_previous_summary() -> None:
    service = AnsichService.in_memory()
    await service.start()
    task_id = new_id()
    execution = AnsichExecutionContext(task_id=task_id, service=service)
    runtime = SimpleNamespace(context={ANSICH_EXECUTION_CONTEXT_KEY: execution})
    model = MagicMock()
    model.with_config.return_value = model
    model.invoke.side_effect = [
        SimpleNamespace(text="first summary"),
        SimpleNamespace(text="second summary"),
    ]
    middleware = DeerFlowSummarizationMiddleware(
        model=model,
        trigger=("messages", 4),
        keep=("messages", 2),
        token_counter=len,
    )
    first = middleware.compact_state(
        {
            "messages": [
                HumanMessage(id="first-old-human", content="old question"),
                AIMessage(id="first-old-ai", content="old answer"),
                HumanMessage(id="first-new-human", content="new question"),
                AIMessage(id="first-new-ai", content="new answer"),
            ]
        },
        runtime,
        force=True,
    )
    assert first is not None
    await service.flush_task(task_id)
    first_compression_id = next(observation.subject_id for observation in await service.list_observations(task_id) if observation.kind == "context.compressed")
    first_compression = await service.get_context_compression(first_compression_id)
    assert first_compression is not None

    second = middleware.compact_state(
        {
            "messages": [
                *first.preserved_messages,
                HumanMessage(id="second-new-human", content="follow-up"),
                AIMessage(id="second-new-ai", content="follow-up answer"),
            ],
            "summary_text": first.summary_text,
        },
        runtime,
        force=True,
    )
    assert second is not None
    await service.flush_task(task_id)
    compression_ids = [observation.subject_id for observation in await service.list_observations(task_id) if observation.kind == "context.compressed"]
    second_compression = await service.get_context_compression(compression_ids[-1])
    assert second_compression is not None
    await service.stop()

    second_sources = [item.block.block_id for item in second_compression.items if item.disposition == "source"]
    assert second_sources[0] == first_compression.summary_block.block_id
    lineage = await service.get_content_lineage(
        second_compression.summary_block.block_id,
        direction="backward",
        max_depth=8,
        max_nodes=500,
    )
    assert lineage is not None
    assert first_compression.summary_block.block_id in {node.block_id for node in lineage.nodes}


@pytest.mark.anyio
async def test_unresolved_previous_summary_is_recorded_as_unknown_origin() -> None:
    service = AnsichService.in_memory()
    await service.start()
    task_id = new_id()
    execution = AnsichExecutionContext(task_id=task_id, service=service)
    runtime = SimpleNamespace(context={ANSICH_EXECUTION_CONTEXT_KEY: execution})
    model = MagicMock()
    model.with_config.return_value = model
    model.invoke.return_value = SimpleNamespace(text="replacement summary")
    middleware = DeerFlowSummarizationMiddleware(
        model=model,
        trigger=("messages", 4),
        keep=("messages", 2),
        token_counter=len,
    )

    result = middleware.compact_state(
        {
            "messages": [
                HumanMessage(id="legacy-old-human", content="old question"),
                AIMessage(id="legacy-old-ai", content="old answer"),
                HumanMessage(id="legacy-new-human", content="new question"),
                AIMessage(id="legacy-new-ai", content="new answer"),
            ],
            "summary_text": "summary restored without an Ansich block reference",
        },
        runtime,
        force=True,
    )
    assert result is not None
    await service.flush_task(task_id)
    observations = await service.list_observations(task_id)
    compression_observation = next(observation for observation in observations if observation.kind == "context.compressed")
    compression = await service.get_context_compression(compression_observation.subject_id)
    await service.stop()

    assert compression is not None
    unknown_source = compression.items[0].block
    assert compression.items[0].disposition == "source"
    assert unknown_source.kind == "summary"
    source_observation = next(observation for observation in observations if observation.subject_id == unknown_source.block_id)
    assert source_observation.payload is not None
    assert source_observation.payload["unknown_origin"] is True
    assert source_observation.payload["producer_kind"] == "unknown"


@pytest.mark.anyio
async def test_ansich_write_rejection_does_not_abort_agent_compaction() -> None:
    service = AnsichService.in_memory(queue_capacity=1)
    await service.start()
    execution = AnsichExecutionContext(task_id=new_id(), service=service)
    runtime = SimpleNamespace(context={ANSICH_EXECUTION_CONTEXT_KEY: execution})
    model = MagicMock()
    model.with_config.return_value = model
    model.invoke.return_value = SimpleNamespace(text="fail-open summary")
    middleware = DeerFlowSummarizationMiddleware(
        model=model,
        trigger=("messages", 4),
        keep=("messages", 2),
        token_counter=len,
    )

    result = middleware.compact_state(
        {
            "messages": [
                HumanMessage(id="fail-open-human-1", content="one"),
                AIMessage(id="fail-open-ai-1", content="two"),
                HumanMessage(id="fail-open-human-2", content="three"),
                AIMessage(id="fail-open-ai-2", content="four"),
            ]
        },
        runtime,
        force=True,
    )
    health = service.get_health()
    await service.stop()

    assert result is not None
    assert result.summary_text == "fail-open summary"
    assert health.dropped_count > 0
    assert health.status == "degraded"


@pytest.mark.anyio
async def test_summary_model_failure_does_not_record_a_compression_fact() -> None:
    service = AnsichService.in_memory()
    await service.start()
    task_id = new_id()
    execution = AnsichExecutionContext(task_id=task_id, service=service)
    runtime = SimpleNamespace(context={ANSICH_EXECUTION_CONTEXT_KEY: execution})
    model = MagicMock()
    model.with_config.return_value = model
    model.invoke.side_effect = RuntimeError("summary provider failed")
    middleware = DeerFlowSummarizationMiddleware(
        model=model,
        trigger=("messages", 4),
        keep=("messages", 2),
        token_counter=len,
    )

    result = middleware.compact_state(
        {
            "messages": [
                HumanMessage(id="failure-human-1", content="one"),
                AIMessage(id="failure-ai-1", content="two"),
                HumanMessage(id="failure-human-2", content="three"),
                AIMessage(id="failure-ai-2", content="four"),
            ]
        },
        runtime,
        force=True,
    )
    await service.flush_task(task_id)
    observations = await service.list_observations(task_id)
    await service.stop()

    assert result is None
    assert not any(observation.kind == "context.compressed" for observation in observations)
