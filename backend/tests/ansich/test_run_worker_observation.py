from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from ansich import AnsichService, ObservationEnvelope, Producer, new_id
from ansich.memory import InMemoryAnsichBackend
from ansich.release import AgentRuntimeDescriptor

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


class SilentUntilReleasedAgent(SuccessfulAgent):
    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def astream(self, graph_input, *, config, stream_mode, **kwargs):
        self.entered.set()
        await self.release.wait()
        return
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
        self.worker_id = "worker-a"

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


def _heartbeat_app_config(*, interval_seconds: float = 0.01) -> SimpleNamespace:
    return SimpleNamespace(
        ansich=SimpleNamespace(heartbeat_interval_seconds=interval_seconds),
    )


@pytest.mark.asyncio
async def test_worker_records_descriptor_published_by_actual_agent_factory():
    service = AnsichService.in_memory(flush_interval_ms=1)
    await service.start()
    record = RunRecord(
        run_id="run-agent-release",
        thread_id="thread-agent-release",
        assistant_id="lead-agent",
        status=RunStatus.pending,
        on_disconnect=DisconnectMode.cancel,
        owner_worker_id="worker-a",
    )
    agent = SuccessfulAgent()
    setattr(
        agent,
        "__ansich_agent_runtime_descriptor",
        AgentRuntimeDescriptor(
            namespace="deerflow",
            agent_name="lead-agent",
            effective_model="provider/model-v1",
            prompt_template_id="lead-v1",
            rendered_base_prompt="You are DeerFlow.",
        ),
    )

    try:
        await run_agent(
            RecordingBridge(),
            RecordingRunManager(record),
            record,
            ctx=RunContext(
                checkpointer=None,
                ansich_service=service,
                app_config=_heartbeat_app_config(),
            ),
            agent_factory=lambda config: agent,
            graph_input={"messages": []},
            config={"configurable": {"thread_id": record.thread_id}},
        )
        task = await service.get_task_by_source("deerflow_run", record.run_id)
        assert task is not None
        await service.flush_task(task.task_id)
        binding = await service.get_task_agent_release(task.task_id)
    finally:
        await service.stop()

    assert binding is not None
    assert binding.release.manifest.model.effective == "provider/model-v1"


@pytest.mark.asyncio
async def test_worker_marks_observability_degraded_when_factory_omits_release_descriptor():
    service = AnsichService.in_memory(flush_interval_ms=1)
    await service.start()
    record = RunRecord(
        run_id="run-missing-agent-release",
        thread_id="thread-missing-agent-release",
        assistant_id="custom-agent",
        status=RunStatus.pending,
        on_disconnect=DisconnectMode.cancel,
        owner_worker_id="worker-a",
    )

    try:
        await run_agent(
            RecordingBridge(),
            RecordingRunManager(record),
            record,
            ctx=RunContext(
                checkpointer=None,
                ansich_service=service,
                app_config=_heartbeat_app_config(),
            ),
            agent_factory=lambda config: SuccessfulAgent(),
            graph_input={"messages": []},
            config={"configurable": {"thread_id": record.thread_id}},
        )
        task = await service.get_task_by_source("deerflow_run", record.run_id)
        assert task is not None
        await service.flush_task(task.task_id)
        observations = await service.list_observations(task.task_id)
    finally:
        await service.stop()

    assert record.status == RunStatus.success
    assert any(
        item.kind == "observability.degraded"
        and item.payload
        == {
            "component": "agent_release",
            "reason": "resolution_failed",
        }
        for item in observations
    )


@pytest.mark.asyncio
async def test_worker_emits_heartbeat_during_graph_silence_and_stops_before_terminal():
    service = AnsichService.in_memory(flush_interval_ms=1)
    await service.start()
    record = RunRecord(
        run_id="run-ansich-heartbeat",
        thread_id="thread-ansich-heartbeat",
        assistant_id="lead-agent",
        status=RunStatus.pending,
        on_disconnect=DisconnectMode.cancel,
        owner_worker_id="worker-a",
    )
    record.abort_event = asyncio.Event()
    agent = SilentUntilReleasedAgent()

    run_task = asyncio.create_task(
        run_agent(
            RecordingBridge(),
            RecordingRunManager(record),
            record,
            ctx=RunContext(
                checkpointer=None,
                ansich_service=service,
                app_config=_heartbeat_app_config(),
            ),
            agent_factory=lambda config: agent,
            graph_input={"messages": []},
            config={"configurable": {"thread_id": record.thread_id}},
        )
    )

    try:
        await asyncio.wait_for(agent.entered.wait(), timeout=1)
        async with asyncio.timeout(1):
            while True:
                task = await service.get_task_by_source("deerflow_run", record.run_id)
                if task is not None:
                    observations = await service.list_observations(task.task_id)
                    if any(item.kind == "task.heartbeat" for item in observations):
                        break
                await asyncio.sleep(0.005)

        agent.release.set()
        await asyncio.wait_for(run_task, timeout=1)
        await service.flush_task(task.task_id)
        observations = await service.list_observations(task.task_id)
        heartbeat_count = sum(item.kind == "task.heartbeat" for item in observations)
        terminal_index = next(index for index, item in enumerate(observations) if item.kind in {"task.completed", "task.failed", "task.interrupted"})

        await asyncio.sleep(0.03)
        await service.flush_task(task.task_id)
        observations_after_terminal = await service.list_observations(task.task_id)
    finally:
        agent.release.set()
        if not run_task.done():
            run_task.cancel()
            await asyncio.gather(run_task, return_exceptions=True)
        await service.stop()

    assert heartbeat_count >= 1
    assert all(index < terminal_index for index, item in enumerate(observations) if item.kind == "task.heartbeat")
    assert sum(item.kind == "task.heartbeat" for item in observations_after_terminal) == heartbeat_count


@pytest.mark.asyncio
async def test_worker_does_not_emit_heartbeat_without_current_run_ownership():
    service = AnsichService.in_memory(flush_interval_ms=1)
    await service.start()
    record = RunRecord(
        run_id="run-ansich-not-owner",
        thread_id="thread-ansich-not-owner",
        assistant_id="lead-agent",
        status=RunStatus.pending,
        on_disconnect=DisconnectMode.cancel,
        owner_worker_id="worker-b",
    )
    agent = SilentUntilReleasedAgent()
    run_task = asyncio.create_task(
        run_agent(
            RecordingBridge(),
            RecordingRunManager(record),
            record,
            ctx=RunContext(
                checkpointer=None,
                ansich_service=service,
                app_config=_heartbeat_app_config(),
            ),
            agent_factory=lambda config: agent,
            graph_input={"messages": []},
            config={"configurable": {"thread_id": record.thread_id}},
        )
    )

    try:
        await asyncio.wait_for(agent.entered.wait(), timeout=1)
        await asyncio.sleep(0.03)
        agent.release.set()
        await asyncio.wait_for(run_task, timeout=1)
        task = await service.get_task_by_source("deerflow_run", record.run_id)
        assert task is not None
        observations = await service.list_observations(task.task_id)
    finally:
        agent.release.set()
        if not run_task.done():
            run_task.cancel()
            await asyncio.gather(run_task, return_exceptions=True)
        await service.stop()

    assert all(item.kind != "task.heartbeat" for item in observations)


@pytest.mark.asyncio
async def test_worker_cancellation_stops_heartbeat_before_interrupted_terminal():
    service = AnsichService.in_memory(flush_interval_ms=1)
    await service.start()
    record = RunRecord(
        run_id="run-ansich-heartbeat-cancel",
        thread_id="thread-ansich-heartbeat-cancel",
        assistant_id="lead-agent",
        status=RunStatus.pending,
        on_disconnect=DisconnectMode.cancel,
        owner_worker_id="worker-a",
    )
    agent = SilentUntilReleasedAgent()
    run_task = asyncio.create_task(
        run_agent(
            RecordingBridge(),
            RecordingRunManager(record),
            record,
            ctx=RunContext(
                checkpointer=None,
                ansich_service=service,
                app_config=_heartbeat_app_config(),
            ),
            agent_factory=lambda config: agent,
            graph_input={"messages": []},
            config={"configurable": {"thread_id": record.thread_id}},
        )
    )

    try:
        await asyncio.wait_for(agent.entered.wait(), timeout=1)
        async with asyncio.timeout(1):
            while True:
                task = await service.get_task_by_source("deerflow_run", record.run_id)
                if task is not None:
                    observations = await service.list_observations(task.task_id)
                    if any(item.kind == "task.heartbeat" for item in observations):
                        break
                await asyncio.sleep(0.005)

        run_task.cancel()
        await asyncio.wait_for(run_task, timeout=1)
        await service.flush_task(task.task_id)
        observations = await service.list_observations(task.task_id)
    finally:
        agent.release.set()
        if not run_task.done():
            run_task.cancel()
            await asyncio.gather(run_task, return_exceptions=True)
        await service.stop()

    terminal_index = next(index for index, item in enumerate(observations) if item.kind == "task.interrupted")
    assert record.status == RunStatus.interrupted
    assert all(index < terminal_index for index, item in enumerate(observations) if item.kind == "task.heartbeat")


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
    # created, started, missing-release degradation, wall time, terminal
    assert health.dropped_count == 5


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
