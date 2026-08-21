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
ScopeObservationKind = Literal["scope.snapshotted"]
EnvironmentObservationKind = Literal["environment.sampled"]
AuthorizationObservationKind = Literal[
    "authorization.evaluated",
    "authorization.allowed",
    "authorization.denied",
    "authorization.unknown",
]
EffectObservationKind = Literal[
    "effect.potential",
    "effect.intended",
    "effect.observed",
]
EvaluationObservationKind = Literal["evaluation.recorded"]
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
ObservationKind = (
    TaskLifecycleKind
    | StepObservationKind
    | LlmObservationKind
    | ContextObservationKind
    | ToolObservationKind
    | BudgetObservationKind
    | OperatorObservationKind
    | ScopeObservationKind
    | AuthorizationObservationKind
    | EffectObservationKind
    | EvaluationObservationKind
    | EnvironmentObservationKind
    | Literal[
        "agent_release.resolved",
        "task.heartbeat",
        "observability.degraded",
        # RB2. Process-wide collection loss: a range charged for something that
        # never was an Observation, so it has no Task to be subjected to and
        # `observability.degraded` (Task-subjected, frozen) cannot carry it. It
        # is subjected to the host Scope instead, under
        # `ANSICH_BOOTSTRAP_TASK_ID`.
        #
        # **Deliberately unprojected.** This kind is registered in no projector
        # (`sql.py::_PROJECTOR_KINDS`): the evidence chain a process-wide Alert
        # needs is that the row exists, which the Observation stream already
        # provides, so a read model would only duplicate it. The consequence is
        # a one-way door and is written here rather than discovered later —
        # `rebuild_projections()` re-pends the jobs that *exist*, so a projector
        # added for this kind tomorrow would silently start at the rows written
        # after it was registered and skip every one before. Adding one means
        # backfilling those rows deliberately, not just registering a name.
        "observability.lost",
    ]
)

#: The ``task_id`` every **bootstrap** Observation carries.
#:
#: RB1②. ``ObservationEnvelope.task_id`` is required and UUID4-validated, but a
#: process-level fact — the host ``Scope`` this process runs in, and the loss it
#: charged for something that never was an Observation — belongs to no Task.
#: This fixed UUID4 states that explicitly instead of minting a per-process id
#: that would read like a real Task: an Observation under this id is a bootstrap
#: record and **has no corresponding Task entity**. Storing it is legal because
#: ``ansich_observations.task_id`` carries no foreign key.
#:
#: What must never happen under it: Task-scoped machinery. The assessor job and
#: watermark tables are FK-bound to ``ansich_tasks`` (RB3①), so a Task-scoped
#: job minted for this id would not even insert — see the guard at the assessor
#: enqueue in ``sql.py``.
#:
#: The value is part of the contract, not an implementation detail: rows already
#: written under it are found by it, so changing it orphans them.
ANSICH_BOOTSTRAP_TASK_ID = "00000000-0000-4000-8000-000000000001"
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
        "agent_release",
        "alert",
        "scope",
        "authorization_snapshot",
        "effect",
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
        elif self.kind == "observability.lost":
            # RB2②. The subject is the host Scope and the Task field is the
            # bootstrap sentinel — both required, because this kind exists to
            # carry loss that has no Task. A real `task_id` here would mean the
            # loss did have one, and that loss is `observability.degraded`.
            if self.subject_type != "scope":
                raise ValueError("observability.lost subject_type must be scope")
            if self.task_id != ANSICH_BOOTSTRAP_TASK_ID:
                raise ValueError("observability.lost must carry the bootstrap Task sentinel")
            # Guarded on `payload is not None`, and that guard is the point
            # (F10-29). A payload over `inline_payload_max_bytes` is stored in
            # `ansich_payloads` and reads back as `payload_json IS NULL` plus a
            # `payload_ref_id`; `_observation_from_row` hands exactly that to
            # this model. `environment.sampled` raises on it and is the open
            # instance of the class — this branch must not join it.
            if self.payload is not None:
                first_sequence = self.payload.get("first_sequence")
                last_sequence = self.payload.get("last_sequence")
                for field_name, value in (
                    ("first_sequence", first_sequence),
                    ("last_sequence", last_sequence),
                ):
                    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                        raise ValueError(f"observability.lost {field_name} must be a positive integer")
                if last_sequence < first_sequence:  # type: ignore[operator]
                    raise ValueError("observability.lost last_sequence must not precede first_sequence")
                for field_name in ("producer_name", "producer_instance_id"):
                    if not isinstance(self.payload.get(field_name), str) or not self.payload[field_name]:
                        raise ValueError(f"observability.lost {field_name} must be non-empty")
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
        elif self.kind == "agent_release.resolved" and self.subject_type != "agent_release":
            raise ValueError("agent release observation subject_type must be agent_release")
        elif self.kind.startswith("budget.") and (self.subject_type != "task" or self.subject_id != self.task_id):
            raise ValueError("budget observation subject must identify task_id")
        elif self.kind.startswith("operator.alert_") and self.subject_type != "alert":
            raise ValueError("Alert workflow observation subject_type must be alert")
        elif self.kind.startswith("operator.action_") and (self.subject_type != "task" or self.subject_id != self.task_id):
            raise ValueError("Operator action observation subject must identify task_id")
        elif self.kind == "scope.snapshotted":
            if self.subject_type != "scope":
                raise ValueError("scope observation subject_type must be scope")
            if self.payload is not None:
                from ansich.safety import ScopeDescriptor

                scope = ScopeDescriptor.model_validate(self.payload.get("scope"), strict=False)
                if scope.scope_id != self.subject_id:
                    raise ValueError("scope observation subject must identify payload scope")
        elif self.kind == "environment.sampled":
            if self.subject_type != "scope":
                raise ValueError("environment observation subject_type must be scope")
            if self.payload is None:
                raise ValueError("environment observation requires a payload")
            from ansich.environment import EnvironmentSamplePayload

            EnvironmentSamplePayload.model_validate(self.payload, strict=False)
        elif self.kind.startswith("authorization."):
            if self.subject_type != "authorization_snapshot":
                raise ValueError("authorization observation subject_type must be authorization_snapshot")
            if self.payload is not None:
                from ansich.safety import AuthorizationSnapshot

                snapshot = AuthorizationSnapshot.model_validate(self.payload.get("snapshot"), strict=False)
                if snapshot.snapshot_id != self.subject_id:
                    raise ValueError("authorization observation subject must identify payload snapshot")
                if self.kind != "authorization.evaluated":
                    expected_kind = f"authorization.{snapshot.decision}"
                    if self.kind != expected_kind:
                        raise ValueError("authorization observation kind does not match snapshot decision")
        elif self.kind.startswith("effect."):
            if self.subject_type != "effect":
                raise ValueError("effect observation subject_type must be effect")
            if self.payload is not None:
                from ansich.safety import ToolEffect

                effect = ToolEffect.model_validate(self.payload.get("effect"), strict=False)
                if effect.effect_id != self.subject_id:
                    raise ValueError("effect observation subject must identify payload effect")
                if self.kind != f"effect.{effect.phase}":
                    raise ValueError("effect observation kind does not match effect phase")
        elif self.kind == "evaluation.recorded":
            if self.subject_type not in {"task", "step", "tool_call", "content_block", "agent_release"}:
                raise ValueError("evaluation.recorded requires a task/step/tool_call/content_block/agent_release subject")
            if self.payload is not None:
                from ansich.evaluation import EvaluationRecord

                evaluation = EvaluationRecord.model_validate(self.payload.get("evaluation"), strict=False)
                if evaluation.subject_id != self.subject_id or evaluation.subject_type != self.subject_type:
                    raise ValueError("evaluation payload subject must match the Observation subject")
                if evaluation.task_id != self.task_id:
                    raise ValueError("evaluation payload task must match the Observation task")
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
        attributes: dict[str, object] | None = None,
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
        if attributes:
            reserved = {"source_kind", "source_id", "thread_id", "owner_id", "trigger_kind"}
            overlap = reserved.intersection(attributes)
            if overlap:
                raise ValueError("task lifecycle attributes cannot override reserved fields: " + ", ".join(sorted(overlap)))
            payload.update(attributes)
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
    def environment_sampled(
        cls,
        *,
        task_id: str,
        run_id: str,
        occurred_at: datetime,
        scope_id: str,
        payload: dict[str, object],
        source_event_id: str,
        producer_seq: int = 1,
        producer_name: str = "environment-probe",
        producer_version: str = "1",
        producer_instance_id: str = "local",
    ) -> Self:
        return cls(
            kind="environment.sampled",
            occurred_at=occurred_at,
            task_id=task_id,
            subject_type="scope",
            subject_id=scope_id,
            producer=Producer(name=producer_name, version=producer_version, instance_id=producer_instance_id),
            producer_seq=producer_seq,
            source_event_id=source_event_id,
            correlation_id=run_id,
            payload=payload,
        )

    @classmethod
    def scope_snapshotted(
        cls,
        *,
        task_id: str,
        run_id: str,
        occurred_at: datetime,
        scope_kind: str,
        external_ref: str,
        relation_role: str | None,
        source_event_id: str,
        parent_scope_id: str | None = None,
        producer_seq: int = 1,
        producer_name: str = "environment-probe",
        producer_version: str = "1",
        producer_instance_id: str = "local",
    ) -> Self:
        from ansich.safety import scope_display_label, scope_entity_id, scope_reference_hash

        ref_hash = scope_reference_hash(scope_kind, external_ref)  # type: ignore[arg-type]
        scope_id = scope_entity_id(scope_kind, ref_hash)  # type: ignore[arg-type]
        obs_id = new_id()
        payload: dict[str, object] = {
            "scope": {
                "scope_id": scope_id,
                "scope_kind": scope_kind,
                "external_ref_hash": ref_hash,
                "display_label": scope_display_label(scope_kind, external_ref),  # type: ignore[arg-type]
                "parent_scope_id": parent_scope_id,
                "created_obs_id": obs_id,
            }
        }
        if relation_role is not None:
            payload["relation_role"] = relation_role
        return cls(
            obs_id=obs_id,
            kind="scope.snapshotted",
            occurred_at=occurred_at,
            task_id=task_id,
            subject_type="scope",
            subject_id=scope_id,
            producer=Producer(name=producer_name, version=producer_version, instance_id=producer_instance_id),
            producer_seq=producer_seq,
            source_event_id=source_event_id,
            correlation_id=run_id,
            payload=payload,
        )

    @classmethod
    def observability_lost(
        cls,
        *,
        host_scope_id: str,
        occurred_at: datetime,
        first_sequence: int,
        last_sequence: int,
        lost_producer_name: str,
        lost_producer_instance_id: str,
        source_event_id: str,
        producer_seq: int = 1,
        producer_name: str = "ansich-collector",
        producer_version: str = "1",
        producer_instance_id: str = "local",
    ) -> Self:
        """One process-wide lost range, reported against the host ``Scope``.

        Two producer identities meet here and they are not the same thing. The
        **envelope's** producer is the collector reporting the loss; the
        ``lost_producer_*`` arguments are whoever's rows were charged, and they
        live in the payload beside the range — the same shape
        ``observability.degraded`` uses, so a reader of either kind reads one
        payload.

        ``correlation_id`` is the host Scope id: every bootstrap-subjected row
        this process writes correlates on the Scope it is about, which is the
        only durable identity available (there is no run and no Task).
        """

        return cls(
            kind="observability.lost",
            occurred_at=occurred_at,
            task_id=ANSICH_BOOTSTRAP_TASK_ID,
            subject_type="scope",
            subject_id=host_scope_id,
            producer=Producer(
                name=producer_name,
                version=producer_version,
                instance_id=producer_instance_id,
            ),
            producer_seq=producer_seq,
            source_event_id=source_event_id,
            correlation_id=host_scope_id,
            payload={
                "first_sequence": first_sequence,
                "last_sequence": last_sequence,
                "producer_name": lost_producer_name,
                "producer_instance_id": lost_producer_instance_id,
            },
        )

    @classmethod
    def agent_release_resolved(
        cls,
        *,
        task_id: str,
        run_id: str,
        occurred_at: datetime,
        release: object,
        source_event_id: str,
        producer_seq: int = 1,
        producer_name: str = "agent-release-probe",
        producer_version: str = "1",
        producer_instance_id: str = "local",
    ) -> Self:
        from ansich.release import AgentRelease, release_entity_id

        resolved = AgentRelease.model_validate(release)
        manifest = resolved.manifest
        return cls(
            kind="agent_release.resolved",
            occurred_at=occurred_at,
            task_id=task_id,
            subject_type="agent_release",
            subject_id=release_entity_id(
                manifest.namespace,
                manifest.agent_name,
                resolved.fingerprint.release_hash,
            ),
            producer=Producer(
                name=producer_name,
                version=producer_version,
                instance_id=producer_instance_id,
            ),
            producer_seq=producer_seq,
            source_event_id=source_event_id,
            correlation_id=run_id,
            payload={
                "relation_role": "executed_by",
                "release": resolved.model_dump(mode="json"),
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
    persisted_through: int | None = None
    lost_ranges: tuple[LostRange, ...] = ()
    timed_out: bool = False


class RebuildOutcome(BaseModel):
    """What one ``rebuild_projections()`` pass actually accomplished.

    ``replayed`` is the number of projection jobs the replay settled.

    ``unsettled`` is the honest half, and it exists because "this round found
    nothing to project" is **not** the same statement as "the rebuild is
    complete" (F10-26). Two things can leave work behind that the drain loop
    cannot see: a job waiting on a projection dependency is invisible to the
    claim for the length of its backoff, and a job another worker took over
    stopped being this replay's to settle. Both are counted here -- every
    projection or assessor job still ``pending``/``retry``/``processing`` when
    the pass returns -- so the caller can decide whether to run it again rather
    than reading a complete-looking count off an incomplete rebuild. ``failed``
    rows are deliberately not counted: they are settled, badly, and already
    surfaced through the failed-job count and its operator retry path.

    It is counted at the end of the *backend's* pass, which is before
    ``AnsichService.rebuild_projections`` runs its own final assessment sweep;
    that sweep can settle assessor jobs this number still counts, and can mint
    new ones it does not. So it is a lower bound on completeness taken at a
    known point, not a live gauge -- re-running the rebuild is what confirms an
    empty backlog.
    """

    model_config = ConfigDict(frozen=True)

    replayed: int
    unsettled: int


class LostRange(BaseModel):
    model_config = ConfigDict(frozen=True)

    first_sequence: int
    last_sequence: int
    task_id: str | None
    producer_name: str | None = None
    producer_instance_id: str | None = None


class ProducerHealth(BaseModel):
    model_config = ConfigDict(frozen=True)

    producer_name: str
    producer_instance_id: str
    accepted_count: int
    dropped_count: int
    last_accepted_sequence: int | None
    serialization_failures: int
    last_successful_flush_at: datetime | None


class WriterHealth(BaseModel):
    model_config = ConfigDict(frozen=True)

    consecutive_failures: int = 0
    backoff_until: datetime | None = None
    in_flight_count: int = 0
    poison_observation_count: int = 0


class ProjectorHealth(BaseModel):
    """One projector's job ledger as the database holds it (RB6).

    The four counts are the whole claimable/working/settled-badly split:
    ``pending`` is never-attempted work, ``retry`` is work a hard error re-armed
    (leaving it out would make re-armed jobs vanish from the health page while
    they are still owed), ``processing`` is leased, and ``failed`` is durably
    given up on. ``complete_through`` is a **continuity** mark, not a maximum:
    ``min(ingest_seq) - 1`` over this projector's unsettled jobs, so it names
    the last ingest sequence below which this projector has nothing outstanding.
    A single hole keeps it low no matter how far past the hole the projector has
    otherwise run -- that is the point. With nothing unsettled it is the highest
    ingest sequence the store holds, and ``None`` only when the store holds no
    Observations at all.

    It is computed on read rather than stored (RB6③): the spec asks for a
    maintained projector watermark, and a stored copy of a number this cheap to
    derive is a copy that drifts. The index ``ix_ansich_projection_jobs_projector_status``
    is what keeps the derivation bounded.
    """

    model_config = ConfigDict(frozen=True)

    projector_name: str
    projector_version: str
    pending: int = 0
    retry: int = 0
    processing: int = 0
    failed: int = 0
    complete_through: int | None = None


class DatabaseHealth(BaseModel):
    """Database-side projection truth, merged into ``GET /health`` at the route.

    Additive and separate from :class:`AnsichHealth` on purpose (RB7). Process
    health is answered synchronously under the collector's lock with zero IO --
    a database round trip inside that lock would put storage latency directly on
    the collection hot path -- so this block is produced by its own ``async``
    call and joined to the process block by the HTTP layer.

    ``status`` is the reachability of that call, nothing more. When it is
    ``unreachable`` every other field is at its default and the process-side
    block is still served in full: ``GET /health`` stays the one endpoint that
    reads while storage is down.

    ``failed_jobs`` is the **authoritative** failed-job count, read live from
    both job tables. ``AnsichHealth.failed_jobs`` keeps its name and its
    process-local, advisory meaning (a worker counts what it has seen fail, and
    other workers' failures are not in it).

    ``lag_ms`` is the age of the *oldest unsettled* job's Observation: the row
    at ``MIN(ingest_seq)`` over unsettled jobs, compared against now. It answers
    "how far behind is the backlog", not "how long ago did anything arrive".

    ``stale_completion_count`` is the one field here that is **not** database
    truth: it is the reporting worker's own count of writes dropped because the
    job had been taken over. It is ``None`` when unknown -- including whenever
    ``status`` is ``unreachable`` -- rather than a zero that would read as "no
    takeovers happened".
    """

    model_config = ConfigDict(frozen=True)

    status: Literal["reachable", "unreachable"]
    projectors: tuple[ProjectorHealth, ...] = ()
    lag_ms: int = 0
    failed_jobs: int = 0
    stale_completion_count: int | None = None


class AnsichHealth(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["starting", "healthy", "degraded", "recovering", "failed", "shutting_down", "stopped"]
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
    producers: tuple[ProducerHealth, ...] = ()
    writer: WriterHealth = WriterHealth()
    evicted_producer_count: int = 0
    unreported_global_lost_range_count: int = 0


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
