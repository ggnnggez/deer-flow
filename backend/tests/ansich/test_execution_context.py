from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

from ansich import AnsichService, new_id
from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool

from deerflow.agents.lead_agent.agent import build_middlewares
from deerflow.agents.memory.manager import _host_default_memory_model_invoke
from deerflow.agents.middlewares.llm_error_handling_middleware import LLMErrorHandlingMiddleware
from deerflow.agents.middlewares.memory_middleware import MemoryMiddleware
from deerflow.agents.middlewares.tool_error_handling_middleware import build_subagent_runtime_middlewares
from deerflow.ansich.execution import ANSICH_EXECUTION_CONTEXT_KEY, AnsichExecutionContext
from deerflow.ansich.middleware import AnsichAttemptMiddleware, AnsichDecisionMiddleware, observe_system_model_ainvoke
from deerflow.config.ansich_config import AnsichConfig
from deerflow.config.app_config import AppConfig
from deerflow.config.sandbox_config import SandboxConfig


def test_step_allocator_continues_from_durable_max_and_skips_system_operations() -> None:
    context = AnsichExecutionContext(task_id="00000000-0000-4000-8000-000000000001", next_step_seq=8)

    first = context.begin_call(actor_kind="lead_agent")
    internal = context.begin_call(actor_kind="system_operation", operation_kind="summarization")
    second = context.begin_call(actor_kind="lead_agent")

    assert (first.step_seq, second.step_seq) == (8, 9)
    assert first.step_id is not None
    assert second.step_id is not None
    assert internal.step_id is None
    assert internal.step_seq is None
    assert internal.operation_id is not None
    assert context.next_step_seq == 10


class _FinalAnswerModel(BaseChatModel):
    @property
    def _llm_type(self) -> str:
        return "ansich-final-answer"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="done"))])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def test_direct_final_answer_records_one_step_attempt_and_context_snapshot() -> None:
    async def scenario() -> None:
        service = AnsichService.in_memory()
        await service.start()
        task_id = new_id()
        execution = AnsichExecutionContext(task_id=task_id, service=service)
        agent = create_agent(
            model=_FinalAnswerModel(),
            tools=[],
            middleware=[AnsichDecisionMiddleware(), AnsichAttemptMiddleware()],
        )

        await agent.ainvoke(
            {"messages": [HumanMessage(content="hello")]},
            context={ANSICH_EXECUTION_CONTEXT_KEY: execution},
        )
        await service.flush_task(task_id)
        observations = await service.list_observations(task_id)
        steps = await service.list_steps(task_id)
        context = await service.get_step_context(steps[0].step_id)
        payload = await service.get_content_block_payload(context.items[0].block_id)
        await service.stop()

        assert [observation.kind for observation in observations] == [
            "step.started",
            "llm.requested",
            "content.produced",
            "context.snapshotted",
            "llm.responded",
            "step.closed",
        ]
        assert observations[0].payload == {"step_seq": 1, "actor_kind": "lead_agent"}
        assert observations[-1].payload["effective_attempt_no"] == 1
        assert observations[-1].payload["result"] == "final_answer"
        assert len(steps) == 1
        assert steps[0].attempts[0].effective is True
        assert context.items[0].body is None
        assert payload is not None
        assert payload.body == "hello"

    asyncio.run(scenario())


def test_probe_failure_does_not_change_agent_result(monkeypatch) -> None:
    async def scenario() -> None:
        service = AnsichService.in_memory()
        await service.start()
        execution = AnsichExecutionContext(task_id=new_id(), service=service)

        def fail_probe_sequence() -> int:
            raise RuntimeError("probe allocator failed")

        monkeypatch.setattr(execution, "next_producer_seq", fail_probe_sequence)
        agent = create_agent(
            model=_FinalAnswerModel(),
            tools=[],
            middleware=[AnsichDecisionMiddleware(), AnsichAttemptMiddleware()],
        )

        result = await agent.ainvoke(
            {"messages": [HumanMessage(content="hello")]},
            context={ANSICH_EXECUTION_CONTEXT_KEY: execution},
        )
        await service.stop()

        assert result["messages"][-1].content == "done"

    asyncio.run(scenario())


class _RetryableError(Exception):
    status_code = 503


@tool
def _observed_noop(value: str) -> str:
    """Return the supplied value."""
    return value


class _ToolThenFinalModel(_FinalAnswerModel):
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
                            tool_calls=[{"id": "provider-call-1", "name": "_observed_noop", "args": {"value": "ok"}}],
                        )
                    )
                ]
            )
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def test_tool_decision_is_acting_and_next_decision_closes_with_final_answer() -> None:
    async def scenario() -> None:
        service = AnsichService.in_memory()
        await service.start()
        task_id = new_id()
        execution = AnsichExecutionContext(task_id=task_id, service=service)
        agent = create_agent(
            model=_ToolThenFinalModel(),
            tools=[_observed_noop],
            middleware=[AnsichDecisionMiddleware(), AnsichAttemptMiddleware()],
        )

        await agent.ainvoke(
            {"messages": [HumanMessage(content="use a tool")]},
            context={ANSICH_EXECUTION_CONTEXT_KEY: execution},
        )
        await service.flush_task(task_id)
        steps = await service.list_steps(task_id)
        await service.stop()

        assert [(step.step_seq, step.status, step.result) for step in steps] == [
            (1, "acting", "acting"),
            (2, "closed", "final_answer"),
        ]
        assert steps[0].issued_tools == ({"provider_call_id": "provider-call-1", "name": "_observed_noop"},)

    asyncio.run(scenario())


class _RetryOnceModel(_FinalAnswerModel):
    call_count: int = 0

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.call_count += 1
        if self.call_count == 1:
            raise _RetryableError("temporary")
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


class _AlwaysFailModel(_FinalAnswerModel):
    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        raise RuntimeError("provider failed")


class _RecordingModel(_FinalAnswerModel):
    captured_requests: list[tuple[list[dict[str, object]], dict[str, object]]]

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.captured_requests.append(
            (
                [message.model_dump(mode="json") for message in messages],
                dict(kwargs),
            )
        )
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def test_enabling_ansich_does_not_change_adapter_request() -> None:
    async def scenario() -> None:
        plain_requests: list[tuple[list[dict[str, object]], dict[str, object]]] = []
        observed_requests: list[tuple[list[dict[str, object]], dict[str, object]]] = []
        plain_agent = create_agent(
            model=_RecordingModel(captured_requests=plain_requests),
            tools=[],
        )
        service = AnsichService.in_memory()
        await service.start()
        execution = AnsichExecutionContext(task_id=new_id(), service=service)
        observed_agent = create_agent(
            model=_RecordingModel(captured_requests=observed_requests),
            tools=[],
            middleware=[AnsichDecisionMiddleware(), AnsichAttemptMiddleware()],
        )
        input_value = {"messages": [HumanMessage(content="same adapter request")]}

        plain_result = await plain_agent.ainvoke(input_value)
        observed_result = await observed_agent.ainvoke(
            input_value,
            context={ANSICH_EXECUTION_CONTEXT_KEY: execution},
        )
        await service.stop()

        assert observed_requests == plain_requests
        assert observed_result["messages"][-1].content == plain_result["messages"][-1].content

    asyncio.run(scenario())


def test_unrecoverable_model_failure_closes_step_without_effective_attempt() -> None:
    async def scenario() -> None:
        service = AnsichService.in_memory()
        await service.start()
        task_id = new_id()
        execution = AnsichExecutionContext(task_id=task_id, service=service)
        agent = create_agent(
            model=_AlwaysFailModel(),
            tools=[],
            middleware=[AnsichDecisionMiddleware(), AnsichAttemptMiddleware()],
        )

        try:
            await agent.ainvoke(
                {"messages": [HumanMessage(content="fail")]},
                context={ANSICH_EXECUTION_CONTEXT_KEY: execution},
            )
        except RuntimeError as exc:
            assert str(exc) == "provider failed"
        else:
            raise AssertionError("expected provider failure")
        await service.flush_task(task_id)
        step = (await service.list_steps(task_id))[0]
        await service.stop()

        assert step.status == "model_failed"
        assert step.result == "model_failed"
        assert step.effective_attempt_no is None
        assert step.attempts[0].status == "failed"
        assert step.attempts[0].effective is False

    asyncio.run(scenario())


def test_provider_retry_creates_multiple_attempts_under_one_step() -> None:
    async def scenario() -> None:
        service = AnsichService.in_memory()
        await service.start()
        task_id = new_id()
        execution = AnsichExecutionContext(task_id=task_id, service=service)
        retry = LLMErrorHandlingMiddleware(app_config=AppConfig(sandbox=SandboxConfig(use="test")))
        retry.retry_max_attempts = 2
        retry.retry_base_delay_ms = 0
        retry.retry_cap_delay_ms = 0
        agent = create_agent(
            model=_RetryOnceModel(),
            tools=[],
            middleware=[AnsichDecisionMiddleware(), retry, AnsichAttemptMiddleware()],
        )

        await agent.ainvoke(
            {"messages": [HumanMessage(content="hello")]},
            context={ANSICH_EXECUTION_CONTEXT_KEY: execution},
        )
        await service.flush_task(task_id)
        observations = await service.list_observations(task_id)
        await service.stop()

        assert [item.payload["attempt_no"] for item in observations if item.kind == "llm.requested"] == [1, 2]
        assert [item.kind for item in observations].count("step.started") == 1
        assert [item.kind for item in observations].count("step.closed") == 1
        assert [item.kind for item in observations].count("llm.failed") == 1
        assert [item.kind for item in observations].count("llm.responded") == 1
        assert observations[-1].payload["effective_attempt_no"] == 2

    asyncio.run(scenario())


def test_system_operation_records_attempt_without_consuming_step_sequence() -> None:
    async def scenario() -> None:
        service = AnsichService.in_memory()
        await service.start()
        task_id = new_id()
        execution = AnsichExecutionContext(task_id=task_id, service=service, next_step_seq=4)
        agent = create_agent(
            model=_FinalAnswerModel(),
            tools=[],
            middleware=[
                AnsichDecisionMiddleware(actor_kind="system_operation", operation_kind="summarization"),
                AnsichAttemptMiddleware(),
            ],
        )

        await agent.ainvoke(
            {"messages": [HumanMessage(content="summarize")]},
            context={ANSICH_EXECUTION_CONTEXT_KEY: execution},
        )
        await service.flush_task(task_id)
        observations = await service.list_observations(task_id)
        await service.stop()

        assert execution.next_step_seq == 4
        assert all(not observation.kind.startswith("step.") for observation in observations)
        requested = next(observation for observation in observations if observation.kind == "llm.requested")
        assert requested.step_id is None
        assert requested.payload["actor_kind"] == "system_operation"
        assert requested.payload["operation_kind"] == "summarization"
        assert requested.payload["operation_id"] is not None

    asyncio.run(scenario())


def test_standalone_internal_model_call_is_observed_without_agent_middleware() -> None:
    async def scenario() -> None:
        service = AnsichService.in_memory()
        await service.start()
        task_id = new_id()
        execution = AnsichExecutionContext(task_id=task_id, service=service, next_step_seq=6)

        response = await observe_system_model_ainvoke(
            _FinalAnswerModel(),
            [HumanMessage(content="evaluate")],
            execution=execution,
            operation_kind="goal",
        )
        await service.flush_task(task_id)
        operations = await service.list_system_operations(task_id)
        observations = await service.list_observations(task_id)
        await service.stop()

        assert response.content == "done"
        assert execution.next_step_seq == 6
        assert len(operations) == 1
        assert operations[0].operation_kind == "goal"
        assert operations[0].status == "success"
        assert all(not observation.kind.startswith("step.") for observation in observations)

    asyncio.run(scenario())


def test_memory_middleware_forwards_task_observability_context(monkeypatch) -> None:
    manager = MagicMock()
    execution = AnsichExecutionContext(task_id=new_id(), service=MagicMock())
    runtime = SimpleNamespace(
        context={
            "thread_id": "thread-memory",
            ANSICH_EXECUTION_CONTEXT_KEY: execution,
        }
    )
    middleware = MemoryMiddleware(memory_config=SimpleNamespace(enabled=True))
    monkeypatch.setattr(
        "deerflow.agents.middlewares.memory_middleware.get_memory_manager",
        lambda: manager,
    )

    middleware.after_agent(
        {"messages": [HumanMessage(content="remember"), AIMessage(content="done")]},
        runtime,
    )

    assert manager.add.call_args.kwargs["observability_context"] is execution


def test_host_memory_model_invoke_records_system_operation() -> None:
    async def scenario() -> None:
        service = AnsichService.in_memory()
        await service.start()
        task_id = new_id()
        execution = AnsichExecutionContext(task_id=task_id, service=service, next_step_seq=3)

        response = _host_default_memory_model_invoke(
            _FinalAnswerModel(),
            "remember this",
            config=None,
            observability_context=execution,
        )
        await service.flush_task(task_id)
        operations = await service.list_system_operations(task_id)
        await service.stop()

        assert response.content == "done"
        assert execution.next_step_seq == 3
        assert len(operations) == 1
        assert operations[0].operation_kind == "memory"

    asyncio.run(scenario())


def test_enabled_ansich_places_decision_outside_retry_and_attempt_at_adapter_boundary() -> None:
    enabled = AppConfig(
        sandbox=SandboxConfig(use="test"),
        ansich=AnsichConfig(enabled=True),
    )
    disabled = AppConfig(
        sandbox=SandboxConfig(use="test"),
        ansich=AnsichConfig(enabled=False),
    )

    lead = build_middlewares({}, model_name=None, app_config=enabled)
    lead_names = [type(middleware).__name__ for middleware in lead]
    assert lead_names.index("AnsichDecisionMiddleware") < lead_names.index("LLMErrorHandlingMiddleware")
    assert lead_names.index("LLMErrorHandlingMiddleware") < lead_names.index("AnsichAttemptMiddleware")
    assert lead_names.index("AnsichAttemptMiddleware") < lead_names.index("ClarificationMiddleware")

    subagent = build_subagent_runtime_middlewares(app_config=enabled)
    subagent_names = [type(middleware).__name__ for middleware in subagent]
    assert subagent_names.index("AnsichDecisionMiddleware") < subagent_names.index("LLMErrorHandlingMiddleware")
    assert subagent_names[-1] == "AnsichAttemptMiddleware"

    disabled_names = [type(middleware).__name__ for middleware in build_middlewares({}, model_name=None, app_config=disabled)]
    assert "AnsichDecisionMiddleware" not in disabled_names
    assert "AnsichAttemptMiddleware" not in disabled_names
