from __future__ import annotations

from ansich.context_state import (
    ContextStateItem,
    build_context_state_delta,
    context_state_hash,
    materialize_context_state,
)


def _item(block_id: str, ordinal: int) -> ContextStateItem:
    return ContextStateItem(
        ordinal=ordinal,
        channel="message",
        role="user",
        message_id=f"message-{block_id}",
        source_identity=f"message:message-{block_id}:occurrence:1:content:0",
        name=None,
        block_id=block_id,
        visible_bytes=1,
        estimated_tokens=1,
        metadata={},
    )


def test_append_only_state_uses_one_append_delta_and_materializes_exact_inventory() -> None:
    parent = (_item("a", 0), _item("b", 1))
    current = (*parent, _item("c", 2))

    delta = build_context_state_delta(parent, current)

    assert [(operation.op, operation.source_ordinal, operation.target_ordinal) for operation in delta] == [("append", None, 2)]
    assert materialize_context_state(parent, delta, item_count=3) == current


def test_delta_materialization_supports_remove_replace_and_reorder() -> None:
    parent = (_item("a", 0), _item("b", 1), _item("c", 2))
    reordered = (_item("b", 0), _item("d", 1), _item("a", 2))

    delta = build_context_state_delta(parent, reordered)
    materialized = materialize_context_state(parent, delta, item_count=3)

    assert materialized == reordered
    assert {operation.op for operation in delta} >= {"remove", "reorder"}

    replacement = (_item("z", 0),)
    replacement_delta = build_context_state_delta((_item("a", 0),), replacement)
    assert [operation.op for operation in replacement_delta] == ["replace"]
    assert materialize_context_state((_item("a", 0),), replacement_delta, item_count=1) == replacement


def test_context_state_hash_is_order_sensitive_but_not_object_identity_sensitive() -> None:
    first = (_item("a", 0), _item("b", 1))
    same = tuple(item.model_copy(deep=True) for item in first)
    reversed_items = (_item("b", 0), _item("a", 1))

    assert context_state_hash(first) == context_state_hash(same)
    assert context_state_hash(first) != context_state_hash(reversed_items)
