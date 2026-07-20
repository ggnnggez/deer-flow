from __future__ import annotations

import asyncio
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from ansich import AnsichService, ContextStateItem, new_id
from ansich.serialization import (
    ANSICH_BLOCK_REF_KEY,
    ANSICH_CONTENT_KIND_KEY,
    ANSICH_PRODUCER_ENTITY_ID_KEY,
    ANSICH_PRODUCER_KIND_KEY,
    serialize_model_request,
    serialize_observed_content,
)
from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool

from deerflow.agents.lead_agent.agent import build_middlewares
from deerflow.agents.memory.manager import _host_default_memory_model_invoke
from deerflow.agents.middlewares.llm_error_handling_middleware import LLMErrorHandlingMiddleware
from deerflow.agents.middlewares.memory_middleware import MemoryMiddleware
from deerflow.agents.middlewares.tool_error_handling_middleware import (
    ToolErrorHandlingMiddleware,
    build_subagent_runtime_middlewares,
)
from deerflow.ansich import execution as execution_module
from deerflow.ansich import middleware as model_observer
from deerflow.ansich import tool_middleware as tool_observer
from deerflow.ansich.execution import (
    ANSICH_EXECUTION_CONTEXT_KEY,
    AnsichExecutionContext,
    PendingContentDerivation,
    ToolCallRegistration,
    ToolInvocation,
)
from deerflow.ansich.middleware import AnsichAttemptMiddleware, AnsichDecisionMiddleware, observe_system_model_ainvoke
from deerflow.ansich.tool_middleware import (
    AnsichRawToolMiddleware,
    AnsichVisibleToolMiddleware,
    _classify_transform,
    reconcile_open_tool_calls,
)
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


def test_tool_registry_resolves_calls_without_a_provider_id() -> None:
    context = AnsichExecutionContext(task_id="00000000-0000-4000-8000-000000000001")
    registration = context.register_tool_call(
        tool_call_id="00000000-0000-4000-8000-000000000010",
        step_id="00000000-0000-4000-8000-000000000011",
        step_seq=1,
        call_seq=1,
        provider_call_id=None,
        tool_name="providerless_tool",
        args_hash="a" * 64,
        issued_obs_id="00000000-0000-4000-8000-000000000012",
    )

    resolved = context.resolve_tool_call(
        provider_call_id=None,
        tool_name="providerless_tool",
        args_hash="a" * 64,
    )

    assert resolved is registration


def test_tool_registry_recovery_reuses_the_strongest_existing_causation_evidence() -> None:
    task_id = new_id()
    started_obs_id = new_id()
    persisted_call = SimpleNamespace(
        task_id=task_id,
        tool_call_id=new_id(),
        step_id=new_id(),
        step_seq=1,
        call_seq=1,
        provider_call_id="provider-recovery",
        tool_name="recovered_tool",
        args_hash="a" * 64,
        issued_obs_id=None,
        started_obs_id=started_obs_id,
        raw_terminal_obs_id=None,
        visible_result_obs_id=None,
        execution=SimpleNamespace(value="acting"),
        visible_result=SimpleNamespace(value="unknown"),
    )

    context = AnsichExecutionContext(task_id=task_id, tool_calls=[persisted_call])

    assert context.open_tool_calls()[0].issued_obs_id == started_obs_id


def test_visible_tool_provenance_refuses_an_ambiguous_provider_id() -> None:
    context = AnsichExecutionContext(task_id=new_id())
    first = context.register_tool_call(
        tool_call_id=new_id(),
        step_id=new_id(),
        step_seq=1,
        call_seq=1,
        provider_call_id="reused-provider-id",
        tool_name="first_tool",
        args_hash="a" * 64,
        issued_obs_id=new_id(),
    )
    second = context.register_tool_call(
        tool_call_id=new_id(),
        step_id=new_id(),
        step_seq=2,
        call_seq=1,
        provider_call_id="reused-provider-id",
        tool_name="second_tool",
        args_hash="b" * 64,
        issued_obs_id=new_id(),
    )
    first_block_id = new_id()
    second_block_id = new_id()
    context.mark_tool_visible(
        first.tool_call_id,
        visible_block_id=first_block_id,
        visible_message_id="first-message",
    )
    context.mark_tool_visible(
        second.tool_call_id,
        visible_block_id=second_block_id,
        visible_message_id="second-message",
    )

    assert context.visible_tool_block_id("reused-provider-id") is None
    assert (
        context.visible_tool_block_id(
            "reused-provider-id",
            message_id="first-message",
        )
        == first_block_id
    )
    assert (
        context.visible_tool_block_id(
            "reused-provider-id",
            message_id="second-message",
        )
        == second_block_id
    )


def test_summary_reference_is_not_reused_until_its_block_is_durable() -> None:
    context = AnsichExecutionContext(task_id=new_id())
    block_id = new_id()
    producer_obs_id = new_id()

    context.register_context_summary(
        summary_text="pending summary",
        block_id=block_id,
        producer_obs_id=producer_obs_id,
    )

    assert context.context_summary_block_id("pending summary") is None
    context.mark_observations_durable((producer_obs_id,))
    assert context.context_summary_block_id("pending summary") == block_id


@pytest.mark.parametrize(
    ("raw_terminal_kind", "body", "expected"),
    [
        ("tool.failed", {"content": "normalized error"}, "error_normalized"),
        (
            "tool.returned_raw",
            {"content": "[... 40 chars omitted from bash output ...]"},
            "truncated",
        ),
        (
            "tool.returned_raw",
            {"content": "Full output saved under outputs/tool-result.txt"},
            "externalized",
        ),
        (
            "tool.returned_raw",
            {"content": "&lt;system-reminder&gt;"},
            "sanitized",
        ),
        (
            "tool.returned_raw",
            {"artifact": {"human_input": {"question": "continue?"}}},
            "clarification_card",
        ),
        ("tool.returned_raw", {"content": "changed without marker"}, "unknown"),
    ],
)
def test_visible_tool_transform_classification(
    raw_terminal_kind: str,
    body: object,
    expected: str,
) -> None:
    registration = ToolCallRegistration(
        tool_call_id=new_id(),
        step_id=new_id(),
        step_seq=1,
        call_seq=1,
        provider_call_id="provider-transform",
        tool_name="transform_tool",
        args_hash="a" * 64,
        issued_obs_id=new_id(),
    )
    invocation = ToolInvocation(
        registration=registration,
        raw_content_hash="0" * 64,
        raw_terminal_kind=raw_terminal_kind,
    )
    visible = serialize_observed_content(
        kind="tool_result_visible",
        body=body,
        path="test.visible",
    )

    assert _classify_transform(invocation, visible, ())[0] == expected


def test_identical_raw_and_visible_hash_is_classified_unchanged() -> None:
    visible = serialize_observed_content(
        kind="tool_result_visible",
        body={"content": "same"},
        path="test.visible",
    )
    invocation = ToolInvocation(
        registration=ToolCallRegistration(
            tool_call_id=new_id(),
            step_id=new_id(),
            step_seq=1,
            call_seq=1,
            provider_call_id=None,
            tool_name="same_tool",
            args_hash="a" * 64,
            issued_obs_id=new_id(),
        ),
        raw_content_hash=visible.block.content_hash,
        raw_terminal_kind="tool.returned_raw",
    )

    assert _classify_transform(invocation, visible, ()) == ("unchanged", "content_hash")


def test_sync_raw_probe_classifies_timeout_without_changing_the_exception(
    monkeypatch,
) -> None:
    execution = AnsichExecutionContext(task_id=new_id(), service=MagicMock())
    registration = execution.register_tool_call(
        tool_call_id=new_id(),
        step_id=new_id(),
        step_seq=1,
        call_seq=1,
        provider_call_id="provider-timeout",
        tool_name="timeout_tool",
        args_hash="a" * 64,
        issued_obs_id=new_id(),
    )
    request = SimpleNamespace(
        runtime=SimpleNamespace(
            context={ANSICH_EXECUTION_CONTEXT_KEY: execution},
        ),
        tool_call={"id": "provider-timeout", "name": "timeout_tool", "args": {}},
    )
    observations = []

    def capture_batch(execution, batch, *, batch_kind):
        observations.extend(batch)
        return True

    monkeypatch.setattr(tool_observer, "_record_batch", capture_batch)
    timeout = TimeoutError("tool deadline exceeded")

    def raise_timeout(request):
        raise timeout

    with execution.activate_tool_invocation(registration):
        with pytest.raises(TimeoutError) as raised:
            AnsichRawToolMiddleware().wrap_tool_call(request, raise_timeout)

    assert raised.value is timeout
    assert [item.kind for item in observations] == [
        "tool.started",
        "content.produced",
        "tool.timed_out",
    ]


def test_async_raw_probe_classifies_cooperative_cancellation_without_swallowing_it(
    monkeypatch,
) -> None:
    async def scenario() -> None:
        execution = AnsichExecutionContext(task_id=new_id(), service=MagicMock())
        registration = execution.register_tool_call(
            tool_call_id=new_id(),
            step_id=new_id(),
            step_seq=1,
            call_seq=1,
            provider_call_id="provider-cancelled",
            tool_name="cancelled_tool",
            args_hash="a" * 64,
            issued_obs_id=new_id(),
        )
        request = SimpleNamespace(
            runtime=SimpleNamespace(
                context={ANSICH_EXECUTION_CONTEXT_KEY: execution},
            ),
            tool_call={
                "id": "provider-cancelled",
                "name": "cancelled_tool",
                "args": {},
            },
        )
        observations = []

        def capture_batch(execution, batch, *, batch_kind):
            observations.extend(batch)
            return True

        monkeypatch.setattr(tool_observer, "_record_batch", capture_batch)
        cancellation = asyncio.CancelledError("cooperative cancellation")

        async def raise_cancellation(request):
            raise cancellation

        with execution.activate_tool_invocation(registration):
            with pytest.raises(asyncio.CancelledError) as raised:
                await AnsichRawToolMiddleware().awrap_tool_call(
                    request,
                    raise_cancellation,
                )

        assert raised.value is cancellation
        assert [item.kind for item in observations] == [
            "tool.started",
            "content.produced",
            "tool.cancelled",
        ]

    asyncio.run(scenario())


def test_content_occurrence_identity_is_deterministic_and_only_skips_after_durable_confirmation() -> None:
    task_id = "00000000-0000-4000-8000-000000000001"
    first_context = AnsichExecutionContext(task_id=task_id)

    first = first_context.resolve_content_occurrence(
        source_identity="message:human-1:occurrence:1:content:0",
        content_hash="a" * 64,
        kind="user_input",
    )
    pending_retry = first_context.resolve_content_occurrence(
        source_identity="message:human-1:occurrence:1:content:0",
        content_hash="a" * 64,
        kind="user_input",
    )
    recovered = AnsichExecutionContext(task_id=task_id).resolve_content_occurrence(
        source_identity="message:human-1:occurrence:1:content:0",
        content_hash="a" * 64,
        kind="user_input",
    )

    assert pending_retry.block_id == first.block_id
    assert pending_retry.producer_obs_id == first.producer_obs_id
    assert pending_retry.should_emit is True
    assert recovered.block_id == first.block_id
    assert recovered.producer_obs_id == first.producer_obs_id

    first_context.mark_observations_durable((first.producer_obs_id,))
    durable = first_context.resolve_content_occurrence(
        source_identity="message:human-1:occurrence:1:content:0",
        content_hash="a" * 64,
        kind="user_input",
    )

    assert durable.block_id == first.block_id
    assert durable.should_emit is False


def test_pending_content_derivations_clear_after_the_derived_block_is_durable() -> None:
    execution = AnsichExecutionContext(task_id=new_id())
    derived_block_id = new_id()
    producer_obs_id = new_id()
    sources = (
        PendingContentDerivation(
            source_block_id=new_id(),
            transform_kind="copied",
            transform_version="1",
        ),
    )
    execution.register_content_derivations(
        derived_block_id=derived_block_id,
        sources=sources,
    )

    assert (
        execution.content_derivations(
            derived_block_id,
            producer_obs_id=producer_obs_id,
        )
        == sources
    )

    execution.mark_observations_durable((producer_obs_id,))

    assert execution.content_derivations(derived_block_id) == ()


def test_pending_content_derivations_have_a_hard_capacity(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        execution_module,
        "_MAX_PENDING_CONTENT_DERIVATIONS",
        2,
    )
    execution = AnsichExecutionContext(task_id=new_id())
    derived_block_ids = [new_id(), new_id(), new_id()]
    source = PendingContentDerivation(
        source_block_id=new_id(),
        transform_kind="copied",
        transform_version="1",
    )

    for derived_block_id in derived_block_ids:
        execution.register_content_derivations(
            derived_block_id=derived_block_id,
            sources=(source,),
        )

    assert execution.content_derivations(derived_block_ids[0]) == ()
    assert execution.content_derivations(derived_block_ids[1]) == (source,)
    assert execution.content_derivations(derived_block_ids[2]) == (source,)


def test_attempt_adapter_strips_markers_without_an_active_execution_call() -> None:
    message = HumanMessage(
        content="internal context",
        additional_kwargs={
            "hide_from_ui": True,
            ANSICH_BLOCK_REF_KEY: new_id(),
            ANSICH_CONTENT_KIND_KEY: "middleware_injection",
            ANSICH_PRODUCER_KIND_KEY: "test",
            ANSICH_PRODUCER_ENTITY_ID_KEY: new_id(),
        },
    )
    request = ModelRequest(
        model=object(),
        messages=[message],
        state={"messages": [message]},
        runtime=SimpleNamespace(context={}),
    )
    captured = {}

    AnsichAttemptMiddleware().wrap_model_call(
        request,
        lambda provider_request: captured.setdefault("message", provider_request.messages[0]),
    )

    provider_kwargs = captured["message"].additional_kwargs
    assert provider_kwargs == {"hide_from_ui": True}


def test_durable_block_ref_emits_content_only_once_across_two_attempts(monkeypatch) -> None:
    execution = AnsichExecutionContext(task_id=new_id())
    call = execution.begin_call(actor_kind="lead_agent")
    block_ref = new_id()
    message = HumanMessage(
        id="coalesced-system-message",
        content="large coalesced system prompt",
        additional_kwargs={
            ANSICH_BLOCK_REF_KEY: block_ref,
            ANSICH_CONTENT_KIND_KEY: "system_prompt",
            ANSICH_PRODUCER_KIND_KEY: "system_message_coalescing",
        },
    )
    captured_observations = []

    def capture_batch(_execution, observations, *, batch_kind):
        assert batch_kind == "context_snapshot"
        captured_observations.extend(observations)

    monkeypatch.setattr(model_observer, "_record_batch", capture_batch)

    for attempt_index in range(2):
        capture = serialize_model_request(
            system_message=None,
            messages=(message,),
            tools=(),
            response_format=None,
            model_settings={},
            model=None,
        )
        model_observer._record_captured_request(execution, call, capture)
        if attempt_index == 0:
            produced = next(observation for observation in captured_observations if observation.kind == "content.produced" and observation.subject_id == block_ref)
            execution.mark_observations_durable((produced.obs_id,))

    produced_for_ref = [observation for observation in captured_observations if observation.kind == "content.produced" and observation.subject_id == block_ref]
    assert len(produced_for_ref) == 1
    assert produced_for_ref[0].payload is not None
    assert produced_for_ref[0].payload["source_identity"] == f"block-ref:{block_ref}"


def test_equal_content_with_distinct_source_identity_keeps_distinct_occurrence_blocks() -> None:
    context = AnsichExecutionContext(task_id="00000000-0000-4000-8000-000000000001")

    first = context.resolve_content_occurrence(
        source_identity="message:human-1:occurrence:1:content:0",
        content_hash="a" * 64,
        kind="user_input",
    )
    second = context.resolve_content_occurrence(
        source_identity="message:human-2:occurrence:1:content:0",
        content_hash="a" * 64,
        kind="user_input",
    )

    assert first.block_id != second.block_id
    assert first.producer_obs_id != second.producer_obs_id


def test_context_state_uses_only_durable_parent_and_checkpoints_pending_chains() -> None:
    context = AnsichExecutionContext(task_id="00000000-0000-4000-8000-000000000001")
    first_items = (
        ContextStateItem(
            ordinal=0,
            channel="message",
            role="user",
            block_id="00000000-0000-4000-8000-000000000010",
            visible_bytes=1,
            estimated_tokens=1,
            metadata={},
        ),
    )
    second_items = (
        *first_items,
        first_items[0].model_copy(
            update={
                "ordinal": 1,
                "block_id": "00000000-0000-4000-8000-000000000011",
            }
        ),
    )

    first = context.resolve_context_state(first_items)
    pending_child = context.resolve_context_state(second_items)

    assert first.is_checkpoint is True
    assert pending_child.is_checkpoint is True
    assert pending_child.parent_state_id is None

    context.mark_observations_durable((pending_child.producer_obs_id,))
    third_items = (
        *second_items,
        first_items[0].model_copy(
            update={
                "ordinal": 2,
                "block_id": "00000000-0000-4000-8000-000000000012",
            }
        ),
    )
    durable_child = context.resolve_context_state(third_items)

    assert durable_child.is_checkpoint is False
    assert durable_child.parent_state_id == pending_child.state_id
    assert [operation.op for operation in durable_child.delta] == ["append"]


def test_context_state_chain_is_checkpointed_after_bounded_depth() -> None:
    context = AnsichExecutionContext(task_id="00000000-0000-4000-8000-000000000001")
    items: tuple[ContextStateItem, ...] = ()
    resolutions = []
    for index in range(34):
        items = (
            *items,
            ContextStateItem(
                ordinal=index,
                channel="message",
                role="user",
                block_id=f"00000000-0000-4000-8000-{index:012d}",
                visible_bytes=1,
                estimated_tokens=1,
                metadata={},
            ),
        )
        resolution = context.resolve_context_state(items)
        context.mark_observations_durable((resolution.producer_obs_id,))
        resolutions.append(resolution)

    assert resolutions[32].chain_depth == 32
    assert resolutions[32].is_checkpoint is False
    assert resolutions[33].chain_depth == 0
    assert resolutions[33].is_checkpoint is True


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
        health = service.get_health()
        await service.stop()

        assert [observation.kind for observation in observations] == [
            "step.started",
            "llm.requested",
            "content.produced",
            "context.state_recorded",
            "context.snapshotted",
            "llm.responded",
            "content.produced",
            "step.closed",
        ]
        assert observations[-2].payload["kind"] == "assistant_output"
        assert observations[-2].payload["producer_kind"] == "llm_response"
        assert observations[-2].causation_obs_id == observations[-3].obs_id
        assert observations[0].payload == {"step_seq": 1, "actor_kind": "lead_agent"}
        assert observations[-1].payload["effective_attempt_no"] == 1
        assert observations[-1].payload["result"] == "final_answer"
        assert len(steps) == 1
        assert steps[0].attempts[0].effective is True
        assert context.items[0].body is None
        assert payload is not None
        assert payload.body == "hello"
        assert health.snapshot_request_count == 1
        assert health.snapshot_observations_accepted == 4
        assert health.snapshot_observations_dropped == 0

    asyncio.run(scenario())


def test_successful_persistence_confirms_task_local_occurrence() -> None:
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
            {"messages": [HumanMessage(id="durable-message", content="hello")]},
            context={ANSICH_EXECUTION_CONTEXT_KEY: execution},
        )
        await service.flush_task(task_id)
        resolution = execution.resolve_content_occurrence(
            source_identity="message:durable-message:occurrence:1:content:0",
            content_hash=hashlib.sha256(b"hello").hexdigest(),
            kind="user_input",
        )
        await service.stop()

        assert resolution.should_emit is False

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


@tool
def _observed_failure(value: str) -> str:
    """Raise a deterministic tool failure."""
    raise RuntimeError(f"failed: {value}")


@tool
def _observed_secret(password: str) -> str:
    """Return a secret so both arguments and results exercise redaction."""
    return password


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


class _FailingToolThenFinalModel(_ToolThenFinalModel):
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
                                    "id": "provider-failure-1",
                                    "name": "_observed_failure",
                                    "args": {"value": "boom"},
                                }
                            ],
                        )
                    )
                ]
            )
        return _FinalAnswerModel._generate(
            self,
            messages,
            stop=stop,
            run_manager=run_manager,
            **kwargs,
        )


class _RepeatedProviderIdModel(_ToolThenFinalModel):
    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.call_count += 1
        if self.call_count <= 2:
            return ChatResult(
                generations=[
                    ChatGeneration(
                        message=AIMessage(
                            content="",
                            tool_calls=[
                                {
                                    "id": "reused-provider-id",
                                    "name": "_observed_noop",
                                    "args": {"value": "same"},
                                }
                            ],
                        )
                    )
                ]
            )
        return _FinalAnswerModel._generate(
            self,
            messages,
            stop=stop,
            run_manager=run_manager,
            **kwargs,
        )


class _ParallelToolModel(_ToolThenFinalModel):
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
                                    "id": "parallel-provider-2",
                                    "name": "_observed_noop",
                                    "args": {"value": "first"},
                                },
                                {
                                    "id": "parallel-provider-1",
                                    "name": "_observed_noop",
                                    "args": {"value": "second"},
                                },
                            ],
                        )
                    )
                ]
            )
        return _FinalAnswerModel._generate(
            self,
            messages,
            stop=stop,
            run_manager=run_manager,
            **kwargs,
        )


class _SecretToolThenFinalModel(_ToolThenFinalModel):
    secret: str

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
                                    "id": "secret-provider-id",
                                    "name": "_observed_secret",
                                    "args": {"password": self.secret},
                                }
                            ],
                        )
                    )
                ]
            )
        return _FinalAnswerModel._generate(
            self,
            messages,
            stop=stop,
            run_manager=run_manager,
            **kwargs,
        )


class _DenyBeforeCallableMiddleware(AgentMiddleware):
    async def awrap_tool_call(self, request, handler):
        return ToolMessage(
            content="denied by policy",
            name=str(request.tool_call.get("name")),
            tool_call_id=str(request.tool_call.get("id")),
            status="error",
        )


def test_tool_decision_is_acting_and_next_decision_closes_with_final_answer() -> None:
    async def scenario() -> None:
        service = AnsichService.in_memory()
        await service.start()
        task_id = new_id()
        execution = AnsichExecutionContext(task_id=task_id, service=service)
        agent = create_agent(
            model=_ToolThenFinalModel(),
            tools=[_observed_noop],
            middleware=[
                AnsichDecisionMiddleware(),
                AnsichVisibleToolMiddleware(),
                AnsichRawToolMiddleware(),
                AnsichAttemptMiddleware(),
            ],
        )

        await agent.ainvoke(
            {"messages": [HumanMessage(content="use a tool")]},
            context={ANSICH_EXECUTION_CONTEXT_KEY: execution},
        )
        await service.flush_task(task_id)
        observations = await service.list_observations(task_id)
        steps = await service.list_steps(task_id)
        tool_call = await service.get_tool_call(steps[0].tool_calls[0].tool_call_id)
        await service.stop()

        assert [(step.step_seq, step.status, step.result) for step in steps] == [
            (1, "closed", "acting"),
            (2, "closed", "final_answer"),
        ]
        assert len(steps[0].issued_tools) == 1
        assert steps[0].issued_tools[0] == {
            "tool_call_id": steps[0].tool_calls[0].tool_call_id,
            "provider_call_id": "provider-call-1",
            "name": "_observed_noop",
            "call_seq": 1,
        }
        assert tool_call is not None
        assert tool_call.authorization.value == "unknown"
        assert tool_call.execution.value == "returned"
        assert tool_call.visible_result.value == "available"
        assert tool_call.raw_results[0].content_hash == tool_call.visible_results[0].content_hash
        assert tool_call.derivations[0].transform_kind == "unchanged"
        assert [
            observation.kind
            for observation in observations
            if observation.subject_id == tool_call.tool_call_id
            or (observation.kind == "content.produced" and observation.payload is not None and str(observation.payload.get("source_identity", "")).startswith(f"tool-call:{tool_call.tool_call_id}:"))
        ] == [
            "tool.issued",
            "tool.started",
            "content.produced",
            "tool.returned_raw",
            "content.produced",
            "tool.result_visible",
        ]

    asyncio.run(scenario())


def test_tool_exception_keeps_raw_failure_separate_from_visible_error() -> None:
    async def scenario() -> None:
        service = AnsichService.in_memory()
        await service.start()
        task_id = new_id()
        execution = AnsichExecutionContext(task_id=task_id, service=service)
        agent = create_agent(
            model=_FailingToolThenFinalModel(),
            tools=[_observed_failure],
            middleware=[
                AnsichDecisionMiddleware(),
                AnsichVisibleToolMiddleware(),
                ToolErrorHandlingMiddleware(),
                AnsichRawToolMiddleware(),
                AnsichAttemptMiddleware(),
            ],
        )

        result = await agent.ainvoke(
            {"messages": [HumanMessage(content="call the failing tool")]},
            context={ANSICH_EXECUTION_CONTEXT_KEY: execution},
        )
        await service.flush_task(task_id)
        step = (await service.list_steps(task_id))[0]
        tool_call = step.tool_calls[0]
        raw_payload = await service.get_content_block_payload(tool_call.raw_results[0].content_block_id)
        visible_payload = await service.get_content_block_payload(tool_call.visible_results[0].content_block_id)
        await service.stop()

        assert result["messages"][-1].content == "done"
        assert tool_call.execution.value == "failed"
        assert tool_call.visible_result.value == "available"
        assert tool_call.derivations[0].transform_kind == "error_normalized"
        assert raw_payload is not None
        assert raw_payload.body["error_type"].endswith("RuntimeError")
        assert visible_payload is not None
        assert "Error: Tool '_observed_failure' failed" in visible_payload.body["content"]

    asyncio.run(scenario())


def test_tool_short_circuit_is_denied_and_not_recorded_as_executed() -> None:
    async def scenario() -> None:
        service = AnsichService.in_memory()
        await service.start()
        task_id = new_id()
        execution = AnsichExecutionContext(task_id=task_id, service=service)
        agent = create_agent(
            model=_ToolThenFinalModel(),
            tools=[_observed_noop],
            middleware=[
                AnsichDecisionMiddleware(),
                AnsichVisibleToolMiddleware(),
                _DenyBeforeCallableMiddleware(),
                AnsichRawToolMiddleware(),
                AnsichAttemptMiddleware(),
            ],
        )

        await agent.ainvoke(
            {"messages": [HumanMessage(content="try a denied tool")]},
            context={ANSICH_EXECUTION_CONTEXT_KEY: execution},
        )
        await service.flush_task(task_id)
        tool_call = (await service.list_steps(task_id))[0].tool_calls[0]
        await service.stop()

        assert tool_call.authorization.value == "denied"
        assert tool_call.execution.value == "denied"
        assert tool_call.visible_result.value == "available"
        assert tool_call.started_obs_id is None
        assert tool_call.raw_results == ()

    asyncio.run(scenario())


def test_reconciliation_marks_missing_terminal_unknown_without_inventing_execution() -> None:
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
            {"messages": [HumanMessage(content="leave terminal unobserved")]},
            context={ANSICH_EXECUTION_CONTEXT_KEY: execution},
        )
        await service.flush_task(task_id)
        persisted_call = (await service.list_steps(task_id))[0].tool_calls[0]
        recovered_execution = AnsichExecutionContext(
            task_id=task_id,
            service=service,
            next_step_seq=3,
            tool_calls=[persisted_call],
        )
        reconcile_open_tool_calls(recovered_execution)
        reconcile_open_tool_calls(recovered_execution)
        await service.flush_task(task_id)
        observations = await service.list_observations(task_id)
        tool_call = (await service.list_steps(task_id))[0].tool_calls[0]
        await service.stop()

        assert tool_call.execution.value == "unknown_terminal"
        assert tool_call.visible_result.value == "unknown"
        assert tool_call.started_obs_id is None
        assert [item.kind for item in observations].count("tool.unknown_terminal") == 1

    asyncio.run(scenario())


def test_reused_provider_id_creates_distinct_ansich_tool_calls_per_step() -> None:
    async def scenario() -> None:
        service = AnsichService.in_memory()
        await service.start()
        task_id = new_id()
        execution = AnsichExecutionContext(task_id=task_id, service=service)
        agent = create_agent(
            model=_RepeatedProviderIdModel(),
            tools=[_observed_noop],
            middleware=[
                AnsichDecisionMiddleware(),
                AnsichVisibleToolMiddleware(),
                AnsichRawToolMiddleware(),
                AnsichAttemptMiddleware(),
            ],
        )

        await agent.ainvoke(
            {"messages": [HumanMessage(content="reuse provider id")]},
            context={ANSICH_EXECUTION_CONTEXT_KEY: execution},
        )
        await service.flush_task(task_id)
        calls = [tool_call for step in await service.list_steps(task_id) for tool_call in step.tool_calls]
        await service.stop()

        assert len(calls) == 2
        assert len({item.tool_call_id for item in calls}) == 2
        assert {item.provider_call_id for item in calls} == {"reused-provider-id"}
        assert [item.call_seq for item in calls] == [1, 1]
        assert len({item.step_id for item in calls}) == 2
        assert all(item.execution.value == "returned" for item in calls)

    asyncio.run(scenario())


def test_parallel_tool_calls_are_returned_in_model_issued_order() -> None:
    async def scenario() -> None:
        service = AnsichService.in_memory()
        await service.start()
        task_id = new_id()
        execution = AnsichExecutionContext(task_id=task_id, service=service)
        agent = create_agent(
            model=_ParallelToolModel(),
            tools=[_observed_noop],
            middleware=[
                AnsichDecisionMiddleware(),
                AnsichVisibleToolMiddleware(),
                AnsichRawToolMiddleware(),
                AnsichAttemptMiddleware(),
            ],
        )

        await agent.ainvoke(
            {"messages": [HumanMessage(content="call tools in parallel")]},
            context={ANSICH_EXECUTION_CONTEXT_KEY: execution},
        )
        await service.flush_task(task_id)
        calls = (await service.list_steps(task_id))[0].tool_calls
        await service.stop()

        assert [item.call_seq for item in calls] == [1, 2]
        assert [item.provider_call_id for item in calls] == [
            "parallel-provider-2",
            "parallel-provider-1",
        ]

    asyncio.run(scenario())


def test_tool_arguments_and_results_exclude_known_secret_values() -> None:
    async def scenario() -> None:
        secret = "ansich-tool-secret-value"
        service = AnsichService.in_memory()
        await service.start()
        task_id = new_id()
        execution = AnsichExecutionContext(task_id=task_id, service=service)
        agent = create_agent(
            model=_SecretToolThenFinalModel(secret=secret),
            tools=[_observed_secret],
            middleware=[
                AnsichDecisionMiddleware(),
                AnsichVisibleToolMiddleware(),
                AnsichRawToolMiddleware(),
                AnsichAttemptMiddleware(),
            ],
        )

        await agent.ainvoke(
            {"messages": [HumanMessage(content="exercise secret redaction")]},
            context={
                ANSICH_EXECUTION_CONTEXT_KEY: execution,
                "secrets": {"TEST_SECRET": secret},
            },
        )
        await service.flush_task(task_id)
        observations = await service.list_observations(task_id)
        tool_call = (await service.list_steps(task_id))[0].tool_calls[0]
        raw = await service.get_content_block_payload(tool_call.raw_results[0].content_block_id)
        visible = await service.get_content_block_payload(tool_call.visible_results[0].content_block_id)
        await service.stop()

        assert tool_call.args_preview == {}
        assert raw is not None and raw.body["content"] == "<redacted>"
        assert visible is not None and visible.body["content"] == "<redacted>"
        assert secret not in json.dumps([item.model_dump(mode="json") for item in observations])

    asyncio.run(scenario())


def test_tool_observation_failure_does_not_change_callable_result() -> None:
    async def scenario() -> None:
        service = AnsichService.in_memory()
        execution = AnsichExecutionContext(task_id=new_id(), service=service)
        agent = create_agent(
            model=_ToolThenFinalModel(),
            tools=[_observed_noop],
            middleware=[
                AnsichDecisionMiddleware(),
                AnsichVisibleToolMiddleware(),
                AnsichRawToolMiddleware(),
                AnsichAttemptMiddleware(),
            ],
        )

        result = await agent.ainvoke(
            {"messages": [HumanMessage(content="run while collector is stopped")]},
            context={ANSICH_EXECUTION_CONTEXT_KEY: execution},
        )

        assert result["messages"][-1].content == "done"
        tool_messages = [message for message in result["messages"] if isinstance(message, ToolMessage)]
        assert tool_messages[0].content == "ok"

    asyncio.run(scenario())


def test_rejected_raw_batch_keeps_visible_lineage_valid_and_reconciliation_open(
    monkeypatch,
) -> None:
    async def scenario() -> None:
        service = AnsichService.in_memory()
        await service.start()
        task_id = new_id()
        execution = AnsichExecutionContext(task_id=task_id, service=service)
        original_record_batch = tool_observer._record_batch
        visible_observations = []

        def reject_raw_batch(execution, observations, *, batch_kind):
            if batch_kind == "tool_raw_result":
                return False
            if batch_kind == "tool_visible_result":
                visible_observations.extend(observations)
            return original_record_batch(
                execution,
                observations,
                batch_kind=batch_kind,
            )

        monkeypatch.setattr(tool_observer, "_record_batch", reject_raw_batch)
        agent = create_agent(
            model=_ToolThenFinalModel(),
            tools=[_observed_noop],
            middleware=[
                AnsichDecisionMiddleware(),
                AnsichVisibleToolMiddleware(),
                AnsichRawToolMiddleware(),
                AnsichAttemptMiddleware(),
            ],
        )

        await agent.ainvoke(
            {"messages": [HumanMessage(content="reject only the raw batch")]},
            context={ANSICH_EXECUTION_CONTEXT_KEY: execution},
        )
        reconcile_open_tool_calls(execution)
        await service.flush_task(task_id)
        tool_call = (await service.list_steps(task_id))[0].tool_calls[0]
        visible = next(item for item in visible_observations if item.kind == "tool.result_visible")
        await service.stop()

        assert visible.payload is not None
        assert visible.payload["source_block_id"] is None
        assert visible.payload["transform_kind"] == "unknown"
        assert visible.causation_obs_id == tool_call.started_obs_id
        assert tool_call.execution.value == "unknown_terminal"
        assert tool_call.visible_result.value == "available"
        assert tool_call.raw_results == ()
        assert tool_call.derivations == ()

    asyncio.run(scenario())


def test_started_probe_failure_does_not_reclassify_executed_tool_as_denied(
    monkeypatch,
) -> None:
    async def scenario() -> None:
        service = AnsichService.in_memory()
        await service.start()
        task_id = new_id()
        execution = AnsichExecutionContext(task_id=task_id, service=service)
        original_next_sequence = execution.next_producer_seq
        failed_started_probe = False

        def fail_first_tool_boundary_sequence() -> int:
            nonlocal failed_started_probe
            if execution.current_tool_invocation() is not None and not failed_started_probe:
                failed_started_probe = True
                raise RuntimeError("started probe failed")
            return original_next_sequence()

        monkeypatch.setattr(
            execution,
            "next_producer_seq",
            fail_first_tool_boundary_sequence,
        )
        agent = create_agent(
            model=_ToolThenFinalModel(),
            tools=[_observed_noop],
            middleware=[
                AnsichDecisionMiddleware(),
                AnsichVisibleToolMiddleware(),
                AnsichRawToolMiddleware(),
                AnsichAttemptMiddleware(),
            ],
        )

        result = await agent.ainvoke(
            {"messages": [HumanMessage(content="run through a failed probe")]},
            context={ANSICH_EXECUTION_CONTEXT_KEY: execution},
        )
        await service.flush_task(task_id)
        observations = await service.list_observations(task_id)
        tool_call = (await service.list_steps(task_id))[0].tool_calls[0]
        await service.stop()

        assert result["messages"][-1].content == "done"
        assert failed_started_probe is True
        assert tool_call.execution.value == "issued"
        assert tool_call.visible_result.value == "available"
        assert "tool.denied" not in {item.kind for item in observations}

    asyncio.run(scenario())


def test_same_message_occurrence_reuses_content_block_across_snapshots() -> None:
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
            {"messages": [HumanMessage(id="stable-user-message", content="use a tool")]},
            context={ANSICH_EXECUTION_CONTEXT_KEY: execution},
        )
        await service.flush_task(task_id)
        observations = await service.list_observations(task_id)
        steps = await service.list_steps(task_id)
        contexts = [await service.get_step_context(step.step_id) for step in steps]
        await service.stop()

        snapshots = [observation for observation in observations if observation.kind == "context.snapshotted"]
        user_block_ids = [item.block_id for context in contexts if context is not None for item in context.items if item.message_id == "stable-user-message"]
        user_blocks = [observation for observation in observations if observation.kind == "content.produced" and observation.payload is not None and observation.payload.get("kind") == "user_input"]
        assert len(snapshots) == 2
        assert all(snapshot.payload is not None and "state_id" in snapshot.payload and "items" not in snapshot.payload for snapshot in snapshots)
        assert len(user_block_ids) == 2
        assert len(set(user_block_ids)) == 1
        assert len(user_blocks) == 1
        assert user_blocks[0].subject_id == user_block_ids[0]

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


def test_error_fallback_message_closes_step_as_model_failed() -> None:
    async def scenario() -> None:
        service = AnsichService.in_memory()
        await service.start()
        task_id = new_id()
        execution = AnsichExecutionContext(task_id=task_id, service=service)
        retry = LLMErrorHandlingMiddleware(app_config=AppConfig(sandbox=SandboxConfig(use="test")))
        retry.retry_max_attempts = 1
        retry.retry_base_delay_ms = 0
        retry.retry_cap_delay_ms = 0
        agent = create_agent(
            model=_AlwaysFailModel(),
            tools=[],
            middleware=[AnsichDecisionMiddleware(), retry, AnsichAttemptMiddleware()],
        )

        result = await agent.ainvoke(
            {"messages": [HumanMessage(content="fail with fallback")]},
            context={ANSICH_EXECUTION_CONTEXT_KEY: execution},
        )
        await service.flush_task(task_id)
        step = (await service.list_steps(task_id))[0]
        await service.stop()

        assert result["messages"][-1].additional_kwargs["deerflow_error_fallback"] is True
        assert step.status == "model_failed"
        assert step.result == "model_failed"
        assert step.effective_attempt_no is None
        assert step.attempts[0].status == "failed"

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
    assert lead_names.index("AnsichVisibleToolMiddleware") < lead_names.index("ToolOutputBudgetMiddleware")
    assert lead_names.index("ToolOutputBudgetMiddleware") < lead_names.index("ToolResultSanitizationMiddleware")
    assert lead_names.index("ToolErrorHandlingMiddleware") < lead_names.index("AnsichRawToolMiddleware")

    subagent = build_subagent_runtime_middlewares(app_config=enabled)
    subagent_names = [type(middleware).__name__ for middleware in subagent]
    assert subagent_names.index("AnsichDecisionMiddleware") < subagent_names.index("LLMErrorHandlingMiddleware")
    assert subagent_names.index("AnsichVisibleToolMiddleware") < subagent_names.index("ToolOutputBudgetMiddleware")
    assert subagent_names.index("ToolErrorHandlingMiddleware") < subagent_names.index("AnsichRawToolMiddleware")
    assert subagent_names[-1] == "AnsichAttemptMiddleware"

    disabled_names = [type(middleware).__name__ for middleware in build_middlewares({}, model_name=None, app_config=disabled)]
    assert "AnsichDecisionMiddleware" not in disabled_names
    assert "AnsichAttemptMiddleware" not in disabled_names
    assert "AnsichVisibleToolMiddleware" not in disabled_names
    assert "AnsichRawToolMiddleware" not in disabled_names


def test_tool_registry_fallback_never_binds_across_tool_names() -> None:
    """A drifted args hash may fall back only within the same tool (phase-3 M1)."""
    context = AnsichExecutionContext(task_id="00000000-0000-4000-8000-000000000001")
    context.register_tool_call(
        tool_call_id="00000000-0000-4000-8000-000000000020",
        step_id="00000000-0000-4000-8000-000000000021",
        step_seq=1,
        call_seq=1,
        provider_call_id=None,
        tool_name="web_search",
        args_hash="a" * 64,
        issued_obs_id="00000000-0000-4000-8000-000000000022",
    )
    write_file = context.register_tool_call(
        tool_call_id="00000000-0000-4000-8000-000000000023",
        step_id="00000000-0000-4000-8000-000000000021",
        step_seq=1,
        call_seq=2,
        provider_call_id=None,
        tool_name="write_file",
        args_hash="b" * 64,
        issued_obs_id="00000000-0000-4000-8000-000000000024",
    )

    resolved = context.resolve_tool_call(
        provider_call_id=None,
        tool_name="write_file",
        args_hash="c" * 64,
    )

    assert resolved is write_file


def test_tool_registry_refuses_ambiguous_binding_without_provider_id() -> None:
    """Two same-name providerless calls with drifted hashes must not guess (phase-3 M1)."""
    context = AnsichExecutionContext(task_id="00000000-0000-4000-8000-000000000001")
    for suffix, args_hash in (("30", "a" * 64), ("33", "b" * 64)):
        context.register_tool_call(
            tool_call_id=f"00000000-0000-4000-8000-0000000000{suffix}",
            step_id="00000000-0000-4000-8000-000000000031",
            step_seq=1,
            call_seq=int(suffix) - 29,
            provider_call_id=None,
            tool_name="bash",
            args_hash=args_hash,
            issued_obs_id=f"00000000-0000-4000-8000-0000000000{int(suffix) + 2}",
        )

    resolved = context.resolve_tool_call(
        provider_call_id=None,
        tool_name="bash",
        args_hash="c" * 64,
    )

    assert resolved is None
