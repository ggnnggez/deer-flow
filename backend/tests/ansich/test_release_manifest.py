from __future__ import annotations

import pytest
from ansich.release import (
    AgentRuntimeDescriptor,
    MiddlewareRuntimeDescriptor,
    RuntimeBuildDescriptor,
    ToolRuntimeDescriptor,
    build_agent_release,
)


def _descriptor(**overrides: object) -> AgentRuntimeDescriptor:
    values: dict[str, object] = {
        "namespace": "deerflow",
        "agent_name": "lead",
        "requested_model": "fast-alias",
        "effective_model": "provider/model-v1",
        "model_provider": "provider",
        "model_behavior_parameters": {"temperature": 0, "thinking": False},
        "prompt_template_id": "lead-agent-v1",
        "rendered_base_prompt": "You are DeerFlow.",
        "soul_hash": None,
        "available_skill_catalog_hash": "a" * 64,
        "loaded_tools": (
            ToolRuntimeDescriptor(
                name="search",
                description="Search documents",
                argument_schema={"type": "object", "properties": {"query": {"type": "string"}}},
                source="builtin",
                deferred=False,
            ),
            ToolRuntimeDescriptor(
                name="lookup",
                description="Lookup a record",
                argument_schema={"type": "object", "properties": {"id": {"type": "integer"}}},
                source="mcp:catalog",
                deferred=True,
            ),
        ),
        "middleware_chain": (
            MiddlewareRuntimeDescriptor(name="SummarizationMiddleware", public_parameters={"trigger": 0.8}),
            MiddlewareRuntimeDescriptor(name="TokenBudgetMiddleware", public_parameters={"max_tokens": 10_000}),
        ),
        "effective_policies": {"non_interactive": False, "tool_output": {"max_bytes": 8192}},
        "runtime_build": RuntimeBuildDescriptor(package_version="0.1.0", image_digest="unknown", git_commit="abc123"),
    }
    values.update(overrides)
    return AgentRuntimeDescriptor.model_validate(values)


def test_release_hash_is_stable_for_tool_set_order_and_requested_model_alias() -> None:
    descriptor = _descriptor()
    first = build_agent_release(descriptor)
    second = build_agent_release(
        descriptor.model_copy(
            update={
                "requested_model": "another-alias",
                "loaded_tools": tuple(reversed(descriptor.loaded_tools)),
            }
        )
    )

    assert first.fingerprint.release_hash == second.fingerprint.release_hash
    assert first.fingerprint.model_hash == second.fingerprint.model_hash
    assert first.manifest.model.requested == "fast-alias"
    assert second.manifest.model.requested == "another-alias"


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("effective_model", "provider/model-v2"),
        ("rendered_base_prompt", "You are a changed DeerFlow."),
        ("effective_policies", {"non_interactive": True}),
        ("runtime_build", RuntimeBuildDescriptor(package_version="0.2.0")),
    ],
)
def test_behavior_component_changes_create_a_new_release(field: str, replacement: object) -> None:
    original = build_agent_release(_descriptor())
    changed = build_agent_release(_descriptor(**{field: replacement}))

    assert changed.fingerprint.release_hash != original.fingerprint.release_hash


def test_tool_schema_change_creates_a_new_release() -> None:
    descriptor = _descriptor()
    changed_tool = descriptor.loaded_tools[0].model_copy(update={"argument_schema": {"type": "object", "required": ["query"]}})

    changed = build_agent_release(descriptor.model_copy(update={"loaded_tools": (changed_tool, *descriptor.loaded_tools[1:])}))

    assert changed.fingerprint.tool_catalog_hash != build_agent_release(descriptor).fingerprint.tool_catalog_hash


def test_release_sanitizes_secret_fields_values_and_runtime_addresses_before_hashing() -> None:
    secret = "secret-token-value"
    descriptor = _descriptor(
        model_behavior_parameters={
            "temperature": 0,
            "api_key": secret,
            "client": "<Client at 0x7fbadbeef>",
        },
        effective_policies={
            "authorization": f"Bearer {secret}",
            "nested": {"password": secret, "label": f"prefix-{secret}"},
        },
    )

    release = build_agent_release(descriptor, known_secrets=(secret,))
    encoded = release.manifest.model_dump_json()

    assert secret not in encoded
    assert "api_key" not in encoded
    assert "authorization" not in encoded
    assert "password" not in encoded
    assert "0x7fbadbeef" not in encoded


def test_runtime_secret_changes_do_not_change_release_identity() -> None:
    first = _descriptor(model_behavior_parameters={"temperature": 0, "api_key": "first"})
    second = _descriptor(model_behavior_parameters={"temperature": 0, "api_key": "second"})

    assert build_agent_release(first).fingerprint.release_hash == build_agent_release(second).fingerprint.release_hash
