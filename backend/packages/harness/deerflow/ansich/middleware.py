from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from uuid import uuid4

from ansich import ContextStateItem, ObservationEnvelope, Producer, new_id
from ansich.serialization import (
    ANSICH_BLOCK_REF_KEY,
    ANSICH_CONTENT_KIND_KEY,
    ANSICH_PRODUCER_KIND_KEY,
    ContextSnapshotCapture,
    ContextSnapshotItemCapture,
    context_snapshot_item_source_identity,
    serialize_model_request,
    serialize_observed_content,
)
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ExtendedModelResponse, ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage

from deerflow.ansich.execution import (
    ANSICH_EXECUTION_CONTEXT_KEY,
    ActorKind,
    AnsichExecutionContext,
    ContentOccurrenceResolution,
    ExecutionCall,
    OperationKind,
)
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
            _record_step_closed(
                execution,
                call,
                result=_decision_result(result),
                response=result,
                runtime_context=getattr(request.runtime, "context", None),
            )
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
            _record_step_closed(
                execution,
                call,
                result=_decision_result(result),
                response=result,
                runtime_context=getattr(request.runtime, "context", None),
            )
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
        provider_request = _request_without_ansich_metadata(request)
        try:
            attempt_id, attempt_no, request_obs_id = _record_request(execution, call, request)
        except Exception:
            return handler(provider_request)
        started = time.monotonic()
        try:
            result = handler(provider_request)
        except BaseException as exc:
            try:
                _record_attempt_failure(execution, call, attempt_id, attempt_no, request_obs_id, exc, started)
            except Exception:
                pass
            raise
        try:
            response_obs_id = _record_attempt_response(
                execution,
                call,
                attempt_id,
                attempt_no,
                request_obs_id,
                result,
                started,
                runtime_context=getattr(request.runtime, "context", None),
            )
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
        provider_request = _request_without_ansich_metadata(request)
        try:
            attempt_id, attempt_no, request_obs_id = _record_request(execution, call, request)
        except Exception:
            return await handler(provider_request)
        started = time.monotonic()
        try:
            result = await handler(provider_request)
        except BaseException as exc:
            try:
                _record_attempt_failure(execution, call, attempt_id, attempt_no, request_obs_id, exc, started)
            except Exception:
                pass
            raise
        try:
            response_obs_id = _record_attempt_response(
                execution,
                call,
                attempt_id,
                attempt_no,
                request_obs_id,
                result,
                started,
                runtime_context=getattr(request.runtime, "context", None),
            )
            call.effective_attempt_no = attempt_no
            call.last_response_obs_id = response_obs_id
        except Exception:
            pass
        return result


def _execution_context(request: ModelRequest) -> AnsichExecutionContext | None:
    runtime = getattr(request, "runtime", None)
    return execution_context_from_runtime(runtime)


def _request_without_ansich_metadata(request: ModelRequest) -> ModelRequest:
    owned_keys = {
        ANSICH_BLOCK_REF_KEY,
        ANSICH_CONTENT_KIND_KEY,
        ANSICH_PRODUCER_KIND_KEY,
    }

    def clean(message):
        additional_kwargs = getattr(message, "additional_kwargs", None)
        if not isinstance(additional_kwargs, Mapping) or not owned_keys.intersection(additional_kwargs):
            return message
        return message.model_copy(update={"additional_kwargs": {key: value for key, value in additional_kwargs.items() if key not in owned_keys}})

    return request.override(
        system_message=(None if request.system_message is None else clean(request.system_message)),
        messages=[clean(message) for message in request.messages],
    )


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
    call_observer: Callable[[ExecutionCall], None] | None = None,
):
    """Invoke a standalone internal model call without creating an Agent Step."""

    if execution is None:
        return model.invoke(input_value, config=config)
    call = execution.begin_call(actor_kind="system_operation", operation_kind=operation_kind)
    if call_observer is not None:
        call_observer(call)
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
        call.last_response_obs_id = _record_attempt_response(
            execution,
            call,
            attempt_id,
            attempt_no,
            request_obs_id,
            result,
            started,
            runtime_context=runtime_context,
        )
        call.effective_attempt_no = attempt_no
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
    call_observer: Callable[[ExecutionCall], None] | None = None,
):
    """Async counterpart of :func:`observe_system_model_invoke`."""

    if execution is None:
        return await model.ainvoke(input_value, config=config)
    call = execution.begin_call(actor_kind="system_operation", operation_kind=operation_kind)
    if call_observer is not None:
        call_observer(call)
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
        call.last_response_obs_id = _record_attempt_response(
            execution,
            call,
            attempt_id,
            attempt_no,
            request_obs_id,
            result,
            started,
            runtime_context=runtime_context,
        )
        call.effective_attempt_no = attempt_no
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
    resolved_items: list[tuple[ContextSnapshotItemCapture, str | None]] = []
    for item in capture.items:
        source_identity = _content_source_identity(item)
        resolution: ContentOccurrenceResolution | None = None
        block_ref = item.metadata.get(ANSICH_BLOCK_REF_KEY)
        if source_identity is not None and not isinstance(block_ref, str):
            resolution = execution.resolve_content_occurrence(
                source_identity=source_identity,
                content_hash=item.block.content_hash,
                kind=item.block.kind,
            )
            if resolution.block_id != item.block.block_id:
                item = item.model_copy(update={"block": item.block.model_copy(update={"block_id": resolution.block_id})})
        resolved_items.append((item, source_identity))
        if resolution is not None and not resolution.should_emit:
            continue
        block = item.block
        derivation_sources = execution.content_derivations(block.block_id)
        provider_tool_call_id = item.metadata.get("tool_call_id")
        source_block_id = (
            execution.visible_tool_block_id(
                provider_tool_call_id,
                message_id=item.message_id,
            )
            if isinstance(provider_tool_call_id, str)
            else None
        )
        observations.append(
            ObservationEnvelope(
                obs_id=resolution.producer_obs_id if resolution is not None else new_id(),
                kind="content.produced",
                occurred_at=datetime.now(UTC),
                task_id=execution.task_id,
                step_id=call.step_id,
                subject_type="content_block",
                subject_id=block.block_id,
                producer=_producer(),
                producer_seq=execution.next_producer_seq(),
                source_event_id=resolution.source_event_id if resolution is not None else f"attempt:{attempt_id}:content:{item.ordinal}",
                correlation_id=execution.task_id,
                causation_obs_id=request_observation.obs_id,
                payload={
                    "attempt_id": attempt_id,
                    "occurrence_ordinal": item.ordinal,
                    "source_identity": source_identity,
                    "producer_kind": str(item.metadata.get("producer_kind") or "model_request"),
                    "derivation_sources": [
                        {
                            "source_block_id": source.source_block_id,
                            "transform_kind": source.transform_kind,
                            "transform_version": source.transform_version,
                            "source_role": source.source_role,
                            "ordinal": source.ordinal,
                        }
                        for source in derivation_sources
                    ],
                    **(
                        {
                            "source_block_id": source_block_id,
                            "transform_kind": "copied",
                            "transform_version": "1",
                            "source_role": "source",
                        }
                        if source_block_id is not None
                        else {}
                    ),
                    **block.model_dump(mode="json"),
                },
            )
        )
    context_state = execution.resolve_context_state(
        tuple(
            ContextStateItem(
                ordinal=item.ordinal,
                channel=item.channel,
                role=item.role,
                message_id=item.message_id,
                source_identity=source_identity,
                name=item.name,
                block_id=item.block.block_id,
                visible_bytes=item.block.visible_bytes,
                estimated_tokens=item.block.estimated_tokens,
                metadata=item.metadata,
            )
            for item, source_identity in resolved_items
        )
    )
    if context_state.should_emit:
        observations.append(
            ObservationEnvelope(
                obs_id=context_state.producer_obs_id,
                kind="context.state_recorded",
                occurred_at=datetime.now(UTC),
                task_id=execution.task_id,
                step_id=call.step_id,
                subject_type="context_state",
                subject_id=context_state.state_id,
                producer=_producer(),
                producer_seq=execution.next_producer_seq(),
                source_event_id=context_state.source_event_id,
                correlation_id=execution.task_id,
                causation_obs_id=request_observation.obs_id,
                payload={
                    "state_hash": context_state.state_hash,
                    "parent_state_id": context_state.parent_state_id,
                    "chain_depth": context_state.chain_depth,
                    "is_checkpoint": context_state.is_checkpoint,
                    "item_count": context_state.item_count,
                    "checkpoint_items": [item.model_dump(mode="json") for item in context_state.checkpoint_items],
                    "delta": [operation.model_dump(mode="json") for operation in context_state.delta],
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
                "state_id": context_state.state_id,
                "response_format": capture.response_format,
                "generation_settings": capture.generation_settings,
                "redactions": [entry.model_dump(mode="json") for entry in capture.redactions],
                "warnings": list(capture.warnings),
            },
        )
    )
    _record_batch(execution, observations, batch_kind="context_snapshot")
    return attempt_id, attempt_no, request_observation.obs_id


def _content_source_identity(item: ContextSnapshotItemCapture) -> str | None:
    return context_snapshot_item_source_identity(item)


def _record_attempt_response(
    execution: AnsichExecutionContext,
    call: ExecutionCall,
    attempt_id: str,
    attempt_no: int,
    request_obs_id: str,
    result: ModelCallResult,
    started: float,
    *,
    runtime_context: object | None = None,
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
    observations = [response_observation]
    if message is not None:
        capture = serialize_model_request(
            system_message=None,
            messages=(message,),
            tools=(),
            response_format=None,
            model_settings={},
            model=None,
            known_secrets=tuple(
                {
                    *extract_request_secrets(runtime_context).values(),
                    *read_active_secrets(runtime_context).values(),
                }
            ),
        )
        for item in capture.items:
            source_identity = context_snapshot_item_source_identity(item)
            if source_identity is None:
                source_identity = f"llm-attempt:{attempt_id}:response:{item.ordinal}"
            resolution = execution.resolve_content_occurrence(
                source_identity=source_identity,
                content_hash=item.block.content_hash,
                kind=item.block.kind,
            )
            if not resolution.should_emit:
                continue
            block = item.block.model_copy(update={"block_id": resolution.block_id})
            observations.append(
                ObservationEnvelope(
                    obs_id=resolution.producer_obs_id,
                    kind="content.produced",
                    occurred_at=datetime.now(UTC),
                    task_id=execution.task_id,
                    step_id=call.step_id,
                    subject_type="content_block",
                    subject_id=block.block_id,
                    producer=_producer(),
                    producer_seq=execution.next_producer_seq(),
                    source_event_id=resolution.source_event_id,
                    correlation_id=execution.task_id,
                    causation_obs_id=response_observation.obs_id,
                    payload={
                        "attempt_id": attempt_id,
                        "occurrence_ordinal": item.ordinal,
                        "source_identity": source_identity,
                        "producer_kind": "llm_response",
                        "producer_entity_id": attempt_id,
                        **block.model_dump(mode="json"),
                    },
                )
            )
    _record_batch(execution, observations, batch_kind="llm_response")
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
    runtime_context: object | None = None,
) -> None:
    if call.step_id is None:
        return
    message = _ai_message(response)
    observations: list[ObservationEnvelope] = []
    tools: list[dict[str, object]] = []
    known_secrets = [
        *extract_request_secrets(runtime_context).values(),
        *read_active_secrets(runtime_context).values(),
    ]
    for call_seq, item in enumerate(() if message is None else message.tool_calls, start=1):
        provider_call_id = item.get("id") if isinstance(item.get("id"), str) else None
        tool_name = str(item.get("name") or "unknown_tool")
        args_capture = serialize_observed_content(
            kind="tool_request",
            body=item.get("args", {}),
            path=f"tool_calls[{call_seq - 1}].args",
            known_secrets=known_secrets,
        )
        tool_call_id = new_id()
        issued_obs_id = new_id()
        execution.register_tool_call(
            tool_call_id=tool_call_id,
            step_id=call.step_id,
            step_seq=call.step_seq or 0,
            call_seq=call_seq,
            provider_call_id=provider_call_id,
            tool_name=tool_name,
            args_hash=args_capture.block.content_hash,
            issued_obs_id=issued_obs_id,
        )
        tool_schema_block_id = execution.tool_schema_block_id(tool_name)
        tools.append(
            {
                "tool_call_id": tool_call_id,
                "provider_call_id": provider_call_id,
                "name": tool_name,
                "call_seq": call_seq,
            }
        )
        observations.append(
            ObservationEnvelope(
                obs_id=issued_obs_id,
                kind="tool.issued",
                occurred_at=datetime.now(UTC),
                task_id=execution.task_id,
                step_id=call.step_id,
                subject_type="tool_call",
                subject_id=tool_call_id,
                producer=_producer(),
                producer_seq=execution.next_producer_seq(),
                source_event_id=f"tool:{tool_call_id}:issued",
                correlation_id=execution.task_id,
                causation_obs_id=call.last_response_obs_id or call.started_obs_id,
                payload={
                    "call_seq": call_seq,
                    "provider_call_id": provider_call_id,
                    "tool_name": tool_name,
                    "args_hash": args_capture.block.content_hash,
                    "args_preview": args_capture.block.body,
                    "tool_schema_block_id": tool_schema_block_id,
                    "redactions": [entry.model_dump(mode="json") for entry in args_capture.redactions],
                    "warnings": list(args_capture.warnings),
                },
            )
        )
    observations.append(
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
        )
    )
    if len(observations) == 1:
        _record(execution, observations[0])
    else:
        _record_batch(execution, observations, batch_kind="tool_intent")


def _decision_result(result: ModelCallResult) -> str:
    message = _ai_message(result)
    if message is not None and message.additional_kwargs.get("deerflow_error_fallback") is True:
        return "model_failed"
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
