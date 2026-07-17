from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from ansich.contracts import NamedVersion

ToolExecutionValue = Literal[
    "unknown",
    "issued",
    "acting",
    "returned",
    "denied",
    "timed_out",
    "cancelled",
    "failed",
    "unknown_terminal",
]
ToolAuthorizationValue = Literal["unknown", "allowed", "denied"]
ToolVisibleResultValue = Literal["unknown", "available"]
ToolTransformKind = Literal[
    "unchanged",
    "error_normalized",
    "sanitized",
    "truncated",
    "externalized",
    "coalesced",
    "clarification_card",
    "compressed",
    "memory_injected",
    "skill_injected",
    "vision_converted",
    "copied",
    "unknown",
]
ContentDerivationSourceRole = Literal["source", "preserved", "removed", "supporting"]


class ToolBelief(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    value: str
    as_of: datetime | None
    asserted_at: datetime
    source: NamedVersion
    fidelity_class: Literal["hard"] = "hard"
    selected_by: NamedVersion
    evidence_obs_ids: tuple[str, ...] = ()


class ToolResultView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    result_role: Literal["raw", "visible"]
    content_block_id: str
    source_obs_id: str
    content_hash: str | None
    byte_size: int | None
    payload_available: bool
    metadata: dict[str, object]


class ContentDerivationView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    derived_block_id: str
    source_block_id: str
    transform_kind: ToolTransformKind
    transform_version: str
    established_obs_id: str
    source_role: ContentDerivationSourceRole = "source"
    ordinal: int | None = None


class ToolCallView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_call_id: str
    task_id: str
    step_id: str
    step_seq: int
    call_seq: int
    provider_call_id: str | None
    tool_name: str
    args_hash: str
    args_preview: object
    tool_schema_block_id: str | None
    issued_obs_id: str | None
    started_obs_id: str | None
    raw_terminal_obs_id: str | None
    visible_result_obs_id: str | None
    duration_ms: int | None
    authorization: ToolBelief
    execution: ToolBelief
    visible_result: ToolBelief
    raw_results: tuple[ToolResultView, ...] = ()
    visible_results: tuple[ToolResultView, ...] = ()
    derivations: tuple[ContentDerivationView, ...] = ()
