"""Task tool for delegating work to subagents."""

import asyncio
import logging
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from typing import TYPE_CHECKING, Annotated, Any, cast
from uuid import UUID

from ansich import ObservationEnvelope, Producer, ToolEffect, new_id
from ansich.serialization import (
    ANSICH_PRODUCER_ENTITY_ID_KEY,
    ANSICH_PRODUCER_KIND_KEY,
)
from langchain.tools import InjectedToolCallId, tool
from langchain_core.callbacks import BaseCallbackManager
from langchain_core.messages import ToolMessage
from langgraph.config import get_stream_writer
from langgraph.types import Command

from deerflow.authz.principal import normalize_authz_attributes
from deerflow.config import get_app_config
from deerflow.runtime.user_context import resolve_runtime_user_id
from deerflow.sandbox.security import LOCAL_BASH_SUBAGENT_DISABLED_MESSAGE, is_host_bash_allowed
from deerflow.subagents import SubagentExecutor, get_available_subagent_names, get_subagent_config
from deerflow.subagents.config import resolve_subagent_model_name
from deerflow.subagents.executor import (
    SubagentStatus,
    cleanup_background_task,
    get_background_task_result,
    request_cancel_background_task,
)
from deerflow.subagents.status_contract import (
    SubagentStatusValue,
    SubagentStopReasonValue,
    format_subagent_result_message,
    make_subagent_additional_kwargs,
)
from deerflow.tools.types import Runtime
from deerflow.trace_context import DEERFLOW_TRACE_METADATA_KEY, get_current_trace_id, normalize_trace_id

if TYPE_CHECKING:
    from deerflow.config.app_config import AppConfig

logger = logging.getLogger(__name__)

_ANSICH_CHILD_TASK_NAMESPACE = "d676e056-b13f-4f6b-89af-15c13adf6233"

# Cache subagent token usage by tool_call_id so TokenUsageMiddleware can
# write it back to the triggering AIMessage's usage_metadata.
_subagent_usage_cache: dict[str, dict[str, int]] = {}


def _token_usage_cache_enabled(app_config: "AppConfig | None") -> bool:
    if app_config is None:
        try:
            app_config = get_app_config()
        except FileNotFoundError:
            return False
    return bool(getattr(getattr(app_config, "token_usage", None), "enabled", False))


def _cache_subagent_usage(tool_call_id: str, usage: dict | None, *, enabled: bool = True) -> None:
    if enabled and usage:
        _subagent_usage_cache[tool_call_id] = usage


def pop_cached_subagent_usage(tool_call_id: str) -> dict | None:
    return _subagent_usage_cache.pop(tool_call_id, None)


def _is_subagent_terminal(result: Any) -> bool:
    """Return whether a background subagent result is safe to clean up."""
    return result.status in {SubagentStatus.COMPLETED, SubagentStatus.FAILED, SubagentStatus.CANCELLED, SubagentStatus.TIMED_OUT} or getattr(result, "completed_at", None) is not None


async def _await_subagent_terminal(task_id: str, max_polls: int) -> Any | None:
    """Poll until the background subagent reaches a terminal status or we run out of polls."""
    for _ in range(max_polls):
        result = get_background_task_result(task_id)
        if result is None:
            return None
        if _is_subagent_terminal(result):
            return result
        await asyncio.sleep(5)
    return None


async def _deferred_cleanup_subagent_task(task_id: str, trace_id: str, max_polls: int) -> None:
    """Keep polling a cancelled subagent until it can be safely removed."""
    cleanup_poll_count = 0
    while True:
        result = get_background_task_result(task_id)
        if result is None:
            return
        if _is_subagent_terminal(result):
            cleanup_background_task(task_id)
            return
        if cleanup_poll_count >= max_polls:
            logger.warning(f"[trace={trace_id}] Deferred cleanup for task {task_id} timed out after {cleanup_poll_count} polls")
            return
        await asyncio.sleep(5)
        cleanup_poll_count += 1


def _log_cleanup_failure(cleanup_task: asyncio.Task[None], *, trace_id: str, task_id: str) -> None:
    if cleanup_task.cancelled():
        return

    exc = cleanup_task.exception()
    if exc is not None:
        logger.error(f"[trace={trace_id}] Deferred cleanup failed for task {task_id}: {exc}")


def _schedule_deferred_subagent_cleanup(task_id: str, trace_id: str, max_polls: int) -> None:
    logger.debug(f"[trace={trace_id}] Scheduling deferred cleanup for cancelled task {task_id}")
    cleanup_task = asyncio.create_task(_deferred_cleanup_subagent_task(task_id, trace_id, max_polls))
    cleanup_task.add_done_callback(lambda task: _log_cleanup_failure(task, trace_id=trace_id, task_id=task_id))


def _find_usage_recorder(runtime: Any) -> Any | None:
    """Find a callback handler with ``record_external_llm_usage_records`` in the runtime config.

    LangChain may pass ``config["callbacks"]`` in three different shapes:

    - ``None`` (no callbacks registered): no recorder.
    - A plain ``list[BaseCallbackHandler]``: iterate it directly.
    - A ``BaseCallbackManager`` instance (e.g. ``AsyncCallbackManager`` on async
      tool runs): managers are not iterable, so we unwrap ``.handlers`` first.

    Any other shape (e.g. a single handler object accidentally passed without a
    list wrapper) cannot be iterated safely; treat it as "no recorder" rather
    than raise.
    """
    if runtime is None:
        return None
    config = getattr(runtime, "config", None)
    if not isinstance(config, dict):
        return None
    callbacks = config.get("callbacks")
    if isinstance(callbacks, BaseCallbackManager):
        callbacks = callbacks.handlers
    if not callbacks:
        return None
    if not isinstance(callbacks, list):
        return None
    for cb in callbacks:
        if hasattr(cb, "record_external_llm_usage_records"):
            return cb
    return None


def _summarize_usage(records: list[dict] | None) -> dict | None:
    """Summarize token usage records into a compact dict for SSE events."""
    if not records:
        return None
    return {
        "input_tokens": sum(r.get("input_tokens", 0) or 0 for r in records),
        "output_tokens": sum(r.get("output_tokens", 0) or 0 for r in records),
        "total_tokens": sum(r.get("total_tokens", 0) or 0 for r in records),
    }


def _report_subagent_usage(runtime: Any, result: Any) -> None:
    """Report subagent token usage to the parent RunJournal, if available.

    Each subagent task must be reported only once (guarded by usage_reported).
    """
    if getattr(result, "usage_reported", True):
        return
    records = getattr(result, "token_usage_records", None) or []
    if not records:
        return
    journal = _find_usage_recorder(runtime)
    if journal is None:
        logger.debug("No usage recorder found in runtime callbacks — subagent token usage not recorded")
        return
    try:
        journal.record_external_llm_usage_records(records)
        result.usage_reported = True
    except Exception:
        logger.warning("Failed to report subagent token usage", exc_info=True)


def _get_runtime_app_config(runtime: Any) -> "AppConfig | None":
    context = getattr(runtime, "context", None)
    if isinstance(context, dict):
        app_config = context.get("app_config")
        if app_config is not None:
            return cast("AppConfig", app_config)
    return None


def _merge_skill_allowlists(parent: list[str] | None, child: list[str] | None) -> list[str] | None:
    """Return the effective subagent skill allowlist under the parent policy."""
    if parent is None:
        return child
    if child is None:
        return list(parent)

    parent_set = set(parent)
    return [skill for skill in child if skill in parent_set]


def _ansich_child_task_id(parent_task_id: str, spawning_tool_call_id: str) -> str:
    digest = sha256(f"{_ANSICH_CHILD_TASK_NAMESPACE}:{parent_task_id}:{spawning_tool_call_id}".encode()).digest()
    return str(UUID(bytes=digest[:16], version=4))


def _create_child_ansich_context(
    parent_execution: Any,
    *,
    executor_task_id: str,
    thread_id: str | None,
    owner_id: str | None,
    subagent_name: str,
    workspace_ref: str | None = None,
    sandbox_ref: str | None = None,
) -> tuple[Any | None, Any | None]:
    """Create a child Task/context from the currently executing parent ToolCall.

    This boundary is deliberately fail-open; callers catch every failure and
    continue delegation without Ansich.
    """
    from deerflow.ansich.execution import AnsichExecutionContext
    from deerflow.ansich.probes.task_control import TaskControlProbe

    if not isinstance(parent_execution, AnsichExecutionContext) or parent_execution.service is None:
        return None, None
    invocation = parent_execution.current_tool_invocation()
    if invocation is None:
        raise RuntimeError("spawning Ansich ToolCall is unavailable")
    registration = invocation.registration
    child_task_id = _ansich_child_task_id(
        parent_execution.task_id,
        registration.tool_call_id,
    )
    child_probe = TaskControlProbe(
        parent_execution.service,
        run_id=executor_task_id,
        task_id=child_task_id,
        source_kind="deerflow_subagent",
        source_id=executor_task_id,
        thread_id=thread_id or "unknown",
        owner_id=owner_id,
        trigger_kind="subagent",
        lifecycle_attributes={
            "parent_task_id": parent_execution.task_id,
            "spawning_step_id": registration.step_id,
            "spawning_tool_call_id": registration.tool_call_id,
            "subagent_name": subagent_name,
            "scope_inheritance_source": "parent_task",
            **({"workspace_ref": workspace_ref} if isinstance(workspace_ref, str) and workspace_ref else {}),
            **({"sandbox_ref": sandbox_ref} if isinstance(sandbox_ref, str) and sandbox_ref else {}),
        },
        flush_on_terminal=False,
    )
    child_probe.created()
    _record_child_task_spawn_effect(
        parent_execution,
        child_task_id=child_task_id,
        subagent_name=subagent_name,
    )
    return (
        AnsichExecutionContext(
            task_id=child_task_id,
            service=parent_execution.service,
        ),
        child_probe,
    )


def _record_child_task_spawn_effect(
    parent_execution: Any,
    *,
    child_task_id: str,
    subagent_name: str,
) -> None:
    """Record the hard spawn fact at the child Task creation boundary."""

    service = getattr(parent_execution, "service", None)
    task_id = getattr(parent_execution, "task_id", None)
    invocation = parent_execution.current_tool_invocation()
    if service is None or not isinstance(task_id, str) or invocation is None:
        return
    registration = invocation.registration
    try:
        obs_id = new_id()
        effect = ToolEffect(
            effect_id=new_id(),
            tool_call_id=registration.tool_call_id,
            effect_class="child_task_spawn",
            phase="observed",
            target_hash=sha256(child_task_id.encode()).hexdigest(),
            target_preview=f"subagent:{subagent_name}"[:512],
            fidelity_class="hard",
            source_obs_id=obs_id,
            result_metadata={"child_task_id": child_task_id},
        )
        service.record(
            ObservationEnvelope(
                obs_id=obs_id,
                kind="effect.observed",
                occurred_at=datetime.now(UTC),
                task_id=task_id,
                step_id=registration.step_id,
                subject_type="effect",
                subject_id=effect.effect_id,
                producer=Producer(
                    name="deerflow-subagent-observability",
                    version="1",
                    instance_id=task_id,
                ),
                producer_seq=parent_execution.next_producer_seq(),
                source_event_id=(f"task:{task_id}:tool:{registration.tool_call_id}:child:{child_task_id}:spawned"),
                correlation_id=task_id,
                causation_obs_id=registration.issued_obs_id,
                payload={"effect": effect.model_dump(mode="json")},
            )
        )
    except Exception:
        logger.warning(
            "Could not record child Task spawn effect for tool %s",
            registration.tool_call_id,
            exc_info=True,
        )


def _record_child_ansich_degradation(
    parent_execution: Any,
    *,
    provider_tool_call_id: str,
) -> None:
    """Best-effort parent evidence when child observation setup is unavailable."""
    service = getattr(parent_execution, "service", None)
    task_id = getattr(parent_execution, "task_id", None)
    if service is None or not isinstance(task_id, str):
        return
    try:
        payload: dict[str, object] = {
            "component": "tool_call",
            "reason": "child_context_initialization_failed",
            "provider_tool_call_id": provider_tool_call_id,
        }
        invocation = parent_execution.current_tool_invocation()
        if invocation is not None:
            payload["spawning_tool_call_id"] = invocation.registration.tool_call_id
        service.record(
            ObservationEnvelope(
                kind="observability.degraded",
                occurred_at=datetime.now(UTC),
                task_id=task_id,
                subject_id=task_id,
                producer=Producer(
                    name="deerflow-subagent-observability",
                    version="1",
                    instance_id=task_id,
                ),
                producer_seq=parent_execution.next_producer_seq(),
                source_event_id=(f"task:{task_id}:tool:{provider_tool_call_id}:child-context-failed"),
                correlation_id=provider_tool_call_id,
                payload=payload,
            )
        )
    except Exception:
        logger.warning(
            "Could not record child Ansich context degradation for tool %s",
            provider_tool_call_id,
            exc_info=True,
        )


def _task_result_command(
    *,
    tool_call_id: str,
    status: SubagentStatusValue,
    result: str | None = None,
    error: str | None = None,
    stop_reason: SubagentStopReasonValue | None = None,
    model_name: str | None = None,
    usage: dict[str, int] | None = None,
    producer_task_id: str | None = None,
) -> Command:
    content, metadata_error = format_subagent_result_message(status, result=result, error=error, stop_reason=stop_reason)
    return Command(
        update={
            "messages": [
                ToolMessage(
                    content=content,
                    tool_call_id=tool_call_id,
                    name="task",
                    additional_kwargs={
                        **make_subagent_additional_kwargs(
                            status,
                            result=result,
                            error=metadata_error,
                            stop_reason=stop_reason,
                            model_name=model_name,
                            token_usage=usage,
                        ),
                        **(
                            {
                                ANSICH_PRODUCER_KIND_KEY: "subagent_task",
                                ANSICH_PRODUCER_ENTITY_ID_KEY: producer_task_id,
                            }
                            if producer_task_id is not None
                            else {}
                        ),
                    },
                )
            ]
        }
    )


@tool("task", parse_docstring=True)
async def task_tool(
    runtime: Runtime,
    description: str,
    prompt: str,
    subagent_type: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> str | Command:
    """Delegate a task to a specialized subagent that runs in its own context.

    Subagents help you:
    - Preserve context by keeping exploration and implementation separate
    - Handle complex multi-step tasks autonomously
    - Execute commands or operations in isolated contexts

    Built-in subagent types:
    - **general-purpose**: A capable agent for complex, multi-step tasks that require
      both exploration and action. Use when the task requires complex reasoning,
      multiple dependent steps, or would benefit from isolated context.
    - **bash**: Command execution specialist for running bash commands. This is only
      available when host bash is explicitly allowed or when using an isolated shell
      sandbox such as `AioSandboxProvider`.

    Additional custom subagent types may be defined in config.yaml under
    `subagents.custom_agents`. Each custom type can have its own system prompt,
    tools, skills, model, and timeout configuration. If an unknown subagent_type
    is provided, the error message will list all available types.

    When to use this tool:
    - Complex tasks requiring multiple steps or tools
    - Tasks that produce verbose output
    - When you want to isolate context from the main conversation
    - Parallel research or exploration tasks

    When NOT to use this tool:
    - Simple, single-step operations (use tools directly)
    - Tasks requiring user interaction or clarification

    Args:
        description: A short (3-5 word) description of the task for logging/display. ALWAYS PROVIDE THIS PARAMETER FIRST.
        prompt: The task description for the subagent. Be specific and clear about what needs to be done. ALWAYS PROVIDE THIS PARAMETER SECOND.
        subagent_type: The type of subagent to use. ALWAYS PROVIDE THIS PARAMETER THIRD.
    """
    runtime_app_config = _get_runtime_app_config(runtime)
    cache_token_usage = _token_usage_cache_enabled(runtime_app_config)
    available_subagent_names = get_available_subagent_names(app_config=runtime_app_config) if runtime_app_config is not None else get_available_subagent_names()

    # Get subagent configuration
    config = get_subagent_config(subagent_type, app_config=runtime_app_config) if runtime_app_config is not None else get_subagent_config(subagent_type)
    if config is None:
        available = ", ".join(available_subagent_names)
        error = f"Unknown subagent type '{subagent_type}'. Available: {available}"
        return _task_result_command(
            tool_call_id=tool_call_id,
            status="failed",
            error=error,
        )
    if subagent_type == "bash":
        host_bash_allowed = is_host_bash_allowed(runtime_app_config) if runtime_app_config is not None else is_host_bash_allowed()
        if not host_bash_allowed:
            return _task_result_command(
                tool_call_id=tool_call_id,
                status="failed",
                error=LOCAL_BASH_SUBAGENT_DISABLED_MESSAGE,
            )

    # Build config overrides
    overrides: dict = {}

    # Skills are loaded by SubagentExecutor per-session (aligned with Codex's pattern:
    # each subagent loads its own skills based on config, injected as conversation items).
    # No longer appended to system_prompt here.

    # Extract parent context from runtime
    sandbox_state = None
    thread_data = None
    thread_id = None
    parent_model = None
    trace_id = None
    user_id = None
    deerflow_trace_id = None
    metadata: dict = {}

    if runtime is not None:
        sandbox_state = runtime.state.get("sandbox")
        thread_data = runtime.state.get("thread_data")
        thread_id = runtime.context.get("thread_id") if runtime.context else None
        if thread_id is None:
            thread_id = runtime.config.get("configurable", {}).get("thread_id")

        # Try to get parent model from configurable
        metadata = runtime.config.get("metadata", {})
        parent_model = metadata.get("model_name")

        # Get or generate trace_id for distributed tracing
        trace_id = metadata.get("trace_id") or str(uuid.uuid4())[:8]

    # Get user_id for tracing (uses standard resolution order)
    user_id = resolve_runtime_user_id(runtime)

    # Propagate the authenticated runtime context so delegated tool calls are
    # evaluated by GuardrailMiddleware with the same identity/attribution as
    # the lead agent. Sourced from the server-side context written by
    # inject_authenticated_user_context (and run_id by the run worker); stays
    # None when absent (e.g. internal-auth runs) so guardrail behavior is
    # unchanged. Without this, role-aware policy silently mis-attributes any
    # tool call delegated to a subagent (user_role=None).
    parent_context = runtime.context if runtime is not None else None
    parent_context = parent_context if isinstance(parent_context, dict) else {}
    user_role = parent_context.get("user_role")
    oauth_provider = parent_context.get("oauth_provider")
    oauth_id = parent_context.get("oauth_id")
    run_id = parent_context.get("run_id")
    from deerflow.ansich.execution import ANSICH_EXECUTION_CONTEXT_KEY, AnsichExecutionContext

    parent_ansich_execution_context = parent_context.get(ANSICH_EXECUTION_CONTEXT_KEY)
    if not isinstance(parent_ansich_execution_context, AnsichExecutionContext):
        parent_ansich_execution_context = None
    # IM-channel sender identity: group chats share one thread across senders,
    # so delegated bash commands need the dispatching turn's channel_user_id.
    channel_user_id = parent_context.get("channel_user_id")
    # Propagate authorization identity: is_internal (strict bool) and
    # authz_attributes (validated Mapping, copied). These follow the same
    # server-side provenance as user_role/oauth — see inject_authenticated_user_context.
    is_internal = parent_context.get("is_internal") is True
    authz_attributes = normalize_authz_attributes(parent_context.get("authz_attributes"))
    deerflow_trace_id = normalize_trace_id(parent_context.get(DEERFLOW_TRACE_METADATA_KEY)) or normalize_trace_id(metadata.get(DEERFLOW_TRACE_METADATA_KEY)) or get_current_trace_id()

    parent_available_skills = metadata.get("available_skills")
    if parent_available_skills is not None:
        overrides["skills"] = _merge_skill_allowlists(list(parent_available_skills), config.skills)

    if overrides:
        config = replace(config, **overrides)

    # Get available tools (excluding task tool to prevent nesting)
    # Lazy import to avoid circular dependency
    from deerflow.tools import get_available_tools

    # Inherit parent agent's tool_groups so subagents respect the same restrictions
    parent_tool_groups = metadata.get("tool_groups")
    resolved_app_config = runtime_app_config
    if config.model == "inherit" and parent_model is None and resolved_app_config is None:
        resolved_app_config = get_app_config()
    effective_model = resolve_subagent_model_name(config, parent_model, app_config=resolved_app_config)

    # Subagents should not have subagent tools enabled (prevent recursive nesting)
    available_tools_kwargs = {
        "model_name": effective_model,
        "groups": parent_tool_groups,
        "subagent_enabled": False,
    }
    if resolved_app_config is not None:
        available_tools_kwargs["app_config"] = resolved_app_config
    tools = get_available_tools(**available_tools_kwargs)

    child_ansich_execution_context = None
    child_ansich_task_control = None
    try:
        (
            child_ansich_execution_context,
            child_ansich_task_control,
        ) = _create_child_ansich_context(
            parent_ansich_execution_context,
            executor_task_id=tool_call_id,
            thread_id=thread_id,
            owner_id=user_id,
            subagent_name=subagent_type,
            workspace_ref=(thread_data.get("workspace_path") if isinstance(thread_data, dict) else None),
            sandbox_ref=(sandbox_state.get("sandbox_id") if isinstance(sandbox_state, dict) else None),
        )
    except Exception:
        logger.warning(
            "[trace=%s] Could not initialize child Ansich context for task tool %s",
            trace_id,
            tool_call_id,
            exc_info=True,
        )
        _record_child_ansich_degradation(
            parent_ansich_execution_context,
            provider_tool_call_id=tool_call_id,
        )

    child_ansich_task_id = getattr(child_ansich_execution_context, "task_id", None)

    def child_result_command(**kwargs: Any) -> Command:
        return _task_result_command(
            **kwargs,
            producer_task_id=(child_ansich_task_id if isinstance(child_ansich_task_id, str) else None),
        )

    # Create executor
    executor_kwargs = {
        "config": config,
        "tools": tools,
        "parent_model": parent_model,
        "sandbox_state": sandbox_state,
        "thread_data": thread_data,
        "thread_id": thread_id,
        "trace_id": trace_id,
        "user_id": user_id,
        "user_role": user_role,
        "oauth_provider": oauth_provider,
        "oauth_id": oauth_id,
        "run_id": run_id,
        "ansich_execution_context": child_ansich_execution_context,
        "ansich_task_control": child_ansich_task_control,
        "channel_user_id": channel_user_id,
        "is_internal": is_internal,
        "authz_attributes": authz_attributes,
        "deerflow_trace_id": deerflow_trace_id,
    }
    if resolved_app_config is not None:
        executor_kwargs["app_config"] = resolved_app_config
    try:
        executor = SubagentExecutor(**executor_kwargs)

        # Start background execution (always async to prevent blocking).
        # Use tool_call_id as task_id for better traceability.
        task_id = executor.execute_async(prompt, task_id=tool_call_id)
    except Exception:
        if child_ansich_task_control is not None:
            try:
                await child_ansich_task_control.terminal(
                    "error",
                    attributes={"failure_reason": "executor_start_failed"},
                )
            except Exception:
                logger.warning(
                    "[trace=%s] Could not close unstarted child Ansich Task for tool %s",
                    trace_id,
                    tool_call_id,
                    exc_info=True,
                )
        raise

    # Poll for task completion in backend (removes need for LLM to poll)
    poll_count = 0
    last_status = None
    last_message_count = 0  # Track how many AI messages we've already sent
    # Polling timeout: execution timeout + 60s buffer, checked every 5s
    max_poll_count = (config.timeout_seconds + 60) // 5

    logger.info(f"[trace={trace_id}] Started background task {task_id} (subagent={subagent_type}, timeout={config.timeout_seconds}s, polling_limit={max_poll_count} polls)")

    writer = get_stream_writer()
    # Send Task Started message'
    writer(
        {
            "type": "task_started",
            "task_id": task_id,
            "description": description,
            "model_name": effective_model,
        }
    )

    try:
        while True:
            result = get_background_task_result(task_id)

            if result is None:
                logger.error(f"[trace={trace_id}] Task {task_id} not found in background tasks")
                writer({"type": "task_failed", "task_id": task_id, "error": "Task disappeared from background tasks"})
                cleanup_background_task(task_id)
                error = f"Task {task_id} disappeared from background tasks"
                return child_result_command(
                    tool_call_id=tool_call_id,
                    status="failed",
                    error=error,
                )

            # Log status changes for debugging
            if result.status != last_status:
                logger.info(f"[trace={trace_id}] Task {task_id} status: {result.status.value}")
                last_status = result.status

            # The collector publishes cumulative records. Reuse one snapshot for
            # both live progress and the terminal event so the frontend can
            # replace, rather than add, its per-task total.
            usage = _summarize_usage(getattr(result, "token_usage_records", None))

            # Check for new AI messages and send task_running events
            ai_messages = result.ai_messages or []
            current_message_count = len(ai_messages)
            if current_message_count > last_message_count:
                # Send task_running event for each new message
                for i in range(last_message_count, current_message_count):
                    message = ai_messages[i]
                    writer(
                        {
                            "type": "task_running",
                            "task_id": task_id,
                            "message": message,
                            "message_index": i + 1,  # 1-based index for display
                            "total_messages": current_message_count,
                            "usage": usage,
                            "model_name": effective_model,
                        }
                    )
                    logger.info(f"[trace={trace_id}] Task {task_id} sent message #{i + 1}/{current_message_count}")
                last_message_count = current_message_count

            # Check if task completed, failed, or timed out
            if result.status == SubagentStatus.COMPLETED:
                _cache_subagent_usage(tool_call_id, usage, enabled=cache_token_usage)
                _report_subagent_usage(runtime, result)
                writer(
                    {
                        "type": "task_completed",
                        "task_id": task_id,
                        "result": result.result,
                        "usage": usage,
                        "model_name": effective_model,
                    }
                )
                logger.info(f"[trace={trace_id}] Task {task_id} completed after {poll_count} polls")
                cleanup_background_task(task_id)
                # stop_reason carries a guardrail cap (token_capped / turn_capped)
                # when the run was ended early but still produced a final answer
                # — the work survives on result_brief like a clean success.
                return child_result_command(
                    tool_call_id=tool_call_id,
                    status="completed",
                    result=result.result,
                    stop_reason=result.stop_reason,
                    model_name=effective_model,
                    usage=usage,
                )
            elif result.status == SubagentStatus.FAILED:
                _cache_subagent_usage(tool_call_id, usage, enabled=cache_token_usage)
                _report_subagent_usage(runtime, result)
                writer(
                    {
                        "type": "task_failed",
                        "task_id": task_id,
                        "error": result.error,
                        "usage": usage,
                        "model_name": effective_model,
                    }
                )
                logger.error(f"[trace={trace_id}] Task {task_id} failed: {result.error}")
                cleanup_background_task(task_id)
                # A turn-capped run with no usable output surfaces as failed +
                # stop_reason=turn_capped; the cap note lets the lead tell "out
                # of budget" from "broken subagent".
                return child_result_command(
                    tool_call_id=tool_call_id,
                    status="failed",
                    error=result.error,
                    stop_reason=result.stop_reason,
                    model_name=effective_model,
                    usage=usage,
                )
            elif result.status == SubagentStatus.CANCELLED:
                _cache_subagent_usage(tool_call_id, usage, enabled=cache_token_usage)
                _report_subagent_usage(runtime, result)
                writer(
                    {
                        "type": "task_cancelled",
                        "task_id": task_id,
                        "error": result.error,
                        "usage": usage,
                        "model_name": effective_model,
                    }
                )
                logger.info(f"[trace={trace_id}] Task {task_id} cancelled: {result.error}")
                cleanup_background_task(task_id)
                return child_result_command(
                    tool_call_id=tool_call_id,
                    status="cancelled",
                    error=result.error,
                    model_name=effective_model,
                    usage=usage,
                )
            elif result.status == SubagentStatus.TIMED_OUT:
                _cache_subagent_usage(tool_call_id, usage, enabled=cache_token_usage)
                _report_subagent_usage(runtime, result)
                writer(
                    {
                        "type": "task_timed_out",
                        "task_id": task_id,
                        "error": result.error,
                        "usage": usage,
                        "model_name": effective_model,
                    }
                )
                logger.warning(f"[trace={trace_id}] Task {task_id} timed out: {result.error}")
                cleanup_background_task(task_id)
                return child_result_command(
                    tool_call_id=tool_call_id,
                    status="timed_out",
                    error=result.error,
                    model_name=effective_model,
                    usage=usage,
                )

            # Still running, wait before next poll
            await asyncio.sleep(5)
            poll_count += 1

            # Polling timeout as a safety net (in case thread pool timeout doesn't work)
            # Set to execution timeout + 60s buffer, in 5s poll intervals
            # This catches edge cases where the background task gets stuck
            if poll_count > max_poll_count:
                timeout_minutes = config.timeout_seconds // 60
                logger.error(f"[trace={trace_id}] Task {task_id} polling timed out after {poll_count} polls (should have been caught by thread pool timeout)")
                _report_subagent_usage(runtime, result)
                usage = _summarize_usage(getattr(result, "token_usage_records", None))
                _cache_subagent_usage(tool_call_id, usage, enabled=cache_token_usage)
                writer(
                    {
                        "type": "task_timed_out",
                        "task_id": task_id,
                        "usage": usage,
                        "model_name": effective_model,
                    }
                )
                # The task may still be running in the background. Signal cooperative
                # cancellation and schedule deferred cleanup to remove the entry from
                # _background_tasks once the background thread reaches a terminal state.
                request_cancel_background_task(task_id)
                _schedule_deferred_subagent_cleanup(task_id, trace_id, max_poll_count)
                message = f"Task polling timed out after {timeout_minutes} minutes. This may indicate the background task is stuck. Status: {result.status.value}"
                return child_result_command(
                    tool_call_id=tool_call_id,
                    status="polling_timed_out",
                    error=message,
                    model_name=effective_model,
                    usage=usage,
                )
    except asyncio.CancelledError:
        # Signal the background subagent thread to stop cooperatively.
        request_cancel_background_task(task_id)

        # Wait (shielded) for the subagent to reach a terminal state so the
        # final token usage snapshot is reported to the parent RunJournal
        # before the parent worker persists get_completion_data().
        terminal_result = None
        try:
            terminal_result = await asyncio.shield(_await_subagent_terminal(task_id, max_poll_count))
        except asyncio.CancelledError:
            pass

        # Report whatever the subagent collected (even if we timed out).
        final_result = terminal_result or get_background_task_result(task_id)
        if final_result is not None:
            _report_subagent_usage(runtime, final_result)
        if final_result is not None and _is_subagent_terminal(final_result):
            cleanup_background_task(task_id)
        else:
            _schedule_deferred_subagent_cleanup(task_id, trace_id, max_poll_count)
        _subagent_usage_cache.pop(tool_call_id, None)
        raise
    except Exception:
        _subagent_usage_cache.pop(tool_call_id, None)
        raise
