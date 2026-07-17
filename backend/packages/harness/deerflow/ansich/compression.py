from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from ansich import ObservationEnvelope, Producer, new_id
from ansich.serialization import (
    ContextSnapshotItemCapture,
    context_snapshot_item_source_identity,
    serialize_model_request,
    serialize_observed_content,
)

from deerflow.ansich.execution import AnsichExecutionContext, ExecutionCall
from deerflow.runtime.secret_context import extract_request_secrets, read_active_secrets

_PRODUCER_INSTANCE_ID = str(uuid4())
_ALGORITHM = "deerflow_summarization_middleware"
_ALGORITHM_VERSION = "1"


@dataclass(frozen=True)
class FrozenContextCompression:
    """Pre-model inventory frozen from exact message occurrences."""

    compression_id: str
    execution: AnsichExecutionContext
    content_observations: tuple[ObservationEnvelope, ...]
    source_block_ids: tuple[str, ...]
    preserved_block_ids: tuple[str, ...]
    removed_block_ids: tuple[str, ...]
    before_tokens: int
    before_visible_bytes: int
    preserved_visible_bytes: int


def freeze_context_compression(
    *,
    execution: AnsichExecutionContext,
    messages: Sequence[object],
    source_messages: Sequence[object],
    preserved_messages: Sequence[object],
    removed_messages: Sequence[object],
    before_tokens: int,
    previous_summary: str | None,
    runtime_context: object | None,
) -> FrozenContextCompression:
    """Resolve exact source/preserved/removed occurrences before the summary call."""

    compression_id = new_id()
    request_secrets = extract_request_secrets(runtime_context)
    active_secrets = read_active_secrets(runtime_context)
    capture = serialize_model_request(
        system_message=None,
        messages=messages,
        tools=(),
        response_format=None,
        model_settings={},
        model=None,
        known_secrets=tuple({*request_secrets.values(), *active_secrets.values()}),
    )
    resolved_items: list[ContextSnapshotItemCapture] = []
    content_observations: list[ObservationEnvelope] = []
    for item in capture.items:
        source_identity = context_snapshot_item_source_identity(item)
        resolution = None
        if source_identity is not None:
            resolution = execution.resolve_content_occurrence(
                source_identity=source_identity,
                content_hash=item.block.content_hash,
                kind=item.block.kind,
            )
            if resolution.block_id != item.block.block_id:
                item = item.model_copy(update={"block": item.block.model_copy(update={"block_id": resolution.block_id})})
        resolved_items.append(item)
        if resolution is not None and not resolution.should_emit:
            continue
        content_observations.append(
            ObservationEnvelope(
                obs_id=resolution.producer_obs_id if resolution is not None else new_id(),
                kind="content.produced",
                occurred_at=datetime.now(UTC),
                task_id=execution.task_id,
                subject_type="content_block",
                subject_id=item.block.block_id,
                producer=_producer(),
                producer_seq=execution.next_producer_seq(),
                source_event_id=(resolution.source_event_id if resolution is not None else f"context-compression:{compression_id}:content:{item.ordinal}"),
                correlation_id=execution.task_id,
                payload={
                    "compression_id": compression_id,
                    "occurrence_ordinal": item.ordinal,
                    "source_identity": source_identity,
                    "unknown_origin": source_identity is None,
                    "producer_kind": str(item.metadata.get("producer_kind") or "context_compression_source"),
                    **item.block.model_dump(mode="json"),
                },
            )
        )

    previous_summary_block_id: str | None = None
    previous_summary_visible_bytes = 0
    if previous_summary:
        previous_capture = serialize_observed_content(
            kind="summary",
            body=previous_summary,
            path=f"context-compression:{compression_id}:previous-summary",
        )
        previous_summary_visible_bytes = previous_capture.block.visible_bytes
        previous_summary_block_id = execution.context_summary_block_id(previous_summary)
        if previous_summary_block_id is None:
            previous_source_identity = f"summary-text:unknown-origin:{previous_capture.block.content_hash}"
            previous_resolution = execution.resolve_content_occurrence(
                source_identity=previous_source_identity,
                content_hash=previous_capture.block.content_hash,
                kind=previous_capture.block.kind,
            )
            previous_summary_block_id = previous_resolution.block_id
            if previous_resolution.should_emit:
                previous_block = previous_capture.block.model_copy(update={"block_id": previous_resolution.block_id})
                content_observations.append(
                    ObservationEnvelope(
                        obs_id=previous_resolution.producer_obs_id,
                        kind="content.produced",
                        occurred_at=datetime.now(UTC),
                        task_id=execution.task_id,
                        subject_type="content_block",
                        subject_id=previous_block.block_id,
                        producer=_producer(),
                        producer_seq=execution.next_producer_seq(),
                        source_event_id=previous_resolution.source_event_id,
                        correlation_id=execution.task_id,
                        payload={
                            "compression_id": compression_id,
                            "source_identity": previous_source_identity,
                            "unknown_origin": True,
                            "producer_kind": "unknown",
                            **previous_block.model_dump(mode="json"),
                        },
                    )
                )

    items_by_message_ordinal: dict[int, list[ContextSnapshotItemCapture]] = defaultdict(list)
    for item in resolved_items:
        message_ordinal = item.metadata.get("message_ordinal")
        if isinstance(message_ordinal, int):
            items_by_message_ordinal[message_ordinal].append(item)

    def selected_items(
        selected_messages: Sequence[object],
    ) -> tuple[ContextSnapshotItemCapture, ...]:
        selected_ordinals = _selected_message_ordinals(messages, selected_messages)
        return tuple(item for message_ordinal in selected_ordinals for item in items_by_message_ordinal.get(message_ordinal, ()))

    source_items = selected_items(source_messages)
    preserved_items = selected_items(preserved_messages)
    removed_items = selected_items(removed_messages)
    previous_source = () if previous_summary_block_id is None else (previous_summary_block_id,)

    return FrozenContextCompression(
        compression_id=compression_id,
        execution=execution,
        content_observations=tuple(content_observations),
        source_block_ids=previous_source + tuple(item.block.block_id for item in source_items),
        preserved_block_ids=tuple(item.block.block_id for item in preserved_items),
        removed_block_ids=previous_source + tuple(item.block.block_id for item in removed_items),
        before_tokens=before_tokens,
        before_visible_bytes=capture.visible_bytes + previous_summary_visible_bytes,
        preserved_visible_bytes=sum(item.block.visible_bytes for item in preserved_items),
    )


def record_context_compression(
    frozen: FrozenContextCompression,
    *,
    summary_text: str,
    summary_call: ExecutionCall | None,
    after_tokens: int,
) -> bool:
    """Record the summary block and its exact typed compression inventory fail-open."""

    execution = frozen.execution
    capture = serialize_observed_content(
        kind="summary",
        body=summary_text,
        path=f"context-compression:{frozen.compression_id}:summary",
    )
    source_identity = f"context-compression:{frozen.compression_id}:summary"
    resolution = execution.resolve_content_occurrence(
        source_identity=source_identity,
        content_hash=capture.block.content_hash,
        kind=capture.block.kind,
    )
    summary_block = capture.block.model_copy(update={"block_id": resolution.block_id})
    observations = list(frozen.content_observations)
    if resolution.should_emit:
        observations.append(
            ObservationEnvelope(
                obs_id=resolution.producer_obs_id,
                kind="content.produced",
                occurred_at=datetime.now(UTC),
                task_id=execution.task_id,
                subject_type="content_block",
                subject_id=summary_block.block_id,
                producer=_producer(),
                producer_seq=execution.next_producer_seq(),
                source_event_id=resolution.source_event_id,
                correlation_id=execution.task_id,
                causation_obs_id=(None if summary_call is None else summary_call.last_response_obs_id),
                payload={
                    "compression_id": frozen.compression_id,
                    "source_identity": source_identity,
                    "producer_kind": "context_compression",
                    "producer_entity_id": frozen.compression_id,
                    **summary_block.model_dump(mode="json"),
                },
            )
        )

    items = [
        {"disposition": disposition, "ordinal": ordinal, "block_id": block_id}
        for disposition, block_ids in (
            ("source", frozen.source_block_ids),
            ("preserved", frozen.preserved_block_ids),
            ("removed", frozen.removed_block_ids),
        )
        for ordinal, block_id in enumerate(block_ids)
    ]
    compression_observation = ObservationEnvelope(
        kind="context.compressed",
        occurred_at=datetime.now(UTC),
        task_id=execution.task_id,
        subject_type="context_compression",
        subject_id=frozen.compression_id,
        producer=_producer(),
        producer_seq=execution.next_producer_seq(),
        source_event_id=f"context-compression:{frozen.compression_id}",
        correlation_id=execution.task_id,
        causation_obs_id=(None if summary_call is None else summary_call.last_response_obs_id),
        payload={
            "summary_operation_id": (None if summary_call is None else summary_call.operation_id),
            "summary_block_id": summary_block.block_id,
            "before_tokens": frozen.before_tokens,
            "after_tokens": after_tokens,
            "before_visible_bytes": frozen.before_visible_bytes,
            "after_visible_bytes": (summary_block.visible_bytes + frozen.preserved_visible_bytes),
            "algorithm": _ALGORITHM,
            "algorithm_version": _ALGORITHM_VERSION,
            "items": items,
        },
    )
    observations.append(compression_observation)
    receipts = (
        execution.service.record_batch(
            observations,
            batch_kind="context_compression",
        )
        if execution.service is not None
        else ()
    )
    accepted = bool(receipts) and all(receipt.accepted for receipt in receipts)
    if accepted:
        execution.register_context_summary(
            summary_text=summary_text,
            block_id=summary_block.block_id,
            producer_obs_id=resolution.producer_obs_id,
            durable=not resolution.should_emit,
        )
    return accepted


def _selected_message_ordinals(
    messages: Sequence[object],
    selected_messages: Sequence[object],
) -> tuple[int, ...]:
    available: dict[int, deque[int]] = defaultdict(deque)
    for ordinal, message in enumerate(messages):
        available[id(message)].append(ordinal)
    selected: list[int] = []
    for message in selected_messages:
        ordinals = available.get(id(message))
        if not ordinals:
            raise ValueError("compaction inventory message is not in the source context")
        selected.append(ordinals.popleft())
    return tuple(selected)


def _producer() -> Producer:
    return Producer(
        name="deerflow-context-compression-observer",
        version="1",
        instance_id=_PRODUCER_INSTANCE_ID,
    )
