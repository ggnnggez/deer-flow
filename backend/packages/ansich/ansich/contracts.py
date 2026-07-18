from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ansich.ids import new_id

TaskLifecycleKind = Literal[
    "task.created",
    "task.started",
    "task.completed",
    "task.failed",
    "task.interrupted",
]
StepObservationKind = Literal["step.started", "step.closed"]
LlmObservationKind = Literal["llm.requested", "llm.responded", "llm.failed"]
ContextObservationKind = Literal[
    "content.produced",
    "context.state_recorded",
    "context.snapshotted",
    "context.compressed",
]
ToolObservationKind = Literal[
    "tool.issued",
    "tool.started",
    "tool.returned_raw",
    "tool.result_visible",
    "tool.denied",
    "tool.timed_out",
    "tool.cancelled",
    "tool.failed",
    "tool.unknown_terminal",
]
BudgetObservationKind = Literal["budget.configured", "budget.consumed"]
OperatorObservationKind = Literal[
    "operator.action_requested",
    "operator.action_succeeded",
    "operator.action_failed",
    "operator.alert_acknowledged",
    "operator.alert_dismissed",
]
UsageDimension = Literal[
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "llm_attempts",
    "steps",
    "tool_calls_issued",
    "tool_calls_executed",
    "wall_time_ms",
    "child_tasks_spawned",
]
ObservationKind = TaskLifecycleKind | StepObservationKind | LlmObservationKind | ContextObservationKind | ToolObservationKind | BudgetObservationKind | OperatorObservationKind | Literal["task.heartbeat", "observability.degraded"]
ControlValue = Literal["unknown", "created", "running", "completed", "failed", "interrupted"]
TaskLifecycleScope = Literal["all", "active", "terminal"]


def control_values_for_lifecycle_scope(
    scope: TaskLifecycleScope,
) -> frozenset[ControlValue] | None:
    if scope == "all":
        return None
    if scope == "active":
        return frozenset(("created", "running"))
    if scope == "terminal":
        return frozenset(("completed", "failed", "interrupted"))
    raise ValueError(f"unsupported Task lifecycle scope: {scope}")


_USAGE_DIMENSIONS = frozenset(
    {
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "llm_attempts",
        "steps",
        "tool_calls_issued",
        "tool_calls_executed",
        "wall_time_ms",
        "child_tasks_spawned",
    }
)

_SECRET_FIELD_NAMES = frozenset(
    {
        "apikey",
        "authorization",
        "clientsecret",
        "cookie",
        "credential",
        "credentials",
        "dsn",
        "idtoken",
        "password",
        "passwd",
        "refreshtoken",
        "setcookie",
        "accesstoken",
    }
)


def _normalized_field_name(value: object) -> str:
    return "".join(character for character in str(value).lower() if character.isalnum())


def _find_secret_field(value: object, path: str = "payload") -> str | None:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if _normalized_field_name(key) in _SECRET_FIELD_NAMES:
                return child_path
            found = _find_secret_field(child, child_path)
            if found is not None:
                return found
    elif isinstance(value, list | tuple):
        for index, child in enumerate(value):
            found = _find_secret_field(child, f"{path}[{index}]")
            if found is not None:
                return found
    return None


def _validate_uuid4(value: str) -> str:
    parsed = UUID(value)
    if parsed.version != 4 or str(parsed) != value.lower():
        raise ValueError("identity must be a canonical UUID4 string")
    return str(parsed)


class NamedVersion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    name: str = Field(min_length=1)
    version: str = Field(min_length=1)


class Producer(NamedVersion):
    instance_id: str = Field(min_length=1)


class ObservationEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    obs_id: str = Field(default_factory=new_id)
    schema_version: int = 1
    kind: ObservationKind
    occurred_at: datetime
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    task_id: str
    step_id: str | None = None
    subject_type: Literal[
        "task",
        "step",
        "llm_attempt",
        "tool_call",
        "content_block",
        "context_state",
        "context_snapshot",
        "context_compression",
        "alert",
    ] = "task"
    subject_id: str
    fidelity_class: Literal["hard"] = "hard"
    producer: Producer
    producer_seq: int = Field(default=1, ge=1)
    source_event_id: str = Field(min_length=1)
    correlation_id: str = Field(min_length=1)
    causation_obs_id: str | None = None
    payload: dict[str, object] | None = None
    payload_ref_id: str | None = None

    @field_validator("obs_id", "task_id", "step_id", "subject_id", "causation_obs_id", "payload_ref_id")
    @classmethod
    def _identity_is_uuid4(cls, value: str | None) -> str | None:
        return None if value is None else _validate_uuid4(value)

    @model_validator(mode="after")
    def _validate_subject(self) -> Self:
        if self.kind.startswith("task.") or self.kind == "observability.degraded":
            if self.subject_type != "task" or self.subject_id != self.task_id:
                raise ValueError("task observation subject must identify task_id")
        elif self.kind.startswith("step."):
            if self.step_id is None or self.subject_type != "step" or self.subject_id != self.step_id:
                raise ValueError("step observation subject must identify step_id")
        elif self.kind.startswith("llm.") and self.subject_type != "llm_attempt":
            raise ValueError("LLM observation subject_type must be llm_attempt")
        elif self.kind.startswith("tool.") and self.subject_type != "tool_call":
            raise ValueError("Tool observation subject_type must be tool_call")
        elif self.kind == "content.produced" and self.subject_type != "content_block":
            raise ValueError("content observation subject_type must be content_block")
        elif self.kind == "context.state_recorded" and self.subject_type != "context_state":
            raise ValueError("context state observation subject_type must be context_state")
        elif self.kind == "context.snapshotted" and self.subject_type != "context_snapshot":
            raise ValueError("context snapshot observation subject_type must be context_snapshot")
        elif self.kind == "context.compressed" and self.subject_type != "context_compression":
            raise ValueError("context compression observation subject_type must be context_compression")
        elif self.kind.startswith("budget.") and (self.subject_type != "task" or self.subject_id != self.task_id):
            raise ValueError("budget observation subject must identify task_id")
        elif self.kind.startswith("operator.alert_") and self.subject_type != "alert":
            raise ValueError("Alert workflow observation subject_type must be alert")
        elif self.kind.startswith("operator.action_") and (self.subject_type != "task" or self.subject_id != self.task_id):
            raise ValueError("Operator action observation subject must identify task_id")
        if self.kind == "task.heartbeat":
            payload = self.payload or {}
            elapsed_ms = payload.get("elapsed_ms")
            if not isinstance(elapsed_ms, int) or isinstance(elapsed_ms, bool) or elapsed_ms < 0:
                raise ValueError("task.heartbeat elapsed_ms must be a non-negative integer")
            for field_name in (
                "worker_id",
                "producer_instance_id",
                "ownership_epoch",
            ):
                if not isinstance(payload.get(field_name), str) or not payload[field_name]:
                    raise ValueError(f"task.heartbeat {field_name} must be non-empty")
        if self.kind == "budget.configured":
            payload = self.payload or {}
            if payload.get("dimension") not in _USAGE_DIMENSIONS:
                raise ValueError("budget.configured dimension is unsupported")
            if payload.get("aggregation_scope") not in {"local", "inclusive"}:
                raise ValueError("budget.configured aggregation_scope is unsupported")
            if payload.get("source_kind") not in {
                "release_default",
                "runtime_override",
                "shadow",
            }:
                raise ValueError("budget.configured source_kind is unsupported")
            if not isinstance(payload.get("enforcement"), bool):
                raise ValueError("budget.configured enforcement must be boolean")
            for field_name in (
                "warning_limit",
                "hard_limit",
                "requested_value",
                "effective_value",
            ):
                value = payload.get(field_name)
                if field_name != "effective_value" and value is None:
                    continue
                if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                    raise ValueError(f"budget.configured {field_name} must be a non-negative integer")
        if self.occurred_at.tzinfo is None or self.recorded_at.tzinfo is None:
            raise ValueError("observation timestamps must be timezone-aware")
        if (self.payload is None) == (self.payload_ref_id is None):
            raise ValueError("exactly one of payload and payload_ref_id must be provided")
        if self.payload is not None:
            secret_path = _find_secret_field(self.payload)
            if secret_path is not None:
                raise ValueError(f"secret-bearing field is not allowed in Observation payload: {secret_path}")
        return self

    @classmethod
    def task_lifecycle(
        cls,
        *,
        kind: TaskLifecycleKind,
        task_id: str,
        source_kind: str,
        source_id: str,
        occurred_at: datetime,
        source_event_id: str,
        producer_seq: int = 1,
        thread_id: str | None = None,
        owner_id: str | None = None,
        trigger_kind: str | None = None,
        producer_name: str = "task-control-probe",
        producer_version: str = "1",
        producer_instance_id: str = "local",
    ) -> Self:
        payload: dict[str, object] = {"source_kind": source_kind, "source_id": source_id}
        if thread_id is not None:
            payload["thread_id"] = thread_id
        if owner_id is not None:
            payload["owner_id"] = owner_id
        if trigger_kind is not None:
            payload["trigger_kind"] = trigger_kind
        return cls(
            kind=kind,
            occurred_at=occurred_at,
            task_id=task_id,
            subject_id=task_id,
            producer=Producer(
                name=producer_name,
                version=producer_version,
                instance_id=producer_instance_id,
            ),
            producer_seq=producer_seq,
            source_event_id=source_event_id,
            correlation_id=source_id,
            payload=payload,
        )

    @classmethod
    def task_heartbeat(
        cls,
        *,
        task_id: str,
        run_id: str,
        occurred_at: datetime,
        elapsed_ms: int,
        worker_id: str,
        ownership_epoch: str,
        source_event_id: str,
        producer_seq: int = 1,
        producer_name: str = "task-heartbeat-probe",
        producer_version: str = "1",
        producer_instance_id: str = "local",
    ) -> Self:
        return cls(
            kind="task.heartbeat",
            occurred_at=occurred_at,
            task_id=task_id,
            subject_id=task_id,
            producer=Producer(
                name=producer_name,
                version=producer_version,
                instance_id=producer_instance_id,
            ),
            producer_seq=producer_seq,
            source_event_id=source_event_id,
            correlation_id=run_id,
            payload={
                "worker_id": worker_id,
                "producer_instance_id": producer_instance_id,
                "ownership_epoch": ownership_epoch,
                "elapsed_ms": elapsed_ms,
            },
        )

    @classmethod
    def budget_consumed(
        cls,
        *,
        task_id: str,
        run_id: str,
        occurred_at: datetime,
        dimension: UsageDimension,
        delta: int,
        source_event_id: str,
        producer_seq: int = 1,
        producer_name: str = "budget-consumption-probe",
        producer_version: str = "1",
        producer_instance_id: str = "local",
    ) -> Self:
        if dimension not in _USAGE_DIMENSIONS:
            raise ValueError(f"unsupported usage dimension: {dimension}")
        if not isinstance(delta, int) or isinstance(delta, bool) or delta < 0:
            raise ValueError("budget consumption delta must be a non-negative integer")
        return cls(
            kind="budget.consumed",
            occurred_at=occurred_at,
            task_id=task_id,
            subject_id=task_id,
            producer=Producer(
                name=producer_name,
                version=producer_version,
                instance_id=producer_instance_id,
            ),
            producer_seq=producer_seq,
            source_event_id=source_event_id,
            correlation_id=run_id,
            payload={"dimension": dimension, "delta": delta},
        )

    @classmethod
    def budget_configured(
        cls,
        *,
        task_id: str,
        run_id: str,
        occurred_at: datetime,
        dimension: UsageDimension,
        aggregation_scope: Literal["local", "inclusive"],
        warning_limit: int | None,
        hard_limit: int | None,
        enforcement: bool,
        source_kind: Literal["release_default", "runtime_override", "shadow"],
        requested_value: int | None,
        effective_value: int,
        source_event_id: str,
        producer_seq: int = 1,
        producer_name: str = "budget-configuration-probe",
        producer_version: str = "1",
        producer_instance_id: str = "local",
    ) -> Self:
        return cls(
            kind="budget.configured",
            occurred_at=occurred_at,
            task_id=task_id,
            subject_id=task_id,
            producer=Producer(
                name=producer_name,
                version=producer_version,
                instance_id=producer_instance_id,
            ),
            producer_seq=producer_seq,
            source_event_id=source_event_id,
            correlation_id=run_id,
            payload={
                "dimension": dimension,
                "aggregation_scope": aggregation_scope,
                "warning_limit": warning_limit,
                "hard_limit": hard_limit,
                "enforcement": enforcement,
                "source_kind": source_kind,
                "requested_value": requested_value,
                "effective_value": effective_value,
            },
        )


class RecordReceipt(BaseModel):
    model_config = ConfigDict(frozen=True)

    obs_id: str | None
    accepted: bool
    reason: str | None = None


class FlushResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    persisted: bool
    processed_count: int
    reason: str | None = None


class LostRange(BaseModel):
    model_config = ConfigDict(frozen=True)

    first_sequence: int
    last_sequence: int
    task_id: str | None
    producer_name: str | None = None
    producer_instance_id: str | None = None


class AnsichHealth(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["healthy", "degraded", "failed", "stopped"]
    queue_depth: int
    queue_capacity: int
    queue_bytes: int = 0
    queue_byte_capacity: int = 0
    accepted_count: int
    dropped_count: int
    lost_ranges: tuple[LostRange, ...]
    watermark: int | None = None
    lag_ms: int = 0
    failed_jobs: int = 0
    loss_detected: bool = False
    range_known: bool = True
    storage_available: bool = True
    queue_high_watermark: int = 0
    queue_byte_high_watermark: int = 0
    snapshot_request_count: int = 0
    snapshot_observations_accepted: int = 0
    snapshot_observations_dropped: int = 0
    snapshot_count: int = 0
    snapshot_item_count: int = 0
    snapshot_visible_bytes: int = 0
    incomplete_snapshot_count: int = 0
    missing_content_block_count: int = 0


class ControlBelief(BaseModel):
    model_config = ConfigDict(frozen=True)

    value: ControlValue
    as_of: datetime | None
    asserted_at: datetime
    source: NamedVersion
    fidelity_class: Literal["hard"]
    selected_by: NamedVersion
    evidence_obs_ids: tuple[str, ...]


class TaskView(BaseModel):
    model_config = ConfigDict(frozen=True)

    task_id: str
    source_kind: str
    source_id: str
    control: ControlBelief
    observability_status: Literal["healthy", "degraded"] = "healthy"
    tool_calls_issued: int = 0
    tool_calls_executed: int = 0
