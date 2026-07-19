from __future__ import annotations

import os
from importlib.metadata import PackageNotFoundError, version

from ansich.release import (
    AgentRuntimeDescriptor,
    MiddlewareRuntimeDescriptor,
    RuntimeBuildDescriptor,
    ToolRuntimeDescriptor,
)
from ansich.release.canonical import sha256_canonical

_MODEL_BEHAVIOR_FIELDS = (
    "model",
    "use_responses_api",
    "output_version",
    "supports_thinking",
    "supports_reasoning_effort",
    "supports_vision",
    "stream_chunk_timeout",
    "thinking",
    "when_thinking_enabled",
    "when_thinking_disabled",
)
_MCP_FLAG = "deerflow_mcp"
_MCP_SOURCE = "deerflow_mcp_source"


def _is_mcp_tool(tool: object) -> bool:
    metadata = getattr(tool, "metadata", None)
    return isinstance(metadata, dict) and metadata.get(_MCP_FLAG) is True


def _get_mcp_source(tool: object) -> dict[str, str] | None:
    metadata = getattr(tool, "metadata", None)
    source = metadata.get(_MCP_SOURCE) if isinstance(metadata, dict) else None
    if not isinstance(source, dict):
        return None
    server_name = source.get("server_name")
    transport = source.get("transport")
    if not isinstance(server_name, str) or not server_name:
        return None
    return {
        "server_name": server_name,
        "transport": transport if isinstance(transport, str) and transport else "unknown",
    }


_MIDDLEWARE_PUBLIC_FIELDS = (
    "max_concurrent",
    "max_total",
    "warn_threshold",
    "hard_limit",
    "window_size",
    "max_tracked_threads",
    "tool_freq_warn",
    "tool_freq_hard_limit",
    "trigger",
    "keep",
    "trim_tokens_to_summarize",
    "fail_closed",
    "passport",
    "_tool_freq_overrides",
    "_top_k",
    "_deferred",
    "_catalog_hash",
)
_MIDDLEWARE_HASHED_TEXT_FIELDS = (
    "summary_prompt",
    "system_prompt",
    "tool_description",
)
_MODEL_IDENTITY_FIELDS = (
    "model",
    "model_name",
    "deployment_name",
)
_PROVIDER_PARAMETER_FIELDS = (
    "_allowed",
    "_denied",
    "_default_role",
    "_resource_type",
    "_action",
)
_DETECTOR_PARAMETER_FIELDS = (
    "_finish_reasons",
    "_stop_reasons",
)


def _plain_value(value: object) -> object | None:
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, (list, tuple, set, frozenset)):
        children = [_plain_value(child) for child in value]
        if any(child is None and original is not None for child, original in zip(children, value, strict=True)):
            return None
        return sorted(children, key=str) if isinstance(value, (set, frozenset)) else children
    if isinstance(value, dict):
        result: dict[str, object] = {}
        for key, child in value.items():
            if not isinstance(key, str):
                continue
            plain = _plain_value(child)
            if plain is not None or child is None:
                result[key] = plain
        return result
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            return _plain_value(model_dump(mode="python"))
        except Exception:
            return None
    return None


def _stable_type_name(value: object) -> str:
    value_type = type(value)
    return f"{value_type.__module__}.{value_type.__qualname__}"


def _model_identity(value: object) -> dict[str, str]:
    if isinstance(value, str):
        return {"class": "builtins.str", "name": value}
    resolved = value
    seen: set[int] = set()
    while hasattr(resolved, "bound") and id(resolved) not in seen:
        seen.add(id(resolved))
        bound = getattr(resolved, "bound")
        if bound is None or bound is resolved:
            break
        resolved = bound
    identity = {"class": _stable_type_name(resolved)}
    for field_name in _MODEL_IDENTITY_FIELDS:
        field_value = getattr(resolved, field_name, None)
        if isinstance(field_value, str) and field_value:
            identity["name"] = field_value
            break
    return identity


def _provider_identity(value: object) -> dict[str, object]:
    identity: dict[str, object] = {
        "class": _stable_type_name(value),
        "name": str(getattr(value, "name", type(value).__name__)),
    }
    parameters: dict[str, object] = {}
    for field_name in _PROVIDER_PARAMETER_FIELDS:
        if not hasattr(value, field_name):
            continue
        raw_value = getattr(value, field_name)
        plain = _plain_value(raw_value)
        if plain is not None or raw_value is None:
            parameters[field_name.removeprefix("_")] = plain
    if parameters:
        identity["parameters"] = parameters
    nested = getattr(value, "_provider", None)
    if nested is not None and nested is not value:
        identity["provider"] = _provider_identity(nested)
    return identity


def _tool_schema(tool: object) -> dict[str, object]:
    get_input_schema = getattr(tool, "get_input_schema", None)
    if callable(get_input_schema):
        try:
            schema_model = get_input_schema()
            schema = schema_model.model_json_schema()
            if isinstance(schema, dict):
                return schema
        except Exception:
            pass
    args_schema = getattr(tool, "args_schema", None)
    model_json_schema = getattr(args_schema, "model_json_schema", None)
    if callable(model_json_schema):
        try:
            schema = model_json_schema()
            if isinstance(schema, dict):
                return schema
        except Exception:
            pass
    return {}


def _tool_source(tool: object) -> str:
    if _is_mcp_tool(tool):
        source = _get_mcp_source(tool)
        return f"mcp:{source['server_name']}" if source is not None else "mcp:unknown"
    metadata = getattr(tool, "metadata", None)
    if isinstance(metadata, dict):
        declared = metadata.get("deerflow_tool_source")
        if isinstance(declared, str) and declared:
            return declared
    callable_object = getattr(tool, "func", None) or getattr(tool, "coroutine", None)
    module = getattr(callable_object, "__module__", "") or ""
    if module.startswith("deerflow.tools.builtins") or module.startswith("deerflow.agents.memory"):
        return "builtin"
    if "skill" in module:
        return "skill"
    return "community" if module else "builtin"


def describe_tool(tool: object, *, deferred_names: frozenset[str] = frozenset()) -> ToolRuntimeDescriptor:
    name = str(getattr(tool, "name", type(tool).__name__))
    metadata: dict[str, object] = {}
    source = _get_mcp_source(tool) if _is_mcp_tool(tool) else None
    if source is not None:
        metadata["transport"] = source["transport"]
    routing = (getattr(tool, "metadata", None) or {}).get("deerflow_mcp_routing")
    plain_routing = _plain_value(routing)
    if isinstance(plain_routing, dict):
        metadata["routing"] = plain_routing
    return ToolRuntimeDescriptor(
        name=name,
        description=str(getattr(tool, "description", "") or ""),
        argument_schema=_tool_schema(tool),
        source=_tool_source(tool),
        deferred=name in deferred_names,
        behavior_metadata=metadata,
    )


def describe_middleware(middleware: object) -> MiddlewareRuntimeDescriptor:
    parameters: dict[str, object] = {}
    for field_name in _MIDDLEWARE_PUBLIC_FIELDS:
        if not hasattr(middleware, field_name):
            continue
        raw_value = getattr(middleware, field_name)
        plain = _plain_value(raw_value)
        if plain is not None or raw_value is None:
            parameters[field_name.removeprefix("_")] = plain
    for field_name in _MIDDLEWARE_HASHED_TEXT_FIELDS:
        raw_value = getattr(middleware, field_name, None)
        if isinstance(raw_value, str):
            parameters[f"{field_name}_hash"] = sha256_canonical(raw_value)
    model = getattr(middleware, "model", None)
    if model is not None:
        parameters["model"] = _model_identity(model)
    provider = getattr(middleware, "provider", None)
    if provider is not None:
        parameters["provider"] = _provider_identity(provider)
    routing_index = getattr(middleware, "_routing_index", None)
    plain_routing_index = _plain_value(routing_index)
    if plain_routing_index is not None:
        parameters["routing_index_hash"] = sha256_canonical(
            plain_routing_index,
        )
    detectors = getattr(middleware, "_detectors", None)
    if isinstance(detectors, (list, tuple)):
        detector_descriptors: list[dict[str, object]] = []
        for detector in detectors:
            descriptor: dict[str, object] = {
                "class": _stable_type_name(detector),
                "name": str(getattr(detector, "name", type(detector).__name__)),
            }
            detector_parameters: dict[str, object] = {}
            for field_name in _DETECTOR_PARAMETER_FIELDS:
                if not hasattr(detector, field_name):
                    continue
                raw_value = getattr(detector, field_name)
                plain = _plain_value(raw_value)
                if plain is not None or raw_value is None:
                    detector_parameters[field_name.removeprefix("_")] = plain
            if detector_parameters:
                descriptor["parameters"] = detector_parameters
            detector_descriptors.append(descriptor)
        parameters["detectors"] = detector_descriptors
    config = getattr(middleware, "_config", None)
    plain_config = _plain_value(config)
    if isinstance(plain_config, dict):
        parameters["config"] = plain_config
    return MiddlewareRuntimeDescriptor(
        name=type(middleware).__name__,
        public_parameters=parameters,
    )


def _runtime_build() -> RuntimeBuildDescriptor:
    try:
        package_version = version("deerflow-harness")
    except PackageNotFoundError:
        package_version = "unknown"
    return RuntimeBuildDescriptor(
        package_version=package_version,
        image_digest=os.environ.get("DEER_FLOW_IMAGE_DIGEST", "unknown"),
        git_commit=os.environ.get("DEER_FLOW_GIT_COMMIT", "unknown"),
    )


def _model_behavior(model_config: object, *, thinking_enabled: bool, reasoning_effort: object) -> dict[str, object]:
    result: dict[str, object] = {
        "thinking_enabled": thinking_enabled,
        "reasoning_effort": reasoning_effort,
    }
    for field_name in _MODEL_BEHAVIOR_FIELDS:
        if not hasattr(model_config, field_name):
            continue
        value = getattr(model_config, field_name)
        plain = _plain_value(value)
        if plain is not None or value is None:
            result[field_name] = plain
    return result


def build_runtime_descriptor(
    *,
    namespace: str,
    agent_name: str,
    requested_model: str | None,
    effective_model: str,
    model_config: object,
    thinking_enabled: bool,
    reasoning_effort: object,
    rendered_base_prompt: str,
    prompt_template_id: str = "deerflow-lead-agent-v1",
    tools: list[object],
    middlewares: list[object],
    deferred_names: frozenset[str],
    enabled_skills: list[object],
    effective_policies: dict[str, object],
) -> AgentRuntimeDescriptor:
    skill_catalog = [
        {
            "name": str(getattr(skill, "name", "")),
            "description": str(getattr(skill, "description", "")),
            "allowed_tools": sorted(str(item) for item in (getattr(skill, "allowed_tools", None) or ())),
        }
        for skill in enabled_skills
    ]
    use = getattr(model_config, "use", None)
    assembled_tools = list(tools)
    for middleware in middlewares:
        middleware_tools = getattr(middleware, "tools", None)
        if isinstance(middleware_tools, (list, tuple)):
            assembled_tools.extend(middleware_tools)
    return AgentRuntimeDescriptor(
        namespace=namespace,
        agent_name=agent_name,
        requested_model=requested_model,
        effective_model=effective_model,
        model_provider=str(use) if use else None,
        model_behavior_parameters=_model_behavior(
            model_config,
            thinking_enabled=thinking_enabled,
            reasoning_effort=reasoning_effort,
        ),
        prompt_template_id=prompt_template_id,
        rendered_base_prompt=rendered_base_prompt,
        available_skill_catalog_hash=sha256_canonical(sorted(skill_catalog, key=lambda item: item["name"])),
        loaded_tools=tuple(describe_tool(tool, deferred_names=deferred_names) for tool in assembled_tools),
        middleware_chain=tuple(describe_middleware(middleware) for middleware in middlewares),
        effective_policies=effective_policies,
        runtime_build=_runtime_build(),
    )


__all__ = [
    "build_runtime_descriptor",
    "describe_middleware",
    "describe_tool",
]
