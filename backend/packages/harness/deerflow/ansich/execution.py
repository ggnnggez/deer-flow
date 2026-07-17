from __future__ import annotations

from collections.abc import Iterable
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from hashlib import sha256
from threading import Lock
from typing import Literal
from uuid import UUID

from ansich import AnsichService, ContentOccurrenceView, ContextStateDelta, ContextStateItem, ContextStateView, ToolCallView, new_id
from ansich.context_state import build_context_state_delta, context_state_hash

ActorKind = Literal["lead_agent", "subagent", "system_operation"]
OperationKind = Literal["title", "summarization", "memory", "goal", "other"]

ANSICH_EXECUTION_CONTEXT_KEY = "__ansich_execution_context"
_CONTENT_OCCURRENCE_NAMESPACE = "a63fb270-277c-5f30-83ad-37b338b53d68"
_MAX_CONTEXT_STATE_CHAIN_DEPTH = 32


def _deterministic_uuid4(value: str) -> str:
    digest = sha256(f"{_CONTENT_OCCURRENCE_NAMESPACE}:{value}".encode()).digest()
    return str(UUID(bytes=digest[:16], version=4))


@dataclass
class ExecutionCall:
    actor_kind: ActorKind
    step_id: str | None
    step_seq: int | None
    operation_id: str | None
    operation_kind: OperationKind | None
    attempt_no: int = 0
    started_obs_id: str | None = None
    last_response_obs_id: str | None = None
    effective_attempt_no: int | None = None


@dataclass(frozen=True)
class ContentOccurrenceResolution:
    source_identity: str
    content_hash: str
    kind: str
    block_id: str
    producer_obs_id: str
    source_event_id: str
    should_emit: bool


@dataclass
class _ContentOccurrenceEntry:
    block_id: str
    producer_obs_id: str
    source_event_id: str
    durable: bool


@dataclass(frozen=True)
class ContextStateResolution:
    state_id: str
    state_hash: str
    parent_state_id: str | None
    chain_depth: int
    is_checkpoint: bool
    item_count: int
    checkpoint_items: tuple[ContextStateItem, ...]
    delta: tuple[ContextStateDelta, ...]
    producer_obs_id: str
    source_event_id: str
    should_emit: bool


@dataclass
class _ContextStateEntry:
    resolution: ContextStateResolution
    items: tuple[ContextStateItem, ...]
    durable: bool


@dataclass
class ToolCallRegistration:
    tool_call_id: str
    step_id: str
    step_seq: int
    call_seq: int
    provider_call_id: str | None
    tool_name: str
    args_hash: str
    issued_obs_id: str
    claimed: bool = False
    terminal_recorded: bool = False
    visible_recorded: bool = False


@dataclass
class ToolInvocation:
    registration: ToolCallRegistration
    started: bool = False
    started_at: float | None = None
    started_obs_id: str | None = None
    raw_block_id: str | None = None
    raw_content_hash: str | None = None
    raw_terminal_kind: str | None = None
    raw_terminal_obs_id: str | None = None
    raw_recorded: bool = False


class AnsichExecutionContext:
    """Run-scoped Step allocator and call carrier.

    A context instance belongs to one Ansich Task. Its current logical call is
    carried by an instance-local ContextVar, so async tasks and copied sync
    contexts do not share a module-global "current Step".
    """

    def __init__(
        self,
        *,
        task_id: str,
        service: AnsichService | None = None,
        next_step_seq: int = 1,
        content_occurrences: Iterable[ContentOccurrenceView] = (),
        context_state: ContextStateView | None = None,
        tool_calls: Iterable[ToolCallView] = (),
    ) -> None:
        if next_step_seq < 1:
            raise ValueError("next_step_seq must be positive")
        self.task_id = task_id
        self.service = service
        self._next_step_seq = next_step_seq
        self._producer_seq = 0
        self._content_occurrences: dict[tuple[str, str, str], _ContentOccurrenceEntry] = {}
        self._content_observation_keys: dict[str, tuple[str, str, str]] = {}
        for occurrence in content_occurrences:
            if occurrence.task_id != task_id:
                raise ValueError("content occurrence belongs to a different task")
            key = (occurrence.source_identity, occurrence.content_hash, occurrence.kind)
            self._content_occurrences[key] = _ContentOccurrenceEntry(
                block_id=occurrence.block_id,
                producer_obs_id=occurrence.producer_obs_id,
                source_event_id=_content_occurrence_source_event_id(task_id, *key),
                durable=True,
            )
            self._content_observation_keys[occurrence.producer_obs_id] = key
        self._context_states_by_hash: dict[str, _ContextStateEntry] = {}
        self._context_state_observation_keys: dict[str, str] = {}
        self._latest_context_state: _ContextStateEntry | None = None
        self._tool_calls: dict[str, ToolCallRegistration] = {}
        for tool_call in tool_calls:
            if tool_call.task_id != task_id:
                raise ValueError("tool call belongs to a different task")
            self._tool_calls[tool_call.tool_call_id] = ToolCallRegistration(
                tool_call_id=tool_call.tool_call_id,
                step_id=tool_call.step_id,
                step_seq=tool_call.step_seq,
                call_seq=tool_call.call_seq,
                provider_call_id=tool_call.provider_call_id,
                tool_name=tool_call.tool_name,
                args_hash=tool_call.args_hash,
                issued_obs_id=(tool_call.issued_obs_id or tool_call.started_obs_id or tool_call.raw_terminal_obs_id or tool_call.visible_result_obs_id or new_id()),
                terminal_recorded=tool_call.execution.value
                in {
                    "returned",
                    "denied",
                    "timed_out",
                    "cancelled",
                    "failed",
                    "unknown_terminal",
                },
                visible_recorded=tool_call.visible_result.value == "available",
            )
        if context_state is not None:
            if context_state.task_id != task_id:
                raise ValueError("context state belongs to a different task")
            resolution = ContextStateResolution(
                state_id=context_state.state_id,
                state_hash=context_state.state_hash,
                parent_state_id=context_state.parent_state_id,
                chain_depth=context_state.chain_depth,
                is_checkpoint=context_state.is_checkpoint,
                item_count=len(context_state.items),
                checkpoint_items=(),
                delta=(),
                producer_obs_id=_deterministic_uuid4(f"context-state-observation:{task_id}:{context_state.state_hash}"),
                source_event_id=f"context-state:{context_state.state_hash}",
                should_emit=False,
            )
            entry = _ContextStateEntry(
                resolution=resolution,
                items=context_state.items,
                durable=True,
            )
            self._context_states_by_hash[context_state.state_hash] = entry
            self._context_state_observation_keys[resolution.producer_obs_id] = context_state.state_hash
            self._latest_context_state = entry
        self._lock = Lock()
        self._current_call: ContextVar[ExecutionCall | None] = ContextVar(
            f"ansich-execution-call-{task_id}",
            default=None,
        )
        self._current_tool_invocation: ContextVar[ToolInvocation | None] = ContextVar(
            f"ansich-tool-invocation-{task_id}",
            default=None,
        )
        if service is not None:
            service.register_persistence_listener(task_id, self.mark_observations_durable)

    @property
    def next_step_seq(self) -> int:
        with self._lock:
            return self._next_step_seq

    def begin_call(
        self,
        *,
        actor_kind: ActorKind,
        operation_kind: OperationKind | None = None,
    ) -> ExecutionCall:
        if actor_kind == "system_operation":
            return ExecutionCall(
                actor_kind=actor_kind,
                step_id=None,
                step_seq=None,
                operation_id=new_id(),
                operation_kind=operation_kind or "other",
            )
        with self._lock:
            step_seq = self._next_step_seq
            self._next_step_seq += 1
        return ExecutionCall(
            actor_kind=actor_kind,
            step_id=new_id(),
            step_seq=step_seq,
            operation_id=None,
            operation_kind=None,
        )

    @contextmanager
    def activate(self, call: ExecutionCall):
        token = self._current_call.set(call)
        try:
            yield call
        finally:
            self._current_call.reset(token)

    def current_call(self) -> ExecutionCall | None:
        return self._current_call.get()

    def register_tool_call(
        self,
        *,
        tool_call_id: str,
        step_id: str,
        step_seq: int,
        call_seq: int,
        provider_call_id: str | None,
        tool_name: str,
        args_hash: str,
        issued_obs_id: str,
    ) -> ToolCallRegistration:
        registration = ToolCallRegistration(
            tool_call_id=tool_call_id,
            step_id=step_id,
            step_seq=step_seq,
            call_seq=call_seq,
            provider_call_id=provider_call_id,
            tool_name=tool_name,
            args_hash=args_hash,
            issued_obs_id=issued_obs_id,
        )
        with self._lock:
            self._tool_calls[tool_call_id] = registration
        return registration

    def resolve_tool_call(
        self,
        *,
        provider_call_id: str | None,
        tool_name: str,
        args_hash: str,
    ) -> ToolCallRegistration | None:
        with self._lock:
            candidates = [
                registration
                for registration in self._tool_calls.values()
                if not registration.claimed and not registration.terminal_recorded and registration.provider_call_id == provider_call_id and registration.tool_name == tool_name and registration.args_hash == args_hash
            ]
            if not candidates:
                candidates = [registration for registration in self._tool_calls.values() if not registration.claimed and not registration.terminal_recorded and registration.provider_call_id == provider_call_id]
            if not candidates:
                return None
            registration = max(candidates, key=lambda item: (item.step_seq, -item.call_seq))
            registration.claimed = True
            return registration

    @contextmanager
    def activate_tool_invocation(self, registration: ToolCallRegistration):
        invocation = ToolInvocation(registration=registration)
        token = self._current_tool_invocation.set(invocation)
        try:
            yield invocation
        finally:
            with self._lock:
                registration.claimed = False
            self._current_tool_invocation.reset(token)

    def current_tool_invocation(self) -> ToolInvocation | None:
        return self._current_tool_invocation.get()

    def mark_tool_terminal(self, tool_call_id: str, *, visible: bool = False) -> None:
        with self._lock:
            registration = self._tool_calls.get(tool_call_id)
            if registration is None:
                return
            registration.terminal_recorded = True
            if visible:
                registration.visible_recorded = True

    def mark_tool_visible(self, tool_call_id: str) -> None:
        with self._lock:
            registration = self._tool_calls.get(tool_call_id)
            if registration is not None:
                registration.visible_recorded = True

    def open_tool_calls(self) -> tuple[ToolCallRegistration, ...]:
        with self._lock:
            return tuple(registration for registration in sorted(self._tool_calls.values(), key=lambda item: (item.step_seq, item.call_seq)) if not registration.terminal_recorded)

    def tool_schema_block_id(self, tool_name: str) -> str | None:
        with self._lock:
            state = self._latest_context_state
            if state is None:
                return None
            return next(
                (item.block_id for item in state.items if item.channel == "tool_schema" and item.name == tool_name),
                None,
            )

    def next_attempt(self, call: ExecutionCall) -> int:
        with self._lock:
            call.attempt_no += 1
            return call.attempt_no

    def next_producer_seq(self) -> int:
        with self._lock:
            self._producer_seq += 1
            return self._producer_seq

    def resolve_content_occurrence(
        self,
        *,
        source_identity: str,
        content_hash: str,
        kind: str,
    ) -> ContentOccurrenceResolution:
        key = (source_identity, content_hash, kind)
        with self._lock:
            entry = self._content_occurrences.get(key)
            if entry is None:
                seed = "\0".join((self.task_id, source_identity, content_hash, kind))
                entry = _ContentOccurrenceEntry(
                    block_id=_deterministic_uuid4(f"block:{seed}"),
                    producer_obs_id=_deterministic_uuid4(f"observation:{seed}"),
                    source_event_id=_content_occurrence_source_event_id(
                        self.task_id,
                        source_identity,
                        content_hash,
                        kind,
                    ),
                    durable=False,
                )
                self._content_occurrences[key] = entry
                self._content_observation_keys[entry.producer_obs_id] = key
            return ContentOccurrenceResolution(
                source_identity=source_identity,
                content_hash=content_hash,
                kind=kind,
                block_id=entry.block_id,
                producer_obs_id=entry.producer_obs_id,
                source_event_id=entry.source_event_id,
                should_emit=not entry.durable,
            )

    def mark_observations_durable(self, observation_ids: tuple[str, ...]) -> None:
        with self._lock:
            for observation_id in observation_ids:
                key = self._content_observation_keys.get(observation_id)
                if key is not None:
                    self._content_occurrences[key].durable = True
                state_hash = self._context_state_observation_keys.get(observation_id)
                if state_hash is not None:
                    self._context_states_by_hash[state_hash].durable = True

    def resolve_context_state(
        self,
        items: tuple[ContextStateItem, ...],
    ) -> ContextStateResolution:
        state_hash = context_state_hash(items)
        with self._lock:
            existing = self._context_states_by_hash.get(state_hash)
            if existing is not None:
                self._latest_context_state = existing
                return _state_resolution_with_emit(existing)

            parent = self._latest_context_state
            use_parent = parent is not None and parent.durable and parent.resolution.chain_depth < _MAX_CONTEXT_STATE_CHAIN_DEPTH
            parent_state_id = parent.resolution.state_id if use_parent else None
            chain_depth = parent.resolution.chain_depth + 1 if use_parent else 0
            is_checkpoint = not use_parent
            delta = build_context_state_delta(parent.items, items) if use_parent else ()
            state_id = _deterministic_uuid4(f"context-state:{self.task_id}:{state_hash}")
            producer_obs_id = _deterministic_uuid4(f"context-state-observation:{self.task_id}:{state_hash}")
            resolution = ContextStateResolution(
                state_id=state_id,
                state_hash=state_hash,
                parent_state_id=parent_state_id,
                chain_depth=chain_depth,
                is_checkpoint=is_checkpoint,
                item_count=len(items),
                checkpoint_items=items if is_checkpoint else (),
                delta=delta,
                producer_obs_id=producer_obs_id,
                source_event_id=f"context-state:{state_hash}",
                should_emit=True,
            )
            entry = _ContextStateEntry(resolution=resolution, items=items, durable=False)
            self._context_states_by_hash[state_hash] = entry
            self._context_state_observation_keys[producer_obs_id] = state_hash
            self._latest_context_state = entry
            return resolution


def _content_occurrence_source_event_id(
    task_id: str,
    source_identity: str,
    content_hash: str,
    kind: str,
) -> str:
    seed = "\0".join((task_id, source_identity, content_hash, kind))
    return f"content-occurrence:{sha256(seed.encode('utf-8')).hexdigest()}"


def _state_resolution_with_emit(entry: _ContextStateEntry) -> ContextStateResolution:
    return replace(entry.resolution, should_emit=not entry.durable)
