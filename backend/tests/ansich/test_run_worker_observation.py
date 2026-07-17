from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from ansich import AnsichService, ObservationEnvelope, Producer, new_id
from ansich.memory import InMemoryAnsichBackend

from deerflow.ansich.execution import ANSICH_EXECUTION_CONTEXT_KEY, AnsichExecutionContext
from deerflow.runtime.runs.manager import RunRecord
from deerflow.runtime.runs.schemas import DisconnectMode, RunStatus
from deerflow.runtime.runs.worker import RunContext, run_agent


class SuccessfulAgent:
    metadata: dict = {}
    checkpointer = None
    store = None
    interrupt_before_nodes: list[str] = []
    interrupt_after_nodes: list[str] = []

    async def astream(self, graph_input, *, config, stream_mode, **kwargs):
        return
        yield


class FailingAgent(SuccessfulAgent):
    async def astream(self, graph_input, *, config, stream_mode, **kwargs):
        raise RuntimeError("agent execution failed")
        yield


class InterruptedAgent(SuccessfulAgent):
    async def astream(self, graph_input, *, config, stream_mode, **kwargs):
        raise asyncio.CancelledError
        yield


class CapturingExecutionAgent(SuccessfulAgent):
    execution: AnsichExecutionContext | None = None

    async def astream(self, graph_input, *, config, stream_mode, **kwargs):
        runtime = config["configurable"]["__pregel_runtime"]
        self.execution = runtime.context.get(ANSICH_EXECUTION_CONTEXT_KEY)
        return
        yield


class LeavesIssuedToolOpenAgent(CapturingExecutionAgent):
    tool_call_id: str | None = None

    async def astream(self, graph_input, *, config, stream_mode, **kwargs):
        runtime = config["configurable"]["__pregel_runtime"]
        self.execution = runtime.context.get(ANSICH_EXECUTION_CONTEXT_KEY)
        assert self.execution is not None
        step_id = new_id()
        self.tool_call_id = new_id()
        issued = ObservationEnvelope(
            kind="tool.issued",
            occurred_at=datetime.now(UTC),
            task_id=self.execution.task_id,
            step_id=step_id,
            subject_type="tool_call",
            subject_id=self.tool_call_id,
            producer=Producer(
                name="worker-reconciliation-test",
                version="1",
                instance_id="test",
            ),
            source_event_id=f"tool:{self.tool_call_id}:issued",
            correlation_id=self.execution.task_id,
            payload={
                "call_seq": 1,
                "provider_call_id": "worker-open-tool",
                "tool_name": "open_tool",
                "args_hash": "d" * 64,
                "args_preview": {},
                "tool_schema_block_id": None,
            },
        )
        self.execution.service.record(issued)
        self.execution.register_tool_call(
            tool_call_id=self.tool_call_id,
            step_id=step_id,
            step_seq=1,
            call_seq=1,
            provider_call_id="worker-open-tool",
            tool_name="open_tool",
            args_hash="d" * 64,
            issued_obs_id=issued.obs_id,
        )
        return
        yield


class RecordingRunManager:
    def __init__(self, record: RunRecord) -> None:
        self.record = record

    async def wait_for_prior_finalizing(self, *_args, **_kwargs) -> None:
        return None

    async def has_later_started_run(self, *_args, **_kwargs) -> bool:
        return False

    async def set_status(self, _run_id, status, *, error=None, stop_reason=None) -> None:
        self.record.status = status
        self.record.error = error
        self.record.updated_at = datetime.now(UTC).isoformat()

    async def update_model_name(self, *_args, **_kwargs) -> None:
        return None

    async def update_run_completion(self, *_args, **_kwargs) -> None:
        return None

    async def set_finalizing(self, _run_id, finalizing: bool) -> None:
        self.record.finalizing = finalizing


class RecordingBridge:
    async def publish(self, *_args, **_kwargs) -> None:
        return None

    async def publish_end(self, *_args, **_kwargs) -> None:
        return None

    async def cleanup(self, *_args, **_kwargs) -> None:
        return None


@pytest.mark.asyncio
async def test_successful_run_is_observed_as_completed_task():
    service = AnsichService.in_memory()
    await service.start()
    record = RunRecord(
        run_id="run-ansich-success",
        thread_id="thread-ansich",
        assistant_id="lead-agent",
        status=RunStatus.pending,
        on_disconnect=DisconnectMode.cancel,
    )
    record.abort_event = asyncio.Event()

    try:
        await run_agent(
            RecordingBridge(),
            RecordingRunManager(record),
            record,
            ctx=RunContext(checkpointer=None, ansich_service=service),
            agent_factory=lambda config: SuccessfulAgent(),
            graph_input={"messages": []},
            config={"configurable": {"thread_id": record.thread_id}},
        )
        task = await service.get_task_by_source("deerflow_run", record.run_id)
    finally:
        await service.stop()

    assert task is not None
    assert task.source_id == record.run_id
    assert task.control.value == "completed"
    assert task.control.source.name == "task-control"


@pytest.mark.parametrize(
    ("agent_factory", "expected_run_status", "expected_control"),
    [
        (FailingAgent, RunStatus.error, "failed"),
        (InterruptedAgent, RunStatus.interrupted, "interrupted"),
    ],
)
@pytest.mark.asyncio
async def test_worker_terminal_outcome_is_mapped_to_ansich_control(
    agent_factory,
    expected_run_status,
    expected_control,
):
    service = AnsichService.in_memory()
    await service.start()
    record = RunRecord(
        run_id=f"run-ansich-{expected_control}",
        thread_id="thread-ansich-terminal",
        assistant_id="lead-agent",
        status=RunStatus.pending,
        on_disconnect=DisconnectMode.cancel,
    )
    record.abort_event = asyncio.Event()

    try:
        await run_agent(
            RecordingBridge(),
            RecordingRunManager(record),
            record,
            ctx=RunContext(checkpointer=None, ansich_service=service),
            agent_factory=lambda config: agent_factory(),
            graph_input={"messages": []},
            config={"configurable": {"thread_id": record.thread_id}},
        )
        task = await service.get_task_by_source("deerflow_run", record.run_id)
    finally:
        await service.stop()

    assert record.status == expected_run_status
    assert task is not None
    assert task.control.value == expected_control


@pytest.mark.asyncio
async def test_ansich_storage_unavailability_does_not_change_successful_run_result():
    service = AnsichService(InMemoryAnsichBackend(), unavailable_reason="storage_unavailable")
    await service.start()
    record = RunRecord(
        run_id="run-ansich-storage-down",
        thread_id="thread-ansich-storage-down",
        assistant_id="lead-agent",
        status=RunStatus.pending,
        on_disconnect=DisconnectMode.cancel,
    )
    record.abort_event = asyncio.Event()

    try:
        await run_agent(
            RecordingBridge(),
            RecordingRunManager(record),
            record,
            ctx=RunContext(checkpointer=None, ansich_service=service),
            agent_factory=lambda config: SuccessfulAgent(),
            graph_input={"messages": []},
            config={"configurable": {"thread_id": record.thread_id}},
        )
        task = await service.get_task_by_source("deerflow_run", record.run_id)
        health = service.get_health()
    finally:
        await service.stop()

    assert record.status == RunStatus.success
    assert task is None
    assert health.status == "failed"
    assert health.dropped_count == 3


@pytest.mark.asyncio
async def test_worker_injects_task_scoped_ansich_execution_context_into_graph_runtime():
    service = AnsichService.in_memory()
    await service.start()
    record = RunRecord(
        run_id="run-ansich-execution",
        thread_id="thread-ansich-execution",
        assistant_id="lead-agent",
        status=RunStatus.pending,
        on_disconnect=DisconnectMode.cancel,
    )
    record.abort_event = asyncio.Event()
    agent = CapturingExecutionAgent()

    try:
        await run_agent(
            RecordingBridge(),
            RecordingRunManager(record),
            record,
            ctx=RunContext(checkpointer=None, ansich_service=service),
            agent_factory=lambda config: agent,
            graph_input={"messages": []},
            config={"configurable": {"thread_id": record.thread_id}},
        )
        task = await service.get_task_by_source("deerflow_run", record.run_id)
    finally:
        await service.stop()

    assert task is not None
    assert agent.execution is not None
    assert agent.execution.task_id == task.task_id
    assert agent.execution.service is service
    assert agent.execution.next_step_seq == 1


@pytest.mark.asyncio
async def test_worker_reconciles_open_tool_before_recording_task_terminal():
    service = AnsichService.in_memory()
    await service.start()
    record = RunRecord(
        run_id="run-ansich-open-tool",
        thread_id="thread-ansich-open-tool",
        assistant_id="lead-agent",
        status=RunStatus.pending,
        on_disconnect=DisconnectMode.cancel,
    )
    record.abort_event = asyncio.Event()
    agent = LeavesIssuedToolOpenAgent()

    try:
        await run_agent(
            RecordingBridge(),
            RecordingRunManager(record),
            record,
            ctx=RunContext(checkpointer=None, ansich_service=service),
            agent_factory=lambda config: agent,
            graph_input={"messages": []},
            config={"configurable": {"thread_id": record.thread_id}},
        )
        task = await service.get_task_by_source("deerflow_run", record.run_id)
        assert task is not None
        observations = await service.list_observations(task.task_id)
        tool_call = await service.get_tool_call(agent.tool_call_id or "")
    finally:
        await service.stop()

    assert tool_call is not None
    assert tool_call.execution.value == "unknown_terminal"
    assert task.tool_calls_issued == 1
    assert task.tool_calls_executed == 0
    kinds = [item.kind for item in observations]
    assert kinds.index("tool.unknown_terminal") < kinds.index("task.completed")
