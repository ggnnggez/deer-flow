"""The two model-call probes: a logical decision and the physical calls inside it.

``DecisionProbe`` sits at ``MODEL_LOGICAL`` — outer of the host's retry loop —
so one decision is one step however many times the provider is retried.
``AttemptProbe`` sits at ``MODEL_PHYSICAL`` — inner of every request transform
— so it sees the exact request the provider receives and fires once per call.
Neither changes the request or the result; both call the downstream handler
exactly once. All per-task state lives in the task store the host hands the
runtime; nothing is kept on the middleware instance, which the host shares
across concurrent runs.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Awaitable, Callable, Mapping
from typing import Any
from uuid import uuid4

from deerflow_extension_api import AgentScope, MiddlewarePlacement, Placement, TaskInfo, task_store_from_runtime
from langchain.agents.middleware import AgentMiddleware

from .inventory import ESTIMATOR_NAME, ESTIMATOR_VERSION, inventory
from .options import Options
from .recorder import AttemptFinished, AttemptRequested, RecorderHandle, StepClosed, now_iso

logger = logging.getLogger(__name__)


class ResidencyTaskState:
    """Per-task counters, kept in the task store and discarded with it."""

    __slots__ = ("task_id", "next_step_seq", "step_id", "step_seq", "next_attempt_no", "last_attempt_id", "lock")

    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        self.next_step_seq = 1
        self.step_id: str | None = None
        self.step_seq = 0
        self.next_attempt_no = 1
        self.last_attempt_id: str | None = None
        self.lock = threading.Lock()


def _task_state(runtime: Any) -> ResidencyTaskState | None:
    store = task_store_from_runtime(runtime)
    if store is None:
        return None

    def init() -> ResidencyTaskState:
        info = store.get(TaskInfo)
        return ResidencyTaskState(info.task_id if info is not None else store.scope_id)

    return store.get_or_init(ResidencyTaskState, init)


def _model_name(model: Any) -> str | None:
    for candidate in (model, getattr(model, "bound", None)):
        if candidate is None:
            continue
        for attribute in ("model_name", "model"):
            value = getattr(candidate, attribute, None)
            if isinstance(value, str) and value:
                return value
    return None


def _runtime_context(request: Any) -> Mapping[str, Any]:
    context = getattr(getattr(request, "runtime", None), "context", None)
    return context if isinstance(context, Mapping) else {}


def _configured_model_name(request: Any) -> str | None:
    """The configured model name the run declared, when the host put it on the runtime."""
    value = _runtime_context(request).get("model_name")
    return value if isinstance(value, str) and value else None


def _positive_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _configured_entry(app_config: Any, name: str) -> Any | None:
    """The host's model config entry for a configured name, or None when it has none."""
    lookup = getattr(app_config, "get_model_config", None)
    if callable(lookup):
        try:
            entry = lookup(name)
        except Exception:  # noqa: BLE001 - an unknown name is the same as no entry
            entry = None
        # A lookup that answers with another entry (a default fallback) is no answer.
        if entry is not None and getattr(entry, "name", name) == name:
            return entry
    for entry in getattr(app_config, "models", None) or ():
        if getattr(entry, "name", None) == name:
            return entry
    return None


def _entry_by_provider_id(app_config: Any, provider_id: str) -> Any | None:
    for entry in getattr(app_config, "models", None) or ():
        if getattr(entry, "model", None) == provider_id:
            return entry
    return None


def _resolve_model(request: Any, options: Options) -> tuple[str | None, int | None]:
    """The model name to record and its context window, from what the host already knows.

    The run worker puts the resolved ``AppConfig`` and the run's requested
    ``model_name`` on the runtime. The requested name is trusted only while its
    configured entry names the provider model that actually ran (the host falls
    back to its default model when a request is not on the allowlist); otherwise
    the provider id wins and is matched against the configured models. The
    window comes from that entry's ``context_window``, else the extension's own
    ``context_windows`` map (by configured name, then provider id), else
    ``default_context_window``. Nothing here is inferred from a model's name: an
    unknown window is recorded as absent.
    """
    provider_id = _model_name(getattr(request, "model", None))
    configured = _configured_model_name(request)
    app_config = _runtime_context(request).get("app_config")
    entry = _configured_entry(app_config, configured) if configured and app_config is not None else None
    if configured and provider_id:
        entry_model = getattr(entry, "model", None) if entry is not None else None
        if entry is None or (entry_model is not None and entry_model != provider_id):
            configured, entry = None, None
    if entry is None and provider_id and app_config is not None:
        entry = _entry_by_provider_id(app_config, provider_id)
    window = _positive_int(getattr(entry, "context_window", None)) if entry is not None else None
    if window is None:
        for candidate in (configured, provider_id):
            if candidate:
                window = _positive_int(options.context_windows.get(candidate))
                if window is not None:
                    break
    if window is None:
        window = options.default_context_window
    return configured or provider_id, window


class DecisionProbe(AgentMiddleware):
    """One logical model decision = one step, whatever the host retries underneath."""

    def __init__(self, handle: RecorderHandle) -> None:
        super().__init__()
        self._handle = handle

    def release_policy_parameters(self) -> dict[str, object]:
        return {"probe": "decision", "placement": Placement.MODEL_LOGICAL.value}

    def _open(self, request: Any) -> tuple[ResidencyTaskState, str] | None:
        state = _task_state(getattr(request, "runtime", None))
        if state is None:
            return None
        step_id = uuid4().hex
        with state.lock:
            state.step_seq = state.next_step_seq
            state.next_step_seq += 1
            state.step_id = step_id
            state.next_attempt_no = 1
            state.last_attempt_id = None
        return state, step_id

    def _close(self, opened: tuple[ResidencyTaskState, str]) -> None:
        state, step_id = opened
        with state.lock:
            effective = state.last_attempt_id
            state.step_id = None
        self._handle.put(StepClosed(task_id=state.task_id, step_id=step_id, effective_attempt_id=effective, closed_at=now_iso()))

    def wrap_model_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
        opened = self._open(request)
        try:
            return handler(request)
        finally:
            if opened is not None:
                self._close(opened)

    async def awrap_model_call(self, request: Any, handler: Callable[[Any], Awaitable[Any]]) -> Any:
        opened = self._open(request)
        try:
            return await handler(request)
        finally:
            if opened is not None:
                self._close(opened)


class AttemptProbe(AgentMiddleware):
    """One physical provider call = one attempt, with the request's member inventory."""

    def __init__(self, handle: RecorderHandle, options: Options | None = None) -> None:
        super().__init__()
        self._handle = handle
        self._options = options if options is not None else Options()

    def release_policy_parameters(self) -> dict[str, object]:
        return {"probe": "attempt", "placement": Placement.MODEL_PHYSICAL.value, "estimator": f"{ESTIMATOR_NAME}@{ESTIMATOR_VERSION}"}

    def _request(self, request: Any) -> tuple[ResidencyTaskState, str, str | None] | None:
        state = _task_state(getattr(request, "runtime", None))
        if state is None:
            return None
        synthesized_step: str | None = None
        with state.lock:
            if state.step_id is None:
                # No decision probe wrapped this call (a stack without the
                # logical anchor): the call is its own step, closed after it.
                synthesized_step = uuid4().hex
                state.step_id = synthesized_step
                state.step_seq = state.next_step_seq
                state.next_step_seq += 1
                state.next_attempt_no = 1
            step_id, step_seq = state.step_id, state.step_seq
            attempt_no = state.next_attempt_no
            state.next_attempt_no += 1
        attempt_id = uuid4().hex
        try:
            members = inventory(state.task_id, list(getattr(request, "messages", None) or ()), getattr(request, "system_message", None), list(getattr(request, "tools", None) or ()))
            status = "complete"
        except Exception:  # noqa: BLE001 - an inventory that cannot be built is recorded as incomplete, never as empty-and-complete
            logger.exception("context-residency: could not serialize the request inventory")
            members, status = (), "incomplete"
        model_name, context_window = _resolve_model(request, self._options)
        self._handle.put(
            AttemptRequested(
                attempt_id=attempt_id,
                task_id=state.task_id,
                step_id=step_id,
                step_seq=step_seq,
                attempt_no=attempt_no,
                occurred_at=now_iso(),
                model_name=model_name,
                status=status,
                members=members,
                context_window_tokens=context_window,
            )
        )
        return state, attempt_id, synthesized_step

    def _finish(self, opened: tuple[ResidencyTaskState, str, str | None], *, ok: bool) -> None:
        state, attempt_id, synthesized_step = opened
        self._handle.put(AttemptFinished(attempt_id=attempt_id, outcome="responded" if ok else "failed", finished_at=now_iso()))
        with state.lock:
            if ok:
                state.last_attempt_id = attempt_id
            if synthesized_step is not None:
                state.step_id = None
        if synthesized_step is not None:
            self._handle.put(StepClosed(task_id=state.task_id, step_id=synthesized_step, effective_attempt_id=attempt_id if ok else None, closed_at=now_iso()))

    def wrap_model_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
        opened = self._request(request)
        if opened is None:
            return handler(request)
        try:
            result = handler(request)
        except BaseException:
            self._finish(opened, ok=False)
            raise
        self._finish(opened, ok=True)
        return result

    async def awrap_model_call(self, request: Any, handler: Callable[[Any], Awaitable[Any]]) -> Any:
        opened = self._request(request)
        if opened is None:
            return await handler(request)
        try:
            result = await handler(request)
        except BaseException:
            self._finish(opened, ok=False)
            raise
        self._finish(opened, ok=True)
        return result


class ResidencyContributor:
    def __init__(self, handle: RecorderHandle, options: Options) -> None:
        self._handle = handle
        self._options = options

    def contribute_middlewares(self, app_store: Any, ctx: Any) -> tuple[MiddlewarePlacement, ...]:
        if not self._options.enabled:
            return ()
        return (
            MiddlewarePlacement(DecisionProbe(self._handle), Placement.MODEL_LOGICAL, AgentScope.BOTH),
            MiddlewarePlacement(AttemptProbe(self._handle, self._options), Placement.MODEL_PHYSICAL, AgentScope.BOTH),
        )
