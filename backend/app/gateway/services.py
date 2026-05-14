"""Run lifecycle service layer.

Centralizes the business logic for creating runs, formatting SSE
frames, and consuming stream bridge events.  Router modules
(``thread_runs``, ``runs``) are thin HTTP handlers that delegate here.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from fastapi import HTTPException, Request
from langchain_core.messages import HumanMessage

from app.gateway.deps import get_run_context, get_run_manager, get_stream_bridge
from app.gateway.utils import sanitize_log_param
from deerflow.config.app_config import get_app_config
from deerflow.runtime import (
    END_SENTINEL,
    HEARTBEAT_SENTINEL,
    ConflictError,
    DisconnectMode,
    RunManager,
    RunRecord,
    RunStatus,
    StreamBridge,
    UnsupportedStrategyError,
    run_agent,
)

logger = logging.getLogger(__name__)


_SSE_PROFILE_ENV = "DEERFLOW_SSE_PROFILE"
_TRUE_ENV_VALUES = frozenset({"1", "true", "yes", "on"})


# ---------------------------------------------------------------------------
# SSE formatting
# ---------------------------------------------------------------------------


def format_sse(event: str, data: Any, *, event_id: str | None = None) -> str:
    """Format a single SSE frame.

    Field order: ``event:`` -> ``data:`` -> ``id:`` (optional) -> blank line.
    This matches the LangGraph Platform wire format consumed by the
    ``useStream`` React hook and the Python ``langgraph-sdk`` SSE decoder.
    """
    payload = json.dumps(data, default=str, ensure_ascii=False)
    parts = [f"event: {event}", f"data: {payload}"]
    if event_id:
        parts.append(f"id: {event_id}")
    parts.append("")
    parts.append("")
    return "\n".join(parts)


@dataclass(slots=True)
class _SseEventStats:
    count: int = 0
    total_bytes: int = 0
    max_bytes: int = 0
    total_format_ns: int = 0
    max_format_ns: int = 0
    byte_samples: list[int] = field(default_factory=list)

    def record(self, frame_bytes: int, format_ns: int) -> None:
        self.count += 1
        self.total_bytes += frame_bytes
        self.max_bytes = max(self.max_bytes, frame_bytes)
        self.total_format_ns += format_ns
        self.max_format_ns = max(self.max_format_ns, format_ns)
        self.byte_samples.append(frame_bytes)

    def as_dict(self) -> dict[str, int | float]:
        return {
            "count": self.count,
            "total_bytes": self.total_bytes,
            "max_bytes": self.max_bytes,
            "p95_bytes": _percentile(self.byte_samples, 95),
            "total_format_ms": round(self.total_format_ns / 1_000_000, 3),
            "max_format_ms": round(self.max_format_ns / 1_000_000, 3),
        }


@dataclass(slots=True)
class _SseProfile:
    run_id: str
    last_event_id: str | None
    start_ns: int = field(default_factory=time.perf_counter_ns)
    rss_start_bytes: int | None = field(default_factory=lambda: _current_rss_bytes())
    events: dict[str, _SseEventStats] = field(default_factory=dict)

    def record(self, event: str, frame: str, format_ns: int) -> None:
        stats = self.events.setdefault(event, _SseEventStats())
        stats.record(len(frame.encode("utf-8")), format_ns)

    def as_dict(self) -> dict[str, Any]:
        rss_end_bytes = _current_rss_bytes()
        rss_delta_bytes = None
        if self.rss_start_bytes is not None and rss_end_bytes is not None:
            rss_delta_bytes = rss_end_bytes - self.rss_start_bytes

        return {
            "run_id": sanitize_log_param(self.run_id),
            "last_event_id": _sanitize_optional_log_param(self.last_event_id),
            "duration_ms": round((time.perf_counter_ns() - self.start_ns) / 1_000_000, 3),
            "rss_start_bytes": self.rss_start_bytes,
            "rss_end_bytes": rss_end_bytes,
            "rss_delta_bytes": rss_delta_bytes,
            "total_events": sum(stats.count for stats in self.events.values()),
            "total_bytes": sum(stats.total_bytes for stats in self.events.values()),
            "events": {event: stats.as_dict() for event, stats in sorted(self.events.items())},
        }


def _sse_profile_enabled() -> bool:
    return os.getenv(_SSE_PROFILE_ENV, "").strip().lower() in _TRUE_ENV_VALUES


def _format_profiled_sse(
    profile: _SseProfile | None,
    event: str,
    data: Any,
    *,
    event_id: str | None = None,
) -> str:
    if profile is None:
        return format_sse(event, data, event_id=event_id)

    started_ns = time.perf_counter_ns()
    frame = format_sse(event, data, event_id=event_id)
    profile.record(event, frame, time.perf_counter_ns() - started_ns)
    return frame


def _sanitize_optional_log_param(value: str | None) -> str | None:
    return sanitize_log_param(value) if value is not None else None


def _current_rss_bytes() -> int | None:
    try:
        with open("/proc/self/statm", encoding="ascii") as statm:
            fields = statm.readline().split()
        return int(fields[1]) * os.sysconf("SC_PAGE_SIZE")
    except (IndexError, OSError, ValueError):
        return None


def _percentile(values: list[int], percentile: int) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, (percentile * len(ordered) + 99) // 100 - 1))
    return ordered[index]


# ---------------------------------------------------------------------------
# Input / config helpers
# ---------------------------------------------------------------------------


def normalize_stream_modes(raw: list[str] | str | None) -> list[str]:
    """Normalize the stream_mode parameter to a list.

    Default matches what ``useStream`` expects: values + messages-tuple.
    """
    if raw is None:
        return ["values"]
    if isinstance(raw, str):
        return [raw]
    return raw if raw else ["values"]


def normalize_input(raw_input: dict[str, Any] | None) -> dict[str, Any]:
    """Convert LangGraph Platform input format to LangChain state dict."""
    if raw_input is None:
        return {}
    messages = raw_input.get("messages")
    if messages and isinstance(messages, list):
        converted = []
        for msg in messages:
            if isinstance(msg, dict):
                role = msg.get("role", msg.get("type", "user"))
                content = msg.get("content", "")
                if role in ("user", "human"):
                    converted.append(HumanMessage(content=content))
                else:
                    # TODO: handle other message types (system, ai, tool)
                    converted.append(HumanMessage(content=content))
            else:
                converted.append(msg)
        return {**raw_input, "messages": converted}
    return raw_input


_DEFAULT_ASSISTANT_ID = "lead_agent"


# Whitelist of run-context keys that the langgraph-compat layer forwards from
# ``body.context`` into the run config. ``config["context"]`` exists in
# LangGraph >=0.6, but these values must be written to both ``configurable``
# (for legacy ``_get_runtime_config`` consumers) and ``context`` because
# LangGraph >=1.1.9 no longer makes ``ToolRuntime.context`` fall back to
# ``configurable`` for consumers like ``setup_agent``.
_CONTEXT_CONFIGURABLE_KEYS: frozenset[str] = frozenset(
    {
        "model_name",
        "mode",
        "thinking_enabled",
        "reasoning_effort",
        "is_plan_mode",
        "subagent_enabled",
        "max_concurrent_subagents",
        "agent_name",
        "is_bootstrap",
    }
)


def merge_run_context_overrides(config: dict[str, Any], context: Mapping[str, Any] | None) -> None:
    """Merge whitelisted keys from ``body.context`` into both ``config['configurable']``
    and ``config['context']`` so they are visible to legacy configurable readers and
    to LangGraph ``ToolRuntime.context`` consumers (e.g. the ``setup_agent`` tool —
    see issue #2677)."""
    if not context:
        return
    configurable = config.setdefault("configurable", {})
    runtime_context = config.setdefault("context", {})
    for key in _CONTEXT_CONFIGURABLE_KEYS:
        if key in context:
            if isinstance(configurable, dict):
                configurable.setdefault(key, context[key])
            if isinstance(runtime_context, dict):
                runtime_context.setdefault(key, context[key])


def inject_authenticated_user_context(config: dict[str, Any], request: Request) -> None:
    """Stamp the authenticated user into the run context for background tools.

    Tool execution may happen after the request handler has returned, so tools
    that persist user-scoped files should not rely only on ambient ContextVars.
    The value comes from server-side auth state, never from client context.
    """

    user = getattr(request.state, "user", None)
    user_id = getattr(user, "id", None)
    if user_id is None:
        return

    runtime_context = config.setdefault("context", {})
    if isinstance(runtime_context, dict):
        runtime_context["user_id"] = str(user_id)


def resolve_agent_factory(assistant_id: str | None):
    """Resolve the agent factory callable from config.

    Custom agents are implemented as ``lead_agent`` + an ``agent_name``
    injected into ``configurable`` or ``context`` — see
    :func:`build_run_config`.  All ``assistant_id`` values therefore map to the
    same factory; the routing happens inside ``make_lead_agent`` when it reads
    ``cfg["agent_name"]``.
    """
    from deerflow.agents.lead_agent.agent import make_lead_agent

    return make_lead_agent


def build_run_config(
    thread_id: str,
    request_config: dict[str, Any] | None,
    metadata: dict[str, Any] | None,
    *,
    assistant_id: str | None = None,
) -> dict[str, Any]:
    """Build a RunnableConfig dict for the agent.

    When *assistant_id* refers to a custom agent (anything other than
    ``"lead_agent"`` / ``None``), the name is forwarded as ``agent_name`` in
    whichever runtime options container is active: ``context`` for
    LangGraph >= 0.6.0 requests, otherwise ``configurable``.
    ``make_lead_agent`` reads this key to load the matching
    ``agents/<name>/SOUL.md`` and per-agent config — without it the agent
    silently runs as the default lead agent.

    This mirrors the channel manager's ``_resolve_run_params`` logic so that
    the LangGraph Platform-compatible HTTP API and the IM channel path behave
    identically.
    """
    config: dict[str, Any] = {"recursion_limit": 100}
    if request_config:
        # LangGraph >= 0.6.0 introduced ``context`` as the preferred way to
        # pass thread-level data and rejects requests that include both
        # ``configurable`` and ``context``.  If the caller already sends
        # ``context``, honour it and skip our own ``configurable`` dict.
        if "context" in request_config:
            if "configurable" in request_config:
                logger.warning(
                    "build_run_config: client sent both 'context' and 'configurable'; preferring 'context' (LangGraph >= 0.6.0). thread_id=%s, caller_configurable keys=%s",
                    thread_id,
                    list(request_config.get("configurable", {}).keys()),
                )
            context_value = request_config["context"]
            if context_value is None:
                context = {}
            elif isinstance(context_value, Mapping):
                context = dict(context_value)
            else:
                raise ValueError("request config 'context' must be a mapping or null.")
            config["context"] = context
        else:
            configurable = {"thread_id": thread_id}
            configurable.update(request_config.get("configurable", {}))
            config["configurable"] = configurable
        for k, v in request_config.items():
            if k not in ("configurable", "context"):
                config[k] = v
    else:
        config["configurable"] = {"thread_id": thread_id}

    # Inject custom agent name when the caller specified a non-default assistant.
    # Honour an explicit agent_name in the active runtime options container.
    if assistant_id and assistant_id != _DEFAULT_ASSISTANT_ID:
        normalized = assistant_id.strip().lower().replace("_", "-")
        if not normalized or not re.fullmatch(r"[a-z0-9-]+", normalized):
            raise ValueError(f"Invalid assistant_id {assistant_id!r}: must contain only letters, digits, and hyphens after normalization.")
        if "configurable" in config:
            target = config["configurable"]
        elif "context" in config:
            target = config["context"]
        else:
            target = config.setdefault("configurable", {})
        if target is not None and "agent_name" not in target:
            target["agent_name"] = normalized
    if metadata:
        config.setdefault("metadata", {}).update(metadata)
    return config


# ---------------------------------------------------------------------------
# Run lifecycle
# ---------------------------------------------------------------------------


async def start_run(
    body: Any,
    thread_id: str,
    request: Request,
) -> RunRecord:
    """Create a RunRecord and launch the background agent task.

    Parameters
    ----------
    body : RunCreateRequest
        The validated request body (typed as Any to avoid circular import
        with the router module that defines the Pydantic model).
    thread_id : str
        Target thread.
    request : Request
        FastAPI request — used to retrieve singletons from ``app.state``.
    """
    bridge = get_stream_bridge(request)
    run_mgr = get_run_manager(request)
    run_ctx = get_run_context(request)

    disconnect = DisconnectMode.cancel if body.on_disconnect == "cancel" else DisconnectMode.continue_

    body_context = getattr(body, "context", None) or {}
    model_name = body_context.get("model_name")

    # Coerce non-string model_name values to str before truncation.
    if model_name is not None and not isinstance(model_name, str):
        model_name = str(model_name)

    # Validate model against the allowlist when a model_name is provided.
    if model_name:
        app_config = get_app_config()
        resolved = app_config.get_model_config(model_name)
        if resolved is None:
            raise HTTPException(
                status_code=400,
                detail=f"Model {model_name!r} is not in the configured model allowlist",
            )

    try:
        record = await run_mgr.create_or_reject(
            thread_id,
            body.assistant_id,
            on_disconnect=disconnect,
            metadata=body.metadata or {},
            kwargs={"input": body.input, "config": body.config},
            multitask_strategy=body.multitask_strategy,
            model_name=model_name,
        )
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except UnsupportedStrategyError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc

    # Upsert thread metadata so the thread appears in /threads/search,
    # even for threads that were never explicitly created via POST /threads
    # (e.g. stateless runs).
    try:
        existing = await run_ctx.thread_store.get(thread_id)
        if existing is None:
            await run_ctx.thread_store.create(
                thread_id,
                assistant_id=body.assistant_id,
                metadata=body.metadata,
            )
        else:
            await run_ctx.thread_store.update_status(thread_id, "running")
    except Exception:
        logger.warning("Failed to upsert thread_meta for %s (non-fatal)", sanitize_log_param(thread_id))

    agent_factory = resolve_agent_factory(body.assistant_id)
    graph_input = normalize_input(body.input)
    config = build_run_config(thread_id, body.config, body.metadata, assistant_id=body.assistant_id)

    # Merge DeerFlow-specific context overrides into both ``configurable`` and ``context``.
    # The ``context`` field is a custom extension for the langgraph-compat layer
    # that carries agent configuration (model_name, thinking_enabled, etc.).
    # Only agent-relevant keys are forwarded; unknown keys (e.g. thread_id) are ignored.
    merge_run_context_overrides(config, getattr(body, "context", None))
    inject_authenticated_user_context(config, request)

    stream_modes = normalize_stream_modes(body.stream_mode)

    task = asyncio.create_task(
        run_agent(
            bridge,
            run_mgr,
            record,
            ctx=run_ctx,
            agent_factory=agent_factory,
            graph_input=graph_input,
            config=config,
            stream_modes=stream_modes,
            stream_subgraphs=body.stream_subgraphs,
            interrupt_before=body.interrupt_before,
            interrupt_after=body.interrupt_after,
        )
    )
    record.task = task

    # Title sync is handled by worker.py's finally block which reads the
    # title from the checkpoint and calls thread_store.update_display_name
    # after the run completes.

    return record


async def sse_consumer(
    bridge: StreamBridge,
    record: RunRecord,
    request: Request,
    run_mgr: RunManager,
):
    """Async generator that yields SSE frames from the bridge.

    The ``finally`` block implements ``on_disconnect`` semantics:
    - ``cancel``: abort the background task on client disconnect.
    - ``continue``: let the task run; events are discarded.
    """
    last_event_id = request.headers.get("Last-Event-ID")
    profile = _SseProfile(record.run_id, last_event_id) if _sse_profile_enabled() else None
    try:
        async for entry in bridge.subscribe(record.run_id, last_event_id=last_event_id):
            if await request.is_disconnected():
                break

            if entry is HEARTBEAT_SENTINEL:
                frame = ": heartbeat\n\n"
                if profile is not None:
                    profile.record("heartbeat", frame, 0)
                yield frame
                continue

            if entry is END_SENTINEL:
                yield _format_profiled_sse(profile, "end", None, event_id=entry.id or None)
                return

            yield _format_profiled_sse(profile, entry.event, entry.data, event_id=entry.id or None)

    finally:
        if profile is not None:
            logger.info(
                "SSE profile %s",
                json.dumps(profile.as_dict(), ensure_ascii=False, sort_keys=True),
            )

        if record.status in (RunStatus.pending, RunStatus.running):
            if record.on_disconnect == DisconnectMode.cancel:
                await run_mgr.cancel(record.run_id)
