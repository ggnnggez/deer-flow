from __future__ import annotations

import hashlib
import json
from collections import defaultdict, deque
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator


class ContextStateItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ordinal: int
    channel: Literal["message", "tool_schema"]
    role: Literal["system", "user", "assistant", "tool"] | None = None
    message_id: str | None = None
    source_identity: str | None = None
    name: str | None = None
    block_id: str
    visible_bytes: int
    estimated_tokens: int
    metadata: dict[str, object]


class ContextStateDelta(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    op: Literal["append", "remove", "replace", "reorder"]
    source_ordinal: int | None = None
    target_ordinal: int | None = None
    item: ContextStateItem | None = None

    @model_validator(mode="after")
    def _validate_shape(self) -> ContextStateDelta:
        if self.op == "remove":
            if self.source_ordinal is None or self.target_ordinal is not None or self.item is not None:
                raise ValueError("remove requires only source_ordinal")
        elif self.op == "reorder":
            if self.source_ordinal is None or self.target_ordinal is None or self.item is not None:
                raise ValueError("reorder requires source_ordinal and target_ordinal")
        elif self.op == "replace":
            if self.source_ordinal is None or self.target_ordinal is None or self.item is None:
                raise ValueError("replace requires source, target, and item")
        elif self.target_ordinal is None or self.source_ordinal is not None or self.item is None:
            raise ValueError("append requires target_ordinal and item")
        return self


class ContextStateView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    state_id: str
    task_id: str
    state_hash: str
    parent_state_id: str | None = None
    chain_depth: int
    is_checkpoint: bool
    status: Literal["complete", "incomplete", "missing"]
    items: tuple[ContextStateItem, ...]


def _validate_inventory(items: tuple[ContextStateItem, ...]) -> None:
    if any(item.ordinal != ordinal for ordinal, item in enumerate(items)):
        raise ValueError("ContextState inventory ordinals must be contiguous from zero")


def _item_fingerprint(item: ContextStateItem) -> str:
    payload = item.model_dump(mode="json", exclude={"ordinal"})
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def context_state_hash(items: tuple[ContextStateItem, ...]) -> str:
    _validate_inventory(items)
    encoded = json.dumps(
        [item.model_dump(mode="json") for item in items],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_context_state_delta(
    parent: tuple[ContextStateItem, ...],
    current: tuple[ContextStateItem, ...],
) -> tuple[ContextStateDelta, ...]:
    _validate_inventory(parent)
    _validate_inventory(current)
    parent_by_fingerprint: dict[str, deque[int]] = defaultdict(deque)
    for source_ordinal, item in enumerate(parent):
        parent_by_fingerprint[_item_fingerprint(item)].append(source_ordinal)

    used_sources: set[int] = set()
    operations: list[ContextStateDelta] = []
    for target_ordinal, target_item in enumerate(current):
        target_fingerprint = _item_fingerprint(target_item)
        if target_ordinal < len(parent) and target_ordinal not in used_sources and _item_fingerprint(parent[target_ordinal]) == target_fingerprint:
            used_sources.add(target_ordinal)
            continue
        candidates = parent_by_fingerprint[target_fingerprint]
        while candidates and candidates[0] in used_sources:
            candidates.popleft()
        if candidates:
            source_ordinal = candidates.popleft()
            used_sources.add(source_ordinal)
            operations.append(
                ContextStateDelta(
                    op="reorder",
                    source_ordinal=source_ordinal,
                    target_ordinal=target_ordinal,
                )
            )
        elif target_ordinal < len(parent) and target_ordinal not in used_sources:
            used_sources.add(target_ordinal)
            operations.append(
                ContextStateDelta(
                    op="replace",
                    source_ordinal=target_ordinal,
                    target_ordinal=target_ordinal,
                    item=target_item,
                )
            )
        else:
            operations.append(
                ContextStateDelta(
                    op="append",
                    target_ordinal=target_ordinal,
                    item=target_item,
                )
            )
    operations.extend(ContextStateDelta(op="remove", source_ordinal=source_ordinal) for source_ordinal in range(len(parent)) if source_ordinal not in used_sources)
    return tuple(operations)


def materialize_context_state(
    parent: tuple[ContextStateItem, ...],
    delta: tuple[ContextStateDelta, ...],
    *,
    item_count: int,
) -> tuple[ContextStateItem, ...]:
    _validate_inventory(parent)
    if item_count < 0:
        raise ValueError("ContextState item_count cannot be negative")
    removed_sources: set[int] = set()
    moved_sources: set[int] = set()
    result: dict[int, ContextStateItem] = {}
    for operation in delta:
        if operation.op == "remove":
            if operation.source_ordinal is None or operation.source_ordinal >= len(parent):
                raise ValueError("ContextState remove references a missing parent item")
            removed_sources.add(operation.source_ordinal)
            continue
        if operation.target_ordinal is None or operation.target_ordinal >= item_count:
            raise ValueError("ContextState delta target is outside the resulting inventory")
        if operation.op == "reorder":
            if operation.source_ordinal is None or operation.source_ordinal >= len(parent):
                raise ValueError("ContextState reorder references a missing parent item")
            moved_sources.add(operation.source_ordinal)
            item = parent[operation.source_ordinal].model_copy(update={"ordinal": operation.target_ordinal})
        else:
            if operation.item is None:
                raise ValueError("ContextState item-producing delta is missing its item")
            item = operation.item.model_copy(update={"ordinal": operation.target_ordinal})
            if operation.op == "replace" and operation.source_ordinal is not None:
                removed_sources.add(operation.source_ordinal)
        if operation.target_ordinal in result:
            raise ValueError("ContextState delta writes one target ordinal more than once")
        result[operation.target_ordinal] = item

    for source_ordinal, item in enumerate(parent):
        if source_ordinal in removed_sources or source_ordinal in moved_sources or source_ordinal >= item_count:
            continue
        result.setdefault(source_ordinal, item)
    if set(result) != set(range(item_count)):
        raise ValueError("ContextState delta does not materialize a complete inventory")
    materialized = tuple(result[ordinal].model_copy(update={"ordinal": ordinal}) for ordinal in range(item_count))
    _validate_inventory(materialized)
    return materialized
