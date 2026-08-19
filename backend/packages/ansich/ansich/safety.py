from __future__ import annotations

import posixpath
from datetime import datetime
from hashlib import sha256
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ansich.credentials import contains_credential_like_material

ScopeKind = Literal[
    "owner",
    "thread",
    "workspace",
    "sandbox",
    "authorization",
    "external_origin",
    "host",
]
ScopeRelationRole = Literal[
    "owner",
    "conversation",
    "execution_workspace",
    "sandbox_boundary",
    "auth_context",
    "trigger_origin",
    "host_environment",
]
AuthorizationDecision = Literal["allowed", "denied", "unknown"]
EffectClass = Literal[
    "filesystem_read",
    "filesystem_write",
    "filesystem_delete",
    "process_execute",
    "network_read",
    "external_write",
    "permission_change",
    "child_task_spawn",
    "unknown",
]
EffectPhase = Literal["potential", "intended", "observed"]
EffectFidelity = Literal["hard", "declared", "inferred", "unknown"]


def scope_reference_hash(scope_kind: ScopeKind, external_ref: str) -> str:
    """Return a stable identifier component without retaining a sensitive raw ref."""

    normalized = external_ref.strip()
    if not normalized:
        raise ValueError("scope external reference must be non-empty")
    if scope_kind in {"workspace", "sandbox"}:
        normalized = posixpath.normpath(normalized.replace("\\", "/"))
    return sha256(f"ansich-scope-v1\0{scope_kind}\0{normalized}".encode()).hexdigest()


def scope_display_label(scope_kind: ScopeKind, external_ref: str) -> str:
    """Return a bounded label that does not expose workspace/sandbox absolute roots."""

    normalized = external_ref.strip()
    if not normalized:
        raise ValueError("scope external reference must be non-empty")
    if scope_kind in {"workspace", "sandbox"}:
        logical_path = posixpath.normpath(normalized.replace("\\", "/"))
        return (posixpath.basename(logical_path) or scope_kind)[:256]
    return normalized[:256]


def scope_entity_id(scope_kind: ScopeKind, external_ref_hash: str) -> str:
    """Return a replay-stable UUID4-shaped entity ID for a hashed Scope ref."""

    if len(external_ref_hash) != 64 or any(character not in "0123456789abcdef" for character in external_ref_hash):
        raise ValueError("scope external_ref_hash must be lowercase sha256 hex")
    digest = sha256(f"ansich-scope-entity-v1\0{scope_kind}\0{external_ref_hash}".encode()).digest()
    return str(UUID(bytes=digest[:16], version=4))


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ScopeDescriptor(_FrozenModel):
    scope_id: str = Field(min_length=1)
    scope_kind: ScopeKind
    external_ref_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    display_label: str = Field(min_length=1, max_length=256)
    parent_scope_id: str | None = None
    created_obs_id: str = Field(min_length=1)


class TaskScopeView(ScopeDescriptor):
    relation_role: ScopeRelationRole
    relation_obs_id: str = Field(min_length=1)
    inherited_from_task_id: str | None = None


class TaskScopesView(_FrozenModel):
    task_id: str = Field(min_length=1)
    scopes: tuple[TaskScopeView, ...]


class AuthorizationPermission(_FrozenModel):
    resource: str = Field(min_length=1, max_length=512)
    action: str = Field(min_length=1, max_length=128)
    scope_id: str | None = None
    effect: EffectClass


class AuthorizationSnapshot(_FrozenModel):
    snapshot_id: str = Field(min_length=1)
    tool_call_id: str = Field(min_length=1)
    principal_scope_ids: tuple[str, ...] = ()
    policy_id: str = Field(min_length=1, max_length=256)
    policy_version: str = Field(min_length=1, max_length=128)
    policy_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision: AuthorizationDecision
    details_available: bool
    effective_permissions: tuple[AuthorizationPermission, ...] = ()
    resource_scope_ids: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    evaluated_at: datetime
    evidence_obs_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _bool_only_provider_has_no_permissions(self) -> Self:
        if not self.details_available and self.effective_permissions:
            raise ValueError("details_available=false cannot include effective permissions")
        if self.evaluated_at.tzinfo is None:
            raise ValueError("authorization evaluated_at must be timezone-aware")
        if contains_credential_like_material(self.model_dump(mode="python")):
            raise ValueError("AuthorizationSnapshot contains credential-like material")
        return self


class ToolAuthorizationView(_FrozenModel):
    tool_call_id: str = Field(min_length=1)
    snapshots: tuple[AuthorizationSnapshot, ...]
    current_decision: AuthorizationDecision


class ToolEffect(_FrozenModel):
    effect_id: str = Field(min_length=1)
    tool_call_id: str = Field(min_length=1)
    effect_class: EffectClass
    phase: EffectPhase
    scope_id: str | None = None
    target_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    target_preview: str | None = Field(default=None, max_length=512)
    fidelity_class: EffectFidelity
    source_obs_id: str = Field(min_length=1)
    result_metadata: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _exclude_credentials(self) -> Self:
        if contains_credential_like_material(
            {
                "target_preview": self.target_preview,
                "result_metadata": self.result_metadata,
            }
        ):
            raise ValueError("ToolEffect contains credential-like material")
        return self


class ToolEffectsView(_FrozenModel):
    tool_call_id: str = Field(min_length=1)
    effects: tuple[ToolEffect, ...]
    coverage: Literal["complete", "partial", "unknown"]
