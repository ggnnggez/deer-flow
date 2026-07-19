from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ansich.assessment.base import canonical_json_value
from ansich.release.canonical import sha256_canonical

_RUNTIME_ADDRESS = re.compile(r"(?<=\bat )0x[0-9a-fA-F]+\b")
_SCHEMA_VERSION = 1


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ToolRuntimeDescriptor(_FrozenModel):
    name: str = Field(min_length=1)
    description: str = ""
    argument_schema: dict[str, object] = Field(default_factory=dict)
    source: str = Field(min_length=1)
    deferred: bool = False
    behavior_metadata: dict[str, object] = Field(default_factory=dict)


class MiddlewareRuntimeDescriptor(_FrozenModel):
    name: str = Field(min_length=1)
    public_parameters: dict[str, object] = Field(default_factory=dict)


class RuntimeBuildDescriptor(_FrozenModel):
    package_version: str = "unknown"
    image_digest: str = "unknown"
    git_commit: str = "unknown"

    @field_validator("package_version", "image_digest", "git_commit", mode="before")
    @classmethod
    def _explicit_unknown(cls, value: object) -> object:
        return "unknown" if value is None or value == "" else value


class AgentRuntimeDescriptor(_FrozenModel):
    """Safe inputs captured from the objects used by actual agent assembly."""

    namespace: str = Field(min_length=1)
    agent_name: str = Field(min_length=1)
    requested_model: str | None = None
    effective_model: str = Field(min_length=1)
    model_provider: str | None = None
    model_behavior_parameters: dict[str, object] = Field(default_factory=dict)
    prompt_template_id: str = Field(min_length=1)
    prompt_template_hash: str | None = None
    rendered_base_prompt: str
    soul_hash: str | None = None
    available_skill_catalog_hash: str | None = None
    loaded_tools: tuple[ToolRuntimeDescriptor, ...] = ()
    middleware_chain: tuple[MiddlewareRuntimeDescriptor, ...] = ()
    effective_policies: dict[str, object] = Field(default_factory=dict)
    runtime_build: RuntimeBuildDescriptor = Field(default_factory=RuntimeBuildDescriptor)


class ReleaseModelManifest(_FrozenModel):
    requested: str | None = None
    effective: str
    provider: str | None = None
    behavior_parameters: dict[str, object]


class ReleasePromptManifest(_FrozenModel):
    template_id: str
    template_hash: str
    rendered_base_prompt: str
    rendered_base_prompt_hash: str
    soul_hash: str | None = None
    available_skill_catalog_hash: str | None = None


class ReleaseToolManifest(_FrozenModel):
    name: str
    description: str
    argument_schema: dict[str, object]
    schema_hash: str
    source: str
    deferred: bool
    behavior_metadata: dict[str, object]


class ReleasePolicyManifest(_FrozenModel):
    middleware_chain: tuple[MiddlewareRuntimeDescriptor, ...]
    values: dict[str, object]


class AgentReleaseManifest(_FrozenModel):
    schema_version: int = _SCHEMA_VERSION
    namespace: str
    agent_name: str
    model: ReleaseModelManifest
    prompt: ReleasePromptManifest
    tools: tuple[ReleaseToolManifest, ...]
    policy: ReleasePolicyManifest
    runtime_build: RuntimeBuildDescriptor


class AgentReleaseFingerprint(_FrozenModel):
    model_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    prompt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    tool_catalog_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    runtime_build_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    release_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class AgentRelease(_FrozenModel):
    manifest: AgentReleaseManifest
    fingerprint: AgentReleaseFingerprint


def _remove_runtime_addresses(value: object) -> object:
    if isinstance(value, str):
        return _RUNTIME_ADDRESS.sub("<runtime-address>", value)
    if isinstance(value, Mapping):
        return {key: _remove_runtime_addresses(child) for key, child in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray):
        return [_remove_runtime_addresses(child) for child in value]
    return value


def _sanitize(value: object, *, known_secrets: Sequence[str]) -> Any:
    """Apply the release allowlist's second-line structural secret filter."""

    without_credentials = canonical_json_value(
        value,
        filter_secret_fields=True,
        known_secrets=known_secrets,
    )
    return _remove_runtime_addresses(without_credentials)


def _tool_manifest(tool: ToolRuntimeDescriptor, *, known_secrets: Sequence[str]) -> ReleaseToolManifest:
    schema = _sanitize(tool.argument_schema, known_secrets=known_secrets)
    metadata = _sanitize(tool.behavior_metadata, known_secrets=known_secrets)
    description = _sanitize(tool.description, known_secrets=known_secrets)
    return ReleaseToolManifest(
        name=tool.name,
        description=str(description),
        argument_schema=dict(schema),
        schema_hash=sha256_canonical(schema),
        source=tool.source,
        deferred=tool.deferred,
        behavior_metadata=dict(metadata),
    )


def build_agent_release(
    descriptor: AgentRuntimeDescriptor,
    *,
    known_secrets: Sequence[str] = (),
) -> AgentRelease:
    """Sanitize and fingerprint the effective Task-start actor configuration."""

    model_parameters = _sanitize(descriptor.model_behavior_parameters, known_secrets=known_secrets)
    rendered_prompt = str(_sanitize(descriptor.rendered_base_prompt, known_secrets=known_secrets))
    tools = tuple(
        sorted(
            (_tool_manifest(tool, known_secrets=known_secrets) for tool in descriptor.loaded_tools),
            key=lambda tool: (tool.source, tool.name, tool.schema_hash),
        )
    )
    middleware_chain = tuple(
        MiddlewareRuntimeDescriptor(
            name=item.name,
            public_parameters=dict(_sanitize(item.public_parameters, known_secrets=known_secrets)),
        )
        for item in descriptor.middleware_chain
    )
    policy_values = dict(_sanitize(descriptor.effective_policies, known_secrets=known_secrets))
    build = RuntimeBuildDescriptor.model_validate(_sanitize(descriptor.runtime_build.model_dump(mode="python"), known_secrets=known_secrets))

    model_identity = {
        "effective": descriptor.effective_model,
        "provider": descriptor.model_provider,
        "behavior_parameters": model_parameters,
    }
    prompt = ReleasePromptManifest(
        template_id=descriptor.prompt_template_id,
        template_hash=descriptor.prompt_template_hash or sha256_canonical({"template_id": descriptor.prompt_template_id}),
        rendered_base_prompt=rendered_prompt,
        rendered_base_prompt_hash=sha256_canonical(rendered_prompt),
        soul_hash=descriptor.soul_hash,
        available_skill_catalog_hash=descriptor.available_skill_catalog_hash,
    )
    model = ReleaseModelManifest(
        requested=descriptor.requested_model,
        effective=descriptor.effective_model,
        provider=descriptor.model_provider,
        behavior_parameters=dict(model_parameters),
    )
    policy = ReleasePolicyManifest(middleware_chain=middleware_chain, values=policy_values)

    model_hash = sha256_canonical(model_identity)
    prompt_hash = sha256_canonical(prompt.model_dump(mode="python"))
    tool_catalog_hash = sha256_canonical([tool.model_dump(mode="python") for tool in tools])
    policy_hash = sha256_canonical(policy.model_dump(mode="python"))
    runtime_build_id = sha256_canonical(build.model_dump(mode="python"))
    component_hashes = {
        "model_hash": model_hash,
        "prompt_hash": prompt_hash,
        "tool_catalog_hash": tool_catalog_hash,
        "policy_hash": policy_hash,
        "runtime_build_id": runtime_build_id,
    }
    release_hash = sha256_canonical(
        {
            "schema_version": _SCHEMA_VERSION,
            "namespace": descriptor.namespace,
            "agent_name": descriptor.agent_name,
            "component_hashes": component_hashes,
        }
    )
    return AgentRelease(
        manifest=AgentReleaseManifest(
            namespace=descriptor.namespace,
            agent_name=descriptor.agent_name,
            model=model,
            prompt=prompt,
            tools=tools,
            policy=policy,
            runtime_build=build,
        ),
        fingerprint=AgentReleaseFingerprint(**component_hashes, release_hash=release_hash),
    )


__all__ = [
    "AgentRelease",
    "AgentReleaseFingerprint",
    "AgentReleaseManifest",
    "AgentRuntimeDescriptor",
    "MiddlewareRuntimeDescriptor",
    "RuntimeBuildDescriptor",
    "ToolRuntimeDescriptor",
    "build_agent_release",
]
