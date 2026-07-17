from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class LlmAttemptView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    attempt_id: str
    task_id: str
    step_id: str | None
    actor_kind: Literal["lead_agent", "subagent", "system_operation"]
    operation_id: str | None = None
    operation_kind: str | None = None
    attempt_no: int
    status: Literal["requested", "success", "failed", "incomplete"]
    request_obs_id: str | None
    response_obs_id: str | None
    failure_obs_id: str | None
    provider_model: str | None
    usage: dict[str, int]
    response_metadata: dict[str, object]
    latency_ms: int | None
    context_snapshot_id: str | None
    effective: bool = False


class StepView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    step_id: str
    task_id: str
    step_seq: int
    actor_kind: Literal["lead_agent", "subagent"]
    status: Literal["deciding", "acting", "closed", "model_failed"]
    result: Literal["acting", "final_answer", "model_failed"] | None
    started_obs_id: str
    closed_obs_id: str | None
    effective_attempt_no: int | None
    effective_context_snapshot_id: str | None
    issued_tools: tuple[dict[str, object], ...] = ()
    attempts: tuple[LlmAttemptView, ...] = ()


class ContextSnapshotItemView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ordinal: int
    channel: Literal["message", "tool_schema"]
    role: Literal["system", "user", "assistant", "tool"] | None
    name: str | None
    block_id: str
    kind: str | None
    content_hash: str | None
    visible_bytes: int
    estimated_tokens: int
    metadata: dict[str, object]
    sensitivity_flags: tuple[str, ...] = ()
    payload_available: bool
    resolution_status: Literal["available", "missing"] = "available"
    body: None = None


class ContextSnapshotView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot_id: str
    task_id: str
    step_id: str | None
    operation_id: str | None
    attempt_no: int
    request_obs_id: str
    message_count: int
    tool_schema_count: int
    visible_bytes: int
    estimated_tokens: int
    estimator_name: str
    estimator_version: str
    adapter_name: str
    adapter_version: str
    configured_model: str | None
    response_format: object | None
    generation_settings: dict[str, object]
    redactions: tuple[dict[str, object], ...]
    warnings: tuple[str, ...]
    items: tuple[ContextSnapshotItemView, ...]
    status: Literal["complete", "incomplete"] = "complete"


class ContentBlockPayloadView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    block_id: str
    content_type: str = "application/json"
    body: object
