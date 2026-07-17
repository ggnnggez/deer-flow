from __future__ import annotations

import base64
import hashlib
import importlib.metadata
import json
import math
from collections.abc import Mapping, Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ansich.ids import new_id

ContentKind = Literal[
    "user_input",
    "assistant_output",
    "tool_request",
    "tool_result_raw",
    "tool_result_visible",
    "system_prompt",
    "tool_schema",
    "image_or_attachment",
    "unknown",
]

_REDACTED = "<redacted>"
_SECRET_FIELDS = frozenset(
    {
        "apikey",
        "authorization",
        "clientsecret",
        "cookie",
        "credential",
        "credentials",
        "dsn",
        "header",
        "headers",
        "idtoken",
        "password",
        "passwd",
        "refreshtoken",
        "setcookie",
        "accesstoken",
    }
)
_GENERATION_SETTING_FIELDS = frozenset(
    {
        "temperature",
        "top_p",
        "max_tokens",
        "max_output_tokens",
        "stop",
        "reasoning",
        "reasoning_effort",
        "thinking",
        "tool_choice",
        "extra_body",
    }
)


def _normalized_field_name(value: object) -> str:
    return "".join(character for character in str(value).lower() if character.isalnum())


class RedactionManifestEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str
    reason: Literal["secret_field", "known_secret_value", "credential_bearing_reference"]
    replacement: str = _REDACTED


class SerializedContentBlock(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    block_id: str = Field(default_factory=new_id)
    kind: ContentKind
    content_hash: str
    body: object
    visible_bytes: int
    estimated_tokens: int
    sensitivity_flags: tuple[str, ...] = ()


class ObservedContentCapture(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    block: SerializedContentBlock
    redactions: tuple[RedactionManifestEntry, ...] = ()
    warnings: tuple[str, ...] = ()


def serialize_observed_content(
    *,
    kind: ContentKind,
    body: object,
    path: str,
    known_secrets: Sequence[str] = (),
) -> ObservedContentCapture:
    """Safely serialize one observed content occurrence without using repr."""

    redactions: list[RedactionManifestEntry] = []
    warnings: list[str] = []
    safe_body = _safe_json(
        body,
        path,
        frozenset(value for value in known_secrets if value),
        redactions,
        warnings,
    )
    return ObservedContentCapture(
        block=_block(kind, safe_body),
        redactions=tuple(redactions),
        warnings=tuple(warnings),
    )


def canonical_content_hash(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


class ContextSnapshotItemCapture(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ordinal: int
    channel: Literal["message", "tool_schema"]
    role: Literal["system", "user", "assistant", "tool"] | None = None
    message_id: str | None = None
    name: str | None = None
    block: SerializedContentBlock
    metadata: dict[str, object] = Field(default_factory=dict)


class ContextSnapshotCapture(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot_id: str = Field(default_factory=new_id)
    items: tuple[ContextSnapshotItemCapture, ...]
    message_count: int
    tool_schema_count: int
    visible_bytes: int
    estimated_tokens: int
    estimator_name: str = "utf8-bytes-div4"
    estimator_version: str = "1"
    adapter_name: str
    adapter_version: str = "unknown"
    configured_model: str | None = None
    response_format: object | None = None
    generation_settings: dict[str, object] = Field(default_factory=dict)
    redactions: tuple[RedactionManifestEntry, ...] = ()
    warnings: tuple[str, ...] = ()


def serialize_model_request(
    *,
    system_message: object | None,
    messages: Sequence[object],
    tools: Sequence[object],
    response_format: object | None,
    model_settings: Mapping[str, object],
    model: object | None,
    known_secrets: Sequence[str] = (),
) -> ContextSnapshotCapture:
    """Capture a deterministic, JSON-safe view of the adapter-bound request.

    The function never falls back to ``repr``. Unsupported values remain visible
    as explicit type/status objects, and secret-bearing mapping fields are
    structurally omitted while exact known secret values are replaced.
    """

    redactions: list[RedactionManifestEntry] = []
    warnings: list[str] = []
    secret_values = frozenset(value for value in known_secrets if value)
    items: list[ContextSnapshotItemCapture] = []
    ordered_messages = ([system_message] if system_message is not None else []) + list(messages)
    message_occurrence_counts: dict[str, int] = {}

    for message_index, message in enumerate(ordered_messages):
        role = _message_role(message)
        message_id = _string_attribute(message, "id")
        message_occurrence_seq = 1
        if message_id is not None:
            message_occurrence_seq = message_occurrence_counts.get(message_id, 0) + 1
            message_occurrence_counts[message_id] = message_occurrence_seq
        name = _string_attribute(message, "name")
        content = getattr(message, "content", None)
        parts = content if isinstance(content, list | tuple) else [content]
        for part_index, part in enumerate(parts):
            path = f"messages[{message_index}].content[{part_index}]"
            body = _content_part_body(part, path, secret_values, redactions, warnings)
            kind = _content_kind(role, part)
            items.append(
                ContextSnapshotItemCapture(
                    ordinal=len(items),
                    channel="message",
                    role=role,
                    message_id=message_id,
                    name=name,
                    block=_block(kind, body),
                    metadata={
                        "message_ordinal": message_index,
                        "message_occurrence_seq": message_occurrence_seq,
                        "part_ordinal": part_index,
                    },
                )
            )
        for tool_index, tool_call in enumerate(_message_tool_calls(message)):
            body = _safe_json(
                tool_call,
                f"messages[{message_index}].tool_calls[{tool_index}]",
                secret_values,
                redactions,
                warnings,
            )
            items.append(
                ContextSnapshotItemCapture(
                    ordinal=len(items),
                    channel="message",
                    role=role,
                    message_id=message_id,
                    name=name,
                    block=_block("tool_request", body),
                    metadata={
                        "message_ordinal": message_index,
                        "message_occurrence_seq": message_occurrence_seq,
                        "tool_call_ordinal": tool_index,
                    },
                )
            )

    for tool_index, tool in enumerate(tools):
        body = _serialize_tool(tool, tool_index, secret_values, redactions, warnings)
        items.append(
            ContextSnapshotItemCapture(
                ordinal=len(items),
                channel="tool_schema",
                name=body.get("name") if isinstance(body.get("name"), str) else None,
                block=_block("tool_schema", body),
                metadata={"tool_ordinal": tool_index},
            )
        )

    safe_response_format = _serialize_schema(response_format, "response_format", secret_values, redactions, warnings)
    generation_settings = {
        key: _safe_json(value, f"model_settings.{key}", secret_values, redactions, warnings) for key, value in model_settings.items() if key in _GENERATION_SETTING_FIELDS and _normalized_field_name(key) not in _SECRET_FIELDS
    }
    if "tool_choice" not in generation_settings:
        tool_choice = getattr(model, "tool_choice", None) if model is not None else None
        if tool_choice is not None:
            generation_settings["tool_choice"] = _safe_json(
                tool_choice,
                "model.tool_choice",
                secret_values,
                redactions,
                warnings,
            )

    adapter_name = "unknown"
    adapter_version = "unknown"
    configured_model = None
    if model is not None:
        model_type = type(model)
        adapter_name = f"{model_type.__module__}.{model_type.__name__}"
        adapter_version = _adapter_package_version(model_type.__module__)
        configured_model = _string_attribute(model, "model_name") or _string_attribute(model, "model")

    return ContextSnapshotCapture(
        items=tuple(items),
        message_count=len(ordered_messages),
        tool_schema_count=len(tools),
        visible_bytes=sum(item.block.visible_bytes for item in items),
        estimated_tokens=sum(item.block.estimated_tokens for item in items),
        adapter_name=adapter_name,
        adapter_version=adapter_version,
        configured_model=configured_model,
        response_format=safe_response_format,
        generation_settings=generation_settings,
        redactions=tuple(redactions),
        warnings=tuple(warnings),
    )


def _message_role(message: object) -> Literal["system", "user", "assistant", "tool"]:
    message_type = getattr(message, "type", None)
    return {
        "system": "system",
        "human": "user",
        "ai": "assistant",
        "tool": "tool",
    }.get(message_type, "user")


def _content_kind(role: str, part: object) -> ContentKind:
    if isinstance(part, Mapping):
        part_type = part.get("type")
        if part_type in {"image", "image_url", "file", "attachment"}:
            return "image_or_attachment"
    return {
        "system": "system_prompt",
        "user": "user_input",
        "assistant": "assistant_output",
        "tool": "tool_result_visible",
    }.get(role, "unknown")


def _content_part_body(
    part: object,
    path: str,
    secret_values: frozenset[str],
    redactions: list[RedactionManifestEntry],
    warnings: list[str],
) -> object:
    if isinstance(part, Mapping) and part.get("type") == "text" and isinstance(part.get("text"), str):
        return _safe_json(part["text"], path, secret_values, redactions, warnings)
    if isinstance(part, Mapping) and part.get("type") in {"image", "image_url", "file", "attachment"}:
        return _safe_attachment(part, path, secret_values, redactions, warnings)
    return _safe_json(part, path, secret_values, redactions, warnings)


def _safe_attachment(
    value: Mapping[object, object],
    path: str,
    secret_values: frozenset[str],
    redactions: list[RedactionManifestEntry],
    warnings: list[str],
) -> dict[str, object]:
    result: dict[str, object] = {"type": str(value.get("type", "attachment"))}
    for key in ("artifact_id", "mime_type", "media_type", "width", "height", "detail", "name"):
        if key in value:
            result[key] = _safe_json(value[key], f"{path}.{key}", secret_values, redactions, warnings)
    omitted_reference = False
    for key in ("url", "image_url", "source", "data"):
        if key in value:
            omitted_reference = True
            redactions.append(
                RedactionManifestEntry(
                    path=f"{path}.{key}",
                    reason="credential_bearing_reference",
                )
            )
    if omitted_reference:
        result["reference_status"] = "omitted_external_or_embedded_reference"
        warnings.append(f"{path}:attachment_reference_omitted")
    elif "artifact_id" not in result:
        result["reference_status"] = "unsupported_reference"
        warnings.append(f"{path}:attachment_reference_unsupported")
    return result


def _message_tool_calls(message: object) -> list[object]:
    tool_calls = getattr(message, "tool_calls", None)
    return list(tool_calls) if isinstance(tool_calls, list | tuple) else []


def _serialize_tool(
    tool: object,
    ordinal: int,
    secret_values: frozenset[str],
    redactions: list[RedactionManifestEntry],
    warnings: list[str],
) -> dict[str, object]:
    path = f"tools[{ordinal}]"
    if isinstance(tool, Mapping):
        safe = _safe_json(tool, path, secret_values, redactions, warnings)
        return safe if isinstance(safe, dict) else {"schema": safe}
    name = _string_attribute(tool, "name")
    description = _string_attribute(tool, "description")
    args_schema = getattr(tool, "args_schema", None)
    schema = _serialize_schema(args_schema, f"{path}.args_schema", secret_values, redactions, warnings)
    metadata = _safe_json(getattr(tool, "metadata", None), f"{path}.metadata", secret_values, redactions, warnings)
    return {
        "name": name or "unknown",
        "description": description or "",
        "argument_schema": schema,
        "metadata": metadata,
    }


def _serialize_schema(
    value: object,
    path: str,
    secret_values: frozenset[str],
    redactions: list[RedactionManifestEntry],
    warnings: list[str],
) -> object | None:
    if value is None:
        return None
    if isinstance(value, Mapping | str | int | float | bool | list | tuple):
        return _safe_json(value, path, secret_values, redactions, warnings)
    schema_method = getattr(value, "model_json_schema", None)
    if callable(schema_method):
        try:
            return _safe_json(schema_method(), path, secret_values, redactions, warnings)
        except Exception:
            warnings.append(f"{path}:schema_serialization_failed")
    return _unsupported(value, path, warnings)


def _safe_json(
    value: object,
    path: str,
    secret_values: frozenset[str],
    redactions: list[RedactionManifestEntry],
    warnings: list[str],
) -> object:
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        safe_value = value
        for secret in sorted(secret_values, key=len, reverse=True):
            safe_value = safe_value.replace(secret, _REDACTED)
        if safe_value != value:
            redactions.append(RedactionManifestEntry(path=path, reason="known_secret_value"))
        return safe_value
    if isinstance(value, bytes | bytearray | memoryview):
        raw = bytes(value)
        if any(secret.encode("utf-8") in raw for secret in secret_values):
            redactions.append(RedactionManifestEntry(path=path, reason="known_secret_value"))
            return {
                "type": "binary",
                "encoding": "redacted",
                "byte_length": len(raw),
                "data": _REDACTED,
            }
        return {
            "type": "binary",
            "encoding": "base64",
            "byte_length": len(raw),
            "data": base64.b64encode(raw).decode("ascii"),
        }
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for raw_key, child in value.items():
            key = raw_key if isinstance(raw_key, str) else str(raw_key)
            child_path = f"{path}.{key}"
            if _normalized_field_name(key) in _SECRET_FIELDS:
                redactions.append(RedactionManifestEntry(path=child_path, reason="secret_field"))
                continue
            result[key] = _safe_json(child, child_path, secret_values, redactions, warnings)
        return result
    if isinstance(value, list | tuple):
        return [_safe_json(child, f"{path}[{index}]", secret_values, redactions, warnings) for index, child in enumerate(value)]
    return _unsupported(value, path, warnings)


def _unsupported(value: object, path: str, warnings: list[str]) -> dict[str, str]:
    type_name = f"{type(value).__module__}.{type(value).__name__}"
    warnings.append(f"{path}:unsupported:{type_name}")
    return {"type": type_name, "status": "unsupported"}


def _string_attribute(value: object, name: str) -> str | None:
    attribute = getattr(value, name, None)
    return attribute if isinstance(attribute, str) and attribute else None


def _adapter_package_version(module_name: str) -> str:
    package_name = module_name.partition(".")[0].replace("_", "-")
    try:
        return importlib.metadata.version(package_name)
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def _block(kind: ContentKind, body: object) -> SerializedContentBlock:
    encoded = _canonical_bytes(body)
    return SerializedContentBlock(
        kind=kind,
        content_hash=hashlib.sha256(encoded).hexdigest(),
        body=body,
        visible_bytes=len(encoded),
        estimated_tokens=0 if not encoded else max(1, math.ceil(len(encoded) / 4)),
    )


def _canonical_bytes(value: object) -> bytes:
    if isinstance(value, str):
        return value.encode("utf-8")
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
