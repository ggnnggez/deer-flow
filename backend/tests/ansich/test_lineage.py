from __future__ import annotations

from datetime import UTC, datetime

import pytest
from ansich import AnsichService, ContentBlockView, ContentDerivationView, ObservationEnvelope, Producer, new_id
from ansich.lineage import traverse_content_lineage
from ansich.serialization import serialize_observed_content
from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from deerflow.agents.middlewares.durable_context_middleware import (
    DurableContextMiddleware,
)
from deerflow.agents.middlewares.system_message_coalescing_middleware import (
    SystemMessageCoalescingMiddleware,
)
from deerflow.agents.thread_state import ThreadState
from deerflow.ansich import create_sql_ansich_service
from deerflow.ansich.execution import ANSICH_EXECUTION_CONTEXT_KEY, AnsichExecutionContext
from deerflow.ansich.middleware import AnsichAttemptMiddleware, AnsichDecisionMiddleware
from deerflow.ansich.tool_middleware import AnsichRawToolMiddleware, AnsichVisibleToolMiddleware
from deerflow.persistence.base import Base


@tool
def _lineage_exposure_tool(value: str) -> str:
    """Return a value for the SQL possible-exposure test."""
    return value


class _ToolThenFinalModel(BaseChatModel):
    call_count: int = 0

    @property
    def _llm_type(self) -> str:
        return "ansich-sql-exposure"

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
                                    "id": "sql-exposure-provider-call",
                                    "name": "_lineage_exposure_tool",
                                    "args": {"value": "exposed value"},
                                }
                            ],
                        )
                    )
                ]
            )
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="done"))])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def _content_observation(
    *,
    task_id: str,
    producer: Producer,
    producer_seq: int,
    source_event_id: str,
    kind: str,
    body: object,
) -> ObservationEnvelope:
    capture = serialize_observed_content(
        kind=kind,  # type: ignore[arg-type]
        body=body,
        path=source_event_id,
    )
    return ObservationEnvelope(
        kind="content.produced",
        occurred_at=datetime.now(UTC),
        task_id=task_id,
        subject_type="content_block",
        subject_id=capture.block.block_id,
        producer=producer,
        producer_seq=producer_seq,
        source_event_id=source_event_id,
        correlation_id=task_id,
        payload=capture.block.model_dump(mode="json"),
    )


@pytest.mark.anyio
async def test_backward_lineage_traverses_visible_tool_result_to_raw_source() -> None:
    service = AnsichService.in_memory()
    await service.start()
    task_id = new_id()
    producer = Producer(name="lineage-test", version="1", instance_id="test")
    raw = _content_observation(
        task_id=task_id,
        producer=producer,
        producer_seq=1,
        source_event_id="lineage:raw",
        kind="tool_result_raw",
        body={"content": "raw"},
    )
    visible = _content_observation(
        task_id=task_id,
        producer=producer,
        producer_seq=2,
        source_event_id="lineage:visible",
        kind="tool_result_visible",
        body={"content": "visible"},
    )
    derivation = ObservationEnvelope(
        kind="tool.result_visible",
        occurred_at=datetime.now(UTC),
        task_id=task_id,
        subject_type="tool_call",
        subject_id=new_id(),
        producer=producer,
        producer_seq=3,
        source_event_id="lineage:derivation",
        correlation_id=task_id,
        payload={
            "call_seq": 1,
            "result_block_id": visible.subject_id,
            "source_block_id": raw.subject_id,
            "transform_kind": "sanitized",
            "transform_version": "1",
        },
    )
    service.record_batch([raw, visible, derivation])
    await service.flush_task(task_id)

    try:
        lineage = await service.get_content_lineage(
            visible.subject_id,
            direction="backward",
            max_depth=8,
            max_nodes=500,
        )
    finally:
        await service.stop()

    assert lineage is not None
    assert lineage.semantic == "provenance"
    assert lineage.root_block_id == visible.subject_id
    assert lineage.direction == "backward"
    assert [(node.block_id, node.depth, node.kind) for node in lineage.nodes] == [
        (visible.subject_id, 0, "tool_result_visible"),
        (raw.subject_id, 1, "tool_result_raw"),
    ]
    assert [
        (
            edge.derived_block_id,
            edge.source_block_id,
            edge.transform_kind,
            edge.source_role,
        )
        for edge in lineage.edges
    ] == [(visible.subject_id, raw.subject_id, "sanitized", "source")]
    assert lineage.truncated is False
    assert lineage.truncation_reason is None
    assert lineage.unknown_gaps == ()


@pytest.mark.anyio
async def test_sql_backward_lineage_reads_the_typed_derivation_graph(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-lineage.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(session_factory)
    await service.start()
    task_id = new_id()
    step_id = new_id()
    producer = Producer(name="sql-lineage-test", version="1", instance_id="test")
    service.record(
        ObservationEnvelope.task_lifecycle(
            kind="task.created",
            task_id=task_id,
            source_kind="deerflow_run",
            source_id="run-lineage-sql",
            occurred_at=datetime.now(UTC),
            source_event_id="lineage:sql:task",
        )
    )
    await service.flush_task(task_id)
    raw = _content_observation(
        task_id=task_id,
        producer=producer,
        producer_seq=2,
        source_event_id="lineage:sql:raw",
        kind="tool_result_raw",
        body={"content": "raw"},
    )
    visible = _content_observation(
        task_id=task_id,
        producer=producer,
        producer_seq=3,
        source_event_id="lineage:sql:visible",
        kind="tool_result_visible",
        body={"content": "visible"},
    )
    observations = [
        ObservationEnvelope(
            kind="step.started",
            occurred_at=datetime.now(UTC),
            task_id=task_id,
            step_id=step_id,
            subject_type="step",
            subject_id=step_id,
            producer=producer,
            producer_seq=1,
            source_event_id="lineage:sql:step",
            correlation_id=task_id,
            payload={"step_seq": 1, "actor_kind": "lead_agent"},
        ),
        raw,
        visible,
        ObservationEnvelope(
            kind="tool.result_visible",
            occurred_at=datetime.now(UTC),
            task_id=task_id,
            step_id=step_id,
            subject_type="tool_call",
            subject_id=new_id(),
            producer=producer,
            producer_seq=4,
            source_event_id="lineage:sql:derivation",
            correlation_id=task_id,
            payload={
                "call_seq": 1,
                "result_block_id": visible.subject_id,
                "source_block_id": raw.subject_id,
                "transform_kind": "sanitized",
                "transform_version": "1",
            },
        ),
    ]
    service.record_batch(observations)
    await service.flush_task(task_id)

    try:
        lineage = await service.get_content_lineage(
            visible.subject_id,
            direction="backward",
            max_depth=8,
            max_nodes=500,
        )
    finally:
        await service.stop()
        await engine.dispose()

    assert lineage is not None
    assert [(node.block_id, node.depth) for node in lineage.nodes] == [
        (visible.subject_id, 0),
        (raw.subject_id, 1),
    ]
    assert lineage.edges[0].established_obs_id == observations[-1].obs_id


@pytest.mark.anyio
async def test_sql_projects_ordered_multi_source_content_derivations(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-multi-source-lineage.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(session_factory)
    await service.start()
    task_id = new_id()
    producer = Producer(name="sql-lineage-test", version="1", instance_id="test")
    service.record(
        ObservationEnvelope.task_lifecycle(
            kind="task.created",
            task_id=task_id,
            source_kind="deerflow_run",
            source_id="run-lineage-multi-source",
            occurred_at=datetime.now(UTC),
            source_event_id="lineage:multi-source:task",
        )
    )
    await service.flush_task(task_id)
    first = _content_observation(
        task_id=task_id,
        producer=producer,
        producer_seq=1,
        source_event_id="lineage:multi-source:first",
        kind="system_prompt",
        body="first",
    )
    second = _content_observation(
        task_id=task_id,
        producer=producer,
        producer_seq=2,
        source_event_id="lineage:multi-source:second",
        kind="system_prompt",
        body="second",
    )
    derived = _content_observation(
        task_id=task_id,
        producer=producer,
        producer_seq=3,
        source_event_id="lineage:multi-source:derived",
        kind="system_prompt",
        body="first\n\nsecond",
    )
    assert derived.payload is not None
    derived = derived.model_copy(
        update={
            "payload": {
                **derived.payload,
                "derivation_sources": [
                    {
                        "source_block_id": first.subject_id,
                        "transform_kind": "coalesced",
                        "transform_version": "1",
                        "source_role": "source",
                        "ordinal": 0,
                    },
                    {
                        "source_block_id": second.subject_id,
                        "transform_kind": "coalesced",
                        "transform_version": "1",
                        "source_role": "source",
                        "ordinal": 1,
                    },
                ],
            }
        }
    )
    service.record_batch([first, second, derived])
    await service.flush_task(task_id)

    try:
        lineage = await service.get_content_lineage(
            derived.subject_id,
            direction="backward",
            max_depth=8,
            max_nodes=500,
        )
    finally:
        await service.stop()
        await engine.dispose()

    assert lineage is not None
    assert [(edge.source_block_id, edge.ordinal) for edge in lineage.edges] == [
        (first.subject_id, 0),
        (second.subject_id, 1),
    ]


@pytest.mark.anyio
async def test_sql_projection_rejects_a_self_referencing_derivation(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-lineage-self-edge.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(session_factory)
    await service.start()
    task_id = new_id()
    step_id = new_id()
    producer = Producer(name="sql-lineage-test", version="1", instance_id="test")
    block = _content_observation(
        task_id=task_id,
        producer=producer,
        producer_seq=2,
        source_event_id="lineage:self-edge:block",
        kind="tool_result_visible",
        body={"content": "visible"},
    )
    service.record_batch(
        [
            ObservationEnvelope.task_lifecycle(
                kind="task.created",
                task_id=task_id,
                source_kind="deerflow_run",
                source_id="run-lineage-self-edge",
                occurred_at=datetime.now(UTC),
                source_event_id="lineage:self-edge:task",
            ),
            ObservationEnvelope(
                kind="step.started",
                occurred_at=datetime.now(UTC),
                task_id=task_id,
                step_id=step_id,
                subject_type="step",
                subject_id=step_id,
                producer=producer,
                producer_seq=1,
                source_event_id="lineage:self-edge:step",
                correlation_id=task_id,
                payload={"step_seq": 1, "actor_kind": "lead_agent"},
            ),
            block,
            ObservationEnvelope(
                kind="tool.result_visible",
                occurred_at=datetime.now(UTC),
                task_id=task_id,
                step_id=step_id,
                subject_type="tool_call",
                subject_id=new_id(),
                producer=producer,
                producer_seq=3,
                source_event_id="lineage:self-edge:derivation",
                correlation_id=task_id,
                payload={
                    "call_seq": 1,
                    "result_block_id": block.subject_id,
                    "source_block_id": block.subject_id,
                    "transform_kind": "copied",
                    "transform_version": "1",
                },
            ),
        ]
    )
    await service.flush_task(task_id)

    try:
        lineage = await service.get_content_lineage(
            block.subject_id,
            direction="backward",
            max_depth=8,
            max_nodes=500,
        )
    finally:
        await service.stop()
        await engine.dispose()

    assert lineage is not None
    assert lineage.edges == ()


@pytest.mark.anyio
async def test_sql_possible_exposure_uses_descendant_snapshot_membership(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-exposure.db'}")
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
            source_id="run-sql-exposure",
            occurred_at=datetime.now(UTC),
            source_event_id="sql-exposure:task",
        )
    )
    await service.flush_task(task_id)
    execution = AnsichExecutionContext(task_id=task_id, service=service)
    agent = create_agent(
        model=_ToolThenFinalModel(),
        tools=[_lineage_exposure_tool],
        middleware=[
            AnsichDecisionMiddleware(),
            AnsichVisibleToolMiddleware(),
            AnsichRawToolMiddleware(),
            AnsichAttemptMiddleware(),
        ],
    )
    await agent.ainvoke(
        {"messages": [HumanMessage(id="sql-exposure-user", content="use tool")]},
        context={ANSICH_EXECUTION_CONTEXT_KEY: execution},
    )
    await service.flush_task(task_id)
    tool_call = (await service.list_steps(task_id))[0].tool_calls[0]
    raw_block_id = tool_call.raw_results[-1].content_block_id

    try:
        exposures = await service.get_possible_exposures(
            raw_block_id,
            max_depth=8,
            max_nodes=500,
        )
    finally:
        await service.stop()
        await engine.dispose()

    assert exposures is not None
    assert exposures.semantic == "possible_exposure"
    assert len(exposures.items) == 1
    assert exposures.items[0].step_seq == 2
    assert exposures.items[0].descendant_depth == 2
    assert exposures.items[0].ordering == "later"


@pytest.mark.anyio
async def test_system_message_coalescing_records_ordered_source_edges() -> None:
    service = AnsichService.in_memory()
    await service.start()
    task_id = new_id()
    execution = AnsichExecutionContext(task_id=task_id, service=service)
    agent = create_agent(
        model=_ToolThenFinalModel(call_count=1),
        tools=[],
        system_prompt=SystemMessage(id="static-system", content="static rules"),
        middleware=[
            AnsichDecisionMiddleware(),
            SystemMessageCoalescingMiddleware(),
            AnsichAttemptMiddleware(),
        ],
        state_schema=ThreadState,
    )

    await agent.ainvoke(
        {
            "messages": [
                SystemMessage(id="dynamic-system", content="dynamic rules"),
                HumanMessage(id="coalescing-user", content="hello"),
            ]
        },
        context={ANSICH_EXECUTION_CONTEXT_KEY: execution},
    )
    await service.flush_task(task_id)
    snapshot = await service.get_step_context((await service.list_steps(task_id))[0].step_id)
    assert snapshot is not None
    merged = next(item for item in snapshot.items if item.role == "system")
    lineage = await service.get_content_lineage(
        merged.block_id,
        direction="backward",
        max_depth=8,
        max_nodes=500,
    )
    await service.stop()

    assert lineage is not None
    assert [(edge.transform_kind, edge.ordinal) for edge in lineage.edges] == [
        ("coalesced", 0),
        ("coalesced", 1),
    ]
    assert [node.kind for node in lineage.nodes] == [
        "system_prompt",
        "system_prompt",
        "system_prompt",
    ]


@pytest.mark.anyio
async def test_summary_lineage_reaches_a_later_durable_context_snapshot() -> None:
    service = AnsichService.in_memory()
    await service.start()
    task_id = new_id()
    execution = AnsichExecutionContext(task_id=task_id, service=service)
    producer = Producer(name="summary-exposure-test", version="1", instance_id="test")
    summary = _content_observation(
        task_id=task_id,
        producer=producer,
        producer_seq=1,
        source_event_id="summary-exposure:source",
        kind="summary",
        body="earlier work summary",
    )
    execution.register_context_summary(
        summary_text="earlier work summary",
        block_id=summary.subject_id,
        producer_obs_id=summary.obs_id,
    )
    service.record(summary)
    await service.flush_task(task_id)
    agent = create_agent(
        model=_ToolThenFinalModel(call_count=1),
        tools=[],
        middleware=[
            AnsichDecisionMiddleware(),
            DurableContextMiddleware(),
            AnsichAttemptMiddleware(),
        ],
        state_schema=ThreadState,
    )

    await agent.ainvoke(
        {
            "messages": [HumanMessage(id="summary-exposure-user", content="continue")],
            "summary_text": "earlier work summary",
        },
        context={ANSICH_EXECUTION_CONTEXT_KEY: execution},
    )
    await service.flush_task(task_id)
    exposures = await service.get_possible_exposures(
        summary.subject_id,
        max_depth=8,
        max_nodes=500,
    )
    await service.stop()

    assert exposures is not None
    assert len(exposures.items) == 1
    assert exposures.items[0].descendant_depth == 1
    assert exposures.items[0].ordering == "later"


@pytest.mark.anyio
async def test_bfs_preserves_diamond_edges_and_defends_against_a_cycle() -> None:
    root_id, left_id, right_id, shared_id = (new_id() for _ in range(4))
    blocks = {
        block_id: ContentBlockView(
            block_id=block_id,
            kind="assistant_output",
            content_hash=block_id.replace("-", "")[:64],
            byte_size=1,
            token_estimate=1,
            payload_status="available",
        )
        for block_id in (root_id, left_id, right_id, shared_id)
    }
    producer_obs_id = new_id()
    edges = [
        ContentDerivationView(
            derived_block_id=derived,
            source_block_id=source,
            transform_kind="copied",
            transform_version="1",
            established_obs_id=producer_obs_id,
        )
        for derived, source in (
            (root_id, left_id),
            (root_id, right_id),
            (left_id, shared_id),
            (right_id, shared_id),
            (shared_id, root_id),
        )
    ]

    async def get_blocks(block_ids: tuple[str, ...]):
        return [blocks[block_id] for block_id in block_ids if block_id in blocks]

    async def get_edges(block_ids: tuple[str, ...], direction: str):
        assert direction == "backward"
        return [edge for edge in edges if edge.derived_block_id in block_ids]

    lineage = await traverse_content_lineage(
        root_id,
        direction="backward",
        max_depth=8,
        max_nodes=500,
        get_blocks=get_blocks,
        get_derivations=get_edges,  # type: ignore[arg-type]
    )

    assert lineage is not None
    assert len(lineage.nodes) == 4
    assert len(lineage.edges) == 5
    assert {node.block_id for node in lineage.nodes} == set(blocks)
    assert lineage.truncated is False


@pytest.mark.anyio
async def test_bfs_reports_depth_truncation_instead_of_silently_cutting_the_graph() -> None:
    root_id, parent_id, grandparent_id = (new_id() for _ in range(3))
    blocks = {
        block_id: ContentBlockView(
            block_id=block_id,
            kind="assistant_output",
            content_hash=block_id.replace("-", "")[:64],
            byte_size=1,
            token_estimate=1,
            payload_status="available",
        )
        for block_id in (root_id, parent_id, grandparent_id)
    }
    edges = [
        ContentDerivationView(
            derived_block_id=root_id,
            source_block_id=parent_id,
            transform_kind="copied",
            transform_version="1",
            established_obs_id=new_id(),
        ),
        ContentDerivationView(
            derived_block_id=parent_id,
            source_block_id=grandparent_id,
            transform_kind="copied",
            transform_version="1",
            established_obs_id=new_id(),
        ),
    ]

    async def get_blocks(block_ids: tuple[str, ...]):
        return [blocks[block_id] for block_id in block_ids if block_id in blocks]

    async def get_edges(block_ids: tuple[str, ...], direction: str):
        return [edge for edge in edges if edge.derived_block_id in block_ids]

    lineage = await traverse_content_lineage(
        root_id,
        direction="backward",
        max_depth=1,
        max_nodes=500,
        get_blocks=get_blocks,
        get_derivations=get_edges,  # type: ignore[arg-type]
    )

    assert lineage is not None
    assert [node.block_id for node in lineage.nodes] == [root_id, parent_id]
    assert lineage.truncated is True
    assert lineage.truncation_reason == "max_depth"


@pytest.mark.anyio
async def test_bfs_batches_neighbor_queries_once_per_depth() -> None:
    layer_width = 100
    root_id = new_id()
    first_layer = [new_id() for _ in range(layer_width)]
    second_layer = [new_id() for _ in range(layer_width)]
    block_ids = [root_id, *first_layer, *second_layer]
    blocks = {
        block_id: ContentBlockView(
            block_id=block_id,
            kind="assistant_output",
            content_hash=block_id.replace("-", "")[:64],
            byte_size=1,
            token_estimate=1,
            payload_status="available",
        )
        for block_id in block_ids
    }
    producer_obs_id = new_id()
    edges = [
        ContentDerivationView(
            derived_block_id=root_id,
            source_block_id=block_id,
            transform_kind="copied",
            transform_version="1",
            established_obs_id=producer_obs_id,
        )
        for block_id in first_layer
    ] + [
        ContentDerivationView(
            derived_block_id=first_layer[index],
            source_block_id=block_id,
            transform_kind="copied",
            transform_version="1",
            established_obs_id=producer_obs_id,
        )
        for index, block_id in enumerate(second_layer)
    ]
    block_batches: list[tuple[str, ...]] = []
    edge_batches: list[tuple[str, ...]] = []

    async def get_blocks(requested_ids: tuple[str, ...]):
        block_batches.append(requested_ids)
        return [blocks[block_id] for block_id in requested_ids if block_id in blocks]

    async def get_edges(requested_ids: tuple[str, ...], direction: str):
        assert direction == "backward"
        edge_batches.append(requested_ids)
        return [edge for edge in edges if edge.derived_block_id in requested_ids]

    lineage = await traverse_content_lineage(
        root_id,
        direction="backward",
        max_depth=2,
        max_nodes=500,
        get_blocks=get_blocks,
        get_derivations=get_edges,  # type: ignore[arg-type]
    )

    assert lineage is not None
    assert len(lineage.nodes) == 201
    assert [len(batch) for batch in block_batches] == [1, 100, 100]
    assert [len(batch) for batch in edge_batches] == [1, 100, 100]


@pytest.mark.anyio
async def test_bfs_keeps_a_missing_source_as_an_unknown_gap() -> None:
    root_id = new_id()
    missing_id = new_id()
    root = ContentBlockView(
        block_id=root_id,
        kind="assistant_output",
        content_hash=root_id.replace("-", "")[:64],
        byte_size=1,
        token_estimate=1,
        payload_status="available",
    )
    edge = ContentDerivationView(
        derived_block_id=root_id,
        source_block_id=missing_id,
        transform_kind="unknown",
        transform_version="1",
        established_obs_id=new_id(),
    )

    async def get_blocks(block_ids: tuple[str, ...]):
        return [root] if root_id in block_ids else []

    async def get_edges(block_ids: tuple[str, ...], direction: str):
        assert direction == "backward"
        return [edge] if root_id in block_ids else []

    lineage = await traverse_content_lineage(
        root_id,
        direction="backward",
        max_depth=8,
        max_nodes=500,
        get_blocks=get_blocks,
        get_derivations=get_edges,  # type: ignore[arg-type]
    )

    assert lineage is not None
    assert [node.block_id for node in lineage.nodes] == [root_id]
    assert lineage.edges == (edge,)
    assert [gap.model_dump() for gap in lineage.unknown_gaps] == [
        {
            "block_id": missing_id,
            "depth": 1,
            "reason": "missing_content_block",
        }
    ]
