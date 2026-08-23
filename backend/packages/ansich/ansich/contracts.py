from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, Self, get_args
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
            # (F10-8, and the shape F10-29 closed the class with). A payload
            # over `inline_payload_max_bytes` is stored in `ansich_payloads` and
            # reads back as `payload_json IS NULL` plus a `payload_ref_id`;
            # `_observation_from_row` hands exactly that to this model. F10-29
            # swept the rest of this validator to the same shape — the
            # `environment.sampled` branch raised on the `None`, while
            # `task.heartbeat` and `budget.configured` fabricated a `{}` and
            # validated that — so every validating branch here now guards, and
            # no new one may join them.
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
        elif self.kind.startswith("operator.action_"):
            if self.subject_type == "scope":
                # RC8's Scope arm, and it is deliberately narrow. An operator
                # action that targets one Task keeps the Task subject it always
                # had; this admits the *process*-scoped family
                # (`OperatorAuditActionType`) — an active-version switch, an
                # audited raw-payload read of something no Task owns — whose
                # only honest subject is the host `Scope`.
                #
                # Two things are required together and neither is decorative.
                # The Task field must be the bootstrap sentinel, because a real
                # `task_id` beside a Scope subject would be a row claiming both
                # at once and no reader could tell which one it is about. And
                # the action type must be a member of the process-scoped family:
                # `interrupt`/`rollback` own an `ansich_operator_actions` row
                # keyed by a Task, so a Scope-subjected one would be an audit of
                # an action the ledger cannot hold.
                from ansich.operator import OperatorAuditActionType

                if self.task_id != ANSICH_BOOTSTRAP_TASK_ID:
                    raise ValueError("Scope-subjected operator action must carry the bootstrap Task sentinel")
                # Guarded on `payload is not None` like every other validating
                # branch in this method (F10-29): an externalized payload reads
                # back as `None` plus a `payload_ref_id`, and validating a
                # fabricated `{}` here would refuse a row that is merely large.
                if self.payload is not None and self.payload.get("action_type") not in get_args(OperatorAuditActionType):
                    raise ValueError("only a process-scoped operator action may subject a Scope")
            elif self.subject_type != "task" or self.subject_id != self.task_id:
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
            # F10-29 ①. This branch used to raise unconditionally on a `None`
            # payload, so an externalized environment sample could not be read
            # back at all: every public read that rebuilds an envelope from a
            # row (`list_observations`, `list_timeline`, alert evidence) blew up
            # on a sample that was merely large. Guarding costs nothing that was
            # worth keeping: the "requires a payload" rule it replaced is
            # already carried, for every kind, by the exactly-one-of
            # payload/payload_ref_id check at the end of this validator — so a
            # `None` here means externalized and nothing else, and the guard
            # skips validating a payload this envelope does not carry rather
            # than validating an empty one into a different verdict.
            if self.payload is not None:
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
        if self.kind == "task.heartbeat" and self.payload is not None:
            # Guarded like every other validating branch (F10-29). This one
            # read `self.payload or {}` and then raised on the fabricated empty
            # dict, so an externalized heartbeat could not be read back at all
            # — `environment.sampled`'s shape exactly. It was unreachable only
            # because a heartbeat payload is small, and "small enough not to
            # cross the threshold" is the argument that had held for
            # `environment.sampled` right up until it did not.
            payload = self.payload
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
        if self.kind == "budget.configured" and self.payload is not None:
            # Same guard, same reason as `task.heartbeat` above (F10-29): the
            # `or {}` fabricated a payload this envelope does not carry and
            # validated it into a refusal.
            payload = self.payload
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
    def raw_payload_read(
        cls,
        *,
        status: Literal["requested", "succeeded", "failed"],
        read_id: str,
        actor: str,
        target_kind: str,
        target_id: str,
        occurred_at: datetime,
        task_id: str,
        subject_type: Literal["task", "scope"],
        subject_id: str,
        purpose: str | None = None,
        request_correlation_id: str | None = None,
        outcome: str | None = None,
        http_status: int | None = None,
        served_byte_size: int | None = None,
        producer_name: str = "ansich-raw-read-audit",
        producer_version: str = "1",
        producer_instance_id: str = "gateway",
    ) -> Self:
        """One row of the §7 raw-read audit trail. **Never carries the body.**

        The payload is exactly spec:112's list — who read, which payload, why,
        which request, and when (the envelope's ``occurred_at``) — plus the
        outcome fields the terminal row adds. The bytes that were read are the
        one thing this must not contain, and the shape enforces it by having
        nowhere to put them: ``served_byte_size`` is a length, not content.

        **Two rows per read, keyed by one ``read_id``.** The
        ``requested`` row is written and committed *before* the store is asked
        for the body (RC9's audit-then-read), the terminal row after. Both keys
        carry the read id, which is fresh per request (H7-D), so the same actor
        reading the same payload twice produces two independent pairs rather
        than one deduped row — the producer dedupe is keyed on
        ``(producer, instance, source_event_id)`` and a deterministic
        ``(actor, payload)`` key would silently absorb the second read, which is
        the one an auditor most wants to see.

        **The subject follows the thing read** (RC8): the owning Task when the
        payload belongs to one, else the host ``Scope``, else — on a store with
        no minted Scope — the bootstrap sentinel, which states "this Observation
        has no Task entity" rather than pointing at an entity nobody made. The
        caller resolves it, because only the store knows.
        """

        from ansich.operator import RAW_PAYLOAD_READ_ACTION

        payload: dict[str, object] = {
            "action_type": RAW_PAYLOAD_READ_ACTION,
            "status": status,
            "read_id": read_id,
            "actor": actor,
            "target_kind": target_kind,
            "target_id": target_id,
            "purpose": purpose,
            "request_correlation_id": request_correlation_id,
        }
        if outcome is not None:
            payload["outcome"] = outcome
        if http_status is not None:
            payload["http_status"] = http_status
        if served_byte_size is not None:
            payload["served_byte_size"] = served_byte_size
        return cls(
            kind=f"operator.action_{status}",  # type: ignore[arg-type]
            occurred_at=occurred_at,
            recorded_at=occurred_at,
            task_id=task_id,
            subject_type=subject_type,
            subject_id=subject_id,
            producer=Producer(
                name=producer_name,
                version=producer_version,
                instance_id=producer_instance_id,
            ),
            # Unique per read *and* per row of the pair, so neither the
            # requested row nor its terminal can be absorbed as a duplicate.
            source_event_id=f"raw-read:{read_id}:{status}",
            # The read id, not the trace id: `correlation_id` is a canonical
            # identity field here and an inbound `X-Trace-Id` is caller-supplied
            # text of any shape. The request correlation the spec asks for rides
            # in the payload, where it can be recorded exactly as received.
            correlation_id=read_id,
            payload=payload,
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

    ``AnsichService.rebuild_until_settled`` is that re-running, written once so
    every caller that needs completeness rather than a report shares one bounded
    loop instead of open-coding its own.
    """

    model_config = ConfigDict(frozen=True)

    replayed: int
    unsettled: int


class RetryOutcome(BaseModel):
    """What one ``retry_failed_projections()`` pass actually accomplished.

    ``re_armed`` is the number of durably failed jobs the call put back in the
    queue -- rows the re-arm really changed, so a job a concurrent state change
    had already taken off the failed list is never counted.

    ``unsettled`` is the same honest half :class:`RebuildOutcome` carries, and
    it exists for the same reason: **a re-arm count is not a completion
    claim**. A re-armed job is claimed and projected afterwards, by whichever
    worker's loop gets to it, so "3 rows re-armed" says nothing about whether
    any of them has since settled -- and it says nothing at all about work that
    was already owed for other reasons. This number is every projection or
    assessor job still ``pending``/``retry``/``processing`` when the pass
    returns, read *after* the re-arm and after the replay it drives, so a job
    that was re-armed and immediately walked back into a dependency wait is
    counted rather than mistaken for a repair. ``failed`` rows are deliberately
    not counted, exactly as in ``RebuildOutcome``: they are settled, badly, and
    already surfaced through the failed-job count.

    It carries the same lower-bound caveat too. It is a count taken at one known
    point -- the end of this pass -- while other workers stay free to claim,
    settle and mint jobs, and the maintenance lock is released the moment the
    pass returns. So it is a bound on what was owed at a moment, not a live
    gauge, and a caller that needs "the failures are gone" re-reads the
    failed-job count rather than reading completion off either number here.
    """

    model_config = ConfigDict(frozen=True)

    re_armed: int
    unsettled: int


class RetentionPolicy(BaseModel):
    """The four numbers one retention pass runs under.

    A framework-independent restatement of ``AnsichRetentionConfig`` — the same
    four fields with the same bounds and the same containment rule — so this
    package's ``run_retention`` boundary can name what it takes without
    importing DeerFlow's configuration layer. The adapter converts once
    (``deerflow.ansich.retention_policy_from_config``); nothing here reads
    configuration.

    It is passed **per pass** rather than held on the backend on purpose. The
    configuration is startup-only, but a retention pass is a deliberate
    operation whose policy is worth recording *as it ran* — which is exactly
    what :meth:`snapshot` produces and what the retention state row's
    ``last_run_policy`` column stores, so an operator reading an expired row
    later can tell which rule expired it rather than inferring it from a
    configuration that may since have been retuned.
    """

    model_config = ConfigDict(frozen=True)

    raw_payload_days: int = Field(ge=1)
    observation_days: int = Field(ge=1)
    structural_days: int = Field(ge=1)
    cleanup_batch_size: int = Field(ge=1)

    @model_validator(mode="after")
    def _validate_tier_containment(self) -> Self:
        # The same two comparisons the configuration model makes, restated
        # rather than delegated, because this type is reachable without that
        # model (a test, a future operator route) and an inverted pair is not a
        # stricter policy — it is a broken store.
        if self.raw_payload_days > self.observation_days:
            raise ValueError("raw_payload_days must not exceed observation_days")
        if self.observation_days > self.structural_days:
            raise ValueError("observation_days must not exceed structural_days")
        return self

    def snapshot(self) -> dict[str, int]:
        """The policy as it is written into ``last_run_policy``.

        **This shape is the contract** — Task 9 is its first writer, so what it
        serialises is what every later reader may assume. It is a flat mapping
        of the four field names to their integer values, and deliberately
        nothing else: no timestamp (the row carries ``last_run_started_at`` and
        ``last_run_finished_at`` beside it, and duplicating a clock into a
        policy record invites the two to disagree), no derived cutoffs (they
        are a function of the policy and the run's ``now``, so storing them
        would freeze one reading of a value that is already recoverable), and
        no schema version (a flat mapping of named integers has no shape to
        migrate; a reader that finds an unknown key ignores it and one that
        misses a known key reports it unknown, which is the same discipline
        every other read model here follows).
        """

        return {
            "raw_payload_days": self.raw_payload_days,
            "observation_days": self.observation_days,
            "structural_days": self.structural_days,
            "cleanup_batch_size": self.cleanup_batch_size,
        }

    def payload_policy_label(self) -> str:
        """The stamp written onto a payload tombstone's ``policy`` column.

        Short enough for ``String(128)`` and readable without a decoder ring:
        it names the rule that made the tombstone, not the whole policy, so an
        operator reading an expired row is told which of the three tiers
        deleted it and at what threshold.
        """

        return f"raw_payload_days={self.raw_payload_days}"


class RetentionLastRun(BaseModel):
    """When retention last ran, under which policy, and where it has reached.

    The whole model is ``None`` when retention has **never run** — that is the
    Constraint 2 half, and it is why this is a nested optional block rather than
    four nullable fields on the health block: "no pass has ever happened" is one
    fact, and spelling it as four separate ``None``s invites a consumer to
    render three of them and miss the fourth.

    Within a real run the fields are ``None`` for their own reasons.
    ``finished_at`` is ``None`` for a pass that started and did not finish,
    which is a genuine state (a crash, a kill, a deploy mid-sweep) and must not
    be collapsed into "never run"; ``policy`` is ``None`` only for a run written
    by something that recorded none.

    ``observation_horizon_ingest_seq`` is not a per-run number: it is the
    store's durable claim about how far Observation deletion has *completed*,
    carried here because the only place an operator asks the question is beside
    the last run that could have moved it. ``0`` is honest and means "nothing
    deleted yet" — ``ingest_seq`` starts at 1.
    """

    model_config = ConfigDict(frozen=True)

    started_at: datetime
    finished_at: datetime | None = None
    policy: dict[str, object] | None = None
    observation_horizon_ingest_seq: int = Field(default=0, ge=0)


class RetentionReport(BaseModel):
    """What one ``run_retention`` pass actually did.

    Counts are per-pass, never cumulative: a pass reports what *it* deleted, and
    the durable record of where retention has reached is the retention state
    row (its cursors and its horizon), not a number added up across passes.

    ``payload_tombstoned`` counts payload **bodies** replaced by a tombstone,
    not rows removed — tier 1 never deletes an ``ansich_payloads`` row, because
    the row is what keeps "expired by policy" distinguishable from "missing,
    which is corruption".

    ``observations_deleted`` and ``structural_deleted`` are ``int | None``, and
    the ``None`` is load-bearing rather than defensive: it means *that tier did
    not run in this pass*, which is a different statement from "it ran and
    deleted nothing". Reporting an unexecuted tier as ``0`` would be the
    None-never-0 mistake in its most expensive form — an operator reading a
    clean zero for a tier that never executed has been told the store is
    smaller than it is. There is now exactly one way to reach that state:
    ``max_batches`` was spent before the pass got to that tier. Running a tier
    with a budget of zero would spin a loop that commits nothing and report
    ``0``, which is the same mistake wearing a day's work.

    ``batches`` counts committed batches across every tier that ran, which is
    also the number of times the durable cursor advanced. ``resumed_from_cursor``
    says this pass began from a cursor an earlier interrupted pass left behind,
    so a short report is legible as "picking up" rather than as "nothing to do".

    ``finished`` is the completeness claim and it is deliberately weak: it is
    true only when every tier that ran walked its whole candidate set to the
    end. A pass cut short by an error, or one that stopped on a batch boundary
    it could not pass, reports ``False`` and the cursor says where to resume.

    **``finished`` is not "the store is fully expired", and under cross-pass
    convergence a caller re-runs regardless.** The Observation tier stops at the
    first row a structural row still pins, which is the end of what *it* can do
    this pass, so it reports ``True`` — while the structural tier, running after
    it, may have just unpinned exactly that row for the next pass. A scheduler
    that stopped on ``finished`` would therefore stop one pass early, every
    time. The field answers "did the batch bound cut this pass short"; whether
    more remains is answered by running again and reading the counts.

    ``observation_horizon_ingest_seq`` is the horizon as it stood when the pass
    returned. ``0`` is honest here and not a missing value: ``ingest_seq``
    starts at 1, so zero means no Observation-tier deletion has ever completed.
    """

    model_config = ConfigDict(frozen=True)

    payload_tombstoned: int = Field(ge=0)
    observations_deleted: int | None = Field(default=None, ge=0)
    structural_deleted: int | None = Field(default=None, ge=0)
    batches: int = Field(ge=0)
    resumed_from_cursor: bool
    finished: bool
    started_at: datetime
    finished_at: datetime
    observation_horizon_ingest_seq: int = Field(ge=0)


class HardDeleteReport(BaseModel):
    """What one owner/thread hard delete erased (spec §6 D6-2).

    Every count is **rows this call actually deleted**, never rows it found: a
    resumed run reports only its own half, and adding two runs' reports gives
    the whole erasure. The families are the ones D6-2 names, so an operator can
    read the answer to "what went" without knowing the schema.

    ``tasks`` counts ``ansich_tasks`` rows — the subtree the Scope resolved to,
    the number a person recognises. ``observations`` counts Observation rows,
    which is the volume figure. ``payloads`` counts ``ansich_payloads`` rows
    **deleted outright** — not tombstoned: this path owns the rows it orphans
    (the last-referrer-deleter obligation) and a tombstone here would leave
    lineage nothing can ever query. ``relations`` and ``read_models`` are called
    out of the general projection total because they are the two families a
    reader most often wants to confirm went: the graph edges that made the
    Scope's membership queryable, and the active-Task read model rows whose
    survival would be the PB7 failure.

    ``projections`` is **every other deleted row**, summed across every table
    the cascade reached — Entities, Steps, ToolCalls, content blocks and blobs,
    heartbeats, budgets, usage contributions, jobs, alerts. One number rather
    than a per-table map on purpose: the per-table breakdown is a fact about the
    schema at one revision, and an operator acting on this report is asking "did
    the derived world go too", which one total answers.

    ``audit_refs`` counts the §7 raw-read audit Observations
    (``operator.action_*``) that went with the deleted Tasks, and it is
    deliberately a **subset of** ``observations`` rather than a disjoint family.
    It is reported separately because *whether* those rows go is a ruling rather
    than a mechanism: an audit of reading this owner's payloads is itself a
    record about this owner, so privacy deletion takes it, while audit rows
    about other subjects — the ones subjected to the host ``Scope`` — are
    untouched. Double counting is the honest shape here: the rows really are
    Observations, and a reader who wants the non-audit total subtracts.

    ``batches`` counts committed transactions that deleted something, which is
    also the number of points at which an interrupted run could have stopped.
    A hard delete has no batch bound and no ``finished`` field: it runs to
    completion or raises :class:`~ansich.errors.HardDeleteError`, because a
    half-finished erasure that reported success would be the one failure mode
    this operation cannot have.
    """

    model_config = ConfigDict(frozen=True)

    tasks: int = Field(ge=0)
    observations: int = Field(ge=0)
    payloads: int = Field(ge=0)
    projections: int = Field(ge=0)
    relations: int = Field(ge=0)
    read_models: int = Field(ge=0)
    audit_refs: int = Field(ge=0)
    batches: int = Field(ge=0)


class LeaseSweepReport(BaseModel):
    """What the startup lease sweep moved out of ``processing`` (D8-2, RC12).

    A row left ``processing`` by a process that died still carries a lease
    nobody will renew. The claim path already handles it — an expired lease is
    claimable, which is the correctness backstop — so this sweep buys
    *legibility*, not safety: without it health keeps reporting phantom
    ``processing`` jobs for work no worker holds.

    The bucket a row lands in is its honest one and is decided by
    ``attempts``: a row that has been attempted goes to ``retry``, a row that
    has not goes to ``pending``. That is Global Constraint 7 (``pending ⟺
    attempts == 0``) obeyed rather than restated, which is why the sweep
    **touches neither ``attempts`` nor ``lease_generation``**. Leaving the
    generation alone is deliberate and has one consequence worth naming: a
    zombie worker still inside its own projection can complete a row this
    sweep re-armed, because its compare-and-set still matches. That write is
    the work it really did, and if any *live* worker claims the row first the
    generation moves and the zombie's write is dropped as usual — so the
    ordinary CAS covers the case and re-arming without a bump is safe.

    ``to_retry`` / ``to_pending`` count rows the sweep's UPDATE **moved**, not
    rows its SELECT chose. The two differ because the read takes no lock and
    the write therefore re-checks the lease cutoff the read used: a peer that
    claimed one of those rows in between has moved its expiry past the cutoff
    and is declined, which is what keeps a sweep from re-arming a *live*
    worker's fresh claim — a claim leaves the row ``processing``, so status
    alone cannot tell the two apart. This report is one lower in that case
    rather than claiming a re-arm that did not happen.

    ``truncated`` is the bound saying so out loud: the sweep reads at most
    ``limit`` rows per table so startup cannot turn into a full scan of a table
    with no retention. A truncated sweep is not a failure — the claim path
    re-arms whatever is left lazily — but a reader must not take the counts as
    "all of them", so the flag is carried rather than inferred from a count
    equal to the limit.
    """

    model_config = ConfigDict(frozen=True)

    to_retry: int = Field(default=0, ge=0)
    to_pending: int = Field(default=0, ge=0)
    truncated: bool = False


class ShutdownStep(BaseModel):
    """One step of the bounded shutdown sequence, and how it ended (spec §8).

    Every step is recorded whatever happened to it, because the report is the
    only account of a shutdown anybody gets: the process is on its way out, so
    a step that is merely *absent* from a report is indistinguishable from one
    that was never reached.

    ``ok`` and ``timed_out`` are two facts, not one negated: a step can end
    ``ok=False`` without a timeout (it ran and reported something unfinished),
    and every timeout is also not-ok. ``duration_ms`` is what the step actually
    cost, including a timeout's own budget, so the durations sum to roughly
    ``ShutdownReport.total_ms``.

    ``detail`` is a short machine-ish string naming what was left behind
    (``"queued=12"``, ``"outstanding_barriers=1"``) or ``None`` when there is
    nothing to add. It is deliberately not a free-text sentence: it is read out
    of a log line at 3am beside six of its siblings.
    """

    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1)
    ok: bool
    timed_out: bool = False
    duration_ms: int = Field(ge=0)
    detail: str | None = None


class ShutdownReport(BaseModel):
    """The whole of what ``AnsichService.stop()`` did, step by step (spec §8).

    Spec §8 asks for seven ordered shutdown steps, each with its own timeout
    and its own health/log result, and a total inside the Gateway's graceful
    shutdown budget. This model is that result. It is **not** a lifecycle
    status: ``ansich.lifecycle``'s seven states and their 17-edge clamp are a
    merge gate, and adding a phase vocabulary there to describe shutdown
    internals would spend a proven invariant on wording (ruling H8-A). A
    shutdown phase lives here, where it can be as detailed as it likes and
    nothing derives a status from it.

    ``completed`` means every step reported ``ok``. It is deliberately not
    "the budget was not exhausted": a step can finish inside its budget and
    still leave work behind (a barrier still outstanding, a range still in the
    bucket), and a shutdown that left something behind must not read as clean.

    ``budget_ms`` is the whole budget the sequence was given, not the sum of
    the per-step slices, so a reader can see how much of it ``total_ms``
    spent.
    """

    model_config = ConfigDict(frozen=True)

    steps: tuple[ShutdownStep, ...] = ()
    total_ms: int = Field(ge=0)
    budget_ms: int = Field(ge=0)
    completed: bool


class ReplaySelector(BaseModel):
    """Which Observations a replay aims at — the three filters, and nothing else.

    A selector never names a projector: it describes a *slice of history*, and
    the same slice is legal for any target. The three filters compose (all
    given ones must hold) and each is chosen so an index serves it:

    * ``task_id`` — served by ``ix_ansich_observations_task_ingest``.
    * ``occurred_from`` / ``occurred_to`` — an **event-time** window, served by
      ``ix_ansich_observations_kind_occurred`` once the caller pairs it with
      the target projector's kind list. ``recorded_at`` is deliberately *not*
      offered: that column carries no index, so the same window over it is a
      full scan of a table that only grows.
    * ``ingest_from`` / ``ingest_to`` — a primary-key range.

    Both halves of each range are required together. A one-sided window is
    almost always a typo for a two-sided one, and the open side is precisely
    where an operator does not want to discover they replayed the whole store.

    An all-``None`` selector is legal and means *everything the target claims*;
    :attr:`is_unfiltered` says so, because "delete every affected read-model
    row" and "delete the affected ones" are different statements and the
    executor has to be able to tell.
    """

    model_config = ConfigDict(frozen=True)

    task_id: str | None = None
    occurred_from: datetime | None = None
    occurred_to: datetime | None = None
    ingest_from: int | None = Field(default=None, ge=1)
    ingest_to: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _ranges_are_two_sided_and_ordered(self) -> Self:
        if (self.occurred_from is None) != (self.occurred_to is None):
            raise ValueError("Ansich replay time filter needs both occurred_from and occurred_to")
        if self.occurred_from is not None and self.occurred_to is not None and self.occurred_from > self.occurred_to:
            raise ValueError("Ansich replay time filter starts after it ends")
        if (self.ingest_from is None) != (self.ingest_to is None):
            raise ValueError("Ansich replay ingest filter needs both ingest_from and ingest_to")
        if self.ingest_from is not None and self.ingest_to is not None and self.ingest_from > self.ingest_to:
            raise ValueError("Ansich replay ingest filter starts after it ends")
        return self

    @property
    def is_unfiltered(self) -> bool:
        """True when this selector narrows nothing at all."""

        return self.task_id is None and self.occurred_from is None and self.ingest_from is None

    @property
    def has_time_filter(self) -> bool:
        return self.occurred_from is not None


class ReplayReport(BaseModel):
    """What one replay pass targeted, changed, and can honestly claim.

    Every field is a count of something the pass *observed*, and two of them
    are deliberately allowed to be ``None`` rather than zero.

    ``targeted`` is the number of Observations in the target set, and it always
    equals ``minted + re_pended``: an Observation the target has no job for is
    minted one, an Observation that already has one is re-pended, and there is
    no third case. ``minted`` is zero for a projector that claims no kinds
    (``task-spawn-reconcile``), which is not a defect — its jobs are enqueued
    by another projector's transaction, never fanned out by kind, so a replay
    of it re-pends what exists and invents nothing.

    ``replayed`` is the number of jobs the drive loop settled, and it is
    **store-wide, not target-scoped**. The loop drains the claim queue, and the
    claim knows nothing about this replay's filters: a job another producer
    minted while the loop ran is claimed by it like any other. So
    ``replayed > targeted`` is ordinary rather than suspicious, and the
    difference is the honest signal that the store moved underneath the pass —
    the alternative, silently counting only the targeted subset, would let a
    concurrently ingested Observation be absorbed with nothing said.

    **``settled`` is doing exact work in that sentence: it counts jobs that were
    settled, not projections that were written.** A job whose Observation's
    payload expired under the retention policy is settled without projecting
    anything (the tombstone's lineage is recorded on the job; see
    ``sql.py::_settle_expired_evidence_job``), and it is counted here like any
    other. So on a store old enough to have run retention, ``replayed`` is a
    count of work the loop *finished*, and some of that work honestly produced
    no rows. A caller reading it as "rows re-derived" will over-read a replay
    over expired evidence.

    Counting them is the right choice and the reason is mechanical rather than
    semantic: the drive loop — like ``_rebuild_projections_locked``'s — exits
    the round when ``project_pending`` returns **zero**. A round consisting only
    of expired settles would therefore end the drain early with claimable work
    still queued behind it, and a store holding many such jobs could spend the
    whole round budget without converging. (What it would *not* do is leave
    ``unsettled`` non-zero forever: that is a live query over the job tables and
    the rows really are ``completed`` either way — worth stating because it is
    the plausible-sounding wrong reason for the same decision.)

    ``unsettled`` carries the same meaning and the same lower-bound caveat as
    :class:`RebuildOutcome`'s: every projection or assessor job still
    ``pending``/``retry``/``processing`` at the end of the last round, counted
    at one known point rather than watched. A non-zero value after the round
    budget is spent is **reported, not raised**.

    ``failed`` is the number of **durably failed** projection jobs for the
    target ``(projector, version)``, and it exists because ``unsettled`` cannot
    see them: a failed job is settled, badly, so a pass can report
    ``unsettled == 0`` and still have left projections that never landed. It is
    the one number a script has to read beside ``unsettled`` before calling a
    replay clean. It is scoped to the projector but **not** to the selector, so
    a filtered replay also counts failures outside its own target set — a
    durable failure anywhere in the projector is worth saying, but the number is
    not always this pass's own doing.

    ``digest`` is ``None`` in exactly three situations, and none of them is an
    error the caller can fix by retrying:

    * ``unsettled > 0`` — a digest over a store that still owes work describes
      a state nobody asked for and would compare unequal against the same
      history replayed to completion. Refusing to compute it is the point.
    * ``failed > 0`` — the same principle for the one state in which owned rows
      are *known* never to have been written.
    * the target projector exclusively owns no read-model table, so there is
      nothing to hash that the projector alone wrote (see
      ``_PROJECTOR_OWNED_TABLES``). Hashing the empty set would make every such
      replay "reproducible" by construction.

    Because of the third case, **a missing digest is not by itself an incomplete
    pass**: three projectors honestly have none, and treating that as a failure
    would page an operator for a clean replay. ``unsettled`` and ``failed`` are
    what say whether work is owed.

    ``watermark`` is the store-wide projection continuity mark after the pass
    (``min`` over the per-projector ``complete_through``), or ``None`` when the
    store holds no Observations at all. It is not a per-target number.

    ``errors`` is the free-text channel for everything above that has to be
    said in words: a round budget spent with work still owed, durably failed
    jobs found for the target, a digest that was not computed and why. It is
    prose for a human and is never parsed.
    """

    model_config = ConfigDict(frozen=True)

    projector_name: str
    projector_version: str
    targeted: int
    minted: int
    re_pended: int
    replayed: int
    unsettled: int
    failed: int = 0
    errors: tuple[str, ...] = ()
    watermark: int | None = None
    digest: str | None = None
    dry_run: bool


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
    derive is a copy that drifts. What keeps the derivation bounded is that both
    reads behind it filter to the unsettled statuses, so they touch the backlog
    rather than the history -- see ``sql.py::_projector_status_counts_statement``
    for the measurement and the index that actually serves it.
    """

    model_config = ConfigDict(frozen=True)

    projector_name: str
    projector_version: str
    pending: int = 0
    retry: int = 0
    processing: int = 0
    failed: int = 0
    complete_through: int | None = None


#: Where one component's running version came from, and how well the switch is
#: evidenced. One enum rather than two fields because the four values are the
#: four rows of ``AnsichActiveVersionRow``'s latch contract plus the absent-row
#: case, and splitting them into "origin" and "audit status" would invite the
#: combination the schema's CHECK forbids (evidence on a row nobody activated).
#:
#: * ``code_default`` — no row. The build's own default is what runs, and that
#:   is a complete answer rather than a missing one: the table records
#:   *deviations*. Nothing was activated, so nothing is owed an audit.
#: * ``activated_audited`` — a row, its audit Observation still in the store.
#: * ``activated_expired`` — a row whose audit Observation existed and has since
#:   aged out under retention (the FK's ``ON DELETE SET NULL`` fired, the latch
#:   survived). The selection is intact; only the evidence pointer is gone.
#: * ``activated_unaudited`` — a row written while the audit write was degraded,
#:   so no Observation was ever recorded for it. This is the one value that
#:   should prompt a question, and it is why the latch exists: without it this
#:   state and ``activated_expired`` are the same NULL.
ActiveVersionOrigin = Literal[
    "code_default",
    "activated_audited",
    "activated_expired",
    "activated_unaudited",
]


class ActiveVersion(BaseModel):
    """Which version of one versioned component this store says is authoritative.

    Reported for **every** component the build knows, not only the ones with a
    row: a component with no row is reported at its ``code_default_version``
    with ``origin="code_default"``. Omitting it would make an operator infer the
    default from its absence, and an absent entry is exactly what an unreadable
    block looks like — the same conflation ``None``-never-zero exists to
    prevent one level up.

    ``active_version`` and ``code_default_version`` are both carried because
    "what runs" and "what would run untouched" are different questions and an
    operator reading a switch needs both. They are legitimately equal: an
    operator may activate the version that is already the default, which leaves
    a row (and an audit trail) saying so.

    ``activated_at`` / ``activated_by`` / ``audit_obs_id`` are ``None`` for a
    code default because nobody activated it — never epoch-zero, never an empty
    string. On an activated row ``audit_obs_id`` may still be ``None``, and
    :data:`ActiveVersionOrigin` is what says which of the two reasons applies.
    """

    model_config = ConfigDict(frozen=True)

    component_kind: Literal["projector", "resolver"]
    component_name: str
    active_version: str
    code_default_version: str
    origin: ActiveVersionOrigin
    activated_at: datetime | None = None
    activated_by: str | None = None
    audit_obs_id: str | None = None


class ActiveVersionMismatch(BaseModel):
    """One active-version row this build can no longer honour.

    Produced by ``validate_active_versions()`` at ``start()`` and **never
    raised**: a row naming a version this build does not know is a deployment
    fact, not a corrupt store, and the reader it affects already has an honest
    fallback (the code default). Crashing the process over it would turn a
    degraded-but-working deployment into an outage, so the helper reports and
    the caller decides.

    ``reason`` reuses :data:`~ansich.errors.ActiveVersionRefusal`'s vocabulary
    on purpose: the same three questions the writer asked are the ones a later
    start re-asks, and the answers mean the same thing. What changed between
    the two moments is the *build*, not the request — a row that was legal when
    written is a mismatch after a rollback — which is why validating once at
    the write is not enough.

    **What a mismatch is not, and must not be read as.** Every reason here is a
    statement about whether this build *knows* the version. A version this
    build knows perfectly well can still be **degraded at runtime** against the
    evidence a particular store holds — ``ansich-default@1.0.0`` cannot rank a
    ``soft_human`` assertion at all, so on a store that has any, it resolves
    nothing and the read falls back to the code default. That row is *not*
    reported here, and deliberately so: a startup scan for "does the store
    contain a class this ladder cannot rank" answers a question that goes stale
    the moment the next such assertion is written, so a clean answer would be a
    promise nobody can keep, and calling it a "mismatch" would conflate "this
    build does not know the version" with "this version is lossy on this data".
    The runtime condition is handled where it can be handled honestly — at the
    read, which falls back and says so in a rate-limited log naming the active
    version — and it is visible up front through the CLI's caveat on the
    versions listing and on the activation itself. An empty tuple here means
    "every row names something this build can execute", nothing more.
    """

    model_config = ConfigDict(frozen=True)

    component_kind: str
    component_name: str
    active_version: str
    reason: Literal["unknown_component_kind", "unknown_component", "unknown_version"]


class DatabaseHealth(BaseModel):
    """Database-side projection truth, merged into ``GET /health`` at the route.

    Additive and separate from :class:`AnsichHealth` on purpose (RB7). Process
    health is answered synchronously under the collector's lock with zero IO --
    a database round trip inside that lock would put storage latency directly on
    the collection hot path -- so this block is produced by its own ``async``
    call and joined to the process block by the HTTP layer.

    ``status`` is the reachability of that call, nothing more, and it is the
    field every other one is conditional on: when it is ``unreachable`` the
    projector rows are empty and every number is ``None``, because a block that
    could not be read must not render as "0ms behind, 0 failed jobs" to a
    consumer that forgot to branch. ``None`` means unknown here and nowhere
    means zero. The process-side block is still served in full either way:
    ``GET /health`` stays the one endpoint that reads while storage is down.

    ``failed_jobs`` is the **authoritative** failed-job count, read live from
    both job tables. ``AnsichHealth.failed_jobs`` keeps its name and its
    process-local, advisory meaning (a worker counts what it has seen fail, and
    other workers' failures are not in it).

    ``lag_ms`` is the age of the *oldest unsettled* job's Observation: the row
    at ``MIN(ingest_seq)`` over unsettled jobs, compared against now. It answers
    "how far behind is the backlog", not "how long ago did anything arrive".

    ``stale_completion_count`` is the one field here that is **not** database
    truth: it is the reporting worker's own count of writes dropped because the
    job had been taken over.

    ``retention_last_run`` is the one field here whose ``None`` means something
    **other** than "unknown". A reachable store with no retention pass in its
    history answers ``None`` because there is nothing to report -- retention is
    driven by a caller, not by the store, and a store nobody has ever swept is
    a normal store rather than an unreadable one (Global Constraint 2: never
    epoch-zero, never a fabricated "0 deleted"). An ``unreachable`` block also
    answers ``None``, so the two states are not distinguishable from this field
    alone; ``status`` is what tells them apart, exactly as it does for the
    numbers. Rendering it as "retention has never run" without checking
    ``status`` first would report an outage as a configuration.

    ``active_versions`` follows the same ``None``-means-unknown rule as the
    numbers, and it is the field where the distinction is easiest to get wrong:
    an **empty tuple is impossible**, because a reachable store always reports
    one entry per component the build knows (a component with no row is
    reported at its code default). So ``None`` is "nobody could read this" and
    a list is the whole answer; there is no third state where the block is
    readable and the list is legitimately empty, and a consumer that renders
    ``None`` as "no versions" is reporting an outage as a configuration.
    """

    model_config = ConfigDict(frozen=True)

    status: Literal["reachable", "unreachable"]
    projectors: tuple[ProjectorHealth, ...] = ()
    lag_ms: int | None = None
    failed_jobs: int | None = None
    stale_completion_count: int | None = None
    active_versions: tuple[ActiveVersion, ...] | None = None
    retention_last_run: RetentionLastRun | None = None


class AnsichHealth(BaseModel):
    """This process's own collection health, answered with zero IO.

    ``active_version_mismatches`` is the one field here that is not about
    collection at all: it is what ``start()``'s active-version validation (T6's
    ``validate_active_versions``) saw. ``None`` means the rows were not read —
    a backend that cannot answer, or a service that has not started — and an
    empty tuple means they were read and every one of them names something this
    build can execute. Never-zero applies as everywhere else: an unreadable
    store must not render as a clean deployment.

    **Why a field and not a status.** A mismatch is a fact about the
    *deployment* (a row naming a version this build was rolled back past), not
    about the collector, which is collecting perfectly well; every reader it
    affects already falls back to the code default. Routing it into
    ``status`` would mean a new ``LifecycleInputs`` signal and a new legal edge
    in ``lifecycle.LEGAL_TRANSITIONS``, whose *illegal complement* is a pinned
    merge gate — spending a proven invariant to carry a deployment note. So it
    is carried beside the status, visible in the same read, and it is
    accompanied by a typed startup WARNING rather than by a crash (Constraint
    1: fail-open).
    """

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
    active_version_mismatches: tuple[ActiveVersionMismatch, ...] | None = None


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
