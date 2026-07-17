"""Middleware to coalesce multiple SystemMessages into a single leading one.

Strict OpenAI-compatible backends (vLLM, SGLang, Qwen) and Anthropic reject
non-leading SystemMessages with errors like "System message must be at the
beginning" or "Received multiple non-consecutive system messages". The
official OpenAI API tolerates mid-conversation system messages, so the issue
only surfaces on strict backends.

DeerFlow's lead agent accumulates multiple SystemMessages because
DynamicContextMiddleware uses the ID-swap technique to replace the first or
last HumanMessage with a triplet whose first element is a SystemMessage
reminder (framework-owned date/metadata must not masquerade as user input,
per OWASP LLM01). On midnight crossings a second SystemMessage (date update)
is injected. create_agent holds the static system_prompt in the separate
``request.system_message`` field and only flattens it into the message list
inside the model-call handler (``[request.system_message, *messages]``).

This middleware runs in wrap_model_call — before the handler flattens the two
— and merges ``request.system_message`` plus every SystemMessage found in
``request.messages`` into a single leading SystemMessage emitted via the
``system_message`` field. It only touches the request payload; the persistent
conversation state (checkpoint) is unchanged, so middleware that scans history
by marker (e.g. is_dynamic_context_reminder) keeps working.

Note: Mirrors the per-request coalescing already done for Claude in
claude_provider._coalesce_system_messages but at a provider-agnostic layer so
every backend benefits from a single fix instead of per-provider patches.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from hashlib import sha256
from typing import override
from uuid import UUID, uuid4

from ansich import ObservationEnvelope, Producer
from ansich.serialization import (
    ANSICH_BLOCK_REF_KEY,
    ANSICH_CONTENT_KIND_KEY,
    ANSICH_PRODUCER_KIND_KEY,
    serialize_observed_content,
)
from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import SystemMessage

from deerflow.agents.middlewares.dynamic_context_middleware import is_dynamic_context_reminder
from deerflow.ansich.execution import PendingContentDerivation
from deerflow.ansich.middleware import execution_context_from_runtime
from deerflow.runtime.secret_context import extract_request_secrets, read_active_secrets

_PRODUCER_INSTANCE_ID = str(uuid4())


def _flatten_content(content) -> str:
    """Convert message content to a plain string, handling both str and list types.

    langchain messages support list-type content for multimodal (e.g.
    ``[{"type": "text", "text": "..."}]``). SystemMessages in DeerFlow are always
    plain strings, but this helper ensures robustness for any content shape.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and "text" in item:
                parts.append(item["text"])
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(content)


def _coalesce_request(request: ModelRequest) -> ModelRequest | None:
    """Merge ``request.system_message`` and in-``messages`` SystemMessages into one.

    On langchain >= 1.2.15 the static system prompt lives in the separate
    ``request.system_message`` field, not in ``request.messages``. The model-call
    handler flattens them at the very last moment (``[system_message, *messages]``),
    so a middleware that only scans ``messages`` cannot see the prompt and ends up
    a no-op. This helper inspects both sources, merges every SystemMessage into a
    single entry, and emits the result via ``system_message`` so the handler still
    prepends it correctly.

    Returns None when no SystemMessages live inside ``messages`` — in that case
    ``system_message`` (if set) is already the sole leading system block and the
    request can pass through with zero mutation, preserving prefix-cache hits.
    """
    in_msg_systems = [m for m in request.messages if isinstance(m, SystemMessage)]
    if not in_msg_systems:
        return None

    # Merge system_message (if any) + all in-messages SystemMessages.
    parts = _coalescing_parts(request.system_message, in_msg_systems)

    first = parts[0]
    merged_kwargs: dict = {}
    for part in parts:
        merged_kwargs.update(part.additional_kwargs or {})
    merged_kwargs[ANSICH_CONTENT_KIND_KEY] = "system_prompt"
    merged_kwargs[ANSICH_PRODUCER_KIND_KEY] = "system_message_coalescing"
    merged = SystemMessage(
        content="\n\n".join(_flatten_content(part.content) for part in parts),
        id=first.id,
        additional_kwargs=merged_kwargs,
    )

    non_system = [message for message in request.messages if not isinstance(message, SystemMessage)]
    return request.override(system_message=merged, messages=non_system)


def _coalescing_parts(
    system_message: SystemMessage | None,
    in_message_systems: list[SystemMessage],
) -> list[SystemMessage]:
    parts = ([] if system_message is None else [system_message]) + in_message_systems

    # Deduplicate dynamic_context_reminder SystemMessages: only keep the last
    # one (most recent date), drop earlier reminders. On midnight crossings
    # the merged content would otherwise contain two adjacent contradictory
    # <current_date> blocks with no temporal anchor — the intervening turns
    # that originally separated them are gone after coalescing. The model
    # should see only the latest date, not a stale one it must guess to
    # ignore.
    reminder_indices = [i for i, p in enumerate(parts) if is_dynamic_context_reminder(p)]
    if len(reminder_indices) > 1:
        keep_last = reminder_indices[-1]
        parts = [p for i, p in enumerate(parts) if i not in reminder_indices[:-1] or i == keep_last]

    return parts


def _observe_coalescing(
    original: ModelRequest,
    coalesced: ModelRequest,
) -> ModelRequest:
    execution = execution_context_from_runtime(getattr(original, "runtime", None))
    merged = coalesced.system_message
    if execution is None or execution.service is None or merged is None:
        return coalesced
    in_message_systems = [message for message in original.messages if isinstance(message, SystemMessage)]
    parts = _coalescing_parts(original.system_message, in_message_systems)
    runtime_context = getattr(getattr(original, "runtime", None), "context", None)
    known_secrets = tuple(
        {
            *extract_request_secrets(runtime_context).values(),
            *read_active_secrets(runtime_context).values(),
        }
    )
    observations: list[ObservationEnvelope] = []
    sources: list[PendingContentDerivation] = []
    occurrence_counts: dict[str, int] = {}
    for ordinal, part in enumerate(parts):
        part_id = str(part.id) if part.id else None
        occurrence_seq = 1
        if part_id is not None:
            occurrence_seq = occurrence_counts.get(part_id, 0) + 1
            occurrence_counts[part_id] = occurrence_seq
        capture = serialize_observed_content(
            kind="system_prompt",
            body=_flatten_content(part.content),
            path=f"system-coalescing:source:{ordinal}",
            known_secrets=known_secrets,
        )
        source_identity = f"message:{part_id}:occurrence:{occurrence_seq}:content:0" if part_id is not None else (f"system-coalescing:source:{ordinal}:{capture.block.content_hash}")
        resolution = execution.resolve_content_occurrence(
            source_identity=source_identity,
            content_hash=capture.block.content_hash,
            kind=capture.block.kind,
        )
        sources.append(
            PendingContentDerivation(
                source_block_id=resolution.block_id,
                transform_kind="coalesced",
                transform_version="1",
                ordinal=ordinal,
            )
        )
        if not resolution.should_emit:
            continue
        producer_kind = part.additional_kwargs.get(ANSICH_PRODUCER_KIND_KEY)
        observations.append(
            ObservationEnvelope(
                obs_id=resolution.producer_obs_id,
                kind="content.produced",
                occurred_at=datetime.now(UTC),
                task_id=execution.task_id,
                subject_type="content_block",
                subject_id=resolution.block_id,
                producer=Producer(
                    name="deerflow.system-message-coalescing",
                    version="1",
                    instance_id=_PRODUCER_INSTANCE_ID,
                ),
                producer_seq=execution.next_producer_seq(),
                source_event_id=resolution.source_event_id,
                correlation_id=execution.task_id,
                payload={
                    "source_identity": source_identity,
                    "producer_kind": (producer_kind if isinstance(producer_kind, str) else "system_prompt"),
                    **capture.block.model_copy(update={"block_id": resolution.block_id}).model_dump(mode="json"),
                },
            )
        )
    receipts = execution.service.record_batch(
        observations,
        batch_kind="content_coalescing_sources",
    )
    if observations and not all(receipt.accepted for receipt in receipts):
        return coalesced
    merged_capture = serialize_observed_content(
        kind="system_prompt",
        body=_flatten_content(merged.content),
        path="system-coalescing:derived",
        known_secrets=known_secrets,
    )
    identity = "\0".join(
        (
            execution.task_id,
            "system-message-coalescing@1",
            merged_capture.block.content_hash,
            *(source.source_block_id for source in sources),
        )
    )
    derived_block_id = str(UUID(bytes=sha256(identity.encode("utf-8")).digest()[:16], version=4))
    execution.register_content_derivations(
        derived_block_id=derived_block_id,
        sources=tuple(sources),
    )
    merged_kwargs = dict(merged.additional_kwargs)
    merged_kwargs[ANSICH_BLOCK_REF_KEY] = derived_block_id
    return coalesced.override(system_message=merged.model_copy(update={"additional_kwargs": merged_kwargs}))


class SystemMessageCoalescingMiddleware(AgentMiddleware[AgentState]):
    """Merge all SystemMessages into a single leading SystemMessage.

    Uses wrap_model_call (not before_agent) so the merge runs on the final
    request payload — where ``system_message`` and ``messages`` are still
    separate fields — and never touches the persisted state["messages"]. This
    keeps the checkpoint structure intact for every consumer that scans history
    (memory builder, journal, summarization, dynamic-context detection).
    """

    @staticmethod
    def _maybe_coalesce(request: ModelRequest) -> ModelRequest:
        coalesced = _coalesce_request(request)
        if coalesced is None:
            return request
        try:
            return _observe_coalescing(request, coalesced)
        except Exception:
            return coalesced

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        return handler(self._maybe_coalesce(request))

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        return await handler(self._maybe_coalesce(request))
