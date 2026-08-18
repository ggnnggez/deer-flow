from __future__ import annotations

import asyncio
import hashlib
import posixpath
import re
import shlex
import time
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import get_args
from uuid import uuid4

from ansich import (
    AuthorizationSnapshot,
    ObservationEnvelope,
    Producer,
    ToolEffect,
    canonical_config_hash,
    new_id,
)
from ansich.serialization import (
    ANSICH_PRODUCER_ENTITY_ID_KEY,
    ANSICH_PRODUCER_KIND_KEY,
    ObservedContentCapture,
    serialize_observed_content,
)
from ansich.tool import ToolTransformKind
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.errors import GraphBubbleUp
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from deerflow.agents.middlewares.tool_transform_meta import read_tool_transforms
from deerflow.ansich.execution import AnsichExecutionContext, ToolInvocation
from deerflow.ansich.middleware import execution_context_from_runtime
from deerflow.authz.outcome import AuthorizationOutcome, pop_authorization_outcome
from deerflow.runtime.secret_context import extract_request_secrets, read_active_secrets

_PRODUCER_INSTANCE_ID = str(uuid4())
_TRANSFORM_KINDS = frozenset(get_args(ToolTransformKind))


def _producer() -> Producer:
    return Producer(name="deerflow-tool-observer", version="1", instance_id=_PRODUCER_INSTANCE_ID)


def _runtime_context(request: ToolCallRequest) -> object:
    return getattr(getattr(request, "runtime", None), "context", None)


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


def _result_producer_metadata(
    result: ToolMessage | Command,
    request: ToolCallRequest,
) -> dict[str, str]:
    message = _tool_message(result, request)
    additional_kwargs = None if message is None else getattr(message, "additional_kwargs", None)
    if not isinstance(additional_kwargs, Mapping):
        return {}
    producer_kind = additional_kwargs.get(ANSICH_PRODUCER_KIND_KEY)
    producer_entity_id = additional_kwargs.get(ANSICH_PRODUCER_ENTITY_ID_KEY)
    if not isinstance(producer_kind, str) or not isinstance(producer_entity_id, str):
        return {}
    return {
        "producer_kind": producer_kind,
        "producer_entity_id": producer_entity_id,
    }


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


def _record_started(
    execution: AnsichExecutionContext,
    invocation: ToolInvocation,
    *,
    authorization_outcome: AuthorizationOutcome | None = None,
) -> None:
    registration = invocation.registration
    # Mark the real callable boundary before any observer work. If sequence
    # allocation or Collector enqueue fails, the outer visible probe must not
    # misclassify a call that did run as a policy denial.
    invocation.started = True
    invocation.started_at = time.monotonic()
    _record_authorization(
        execution,
        invocation,
        outcome=authorization_outcome,
        fallback_reason_code="callable_boundary_entered",
    )
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


def _record_authorization(
    execution: AnsichExecutionContext,
    invocation: ToolInvocation,
    *,
    outcome: AuthorizationOutcome | None,
    fallback_reason_code: str,
) -> None:
    if invocation.authorization_recorded:
        return
    registration = invocation.registration
    if outcome is not None:
        decision = outcome.decision
        policy_id = outcome.policy_id
        policy_version = outcome.policy_version
        reason_codes = outcome.reason_codes or (fallback_reason_code,)
        details_available = outcome.details_available
    else:
        # No authorization layer evaluated this call (guardrails off, or the
        # guardrail did not run for this tool). Record it honestly as unknown:
        # the evidence code still says whether the callable was reached, but the
        # decision no longer masquerades as an authorization verdict.
        decision = "unknown"
        policy_id = "deerflow-tool-middleware-chain"
        policy_version = "1"
        reason_codes = (fallback_reason_code,)
        details_available = False
    snapshot_id = new_id()
    evaluated_obs_id = new_id()
    decision_obs_id = new_id()
    evaluated_at = datetime.now(UTC)
    snapshot = AuthorizationSnapshot(
        snapshot_id=snapshot_id,
        tool_call_id=registration.tool_call_id,
        policy_id=policy_id,
        policy_version=policy_version,
        policy_hash=canonical_config_hash({"policy": policy_id, "version": policy_version}),
        decision=decision,
        details_available=details_available,
        reason_codes=reason_codes,
        evaluated_at=evaluated_at,
        evidence_obs_ids=(evaluated_obs_id, decision_obs_id),
    )
    common = {
        "occurred_at": evaluated_at,
        "task_id": execution.task_id,
        "step_id": registration.step_id,
        "subject_type": "authorization_snapshot",
        "subject_id": snapshot_id,
        "producer": _producer(),
        "correlation_id": execution.task_id,
        "payload": {"snapshot": snapshot.model_dump(mode="json")},
    }
    evaluated = ObservationEnvelope(
        obs_id=evaluated_obs_id,
        kind="authorization.evaluated",
        producer_seq=execution.next_producer_seq(),
        source_event_id=f"tool:{registration.tool_call_id}:authorization:evaluated",
        causation_obs_id=registration.issued_obs_id,
        **common,
    )
    decided = ObservationEnvelope(
        obs_id=decision_obs_id,
        kind=f"authorization.{decision}",  # type: ignore[arg-type]
        producer_seq=execution.next_producer_seq(),
        source_event_id=f"tool:{registration.tool_call_id}:authorization:{decision}",
        causation_obs_id=evaluated_obs_id,
        **common,
    )
    _record_batch(
        execution,
        [evaluated, decided],
        batch_kind="tool_authorization",
    )
    invocation.authorization_recorded = True


# Shell metacharacters that make a command's effect surface unidentifiable.
# Any of these anywhere in the command string means the shell may chain
# (`;` `&` `|`), redirect (`<` `>`), substitute (`$` backtick `(` `)`), expand
# (`{` `}`), or run more than one command (newline) - none of which the leading
# command word describes. Glob characters are deliberately NOT listed: they only
# widen the target set of the same single command. See `_leading_command_word`.
_SHELL_METACHARACTERS = frozenset("|&;<>()`$\n\r{}")
_ENV_ASSIGNMENT_PREFIX = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_DELETE_COMMANDS = frozenset({"rm", "unlink", "rmdir"})
_PERMISSION_COMMANDS = frozenset({"chmod", "chown", "chgrp"})


def _leading_command_word(command: str) -> str | None:
    """Return the basename of the leading command word, or ``None``.

    Deliberately maximally conservative (phase-9 M1 / ruling HR2): a command
    string is parsed at all only when it is ONE simple command carrying no
    shell metacharacter whatsoever. Pipes, ``&&``/``||``/``;`` chains,
    redirections, substitutions, and multi-line scripts all return ``None`` so
    the caller keeps the honest ``process_execute`` + ``unknown`` pair instead
    of asserting a narrower class from a command word that only describes the
    first of several effects.

    Leading ``NAME=value`` environment assignments are skipped so
    ``DEBUG=1 rm x`` still resolves to ``rm``; the command word itself is
    reduced to its basename so ``/bin/rm`` resolves to ``rm``.
    """

    if not command or any(character in _SHELL_METACHARACTERS for character in command):
        return None
    try:
        tokens = shlex.split(command)
    except ValueError:
        # Unbalanced quoting: the real argv is unknown, so refuse to guess.
        return None
    for token in tokens:
        if _ENV_ASSIGNMENT_PREFIX.match(token):
            continue
        return posixpath.basename(token.replace("\\", "/")) or None
    return None


def _bash_effect_class(args: Mapping[str, object] | None) -> str:
    command = args.get("command") if isinstance(args, Mapping) else None
    if not isinstance(command, str):
        return "process_execute"
    word = _leading_command_word(command)
    if word in _DELETE_COMMANDS:
        return "filesystem_delete"
    if word in _PERMISSION_COMMANDS:
        return "permission_change"
    return "process_execute"


def _tool_call_args(request: ToolCallRequest) -> Mapping[str, object] | None:
    args = request.tool_call.get("args")
    return args if isinstance(args, Mapping) else None


def _effect_class(tool_name: str, args: Mapping[str, object] | None = None) -> str:
    normalized = tool_name.lower().strip("_")
    if normalized in {"read_file", "view_file"} or normalized.endswith("read_file"):
        return "filesystem_read"
    if normalized in {"write_file", "edit_file"} or normalized.endswith("write_file"):
        return "filesystem_write"
    if normalized == "bash" or normalized.endswith("bash_tool"):
        # No built-in tool deletes files or changes permissions, so bash argv
        # patterns are the whole production surface for `filesystem_delete`
        # and `permission_change`.
        return _bash_effect_class(args)
    if normalized == "task" or normalized.endswith("task_tool"):
        return "child_task_spawn"
    if "search" in normalized or normalized in {"fetch", "http_get", "web"}:
        return "network_read"
    return "unknown"


def _effect_target_preview(request: ToolCallRequest) -> str:
    args = request.tool_call.get("args")
    if not isinstance(args, Mapping):
        return f"tool:{request.tool_call.get('name') or 'unknown'}"
    for key in ("path", "file_path"):
        value = args.get(key)
        if isinstance(value, str) and value:
            normalized = posixpath.normpath(value.replace("\\", "/"))
            if normalized.startswith("/"):
                return f"<absolute>/{posixpath.basename(normalized)}"
            return normalized[:512]
    return f"tool:{request.tool_call.get('name') or 'unknown'}"


def _effect_observation(
    execution: AnsichExecutionContext,
    invocation: ToolInvocation,
    *,
    effect_class: str,
    phase: str,
    fidelity_class: str,
    target_hash: str | None,
    target_preview: str | None,
    ordinal: int = 0,
    causation_obs_id: str | None = None,
) -> ObservationEnvelope:
    registration = invocation.registration
    obs_id = new_id()
    effect = ToolEffect(
        effect_id=new_id(),
        tool_call_id=registration.tool_call_id,
        effect_class=effect_class,
        phase=phase,
        scope_id=None,
        target_hash=target_hash,
        target_preview=target_preview,
        fidelity_class=fidelity_class,
        source_obs_id=obs_id,
        result_metadata={},
    )
    return ObservationEnvelope(
        obs_id=obs_id,
        kind=f"effect.{phase}",  # type: ignore[arg-type]
        occurred_at=datetime.now(UTC),
        task_id=execution.task_id,
        step_id=registration.step_id,
        subject_type="effect",
        subject_id=effect.effect_id,
        producer=_producer(),
        producer_seq=execution.next_producer_seq(),
        source_event_id=(f"tool:{registration.tool_call_id}:effect:{phase}:{effect_class}:{ordinal}"),
        correlation_id=execution.task_id,
        causation_obs_id=causation_obs_id or registration.issued_obs_id,
        payload={"effect": effect.model_dump(mode="json")},
    )


def _record_effect_intent(
    execution: AnsichExecutionContext,
    invocation: ToolInvocation,
    request: ToolCallRequest,
) -> None:
    if invocation.effect_intent_recorded:
        return
    effect_class = _effect_class(invocation.registration.tool_name, _tool_call_args(request))
    observations = [
        _effect_observation(
            execution,
            invocation,
            effect_class=effect_class,
            phase="potential",
            fidelity_class="declared",
            target_hash=None,
            target_preview=f"tool:{invocation.registration.tool_name}",
        ),
        _effect_observation(
            execution,
            invocation,
            effect_class=effect_class,
            phase="intended",
            fidelity_class="inferred",
            target_hash=invocation.registration.args_hash,
            target_preview=_effect_target_preview(request),
            ordinal=1,
        ),
    ]
    _record_batch(execution, observations, batch_kind="tool_effect_intent")
    invocation.effect_intent_recorded = True


def _record_observed_effects(
    execution: AnsichExecutionContext,
    invocation: ToolInvocation,
    tool_args: Mapping[str, object] | None,
) -> None:
    effect_class = _effect_class(invocation.registration.tool_name, tool_args)
    # The task tool owns this hard fact: a successful tool return does not by
    # itself prove that the child Task was created.  Its creation boundary
    # emits child_task_spawn only after TaskControlProbe.created().
    if effect_class == "child_task_spawn":
        return
    fidelity_class = "hard" if (invocation.raw_terminal_kind == "tool.returned_raw" and effect_class != "unknown") else "unknown"
    observations = [
        _effect_observation(
            execution,
            invocation,
            effect_class=effect_class,
            phase="observed",
            fidelity_class=fidelity_class,
            target_hash=invocation.registration.args_hash,
            target_preview=f"tool:{invocation.registration.tool_name}",
            causation_obs_id=invocation.raw_terminal_obs_id,
        )
    ]
    if effect_class == "process_execute":
        # A shell command we could not reduce to one identified leading command
        # keeps this honest companion: its real effect surface is unobservable.
        # A classified `rm`/`chmod` does not, because the metacharacter gate in
        # `_leading_command_word` already proved there is nothing else running.
        observations.append(
            _effect_observation(
                execution,
                invocation,
                effect_class="unknown",
                phase="observed",
                fidelity_class="unknown",
                target_hash=invocation.registration.args_hash,
                target_preview="bash internal effects",
                ordinal=1,
                causation_obs_id=invocation.raw_terminal_obs_id,
            )
        )
    _record_batch(execution, observations, batch_kind="tool_effect_observed")


def _record_raw_result(
    execution: AnsichExecutionContext,
    invocation: ToolInvocation,
    capture: ObservedContentCapture,
    *,
    tool_args: Mapping[str, object] | None,
    terminal_kind: str,
    terminal_payload: dict[str, object] | None = None,
    producer_metadata: Mapping[str, str] | None = None,
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
            **dict(producer_metadata or {}),
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
        _record_observed_effects(execution, invocation, tool_args)


def _classify_transform(
    invocation: ToolInvocation,
    visible: ObservedContentCapture,
    transforms: tuple[Mapping[str, object], ...],
) -> tuple[str, str]:
    """Return ``(transform_kind, classified_by)`` for the raw→visible edge.

    Declared trail entries from the transforming middlewares are the
    authoritative facts; wording heuristics survive only as a labeled fallback
    for transformers that do not stamp metadata yet.
    """

    if invocation.raw_content_hash == visible.block.content_hash:
        return "unchanged", "content_hash"
    if invocation.raw_terminal_kind in {"tool.failed", "tool.timed_out", "tool.cancelled"}:
        return "error_normalized", "raw_terminal"
    declared = [str(entry["kind"]) for entry in transforms if entry.get("kind") in _TRANSFORM_KINDS]
    if declared:
        # The last applied transform produced the final visible bytes; the
        # full ordered trail rides in the observation payload.
        return declared[-1], "declared"
    return _wording_heuristic(visible), "heuristic"


def _wording_heuristic(visible: ObservedContentCapture) -> str:
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
    *,
    transforms: tuple[Mapping[str, object], ...] = (),
    visible_message_id: str | None = None,
    producer_metadata: Mapping[str, str] | None = None,
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
    if source_block_id is not None:
        transform_kind, classified_by = _classify_transform(invocation, capture, transforms)
    else:
        transform_kind, classified_by = "unknown", "no_raw_result"
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
            **dict(producer_metadata or {}),
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
            "transform_kind": transform_kind,
            "transform_version": "1",
            "classified_by": classified_by,
            "transforms": [dict(entry) for entry in transforms],
        },
    )
    observations.append(visible_observation)
    accepted = _record_batch(execution, observations, batch_kind="tool_visible_result")
    if accepted:
        if invocation.raw_recorded or not invocation.started:
            execution.mark_tool_terminal(
                registration.tool_call_id,
                visible=True,
                visible_block_id=block_id,
                visible_message_id=visible_message_id,
            )
        else:
            execution.mark_tool_visible(
                registration.tool_call_id,
                visible_block_id=block_id,
                visible_message_id=visible_message_id,
            )


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
            try:
                invocation = execution.current_tool_invocation()
                if invocation is not None:
                    _record_effect_intent(execution, invocation, request)
            except Exception:
                pass
            result = handler(request)
            try:
                invocation = execution.current_tool_invocation()
                if invocation is not None:
                    if not invocation.started:
                        outcome = pop_authorization_outcome(_runtime_context(request), request.tool_call.get("id"))
                        _record_authorization(
                            execution,
                            invocation,
                            outcome=outcome,
                            fallback_reason_code="short_circuited_before_callable",
                        )
                    visible_message = _tool_message(result, request)
                    _record_visible_result(
                        execution,
                        invocation,
                        _capture_result(result, request, kind="tool_result_visible"),
                        transforms=read_tool_transforms(visible_message),
                        visible_message_id=(visible_message.id if visible_message is not None and isinstance(visible_message.id, str) else None),
                        producer_metadata=_result_producer_metadata(result, request),
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
            try:
                invocation = execution.current_tool_invocation()
                if invocation is not None:
                    _record_effect_intent(execution, invocation, request)
            except Exception:
                pass
            result = await handler(request)
            try:
                invocation = execution.current_tool_invocation()
                if invocation is not None:
                    if not invocation.started:
                        outcome = pop_authorization_outcome(_runtime_context(request), request.tool_call.get("id"))
                        _record_authorization(
                            execution,
                            invocation,
                            outcome=outcome,
                            fallback_reason_code="short_circuited_before_callable",
                        )
                    visible_message = _tool_message(result, request)
                    _record_visible_result(
                        execution,
                        invocation,
                        _capture_result(result, request, kind="tool_result_visible"),
                        transforms=read_tool_transforms(visible_message),
                        visible_message_id=(visible_message.id if visible_message is not None and isinstance(visible_message.id, str) else None),
                        producer_metadata=_result_producer_metadata(result, request),
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
            outcome = pop_authorization_outcome(_runtime_context(request), request.tool_call.get("id"))
            _record_started(execution, invocation, authorization_outcome=outcome)
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
                    tool_args=_tool_call_args(request),
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
                tool_args=_tool_call_args(request),
                terminal_kind="tool.returned_raw",
                producer_metadata=_result_producer_metadata(result, request),
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
            outcome = pop_authorization_outcome(_runtime_context(request), request.tool_call.get("id"))
            _record_started(execution, invocation, authorization_outcome=outcome)
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
                    tool_args=_tool_call_args(request),
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
                tool_args=_tool_call_args(request),
                terminal_kind="tool.returned_raw",
                producer_metadata=_result_producer_metadata(result, request),
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
