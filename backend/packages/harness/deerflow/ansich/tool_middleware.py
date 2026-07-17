from __future__ import annotations

import asyncio
import hashlib
import time
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from uuid import uuid4

from ansich import ObservationEnvelope, Producer, new_id
from ansich.serialization import ObservedContentCapture, serialize_observed_content
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.errors import GraphBubbleUp
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from deerflow.ansich.execution import AnsichExecutionContext, ToolInvocation
from deerflow.ansich.middleware import execution_context_from_runtime
from deerflow.runtime.secret_context import extract_request_secrets, read_active_secrets

_PRODUCER_INSTANCE_ID = str(uuid4())


def _producer() -> Producer:
    return Producer(name="deerflow-tool-observer", version="1", instance_id=_PRODUCER_INSTANCE_ID)


def _known_secrets(request: ToolCallRequest) -> list[str]:
    context = getattr(getattr(request, "runtime", None), "context", None)
    return [
        *extract_request_secrets(context).values(),
        *read_active_secrets(context).values(),
    ]


def _result_body(result: ToolMessage | Command, request: ToolCallRequest) -> dict[str, object]:
    message = _tool_message(result, request)
    if message is not None:
        body: dict[str, object] = {
            "content": message.content,
            "name": message.name or str(request.tool_call.get("name") or "unknown_tool"),
            "status": message.status,
        }
        if message.artifact is not None:
            body["artifact"] = message.artifact
        return body
    update = getattr(result, "update", None)
    return {
        "command": {
            "update": update if isinstance(update, Mapping) else None,
            "goto": getattr(result, "goto", None),
            "resume": getattr(result, "resume", None),
        }
    }


def _tool_message(result: ToolMessage | Command, request: ToolCallRequest) -> ToolMessage | None:
    if isinstance(result, ToolMessage):
        return result
    update = getattr(result, "update", None)
    messages = update.get("messages") if isinstance(update, Mapping) else None
    if not isinstance(messages, list | tuple):
        return None
    provider_call_id = request.tool_call.get("id")
    return next(
        (message for message in messages if isinstance(message, ToolMessage) and (provider_call_id is None or message.tool_call_id == provider_call_id)),
        None,
    )


def _capture_result(
    result: ToolMessage | Command,
    request: ToolCallRequest,
    *,
    kind: str,
) -> ObservedContentCapture:
    return serialize_observed_content(
        kind=kind,  # type: ignore[arg-type]
        body=_result_body(result, request),
        path=f"tool.{kind}",
        known_secrets=_known_secrets(request),
    )


def _capture_exception(exc: BaseException, request: ToolCallRequest) -> ObservedContentCapture:
    message = str(exc).strip() or type(exc).__name__
    fingerprint_input = f"{type(exc).__module__}.{type(exc).__name__}:{message[:256]}"
    return serialize_observed_content(
        kind="tool_result_raw",
        body={
            "error_type": f"{type(exc).__module__}.{type(exc).__name__}",
            "message": message[:2_000],
            "stack_fingerprint": hashlib.sha256(fingerprint_input.encode()).hexdigest(),
        },
        path="tool.raw_exception",
        known_secrets=_known_secrets(request),
    )


def _resolve_invocation(
    execution: AnsichExecutionContext,
    request: ToolCallRequest,
) -> object | None:
    args_capture = serialize_observed_content(
        kind="tool_request",
        body=request.tool_call.get("args", {}),
        path="tool_call.args",
        known_secrets=_known_secrets(request),
    )
    return execution.resolve_tool_call(
        provider_call_id=(request.tool_call.get("id") if isinstance(request.tool_call.get("id"), str) else None),
        tool_name=str(request.tool_call.get("name") or "unknown_tool"),
        args_hash=args_capture.block.content_hash,
    )


def _record_batch(
    execution: AnsichExecutionContext,
    observations: list[ObservationEnvelope],
    *,
    batch_kind: str,
) -> bool:
    try:
        if execution.service is None:
            return False
        receipts = execution.service.record_batch(observations, batch_kind=batch_kind)
        return bool(receipts) and all(receipt.accepted for receipt in receipts)
    except Exception:
        return False


def _record_started(execution: AnsichExecutionContext, invocation: ToolInvocation) -> None:
    registration = invocation.registration
    # Mark the real callable boundary before any observer work. If sequence
    # allocation or Collector enqueue fails, the outer visible probe must not
    # misclassify a call that did run as a policy denial.
    invocation.started = True
    invocation.started_at = time.monotonic()
    observation = ObservationEnvelope(
        kind="tool.started",
        occurred_at=datetime.now(UTC),
        task_id=execution.task_id,
        step_id=registration.step_id,
        subject_type="tool_call",
        subject_id=registration.tool_call_id,
        producer=_producer(),
        producer_seq=execution.next_producer_seq(),
        source_event_id=f"tool:{registration.tool_call_id}:started",
        correlation_id=execution.task_id,
        causation_obs_id=registration.issued_obs_id,
        payload={"call_seq": registration.call_seq},
    )
    invocation.started_obs_id = observation.obs_id
    _record_batch(execution, [observation], batch_kind="tool_execution")


def _record_raw_result(
    execution: AnsichExecutionContext,
    invocation: ToolInvocation,
    capture: ObservedContentCapture,
    *,
    terminal_kind: str,
    terminal_payload: dict[str, object] | None = None,
) -> None:
    registration = invocation.registration
    block_id = new_id()
    content_observation = ObservationEnvelope(
        kind="content.produced",
        occurred_at=datetime.now(UTC),
        task_id=execution.task_id,
        step_id=registration.step_id,
        subject_type="content_block",
        subject_id=block_id,
        producer=_producer(),
        producer_seq=execution.next_producer_seq(),
        source_event_id=f"tool:{registration.tool_call_id}:raw-content",
        correlation_id=execution.task_id,
        causation_obs_id=invocation.started_obs_id or registration.issued_obs_id,
        payload={
            **capture.block.model_copy(update={"block_id": block_id}).model_dump(mode="json"),
            "source_identity": f"tool-call:{registration.tool_call_id}:raw-result",
            "redactions": [entry.model_dump(mode="json") for entry in capture.redactions],
            "warnings": list(capture.warnings),
        },
    )
    duration_ms = 0
    if invocation.started_at is not None:
        duration_ms = max(0, int((time.monotonic() - invocation.started_at) * 1000))
    terminal_observation = ObservationEnvelope(
        kind=terminal_kind,  # type: ignore[arg-type]
        occurred_at=datetime.now(UTC),
        task_id=execution.task_id,
        step_id=registration.step_id,
        subject_type="tool_call",
        subject_id=registration.tool_call_id,
        producer=_producer(),
        producer_seq=execution.next_producer_seq(),
        source_event_id=f"tool:{registration.tool_call_id}:{terminal_kind.removeprefix('tool.')}",
        correlation_id=execution.task_id,
        causation_obs_id=invocation.started_obs_id or registration.issued_obs_id,
        payload={
            "call_seq": registration.call_seq,
            "result_block_id": block_id,
            "duration_ms": duration_ms,
            **(terminal_payload or {}),
        },
    )
    accepted = _record_batch(
        execution,
        [content_observation, terminal_observation],
        batch_kind="tool_raw_result",
    )
    invocation.raw_block_id = block_id
    invocation.raw_content_hash = capture.block.content_hash
    invocation.raw_terminal_kind = terminal_kind
    invocation.raw_terminal_obs_id = terminal_observation.obs_id
    invocation.raw_recorded = accepted
    if accepted:
        execution.mark_tool_terminal(registration.tool_call_id)


def _transform_kind(invocation: ToolInvocation, visible: ObservedContentCapture) -> str:
    if invocation.raw_content_hash == visible.block.content_hash:
        return "unchanged"
    if invocation.raw_terminal_kind in {"tool.failed", "tool.timed_out", "tool.cancelled"}:
        return "error_normalized"
    body_text = str(visible.block.body).lower()
    if "chars omitted" in body_text:
        return "truncated"
    if "full output" in body_text and "outputs/" in body_text:
        return "externalized"
    if "&lt;" in body_text or "&gt;" in body_text:
        return "sanitized"
    if "human_input" in body_text:
        return "clarification_card"
    return "unknown"


def _record_visible_result(
    execution: AnsichExecutionContext,
    invocation: ToolInvocation,
    capture: ObservedContentCapture,
) -> None:
    registration = invocation.registration
    observations: list[ObservationEnvelope] = []
    if not invocation.started:
        denied = ObservationEnvelope(
            kind="tool.denied",
            occurred_at=datetime.now(UTC),
            task_id=execution.task_id,
            step_id=registration.step_id,
            subject_type="tool_call",
            subject_id=registration.tool_call_id,
            producer=_producer(),
            producer_seq=execution.next_producer_seq(),
            source_event_id=f"tool:{registration.tool_call_id}:denied",
            correlation_id=execution.task_id,
            causation_obs_id=registration.issued_obs_id,
            payload={
                "call_seq": registration.call_seq,
                "reason": "short_circuited_before_callable",
            },
        )
        observations.append(denied)
        invocation.raw_terminal_kind = "tool.denied"
        invocation.raw_terminal_obs_id = denied.obs_id
    block_id = new_id()
    source_block_id = invocation.raw_block_id if invocation.raw_recorded else None
    causation_obs_id = invocation.raw_terminal_obs_id if invocation.raw_recorded or not invocation.started else invocation.started_obs_id or registration.issued_obs_id
    content_observation = ObservationEnvelope(
        kind="content.produced",
        occurred_at=datetime.now(UTC),
        task_id=execution.task_id,
        step_id=registration.step_id,
        subject_type="content_block",
        subject_id=block_id,
        producer=_producer(),
        producer_seq=execution.next_producer_seq(),
        source_event_id=f"tool:{registration.tool_call_id}:visible-content",
        correlation_id=execution.task_id,
        causation_obs_id=causation_obs_id,
        payload={
            **capture.block.model_copy(update={"block_id": block_id}).model_dump(mode="json"),
            "source_identity": f"tool-call:{registration.tool_call_id}:visible-result",
            "redactions": [entry.model_dump(mode="json") for entry in capture.redactions],
            "warnings": list(capture.warnings),
        },
    )
    observations.append(content_observation)
    visible_observation = ObservationEnvelope(
        kind="tool.result_visible",
        occurred_at=datetime.now(UTC),
        task_id=execution.task_id,
        step_id=registration.step_id,
        subject_type="tool_call",
        subject_id=registration.tool_call_id,
        producer=_producer(),
        producer_seq=execution.next_producer_seq(),
        source_event_id=f"tool:{registration.tool_call_id}:visible",
        correlation_id=execution.task_id,
        causation_obs_id=causation_obs_id,
        payload={
            "call_seq": registration.call_seq,
            "result_block_id": block_id,
            "source_block_id": source_block_id,
            "transform_kind": (_transform_kind(invocation, capture) if source_block_id is not None else "unknown"),
            "transform_version": "1",
        },
    )
    observations.append(visible_observation)
    accepted = _record_batch(execution, observations, batch_kind="tool_visible_result")
    if accepted:
        if invocation.raw_recorded or not invocation.started:
            execution.mark_tool_terminal(registration.tool_call_id, visible=True)
        else:
            execution.mark_tool_visible(registration.tool_call_id)


class AnsichVisibleToolMiddleware(AgentMiddleware):
    """Outermost tool wrapper that records the final model-visible result."""

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        execution = execution_context_from_runtime(getattr(request, "runtime", None))
        if execution is None:
            return handler(request)
        try:
            registration = _resolve_invocation(execution, request)
        except Exception:
            return handler(request)
        if registration is None:
            return handler(request)
        with execution.activate_tool_invocation(registration):
            result = handler(request)
            try:
                invocation = execution.current_tool_invocation()
                if invocation is not None:
                    _record_visible_result(
                        execution,
                        invocation,
                        _capture_result(result, request, kind="tool_result_visible"),
                    )
            except Exception:
                pass
            return result

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        execution = execution_context_from_runtime(getattr(request, "runtime", None))
        if execution is None:
            return await handler(request)
        try:
            registration = _resolve_invocation(execution, request)
        except Exception:
            return await handler(request)
        if registration is None:
            return await handler(request)
        with execution.activate_tool_invocation(registration):
            result = await handler(request)
            try:
                invocation = execution.current_tool_invocation()
                if invocation is not None:
                    _record_visible_result(
                        execution,
                        invocation,
                        _capture_result(result, request, kind="tool_result_visible"),
                    )
            except Exception:
                pass
            return result


class AnsichRawToolMiddleware(AgentMiddleware):
    """Innermost tool wrapper around the real callable boundary."""

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        execution = execution_context_from_runtime(getattr(request, "runtime", None))
        invocation = execution.current_tool_invocation() if execution is not None else None
        if execution is None or invocation is None:
            return handler(request)
        try:
            _record_started(execution, invocation)
        except Exception:
            return handler(request)
        try:
            result = handler(request)
        except GraphBubbleUp:
            raise
        except BaseException as exc:
            terminal_kind = "tool.cancelled" if isinstance(exc, asyncio.CancelledError) else "tool.timed_out" if isinstance(exc, TimeoutError) else "tool.failed"
            try:
                _record_raw_result(
                    execution,
                    invocation,
                    _capture_exception(exc, request),
                    terminal_kind=terminal_kind,
                    terminal_payload={"error_type": type(exc).__name__},
                )
            except Exception:
                pass
            raise
        try:
            _record_raw_result(
                execution,
                invocation,
                _capture_result(result, request, kind="tool_result_raw"),
                terminal_kind="tool.returned_raw",
            )
        except Exception:
            pass
        return result

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        execution = execution_context_from_runtime(getattr(request, "runtime", None))
        invocation = execution.current_tool_invocation() if execution is not None else None
        if execution is None or invocation is None:
            return await handler(request)
        try:
            _record_started(execution, invocation)
        except Exception:
            return await handler(request)
        try:
            result = await handler(request)
        except GraphBubbleUp:
            raise
        except BaseException as exc:
            terminal_kind = "tool.cancelled" if isinstance(exc, asyncio.CancelledError) else "tool.timed_out" if isinstance(exc, TimeoutError) else "tool.failed"
            try:
                _record_raw_result(
                    execution,
                    invocation,
                    _capture_exception(exc, request),
                    terminal_kind=terminal_kind,
                    terminal_payload={"error_type": type(exc).__name__},
                )
            except Exception:
                pass
            raise
        try:
            _record_raw_result(
                execution,
                invocation,
                _capture_result(result, request, kind="tool_result_raw"),
                terminal_kind="tool.returned_raw",
            )
        except Exception:
            pass
        return result


def reconcile_open_tool_calls(execution: AnsichExecutionContext) -> None:
    """Close issued calls lacking terminal evidence without inventing success."""

    for registration in execution.open_tool_calls():
        observation = ObservationEnvelope(
            kind="tool.unknown_terminal",
            occurred_at=datetime.now(UTC),
            task_id=execution.task_id,
            step_id=registration.step_id,
            subject_type="tool_call",
            subject_id=registration.tool_call_id,
            producer=_producer(),
            producer_seq=execution.next_producer_seq(),
            source_event_id=f"tool:{registration.tool_call_id}:unknown-terminal",
            correlation_id=execution.task_id,
            causation_obs_id=registration.issued_obs_id,
            payload={
                "call_seq": registration.call_seq,
                "reason": "task_terminal_without_tool_terminal_evidence",
            },
        )
        if _record_batch(execution, [observation], batch_kind="tool_reconciliation"):
            execution.mark_tool_terminal(registration.tool_call_id)
