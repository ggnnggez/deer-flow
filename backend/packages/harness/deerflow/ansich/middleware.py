from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from uuid import uuid4

from ansich import ObservationEnvelope, Producer, new_id
from ansich.serialization import ContextSnapshotCapture, ContextSnapshotItemCapture, serialize_model_request
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ExtendedModelResponse, ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage

from deerflow.ansich.execution import ANSICH_EXECUTION_CONTEXT_KEY, ActorKind, AnsichExecutionContext, ExecutionCall, OperationKind
from deerflow.runtime.secret_context import extract_request_secrets, read_active_secrets

_PRODUCER_INSTANCE_ID = str(uuid4())


class AnsichDecisionMiddleware(AgentMiddleware):
    """Observe one logical Agent decision outside provider retry logic."""

    def __init__(
        self,
        *,
        actor_kind: ActorKind = "lead_agent",
        operation_kind: OperationKind | None = None,
    ) -> None:
        super().__init__()
        self._actor_kind = actor_kind
        self._operation_kind = operation_kind

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelCallResult],
    ) -> ModelCallResult:
        execution = _execution_context(request)
        if execution is None:
            return handler(request)
        try:
            call = execution.begin_call(actor_kind=self._actor_kind, operation_kind=self._operation_kind)
            _record_step_started(execution, call)
        except Exception:
            return handler(request)
        try:
            with execution.activate(call):
                result = handler(request)
        except BaseException:
            try:
                _record_step_closed(execution, call, result="model_failed", response=None)
            except Exception:
                pass
            raise
        try:
            _record_step_closed(execution, call, result=_decision_result(result), response=result)
        except Exception:
            pass
        return result

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelCallResult]],
    ) -> ModelCallResult:
        execution = _execution_context(request)
        if execution is None:
            return await handler(request)
        try:
            call = execution.begin_call(actor_kind=self._actor_kind, operation_kind=self._operation_kind)
            _record_step_started(execution, call)
        except Exception:
            return await handler(request)
        try:
            with execution.activate(call):
                result = await handler(request)
        except BaseException:
            try:
                _record_step_closed(execution, call, result="model_failed", response=None)
            except Exception:
                pass
            raise
        try:
            _record_step_closed(execution, call, result=_decision_result(result), response=result)
        except Exception:
            pass
        return result


class AnsichAttemptMiddleware(AgentMiddleware):
    """Capture each physical adapter call after request transformations."""

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelCallResult],
    ) -> ModelCallResult:
        execution = _execution_context(request)
        call = execution.current_call() if execution is not None else None
        if execution is None or call is None:
            return handler(request)
        try:
            attempt_id, attempt_no, request_obs_id = _record_request(execution, call, request)
        except Exception:
            return handler(request)
        started = time.monotonic()
        try:
            result = handler(request)
        except BaseException as exc:
            try:
                _record_attempt_failure(execution, call, attempt_id, attempt_no, request_obs_id, exc, started)
            except Exception:
                pass
            raise
        try:
            response_obs_id = _record_attempt_response(execution, call, attempt_id, attempt_no, request_obs_id, result, started)
            call.effective_attempt_no = attempt_no
            call.last_response_obs_id = response_obs_id
        except Exception:
            pass
        return result

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelCallResult]],
    ) -> ModelCallResult:
        execution = _execution_context(request)
        call = execution.current_call() if execution is not None else None
        if execution is None or call is None:
            return await handler(request)
        try:
            attempt_id, attempt_no, request_obs_id = _record_request(execution, call, request)
        except Exception:
            return await handler(request)
        started = time.monotonic()
        try:
            result = await handler(request)
        except BaseException as exc:
            try:
                _record_attempt_failure(execution, call, attempt_id, attempt_no, request_obs_id, exc, started)
            except Exception:
                pass
            raise
        try:
            response_obs_id = _record_attempt_response(execution, call, attempt_id, attempt_no, request_obs_id, result, started)
            call.effective_attempt_no = attempt_no
            call.last_response_obs_id = response_obs_id
        except Exception:
            pass
        return result


def _execution_context(request: ModelRequest) -> AnsichExecutionContext | None:
    runtime = getattr(request, "runtime", None)
    return execution_context_from_runtime(runtime)


def execution_context_from_runtime(runtime: object) -> AnsichExecutionContext | None:
    context = getattr(runtime, "context", None)
    if not isinstance(context, Mapping):
        return None
    execution = context.get(ANSICH_EXECUTION_CONTEXT_KEY)
    return execution if isinstance(execution, AnsichExecutionContext) and execution.service is not None else None


def observe_system_model_invoke(
    model: object,
    input_value: object,
    *,
    execution: AnsichExecutionContext | None,
    operation_kind: OperationKind,
    config: object | None = None,
    runtime_context: object | None = None,
):
    """Invoke a standalone internal model call without creating an Agent Step."""

    if execution is None:
        return model.invoke(input_value, config=config)
    call = execution.begin_call(actor_kind="system_operation", operation_kind=operation_kind)
    try:
        attempt_id, attempt_no, request_obs_id = _record_system_request(
            execution,
            call,
            model,
            input_value,
            runtime_context=runtime_context,
        )
    except Exception:
        return model.invoke(input_value, config=config)
    started = time.monotonic()
    try:
        result = model.invoke(input_value, config=config)
    except BaseException as exc:
        try:
            _record_attempt_failure(execution, call, attempt_id, attempt_no, request_obs_id, exc, started)
        except Exception:
            pass
        raise
    try:
        _record_attempt_response(execution, call, attempt_id, attempt_no, request_obs_id, result, started)
    except Exception:
        pass
    return result


async def observe_system_model_ainvoke(
    model: object,
    input_value: object,
    *,
    execution: AnsichExecutionContext | None,
    operation_kind: OperationKind,
    config: object | None = None,
    runtime_context: object | None = None,
):
    """Async counterpart of :func:`observe_system_model_invoke`."""

    if execution is None:
        return await model.ainvoke(input_value, config=config)
    call = execution.begin_call(actor_kind="system_operation", operation_kind=operation_kind)
    try:
        attempt_id, attempt_no, request_obs_id = _record_system_request(
            execution,
            call,
            model,
            input_value,
            runtime_context=runtime_context,
        )
    except Exception:
        return await model.ainvoke(input_value, config=config)
    started = time.monotonic()
    try:
        result = await model.ainvoke(input_value, config=config)
    except BaseException as exc:
        try:
            _record_attempt_failure(execution, call, attempt_id, attempt_no, request_obs_id, exc, started)
        except Exception:
            pass
        raise
    try:
        _record_attempt_response(execution, call, attempt_id, attempt_no, request_obs_id, result, started)
    except Exception:
        pass
    return result


def _record_step_started(execution: AnsichExecutionContext, call: ExecutionCall) -> None:
    if call.step_id is None or call.step_seq is None:
        return
    observation = ObservationEnvelope(
        kind="step.started",
        occurred_at=datetime.now(UTC),
        task_id=execution.task_id,
        step_id=call.step_id,
        subject_type="step",
        subject_id=call.step_id,
        producer=_producer(),
        producer_seq=execution.next_producer_seq(),
        source_event_id=f"step:{call.step_id}:started",
        correlation_id=execution.task_id,
        payload={"step_seq": call.step_seq, "actor_kind": call.actor_kind},
    )
    call.started_obs_id = observation.obs_id
    _record(execution, observation)


def _record_request(
    execution: AnsichExecutionContext,
    call: ExecutionCall,
    request: ModelRequest,
) -> tuple[str, int, str]:
    context = getattr(getattr(request, "runtime", None), "context", None)
    known_secrets = [
        *extract_request_secrets(context).values(),
        *read_active_secrets(context).values(),
    ]
    try:
        capture = serialize_model_request(
            system_message=request.system_message,
            messages=request.messages,
            tools=request.tools,
            response_format=request.response_format,
            model_settings={**request.model_settings, "tool_choice": request.tool_choice},
            model=request.model,
            known_secrets=known_secrets,
        )
    except Exception as exc:
        capture = ContextSnapshotCapture(
            items=(),
            message_count=0,
            tool_schema_count=0,
            visible_bytes=0,
            estimated_tokens=0,
            adapter_name=f"{type(request.model).__module__}.{type(request.model).__name__}",
            warnings=(f"request_serialization_failed:{type(exc).__name__}",),
        )
    return _record_captured_request(execution, call, capture)


def _record_system_request(
    execution: AnsichExecutionContext,
    call: ExecutionCall,
    model: object,
    input_value: object,
    *,
    runtime_context: object | None,
) -> tuple[str, int, str]:
    if isinstance(input_value, str):
        messages = [HumanMessage(content=input_value)]
    else:
        to_messages = getattr(input_value, "to_messages", None)
        if callable(to_messages):
            messages = list(to_messages())
        elif isinstance(input_value, list | tuple):
            messages = list(input_value)
        else:
            messages = [input_value]
    known_secrets = [
        *extract_request_secrets(runtime_context).values(),
        *read_active_secrets(runtime_context).values(),
    ]
    try:
        capture = serialize_model_request(
            system_message=None,
            messages=messages,
            tools=[],
            response_format=None,
            model_settings={},
            model=model,
            known_secrets=known_secrets,
        )
    except Exception as exc:
        capture = ContextSnapshotCapture(
            items=(),
            message_count=0,
            tool_schema_count=0,
            visible_bytes=0,
            estimated_tokens=0,
            adapter_name=f"{type(model).__module__}.{type(model).__name__}",
            warnings=(f"request_serialization_failed:{type(exc).__name__}",),
        )
    return _record_captured_request(execution, call, capture)


def _record_captured_request(
    execution: AnsichExecutionContext,
    call: ExecutionCall,
    capture: ContextSnapshotCapture,
) -> tuple[str, int, str]:
    attempt_id = new_id()
    attempt_no = execution.next_attempt(call)
    request_observation = ObservationEnvelope(
        kind="llm.requested",
        occurred_at=datetime.now(UTC),
        task_id=execution.task_id,
        step_id=call.step_id,
        subject_type="llm_attempt",
        subject_id=attempt_id,
        producer=_producer(),
        producer_seq=execution.next_producer_seq(),
        source_event_id=f"attempt:{attempt_id}:requested",
        correlation_id=execution.task_id,
        causation_obs_id=call.started_obs_id,
        payload={
            "attempt_no": attempt_no,
            "snapshot_id": capture.snapshot_id,
            "actor_kind": call.actor_kind,
            "operation_id": call.operation_id,
            "operation_kind": call.operation_kind,
            "adapter_name": capture.adapter_name,
            "adapter_version": capture.adapter_version,
            "configured_model": capture.configured_model,
        },
    )
    observations = [request_observation]
    resolved_items: list[tuple[ContextSnapshotItemCapture, str | None, bool]] = []
    for item in capture.items:
        source_identity = _content_source_identity(item)
        is_new_occurrence = True
        if source_identity is not None:
            block_id, is_new_occurrence = execution.resolve_content_occurrence(
                source_identity=source_identity,
                content_hash=item.block.content_hash,
                kind=item.block.kind,
                proposed_block_id=item.block.block_id,
            )
            if block_id != item.block.block_id:
                item = item.model_copy(update={"block": item.block.model_copy(update={"block_id": block_id})})
        resolved_items.append((item, source_identity, is_new_occurrence))
        if not is_new_occurrence:
            continue
        block = item.block
        observations.append(
            ObservationEnvelope(
                kind="content.produced",
                occurred_at=datetime.now(UTC),
                task_id=execution.task_id,
                step_id=call.step_id,
                subject_type="content_block",
                subject_id=block.block_id,
                producer=_producer(),
                producer_seq=execution.next_producer_seq(),
                source_event_id=f"attempt:{attempt_id}:content:{item.ordinal}",
                correlation_id=execution.task_id,
                causation_obs_id=request_observation.obs_id,
                payload={
                    "attempt_id": attempt_id,
                    "occurrence_ordinal": item.ordinal,
                    "source_identity": source_identity,
                    **block.model_dump(mode="json"),
                },
            )
        )
    observations.append(
        ObservationEnvelope(
            kind="context.snapshotted",
            occurred_at=datetime.now(UTC),
            task_id=execution.task_id,
            step_id=call.step_id,
            subject_type="context_snapshot",
            subject_id=capture.snapshot_id,
            producer=_producer(),
            producer_seq=execution.next_producer_seq(),
            source_event_id=f"attempt:{attempt_id}:context",
            correlation_id=execution.task_id,
            causation_obs_id=request_observation.obs_id,
            payload={
                "attempt_id": attempt_id,
                "attempt_no": attempt_no,
                "operation_id": call.operation_id,
                "message_count": capture.message_count,
                "tool_schema_count": capture.tool_schema_count,
                "visible_bytes": capture.visible_bytes,
                "estimated_tokens": capture.estimated_tokens,
                "estimator_name": capture.estimator_name,
                "estimator_version": capture.estimator_version,
                "adapter_name": capture.adapter_name,
                "adapter_version": capture.adapter_version,
                "configured_model": capture.configured_model,
                "response_format": capture.response_format,
                "generation_settings": capture.generation_settings,
                "redactions": [entry.model_dump(mode="json") for entry in capture.redactions],
                "warnings": list(capture.warnings),
                "items": [
                    {
                        "ordinal": item.ordinal,
                        "channel": item.channel,
                        "role": item.role,
                        "message_id": item.message_id,
                        "name": item.name,
                        "block_id": item.block.block_id,
                        "source_identity": source_identity,
                        "visible_bytes": item.block.visible_bytes,
                        "estimated_tokens": item.block.estimated_tokens,
                        "metadata": item.metadata,
                    }
                    for item, source_identity, _ in resolved_items
                ],
            },
        )
    )
    _record_batch(execution, observations, batch_kind="context_snapshot")
    return attempt_id, attempt_no, request_observation.obs_id


def _content_source_identity(item: ContextSnapshotItemCapture) -> str | None:
    if item.channel == "message" and item.message_id:
        part_ordinal = item.metadata.get("part_ordinal")
        if isinstance(part_ordinal, int):
            return f"message:{item.message_id}:content:{part_ordinal}"
        tool_call_ordinal = item.metadata.get("tool_call_ordinal")
        if isinstance(tool_call_ordinal, int):
            return f"message:{item.message_id}:tool-call:{tool_call_ordinal}"
    if item.channel == "tool_schema" and item.name:
        return f"tool-schema:{item.name}"
    return None


def _record_attempt_response(
    execution: AnsichExecutionContext,
    call: ExecutionCall,
    attempt_id: str,
    attempt_no: int,
    request_obs_id: str,
    result: ModelCallResult,
    started: float,
) -> str:
    message = _ai_message(result)
    response_observation = ObservationEnvelope(
        kind="llm.responded",
        occurred_at=datetime.now(UTC),
        task_id=execution.task_id,
        step_id=call.step_id,
        subject_type="llm_attempt",
        subject_id=attempt_id,
        producer=_producer(),
        producer_seq=execution.next_producer_seq(),
        source_event_id=f"attempt:{attempt_id}:responded",
        correlation_id=execution.task_id,
        causation_obs_id=request_obs_id,
        payload={
            "attempt_no": attempt_no,
            "latency_ms": max(0, int((time.monotonic() - started) * 1000)),
            "finish_reason": _finish_reason(message),
            "tool_call_count": len(message.tool_calls) if message is not None else 0,
            "usage": _usage(message),
            "response_metadata": _response_metadata(message),
        },
    )
    _record(execution, response_observation)
    return response_observation.obs_id


def _record_attempt_failure(
    execution: AnsichExecutionContext,
    call: ExecutionCall,
    attempt_id: str,
    attempt_no: int,
    request_obs_id: str,
    exc: BaseException,
    started: float,
) -> None:
    _record(
        execution,
        ObservationEnvelope(
            kind="llm.failed",
            occurred_at=datetime.now(UTC),
            task_id=execution.task_id,
            step_id=call.step_id,
            subject_type="llm_attempt",
            subject_id=attempt_id,
            producer=_producer(),
            producer_seq=execution.next_producer_seq(),
            source_event_id=f"attempt:{attempt_id}:failed",
            correlation_id=execution.task_id,
            causation_obs_id=request_obs_id,
            payload={
                "attempt_no": attempt_no,
                "latency_ms": max(0, int((time.monotonic() - started) * 1000)),
                "error_type": type(exc).__name__,
            },
        ),
    )


def _record_step_closed(
    execution: AnsichExecutionContext,
    call: ExecutionCall,
    *,
    result: str,
    response: ModelCallResult | None,
) -> None:
    if call.step_id is None:
        return
    message = _ai_message(response)
    tools = [] if message is None else [{"provider_call_id": item.get("id"), "name": item.get("name")} for item in message.tool_calls]
    _record(
        execution,
        ObservationEnvelope(
            kind="step.closed",
            occurred_at=datetime.now(UTC),
            task_id=execution.task_id,
            step_id=call.step_id,
            subject_type="step",
            subject_id=call.step_id,
            producer=_producer(),
            producer_seq=execution.next_producer_seq(),
            source_event_id=f"step:{call.step_id}:closed",
            correlation_id=execution.task_id,
            causation_obs_id=call.last_response_obs_id or call.started_obs_id,
            payload={
                "result": result,
                "effective_attempt_no": call.effective_attempt_no,
                "issued_tool_count": len(tools),
                "issued_tools": tools,
            },
        ),
    )


def _decision_result(result: ModelCallResult) -> str:
    message = _ai_message(result)
    return "acting" if message is not None and message.tool_calls else "final_answer"


def _ai_message(result: ModelCallResult | None) -> AIMessage | None:
    if isinstance(result, AIMessage):
        return result
    if isinstance(result, ExtendedModelResponse):
        result = result.model_response
    if isinstance(result, ModelResponse):
        return next((message for message in reversed(result.result) if isinstance(message, AIMessage)), None)
    return None


def _finish_reason(message: AIMessage | None) -> str | None:
    if message is None:
        return None
    value = message.response_metadata.get("finish_reason")
    return value if isinstance(value, str) else None


def _usage(message: AIMessage | None) -> dict[str, int]:
    if message is None or not isinstance(message.usage_metadata, Mapping):
        return {}
    return {key: value for key in ("input_tokens", "output_tokens", "total_tokens") if isinstance((value := message.usage_metadata.get(key)), int)}


def _response_metadata(message: AIMessage | None) -> dict[str, object]:
    if message is None:
        return {}
    allowed: dict[str, object] = {}
    for key in ("finish_reason", "model_name", "system_fingerprint"):
        if key not in message.response_metadata:
            continue
        value = message.response_metadata.get(key)
        if value is None or isinstance(value, str | int | float | bool):
            allowed[key] = value
    return allowed


def _producer() -> Producer:
    return Producer(name="deerflow-model-observer", version="1", instance_id=_PRODUCER_INSTANCE_ID)


def _record(execution: AnsichExecutionContext, observation: ObservationEnvelope) -> None:
    try:
        if execution.service is not None:
            execution.service.record(observation)
    except Exception:
        return


def _record_batch(
    execution: AnsichExecutionContext,
    observations: list[ObservationEnvelope],
    *,
    batch_kind: str,
) -> None:
    try:
        if execution.service is not None:
            execution.service.record_batch(observations, batch_kind=batch_kind)
    except Exception:
        return
