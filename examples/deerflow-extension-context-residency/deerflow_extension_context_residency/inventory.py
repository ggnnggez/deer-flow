"""Serialize the final model request into an ordered member inventory.

Pure: never mutates the request, never calls a provider, never reads the
environment. Sizes are what the estimator recorded for *this* occurrence — the
same block may measure differently in another request once the estimator
changes — which is why sizes travel with members rather than with blocks.

Identity is a hash of what the request actually carried: the task, the block's
kind and role, the canonical hash of its content, and a tie-breaker. Messages
that reached the request from state carry a stable LangGraph id and use it;
messages a middleware injected on the way to the provider usually have none,
and those are told apart by their occurrence index among identical injections
in the same request. So a reminder re-injected with the same text every turn
reads as one block present across turns — which is what it is in the request —
rather than a fresh block each time.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from deerflow_extension_api import canonical_hash, canonical_json, read_provenance

ESTIMATOR_NAME = "utf8-bytes-div4"
ESTIMATOR_VERSION = "1"

#: Stamped content kinds, projected onto this extension's closed kind set. A
#: kind this build does not know passes through verbatim: the reader owns the
#: neutral degrade, and history is never corrected into the nearest lane.
_STAMP_KINDS = {
    "memory": "memory",
    "skill_body": "skill_instruction",
    "durable_context": "durable_context",
    "image_payload": "image_or_attachment",
    "middleware_injection": "middleware_injection",
}
_ROLE_KINDS = {
    "system": "system_prompt",
    "human": "user_input",
    "ai": "assistant_output",
    "tool": "tool_result_visible",
}


@dataclass(frozen=True)
class Member:
    ordinal: int
    channel: str
    role: str
    kind: str
    block_id: str
    content_hash: str
    visible_bytes: int
    estimated_tokens: int
    name: str | None = None
    source_identity: str | None = None
    #: Set when the member is the message that carries a compaction summary:
    #: the hash the compaction recorded, joining this member to its event.
    summary_content_hash: str | None = None


def _role(message: Any) -> str:
    role = getattr(message, "type", None)
    return role if isinstance(role, str) and role else "unknown"


def _visible_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    try:
        return canonical_json(content)
    except TypeError:
        return str(content)


def _visible_payload(message: Any) -> Any:
    """What the provider sees of a message: its content, plus an assistant turn's tool calls.

    Identity still hashes ``content`` alone so members join the compaction
    event's ``source_content_hashes`` (the same recipe); size measures the whole
    visible payload, because a tool request with empty content is not empty.
    """
    content = getattr(message, "content", "")
    tool_calls = getattr(message, "tool_calls", None)
    if _role(message) == "ai" and tool_calls:
        return {"content": content, "tool_calls": tool_calls}
    return content


def _content_hash(content: Any) -> str:
    try:
        return canonical_hash(content)
    except TypeError:
        return canonical_hash(str(content))


def _tokens(visible_bytes: int) -> int:
    return math.ceil(visible_bytes / 4) if visible_bytes else 0


def block_identity(task_id: str, kind: str, role: str, content_hash: str, dedupe: str) -> str:
    return hashlib.sha256(f"block:{task_id}\0{kind}\0{role}\0{content_hash}\0{dedupe}".encode()).hexdigest()


def message_kind(message: Any) -> tuple[str, str | None]:
    """``(kind, summary_content_hash)`` for one message: its stamp first, then its role.

    A coalesced system message keeps the system lane — the merge stamp says who
    folded it, not what it is. A message that declares the summary it carries is
    filed as the summary's continuation, whatever else the block renders.
    """
    provenance = read_provenance(message)
    if provenance is not None:
        if provenance.producer_kind == "system_coalescing":
            return "system_prompt", None
        if provenance.summary_content_hash:
            return "summary", provenance.summary_content_hash
        return _STAMP_KINDS.get(provenance.content_kind, provenance.content_kind), None
    role = _role(message)
    if role == "ai" and not _visible_text(getattr(message, "content", "")) and getattr(message, "tool_calls", None):
        return "tool_request", None
    return _ROLE_KINDS.get(role, "unknown"), None


def _tool_name(tool: Any) -> str:
    if isinstance(tool, dict):
        function = tool.get("function")
        name = tool.get("name") or (function.get("name") if isinstance(function, dict) else None)
        return str(name or "tool")
    return str(getattr(tool, "name", type(tool).__name__))


def _tool_description(tool: Any) -> str:
    if isinstance(tool, dict):
        function = tool.get("function")
        description = tool.get("description") or (function.get("description") if isinstance(function, dict) else None)
        return str(description or "")
    return str(getattr(tool, "description", "") or "")


def _tool_schema(tool: Any) -> Any:
    """The tool's argument schema, the way the host's assembly descriptor reads it."""
    if isinstance(tool, dict):
        function = tool.get("function")
        return tool.get("parameters") or (function.get("parameters") if isinstance(function, dict) else None) or tool
    get_input_schema = getattr(tool, "get_input_schema", None)
    if callable(get_input_schema):
        try:
            schema = get_input_schema().model_json_schema()
            if isinstance(schema, dict):
                return schema
        except Exception:  # noqa: BLE001 - a schema that cannot be projected is recorded as empty
            pass
    args_schema = getattr(tool, "args_schema", None)
    model_json_schema = getattr(args_schema, "model_json_schema", None)
    if callable(model_json_schema):
        try:
            schema = model_json_schema()
            if isinstance(schema, dict):
                return schema
        except Exception:  # noqa: BLE001
            pass
    return {}


def inventory(task_id: str, messages: Iterable[Any], system_message: Any | None, tools: Iterable[Any]) -> tuple[Member, ...]:
    """Every member of one model request, in the order the provider receives them."""
    members: list[Member] = []
    occurrences: dict[tuple[str, str, str], int] = {}
    ordered: list[Any] = ([system_message] if system_message is not None else []) + list(messages)
    for ordinal, message in enumerate(ordered):
        kind, summary_hash = message_kind(message)
        role = _role(message)
        content = getattr(message, "content", "")
        content_hash = _content_hash(content)
        message_id = getattr(message, "id", None)
        if isinstance(message_id, str) and message_id:
            dedupe = f"message:{message_id}"
            source: str | None = f"message:{message_id}"
        else:
            key = (kind, role, content_hash)
            index = occurrences.get(key, 0)
            occurrences[key] = index + 1
            dedupe = f"occurrence:{index}"
            source = None
        visible_bytes = len(_visible_text(_visible_payload(message)).encode("utf-8"))
        name = getattr(message, "name", None)
        members.append(
            Member(
                ordinal=ordinal,
                channel="message",
                role=role,
                kind=kind,
                block_id=block_identity(task_id, kind, role, content_hash, dedupe),
                content_hash=content_hash,
                visible_bytes=visible_bytes,
                estimated_tokens=_tokens(visible_bytes),
                name=name if isinstance(name, str) and name else None,
                source_identity=source,
                summary_content_hash=summary_hash,
            )
        )
    ordinal = len(members)
    for tool in tools:
        name = _tool_name(tool)
        payload = {"name": name, "description": _tool_description(tool), "schema": _tool_schema(tool)}
        content_hash = _content_hash(payload)
        visible_bytes = len(_visible_text(payload).encode("utf-8"))
        members.append(
            Member(
                ordinal=ordinal,
                channel="tool_schema",
                role="tool",
                kind="tool_schema",
                block_id=block_identity(task_id, "tool_schema", "tool", content_hash, f"tool:{name}"),
                content_hash=content_hash,
                visible_bytes=visible_bytes,
                estimated_tokens=_tokens(visible_bytes),
                name=name,
                source_identity=f"tool-schema:{name}",
            )
        )
        ordinal += 1
    return tuple(members)
