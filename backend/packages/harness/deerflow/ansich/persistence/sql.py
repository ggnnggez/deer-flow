from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Literal, NamedTuple, cast
from uuid import uuid4

from ansich import (
    ContentBlockPayloadView,
    ContentBlockView,
    ContentDerivationView,
    ContentOccurrenceView,
    ContentProducerView,
    ContextCompressionItemView,
    ContextCompressionSummaryView,
    ContextCompressionView,
    ContextSnapshotItemView,
    ContextSnapshotView,
    ContextStateDelta,
    ContextStateItem,
    ContextStateView,
    ControlBelief,
    LlmAttemptView,
    NamedVersion,
    ObservationEnvelope,
    PossibleExposureItemView,
    Producer,
    RebuildOutcome,
    StepView,
    TaskScopesView,
    TaskScopeView,
    TaskView,
    ToolAuthorizationView,
    ToolBelief,
    ToolCallView,
    ToolEffect,
    ToolEffectsView,
    ToolResultView,
    new_id,
    scope_display_label,
    scope_entity_id,
    scope_reference_hash,
)
from ansich.alerts.episodes import (
    AlertCondition,
    AlertEpisode,
    AlertReconciliation,
    acknowledge_alert,
    alert_conditions_from_assessment,
    dismiss_alert,
    reconcile_alert_conditions,
    resolve_alert_episode,
)
from ansich.alerts.views import (
    AlertDetailView,
    AlertSummaryView,
    AlertWorkflowEventView,
    BeliefAssertionView,
)
from ansich.assessment.absolute_limit import (
    ABSOLUTE_LIMIT_ASSESSOR,
    AbsoluteLimitAssessmentResult,
    assess_absolute_limits,
)
from ansich.assessment.action_repetition import (
    ACTION_REPETITION_ASSESSOR,
    ToolAction,
    assess_action_repetition,
    build_step_action,
)
from ansich.assessment.base import Assessment, AssessorDescriptor, AuthorityClass, EvidenceRef, canonical_config_hash
from ansich.assessment.configuration_drift import (
    CONFIGURATION_DRIFT_ASSESSOR,
    assess_configuration_drift,
)
from ansich.assessment.scope_safety import (
    SCOPE_SAFETY_ASSESSOR,
    ScopeSafetyAssessmentResult,
    assess_scope_safety,
)
from ansich.assessment.tool_frequency import (
    TOOL_FREQUENCY_ASSESSOR,
    ToolOccurrence,
    assess_tool_frequency,
)
from ansich.belief.resolver import (
    DEFAULT_RESOLVER,
    BeliefAssertion,
    resolve_current_belief,
)
from ansich.budget import (
    BudgetHealthBelief,
    BudgetSourceKind,
    TaskBudgetsView,
    TaskBudgetView,
    WallTimeEvidenceRow,
    assess_budget_health,
    order_wall_time_evidence,
)
from ansich.compression import CompressionDisposition
from ansich.context_state import context_state_hash, materialize_context_state
from ansich.contracts import (
    ControlValue,
    LostRange,
    TaskLifecycleScope,
    UsageDimension,
    control_values_for_lifecycle_scope,
)
from ansich.control import should_select_control_candidate
from ansich.environment import (
    LEAK_ELIGIBLE_ENVIRONMENT_SCOPES,
    PRESSURE_RULED_METRICS,
    EnvironmentAlertSummaryView,
    EnvironmentBeliefView,
    EnvironmentHistoryPoint,
    EnvironmentHistoryView,
    EnvironmentMetricView,
    EnvironmentScopeView,
    EnvironmentThresholds,
    TaskEnvironmentView,
    TaskToolEnvSamplesView,
    ToolEnvironmentSampleView,
    ToolEnvSampleView,
    assess_environment_leak,
    assess_environment_pressure,
)
from ansich.evaluation import (
    EVALUATION_OBSERVATION_KIND,
    EvaluationProjectionStatus,
    EvaluationRecord,
    EvaluationView,
    QualityBeliefView,
)
from ansich.heartbeat import TaskHeartbeatView
from ansich.jobs import FailedJobDetailView, FailedJobErrorView, FailedJobKind, FailedJobSummaryView
from ansich.lineage import LineageDirection
from ansich.operations import (
    ActiveStepView,
    ActiveTaskView,
    ActiveToolView,
    DwellBelief,
    HeartbeatBelief,
    assess_dwell,
    assess_heartbeat,
)
from ansich.operator import OperatorActionView, TaskActionTarget
from ansich.quality import ReleaseQualityDimensionView, ReleaseQualityView
from ansich.release import (
    AgentRelease,
    AgentReleaseDetailView,
    AgentReleaseManifest,
    AgentReleaseSummaryView,
    TaskAgentReleaseView,
    release_entity_id,
    validate_agent_release,
)
from ansich.release.canonical import canonical_json_bytes
from ansich.safety import AuthorizationPermission, AuthorizationSnapshot, ScopeDescriptor
from ansich.task_tree import TaskSpawnView, TaskTreeDirection
from ansich.tool import ContentDerivationSourceRole, ToolTransformKind
from ansich.usage import (
    HIGH_WATER_USAGE_KINDS,
    LLM_TOKEN_USAGE_DIMENSIONS,
    MAX_TYPE_USAGE_DIMENSIONS,
    AggregationScope,
    TaskUsageBreakdownView,
    TaskUsageByModelView,
    TaskUsageSourceView,
    TaskUsageValue,
    TaskUsageView,
    child_task_contribution_for_tool_started,
    usage_contributions_for_observation,
)
from sqlalchemy import and_, case, delete, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased

from deerflow.ansich.persistence.models import (
    AnsichActiveTaskReadModelRow,
    AnsichAgentReleaseComponentRow,
    AnsichAgentReleaseRow,
    AnsichAlertEvidenceRow,
    AnsichAlertReadModelRow,
    AnsichAlertRow,
    AnsichAlertWorkflowEventRow,
    AnsichAssessorErrorRow,
    AnsichAssessorJobRow,
    AnsichAssessorWatermarkRow,
    AnsichAuthorizationPermissionRow,
    AnsichAuthorizationScopeRow,
    AnsichAuthorizationSnapshotRow,
    AnsichBeliefAssertionRow,
    AnsichBeliefEvidenceRow,
    AnsichBlockProducerRow,
    AnsichContentBlobRow,
    AnsichContentBlockDerivationRow,
    AnsichContentBlockRow,
    AnsichContentOccurrenceRow,
    AnsichContextCompressionItemRow,
    AnsichContextCompressionRow,
    AnsichContextSnapshotBlockMembershipRow,
    AnsichContextSnapshotItemRow,
    AnsichContextSnapshotMissingItemRow,
    AnsichContextSnapshotRow,
    AnsichContextStateCheckpointItemRow,
    AnsichContextStateDeltaRow,
    AnsichContextStateMissingBlockRow,
    AnsichContextStateRow,
    AnsichContextWindowRow,
    AnsichCurrentBeliefRow,
    AnsichEntityRow,
    AnsichEnvironmentCoverageRow,
    AnsichEnvironmentStateRow,
    AnsichEvaluationIndexRow,
    AnsichLlmAttemptRow,
    AnsichObservationRow,
    AnsichOperatorActionRow,
    AnsichPayloadRow,
    AnsichProjectionErrorRow,
    AnsichProjectionJobRow,
    AnsichProjectorVersionRow,
    AnsichRelationEvidenceRow,
    AnsichRelationRow,
    AnsichReleaseQualityStatsRow,
    AnsichScopeConclusionRow,
    AnsichScopeRow,
    AnsichStepRow,
    AnsichTaskAgentReleaseRow,
    AnsichTaskAncestryRow,
    AnsichTaskBudgetRow,
    AnsichTaskHeartbeatRow,
    AnsichTaskRow,
    AnsichTaskSpawnRow,
    AnsichTaskSummaryRow,
    AnsichTaskUsageRow,
    AnsichToolCallAuthorizationRow,
    AnsichToolCallResultRow,
    AnsichToolCallRow,
    AnsichToolEffectRow,
    AnsichToolEnvSampleRow,
    AnsichTransitionRow,
    AnsichUsageContributionRow,
)

_CONTROL_BY_KIND = {
    "task.created": "created",
    "task.started": "running",
    "task.completed": "completed",
    "task.failed": "failed",
    "task.interrupted": "interrupted",
}
_STEP_PROJECTION_KINDS = frozenset(
    {
        "step.started",
        "step.closed",
        "llm.requested",
        "llm.responded",
        "llm.failed",
        "content.produced",
        "context.state_recorded",
        "context.snapshotted",
        "context.compressed",
        "tool.issued",
        "tool.started",
        "tool.returned_raw",
        "tool.result_visible",
        "tool.denied",
        "tool.timed_out",
        "tool.cancelled",
        "tool.failed",
        "tool.unknown_terminal",
    }
)
#: Registration order is execution priority for jobs of one observation:
#: structural projections must land before belief/control projections, and
#: future projectors (e.g. Phase 2 steps) run after both. Claim ordering
#: derives from this tuple — never from projector_name collation.
_USAGE_PROJECTION_KINDS = frozenset(
    {
        "llm.requested",
        "llm.responded",
        "step.started",
        "tool.issued",
        "tool.started",
        "tool.returned_raw",
        "tool.timed_out",
        "tool.cancelled",
        "tool.failed",
        "budget.consumed",
        "task.heartbeat",
    }
)
_SAFETY_PROJECTION_KINDS = frozenset(
    {
        "scope.snapshotted",
        "authorization.evaluated",
        "authorization.allowed",
        "authorization.denied",
        "authorization.unknown",
        "effect.potential",
        "effect.intended",
        "effect.observed",
    }
)
_PROJECTORS = (
    ("task-structural", "1"),
    ("task-control", "1"),
    ("task-step", "1"),
    ("task-usage", "1"),
    ("task-budget", "1"),
    ("task-heartbeat", "1"),
    ("task-safety", "1"),
    # Registration order is execution priority for one Observation, and the
    # environment projection hangs off the Scope entity that ``task-safety``
    # creates from ``scope.snapshotted`` — so it must follow it.
    ("environment-projector", "1"),
    # Registered last on purpose: evaluations point at subjects (Task, Step,
    # ToolCall, ContentBlock, AgentRelease) that the projectors above create.
    ("evaluation-projector", "1"),
)
_PROJECTOR_KINDS = {
    "task-structural": frozenset((*_CONTROL_BY_KIND, "agent_release.resolved")),
    "task-control": frozenset(_CONTROL_BY_KIND),
    "task-step": _STEP_PROJECTION_KINDS,
    "task-usage": _USAGE_PROJECTION_KINDS,
    "task-budget": frozenset({"budget.configured"}),
    "task-heartbeat": frozenset({"task.heartbeat"}),
    "task-safety": _SAFETY_PROJECTION_KINDS,
    "environment-projector": frozenset({"environment.sampled"}),
    "evaluation-projector": frozenset({EVALUATION_OBSERVATION_KIND}),
}
_ASSESSOR_VERSIONS = {
    ACTION_REPETITION_ASSESSOR.name: ACTION_REPETITION_ASSESSOR.version,
    TOOL_FREQUENCY_ASSESSOR.name: TOOL_FREQUENCY_ASSESSOR.version,
    ABSOLUTE_LIMIT_ASSESSOR.name: ABSOLUTE_LIMIT_ASSESSOR.version,
    CONFIGURATION_DRIFT_ASSESSOR.name: CONFIGURATION_DRIFT_ASSESSOR.version,
    SCOPE_SAFETY_ASSESSOR.name: SCOPE_SAFETY_ASSESSOR.version,
}
_USAGE_DIMENSION_ORDER = {
    "input_tokens": 0,
    "output_tokens": 1,
    "total_tokens": 2,
    "llm_attempts": 3,
    "steps": 4,
    "tool_calls_issued": 5,
    "tool_calls_executed": 6,
    "wall_time_ms": 7,
    "child_tasks_spawned": 8,
}
_CONTENT_CANONICALIZATION_VERSION = "1"
_EVALUATION_PROJECTOR_VERSION = "1"
_EVALUATION_PROJECTOR_CONFIG_HASH = canonical_config_hash(
    {
        "projector": "evaluation-projector",
        "version": _EVALUATION_PROJECTOR_VERSION,
    }
)
#: Dimensions that carry a named semantic claim, so an evaluation of one of them
#: becomes a ``quality.<dimension>`` Belief assertion and feeds release stats.
#: ``custom`` deliberately stays index-only, and ``earliest_erroneous_step``
#: asserts a Step pointer rather than a quality verdict.
_EVALUATION_QUALITY_DIMENSIONS = frozenset(
    {
        "correctness",
        "completeness",
        "relevance",
        "safety",
        "efficiency",
    }
)
_EVALUATION_SUITE_BOUND_KINDS = frozenset({"benchmark_assertion", "unit_test"})
_TOOL_TERMINAL_PRECEDENCE = {
    "unknown_terminal": 0,
    "denied": 1,
    "cancelled": 2,
    "timed_out": 3,
    "failed": 4,
    "returned": 5,
}
#: Job statuses a claim may take over. ``retry`` is a re-armed job that already
#: spent an attempt; ``pending`` stays reserved for work nothing has tried yet
#: (including a replay-safe dependency wait, which consumes no attempt), and a
#: ``processing`` row only becomes claimable once its lease has expired.
_CLAIMABLE_JOB_STATUSES = ("pending", "retry")
#: Stable advisory-lock key for the Ansich single-operator maintenance
#: operations (``rebuild_projections`` / ``retry_failed_projections``). The
#: value is mnemonic rather than random -- ``0DEE`` marks it as DeerFlow's,
#: ``A115``/``C4A5`` read as "ansich"/"CAS", and ``0027`` is the revision that
#: added the column this work guards -- and it is deliberately distinct from the
#: schema bootstrap key (``persistence/bootstrap.py::_PG_LOCK_KEY``) so a
#: rebuild and a startup migration never queue behind each other. It stays under
#: 2**63 so it is a valid signed bigint lock id. Changing it effectively
#: releases the prior lock, so do not change it without coordinating.
_PG_MAINTENANCE_LOCK_KEY = 0x0DEE_A115_C4A5_0027

logger = logging.getLogger(__name__)


class _ProjectionDependencyPending(RuntimeError):
    """A replay-safe projection dependency has not landed yet."""


class _StaleAssessorClaim(RuntimeError):
    """This worker no longer owns the assessor job it just evaluated.

    Raised inside the evaluation transaction so that transaction rolls back
    whole (controller ruling PB4). Never surfaces to a caller: the loop that
    raises it also catches it, treats the job as somebody else's, and writes no
    error row -- the drop is not a failure of the work, it is a change of owner.
    """


class _AssessorClaim(NamedTuple):
    """One claimed assessor job plus what the claim transaction observed.

    ``pre_claim_watermark`` is the durable evidence mark as it stood *before*
    this claim widened it down over the group (``_widen_assessor_watermark``).
    The evaluation restores it, so a job whose own watermark sits under an
    already-advanced mark cannot drag that mark backwards -- see
    ``_advance_assessor_watermark``.
    """

    job_id: str
    subject_id: str
    assessor_name: str
    evidence_watermark: int
    attempts: int
    lease_generation: int
    pre_claim_watermark: int | None


def _projectors_for_kind(kind: str) -> tuple[tuple[str, str], ...]:
    return tuple(registration for registration in _PROJECTORS if kind in _PROJECTOR_KINDS.get(registration[0], ()))


def _assessors_after_projection(
    projector_name: str,
    observation_kind: str,
) -> tuple[tuple[str, str], ...]:
    names: set[str] = set()
    if projector_name == "task-step" and observation_kind in {
        "tool.issued",
        "step.closed",
    }:
        names.update(
            {
                ACTION_REPETITION_ASSESSOR.name,
                TOOL_FREQUENCY_ASSESSOR.name,
            }
        )
    if projector_name in {"task-usage", "task-budget", "task-heartbeat"}:
        names.add(ABSOLUTE_LIMIT_ASSESSOR.name)
    if projector_name == "task-safety":
        names.add(SCOPE_SAFETY_ASSESSOR.name)
    if (projector_name == "task-structural" and observation_kind == "agent_release.resolved") or (projector_name == "task-step" and observation_kind == "llm.responded"):
        names.add(CONFIGURATION_DRIFT_ASSESSOR.name)
    if projector_name == "task-control" and observation_kind in {
        "task.completed",
        "task.failed",
        "task.interrupted",
    }:
        names.update(_ASSESSOR_VERSIONS)
    return tuple((name, _ASSESSOR_VERSIONS[name]) for name in sorted(names))


def _projector_priority_expression():
    priority_by_name = {name: index for index, (name, _) in enumerate(_PROJECTORS)}
    return case(priority_by_name, value=AnsichProjectionJobRow.projector_name, else_=len(priority_by_name))


def _evaluation_authority_class(record: EvaluationRecord) -> AuthorityClass:
    """Map one evaluation onto the Belief resolver's authority ladder (R2).

    Suite-bound evaluations are deterministic only when they carry ``hard``
    fidelity; the same runner emitting a rule/soft judgement is a configured
    rule. A developer annotation is authoritative only when it explicitly
    claims the human override, otherwise it joins ordinary user feedback in the
    resolver-v2 ``soft_human`` class. An LLM judge is never human evidence.
    """

    if record.evaluation_kind in _EVALUATION_SUITE_BOUND_KINDS:
        return "deterministic" if record.fidelity_class == "hard" else "configured_rule"
    if record.evaluation_kind == "developer_annotation":
        return "human_override" if record.human_override else "soft_human"
    if record.evaluation_kind == "user_feedback":
        return "soft_human"
    return "automated"


def _action_repetition_rows_statement(
    *,
    task_id: str,
    evidence_watermark: int,
):
    closed_observation = aliased(
        AnsichObservationRow,
        name="closed_observation",
    )
    issued_observation = aliased(
        AnsichObservationRow,
        name="issued_observation",
    )
    return (
        select(
            AnsichStepRow,
            closed_observation,
            AnsichToolCallRow,
            issued_observation,
        )
        .join(
            closed_observation,
            closed_observation.obs_id == AnsichStepRow.closed_obs_id,
        )
        .outerjoin(
            AnsichToolCallRow,
            AnsichToolCallRow.step_id == AnsichStepRow.entity_id,
        )
        .outerjoin(
            issued_observation,
            and_(
                issued_observation.obs_id == AnsichToolCallRow.issued_obs_id,
                issued_observation.ingest_seq <= evidence_watermark,
            ),
        )
        .where(
            AnsichStepRow.task_id == task_id,
            AnsichStepRow.actor_kind != "system_operation",
            closed_observation.ingest_seq <= evidence_watermark,
        )
        .order_by(
            AnsichStepRow.step_seq,
            AnsichToolCallRow.call_seq,
            AnsichToolCallRow.entity_id,
        )
    )


def _reconciliation_alert_rows_statement(*, task_id: str):
    latest_episode_by_key = (
        select(
            AnsichAlertRow.alert_key.label("alert_key"),
            func.max(AnsichAlertRow.episode).label("max_episode"),
        )
        .where(AnsichAlertRow.subject_id == task_id)
        .group_by(AnsichAlertRow.alert_key)
        .subquery("latest_alert_episode")
    )
    return (
        select(AnsichAlertRow)
        .join(
            latest_episode_by_key,
            latest_episode_by_key.c.alert_key == AnsichAlertRow.alert_key,
        )
        .where(
            AnsichAlertRow.subject_id == task_id,
            or_(
                AnsichAlertRow.workflow_state != "resolved",
                AnsichAlertRow.episode == latest_episode_by_key.c.max_episode,
            ),
        )
        .order_by(
            AnsichAlertRow.alert_key,
            AnsichAlertRow.episode,
        )
    )


def _periodic_budget_rows_statement():
    return (
        select(AnsichTaskBudgetRow)
        .join(
            AnsichTaskSummaryRow,
            AnsichTaskSummaryRow.task_id == AnsichTaskBudgetRow.task_id,
        )
        .where(AnsichTaskSummaryRow.control_value == "running")
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _as_non_negative_int(value: object) -> int | None:
    """Return a metric reading only when it really is one.

    ``bool`` is excluded deliberately (it is an ``int`` subclass in Python but
    never a metric), and anything else — a string, a float, a missing key —
    yields ``None`` so the caller skips the sample instead of coercing an
    unreadable payload into a number.
    """

    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _read_model_values_equal(current: object, candidate: object) -> bool:
    if isinstance(current, datetime) and isinstance(candidate, datetime):
        return _as_utc(current) == _as_utc(candidate)
    return current == candidate


def _list_task_views_statement(
    *,
    limit: int,
    control: ControlValue | None,
    lifecycle_scope: TaskLifecycleScope,
    from_time: datetime | None,
    to_time: datetime | None,
    cursor: tuple[datetime, str] | None,
    root_only: bool = False,
):
    page_statement = select(
        AnsichTaskSummaryRow.task_id,
        AnsichTaskSummaryRow.source_kind,
        AnsichTaskSummaryRow.source_id,
        AnsichTaskSummaryRow.control_value,
        AnsichTaskSummaryRow.control_as_of,
        AnsichTaskSummaryRow.last_evidence_at,
        AnsichTaskSummaryRow.assertion_id,
        AnsichTaskSummaryRow.observability_status,
        AnsichTaskSummaryRow.tool_calls_issued,
        AnsichTaskSummaryRow.tool_calls_executed,
    )
    if root_only:
        page_statement = page_statement.where(~select(AnsichTaskSpawnRow.child_task_id).where(AnsichTaskSpawnRow.child_task_id == AnsichTaskSummaryRow.task_id).exists())
    if control is not None:
        page_statement = page_statement.where(AnsichTaskSummaryRow.control_value == control)
    lifecycle_controls = control_values_for_lifecycle_scope(lifecycle_scope)
    if lifecycle_controls is not None:
        page_statement = page_statement.where(AnsichTaskSummaryRow.control_value.in_(lifecycle_controls))
    if from_time is not None:
        page_statement = page_statement.where(AnsichTaskSummaryRow.last_evidence_at >= from_time)
    if to_time is not None:
        page_statement = page_statement.where(AnsichTaskSummaryRow.last_evidence_at <= to_time)
    if cursor is not None:
        cursor_time, cursor_task_id = cursor
        page_statement = page_statement.where(
            or_(
                AnsichTaskSummaryRow.last_evidence_at < cursor_time,
                and_(
                    AnsichTaskSummaryRow.last_evidence_at == cursor_time,
                    AnsichTaskSummaryRow.task_id > cursor_task_id,
                ),
            )
        )
    page = (
        page_statement.order_by(
            AnsichTaskSummaryRow.last_evidence_at.desc(),
            AnsichTaskSummaryRow.task_id,
        )
        .limit(limit)
        .cte("ansich_task_page")
    )
    return (
        select(
            page,
            AnsichCurrentBeliefRow.resolver_name.label("resolver_name"),
            AnsichCurrentBeliefRow.resolver_version.label("resolver_version"),
            AnsichBeliefAssertionRow.value_json.label("assertion_value_json"),
            AnsichBeliefAssertionRow.as_of.label("assertion_as_of"),
            AnsichBeliefAssertionRow.asserted_at.label("assertion_asserted_at"),
            AnsichBeliefAssertionRow.source_name.label("assertion_source_name"),
            AnsichBeliefAssertionRow.source_version.label("assertion_source_version"),
            AnsichBeliefEvidenceRow.obs_id.label("evidence_obs_id"),
            AnsichBeliefEvidenceRow.ordinal.label("evidence_ordinal"),
        )
        .select_from(page)
        .outerjoin(
            AnsichCurrentBeliefRow,
            and_(
                AnsichCurrentBeliefRow.subject_id == page.c.task_id,
                AnsichCurrentBeliefRow.field_name == "control",
                AnsichCurrentBeliefRow.assertion_id == page.c.assertion_id,
            ),
        )
        .outerjoin(
            AnsichBeliefAssertionRow,
            AnsichBeliefAssertionRow.assertion_id == page.c.assertion_id,
        )
        .outerjoin(
            AnsichBeliefEvidenceRow,
            AnsichBeliefEvidenceRow.assertion_id == page.c.assertion_id,
        )
        .order_by(
            page.c.last_evidence_at.desc(),
            page.c.task_id,
            AnsichBeliefEvidenceRow.ordinal,
            AnsichBeliefEvidenceRow.obs_id,
        )
    )


def _list_context_compression_summaries_statement(
    *,
    task_id: str,
    limit: int,
    cursor: tuple[datetime, str] | None = None,
):
    statement = (
        select(
            AnsichContextCompressionRow,
            AnsichObservationRow.occurred_at,
        )
        .join(
            AnsichObservationRow,
            AnsichObservationRow.obs_id == AnsichContextCompressionRow.source_obs_id,
        )
        .where(AnsichContextCompressionRow.task_id == task_id)
    )
    if cursor is not None:
        cursor_time, cursor_obs_id = cursor
        statement = statement.where(
            or_(
                AnsichObservationRow.occurred_at < cursor_time,
                and_(
                    AnsichObservationRow.occurred_at == cursor_time,
                    AnsichContextCompressionRow.source_obs_id > cursor_obs_id,
                ),
            )
        )
    return statement.order_by(
        AnsichObservationRow.occurred_at.desc(),
        AnsichContextCompressionRow.source_obs_id,
    ).limit(limit)


def _canonical_content_bytes(body: object) -> tuple[str, bytes]:
    if isinstance(body, str):
        return "text/plain; charset=utf-8", body.encode("utf-8")
    return (
        "application/json",
        json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"),
    )


def _content_blob_key(content_type: str, body: bytes) -> str:
    digest = hashlib.sha256()
    digest.update(f"ansich-content:{_CONTENT_CANONICALIZATION_VERSION}:{content_type}\0".encode())
    digest.update(body)
    return digest.hexdigest()


#: Conservative expiry for an operator action left stranded in ``requested``,
#: sharing the lease intuition of ``projector_lease_seconds`` below: work whose
#: owner stopped renewing eventually becomes claimable by someone else. A process
#: that dies between ``begin_operator_action`` and ``finish_operator_action``
#: leaves its audit row ``requested`` forever, so every later retry carrying that
#: Idempotency-Key would conflict for good and the abandoned attempt would never
#: reach a terminal. Past this window a retry with the same key terminalizes the
#: abandoned attempt and executes fresh; inside it, a ``requested`` row is still
#: treated as a genuine in-flight duplicate. Recovery is deliberately
#: request-driven — there is no startup sweep, so a stranded row is judged only by
#: an operator who actually wants that action to happen now.
_STALE_REQUESTED_TAKEOVER_AFTER = timedelta(minutes=5)


class SqlAnsichBackend:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        projector_lease_seconds: int = 30,
        projector_max_attempts: int = 5,
        projector_dependency_timeout_seconds: int = 300,
        inline_payload_max_bytes: int = 65_536,
        heartbeat_stale_after_seconds: int = 30,
        long_dwell_seconds: int = 120,
        exact_repetition_window: int = 5,
        tool_frequency_window_seconds: int = 300,
        tool_frequency_threshold: int = 30,
        environment_sample_interval_seconds: int = 10,
        environment_thresholds: EnvironmentThresholds | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._projector_lease_seconds = projector_lease_seconds
        self._projector_max_attempts = projector_max_attempts
        self._projector_dependency_timeout = timedelta(seconds=projector_dependency_timeout_seconds)
        self._inline_payload_max_bytes = inline_payload_max_bytes
        self._heartbeat_stale_after_seconds = heartbeat_stale_after_seconds
        self._long_dwell_seconds = long_dwell_seconds
        if exact_repetition_window < 2:
            raise ValueError("exact_repetition_window must be at least two")
        if tool_frequency_window_seconds < 1:
            raise ValueError("tool_frequency_window_seconds must be positive")
        if tool_frequency_threshold < 1:
            raise ValueError("tool_frequency_threshold must be positive")
        if environment_sample_interval_seconds < 1:
            raise ValueError("environment_sample_interval_seconds must be positive")
        self._exact_repetition_window = exact_repetition_window
        self._tool_frequency_window_seconds = tool_frequency_window_seconds
        self._tool_frequency_threshold = tool_frequency_threshold
        self._environment_sample_interval_seconds = environment_sample_interval_seconds
        self._environment_thresholds = environment_thresholds or EnvironmentThresholds()
        self._lease_owner = str(uuid4())
        self._watermark: int | None = None
        self._failed_jobs = 0
        # Debug counter, deliberately not a health field: how many of this
        # worker's writes were dropped because the job had already been taken
        # over (its ``lease_generation`` moved). It is process-local and resets
        # on restart; exposing it as durable health is Task 10's call.
        self._stale_completion_count = 0
        self._latest_recorded_at: datetime | None = None
        self._latest_projected_at: datetime | None = None
        self._context_metrics = {
            "snapshot_count": 0,
            "snapshot_item_count": 0,
            "snapshot_visible_bytes": 0,
            "incomplete_snapshot_count": 0,
            "missing_content_block_count": 0,
        }

    @property
    def stale_completion_count(self) -> int:
        """Writes this worker dropped because the job had been taken over."""

        return self._stale_completion_count

    @asynccontextmanager
    async def _maintenance_lock(self) -> AsyncIterator[None]:
        """Serialise the operator maintenance operations across workers.

        ``rebuild_projections`` and ``retry_failed_projections`` are
        single-operator operations: both re-arm durable jobs wholesale, so two
        of them (or one of them plus another instance of itself) running at once
        would replay the same Observations twice.

        A second operator **blocks** rather than being rejected. Waiting is the
        safer of the two: a rejected rebuild leaves the caller to decide whether
        the work happened, while a queued one always ends with the replay
        actually done -- and these are rare, deliberate operator actions, not a
        hot path where the wait would cost throughput. That wait is not free for
        the worker doing it: ``AnsichService`` holds its process-local
        ``_projection_lock`` around this call, so a queued operator also stalls
        its own projector loop -- and any terminal barrier waiting behind it --
        for as long as it waits.

        The wait is unbounded at the database, but a deployment-level
        ``database.command_timeout`` (30s by default) bounds it in practice:
        past it asyncpg cancels the pending lock request and the call fails
        loudly instead of queueing forever. That is the same exposure the schema
        bootstrap's advisory lock already carries on the same engine. A
        cancelled acquire is *not* proof that no lock was taken -- the grant can
        land server-side while the reply is still in flight -- so the unlock is
        inside the guarded region and runs on that path too; a
        ``pg_advisory_unlock`` for a lock this session never held returns false
        and is otherwise harmless, which is the cheap side of that trade.

        On PostgreSQL the guard is a session-scoped ``pg_advisory_lock`` held on
        one pinned connection for the whole operation (the bootstrap precedent,
        ``persistence/bootstrap.py``), including the disable of
        ``idle_in_transaction_session_timeout`` that otherwise lets a managed
        server kill the holder and silently release the lock; it is issued
        *before* the acquire because a slow acquire is itself time spent idle in
        transaction. Everywhere else -- SQLite in practice -- it is a documented
        no-op: SQLite is single-writer and single-node by deployment, so the only
        concurrency it has is inside one process, which ``AnsichService`` already
        serialises with that same ``_projection_lock``. A dialect that cannot be
        resolved at all raises instead of degrading to the no-op: a lock is a
        safety device, and one that fails open would let two operators replay the
        same Observations with nothing in the logs to say so.
        """

        async with self._session_factory() as session:
            bind = session.bind
            if bind is None:
                raise RuntimeError("Ansich maintenance lock cannot resolve the session's dialect; refusing to run an unguarded rebuild/retry")
            if bind.dialect.name != "postgresql":
                yield
                return
            await session.execute(text("SET LOCAL idle_in_transaction_session_timeout = 0"))
            try:
                await session.execute(
                    text("SELECT pg_advisory_lock(:key)"),
                    {"key": _PG_MAINTENANCE_LOCK_KEY},
                )
                yield
            finally:
                # Rollback first, unlock second. After a DBAPI error the
                # session is left in an inactive state and *every* further
                # ``execute`` raises ``PendingRollbackError`` before reaching
                # the server -- so an unlock issued first would be swallowed by
                # the handler below and the lock would be held until the
                # connection closed. ``ROLLBACK`` makes the connection usable
                # again, and a session-level ``pg_advisory_lock`` survives it
                # (it is bound to the session, not the transaction), so the
                # unlock still has something to release. The stub session in
                # the tests cannot reproduce the inactive state; the real
                # PostgreSQL proof belongs to the opt-in tier.
                await session.rollback()
                try:
                    await session.execute(
                        text("SELECT pg_advisory_unlock(:key)"),
                        {"key": _PG_MAINTENANCE_LOCK_KEY},
                    )
                except Exception:  # noqa: BLE001
                    logger.warning(
                        "ansich maintenance: pg_advisory_unlock raised; the session close will release it",
                        exc_info=True,
                    )

    async def initialize_metrics(self) -> None:
        await self._refresh_failed_job_count()
        await self._refresh_context_metrics()

    async def persist_and_project(self, observations: list[ObservationEnvelope]) -> int:
        processed = 0
        async with self._session_factory() as session, session.begin():
            for observation in observations:
                existing_obs = await session.scalar(
                    select(AnsichObservationRow).where(
                        or_(
                            AnsichObservationRow.obs_id == observation.obs_id,
                            (
                                (AnsichObservationRow.producer_name == observation.producer.name)
                                & (AnsichObservationRow.producer_instance_id == observation.producer.instance_id)
                                & (AnsichObservationRow.source_event_id == observation.source_event_id)
                            ),
                        )
                    )
                )
                if existing_obs is not None:
                    continue
                payload_json = observation.payload
                payload_ref_id = observation.payload_ref_id
                if observation.kind == "content.produced" and payload_json is not None and "body" in payload_json:
                    body = payload_json["body"]
                    content_type, content_bytes = _canonical_content_bytes(body)
                    content_hash = hashlib.sha256(content_bytes).hexdigest()
                    if payload_json.get("content_hash") != content_hash:
                        raise ValueError("content.produced hash does not match canonical body")
                    blob_key = _content_blob_key(content_type, content_bytes)
                    await self._ensure_content_blob(
                        session,
                        blob_key=blob_key,
                        content_hash=content_hash,
                        content_type=content_type,
                        content_bytes=content_bytes,
                    )
                    payload_json = dict(payload_json)
                    payload_json.pop("body", None)
                    payload_json["blob_key"] = blob_key
                    payload_json["content_type"] = content_type
                    payload_json["canonicalization_version"] = _CONTENT_CANONICALIZATION_VERSION
                if payload_json is not None:
                    encoded_payload = json.dumps(
                        payload_json,
                        ensure_ascii=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    ).encode("utf-8")
                    if len(encoded_payload) > self._inline_payload_max_bytes:
                        payload_ref_id = new_id()
                        session.add(
                            AnsichPayloadRow(
                                payload_id=payload_ref_id,
                                content_type="application/json",
                                encoding="utf-8",
                                compression="none",
                                byte_size=len(encoded_payload),
                                sha256=hashlib.sha256(encoded_payload).hexdigest(),
                                body=encoded_payload,
                            )
                        )
                        await session.flush()
                        payload_json = None
                session.add(
                    AnsichObservationRow(
                        obs_id=observation.obs_id,
                        schema_version=observation.schema_version,
                        kind=observation.kind,
                        occurred_at=observation.occurred_at,
                        recorded_at=observation.recorded_at,
                        task_id=observation.task_id,
                        step_id=observation.step_id,
                        subject_type=observation.subject_type,
                        subject_id=observation.subject_id,
                        fidelity_class=observation.fidelity_class,
                        producer_name=observation.producer.name,
                        producer_version=observation.producer.version,
                        producer_instance_id=observation.producer.instance_id,
                        producer_seq=observation.producer_seq,
                        source_event_id=observation.source_event_id,
                        correlation_id=observation.correlation_id,
                        causation_obs_id=observation.causation_obs_id,
                        payload_json=payload_json,
                        payload_ref_id=payload_ref_id,
                    )
                )
                await session.flush()
                for projector_name, projector_version in _projectors_for_kind(observation.kind):
                    version = await session.get(AnsichProjectorVersionRow, (projector_name, projector_version))
                    if version is None:
                        session.add(
                            AnsichProjectorVersionRow(
                                projector_name=projector_name,
                                projector_version=projector_version,
                            )
                        )
                    job = AnsichProjectionJobRow(
                        job_id=new_id(),
                        obs_id=observation.obs_id,
                        projector_name=projector_name,
                        projector_version=projector_version,
                        status="pending",
                    )
                    session.add(job)
                processed += 1
        if processed:
            latest = max(observation.recorded_at for observation in observations)
            if self._latest_recorded_at is None or latest > self._latest_recorded_at:
                self._latest_recorded_at = latest
        return processed

    async def _ensure_content_blob(
        self,
        session: AsyncSession,
        *,
        blob_key: str,
        content_hash: str,
        content_type: str,
        content_bytes: bytes,
    ) -> None:
        blob = await session.get(AnsichContentBlobRow, blob_key)
        if blob is None:
            blob_payload_ref_id = None
            inline_body = content_bytes
            if len(content_bytes) > self._inline_payload_max_bytes:
                blob_payload_ref_id = new_id()
                inline_body = None
                session.add(
                    AnsichPayloadRow(
                        payload_id=blob_payload_ref_id,
                        content_type=content_type,
                        encoding="utf-8",
                        compression="none",
                        byte_size=len(content_bytes),
                        sha256=content_hash,
                        body=content_bytes,
                    )
                )
                await session.flush()
            values = {
                "blob_key": blob_key,
                "content_hash": content_hash,
                "byte_size": len(content_bytes),
                "content_type": content_type,
                "canonicalization_version": _CONTENT_CANONICALIZATION_VERSION,
                "payload_status": "available",
                "inline_body": inline_body,
                "payload_ref_id": blob_payload_ref_id,
            }
            dialect_name = session.bind.dialect.name if session.bind is not None else ""
            if dialect_name == "postgresql":
                statement = postgresql_insert(AnsichContentBlobRow).values(**values)
            elif dialect_name == "sqlite":
                statement = sqlite_insert(AnsichContentBlobRow).values(**values)
            else:
                raise ValueError(f"unsupported Ansich SQL dialect: {dialect_name}")
            inserted_key = (await session.execute(statement.on_conflict_do_nothing(index_elements=["blob_key"]).returning(AnsichContentBlobRow.blob_key))).scalar_one_or_none()
            if inserted_key is None and blob_payload_ref_id is not None:
                losing_payload = await session.get(AnsichPayloadRow, blob_payload_ref_id)
                if losing_payload is not None:
                    await session.delete(losing_payload)
            blob = await session.get(AnsichContentBlobRow, blob_key)
            if blob is None:
                raise RuntimeError("Ansich ContentBlob upsert did not produce a row")
        existing_bytes = await self._content_blob_bytes(session, blob)
        if existing_bytes != content_bytes:
            raise ValueError("Ansich ContentBlob key collision")

    async def project_pending(self, *, limit: int = 200) -> int:
        processed = 0
        for _ in range(limit):
            claim = await self._claim_projection_job()
            if claim is None:
                break
            job_id, projector_name, observation, ingest_seq, attempt, lease_generation = claim
            try:
                context_metrics_changed = False
                settled = False
                async with self._session_factory() as session, session.begin():
                    if projector_name == "task-structural":
                        await self._project_structural(session, observation)
                    elif projector_name == "task-control":
                        await self._project_control(session, observation, ingest_seq=ingest_seq)
                    elif projector_name == "task-step":
                        context_metrics_changed = await self._project_step(session, observation)
                    elif projector_name == "task-usage":
                        await self._project_usage(session, observation, ingest_seq=ingest_seq)
                    elif projector_name == "task-budget":
                        await self._project_budget(session, observation)
                    elif projector_name == "task-heartbeat":
                        await self._project_heartbeat(session, observation)
                    elif projector_name == "task-safety":
                        await self._project_safety(session, observation)
                    elif projector_name == "environment-projector":
                        await self._project_environment(session, observation)
                    elif projector_name == "evaluation-projector":
                        await self._project_evaluation(session, observation)
                    else:
                        raise ValueError(f"unknown Ansich projector: {projector_name}")
                    for assessor_name, assessor_version in _assessors_after_projection(
                        projector_name,
                        observation.kind,
                    ):
                        existing_assessor_job = await session.scalar(
                            select(AnsichAssessorJobRow.job_id).where(
                                AnsichAssessorJobRow.subject_id == observation.task_id,
                                AnsichAssessorJobRow.assessor_name == assessor_name,
                                AnsichAssessorJobRow.assessor_version == assessor_version,
                                AnsichAssessorJobRow.evidence_watermark == ingest_seq,
                            )
                        )
                        if existing_assessor_job is None:
                            session.add(
                                AnsichAssessorJobRow(
                                    job_id=new_id(),
                                    subject_id=observation.task_id,
                                    assessor_name=assessor_name,
                                    assessor_version=assessor_version,
                                    evidence_watermark=ingest_seq,
                                    status="pending",
                                )
                            )
                    settled = await self._complete_projection_job(
                        session,
                        job_id=job_id,
                        lease_generation=lease_generation,
                    )
                if context_metrics_changed:
                    # Unconditional, including on a dropped write: this is a
                    # recount of whole tables, not a report of our progress, and
                    # the rows it counts were committed by the projection above
                    # whoever ends up owning the job. Skipping it would leave the
                    # counts stale until some unrelated projection refreshed them.
                    await self._refresh_context_metrics()
                if not settled:
                    # The job belongs to another worker now, so its progress is
                    # not ours to report: neither the watermark nor the
                    # processed count may advance on a dropped write.
                    continue
                processed += 1
                self._watermark = ingest_seq if self._watermark is None else max(self._watermark, ingest_seq)
                if self._latest_projected_at is None or observation.recorded_at > self._latest_projected_at:
                    self._latest_projected_at = observation.recorded_at
            except Exception as exc:
                await self._record_projection_error(
                    job_id,
                    attempt,
                    exc,
                    lease_generation=lease_generation,
                )
        return processed

    def get_projection_metrics(self) -> dict[str, int | None]:
        lag_ms = 0
        if self._latest_recorded_at is not None:
            projected_at = self._latest_projected_at
            if projected_at is None:
                lag_ms = max(0, int((datetime.now(UTC) - self._latest_recorded_at).total_seconds() * 1000))
            else:
                lag_ms = max(0, int((self._latest_recorded_at - projected_at).total_seconds() * 1000))
        return {
            "watermark": self._watermark,
            "lag_ms": lag_ms,
            "failed_jobs": self._failed_jobs,
            **self._context_metrics,
        }

    async def _refresh_context_metrics(self) -> None:
        async with self._session_factory() as session:
            snapshot_count = await session.scalar(select(func.count()).select_from(AnsichContextSnapshotRow))
            snapshot_visible_bytes = await session.scalar(select(func.coalesce(func.sum(AnsichContextSnapshotRow.visible_bytes), 0)))
            complete_items = await session.scalar(select(func.count()).select_from(AnsichContextSnapshotItemRow))
            missing_items = await session.scalar(select(func.count()).select_from(AnsichContextSnapshotMissingItemRow))
            state_items = await session.scalar(
                select(func.coalesce(func.sum(AnsichContextStateRow.item_count), 0)).select_from(AnsichContextSnapshotRow).join(AnsichContextStateRow, AnsichContextStateRow.state_id == AnsichContextSnapshotRow.state_id)
            )
            state_missing_blocks = await session.scalar(select(func.count()).select_from(AnsichContextStateMissingBlockRow))
            incomplete_snapshots = await session.scalar(select(func.count()).select_from(AnsichContextSnapshotRow).where(AnsichContextSnapshotRow.status == "incomplete"))
        self._context_metrics = {
            "snapshot_count": int(snapshot_count or 0),
            "snapshot_item_count": int(complete_items or 0) + int(missing_items or 0) + int(state_items or 0),
            "snapshot_visible_bytes": int(snapshot_visible_bytes or 0),
            "incomplete_snapshot_count": int(incomplete_snapshots or 0),
            "missing_content_block_count": int(missing_items or 0) + int(state_missing_blocks or 0),
        }

    async def has_pending_for_task(self, task_id: str) -> bool:
        async with self._session_factory() as session:
            pending = await session.scalar(
                select(AnsichProjectionJobRow.job_id)
                .join(AnsichObservationRow, AnsichObservationRow.obs_id == AnsichProjectionJobRow.obs_id)
                .where(
                    AnsichObservationRow.task_id == task_id,
                    # ``retry`` is unsettled work like the other two: it has
                    # spent an attempt but is still queued to be claimed.
                    AnsichProjectionJobRow.status.in_((*_CLAIMABLE_JOB_STATUSES, "processing")),
                )
                .limit(1)
            )
        return pending is not None

    async def rebuild_projections(self) -> RebuildOutcome:
        """Delete rebuildable Phase 1 state and replay every durable job.

        A single-operator maintenance operation: the whole delete-re-pend-replay
        sequence runs under ``_maintenance_lock``, so a second operator (or a
        concurrent retry) waits instead of replaying the same Observations
        alongside it. See that method for the block-rather-than-reject choice
        and the SQLite no-op.

        The re-pend raises every job's ``lease_generation``. A worker holding a
        claim when the rebuild starts is *not* stopped by the lock -- it never
        took it -- so its late completion would otherwise match the re-pended
        row and mark the job settled before the replay ever claimed it, quietly
        dropping that Observation from the rebuilt read model. Raising the
        generation makes that write fail its compare-and-set instead.

        The drain loop's exit condition -- "a round claimed nothing" -- is not
        the same thing as "the rebuild is done" (F10-26), so the return value
        says both: ``replayed`` and ``unsettled``. Waiting for the stragglers
        instead was the other option and was rejected: a dependency-pending job
        is invisible for its 250ms backoff and can legitimately take up to
        ``projector_dependency_timeout_seconds`` to give up, and this call
        already holds both the cross-worker maintenance lock and (through
        ``AnsichService``) the caller's own projector lock, so waiting would
        stall an operator and that worker's projector loop for an interval the
        rebuild does not control. Reporting is bounded and honest; re-running a
        rebuild is idempotent, so the caller can simply call again.
        """

        async with self._maintenance_lock():
            return await self._rebuild_projections_locked()

    async def _unsettled_job_count(self) -> int:
        """Jobs that are neither completed nor durably failed, both tables.

        The one number behind ``RebuildOutcome.unsettled``: it covers the
        dependency-pending job hiding inside its backoff window *and* the job a
        concurrent worker took over mid-rebuild, because from the caller's side
        those are the same fact -- work this pass did not settle.
        """

        async with self._session_factory() as session:
            projection_jobs = await session.scalar(select(func.count()).select_from(AnsichProjectionJobRow).where(AnsichProjectionJobRow.status.in_((*_CLAIMABLE_JOB_STATUSES, "processing"))))
            assessor_jobs = await session.scalar(select(func.count()).select_from(AnsichAssessorJobRow).where(AnsichAssessorJobRow.status.in_((*_CLAIMABLE_JOB_STATUSES, "processing"))))
        return int(projection_jobs or 0) + int(assessor_jobs or 0)

    async def _rebuild_projections_locked(self) -> RebuildOutcome:
        async with self._session_factory() as session, session.begin():
            for model in (
                AnsichAlertReadModelRow,
                AnsichAlertWorkflowEventRow,
                AnsichAlertEvidenceRow,
                AnsichAlertRow,
                AnsichOperatorActionRow,
                AnsichAssessorErrorRow,
                AnsichAssessorJobRow,
                # Deleted with the conclusions it describes: a surviving mark
                # would make the post-rebuild assessment skip the very
                # ToolCalls whose conclusions were just dropped.
                AnsichAssessorWatermarkRow,
                AnsichScopeConclusionRow,
                AnsichTaskHeartbeatRow,
                AnsichActiveTaskReadModelRow,
                AnsichEvaluationIndexRow,
                AnsichReleaseQualityStatsRow,
                AnsichTaskBudgetRow,
                AnsichTaskUsageRow,
                AnsichUsageContributionRow,
                AnsichTaskAncestryRow,
                AnsichTaskSpawnRow,
                AnsichContextSnapshotMissingItemRow,
                AnsichContextSnapshotBlockMembershipRow,
                AnsichContextSnapshotItemRow,
                AnsichContextSnapshotRow,
                AnsichContextWindowRow,
                AnsichContextCompressionItemRow,
                AnsichContextCompressionRow,
                AnsichContextStateMissingBlockRow,
                AnsichContextStateDeltaRow,
                AnsichContextStateCheckpointItemRow,
                AnsichContextStateRow,
                AnsichContentBlockDerivationRow,
                AnsichBlockProducerRow,
                AnsichToolEffectRow,
                AnsichToolCallAuthorizationRow,
                AnsichAuthorizationPermissionRow,
                AnsichAuthorizationScopeRow,
                AnsichAuthorizationSnapshotRow,
                AnsichToolCallResultRow,
                AnsichToolCallRow,
                AnsichContentOccurrenceRow,
                AnsichContentBlockRow,
                AnsichLlmAttemptRow,
                AnsichStepRow,
                AnsichTaskSummaryRow,
                AnsichCurrentBeliefRow,
                AnsichBeliefEvidenceRow,
                AnsichTransitionRow,
                AnsichBeliefAssertionRow,
                AnsichRelationEvidenceRow,
                AnsichRelationRow,
                AnsichTaskAgentReleaseRow,
                AnsichAgentReleaseComponentRow,
                AnsichAgentReleaseRow,
                # Coverage and state carry an FK onto the Scope entity they
                # describe, so they are deleted before AnsichEntityRow; the
                # per-tool-call samples are FK-free but rebuild alongside them.
                AnsichEnvironmentStateRow,
                AnsichEnvironmentCoverageRow,
                AnsichToolEnvSampleRow,
                AnsichScopeRow,
                AnsichTaskRow,
                AnsichEntityRow,
                AnsichProjectionErrorRow,
            ):
                await session.execute(delete(model))
            await session.execute(
                update(AnsichProjectionJobRow).values(
                    status="pending",
                    attempts=0,
                    available_at=datetime.now(UTC),
                    dependency_pending_since=None,
                    lease_owner=None,
                    lease_expires_at=None,
                    last_error=None,
                    # Invalidate any lease this re-pend just took away (see the
                    # docstring). The counter is monotonic and is never reset:
                    # that is exactly what makes it ABA-proof.
                    lease_generation=AnsichProjectionJobRow.lease_generation + 1,
                )
            )
        self._watermark = None
        self._failed_jobs = 0
        self._latest_projected_at = None
        replayed = 0
        while True:
            processed = await self.project_pending(limit=200)
            replayed += processed
            if processed == 0:
                await self.assess_operations()
                await self._refresh_context_metrics()
                return RebuildOutcome(
                    replayed=replayed,
                    unsettled=await self._unsettled_job_count(),
                )

    async def retry_failed_projections(self, *, task_id: str | None = None) -> int:
        """Requeue failed durable jobs and settle them without deleting projections.

        A single-operator maintenance operation like ``rebuild_projections``, and
        held under the same ``_maintenance_lock`` for the same reason: the
        re-arm plus its replay must not interleave with a second operator's.

        Only ``failed`` rows are touched, and that scope is the safety property
        rather than an optimisation: a failed job carries no live lease (both
        error paths clear it before writing the status), while a ``processing``
        row belongs to a worker that is still entitled to finish it. Re-arming
        one of those would hand the same Observation to two workers at once.

        ``lease_generation`` is deliberately **not** reset here. It is monotonic
        for the lifetime of the row -- resetting it would recreate exactly the
        ABA the column exists to prevent, letting an older claim's number match
        again -- and it needs no bump either, because a failed row has no
        in-flight writer to invalidate.

        The return value is the number of rows the re-arm actually changed, so
        it can never over-report work that a concurrent state change had already
        taken off the failed list.
        """

        async with self._maintenance_lock():
            return await self._retry_failed_projections_locked(task_id=task_id)

    async def _retry_failed_projections_locked(self, *, task_id: str | None) -> int:
        re_armed = 0
        async with self._session_factory() as session, session.begin():
            failed_job_ids = select(AnsichProjectionJobRow.job_id).where(AnsichProjectionJobRow.status == "failed")
            if task_id is not None:
                failed_job_ids = failed_job_ids.join(
                    AnsichObservationRow,
                    AnsichObservationRow.obs_id == AnsichProjectionJobRow.obs_id,
                ).where(AnsichObservationRow.task_id == task_id)
            job_ids = tuple((await session.execute(failed_job_ids)).scalars())
            failed_assessor_job_ids = select(AnsichAssessorJobRow.job_id).where(AnsichAssessorJobRow.status == "failed")
            if task_id is not None:
                failed_assessor_job_ids = failed_assessor_job_ids.where(AnsichAssessorJobRow.subject_id == task_id)
            assessor_job_ids = tuple((await session.execute(failed_assessor_job_ids)).scalars())
            if job_ids:
                projection_result = await session.execute(
                    update(AnsichProjectionJobRow)
                    .where(
                        AnsichProjectionJobRow.job_id.in_(job_ids),
                        # Re-asserted at write time, so the count reports rows
                        # this call really re-armed rather than rows it selected.
                        AnsichProjectionJobRow.status == "failed",
                    )
                    .values(
                        status="pending",
                        attempts=0,
                        available_at=datetime.now(UTC),
                        dependency_pending_since=None,
                        lease_owner=None,
                        lease_expires_at=None,
                        last_error=None,
                    )
                )
                re_armed += int(projection_result.rowcount or 0)
            if assessor_job_ids:
                assessor_result = await session.execute(
                    update(AnsichAssessorJobRow)
                    .where(
                        AnsichAssessorJobRow.job_id.in_(assessor_job_ids),
                        AnsichAssessorJobRow.status == "failed",
                    )
                    .values(
                        status="pending",
                        attempts=0,
                        available_at=datetime.now(UTC),
                        dependency_pending_since=None,
                        lease_owner=None,
                        lease_expires_at=None,
                        last_error=None,
                    )
                )
                re_armed += int(assessor_result.rowcount or 0)
        if re_armed == 0:
            return 0

        while await self.project_pending(limit=200):
            pass
        await self.assess_operations()
        await self._refresh_failed_job_count()
        await self._refresh_context_metrics()
        return re_armed

    async def list_failed_jobs(
        self,
        *,
        task_id: str | None = None,
        limit: int = 100,
    ) -> list[FailedJobSummaryView]:
        async with self._session_factory() as session:
            projection_stmt = (
                select(
                    AnsichProjectionJobRow.job_id,
                    AnsichProjectionJobRow.projector_name,
                    AnsichProjectionJobRow.projector_version,
                    AnsichProjectionJobRow.status,
                    AnsichProjectionJobRow.attempts,
                    AnsichProjectionJobRow.last_error,
                    AnsichProjectionJobRow.available_at,
                    AnsichObservationRow.task_id,
                )
                .join(AnsichObservationRow, AnsichObservationRow.obs_id == AnsichProjectionJobRow.obs_id)
                .where(AnsichProjectionJobRow.status == "failed")
            )
            if task_id is not None:
                projection_stmt = projection_stmt.where(AnsichObservationRow.task_id == task_id)
            projection_rows = (await session.execute(projection_stmt)).all()

            assessor_stmt = select(
                AnsichAssessorJobRow.job_id,
                AnsichAssessorJobRow.assessor_name,
                AnsichAssessorJobRow.assessor_version,
                AnsichAssessorJobRow.status,
                AnsichAssessorJobRow.attempts,
                AnsichAssessorJobRow.last_error,
                AnsichAssessorJobRow.available_at,
                AnsichAssessorJobRow.subject_id,
            ).where(AnsichAssessorJobRow.status == "failed")
            if task_id is not None:
                assessor_stmt = assessor_stmt.where(AnsichAssessorJobRow.subject_id == task_id)
            assessor_rows = (await session.execute(assessor_stmt)).all()

        summaries = [
            FailedJobSummaryView(
                job_id=row.job_id,
                kind="projection",
                name=row.projector_name,
                version=row.projector_version,
                task_id=row.task_id,
                status=row.status,
                attempts=row.attempts,
                last_error=row.last_error,
                available_at=row.available_at,
            )
            for row in projection_rows
        ] + [
            FailedJobSummaryView(
                job_id=row.job_id,
                kind="assessor",
                name=row.assessor_name,
                version=row.assessor_version,
                task_id=row.subject_id,
                status=row.status,
                attempts=row.attempts,
                last_error=row.last_error,
                available_at=row.available_at,
            )
            for row in assessor_rows
        ]
        summaries.sort(key=lambda item: (item.available_at, item.job_id), reverse=True)
        return summaries[:limit]

    async def get_failed_job_detail(
        self,
        *,
        job_id: str,
        kind: FailedJobKind,
    ) -> FailedJobDetailView | None:
        async with self._session_factory() as session:
            if kind == "projection":
                job = await session.get(AnsichProjectionJobRow, job_id)
                if job is None:
                    return None
                job_task_id = await session.scalar(select(AnsichObservationRow.task_id).where(AnsichObservationRow.obs_id == job.obs_id))
                name, version = job.projector_name, job.projector_version
                error_rows = (await session.execute(select(AnsichProjectionErrorRow).where(AnsichProjectionErrorRow.job_id == job_id).order_by(AnsichProjectionErrorRow.occurred_at))).scalars()
            else:
                job = await session.get(AnsichAssessorJobRow, job_id)
                if job is None:
                    return None
                job_task_id = job.subject_id
                name, version = job.assessor_name, job.assessor_version
                error_rows = (await session.execute(select(AnsichAssessorErrorRow).where(AnsichAssessorErrorRow.job_id == job_id).order_by(AnsichAssessorErrorRow.occurred_at))).scalars()
            return FailedJobDetailView(
                job_id=job.job_id,
                kind=kind,
                name=name,
                version=version,
                task_id=job_task_id,
                status=job.status,
                attempts=job.attempts,
                last_error=job.last_error,
                available_at=job.available_at,
                errors=tuple(
                    FailedJobErrorView(
                        attempt=error.attempt,
                        error_type=error.error_type,
                        message=error.message,
                        occurred_at=error.occurred_at,
                    )
                    for error in error_rows
                ),
            )

    async def _claim_projection_job(
        self,
    ) -> tuple[str, str, ObservationEnvelope, int, int, int] | None:
        """Take one claimable job, raising its ``lease_generation`` by one.

        The returned generation is what the claim owns; every later write for
        this job carries it as a compare-and-set and is dropped if the row has
        moved on (see ``_complete_projection_job``).
        """

        now = datetime.now(UTC)
        async with self._session_factory() as session, session.begin():
            row = (
                await session.execute(
                    select(AnsichProjectionJobRow, AnsichObservationRow)
                    .join(AnsichObservationRow, AnsichObservationRow.obs_id == AnsichProjectionJobRow.obs_id)
                    .where(
                        AnsichProjectionJobRow.available_at <= now,
                        or_(
                            AnsichProjectionJobRow.status.in_(_CLAIMABLE_JOB_STATUSES),
                            (AnsichProjectionJobRow.status == "processing") & (AnsichProjectionJobRow.lease_expires_at <= now),
                        ),
                    )
                    .order_by(
                        AnsichObservationRow.ingest_seq,
                        _projector_priority_expression(),
                        AnsichProjectionJobRow.projector_name,
                    )
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
            ).first()
            if row is None:
                return None
            job, observation_row = row
            job.status = "processing"
            job.attempts += 1
            job.lease_owner = self._lease_owner
            job.lease_expires_at = now + timedelta(seconds=self._projector_lease_seconds)
            job.lease_generation = (job.lease_generation or 0) + 1
            claimed_generation = job.lease_generation
            observation = self._observation_from_row(observation_row)
            if observation.payload is None and observation.payload_ref_id is not None:
                payload = await session.get(AnsichPayloadRow, observation.payload_ref_id)
                if payload is None:
                    raise RuntimeError(f"Ansich payload disappeared: {observation.payload_ref_id}")
                decoded = json.loads(payload.body.decode(payload.encoding))
                if not isinstance(decoded, dict):
                    raise ValueError("Ansich projection payload must decode to an object")
                observation = observation.model_copy(update={"payload": decoded, "payload_ref_id": None})
            return (
                job.job_id,
                job.projector_name,
                observation,
                observation_row.ingest_seq,
                job.attempts,
                claimed_generation,
            )

    async def _complete_projection_job(
        self,
        session: AsyncSession,
        *,
        job_id: str,
        lease_generation: int,
    ) -> bool:
        """Settle a claimed projection job, unless the claim has been taken over.

        The guard is ``WHERE job_id = :id AND lease_generation = :claimed``. A
        rowcount of zero means this worker no longer owns the outcome -- its
        lease expired and someone else claimed the row, or a rebuild re-pended
        it -- and the write is dropped **silently**: the new owner is
        responsible for the job, and raising here would only convert a
        harmless loss of a race into an error path that re-arms the row under
        the new owner's feet. A row that vanished entirely (an Observation
        deleted with its jobs) takes the same path for the same reason.

        The projection writes themselves stay committed. They are idempotent by
        construction, which is precisely the backstop this drop relies on: the
        new owner redoes the work and converges on the same read model.
        """

        result = await session.execute(
            update(AnsichProjectionJobRow)
            .where(
                AnsichProjectionJobRow.job_id == job_id,
                AnsichProjectionJobRow.lease_generation == lease_generation,
            )
            .values(
                status="completed",
                dependency_pending_since=None,
                lease_owner=None,
                lease_expires_at=None,
                last_error=None,
            )
        )
        if result.rowcount:
            return True
        self._stale_completion_count += 1
        logger.debug(
            "ansich projection job %s was taken over before generation %s could complete it",
            job_id,
            lease_generation,
        )
        return False

    async def _record_projection_error(
        self,
        job_id: str,
        attempt: int,
        exc: Exception,
        *,
        lease_generation: int,
    ) -> None:
        """Re-arm or fail a claimed job, unless the claim has been taken over.

        Carries the same generation compare-and-set as the completion path, and
        for a sharper reason: a stale error write does not merely duplicate a
        settlement, it *un-settles* a row that now belongs to someone else --
        re-arming it for a third claim while the current owner is still working,
        and charging a failed job against health for an attempt nobody owns.
        When the guard rejects the write, the durable error row and the
        degradation mark are dropped with it.

        A hard error re-arms to ``retry`` rather than ``pending``: the attempt
        was spent, and ``pending`` has to keep meaning "never attempted" for a
        health read to tell a queue from a retry loop. A dependency wait is the
        deliberate exception -- it gives its attempt back, so it is not a retry
        and stays ``pending``.
        """

        async with self._session_factory() as session, session.begin():
            job = await session.get(AnsichProjectionJobRow, job_id)
            if job is None:
                return
            obs_id = job.obs_id
            message = str(exc)[:4_000]
            now = datetime.now(UTC)
            if isinstance(exc, _ProjectionDependencyPending):
                pending_since = now if job.dependency_pending_since is None else _as_utc(job.dependency_pending_since)
                timed_out = now - pending_since >= self._projector_dependency_timeout
                values = {
                    "dependency_pending_since": pending_since,
                    "status": "failed" if timed_out else "pending",
                    "attempts": max(0, job.attempts - 1),
                    "available_at": now + timedelta(milliseconds=250),
                    "lease_owner": None,
                    "lease_expires_at": None,
                    "last_error": message,
                }
                durable_failure = timed_out
            else:
                values = {
                    "dependency_pending_since": None,
                    "status": "failed" if attempt >= self._projector_max_attempts else "retry",
                    "available_at": now + timedelta(milliseconds=250),
                    "lease_owner": None,
                    "lease_expires_at": None,
                    "last_error": message,
                }
                durable_failure = True
            if not await self._apply_job_error(
                session,
                model=AnsichProjectionJobRow,
                job_id=job_id,
                lease_generation=lease_generation,
                values=values,
            ):
                return
            if values["status"] == "failed":
                self._failed_jobs += 1
                await self._mark_projection_task_degraded(session, obs_id)
            if not durable_failure:
                return
            session.add(
                AnsichProjectionErrorRow(
                    error_id=new_id(),
                    job_id=job_id,
                    attempt=attempt,
                    error_type=type(exc).__name__,
                    message=message,
                )
            )

    async def _apply_job_error(
        self,
        session: AsyncSession,
        *,
        model: type[AnsichProjectionJobRow] | type[AnsichAssessorJobRow],
        job_id: str,
        lease_generation: int,
        values: dict[str, object],
    ) -> bool:
        """Write one guarded error re-arm; ``False`` means the claim was taken over."""

        result = await session.execute(
            update(model)
            .where(
                model.job_id == job_id,
                model.lease_generation == lease_generation,
            )
            .values(**values)
        )
        if result.rowcount:
            return True
        self._stale_completion_count += 1
        logger.debug(
            "ansich job %s was taken over before generation %s could record its error",
            job_id,
            lease_generation,
        )
        return False

    @staticmethod
    async def _mark_projection_task_degraded(
        session: AsyncSession,
        obs_id: str,
    ) -> None:
        task_id = await session.scalar(select(AnsichObservationRow.task_id).where(AnsichObservationRow.obs_id == obs_id))
        if task_id is None:
            return
        summary = await session.get(AnsichTaskSummaryRow, task_id)
        if summary is not None:
            summary.observability_status = "degraded"

    async def _claim_assessor_job(self) -> _AssessorClaim | None:
        """Claim one assessor job, absorbing its currently claimable siblings.

        Absorption flips the group's lower jobs to ``completed`` here, in the
        claim's own transaction, before the evaluation runs — so an incremental
        assessor cannot re-derive their watermarks after a rollback. The claim
        therefore also widens the durable evidence mark down to just below the
        group's lowest watermark (see ``_widen_assessor_watermark``), making the
        widening exactly as durable as the absorption that requires it.

        The mark as it stood *before* that widening is carried out of here in
        the claim, because only the widening's own transaction can still see it.
        A successful evaluation restores it (``_advance_assessor_watermark``):
        the widening exists to cover this group, not to forget what an earlier
        assessment already settled.

        Absorption is a takeover as much as the claim itself is: an absorbed
        sibling may have been leased by a worker whose lease has since expired
        and which is still evaluating it. Its ``lease_generation`` therefore
        rises too, so that worker's late completion or error write fails its
        compare-and-set instead of re-arming a job this group already settled.
        """

        now = datetime.now(UTC)
        async with self._session_factory() as session, session.begin():
            claimable = or_(
                AnsichAssessorJobRow.status.in_(_CLAIMABLE_JOB_STATUSES),
                and_(
                    AnsichAssessorJobRow.status == "processing",
                    AnsichAssessorJobRow.lease_expires_at <= now,
                ),
            )
            seed = await session.scalar(
                select(AnsichAssessorJobRow)
                .where(
                    AnsichAssessorJobRow.available_at <= now,
                    claimable,
                )
                .order_by(
                    AnsichAssessorJobRow.evidence_watermark,
                    AnsichAssessorJobRow.assessor_name,
                    AnsichAssessorJobRow.job_id,
                )
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if seed is None:
                return None
            grouped_jobs = list(
                (
                    await session.execute(
                        select(AnsichAssessorJobRow)
                        .where(
                            AnsichAssessorJobRow.subject_id == seed.subject_id,
                            AnsichAssessorJobRow.assessor_name == seed.assessor_name,
                            AnsichAssessorJobRow.assessor_version == seed.assessor_version,
                            AnsichAssessorJobRow.available_at <= now,
                            claimable,
                        )
                        .order_by(
                            AnsichAssessorJobRow.evidence_watermark.desc(),
                            AnsichAssessorJobRow.job_id.desc(),
                        )
                        .with_for_update(skip_locked=True)
                    )
                ).scalars()
            )
            if not grouped_jobs:
                return None
            job = grouped_jobs[0]
            for absorbed in grouped_jobs[1:]:
                absorbed.status = "completed"
                absorbed.lease_owner = None
                absorbed.lease_expires_at = None
                absorbed.last_error = None
                absorbed.lease_generation = (absorbed.lease_generation or 0) + 1
            job.status = "processing"
            job.attempts += 1
            job.lease_owner = self._lease_owner
            job.lease_expires_at = now + timedelta(seconds=self._projector_lease_seconds)
            job.lease_generation = (job.lease_generation or 0) + 1
            claimed_generation = job.lease_generation
            existing_mark = await session.get(
                AnsichAssessorWatermarkRow,
                (job.subject_id, job.assessor_name, job.assessor_version),
            )
            pre_claim_watermark = None if existing_mark is None else existing_mark.evidence_watermark
            await self._widen_assessor_watermark(
                session,
                subject_id=job.subject_id,
                assessor_name=job.assessor_name,
                assessor_version=job.assessor_version,
                window_start_exclusive=min(grouped.evidence_watermark for grouped in grouped_jobs) - 1,
            )
            return _AssessorClaim(
                job_id=job.job_id,
                subject_id=job.subject_id,
                assessor_name=job.assessor_name,
                evidence_watermark=job.evidence_watermark,
                attempts=job.attempts,
                lease_generation=claimed_generation,
                pre_claim_watermark=pre_claim_watermark,
            )

    async def _complete_assessor_job(
        self,
        session: AsyncSession,
        *,
        job_id: str,
        lease_generation: int,
    ) -> bool:
        """Settle a claimed assessor job under the same guard as a projection job.

        See ``_complete_projection_job``: rowcount zero means the row moved on
        (a later claim absorbed or re-claimed it) and the write is dropped
        without an exception, leaving the outcome to whoever holds it now.

        The caller decides what a drop costs, and on this path it costs the
        whole evaluation: ``_process_assessor_jobs`` turns ``False`` into
        ``_StaleAssessorClaim`` inside the evaluation's transaction so the
        assessments and the evidence mark roll back with the job status.
        """

        result = await session.execute(
            update(AnsichAssessorJobRow)
            .where(
                AnsichAssessorJobRow.job_id == job_id,
                AnsichAssessorJobRow.lease_generation == lease_generation,
            )
            .values(
                status="completed",
                dependency_pending_since=None,
                lease_owner=None,
                lease_expires_at=None,
                last_error=None,
            )
        )
        if result.rowcount:
            return True
        self._stale_completion_count += 1
        logger.debug(
            "ansich assessor job %s was taken over before generation %s could complete it",
            job_id,
            lease_generation,
        )
        return False

    async def _record_assessor_error(
        self,
        job_id: str,
        attempt: int,
        exc: Exception,
        *,
        lease_generation: int,
    ) -> None:
        """Guarded assessor re-arm; mirrors ``_record_projection_error``.

        The absorbed-sibling case is what makes the guard load-bearing here: the
        group's lower jobs are already ``completed`` by the time an earlier
        owner's evaluation fails, and an unguarded write would put one of them
        back in the queue with an error row against it.
        """

        async with self._session_factory() as session, session.begin():
            job = await session.get(AnsichAssessorJobRow, job_id)
            if job is None:
                return
            message = str(exc)[:4_000]
            now = datetime.now(UTC)
            if isinstance(exc, _ProjectionDependencyPending):
                pending_since = now if job.dependency_pending_since is None else _as_utc(job.dependency_pending_since)
                timed_out = now - pending_since >= self._projector_dependency_timeout
                values = {
                    "dependency_pending_since": pending_since,
                    "status": "failed" if timed_out else "pending",
                    "attempts": max(0, job.attempts - 1),
                    "available_at": now + timedelta(milliseconds=250),
                    "lease_owner": None,
                    "lease_expires_at": None,
                    "last_error": message,
                }
                durable_failure = timed_out
            else:
                values = {
                    "dependency_pending_since": None,
                    "status": "failed" if attempt >= self._projector_max_attempts else "retry",
                    "available_at": now + timedelta(milliseconds=250),
                    "lease_owner": None,
                    "lease_expires_at": None,
                    "last_error": message,
                }
                durable_failure = True
            if not await self._apply_job_error(
                session,
                model=AnsichAssessorJobRow,
                job_id=job_id,
                lease_generation=lease_generation,
                values=values,
            ):
                return
            if durable_failure:
                session.add(
                    AnsichAssessorErrorRow(
                        error_id=new_id(),
                        job_id=job_id,
                        attempt=attempt,
                        error_type=type(exc).__name__,
                        message=message,
                    )
                )
        await self._refresh_failed_job_count()

    async def _refresh_failed_job_count(self) -> None:
        async with self._session_factory() as session:
            projection_failures = await session.scalar(select(func.count()).select_from(AnsichProjectionJobRow).where(AnsichProjectionJobRow.status == "failed"))
            assessor_failures = await session.scalar(select(func.count()).select_from(AnsichAssessorJobRow).where(AnsichAssessorJobRow.status == "failed"))
        self._failed_jobs = int(projection_failures or 0) + int(assessor_failures or 0)

    async def _process_assessor_jobs(
        self,
        *,
        now: datetime,
        incomplete_tasks: frozenset[str],
        global_loss: bool,
        limit: int = 500,
    ) -> int:
        changed = 0
        for _ in range(limit):
            claim = await self._claim_assessor_job()
            if claim is None:
                break
            job_id = claim.job_id
            task_id = claim.subject_id
            assessor_name = claim.assessor_name
            evidence_watermark = claim.evidence_watermark
            attempt = claim.attempts
            lease_generation = claim.lease_generation
            # Counted inside the transaction, added to the caller's total only
            # once it commits: a rolled-back evaluation changed nothing.
            evaluated = 0
            try:
                async with self._session_factory() as session, session.begin():
                    if assessor_name == ACTION_REPETITION_ASSESSOR.name:
                        assessment = await self._assess_action_repetition_at(
                            session,
                            task_id=task_id,
                            evidence_watermark=evidence_watermark,
                            now=now,
                        )
                        signal = assessment.model_copy(update={"field_name": "behavior_signal:action-repetition"})
                        assertion, assertion_changed = await self._persist_assessment(session, signal)
                        evaluated += int(assertion_changed)
                        evaluated += await self._reconcile_alerts_for_assessment(
                            session,
                            assessment=assessment,
                            source_assertion_id=assertion.assertion_id,
                            now=now,
                        )
                        evaluated += await self._refresh_behavior_belief(
                            session,
                            task_id=task_id,
                            now=now,
                        )
                    elif assessor_name == TOOL_FREQUENCY_ASSESSOR.name:
                        assessments = await self._assess_tool_frequency_at(
                            session,
                            task_id=task_id,
                            evidence_watermark=evidence_watermark,
                            now=now,
                        )
                        for assessment in assessments:
                            assertion, assertion_changed = await self._persist_assessment(
                                session,
                                assessment,
                            )
                            evaluated += int(assertion_changed)
                            evaluated += await self._reconcile_alerts_for_assessment(
                                session,
                                assessment=assessment,
                                source_assertion_id=assertion.assertion_id,
                                now=now,
                            )
                    elif assessor_name == ABSOLUTE_LIMIT_ASSESSOR.name:
                        result = await self._assess_absolute_limits_at(
                            session,
                            task_id=task_id,
                            evidence_watermark=evidence_watermark,
                            now=now,
                            usage_complete=(not global_loss and task_id not in incomplete_tasks),
                        )
                        for assessment in result.budget_health:
                            assertion, assertion_changed = await self._persist_assessment(
                                session,
                                assessment,
                            )
                            evaluated += int(assertion_changed)
                            evaluated += await self._reconcile_alerts_for_assessment(
                                session,
                                assessment=assessment,
                                source_assertion_id=assertion.assertion_id,
                                now=now,
                            )
                        signal = result.behavior.model_copy(update={"field_name": "behavior_signal:absolute-limit"})
                        _, signal_changed = await self._persist_assessment(
                            session,
                            signal,
                        )
                        evaluated += int(signal_changed)
                        evaluated += await self._refresh_behavior_belief(
                            session,
                            task_id=task_id,
                            now=now,
                        )
                    elif assessor_name == CONFIGURATION_DRIFT_ASSESSOR.name:
                        assessment = await self._assess_configuration_drift_at(
                            session,
                            task_id=task_id,
                            evidence_watermark=evidence_watermark,
                            now=now,
                        )
                        if assessment is not None:
                            assertion, assertion_changed = await self._persist_assessment(session, assessment)
                            evaluated += int(assertion_changed)
                            evaluated += await self._reconcile_alerts_for_assessment(
                                session,
                                assessment=assessment,
                                source_assertion_id=assertion.assertion_id,
                                now=now,
                            )
                    elif assessor_name == SCOPE_SAFETY_ASSESSOR.name:
                        window_start_exclusive = await self._scope_safety_window_start(
                            session,
                            task_id=task_id,
                        )
                        results = await self._assess_scope_safety_at(
                            session,
                            task_id=task_id,
                            evidence_watermark=evidence_watermark,
                            window_start_exclusive=window_start_exclusive,
                            now=now,
                        )
                        for result in results:
                            for assessment in result.conclusions:
                                assertion, assertion_changed = await self._persist_assessment(
                                    session,
                                    assessment,
                                )
                                evaluated += int(assertion_changed)
                                conclusion = await session.get(
                                    AnsichScopeConclusionRow,
                                    assertion.assertion_id,
                                )
                                if conclusion is None:
                                    session.add(
                                        AnsichScopeConclusionRow(
                                            assertion_id=assertion.assertion_id,
                                            tool_call_id=assessment.subject_id,
                                            conclusion_kind=str(assessment.value["conclusion"]),
                                        )
                                    )
                                evaluated += await self._reconcile_alerts_for_assessment(
                                    session,
                                    assessment=assessment,
                                    source_assertion_id=assertion.assertion_id,
                                    now=now,
                                )
                        # Same transaction as the conclusions above, so the mark
                        # is durable exactly when they are: a failure rolls both
                        # back and the retry re-opens the same window.
                        await self._advance_assessor_watermark(
                            session,
                            task_id=task_id,
                            assessor=SCOPE_SAFETY_ASSESSOR,
                            evidence_watermark=evidence_watermark,
                            pre_claim_watermark=claim.pre_claim_watermark,
                        )
                    else:
                        raise ValueError(f"unknown Ansich assessor: {assessor_name}")
                    summary = await session.get(AnsichTaskSummaryRow, task_id)
                    if summary is not None and summary.control_value in {
                        "completed",
                        "failed",
                        "interrupted",
                    }:
                        evaluated += await self._resolve_terminal_alerts(
                            session,
                            task_id=task_id,
                            now=now,
                        )
                    if not await self._complete_assessor_job(
                        session,
                        job_id=job_id,
                        lease_generation=lease_generation,
                    ):
                        # Controller ruling PB4: on the assessor path the new
                        # owner owns the outcome *in full*. Everything above --
                        # assertions, conclusions, alert episodes and the
                        # evidence mark -- is one indivisible statement about a
                        # window this worker no longer has the right to settle,
                        # and the mark is the half that cannot be repaired by
                        # idempotency (unlike the projection path, where RB4(5)
                        # is a real backstop): committing it would tell the new
                        # owner that a band it has not judged is already
                        # covered, and its own window start is read from that
                        # mark. So the whole transaction goes back.
                        raise _StaleAssessorClaim(job_id)
                changed += evaluated
            except _StaleAssessorClaim:
                # Not a failure of the work: no durable error row, no re-arm,
                # no health charge. ``_complete_assessor_job`` has already
                # counted the drop. Whoever holds the job now will redo it.
                continue
            except Exception as exc:
                await self._record_assessor_error(
                    job_id,
                    attempt,
                    exc,
                    lease_generation=lease_generation,
                )
        return changed

    async def _scope_safety_window_start(
        self,
        session: AsyncSession,
        *,
        task_id: str,
    ) -> int | None:
        """Exclusive lower bound of the evidence window to re-judge.

        ``None`` means cold start (no previous successful assessment for this
        Task), which keeps the original full-Task scan.

        The mark is the single source of truth: ``_claim_assessor_job`` has
        already widened it below the claimed group's lowest watermark, so this
        read needs no second term to cover a job whose watermark sits under the
        last settled one. The window therefore always covers every observation
        whose own assessor job this evaluation is settling, plus everything
        since the last successful assessment.
        """

        mark = await session.get(
            AnsichAssessorWatermarkRow,
            (task_id, SCOPE_SAFETY_ASSESSOR.name, SCOPE_SAFETY_ASSESSOR.version),
        )
        return None if mark is None else mark.evidence_watermark

    @staticmethod
    async def _widen_assessor_watermark(
        session: AsyncSession,
        *,
        subject_id: str,
        assessor_name: str,
        assessor_version: str,
        window_start_exclusive: int,
    ) -> None:
        """Lower an existing mark so it cannot exclude the claimed group.

        Lowering is always safe — it can only widen a future window, never skip
        evidence — and it must happen in the claim's transaction rather than the
        evaluation's: absorbed siblings are already ``completed`` by the time
        the evaluation runs, so a rolled-back evaluation would otherwise leave
        the retry with no way to re-derive their watermarks.

        No row means cold start, which already re-judges everything, and a group
        entirely above the mark widens nothing.
        """

        mark = await session.get(
            AnsichAssessorWatermarkRow,
            (subject_id, assessor_name, assessor_version),
        )
        if mark is None or mark.evidence_watermark <= window_start_exclusive:
            return
        mark.evidence_watermark = window_start_exclusive
        mark.updated_at = datetime.now(UTC)

    @staticmethod
    async def _advance_assessor_watermark(
        session: AsyncSession,
        *,
        task_id: str,
        assessor: AssessorDescriptor,
        evidence_watermark: int,
        pre_claim_watermark: int | None = None,
    ) -> None:
        """Settle the mark at everything this worker knows to be judged.

        Two numbers bound that: the watermark this evaluation just covered, and
        the mark the claim found before widening it down over the group. The
        second one is the fix for F10-10 hypothesis (c): the claim lowers the
        mark unconditionally so the group's lowest evidence is inside the
        window, and an evaluation whose own watermark sits *under* an
        already-advanced mark would otherwise leave that lowering in place
        forever — every later trigger then re-opens the whole band and re-judges
        every converged ToolCall in it. Restoring the pre-claim mark cannot skip
        anything: it is itself a value some earlier evaluation reached by
        judging everything below it, and this evaluation judged the window the
        widening opened.
        """

        target = evidence_watermark if pre_claim_watermark is None else max(evidence_watermark, pre_claim_watermark)
        mark = await session.get(
            AnsichAssessorWatermarkRow,
            (task_id, assessor.name, assessor.version),
        )
        if mark is None:
            session.add(
                AnsichAssessorWatermarkRow(
                    subject_id=task_id,
                    assessor_name=assessor.name,
                    assessor_version=assessor.version,
                    evidence_watermark=target,
                    updated_at=datetime.now(UTC),
                )
            )
            return
        # This advance path never lowers: a job claimed out of watermark order
        # settles evidence the higher assessment already covered. Lowering the
        # mark is a claim-time act only (``_widen_assessor_watermark``).
        if target > mark.evidence_watermark:
            mark.evidence_watermark = target
            mark.updated_at = datetime.now(UTC)

    @staticmethod
    def _scope_safety_evidence_subject(row: AnsichObservationRow) -> str | None:
        """``tool_call_id`` an observation carries, read without validating it.

        Returns ``None`` when the subject cannot be read cheaply (an
        externalized payload, or a kind that carries no ToolCall at all, such as
        ``scope.snapshotted``); callers must not treat that as "belongs to no
        ToolCall".
        """

        payload = row.payload_json
        if not isinstance(payload, dict):
            return None
        if row.kind.startswith("authorization."):
            carrier = payload.get("snapshot")
        elif row.kind.startswith("effect."):
            carrier = payload.get("effect")
        else:
            return None
        if not isinstance(carrier, dict):
            return None
        tool_call_id = carrier.get("tool_call_id")
        return tool_call_id if isinstance(tool_call_id, str) else None

    async def _scope_safety_tool_calls_in_window(
        self,
        session: AsyncSession,
        *,
        task_id: str,
        window_start_exclusive: int,
        evidence_watermark: int,
    ) -> frozenset[str] | None:
        """ToolCalls named by evidence new since the previous assessment.

        ``None`` asks the caller to fall back to the full scan, which is what an
        observation whose subject cannot be read cheaply must produce: skipping
        it would silently drop a conclusion instead of degrading to the previous
        behaviour.
        """

        rows = list(
            (
                await session.execute(
                    select(AnsichObservationRow)
                    .where(
                        AnsichObservationRow.task_id == task_id,
                        AnsichObservationRow.ingest_seq > window_start_exclusive,
                        AnsichObservationRow.ingest_seq <= evidence_watermark,
                        AnsichObservationRow.kind.in_(_SAFETY_PROJECTION_KINDS),
                    )
                    .order_by(AnsichObservationRow.ingest_seq)
                )
            ).scalars()
        )
        affected: set[str] = set()
        for row in rows:
            if row.kind == "scope.snapshotted":
                # Scope evidence is Task-scoped and names no ToolCall; it feeds
                # the Scope projection, never a per-ToolCall conclusion.
                continue
            tool_call_id = self._scope_safety_evidence_subject(row)
            if tool_call_id is None:
                return None
            affected.add(tool_call_id)
        return frozenset(affected)

    async def _assess_scope_safety_at(
        self,
        session: AsyncSession,
        *,
        task_id: str,
        evidence_watermark: int,
        window_start_exclusive: int | None,
        now: datetime,
    ) -> tuple[ScopeSafetyAssessmentResult, ...]:
        """Re-judge the ToolCalls this trigger actually carries evidence for.

        Each conclusion is a pure function of one ``tool_call_id``'s own
        snapshots and effects, so a ToolCall with no new evidence would be
        re-judged to the identical verdict. Its stored conclusion is therefore
        left untouched rather than rewritten — ``as_of`` is stamped with the
        assessment time, so a rewrite would append a fresh assertion and a fresh
        conclusion row every trigger rather than being absorbed by
        ``_persist_assessment``'s dedupe.
        """

        affected: frozenset[str] | None = None
        if window_start_exclusive is not None:
            affected = await self._scope_safety_tool_calls_in_window(
                session,
                task_id=task_id,
                window_start_exclusive=window_start_exclusive,
                evidence_watermark=evidence_watermark,
            )
            if affected is not None and not affected:
                return ()
        rows = list(
            (
                await session.execute(
                    select(AnsichObservationRow)
                    .where(
                        AnsichObservationRow.task_id == task_id,
                        AnsichObservationRow.ingest_seq <= evidence_watermark,
                        AnsichObservationRow.kind.in_(_SAFETY_PROJECTION_KINDS),
                    )
                    .order_by(AnsichObservationRow.ingest_seq)
                )
            ).scalars()
        )
        snapshots_by_tool: dict[str, dict[str, AuthorizationSnapshot]] = {}
        effects_by_tool: dict[str, dict[str, ToolEffect]] = {}
        for row in rows:
            payload = row.payload_json or {}
            # A re-judged ToolCall still needs its complete evidence, so only
            # rows that positively belong to an unaffected ToolCall are skipped;
            # anything unreadable keeps the original validation behaviour.
            if affected is not None and (subject := self._scope_safety_evidence_subject(row)) is not None and subject not in affected:
                continue
            if row.kind.startswith("authorization."):
                snapshot = AuthorizationSnapshot.model_validate(payload.get("snapshot"), strict=False)
                snapshots_by_tool.setdefault(snapshot.tool_call_id, {})[snapshot.snapshot_id] = snapshot
            elif row.kind.startswith("effect."):
                effect = ToolEffect.model_validate(payload.get("effect"), strict=False)
                effects_by_tool.setdefault(effect.tool_call_id, {})[effect.effect_id] = effect
        tool_call_ids = sorted(snapshots_by_tool.keys() | effects_by_tool.keys())
        return tuple(
            assess_scope_safety(
                tool_call_id=tool_call_id,
                authorization_snapshots=tuple(
                    sorted(
                        snapshots_by_tool.get(tool_call_id, {}).values(),
                        key=lambda item: (item.evaluated_at, item.snapshot_id),
                    )
                ),
                effects=tuple(effects_by_tool.get(tool_call_id, {}).values()),
                now=now,
            )
            for tool_call_id in tool_call_ids
        )

    async def _assess_configuration_drift_at(
        self,
        session: AsyncSession,
        *,
        task_id: str,
        evidence_watermark: int,
        now: datetime,
    ) -> Assessment | None:
        binding = await session.get(AnsichTaskAgentReleaseRow, task_id)
        if binding is None:
            return None
        model_component = await session.get(
            AnsichAgentReleaseComponentRow,
            (binding.release_id, "model"),
        )
        if model_component is None:
            return None
        model_summary = model_component.summary_json or {}
        behavior_parameters = model_summary.get("behavior_parameters")
        provider_model = behavior_parameters.get("model") if isinstance(behavior_parameters, dict) else None
        has_provider_model = isinstance(provider_model, str) and bool(provider_model.strip())
        effective_model = provider_model if has_provider_model else model_summary.get("effective")
        expected_model_source = "provider_model" if has_provider_model else "registry_alias"
        if not isinstance(effective_model, str) or not effective_model:
            return None
        latest = (
            await session.execute(
                select(AnsichLlmAttemptRow, AnsichObservationRow)
                .join(
                    AnsichObservationRow,
                    AnsichObservationRow.obs_id == AnsichLlmAttemptRow.response_obs_id,
                )
                .where(
                    AnsichLlmAttemptRow.task_id == task_id,
                    AnsichObservationRow.ingest_seq <= evidence_watermark,
                )
                .order_by(
                    AnsichObservationRow.ingest_seq.desc(),
                    AnsichLlmAttemptRow.attempt_id.desc(),
                )
                .limit(1)
            )
        ).first()
        if latest is None:
            release = await session.get(AnsichAgentReleaseRow, binding.release_id)
            as_of = now if release is None else _as_utc(release.created_at)
            return assess_configuration_drift(
                task_id=task_id,
                effective_model=effective_model,
                expected_model_source=expected_model_source,
                provider_reported_model=None,
                response_obs_id=None,
                as_of=as_of,
                asserted_at=now,
            )
        attempt, response = latest
        return assess_configuration_drift(
            task_id=task_id,
            effective_model=effective_model,
            expected_model_source=expected_model_source,
            provider_reported_model=attempt.provider_model,
            response_obs_id=response.obs_id,
            as_of=_as_utc(response.occurred_at),
            asserted_at=now,
        )

    async def _assess_action_repetition_at(
        self,
        session: AsyncSession,
        *,
        task_id: str,
        evidence_watermark: int,
        now: datetime,
    ) -> Assessment:
        rows = list(
            (
                await session.execute(
                    _action_repetition_rows_statement(
                        task_id=task_id,
                        evidence_watermark=evidence_watermark,
                    )
                )
            ).all()
        )
        step_inputs: dict[
            str,
            tuple[
                AnsichStepRow,
                AnsichObservationRow,
                list[ToolAction],
            ],
        ] = {}
        for step, closed_observation, tool, issued_observation in rows:
            step_input = step_inputs.get(step.entity_id)
            if step_input is None:
                step_input = (step, closed_observation, [])
                step_inputs[step.entity_id] = step_input
            if tool is None or issued_observation is None:
                continue
            step_input[2].append(
                ToolAction(
                    tool_name=tool.tool_name,
                    args=({} if tool.args_preview_json is None else tool.args_preview_json),
                    evidence_obs_id=issued_observation.obs_id,
                )
            )
        steps = []
        for step, closed_observation, tools in step_inputs.values():
            steps.append(
                build_step_action(
                    step_id=step.entity_id,
                    step_seq=step.step_seq,
                    occurred_at=_as_utc(closed_observation.occurred_at),
                    tools=tuple(tools),
                )
            )
        assessment = assess_action_repetition(
            task_id=task_id,
            steps=steps,
            now=now,
            exact_repetition_window=self._exact_repetition_window,
        )
        if steps:
            return assessment
        watermark_occurred_at = await session.scalar(select(AnsichObservationRow.occurred_at).where(AnsichObservationRow.ingest_seq == evidence_watermark))
        return assessment.model_copy(update={"as_of": (now if watermark_occurred_at is None else _as_utc(watermark_occurred_at))})

    async def _assess_tool_frequency_at(
        self,
        session: AsyncSession,
        *,
        task_id: str,
        evidence_watermark: int,
        now: datetime,
    ) -> tuple[Assessment, ...]:
        rows = list(
            (
                await session.execute(
                    select(AnsichToolCallRow, AnsichObservationRow)
                    .join(
                        AnsichObservationRow,
                        AnsichObservationRow.obs_id == AnsichToolCallRow.issued_obs_id,
                    )
                    .where(
                        AnsichToolCallRow.task_id == task_id,
                        AnsichObservationRow.ingest_seq <= evidence_watermark,
                    )
                    .order_by(
                        AnsichObservationRow.occurred_at,
                        AnsichObservationRow.obs_id,
                    )
                )
            ).all()
        )
        watermark_occurred_at = await session.scalar(select(AnsichObservationRow.occurred_at).where(AnsichObservationRow.ingest_seq == evidence_watermark))
        evaluated_at = now if watermark_occurred_at is None else _as_utc(watermark_occurred_at)
        assessments = assess_tool_frequency(
            task_id=task_id,
            occurrences=tuple(
                ToolOccurrence(
                    tool_name=tool.tool_name,
                    occurred_at=_as_utc(observation.occurred_at),
                    evidence_obs_id=observation.obs_id,
                )
                for tool, observation in rows
            ),
            now=evaluated_at,
            window_seconds=self._tool_frequency_window_seconds,
            threshold=self._tool_frequency_threshold,
        )
        return tuple(assessment.model_copy(update={"asserted_at": now}) for assessment in assessments)

    async def _assess_absolute_limits_at(
        self,
        session: AsyncSession,
        *,
        task_id: str,
        evidence_watermark: int,
        now: datetime,
        usage_complete: bool,
    ) -> AbsoluteLimitAssessmentResult:
        configured_rows = list(
            (
                await session.execute(
                    select(AnsichTaskBudgetRow, AnsichObservationRow)
                    .join(
                        AnsichObservationRow,
                        AnsichObservationRow.obs_id == AnsichTaskBudgetRow.configured_obs_id,
                    )
                    .where(
                        AnsichTaskBudgetRow.task_id == task_id,
                        AnsichObservationRow.ingest_seq <= evidence_watermark,
                    )
                    .order_by(AnsichObservationRow.ingest_seq)
                )
            ).all()
        )
        effective_budget_rows: dict[tuple[str, str], AnsichTaskBudgetRow] = {}
        for budget_row, _ in configured_rows:
            effective_budget_rows[(budget_row.dimension, budget_row.aggregation_scope)] = budget_row
        budgets = tuple(
            TaskBudgetView(
                entity_id=row.entity_id,
                task_id=row.task_id,
                dimension=cast(UsageDimension, row.dimension),
                aggregation_scope=cast(AggregationScope, row.aggregation_scope),
                warning_limit=row.warning_limit,
                hard_limit=row.hard_limit,
                enforcement=row.enforcement,
                source_kind=cast(BudgetSourceKind, row.source_kind),
                requested_value=row.requested_value,
                effective_value=row.effective_value,
                configured_obs_id=row.configured_obs_id,
            )
            for row in effective_budget_rows.values()
        )
        contribution_rows = list(
            (
                await session.execute(
                    select(AnsichUsageContributionRow, AnsichObservationRow)
                    .join(
                        AnsichObservationRow,
                        AnsichObservationRow.obs_id == AnsichUsageContributionRow.source_obs_id,
                    )
                    .where(
                        AnsichUsageContributionRow.aggregate_task_id == task_id,
                        AnsichObservationRow.ingest_seq <= evidence_watermark,
                    )
                    .order_by(
                        AnsichUsageContributionRow.as_of,
                        AnsichUsageContributionRow.source_obs_id,
                    )
                )
            ).all()
        )
        values: dict[tuple[UsageDimension, AggregationScope], int] = {}
        as_of: dict[tuple[UsageDimension, AggregationScope], datetime] = {}
        evidence: dict[tuple[UsageDimension, AggregationScope], list[str]] = {}
        wall_time_by_source: dict[tuple[UsageDimension, AggregationScope], dict[str, int]] = {}
        wall_time_evidence_rows: dict[
            tuple[UsageDimension, AggregationScope],
            list[WallTimeEvidenceRow],
        ] = {}
        for contribution, source_observation in contribution_rows:
            scopes: tuple[AggregationScope, ...] = ("local", "inclusive") if contribution.source_task_id == task_id else ("inclusive",)
            for scope in scopes:
                key = (cast(UsageDimension, contribution.dimension), scope)
                if contribution.dimension == "wall_time_ms":
                    source_values = wall_time_by_source.setdefault(key, {})
                    source_values[contribution.source_task_id] = max(
                        source_values.get(contribution.source_task_id, 0),
                        contribution.delta,
                    )
                else:
                    values[key] = values.get(key, 0) + contribution.delta
                as_of[key] = max(
                    as_of.get(key, _as_utc(contribution.as_of)),
                    _as_utc(contribution.as_of),
                )
                if contribution.dimension != "wall_time_ms":
                    evidence.setdefault(key, []).append(contribution.source_obs_id)
                else:
                    wall_time_evidence_rows.setdefault(key, []).append(
                        WallTimeEvidenceRow(
                            source_task_id=contribution.source_task_id,
                            source_obs_id=contribution.source_obs_id,
                            delta=contribution.delta,
                            from_heartbeat=source_observation.kind == "task.heartbeat",
                        )
                    )
        for key, source_values in wall_time_by_source.items():
            values[key] = sum(source_values.values())
            evidence[key] = list(order_wall_time_evidence(wall_time_evidence_rows.get(key, ())))

        heartbeat_rows = list(
            (
                await session.execute(
                    select(AnsichTaskHeartbeatRow, AnsichObservationRow)
                    .join(
                        AnsichObservationRow,
                        AnsichObservationRow.obs_id == AnsichTaskHeartbeatRow.heartbeat_obs_id,
                    )
                    .where(
                        AnsichTaskHeartbeatRow.task_id == task_id,
                        AnsichObservationRow.ingest_seq <= evidence_watermark,
                    )
                    .order_by(
                        AnsichTaskHeartbeatRow.elapsed_ms.desc(),
                        AnsichObservationRow.ingest_seq.desc(),
                    )
                    # Only the highest-elapsed row is read; without the LIMIT
                    # this assessment materialized every historical tick, which
                    # is the same read amplification P8-M2 removes on the
                    # contribution side.
                    .limit(1)
                )
            ).all()
        )
        if heartbeat_rows:
            heartbeat, _ = heartbeat_rows[0]
            wall_time_key = (
                cast(UsageDimension, "wall_time_ms"),
                cast(AggregationScope, "local"),
            )
            heartbeat_as_of = _as_utc(heartbeat.occurred_at)
            values[wall_time_key] = max(
                values.get(wall_time_key, 0),
                heartbeat.elapsed_ms,
            )
            as_of[wall_time_key] = max(
                as_of.get(wall_time_key, heartbeat_as_of),
                heartbeat_as_of,
            )
            wall_time_evidence = evidence.setdefault(wall_time_key, [])
            if heartbeat.heartbeat_obs_id not in wall_time_evidence:
                wall_time_evidence.append(heartbeat.heartbeat_obs_id)

        usage = tuple(
            TaskUsageValue(
                dimension=dimension,
                aggregation_scope=scope,
                value=value,
                as_of=as_of[(dimension, scope)],
                complete_through_ingest_seq=evidence_watermark,
            )
            for (dimension, scope), value in values.items()
        )
        watermark_occurred_at = await session.scalar(select(AnsichObservationRow.occurred_at).where(AnsichObservationRow.ingest_seq == evidence_watermark))
        evaluated_at = now if watermark_occurred_at is None else _as_utc(watermark_occurred_at)
        result = assess_absolute_limits(
            task_id=task_id,
            budgets=budgets,
            usage=usage,
            now=evaluated_at,
            usage_complete=usage_complete,
            usage_evidence={key: tuple(obs_ids) for key, obs_ids in evidence.items()},
        )
        return AbsoluteLimitAssessmentResult(
            budget_health=tuple(assessment.model_copy(update={"asserted_at": now}) for assessment in result.budget_health),
            behavior=result.behavior.model_copy(update={"asserted_at": now}),
        )

    async def _persist_assessment(
        self,
        session: AsyncSession,
        assessment: Assessment,
    ) -> tuple[AnsichBeliefAssertionRow, bool]:
        if await session.get(AnsichEntityRow, assessment.subject_id) is None:
            raise _ProjectionDependencyPending(f"Assessment {assessment.field_name} is waiting for subject Entity {assessment.subject_id}")
        existing_rows = list(
            (
                await session.execute(
                    select(AnsichBeliefAssertionRow)
                    .where(
                        AnsichBeliefAssertionRow.subject_id == assessment.subject_id,
                        AnsichBeliefAssertionRow.field_name == assessment.field_name,
                        AnsichBeliefAssertionRow.assessor_name == assessment.assessor.name,
                        AnsichBeliefAssertionRow.assessor_version == assessment.assessor.version,
                        AnsichBeliefAssertionRow.config_hash == assessment.config_hash,
                    )
                    .order_by(
                        AnsichBeliefAssertionRow.as_of.desc(),
                        AnsichBeliefAssertionRow.asserted_at.desc(),
                        AnsichBeliefAssertionRow.assertion_id.desc(),
                    )
                )
            ).scalars()
        )
        expected_evidence = tuple((item.obs_id, item.role) for item in assessment.evidence)
        for existing in existing_rows:
            evidence = tuple(
                (
                    await session.execute(
                        select(
                            AnsichBeliefEvidenceRow.obs_id,
                            AnsichBeliefEvidenceRow.evidence_role,
                        )
                        .where(AnsichBeliefEvidenceRow.assertion_id == existing.assertion_id)
                        .order_by(AnsichBeliefEvidenceRow.ordinal)
                    )
                ).all()
            )
            if (
                existing.value_json == assessment.value
                and evidence == expected_evidence
                and _as_utc(existing.as_of) == assessment.as_of
                and existing.authority_class == assessment.authority_class
                and existing.fidelity_class == assessment.fidelity_class
                and existing.confidence == assessment.confidence
            ):
                return existing, False

        assertion = AnsichBeliefAssertionRow(
            assertion_id=new_id(),
            subject_id=assessment.subject_id,
            field_name=assessment.field_name,
            value_json=assessment.value,
            as_of=assessment.as_of,
            asserted_at=assessment.asserted_at,
            source_name=assessment.assessor.name,
            source_version=assessment.assessor.version,
            assessor_name=assessment.assessor.name,
            assessor_version=assessment.assessor.version,
            config_hash=assessment.config_hash,
            authority_class=assessment.authority_class,
            fidelity_class=assessment.fidelity_class,
            confidence=assessment.confidence,
        )
        session.add(assertion)
        for ordinal, evidence in enumerate(assessment.evidence):
            session.add(
                AnsichBeliefEvidenceRow(
                    assertion_id=assertion.assertion_id,
                    obs_id=evidence.obs_id,
                    evidence_role=evidence.role,
                    ordinal=ordinal,
                )
            )
        await session.flush()
        await self._resolve_current_assessment(
            session,
            subject_id=assessment.subject_id,
            field_name=assessment.field_name,
        )
        return assertion, True

    async def _resolve_current_assessment(
        self,
        session: AsyncSession,
        *,
        subject_id: str,
        field_name: str,
    ) -> None:
        assertion_rows = list(
            (
                await session.execute(
                    select(AnsichBeliefAssertionRow).where(
                        AnsichBeliefAssertionRow.subject_id == subject_id,
                        AnsichBeliefAssertionRow.field_name == field_name,
                    )
                )
            ).scalars()
        )
        assertions = []
        for row in assertion_rows:
            evidence_rows = list((await session.execute(select(AnsichBeliefEvidenceRow).where(AnsichBeliefEvidenceRow.assertion_id == row.assertion_id).order_by(AnsichBeliefEvidenceRow.ordinal))).scalars())
            assertions.append(
                BeliefAssertion.model_validate(
                    {
                        "assertion_id": row.assertion_id,
                        "subject_id": row.subject_id,
                        "field_name": row.field_name,
                        "value": row.value_json,
                        "as_of": _as_utc(row.as_of),
                        "asserted_at": _as_utc(row.asserted_at),
                        "assessor": NamedVersion(
                            name=row.assessor_name,
                            version=row.assessor_version,
                        ),
                        "config_hash": row.config_hash,
                        "authority_class": row.authority_class,
                        "fidelity_class": row.fidelity_class,
                        "confidence": row.confidence,
                        "evidence": tuple(
                            EvidenceRef(
                                obs_id=evidence.obs_id,
                                role=evidence.evidence_role,
                            )
                            for evidence in evidence_rows
                        ),
                    }
                )
            )
        resolved = resolve_current_belief(assertions, resolver=DEFAULT_RESOLVER)
        current = await session.get(
            AnsichCurrentBeliefRow,
            (subject_id, field_name),
        )
        if current is None:
            session.add(
                AnsichCurrentBeliefRow(
                    subject_id=subject_id,
                    field_name=field_name,
                    assertion_id=resolved.selected.assertion_id,
                    resolver_name=resolved.resolver.name,
                    resolver_version=resolved.resolver.version,
                )
            )
        else:
            current.assertion_id = resolved.selected.assertion_id
            current.resolver_name = resolved.resolver.name
            current.resolver_version = resolved.resolver.version

    async def _refresh_behavior_belief(
        self,
        session: AsyncSession,
        *,
        task_id: str,
        now: datetime,
    ) -> int:
        signal_rows = list(
            (
                await session.execute(
                    select(
                        AnsichCurrentBeliefRow,
                        AnsichBeliefAssertionRow,
                    )
                    .join(
                        AnsichBeliefAssertionRow,
                        AnsichBeliefAssertionRow.assertion_id == AnsichCurrentBeliefRow.assertion_id,
                    )
                    .where(
                        AnsichCurrentBeliefRow.subject_id == task_id,
                        AnsichCurrentBeliefRow.field_name.like("behavior_signal:%"),
                    )
                    .order_by(AnsichCurrentBeliefRow.field_name)
                )
            ).all()
        )
        active = [(current, assertion) for current, assertion in signal_rows if assertion.value_json.get("value") == "runaway"]
        evidence: list[EvidenceRef] = []
        seen_obs_ids: set[str] = set()
        for _, assertion in active:
            evidence_rows = list((await session.execute(select(AnsichBeliefEvidenceRow).where(AnsichBeliefEvidenceRow.assertion_id == assertion.assertion_id).order_by(AnsichBeliefEvidenceRow.ordinal))).scalars())
            for item in evidence_rows:
                if item.obs_id in seen_obs_ids:
                    continue
                seen_obs_ids.add(item.obs_id)
                evidence.append(
                    EvidenceRef(
                        obs_id=item.obs_id,
                        role=item.evidence_role,
                    )
                )
        assessment = Assessment(
            subject_id=task_id,
            field_name="behavior",
            value={
                "value": "runaway" if active else "unassessed",
                "reason": ("runaway_signal_present" if active else "no_runaway_signal"),
                "signals": [
                    {
                        "field_name": current.field_name,
                        "assessor_name": assertion.assessor_name,
                        "assertion_id": assertion.assertion_id,
                        "reason": assertion.value_json.get("reason"),
                        "shadow": bool(assertion.value_json.get("shadow", False)),
                    }
                    for current, assertion in active
                ],
                "shadow": bool(active) and all(bool(assertion.value_json.get("shadow", False)) for _, assertion in active),
            },
            as_of=max(
                (_as_utc(assertion.as_of) for _, assertion in signal_rows),
                default=now,
            ),
            asserted_at=now,
            assessor=NamedVersion(
                name="behavior-aggregate",
                version="1.0.0",
            ),
            config_hash=canonical_config_hash({"policy": "any-current-runaway-signal", "version": 1}),
            authority_class="configured_rule",
            fidelity_class="rule",
            evidence=tuple(evidence),
        )
        _, did_change = await self._persist_assessment(session, assessment)
        return int(did_change)

    @staticmethod
    def _alert_episode_from_row(
        row: AnsichAlertRow,
        *,
        evidence: tuple[EvidenceRef, ...] = (),
    ) -> AlertEpisode:
        return AlertEpisode.model_validate(
            {
                "alert_id": row.entity_id,
                "alert_key": row.alert_key,
                "episode": row.episode,
                "alert_type": row.alert_type,
                "subject_id": row.subject_id,
                "rule": NamedVersion(
                    name=row.rule_name,
                    version=row.rule_version,
                ),
                "rule_config_hash": row.rule_config_hash,
                "stable_condition_key": row.stable_condition_key,
                "source_assertion_id": row.source_assertion_id,
                "opened_at": _as_utc(row.opened_at),
                "as_of": _as_utc(row.as_of),
                "updated_at": _as_utc(row.updated_at),
                "resolved_at": (None if row.resolved_at is None else _as_utc(row.resolved_at)),
                "resolution_reason": row.resolution_reason,
                "workflow_state": row.workflow_state,
                "workflow_version": row.workflow_version,
                "dismissal_reason": row.dismissal_reason,
                "severity": row.severity,
                "shadow": row.shadow,
                "evidence": evidence,
            }
        )

    async def _load_alert_evidence(
        self,
        session: AsyncSession,
        *,
        alert_id: str,
    ) -> tuple[EvidenceRef, ...]:
        rows = list((await session.execute(select(AnsichAlertEvidenceRow).where(AnsichAlertEvidenceRow.alert_id == alert_id).order_by(AnsichAlertEvidenceRow.ordinal))).scalars())
        return tuple(
            EvidenceRef(
                obs_id=row.obs_id,
                role=row.role,
            )
            for row in rows
        )

    async def _load_reconciliation_alert_episodes(
        self,
        session: AsyncSession,
        *,
        task_id: str,
    ) -> tuple[AlertEpisode, ...]:
        rows = list(
            (
                await session.execute(
                    _reconciliation_alert_rows_statement(
                        task_id=task_id,
                    )
                )
            ).scalars()
        )
        return tuple(self._alert_episode_from_row(row) for row in rows)

    async def _reconcile_alerts_for_assessment(
        self,
        session: AsyncSession,
        *,
        assessment: Assessment,
        source_assertion_id: str,
        now: datetime,
    ) -> int:
        return await self._reconcile_alerts_for_assessments(
            session,
            subject_id=assessment.subject_id,
            assessments=((assessment, source_assertion_id),),
            now=now,
        )

    async def _reconcile_alerts_for_assessments(
        self,
        session: AsyncSession,
        *,
        subject_id: str,
        assessments: Sequence[tuple[Assessment, str]],
        now: datetime,
        possibly_affected_task_ids: list[str] | None = None,
    ) -> int:
        """Reconcile one subject's whole assessment result against its episodes.

        ``reconcile_alert_conditions`` resolves any unresolved episode in an
        evaluated ``(subject, rule, alert_type)`` scope whose stable key is not
        reported. That is only correct if the conditions handed to it are
        *exhaustive* for that scope, so a subject with several stable keys under
        one rule and type — an environment Scope carrying ``env:fd_open`` beside
        ``env:disk_free_bytes`` — must be reconciled in one call. Reconciling it
        metric by metric would make each metric resolve its siblings' episodes.

        ``possibly_affected_task_ids`` is written onto every Alert read-model row
        this call creates or updates; it stays ``None`` (and the column
        untouched) for Task-subject assessments, where the subject already is
        the affected Task.
        """

        conditions: list[AlertCondition] = []
        for assessment, source_assertion_id in assessments:
            conditions.extend(
                alert_conditions_from_assessment(
                    assessment,
                    source_assertion_id=source_assertion_id,
                )
            )
        if not conditions:
            return 0
        summary = await session.get(
            AnsichTaskSummaryRow,
            subject_id,
        )
        if summary is not None and summary.control_value in {
            "completed",
            "failed",
            "interrupted",
        }:
            return 0
        episodes = await self._load_reconciliation_alert_episodes(
            session,
            task_id=subject_id,
        )
        reconciliations = reconcile_alert_conditions(
            episodes,
            conditions,
            now=now,
            alert_id_factory=new_id,
        )
        changed = 0
        by_id = {episode.alert_id: episode for episode in episodes}
        for reconciliation in reconciliations:
            if reconciliation.change == "noop" or reconciliation.alert is None:
                continue
            candidate = reconciliation.alert
            previous = by_id.get(candidate.alert_id)
            hydrated_previous = previous
            if previous is not None:
                hydrated_previous = previous.model_copy(
                    update={
                        "evidence": await self._load_alert_evidence(
                            session,
                            alert_id=previous.alert_id,
                        )
                    }
                )
                if reconciliation.change == "resolved":
                    candidate = candidate.model_copy(update={"evidence": hydrated_previous.evidence})
                    reconciliation = reconciliation.model_copy(update={"alert": candidate})
            if previous is not None and self._same_alert_projection(
                hydrated_previous,
                candidate,
            ):
                continue
            await self._persist_alert_episode(
                session,
                reconciliation=reconciliation,
                possibly_affected_task_ids=possibly_affected_task_ids,
            )
            by_id[candidate.alert_id] = candidate
            changed += 1
        return changed

    @staticmethod
    def _same_alert_projection(
        current: AlertEpisode,
        candidate: AlertEpisode,
    ) -> bool:
        return current.model_copy(update={"updated_at": candidate.updated_at}) == candidate

    async def _persist_alert_episode(
        self,
        session: AsyncSession,
        *,
        reconciliation: AlertReconciliation,
        possibly_affected_task_ids: list[str] | None = None,
    ) -> None:
        alert = reconciliation.alert
        if alert is None:
            return
        row = await session.get(AnsichAlertRow, alert.alert_id)
        if row is None:
            if not alert.evidence:
                raise ValueError("new Alert episode requires Observation evidence")
            session.add(
                AnsichEntityRow(
                    entity_id=alert.alert_id,
                    entity_type="alert",
                    discovered_obs_id=alert.evidence[0].obs_id,
                )
            )
            # No ORM relationship() links AnsichEntityRow to AnsichAlertRow,
            # so SQLAlchemy's flush does not guarantee this INSERT precedes
            # the FK-dependent one below; flush explicitly to enforce order.
            await session.flush()
            row = AnsichAlertRow(
                entity_id=alert.alert_id,
                alert_key=alert.alert_key,
                episode=alert.episode,
                alert_type=alert.alert_type,
                subject_id=alert.subject_id,
                source_assertion_id=alert.source_assertion_id,
                rule_name=alert.rule.name,
                rule_version=alert.rule.version,
                rule_config_hash=alert.rule_config_hash,
                stable_condition_key=alert.stable_condition_key,
                severity=alert.severity,
                shadow=alert.shadow,
                opened_at=alert.opened_at,
                as_of=alert.as_of,
                updated_at=alert.updated_at,
                resolved_at=alert.resolved_at,
                resolution_reason=alert.resolution_reason,
                workflow_state=alert.workflow_state,
                workflow_version=alert.workflow_version,
                dismissal_reason=alert.dismissal_reason,
            )
            session.add(row)
            # AnsichAlertEvidenceRow.alert_id has no ORM relationship() back
            # to AnsichAlertRow either, so the evidence inserts below are not
            # guaranteed to be ordered after this row's INSERT; flush first.
            await session.flush()
        else:
            row.source_assertion_id = alert.source_assertion_id
            row.rule_name = alert.rule.name
            row.rule_version = alert.rule.version
            row.rule_config_hash = alert.rule_config_hash
            row.stable_condition_key = alert.stable_condition_key
            row.severity = alert.severity
            row.shadow = alert.shadow
            row.as_of = alert.as_of
            row.updated_at = alert.updated_at
            row.resolved_at = alert.resolved_at
            row.resolution_reason = alert.resolution_reason
            row.workflow_state = alert.workflow_state
            row.workflow_version = alert.workflow_version
            row.dismissal_reason = alert.dismissal_reason
            await session.execute(delete(AnsichAlertEvidenceRow).where(AnsichAlertEvidenceRow.alert_id == alert.alert_id))
        for ordinal, evidence in enumerate(alert.evidence):
            session.add(
                AnsichAlertEvidenceRow(
                    alert_id=alert.alert_id,
                    obs_id=evidence.obs_id,
                    role=evidence.role,
                    ordinal=ordinal,
                )
            )
        read_model = await session.get(
            AnsichAlertReadModelRow,
            alert.alert_id,
        )
        summary_json = {
            "episode": alert.episode,
            "rule_name": alert.rule.name,
            "rule_version": alert.rule.version,
            "rule_config_hash": alert.rule_config_hash,
            "stable_condition_key": alert.stable_condition_key,
            "source_assertion_id": alert.source_assertion_id,
            "resolution_reason": alert.resolution_reason,
            "dismissal_reason": alert.dismissal_reason,
        }
        if read_model is None:
            session.add(
                AnsichAlertReadModelRow(
                    alert_id=alert.alert_id,
                    subject_id=alert.subject_id,
                    alert_type=alert.alert_type,
                    severity=alert.severity,
                    workflow_state=alert.workflow_state,
                    shadow=alert.shadow,
                    opened_at=alert.opened_at,
                    as_of=alert.as_of,
                    updated_at=alert.updated_at,
                    resolved_at=alert.resolved_at,
                    summary_json=summary_json,
                    evidence_count=len(alert.evidence),
                    possibly_affected_task_ids=(possibly_affected_task_ids or None),
                )
            )
        else:
            read_model.alert_type = alert.alert_type
            read_model.severity = alert.severity
            read_model.workflow_state = alert.workflow_state
            read_model.shadow = alert.shadow
            read_model.as_of = alert.as_of
            read_model.updated_at = alert.updated_at
            read_model.resolved_at = alert.resolved_at
            read_model.summary_json = summary_json
            read_model.evidence_count = len(alert.evidence)
            if possibly_affected_task_ids:
                # Overwrite only with a non-empty observation. The field means
                # "Tasks running when this Alert was last sampled", and the
                # sample that closes an episode is usually the one where the
                # Task has already ended — the candidate Scope survives on its
                # unresolved episode alone, so the list is empty exactly then.
                # Writing that empty list would erase the operator's only
                # attribution at the moment they most need it. Keeping the last
                # non-empty observation is honest; unioning across time would
                # not be, so it is deliberately not done.
                read_model.possibly_affected_task_ids = possibly_affected_task_ids

    async def _resolve_terminal_alerts(
        self,
        session: AsyncSession,
        *,
        task_id: str,
        now: datetime,
    ) -> int:
        episodes = await self._load_reconciliation_alert_episodes(
            session,
            task_id=task_id,
        )
        changed = 0
        for episode in episodes:
            if episode.workflow_state == "resolved" or episode.resolved_at is not None:
                continue
            episode = episode.model_copy(
                update={
                    "evidence": await self._load_alert_evidence(
                        session,
                        alert_id=episode.alert_id,
                    )
                }
            )
            resolved = resolve_alert_episode(
                episode,
                now=now,
                reason="task_terminal",
            )
            await self._persist_alert_episode(
                session,
                reconciliation=AlertReconciliation(
                    change="resolved",
                    alert=resolved,
                ),
            )
            changed += 1
        return changed

    async def get_task(self, task_id: str) -> TaskView | None:
        async with self._session_factory() as session:
            task = await session.get(AnsichTaskRow, task_id)
            if task is None:
                return None
            summary = await session.get(AnsichTaskSummaryRow, task_id)
            usage = {
                "observability_status": ("healthy" if summary is None else summary.observability_status),
                "tool_calls_issued": 0 if summary is None else summary.tool_calls_issued,
                "tool_calls_executed": 0 if summary is None else summary.tool_calls_executed,
            }
            current = await session.get(AnsichCurrentBeliefRow, (task_id, "control"))
            if current is None:
                trigger = await session.scalar(select(AnsichObservationRow).where(AnsichObservationRow.obs_id == task.trigger_obs_id))
                asserted_at = datetime.now(UTC) if trigger is None else _as_utc(trigger.recorded_at)
                return TaskView(
                    task_id=task.entity_id,
                    source_kind=task.source_kind,
                    source_id=task.source_id,
                    control=ControlBelief(
                        value="unknown",
                        as_of=None,
                        asserted_at=asserted_at,
                        source=NamedVersion(name="task-control", version="1"),
                        fidelity_class="hard",
                        selected_by=NamedVersion(name="control-state", version="1"),
                        evidence_obs_ids=(),
                    ),
                    **usage,
                )
            assertion = await session.get(AnsichBeliefAssertionRow, current.assertion_id)
            if assertion is None:
                return None
            evidence_rows = (await session.execute(select(AnsichBeliefEvidenceRow).where(AnsichBeliefEvidenceRow.assertion_id == assertion.assertion_id).order_by(AnsichBeliefEvidenceRow.ordinal))).scalars()
            return TaskView(
                task_id=task.entity_id,
                source_kind=task.source_kind,
                source_id=task.source_id,
                control=ControlBelief(
                    value=cast(str, assertion.value_json["value"]),
                    as_of=_as_utc(assertion.as_of),
                    asserted_at=_as_utc(assertion.asserted_at),
                    source=NamedVersion(name=assertion.source_name, version=assertion.source_version),
                    fidelity_class="hard",
                    selected_by=NamedVersion(name=current.resolver_name, version=current.resolver_version),
                    evidence_obs_ids=tuple(row.obs_id for row in evidence_rows),
                ),
                **usage,
            )

    @staticmethod
    def _agent_release_summary_view(
        row: AnsichAgentReleaseRow,
        *,
        task_count: int,
    ) -> AgentReleaseSummaryView:
        return AgentReleaseSummaryView(
            release_id=row.entity_id,
            namespace=row.namespace,
            agent_name=row.agent_name,
            release_hash=row.release_hash,
            schema_version=row.schema_version,
            model_hash=row.model_hash,
            prompt_hash=row.prompt_hash,
            tool_catalog_hash=row.tool_catalog_hash,
            policy_hash=row.policy_hash,
            runtime_build_id=row.runtime_build_id,
            created_at=_as_utc(row.created_at),
            task_count=task_count,
        )

    @staticmethod
    async def _load_agent_release_manifest(
        session: AsyncSession,
        row: AnsichAgentReleaseRow,
    ) -> AgentReleaseManifest:
        payload = await session.get(AnsichPayloadRow, row.manifest_payload_id)
        if payload is None:
            raise RuntimeError(f"Ansich AgentRelease manifest payload disappeared: {row.manifest_payload_id}")
        decoded = json.loads(payload.body.decode(payload.encoding))
        return AgentReleaseManifest.model_validate(decoded)

    async def get_agent_release(
        self,
        release_id: str,
    ) -> AgentReleaseDetailView | None:
        async with self._session_factory() as session:
            row = await session.get(AnsichAgentReleaseRow, release_id)
            if row is None:
                return None
            task_count = await session.scalar(select(func.count()).select_from(AnsichTaskAgentReleaseRow).where(AnsichTaskAgentReleaseRow.release_id == release_id))
            return AgentReleaseDetailView(
                summary=self._agent_release_summary_view(
                    row,
                    task_count=int(task_count or 0),
                ),
                manifest=await self._load_agent_release_manifest(session, row),
            )

    async def get_task_agent_release(
        self,
        task_id: str,
    ) -> TaskAgentReleaseView | None:
        async with self._session_factory() as session:
            binding = await session.get(AnsichTaskAgentReleaseRow, task_id)
            if binding is None:
                return None
            row = await session.get(AnsichAgentReleaseRow, binding.release_id)
            if row is None:
                return None
            task_count = await session.scalar(select(func.count()).select_from(AnsichTaskAgentReleaseRow).where(AnsichTaskAgentReleaseRow.release_id == row.entity_id))
            detail = AgentReleaseDetailView(
                summary=self._agent_release_summary_view(
                    row,
                    task_count=int(task_count or 0),
                ),
                manifest=await self._load_agent_release_manifest(session, row),
            )
            return TaskAgentReleaseView(
                task_id=task_id,
                relation_role=cast(Literal["executed_by"], binding.relation_role),
                established_obs_id=binding.established_obs_id,
                release=detail,
            )

    async def list_agent_releases(
        self,
        *,
        limit: int = 100,
        agent_name: str | None = None,
        component_hash: str | None = None,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
    ) -> list[AgentReleaseSummaryView]:
        task_count = select(func.count()).select_from(AnsichTaskAgentReleaseRow).where(AnsichTaskAgentReleaseRow.release_id == AnsichAgentReleaseRow.entity_id).correlate(AnsichAgentReleaseRow).scalar_subquery()
        statement = select(AnsichAgentReleaseRow, task_count.label("task_count"))
        if agent_name is not None:
            statement = statement.where(AnsichAgentReleaseRow.agent_name == agent_name)
        if component_hash is not None:
            statement = statement.where(
                or_(
                    AnsichAgentReleaseRow.model_hash == component_hash,
                    AnsichAgentReleaseRow.prompt_hash == component_hash,
                    AnsichAgentReleaseRow.tool_catalog_hash == component_hash,
                    AnsichAgentReleaseRow.policy_hash == component_hash,
                    AnsichAgentReleaseRow.runtime_build_id == component_hash,
                )
            )
        if from_time is not None:
            statement = statement.where(AnsichAgentReleaseRow.created_at >= from_time)
        if to_time is not None:
            statement = statement.where(AnsichAgentReleaseRow.created_at <= to_time)
        statement = statement.order_by(
            AnsichAgentReleaseRow.created_at.desc(),
            AnsichAgentReleaseRow.entity_id,
        ).limit(limit)
        async with self._session_factory() as session:
            rows = (await session.execute(statement)).all()
        return [self._agent_release_summary_view(row, task_count=int(count or 0)) for row, count in rows]

    async def get_current_belief(
        self,
        subject_id: str,
        field_name: str,
    ) -> BeliefAssertionView | None:
        async with self._session_factory() as session:
            current = await session.get(
                AnsichCurrentBeliefRow,
                (subject_id, field_name),
            )
            if current is None:
                return None
            assertion = await session.get(
                AnsichBeliefAssertionRow,
                current.assertion_id,
            )
            if assertion is None:
                return None
            return await self._belief_assertion_view(session, assertion)

    async def find_evaluation_observation(self, source_event_id: str) -> str | None:
        """Return the Observation id an evaluation intake identity already has."""

        async with self._session_factory() as session:
            return await session.scalar(
                select(AnsichObservationRow.obs_id)
                .where(
                    AnsichObservationRow.kind == EVALUATION_OBSERVATION_KIND,
                    AnsichObservationRow.source_event_id == source_event_id,
                )
                # The uniqueness constraint also spans the producer identity, so
                # pin the replay to the first intake rather than an arbitrary one.
                .order_by(AnsichObservationRow.ingest_seq)
                .limit(1)
            )

    async def get_observation_projection_status(
        self,
        obs_id: str,
    ) -> EvaluationProjectionStatus | None:
        """Summarize one Observation's projection jobs, or ``None`` if it has none.

        A failed job dominates: it is durable evidence that the read model will
        not converge without operator retry. Anything still claimable — pending,
        ``retry`` (re-armed after a spent attempt), leased, or
        dependency-waiting — reads as ``pending``: the caller is being told the
        Observation has not landed yet, not why.
        """

        async with self._session_factory() as session:
            statuses = tuple(
                (
                    await session.execute(
                        select(AnsichProjectionJobRow.status).where(
                            AnsichProjectionJobRow.obs_id == obs_id,
                        )
                    )
                ).scalars()
            )
        if not statuses:
            return None
        if any(status == "failed" for status in statuses):
            return "failed"
        if all(status == "completed" for status in statuses):
            return "applied"
        return "pending"

    async def get_evaluation_subject(self, subject_id: str) -> str | None:
        async with self._session_factory() as session:
            entity = await session.get(AnsichEntityRow, subject_id)
        return None if entity is None else entity.entity_type

    async def get_evaluation_observation_payload(self, obs_id: str) -> dict | None:
        """Return one evaluation Observation's full payload, or ``None``.

        This is the only read that returns evaluation bodies — ``expected``,
        ``actual``, ``rationale`` — which the query index deliberately omits.
        An Observation of any other kind is reported as absent rather than
        served, so this route cannot become a general payload reader.
        """

        async with self._session_factory() as session:
            observation = await session.scalar(select(AnsichObservationRow).where(AnsichObservationRow.obs_id == obs_id))
            if observation is None or observation.kind != EVALUATION_OBSERVATION_KIND:
                return None
            if observation.payload_json is not None:
                return observation.payload_json
            if observation.payload_ref_id is None:
                return None
            payload = await session.get(AnsichPayloadRow, observation.payload_ref_id)
            if payload is None:
                return None
            decoded = json.loads(payload.body.decode(payload.encoding))
        return decoded if isinstance(decoded, dict) else None

    async def list_evaluations(
        self,
        *,
        subject_type: str | None = None,
        subject_id: str | None = None,
        task_id: str | None = None,
        limit: int = 100,
    ) -> list[EvaluationView]:
        statement = select(AnsichEvaluationIndexRow)
        if subject_type is not None:
            statement = statement.where(AnsichEvaluationIndexRow.subject_type == subject_type)
        if subject_id is not None:
            statement = statement.where(AnsichEvaluationIndexRow.subject_id == subject_id)
        if task_id is not None:
            statement = statement.where(AnsichEvaluationIndexRow.task_id == task_id)
        statement = statement.order_by(
            AnsichEvaluationIndexRow.occurred_at.desc(),
            AnsichEvaluationIndexRow.evaluation_obs_id.desc(),
        ).limit(limit)
        async with self._session_factory() as session:
            rows = tuple((await session.execute(statement)).scalars())
        return [
            EvaluationView(
                evaluation_obs_id=row.evaluation_obs_id,
                subject_type=row.subject_type,
                subject_id=row.subject_id,
                task_id=row.task_id,
                evaluation_kind=row.evaluation_kind,
                dimension=row.dimension,
                verdict=row.verdict,
                score=row.score,
                scale_min=row.scale_min,
                scale_max=row.scale_max,
                scale_higher_is_better=row.scale_higher_is_better,
                assessor_name=row.assessor_name,
                assessor_version=row.assessor_version,
                authority_class=row.authority_class,
                fidelity_class=row.fidelity_class,
                cohort_key=row.cohort_key,
                suite_id=row.suite_id,
                suite_version=row.suite_version,
                case_id=row.case_id,
                occurred_at=_as_utc(row.occurred_at),
            )
            for row in rows
        ]

    async def list_quality_beliefs(self, subject_id: str) -> list[QualityBeliefView]:
        """Return the persisted ``quality.*`` current Beliefs of one subject.

        Unassessed dimensions are not synthesized here: this read reports only
        what was actually asserted, and the service completes the picture.
        """

        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(AnsichCurrentBeliefRow, AnsichBeliefAssertionRow)
                    .join(
                        AnsichBeliefAssertionRow,
                        AnsichBeliefAssertionRow.assertion_id == AnsichCurrentBeliefRow.assertion_id,
                    )
                    .where(
                        AnsichCurrentBeliefRow.subject_id == subject_id,
                        AnsichCurrentBeliefRow.field_name.like("quality.%"),
                    )
                    .order_by(AnsichCurrentBeliefRow.field_name)
                )
            ).all()
            if not rows:
                return []
            # ResolvedBelief carries conflicting_assertion_count only for a fresh
            # resolution; the persisted current-belief row does not store it, so
            # the retained losing assertions are counted here.
            conflict_counts = {
                field_name: int(count)
                for field_name, count in (
                    await session.execute(
                        select(AnsichBeliefAssertionRow.field_name, func.count())
                        .where(
                            AnsichBeliefAssertionRow.subject_id == subject_id,
                            AnsichBeliefAssertionRow.field_name.like("quality.%"),
                        )
                        .group_by(AnsichBeliefAssertionRow.field_name)
                    )
                ).all()
            }
            evidence: dict[str, list[str]] = {}
            for assertion_id, obs_id in (
                await session.execute(
                    select(
                        AnsichBeliefEvidenceRow.assertion_id,
                        AnsichBeliefEvidenceRow.obs_id,
                    )
                    .where(AnsichBeliefEvidenceRow.assertion_id.in_([assertion.assertion_id for _, assertion in rows]))
                    .order_by(
                        AnsichBeliefEvidenceRow.assertion_id,
                        AnsichBeliefEvidenceRow.ordinal,
                    )
                )
            ).all():
                evidence.setdefault(assertion_id, []).append(obs_id)
        return [
            QualityBeliefView(
                dimension=current.field_name.removeprefix("quality."),
                value=assertion.value_json,
                source=NamedVersion(
                    name=assertion.assessor_name,
                    version=assertion.assessor_version,
                ),
                authority_class=assertion.authority_class,
                fidelity_class=assertion.fidelity_class,
                as_of=_as_utc(assertion.as_of),
                resolver=NamedVersion(
                    name=current.resolver_name,
                    version=current.resolver_version,
                ),
                conflicting_assertion_count=max(0, conflict_counts.get(current.field_name, 1) - 1),
                evidence_obs_ids=tuple(evidence.get(assertion.assertion_id, ())),
                unassessed=False,
            )
            for current, assertion in rows
        ]

    async def get_release_quality(
        self,
        release_id: str,
        *,
        cohort_key: str | None = None,
    ) -> ReleaseQualityView | None:
        """Read one AgentRelease's ``(cohort, dimension)`` quality cells.

        ``mean_score`` is derived here rather than stored, so a cell whose
        samples span incompatible scales (``score_count == 0``) reports counts
        without an incomparable average.

        Two freshness caveats belong to the projected cells, not this read: a
        cell's ``as_of`` advances with the newest evaluation in it even when
        that evaluation changed no selected Belief, and a Task whose release
        binding lands after the cell's last evaluation only joins the cell when
        the next evaluation for it recomputes the cell.
        """

        async with self._session_factory() as session:
            if await session.get(AnsichAgentReleaseRow, release_id) is None:
                return None
            statement = select(AnsichReleaseQualityStatsRow).where(
                AnsichReleaseQualityStatsRow.release_id == release_id,
            )
            if cohort_key is not None:
                statement = statement.where(AnsichReleaseQualityStatsRow.cohort_key == cohort_key)
            rows = tuple(
                (
                    await session.execute(
                        statement.order_by(
                            AnsichReleaseQualityStatsRow.dimension,
                            AnsichReleaseQualityStatsRow.cohort_key,
                        )
                    )
                ).scalars()
            )
        return ReleaseQualityView(
            release_id=release_id,
            cohorts=tuple(
                ReleaseQualityDimensionView(
                    dimension=row.dimension,
                    cohort_key=row.cohort_key,
                    assessed_count=row.assessed_count,
                    pass_count=row.pass_count,
                    fail_count=row.fail_count,
                    partial_count=row.partial_count,
                    mean_score=(row.score_sum / row.score_count) if row.score_count > 0 and row.score_sum is not None else None,
                    # Polarity ships with the range so ``compare_release_quality``
                    # rejects two cells that share a scale but invert its meaning.
                    scale=None if row.scale_min is None and row.scale_max is None else {"min": row.scale_min, "max": row.scale_max, "higher_is_better": row.scale_higher_is_better},
                    as_of=_as_utc(row.as_of),
                )
                for row in rows
            ),
        )

    async def get_task_by_source(self, source_kind: str, source_id: str) -> TaskView | None:
        async with self._session_factory() as session:
            task_id = await session.scalar(
                select(AnsichTaskRow.entity_id).where(
                    AnsichTaskRow.source_kind == source_kind,
                    AnsichTaskRow.source_id == source_id,
                )
            )
        if task_id is None:
            return None
        return await self.get_task(task_id)

    async def list_tasks(
        self,
        *,
        limit: int = 100,
        control: ControlValue | None = None,
        lifecycle_scope: TaskLifecycleScope = "all",
        from_time: datetime | None = None,
        to_time: datetime | None = None,
        cursor: tuple[datetime, str] | None = None,
        root_only: bool = False,
    ) -> list[TaskView]:
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    _list_task_views_statement(
                        limit=limit,
                        control=control,
                        lifecycle_scope=lifecycle_scope,
                        from_time=from_time,
                        to_time=to_time,
                        cursor=cursor,
                        root_only=root_only,
                    )
                )
            ).all()
        row_by_task_id = {}
        evidence_by_task_id: dict[str, list[str]] = {}
        for row in rows:
            if row.task_id not in row_by_task_id:
                row_by_task_id[row.task_id] = row
                evidence_by_task_id[row.task_id] = []
            if row.evidence_obs_id is not None:
                evidence_by_task_id[row.task_id].append(row.evidence_obs_id)

        tasks: list[TaskView] = []
        for task_id, row in row_by_task_id.items():
            assertion_value = row.assertion_value_json
            control_value = assertion_value.get("value", row.control_value) if isinstance(assertion_value, dict) else row.control_value
            tasks.append(
                TaskView(
                    task_id=task_id,
                    source_kind=row.source_kind,
                    source_id=row.source_id,
                    control=ControlBelief(
                        value=cast(str, control_value),
                        as_of=_as_utc(row.assertion_as_of or row.control_as_of),
                        asserted_at=_as_utc(row.assertion_asserted_at or row.last_evidence_at),
                        source=NamedVersion(
                            name=row.assertion_source_name or "task-control",
                            version=row.assertion_source_version or "1",
                        ),
                        fidelity_class="hard",
                        selected_by=NamedVersion(
                            name=row.resolver_name or "control-state",
                            version=row.resolver_version or "1",
                        ),
                        evidence_obs_ids=tuple(evidence_by_task_id[task_id]),
                    ),
                    observability_status=(row.observability_status if row.assertion_value_json is not None and row.resolver_name is not None else "degraded"),
                    tool_calls_issued=row.tool_calls_issued,
                    tool_calls_executed=row.tool_calls_executed,
                )
            )
        return tasks

    async def list_observations(self, task_id: str) -> list[ObservationEnvelope]:
        async with self._session_factory() as session:
            rows = list((await session.execute(select(AnsichObservationRow).where(AnsichObservationRow.task_id == task_id).order_by(AnsichObservationRow.ingest_seq))).scalars())
        return [self._observation_from_row(row) for row in rows]

    async def list_task_children(self, task_id: str) -> list[TaskSpawnView]:
        async with self._session_factory() as session:
            rows = list(
                (
                    await session.execute(
                        select(AnsichTaskSpawnRow)
                        .where(AnsichTaskSpawnRow.parent_task_id == task_id)
                        .order_by(
                            AnsichTaskSpawnRow.established_obs_id,
                            AnsichTaskSpawnRow.child_task_id,
                        )
                    )
                ).scalars()
            )
        return [
            TaskSpawnView(
                parent_task_id=row.parent_task_id,
                spawning_step_id=row.spawning_step_id,
                spawning_tool_call_id=row.spawning_tool_call_id,
                child_task_id=row.child_task_id,
                established_obs_id=row.established_obs_id,
                subagent_name=row.subagent_name,
            )
            for row in rows
        ]

    async def list_task_tree_spawns(
        self,
        task_id: str,
        *,
        direction: TaskTreeDirection,
        depth: int,
    ) -> tuple[list[TaskSpawnView], bool]:
        async with self._session_factory() as session:
            descendant_rows = list((await session.execute(select(AnsichTaskAncestryRow).where(AnsichTaskAncestryRow.ancestor_task_id == task_id))).scalars()) if direction in {"descendants", "both"} else []
            ancestor_rows = list((await session.execute(select(AnsichTaskAncestryRow).where(AnsichTaskAncestryRow.descendant_task_id == task_id))).scalars()) if direction in {"ancestors", "both"} else []
            node_depths = {task_id: 0}
            for row in descendant_rows:
                if row.depth <= depth:
                    node_depths[row.descendant_task_id] = row.depth
            for row in ancestor_rows:
                if row.depth <= depth:
                    node_depths[row.ancestor_task_id] = -row.depth
            node_ids = tuple(node_depths)
            rows = list(
                (
                    await session.execute(
                        select(AnsichTaskSpawnRow).where(
                            AnsichTaskSpawnRow.parent_task_id.in_(node_ids),
                            AnsichTaskSpawnRow.child_task_id.in_(node_ids),
                        )
                    )
                ).scalars()
            )
        rows.sort(
            key=lambda row: (
                node_depths[row.child_task_id],
                row.parent_task_id,
                row.child_task_id,
            )
        )
        truncated = any(row.depth > depth for row in descendant_rows) or any(row.depth > depth for row in ancestor_rows)
        return (
            [
                TaskSpawnView(
                    parent_task_id=row.parent_task_id,
                    spawning_step_id=row.spawning_step_id,
                    spawning_tool_call_id=row.spawning_tool_call_id,
                    child_task_id=row.child_task_id,
                    established_obs_id=row.established_obs_id,
                    subagent_name=row.subagent_name,
                )
                for row in rows
            ],
            truncated,
        )

    async def list_alerts(
        self,
        *,
        limit: int,
        alert_type: str | None = None,
        workflow_state: str | None = None,
        task_id: str | None = None,
        severity: str | None = None,
        shadow: bool | None = None,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
        cursor: tuple[datetime, str] | None = None,
    ) -> list[AlertSummaryView]:
        statement = select(AnsichAlertRow, AnsichAlertReadModelRow).join(
            AnsichAlertReadModelRow,
            AnsichAlertReadModelRow.alert_id == AnsichAlertRow.entity_id,
        )
        if alert_type is not None:
            statement = statement.where(AnsichAlertRow.alert_type == alert_type)
        if workflow_state is not None:
            statement = statement.where(AnsichAlertRow.workflow_state == workflow_state)
        if task_id is not None:
            statement = statement.where(AnsichAlertRow.subject_id == task_id)
        if severity is not None:
            statement = statement.where(AnsichAlertRow.severity == severity)
        if shadow is not None:
            statement = statement.where(AnsichAlertRow.shadow == shadow)
        if from_time is not None:
            statement = statement.where(AnsichAlertRow.updated_at >= from_time)
        if to_time is not None:
            statement = statement.where(AnsichAlertRow.updated_at <= to_time)
        if cursor is not None:
            cursor_time, cursor_alert_id = cursor
            statement = statement.where(
                or_(
                    AnsichAlertRow.updated_at < cursor_time,
                    and_(
                        AnsichAlertRow.updated_at == cursor_time,
                        AnsichAlertRow.entity_id > cursor_alert_id,
                    ),
                )
            )
        statement = statement.order_by(
            AnsichAlertRow.updated_at.desc(),
            AnsichAlertRow.entity_id,
        ).limit(limit)
        async with self._session_factory() as session:
            rows = list((await session.execute(statement)).all())
        return [self._alert_summary_view(alert, read_model.evidence_count) for alert, read_model in rows]

    async def get_alert_detail(
        self,
        alert_id: str,
    ) -> AlertDetailView | None:
        async with self._session_factory() as session:
            alert = await session.get(AnsichAlertRow, alert_id)
            if alert is None:
                return None
            read_model = await session.get(AnsichAlertReadModelRow, alert_id)
            source_assertion = await session.get(
                AnsichBeliefAssertionRow,
                alert.source_assertion_id,
            )
            if read_model is None or source_assertion is None:
                return None
            source_belief = await self._belief_assertion_view(
                session,
                source_assertion,
            )
            alert_evidence = list((await session.execute(select(AnsichAlertEvidenceRow).where(AnsichAlertEvidenceRow.alert_id == alert_id).order_by(AnsichAlertEvidenceRow.ordinal))).scalars())
            observation_rows = list((await session.execute(select(AnsichObservationRow).where(AnsichObservationRow.obs_id.in_([item.obs_id for item in alert_evidence])))).scalars())
            observations_by_id = {observation.obs_id: observation for observation in observation_rows}
            evidence = tuple(self._observation_from_row(observations_by_id[item.obs_id]) for item in alert_evidence if item.obs_id in observations_by_id)
            current_rows = list(
                (
                    await session.execute(
                        select(AnsichBeliefAssertionRow)
                        .join(
                            AnsichCurrentBeliefRow,
                            AnsichCurrentBeliefRow.assertion_id == AnsichBeliefAssertionRow.assertion_id,
                        )
                        .where(AnsichCurrentBeliefRow.subject_id == alert.subject_id)
                        .order_by(AnsichCurrentBeliefRow.field_name)
                    )
                ).scalars()
            )
            current_beliefs = tuple([await self._belief_assertion_view(session, row) for row in current_rows])
            workflow_rows = list(
                (
                    await session.execute(
                        select(AnsichAlertWorkflowEventRow)
                        .where(AnsichAlertWorkflowEventRow.alert_id == alert_id)
                        .order_by(
                            AnsichAlertWorkflowEventRow.workflow_version,
                            AnsichAlertWorkflowEventRow.event_id,
                        )
                    )
                ).scalars()
            )
            summary = await session.get(
                AnsichTaskSummaryRow,
                alert.subject_id,
            )
        actions: list[str] = []
        if alert.workflow_state not in {"resolved", "dismissed"}:
            if alert.workflow_state == "open":
                actions.append("acknowledge")
            actions.append("dismiss")
        if summary is not None and summary.control_value == "running":
            actions.extend(("interrupt", "rollback"))
        return AlertDetailView.model_validate(
            {
                "alert": self._alert_summary_view(
                    alert,
                    read_model.evidence_count,
                ),
                "source_belief": source_belief,
                "evidence": evidence,
                "current_beliefs": current_beliefs,
                "workflow_history": tuple(
                    AlertWorkflowEventView.model_validate(
                        {
                            "event_id": row.event_id,
                            "obs_id": row.obs_id,
                            "action": row.action,
                            "from_state": row.from_state,
                            "to_state": row.to_state,
                            "workflow_version": row.workflow_version,
                            "reason": row.reason,
                            "operator_id": row.operator_id,
                            "occurred_at": _as_utc(row.occurred_at),
                        }
                    )
                    for row in workflow_rows
                ),
                "available_actions": tuple(actions),
            }
        )

    async def change_alert_workflow(
        self,
        alert_id: str,
        *,
        action: Literal["acknowledge", "dismiss"],
        expected_workflow_version: int,
        operator_id: str,
        reason: str | None,
        occurred_at: datetime,
    ) -> AlertSummaryView | None:
        async with self._session_factory() as session, session.begin():
            alert_row = await session.scalar(select(AnsichAlertRow).where(AnsichAlertRow.entity_id == alert_id).with_for_update())
            if alert_row is None:
                return None
            current = self._alert_episode_from_row(
                alert_row,
                evidence=await self._load_alert_evidence(
                    session,
                    alert_id=alert_id,
                ),
            )
            if action == "acknowledge":
                updated = acknowledge_alert(
                    current,
                    expected_workflow_version=expected_workflow_version,
                    now=occurred_at,
                )
                observation_kind = "operator.alert_acknowledged"
            else:
                updated = dismiss_alert(
                    current,
                    expected_workflow_version=expected_workflow_version,
                    now=occurred_at,
                    reason=reason or "",
                )
                observation_kind = "operator.alert_dismissed"
            observation = ObservationEnvelope(
                kind=observation_kind,
                occurred_at=occurred_at,
                recorded_at=occurred_at,
                task_id=current.subject_id,
                subject_type="alert",
                subject_id=current.alert_id,
                producer=Producer(
                    name="ansich-operator-workflow",
                    version="1",
                    instance_id=operator_id,
                ),
                producer_seq=updated.workflow_version,
                source_event_id=(f"alert:{alert_id}:{action}:workflow:{updated.workflow_version}"),
                correlation_id=current.subject_id,
                payload={
                    "action": action,
                    "expected_workflow_version": expected_workflow_version,
                    "workflow_version": updated.workflow_version,
                    "operator_id": operator_id,
                    "reason": reason,
                },
            )
            session.add(
                AnsichObservationRow(
                    obs_id=observation.obs_id,
                    schema_version=observation.schema_version,
                    kind=observation.kind,
                    occurred_at=observation.occurred_at,
                    recorded_at=observation.recorded_at,
                    task_id=observation.task_id,
                    step_id=None,
                    subject_type=observation.subject_type,
                    subject_id=observation.subject_id,
                    fidelity_class=observation.fidelity_class,
                    producer_name=observation.producer.name,
                    producer_version=observation.producer.version,
                    producer_instance_id=observation.producer.instance_id,
                    producer_seq=observation.producer_seq,
                    source_event_id=observation.source_event_id,
                    correlation_id=observation.correlation_id,
                    causation_obs_id=None,
                    payload_json=observation.payload,
                    payload_ref_id=None,
                )
            )
            await session.flush()
            await self._persist_alert_episode(
                session,
                reconciliation=AlertReconciliation(
                    change="confirmed",
                    alert=updated,
                ),
            )
            session.add(
                AnsichAlertWorkflowEventRow(
                    event_id=new_id(),
                    alert_id=alert_id,
                    obs_id=observation.obs_id,
                    action=action,
                    from_state=current.workflow_state,
                    to_state=updated.workflow_state,
                    workflow_version=updated.workflow_version,
                    reason=reason,
                    operator_id=operator_id,
                    occurred_at=occurred_at,
                )
            )
            return self._alert_summary_view(
                alert_row,
                len(updated.evidence),
            ).model_copy(
                update={
                    "workflow_state": updated.workflow_state,
                    "workflow_version": updated.workflow_version,
                    "updated_at": updated.updated_at,
                    "dismissal_reason": updated.dismissal_reason,
                }
            )

    async def get_task_action_target(
        self,
        task_id: str,
    ) -> TaskActionTarget | None:
        async with self._session_factory() as session:
            task = await session.get(AnsichTaskRow, task_id)
            summary = await session.get(AnsichTaskSummaryRow, task_id)
            if task is None or summary is None:
                return None
            thread_id = await session.scalar(
                select(AnsichScopeRow.display_label)
                .join(
                    AnsichRelationRow,
                    AnsichRelationRow.object_id == AnsichScopeRow.entity_id,
                )
                .where(
                    AnsichRelationRow.subject_id == task_id,
                    AnsichRelationRow.predicate == "within_scope",
                    AnsichScopeRow.scope_kind == "thread",
                )
                .limit(1)
            )
        return TaskActionTarget(
            task_id=task_id,
            source_kind=task.source_kind,
            run_id=task.source_id,
            thread_id=thread_id,
            control_value=summary.control_value,
        )

    async def get_operator_action(
        self,
        *,
        task_id: str,
        action_type: Literal["interrupt", "rollback"],
        idempotency_key: str,
    ) -> OperatorActionView | None:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(AnsichOperatorActionRow).where(
                    AnsichOperatorActionRow.task_id == task_id,
                    AnsichOperatorActionRow.action_type == action_type,
                    AnsichOperatorActionRow.idempotency_key == idempotency_key,
                )
            )
        return None if row is None else self._operator_action_view(row)

    async def begin_operator_action(
        self,
        *,
        task_id: str,
        action_type: Literal["interrupt", "rollback"],
        idempotency_key: str,
        operator_id: str,
        occurred_at: datetime,
    ) -> tuple[OperatorActionView, bool]:
        async with self._session_factory() as session, session.begin():
            action_id = new_id()
            values = {
                "action_id": action_id,
                "task_id": task_id,
                "action_type": action_type,
                "idempotency_key": idempotency_key,
                "status": "requested",
                "requested_obs_id": None,
                "terminal_obs_id": None,
                "result_json": None,
                "created_at": occurred_at,
                "updated_at": occurred_at,
            }
            if session.bind is not None and session.bind.dialect.name == "postgresql":
                statement = postgresql_insert(AnsichOperatorActionRow).values(**values)
            else:
                statement = sqlite_insert(AnsichOperatorActionRow).values(**values)
            inserted_action_id = (
                await session.execute(
                    statement.on_conflict_do_nothing(
                        index_elements=[
                            "task_id",
                            "action_type",
                            "idempotency_key",
                        ]
                    ).returning(AnsichOperatorActionRow.action_id)
                )
            ).scalar_one_or_none()
            if inserted_action_id is None:
                existing = await session.scalar(
                    select(AnsichOperatorActionRow)
                    .where(
                        AnsichOperatorActionRow.task_id == task_id,
                        AnsichOperatorActionRow.action_type == action_type,
                        AnsichOperatorActionRow.idempotency_key == idempotency_key,
                    )
                    .with_for_update()
                )
                if existing is None:
                    raise RuntimeError("operator action idempotency conflict did not expose the winning row")
                return await self._take_over_stale_operator_action(
                    session,
                    existing=existing,
                    action_id=action_id,
                    idempotency_key=idempotency_key,
                    operator_id=operator_id,
                    occurred_at=occurred_at,
                )
            observation = self._operator_action_observation(
                task_id=task_id,
                action_id=inserted_action_id,
                action_type=action_type,
                status="requested",
                idempotency_key=idempotency_key,
                operator_id=operator_id,
                occurred_at=occurred_at,
                result=None,
            )
            self._add_observation_row(session, observation)
            await session.execute(update(AnsichOperatorActionRow).where(AnsichOperatorActionRow.action_id == inserted_action_id).values(requested_obs_id=observation.obs_id))
            await session.flush()
            return (
                OperatorActionView(
                    action_id=inserted_action_id,
                    task_id=task_id,
                    action_type=action_type,
                    idempotency_key=idempotency_key,
                    status="requested",
                    requested_obs_id=observation.obs_id,
                    terminal_obs_id=None,
                    result=None,
                    created_at=occurred_at,
                    updated_at=occurred_at,
                ),
                True,
            )

    async def _take_over_stale_operator_action(
        self,
        session: AsyncSession,
        *,
        existing: AnsichOperatorActionRow,
        action_id: str,
        idempotency_key: str,
        operator_id: str,
        occurred_at: datetime,
    ) -> tuple[OperatorActionView, bool]:
        """Recover an operator action stranded in ``requested`` (phase-6 L2 / HR3).

        Declines — reporting the ordinary idempotency conflict — for a terminal
        row, and for a ``requested`` row still inside
        ``_STALE_REQUESTED_TAKEOVER_AFTER``, which is a genuine in-flight
        duplicate rather than an orphan.

        Past that window the abandoned attempt is terminalized by an
        ``operator.action_failed`` Observation carrying
        ``stale_requested_takeover`` plus a forward pointer to the attempt that
        supersedes it — the same Observation kind and payload shape the ordinary
        failure path writes, so no new audit kind is introduced. The audit row is
        the ledger entry for one Idempotency-Key rather than a per-attempt record:
        it holds the unique key, so a later retry has to find the *live* attempt's
        outcome there, not the abandoned one's. It is therefore re-armed in place
        for the fresh attempt (new ``action_id``, fresh ``created_at`` so the new
        attempt owns a full window of its own), and the abandoned attempt's
        terminal lives on in the immutable Observation stream, which is where this
        audit is durable anyway — ``rebuild_projections`` clears the row table.
        """

        if existing.status != "requested":
            return self._operator_action_view(existing), False
        requested_at = _as_utc(existing.created_at)
        if _as_utc(occurred_at) - requested_at < _STALE_REQUESTED_TAKEOVER_AFTER:
            return self._operator_action_view(existing), False
        task_id = existing.task_id
        action_type = cast(Literal["interrupt", "rollback"], existing.action_type)
        abandoned_action_id = existing.action_id
        abandoned = self._operator_action_observation(
            task_id=task_id,
            action_id=abandoned_action_id,
            action_type=action_type,
            status="failed",
            idempotency_key=idempotency_key,
            operator_id=operator_id,
            occurred_at=occurred_at,
            result={
                "outcome": "stale_requested_takeover",
                "requested_at": requested_at.isoformat(),
                "expiry_seconds": int(_STALE_REQUESTED_TAKEOVER_AFTER.total_seconds()),
                "superseded_by_action_id": action_id,
            },
        )
        # Compare-and-set against the row identity this transaction just read, so
        # the election survives a dialect that ignores ``FOR UPDATE``: concurrent
        # retries against one orphan produce exactly one winner, and the loser
        # re-reads the winner's re-armed (no longer stale) row as the ordinary
        # in-progress conflict. ``synchronize_session`` is off because this
        # statement rewrites the primary key.
        elected = (
            await session.execute(
                update(AnsichOperatorActionRow)
                .where(
                    AnsichOperatorActionRow.action_id == abandoned_action_id,
                    AnsichOperatorActionRow.status == "requested",
                )
                .values(
                    action_id=action_id,
                    status="requested",
                    requested_obs_id=None,
                    terminal_obs_id=None,
                    result_json=None,
                    created_at=occurred_at,
                    updated_at=occurred_at,
                )
                .returning(AnsichOperatorActionRow.action_id)
                .execution_options(synchronize_session=False),
            )
        ).scalar_one_or_none()
        if elected is None:
            current = await session.scalar(
                select(AnsichOperatorActionRow).where(
                    AnsichOperatorActionRow.task_id == task_id,
                    AnsichOperatorActionRow.action_type == action_type,
                    AnsichOperatorActionRow.idempotency_key == idempotency_key,
                )
            )
            if current is None:
                raise RuntimeError("operator action takeover conflict did not expose the winning row")
            return self._operator_action_view(current), False
        # The identity map still holds `existing` under the primary key this
        # statement just rewrote; drop it so nothing can write that ghost back.
        session.expunge(existing)
        requested = self._operator_action_observation(
            task_id=task_id,
            action_id=action_id,
            action_type=action_type,
            status="requested",
            idempotency_key=idempotency_key,
            operator_id=operator_id,
            occurred_at=occurred_at,
            result=None,
        )
        self._add_observation_row(session, abandoned)
        self._add_observation_row(session, requested)
        await session.execute(update(AnsichOperatorActionRow).where(AnsichOperatorActionRow.action_id == action_id).values(requested_obs_id=requested.obs_id))
        await session.flush()
        return (
            OperatorActionView(
                action_id=action_id,
                task_id=task_id,
                action_type=action_type,
                idempotency_key=idempotency_key,
                status="requested",
                requested_obs_id=requested.obs_id,
                terminal_obs_id=None,
                result=None,
                created_at=occurred_at,
                updated_at=occurred_at,
            ),
            True,
        )

    async def finish_operator_action(
        self,
        action_id: str,
        *,
        succeeded: bool,
        operator_id: str,
        result: dict[str, object],
        occurred_at: datetime,
    ) -> OperatorActionView | None:
        async with self._session_factory() as session, session.begin():
            row = await session.scalar(select(AnsichOperatorActionRow).where(AnsichOperatorActionRow.action_id == action_id).with_for_update())
            if row is None:
                return None
            if row.status in {"succeeded", "failed"}:
                return self._operator_action_view(row)
            status = "succeeded" if succeeded else "failed"
            observation = self._operator_action_observation(
                task_id=row.task_id,
                action_id=row.action_id,
                action_type=cast(
                    Literal["interrupt", "rollback"],
                    row.action_type,
                ),
                status=status,
                idempotency_key=row.idempotency_key,
                operator_id=operator_id,
                occurred_at=occurred_at,
                result=result,
            )
            self._add_observation_row(session, observation)
            row.status = status
            row.terminal_obs_id = observation.obs_id
            row.result_json = result
            row.updated_at = occurred_at
            await session.flush()
            return self._operator_action_view(row)

    @staticmethod
    def _operator_action_observation(
        *,
        task_id: str,
        action_id: str,
        action_type: Literal["interrupt", "rollback"],
        status: Literal["requested", "succeeded", "failed"],
        idempotency_key: str,
        operator_id: str,
        occurred_at: datetime,
        result: dict[str, object] | None,
    ) -> ObservationEnvelope:
        kind_by_status = {
            "requested": "operator.action_requested",
            "succeeded": "operator.action_succeeded",
            "failed": "operator.action_failed",
        }
        idempotency_hash = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        return ObservationEnvelope(
            kind=kind_by_status[status],
            occurred_at=occurred_at,
            recorded_at=occurred_at,
            task_id=task_id,
            subject_type="task",
            subject_id=task_id,
            producer=Producer(
                name="ansich-operator-action",
                version="1",
                instance_id=operator_id,
            ),
            source_event_id=(f"operator-action:{action_id}:{status}:{idempotency_hash[:16]}"),
            correlation_id=action_id,
            payload={
                "action_id": action_id,
                "action_type": action_type,
                "status": status,
                "idempotency_hash": idempotency_hash,
                "operator_id": operator_id,
                "result": result,
            },
        )

    @staticmethod
    def _add_observation_row(
        session: AsyncSession,
        observation: ObservationEnvelope,
    ) -> None:
        session.add(
            AnsichObservationRow(
                obs_id=observation.obs_id,
                schema_version=observation.schema_version,
                kind=observation.kind,
                occurred_at=observation.occurred_at,
                recorded_at=observation.recorded_at,
                task_id=observation.task_id,
                step_id=observation.step_id,
                subject_type=observation.subject_type,
                subject_id=observation.subject_id,
                fidelity_class=observation.fidelity_class,
                producer_name=observation.producer.name,
                producer_version=observation.producer.version,
                producer_instance_id=observation.producer.instance_id,
                producer_seq=observation.producer_seq,
                source_event_id=observation.source_event_id,
                correlation_id=observation.correlation_id,
                causation_obs_id=observation.causation_obs_id,
                payload_json=observation.payload,
                payload_ref_id=observation.payload_ref_id,
            )
        )

    @staticmethod
    def _operator_action_view(
        row: AnsichOperatorActionRow,
    ) -> OperatorActionView:
        return OperatorActionView.model_validate(
            {
                "action_id": row.action_id,
                "task_id": row.task_id,
                "action_type": row.action_type,
                "idempotency_key": row.idempotency_key,
                "status": row.status,
                "requested_obs_id": row.requested_obs_id,
                "terminal_obs_id": row.terminal_obs_id,
                "result": row.result_json,
                "created_at": _as_utc(row.created_at),
                "updated_at": _as_utc(row.updated_at),
            }
        )

    @staticmethod
    def _alert_summary_view(
        alert: AnsichAlertRow,
        evidence_count: int,
    ) -> AlertSummaryView:
        return AlertSummaryView.model_validate(
            {
                "alert_id": alert.entity_id,
                "subject_id": alert.subject_id,
                "alert_type": alert.alert_type,
                "episode": alert.episode,
                "severity": alert.severity,
                "workflow_state": alert.workflow_state,
                "workflow_version": alert.workflow_version,
                "shadow": alert.shadow,
                "opened_at": _as_utc(alert.opened_at),
                "as_of": _as_utc(alert.as_of),
                "updated_at": _as_utc(alert.updated_at),
                "resolved_at": (None if alert.resolved_at is None else _as_utc(alert.resolved_at)),
                "rule": NamedVersion(
                    name=alert.rule_name,
                    version=alert.rule_version,
                ),
                "rule_config_hash": alert.rule_config_hash,
                "stable_condition_key": alert.stable_condition_key,
                "source_assertion_id": alert.source_assertion_id,
                "resolution_reason": alert.resolution_reason,
                "dismissal_reason": alert.dismissal_reason,
                "evidence_count": evidence_count,
            }
        )

    @staticmethod
    async def _belief_assertion_view(
        session: AsyncSession,
        assertion: AnsichBeliefAssertionRow,
    ) -> BeliefAssertionView:
        evidence_obs_ids = tuple((await session.execute(select(AnsichBeliefEvidenceRow.obs_id).where(AnsichBeliefEvidenceRow.assertion_id == assertion.assertion_id).order_by(AnsichBeliefEvidenceRow.ordinal))).scalars())
        return BeliefAssertionView.model_validate(
            {
                "assertion_id": assertion.assertion_id,
                "subject_id": assertion.subject_id,
                "field_name": assertion.field_name,
                "value": assertion.value_json,
                "as_of": _as_utc(assertion.as_of),
                "asserted_at": _as_utc(assertion.asserted_at),
                "assessor": NamedVersion(
                    name=assertion.assessor_name,
                    version=assertion.assessor_version,
                ),
                "config_hash": assertion.config_hash,
                "authority_class": assertion.authority_class,
                "fidelity_class": assertion.fidelity_class,
                "confidence": assertion.confidence,
                "evidence_obs_ids": evidence_obs_ids,
            }
        )

    async def get_task_usage(self, task_id: str) -> TaskUsageView:
        async with self._session_factory() as session:
            rows = list(
                (
                    await session.execute(
                        select(AnsichTaskUsageRow).where(
                            AnsichTaskUsageRow.task_id == task_id,
                        )
                    )
                ).scalars()
            )
        rows.sort(
            key=lambda row: (
                row.aggregation_scope,
                _USAGE_DIMENSION_ORDER[row.dimension],
            )
        )

        def values_for(scope: AggregationScope) -> tuple[TaskUsageValue, ...]:
            return tuple(
                TaskUsageValue(
                    dimension=row.dimension,
                    aggregation_scope=scope,
                    value=row.value,
                    as_of=_as_utc(row.as_of),
                    complete_through_ingest_seq=row.complete_through_ingest_seq,
                )
                for row in rows
                if row.aggregation_scope == scope
            )

        return TaskUsageView(
            task_id=task_id,
            local=values_for("local"),
            inclusive=values_for("inclusive"),
        )

    async def get_task_usage_breakdown(
        self,
        task_id: str,
        *,
        scope: AggregationScope,
    ) -> TaskUsageBreakdownView:
        statement = (
            select(AnsichUsageContributionRow, AnsichObservationRow.ingest_seq)
            .join(
                AnsichObservationRow,
                AnsichObservationRow.obs_id == AnsichUsageContributionRow.source_obs_id,
            )
            .where(AnsichUsageContributionRow.aggregate_task_id == task_id)
        )
        if scope == "local":
            statement = statement.where(AnsichUsageContributionRow.source_task_id == task_id)
        async with self._session_factory() as session:
            rows = list((await session.execute(statement)).all())
        grouped: dict[tuple[str, str], list[tuple[AnsichUsageContributionRow, int]]] = {}
        for row, ingest_seq in rows:
            grouped.setdefault((row.source_task_id, row.dimension), []).append((row, ingest_seq))
        values_by_source: dict[str, list[TaskUsageValue]] = {}
        for (source_task_id, dimension), group in grouped.items():
            value = max(row.delta for row, _ in group) if dimension == "wall_time_ms" else sum(row.delta for row, _ in group)
            values_by_source.setdefault(source_task_id, []).append(
                TaskUsageValue(
                    dimension=dimension,
                    aggregation_scope=scope,
                    value=value,
                    as_of=max(_as_utc(row.as_of) for row, _ in group),
                    complete_through_ingest_seq=max(ingest_seq for _, ingest_seq in group),
                )
            )
        return TaskUsageBreakdownView(
            task_id=task_id,
            scope=scope,
            sources=tuple(
                TaskUsageSourceView(
                    source_task_id=source_task_id,
                    values=tuple(
                        sorted(
                            values,
                            key=lambda item: _USAGE_DIMENSION_ORDER[item.dimension],
                        )
                    ),
                )
                for source_task_id, values in sorted(values_by_source.items())
            ),
        )

    async def get_task_usage_by_model(self, task_id: str) -> list[TaskUsageByModelView]:
        """Group the Task's own LLM attempts by the provider model they reported.

        LOCAL scope only: an attempt row belongs to the Task that made it, so
        this never fans out through Task ancestry the way inclusive usage does.
        Attempts without a provider identity (requested but never answered,
        failed, or answered without one) are retained in the explicit ``None``
        bucket. Token sums add only recorded values — an unreported dimension
        contributes nothing rather than a zero, and a dimension no attempt in
        the bucket reported stays ``None`` instead of being fabricated as 0.
        """

        async with self._session_factory() as session:
            rows = list(
                (
                    await session.execute(
                        select(
                            AnsichLlmAttemptRow.provider_model,
                            AnsichLlmAttemptRow.usage_json,
                        ).where(AnsichLlmAttemptRow.task_id == task_id)
                    )
                ).all()
            )
        attempt_counts: dict[str | None, int] = {}
        usage_counts: dict[str | None, int] = {}
        sums: dict[tuple[str | None, str], int] = {}
        for provider_model, usage_json in rows:
            attempt_counts[provider_model] = attempt_counts.get(provider_model, 0) + 1
            usage_counts.setdefault(provider_model, 0)
            recorded = False
            if isinstance(usage_json, dict):
                for dimension in LLM_TOKEN_USAGE_DIMENSIONS:
                    value = usage_json.get(dimension)
                    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                        continue
                    sums[(provider_model, dimension)] = sums.get((provider_model, dimension), 0) + value
                    recorded = True
            if recorded:
                usage_counts[provider_model] += 1
        return [
            TaskUsageByModelView(
                provider_model=provider_model,
                attempt_count=attempt_counts[provider_model],
                attempts_with_usage=usage_counts[provider_model],
                input_tokens=sums.get((provider_model, "input_tokens")),
                output_tokens=sums.get((provider_model, "output_tokens")),
                total_tokens=sums.get((provider_model, "total_tokens")),
            )
            # Named models in stable order, the unknown bucket last.
            for provider_model in sorted(attempt_counts, key=lambda name: (name is None, name or ""))
        ]

    async def get_task_budgets(self, task_id: str) -> TaskBudgetsView:
        async with self._session_factory() as session:
            rows = list((await session.execute(select(AnsichTaskBudgetRow).where(AnsichTaskBudgetRow.task_id == task_id))).scalars())
        rows.sort(
            key=lambda row: (
                _USAGE_DIMENSION_ORDER[row.dimension],
                row.aggregation_scope,
            )
        )
        return TaskBudgetsView(
            task_id=task_id,
            budgets=tuple(
                TaskBudgetView(
                    entity_id=row.entity_id,
                    task_id=row.task_id,
                    dimension=row.dimension,
                    aggregation_scope=row.aggregation_scope,
                    warning_limit=row.warning_limit,
                    hard_limit=row.hard_limit,
                    enforcement=row.enforcement,
                    source_kind=cast(BudgetSourceKind, row.source_kind),
                    requested_value=row.requested_value,
                    effective_value=row.effective_value,
                    configured_obs_id=row.configured_obs_id,
                )
                for row in rows
            ),
        )

    #: Alert cap per Scope card, matching the brief's read-side bound (mirrors
    #: the operator Alert list's own recency-ordered per-subject cap).
    _ENVIRONMENT_ALERT_CARD_LIMIT = 20

    async def get_task_environment(self, task_id: str) -> TaskEnvironmentView:
        """Every Scope this Task is attached to, with its environment card(s).

        One card per ``(Scope, environment_scope)`` coverage row — a Scope can
        carry more than one (e.g. continuous ``container`` collection alongside
        per-command ``process_group`` samples). A dimension with a coverage/
        state row but no current Belief yet (assessment lags projection, or the
        Scope is not an assessment candidate) is synthesized as an ``unknown``
        Belief with no evidence, mirroring ``unassessed_quality_belief`` — see
        ``EnvironmentBeliefView``.
        """

        async with self._session_factory() as session:
            relation_rows = list(
                (
                    await session.execute(
                        select(AnsichScopeRow)
                        .join(AnsichRelationRow, AnsichRelationRow.object_id == AnsichScopeRow.entity_id)
                        .where(
                            AnsichRelationRow.subject_id == task_id,
                            AnsichRelationRow.predicate == "within_scope",
                            AnsichRelationRow.relation_role.in_(("sandbox_boundary", "host_environment")),
                        )
                    )
                ).scalars()
            )
            if not relation_rows:
                return TaskEnvironmentView(task_id=task_id, scopes=())
            scope_by_id = {row.entity_id: row for row in relation_rows}
            scope_ids = sorted(scope_by_id)

            coverage_rows = list(
                (
                    await session.execute(
                        select(AnsichEnvironmentCoverageRow)
                        .where(AnsichEnvironmentCoverageRow.scope_id.in_(scope_ids))
                        .order_by(
                            AnsichEnvironmentCoverageRow.scope_id,
                            AnsichEnvironmentCoverageRow.environment_scope,
                        )
                    )
                ).scalars()
            )
            if not coverage_rows:
                return TaskEnvironmentView(task_id=task_id, scopes=())

            state_by_scope_env: dict[tuple[str, str], list[AnsichEnvironmentStateRow]] = {}
            for state_row in (
                await session.execute(
                    select(AnsichEnvironmentStateRow)
                    .where(AnsichEnvironmentStateRow.scope_id.in_(scope_ids))
                    .order_by(
                        AnsichEnvironmentStateRow.scope_id,
                        AnsichEnvironmentStateRow.environment_scope,
                        AnsichEnvironmentStateRow.metric,
                    )
                )
            ).scalars():
                state_by_scope_env.setdefault((state_row.scope_id, state_row.environment_scope), []).append(state_row)

            belief_pairs = list(
                (
                    await session.execute(
                        select(AnsichCurrentBeliefRow, AnsichBeliefAssertionRow)
                        .join(
                            AnsichBeliefAssertionRow,
                            AnsichBeliefAssertionRow.assertion_id == AnsichCurrentBeliefRow.assertion_id,
                        )
                        .where(AnsichCurrentBeliefRow.subject_id.in_(scope_ids))
                    )
                ).all()
            )
            # ``field_name`` deliberately omits ``environment_scope`` — today
            # exactly one environment_scope per Scope is ever assessed, so a
            # (scope_id, field_name) key is unambiguous. A Scope observed under
            # more than one continuously-covered environment_scope would need a
            # richer key; that shape does not occur yet.
            belief_by_field: dict[tuple[str, str], tuple[AnsichCurrentBeliefRow, AnsichBeliefAssertionRow]] = {
                (current.subject_id, current.field_name): (current, assertion) for current, assertion in belief_pairs if current.field_name.startswith("environment_")
            }
            assertion_ids = [assertion.assertion_id for _, assertion in belief_by_field.values()]
            evidence_by_assertion: dict[str, list[str]] = {}
            if assertion_ids:
                for evidence_assertion_id, obs_id in await session.execute(
                    select(AnsichBeliefEvidenceRow.assertion_id, AnsichBeliefEvidenceRow.obs_id).where(AnsichBeliefEvidenceRow.assertion_id.in_(assertion_ids)).order_by(AnsichBeliefEvidenceRow.assertion_id, AnsichBeliefEvidenceRow.ordinal)
                ):
                    evidence_by_assertion.setdefault(evidence_assertion_id, []).append(obs_id)

            alerts_by_scope: dict[str, list[AnsichAlertRow]] = {}
            possibly_affected_by_alert_id: dict[str, tuple[str, ...] | None] = {}
            for alert_row, read_model_row in (
                await session.execute(
                    select(AnsichAlertRow, AnsichAlertReadModelRow)
                    .join(
                        AnsichAlertReadModelRow,
                        AnsichAlertReadModelRow.alert_id == AnsichAlertRow.entity_id,
                    )
                    .where(
                        AnsichAlertRow.subject_id.in_(scope_ids),
                        AnsichAlertRow.alert_type.in_(self._ENVIRONMENT_ALERT_TYPES),
                    )
                    .order_by(AnsichAlertRow.subject_id, AnsichAlertRow.opened_at.desc())
                )
            ).all():
                group = alerts_by_scope.setdefault(alert_row.subject_id, [])
                if len(group) < self._ENVIRONMENT_ALERT_CARD_LIMIT:
                    group.append(alert_row)
                    possibly_affected_by_alert_id[alert_row.entity_id] = None if read_model_row.possibly_affected_task_ids is None else tuple(read_model_row.possibly_affected_task_ids)

        scopes: list[EnvironmentScopeView] = []
        for coverage in coverage_rows:
            scope_row = scope_by_id[coverage.scope_id]
            state_rows = state_by_scope_env.get((coverage.scope_id, coverage.environment_scope), ())
            observed_metrics = {row.metric for row in state_rows}

            expected: list[tuple[str, str]] = [(f"environment_pressure:{metric}", metric) for metric in sorted(observed_metrics & PRESSURE_RULED_METRICS)]
            if coverage.environment_scope in LEAK_ELIGIBLE_ENVIRONMENT_SCOPES and "fd_open" in observed_metrics:
                expected.append(("environment_leak:fd_open", "fd_open"))
            if coverage.coverage == "uninstrumented":
                # No state row exists to read a metric from; fd_open is the
                # canonical placeholder metric, matching the periodic
                # assessor's own uninstrumented-declaration convention
                # (``_assess_environment``'s synthetic ``declaration`` pass).
                expected.append(("environment_pressure:fd_open", "fd_open"))

            beliefs: list[EnvironmentBeliefView] = []
            seen_fields: set[str] = set()
            for field_name, metric in expected:
                if field_name in seen_fields:
                    continue
                seen_fields.add(field_name)
                pair = belief_by_field.get((coverage.scope_id, field_name))
                if pair is None:
                    beliefs.append(
                        EnvironmentBeliefView(
                            field_name=field_name,
                            value={
                                "value": "unknown",
                                "metric": metric,
                                "environment_scope": coverage.environment_scope,
                                "coverage": coverage.coverage,
                            },
                            source=NamedVersion(name="none", version="1"),
                            authority_class="unknown",
                            fidelity_class="unknown",
                        )
                    )
                    continue
                current, assertion = pair
                beliefs.append(
                    EnvironmentBeliefView(
                        field_name=field_name,
                        value=dict(assertion.value_json),
                        as_of=_as_utc(assertion.as_of),
                        asserted_at=_as_utc(assertion.asserted_at),
                        source=NamedVersion(name=assertion.source_name, version=assertion.source_version),
                        authority_class=assertion.authority_class,
                        fidelity_class=assertion.fidelity_class,
                        evidence_obs_ids=tuple(evidence_by_assertion.get(assertion.assertion_id, ())),
                    )
                )

            scopes.append(
                EnvironmentScopeView(
                    scope_id=coverage.scope_id,
                    scope_kind=scope_row.scope_kind,
                    display_label=scope_row.display_label,
                    environment_scope=coverage.environment_scope,
                    coverage=coverage.coverage,
                    provider=coverage.provider,
                    metrics=tuple(
                        EnvironmentMetricView(
                            metric=row.metric,
                            latest_value=row.latest_value,
                            limit=row.limit_value,
                            as_of=_as_utc(row.as_of),
                            sample_count=row.sample_count,
                            window_started_at=_as_utc(row.window_started_at),
                            consecutive_growth_count=row.consecutive_growth_count,
                        )
                        for row in state_rows
                    ),
                    beliefs=tuple(beliefs),
                    alerts=tuple(
                        EnvironmentAlertSummaryView(
                            alert_id=row.entity_id,
                            alert_type=row.alert_type,
                            severity=row.severity,
                            workflow_state=row.workflow_state,
                            opened_at=_as_utc(row.opened_at),
                            resolved_at=(None if row.resolved_at is None else _as_utc(row.resolved_at)),
                            possibly_affected_task_ids=possibly_affected_by_alert_id.get(row.entity_id),
                        )
                        for row in alerts_by_scope.get(coverage.scope_id, [])
                    ),
                )
            )

        return TaskEnvironmentView(task_id=task_id, scopes=tuple(scopes))

    #: Read-side bound on the per-command sequence a single Task can return.
    #: A Task with more commands than this is truncated rather than paged: the
    #: consumer is a trend curve, not an audit list, and the ordered ToolCall
    #: accountability read is where a complete enumeration lives.
    _TOOL_ENV_SAMPLE_LIMIT = 500

    async def get_environment_history(
        self,
        scope_id: str,
        *,
        environment_scope: str,
        metric: str,
        window_minutes: int,
        max_points: int,
    ) -> EnvironmentHistoryView:
        """Replay one metric's recent readings straight off the Observation log.

        Deliberately not a read model: the trend is a lazy, bounded, on-demand
        read, so it is derived from the immutable ``environment.sampled``
        Observations rather than adding a fourth rebuildable table whose only
        consumer is a sparkline. A sample that does not carry ``metric`` is
        skipped, not zeroed — see ``EnvironmentHistoryView``.

        Note: this filters by ``subject_id`` while the available index is
        ``(kind, occurred_at)``. Environment observation volume is the same
        order of magnitude as heartbeats, so the residual scan is acceptable
        today; a ``(subject_id, kind, occurred_at)`` index is the registered
        follow-up if that volume rises.
        """

        window_start = datetime.now(UTC) - timedelta(minutes=window_minutes)
        async with self._session_factory() as session:
            rows = list(
                (
                    await session.execute(
                        select(AnsichObservationRow)
                        .where(
                            AnsichObservationRow.kind == "environment.sampled",
                            AnsichObservationRow.subject_id == scope_id,
                            AnsichObservationRow.occurred_at >= window_start,
                        )
                        .order_by(
                            AnsichObservationRow.occurred_at.asc(),
                            AnsichObservationRow.ingest_seq.asc(),
                        )
                    )
                ).scalars()
            )

        points: list[EnvironmentHistoryPoint] = []
        for row in rows:
            payload = row.payload_json
            if payload is None:
                # Environment payloads are small and never externalized, but a
                # payload-ref row would carry no readable metrics here, so it
                # is skipped rather than counted as a reading.
                continue
            if payload.get("environment_scope") != environment_scope:
                continue
            metrics = payload.get("metrics")
            if not isinstance(metrics, dict):
                continue
            reading = metrics.get(metric)
            if not isinstance(reading, dict):
                continue
            value = _as_non_negative_int(reading.get("value"))
            if value is None:
                continue
            points.append(
                EnvironmentHistoryPoint(
                    occurred_at=_as_utc(row.occurred_at),
                    value=value,
                    limit=_as_non_negative_int(reading.get("limit")),
                )
            )

        truncated = len(points) > max_points
        if truncated:
            # Keep the newest window: a trend read answers "what is happening
            # now", so dropping the oldest points is the honest truncation.
            points = points[-max_points:]
        return EnvironmentHistoryView(
            scope_id=scope_id,
            environment_scope=environment_scope,
            metric=metric,
            window_minutes=window_minutes,
            truncated=truncated,
            points=tuple(points),
        )

    async def get_task_tool_env_samples(self, task_id: str) -> TaskToolEnvSamplesView:
        """The Task's per-command samples in execution order."""

        async with self._session_factory() as session:
            rows = list(
                (
                    await session.execute(
                        select(AnsichToolEnvSampleRow)
                        .where(AnsichToolEnvSampleRow.task_id == task_id)
                        .order_by(
                            AnsichToolEnvSampleRow.started_at.asc(),
                            # Commands sharing a start instant (a sampler
                            # window that opened with the tool call) are still
                            # ordered by when they finished; the id is only the
                            # last deterministic tiebreak, never the ordering
                            # anyone reads meaning from.
                            AnsichToolEnvSampleRow.ended_at.asc(),
                            AnsichToolEnvSampleRow.tool_call_id.asc(),
                        )
                        # One row past the cap, so "there are more" is a fact
                        # read off the query rather than a separate count.
                        .limit(self._TOOL_ENV_SAMPLE_LIMIT + 1)
                    )
                ).scalars()
            )
        truncated = len(rows) > self._TOOL_ENV_SAMPLE_LIMIT
        return TaskToolEnvSamplesView(
            task_id=task_id,
            truncated=truncated,
            samples=tuple(
                ToolEnvSampleView(
                    tool_call_id=row.tool_call_id,
                    started_at=_as_utc(row.started_at),
                    ended_at=_as_utc(row.ended_at),
                    sample_count=row.sample_count,
                    fd_peak=row.fd_peak,
                    io_read_bytes=row.io_read_bytes,
                    io_write_bytes=row.io_write_bytes,
                )
                for row in rows[: self._TOOL_ENV_SAMPLE_LIMIT]
            ),
        )

    async def get_tool_environment_sample(self, tool_call_id: str) -> ToolEnvironmentSampleView | None:
        async with self._session_factory() as session:
            row = await session.get(AnsichToolEnvSampleRow, tool_call_id)
        if row is None:
            return None
        return ToolEnvironmentSampleView(
            tool_call_id=row.tool_call_id,
            task_id=row.task_id,
            scope_id=row.scope_id,
            io_read_bytes=row.io_read_bytes,
            io_write_bytes=row.io_write_bytes,
            fd_peak=row.fd_peak,
            sample_count=row.sample_count,
            started_at=_as_utc(row.started_at),
            ended_at=_as_utc(row.ended_at),
            obs_id=row.obs_id,
        )

    async def get_task_heartbeat(self, task_id: str) -> TaskHeartbeatView | None:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(AnsichTaskHeartbeatRow)
                .where(AnsichTaskHeartbeatRow.task_id == task_id)
                .order_by(
                    AnsichTaskHeartbeatRow.occurred_at.desc(),
                    AnsichTaskHeartbeatRow.heartbeat_obs_id.desc(),
                )
                .limit(1)
            )
        if row is None:
            return None
        return TaskHeartbeatView(
            task_id=row.task_id,
            heartbeat_obs_id=row.heartbeat_obs_id,
            occurred_at=_as_utc(row.occurred_at),
            producer_instance_id=row.producer_instance_id,
            ownership_epoch=row.ownership_epoch,
            elapsed_ms=row.elapsed_ms,
        )

    async def assess_operations(
        self,
        *,
        now: datetime | None = None,
        incomplete_task_ids: tuple[str, ...] = (),
        global_loss: bool = False,
        lost_ranges: tuple[LostRange, ...] = (),
    ) -> int:
        asserted_at = datetime.now(UTC) if now is None else now
        incomplete_tasks = frozenset(incomplete_task_ids)
        await self._process_assessor_jobs(
            now=asserted_at,
            incomplete_tasks=incomplete_tasks,
            global_loss=global_loss,
        )
        # Preserve the Phase 5 return contract: this count reports periodic
        # operational Belief transitions, not event-driven assessor or Alert
        # projection churn.
        changed = 0
        async with self._session_factory() as session, session.begin():
            task_ids = tuple((await session.execute(select(AnsichTaskSummaryRow.task_id).where(AnsichTaskSummaryRow.control_value == "running"))).scalars())
            for task_id in task_ids:
                heartbeat_row = await session.scalar(
                    select(AnsichTaskHeartbeatRow)
                    .where(AnsichTaskHeartbeatRow.task_id == task_id)
                    .order_by(
                        AnsichTaskHeartbeatRow.occurred_at.desc(),
                        AnsichTaskHeartbeatRow.heartbeat_obs_id.desc(),
                    )
                    .limit(1)
                )
                heartbeat = None
                if heartbeat_row is not None:
                    heartbeat = TaskHeartbeatView(
                        task_id=heartbeat_row.task_id,
                        heartbeat_obs_id=heartbeat_row.heartbeat_obs_id,
                        occurred_at=_as_utc(heartbeat_row.occurred_at),
                        producer_instance_id=heartbeat_row.producer_instance_id,
                        ownership_epoch=heartbeat_row.ownership_epoch,
                        elapsed_ms=heartbeat_row.elapsed_ms,
                    )
                belief = assess_heartbeat(
                    heartbeat,
                    now=asserted_at,
                    stale_after_seconds=self._heartbeat_stale_after_seconds,
                )
                current = await session.get(
                    AnsichCurrentBeliefRow,
                    (task_id, "heartbeat"),
                )
                current_assertion = None
                current_evidence: tuple[str, ...] = ()
                if current is not None:
                    current_assertion = await session.get(
                        AnsichBeliefAssertionRow,
                        current.assertion_id,
                    )
                    current_evidence = tuple((await session.execute(select(AnsichBeliefEvidenceRow.obs_id).where(AnsichBeliefEvidenceRow.assertion_id == current.assertion_id).order_by(AnsichBeliefEvidenceRow.ordinal))).scalars())
                heartbeat_unchanged = (
                    current_assertion is not None and current_assertion.value_json == {"value": belief.value} and current_evidence == belief.evidence_obs_ids and current is not None and current.resolver_version == belief.selected_by.version
                )
                if heartbeat_unchanged:
                    assertion = current_assertion
                else:
                    assertion = AnsichBeliefAssertionRow(
                        assertion_id=new_id(),
                        subject_id=task_id,
                        field_name="heartbeat",
                        value_json={"value": belief.value},
                        as_of=belief.as_of or asserted_at,
                        asserted_at=belief.asserted_at,
                        source_name=belief.source.name,
                        source_version=belief.source.version,
                        assessor_name=belief.source.name,
                        assessor_version=belief.source.version,
                        config_hash=canonical_config_hash(
                            {
                                "stale_after_seconds": self._heartbeat_stale_after_seconds,
                            }
                        ),
                        authority_class="configured_rule",
                        fidelity_class=belief.fidelity_class,
                        confidence=None,
                    )
                    session.add(assertion)
                    for ordinal, obs_id in enumerate(belief.evidence_obs_ids):
                        session.add(
                            AnsichBeliefEvidenceRow(
                                assertion_id=assertion.assertion_id,
                                obs_id=obs_id,
                                evidence_role="supporting",
                                ordinal=ordinal,
                            )
                        )
                    if current is None:
                        session.add(
                            AnsichCurrentBeliefRow(
                                subject_id=task_id,
                                field_name="heartbeat",
                                assertion_id=assertion.assertion_id,
                                resolver_name=belief.selected_by.name,
                                resolver_version=belief.selected_by.version,
                            )
                        )
                    else:
                        current.assertion_id = assertion.assertion_id
                        current.resolver_name = belief.selected_by.name
                        current.resolver_version = belief.selected_by.version
                    changed += 1
                heartbeat_assessment = Assessment(
                    subject_id=task_id,
                    field_name="heartbeat",
                    value={"value": belief.value},
                    as_of=belief.as_of or asserted_at,
                    asserted_at=belief.asserted_at,
                    assessor=belief.source,
                    config_hash=canonical_config_hash(
                        {
                            "stale_after_seconds": self._heartbeat_stale_after_seconds,
                        }
                    ),
                    authority_class="configured_rule",
                    fidelity_class=belief.fidelity_class,
                    evidence=tuple(EvidenceRef(obs_id=obs_id) for obs_id in belief.evidence_obs_ids),
                )
                await self._reconcile_alerts_for_assessment(
                    session,
                    assessment=heartbeat_assessment,
                    source_assertion_id=assertion.assertion_id,
                    now=asserted_at,
                )
                changed += await self._assess_and_reconcile_dwell(
                    session,
                    task_id=task_id,
                    now=asserted_at,
                )
            budget_rows = list((await session.execute(_periodic_budget_rows_statement())).scalars())
            changed += await self._assess_budget_rows(
                session,
                budget_rows=budget_rows,
                asserted_at=asserted_at,
                incomplete_tasks=incomplete_tasks,
                global_loss=global_loss,
            )
            changed += await self._assess_environment(session, asserted_at)
        await self._refresh_active_task_read_model(
            now=asserted_at,
            lost_ranges=lost_ranges,
        )
        return changed

    #: Alert types produced by ``environment-pressure@1``. An unresolved
    #: episode of one of these keeps its Scope in the assessment candidate set
    #: even after every Task attached to it has ended, so the episode can still
    #: be resolved instead of being stranded open forever.
    _ENVIRONMENT_ALERT_TYPES = ("environment_pressure", "environment_leak_suspected")

    async def _assess_environment(
        self,
        session: AsyncSession,
        asserted_at: datetime,
    ) -> int:
        """Assess every environment Scope that still matters, once per tick.

        A Scope is a candidate when a running Task is attached to it, or when it
        still carries an unresolved environment Alert. Everything else is
        historical: its readings are frozen and re-judging them would only
        append noise.
        """

        running_by_scope: dict[str, list[str]] = {}
        rows = await session.execute(
            select(AnsichRelationRow.object_id, AnsichRelationRow.subject_id)
            .join(
                AnsichTaskSummaryRow,
                AnsichTaskSummaryRow.task_id == AnsichRelationRow.subject_id,
            )
            .where(
                AnsichRelationRow.predicate == "within_scope",
                AnsichRelationRow.relation_role.in_(("sandbox_boundary", "host_environment")),
                AnsichTaskSummaryRow.control_value == "running",
            )
        )
        for scope_id, task_id in rows:
            running_by_scope.setdefault(scope_id, []).append(task_id)
        open_alert_scopes = set(
            (
                await session.execute(
                    select(AnsichAlertRow.subject_id).where(
                        AnsichAlertRow.alert_type.in_(self._ENVIRONMENT_ALERT_TYPES),
                        AnsichAlertRow.resolved_at.is_(None),
                    )
                )
            ).scalars()
        )
        candidate_scopes = sorted(set(running_by_scope) | open_alert_scopes)
        if not candidate_scopes:
            return 0
        state_by_scope: dict[str, list[AnsichEnvironmentStateRow]] = {}
        for row in (await session.execute(select(AnsichEnvironmentStateRow).where(AnsichEnvironmentStateRow.scope_id.in_(candidate_scopes)).order_by(AnsichEnvironmentStateRow.environment_scope, AnsichEnvironmentStateRow.metric))).scalars():
            state_by_scope.setdefault(row.scope_id, []).append(row)
        coverage_by_scope: dict[str, dict[str, AnsichEnvironmentCoverageRow]] = {}
        for row in (await session.execute(select(AnsichEnvironmentCoverageRow).where(AnsichEnvironmentCoverageRow.scope_id.in_(candidate_scopes)).order_by(AnsichEnvironmentCoverageRow.environment_scope))).scalars():
            coverage_by_scope.setdefault(row.scope_id, {})[row.environment_scope] = row
        thresholds = self._environment_thresholds
        changed = 0
        for scope_id in candidate_scopes:
            coverage_rows = coverage_by_scope.get(scope_id, {})
            assessments: list[Assessment] = []
            observed_environment_scopes = {row.environment_scope for row in state_by_scope.get(scope_id, ())}
            for row in state_by_scope.get(scope_id, ()):
                coverage = coverage_rows.get(row.environment_scope)
                # A state row without a coverage row can only come from a
                # partially projected Scope; the sample itself proves continuous
                # collection, so assume that rather than skipping the reading.
                coverage_value = coverage.coverage if coverage is not None else "continuous"
                pressure = assess_environment_pressure(
                    scope_id=scope_id,
                    metric=row.metric,
                    environment_scope=row.environment_scope,
                    coverage=coverage_value,
                    latest_value=row.latest_value,
                    limit=row.limit_value,
                    as_of=_as_utc(row.as_of),
                    last_obs_id=row.last_obs_id,
                    now=asserted_at,
                    sample_interval_seconds=self._environment_sample_interval_seconds,
                    thresholds=thresholds,
                )
                if pressure is not None:
                    assessments.append(pressure)
                if row.metric == "fd_open":
                    leak = assess_environment_leak(
                        scope_id=scope_id,
                        environment_scope=row.environment_scope,
                        coverage=coverage_value,
                        consecutive_growth_count=row.consecutive_growth_count,
                        growth_started_at=(_as_utc(row.growth_started_at) if row.growth_started_at is not None else None),
                        window_min_value=row.window_min_value,
                        latest_value=row.latest_value,
                        as_of=_as_utc(row.as_of),
                        last_obs_id=row.last_obs_id,
                        now=asserted_at,
                        thresholds=thresholds,
                    )
                    if leak is not None:
                        assessments.append(leak)
            for environment_scope, coverage in coverage_rows.items():
                if coverage.coverage != "uninstrumented":
                    continue
                if environment_scope in observed_environment_scopes:
                    # A Scope that went uninstrumented after being sampled keeps
                    # its state rows, and those already produced the unknown
                    # assertions above; a synthetic declaration here would only
                    # duplicate one of them under the same field name.
                    continue
                # An uninstrumented declaration has no state rows at all, so it
                # would otherwise leave no Belief. Recording the unknown makes
                # "we cannot see this Scope" queryable instead of invisible.
                declaration = assess_environment_pressure(
                    scope_id=scope_id,
                    metric="fd_open",
                    environment_scope=environment_scope,
                    coverage="uninstrumented",
                    latest_value=0,
                    limit=None,
                    as_of=_as_utc(coverage.as_of),
                    last_obs_id=coverage.last_obs_id,
                    now=asserted_at,
                    sample_interval_seconds=self._environment_sample_interval_seconds,
                    thresholds=thresholds,
                )
                if declaration is not None:
                    assessments.append(declaration)
            if not assessments:
                continue
            reconciled: list[tuple[Assessment, str]] = []
            for assessment in assessments:
                assertion, did_change = await self._persist_environment_assessment(
                    session,
                    assessment,
                )
                changed += int(did_change)
                reconciled.append((assessment, assertion.assertion_id))
            await self._reconcile_alerts_for_assessments(
                session,
                subject_id=scope_id,
                assessments=reconciled,
                now=asserted_at,
                # Sorted so the persisted read-model list is a function of the
                # running set, not of row order.
                possibly_affected_task_ids=sorted(running_by_scope.get(scope_id, ())),
            )
        return changed

    async def _persist_environment_assessment(
        self,
        session: AsyncSession,
        assessment: Assessment,
    ) -> tuple[AnsichBeliefAssertionRow, bool]:
        """Append an environment Assertion only when the category transitions.

        This mirrors the heartbeat block's unchanged-skip rather than
        ``_persist_assessment``'s, with one deliberate difference: neither
        ``as_of`` nor the evidence Observation participates in the comparison.
        Both advance with every accepted sample, so including them would append
        an Assertion per sample and defeat the transition-only property the
        stable value dict exists to provide. The retained Assertion keeps
        pointing at the Observation that first established the state, which is
        exactly what it asserts; the current numbers live in the environment
        read-model rows.
        """

        latest = await session.scalar(
            select(AnsichBeliefAssertionRow)
            .where(
                AnsichBeliefAssertionRow.subject_id == assessment.subject_id,
                AnsichBeliefAssertionRow.field_name == assessment.field_name,
                AnsichBeliefAssertionRow.assessor_name == assessment.assessor.name,
                AnsichBeliefAssertionRow.assessor_version == assessment.assessor.version,
                AnsichBeliefAssertionRow.config_hash == assessment.config_hash,
            )
            .order_by(
                AnsichBeliefAssertionRow.asserted_at.desc(),
                AnsichBeliefAssertionRow.assertion_id.desc(),
            )
            .limit(1)
        )
        if latest is not None and latest.value_json == assessment.value:
            return latest, False
        assertion = AnsichBeliefAssertionRow(
            assertion_id=new_id(),
            subject_id=assessment.subject_id,
            field_name=assessment.field_name,
            value_json=assessment.value,
            as_of=assessment.as_of,
            asserted_at=assessment.asserted_at,
            source_name=assessment.assessor.name,
            source_version=assessment.assessor.version,
            assessor_name=assessment.assessor.name,
            assessor_version=assessment.assessor.version,
            config_hash=assessment.config_hash,
            authority_class=assessment.authority_class,
            fidelity_class=assessment.fidelity_class,
            confidence=assessment.confidence,
        )
        session.add(assertion)
        for ordinal, evidence in enumerate(assessment.evidence):
            session.add(
                AnsichBeliefEvidenceRow(
                    assertion_id=assertion.assertion_id,
                    obs_id=evidence.obs_id,
                    evidence_role=evidence.role,
                    ordinal=ordinal,
                )
            )
        await session.flush()
        await self._resolve_current_assessment(
            session,
            subject_id=assessment.subject_id,
            field_name=assessment.field_name,
        )
        return assertion, True

    async def _assess_and_reconcile_dwell(
        self,
        session: AsyncSession,
        *,
        task_id: str,
        now: datetime,
    ) -> int:
        step = await session.scalar(
            select(AnsichStepRow)
            .where(
                AnsichStepRow.task_id == task_id,
                AnsichStepRow.status.not_in(("closed", "model_failed")),
            )
            .order_by(AnsichStepRow.step_seq.desc())
            .limit(1)
        )
        tool = None
        if step is not None:
            tool = await session.scalar(
                select(AnsichToolCallRow)
                .where(
                    AnsichToolCallRow.step_id == step.entity_id,
                    AnsichToolCallRow.execution_status.in_(("issued", "acting")),
                )
                .order_by(AnsichToolCallRow.call_seq.desc())
                .limit(1)
            )
        evidence_obs_id = None
        if tool is not None:
            evidence_obs_id = tool.started_obs_id or tool.issued_obs_id
        if evidence_obs_id is None and step is not None:
            evidence_obs_id = step.started_obs_id
        action_observation = None if evidence_obs_id is None else await session.scalar(select(AnsichObservationRow).where(AnsichObservationRow.obs_id == evidence_obs_id))
        dwell = assess_dwell(
            since=(None if action_observation is None else _as_utc(action_observation.occurred_at)),
            evidence_obs_id=evidence_obs_id,
            now=now,
            long_dwell_seconds=self._long_dwell_seconds,
        )
        evidence = tuple(EvidenceRef(obs_id=obs_id) for obs_id in dwell.evidence_obs_ids)
        config_hash = canonical_config_hash({"long_dwell_seconds": self._long_dwell_seconds})
        assessment = Assessment(
            subject_id=task_id,
            field_name="dwell",
            value={"value": dwell.value},
            as_of=dwell.since or now,
            asserted_at=dwell.asserted_at,
            assessor=dwell.source,
            config_hash=config_hash,
            authority_class="configured_rule",
            fidelity_class=dwell.fidelity_class,
            evidence=evidence,
        )
        current = await session.get(
            AnsichCurrentBeliefRow,
            (task_id, "dwell"),
        )
        if evidence_obs_id is None and current is None:
            return 0
        current_assertion = (
            None
            if current is None
            else await session.get(
                AnsichBeliefAssertionRow,
                current.assertion_id,
            )
        )
        current_evidence: tuple[str, ...] = ()
        if current_assertion is not None:
            current_evidence = tuple((await session.execute(select(AnsichBeliefEvidenceRow.obs_id).where(AnsichBeliefEvidenceRow.assertion_id == current_assertion.assertion_id).order_by(AnsichBeliefEvidenceRow.ordinal))).scalars())
        unchanged = current_assertion is not None and current_assertion.value_json == assessment.value and current_assertion.config_hash == config_hash and current_evidence == dwell.evidence_obs_ids
        if unchanged:
            assertion = current_assertion
            changed = 0
        else:
            assertion, did_change = await self._persist_assessment(
                session,
                assessment,
            )
            changed = int(did_change)
        await self._reconcile_alerts_for_assessment(
            session,
            assessment=assessment,
            source_assertion_id=assertion.assertion_id,
            now=now,
        )
        return changed

    async def _budget_usage_evidence(
        self,
        session: AsyncSession,
        *,
        aggregate_task_id: str,
        dimension: str,
        aggregation_scope: str,
    ) -> tuple[str, ...]:
        """Usage evidence for one budget row, in the order the assessor uses.

        ``_assess_budget_rows`` and ``_assess_absolute_limits_at`` both write
        ``budget_health:<dimension>:<scope>`` Belief Assertions for the same
        Task, and the Belief resolver separates two same-authority assertions
        on ``as_of`` then ``asserted_at``. The terminal-projection call asserts
        at ``recorded_at`` (ingest wall clock) while the assessor asserts at
        event time, so whichever evidence order the two paths disagree on
        becomes a race between two clocks. They must therefore agree by
        construction: summed dimensions keep contribution order, and
        ``wall_time_ms`` — the one maximum-valued dimension, which retains both
        the terminal contribution and the heartbeat high-water mark — goes
        through ``order_wall_time_evidence``.
        """

        scope_filter = (AnsichUsageContributionRow.source_task_id == aggregate_task_id,) if aggregation_scope == "local" else ()
        base_filters = (
            AnsichUsageContributionRow.aggregate_task_id == aggregate_task_id,
            AnsichUsageContributionRow.dimension == dimension,
            *scope_filter,
        )
        ordering = (
            AnsichUsageContributionRow.as_of,
            AnsichUsageContributionRow.source_obs_id,
        )
        if dimension != "wall_time_ms":
            return tuple((await session.execute(select(AnsichUsageContributionRow.source_obs_id).where(*base_filters).order_by(*ordering))).scalars())
        wall_time_rows = (
            await session.execute(
                select(
                    AnsichUsageContributionRow.source_task_id,
                    AnsichUsageContributionRow.source_obs_id,
                    AnsichUsageContributionRow.delta,
                    AnsichObservationRow.kind,
                )
                .join(
                    AnsichObservationRow,
                    AnsichObservationRow.obs_id == AnsichUsageContributionRow.source_obs_id,
                )
                .where(*base_filters)
                .order_by(*ordering)
            )
        ).all()
        return order_wall_time_evidence(
            WallTimeEvidenceRow(
                source_task_id=source_task_id,
                source_obs_id=source_obs_id,
                delta=delta,
                from_heartbeat=kind == "task.heartbeat",
            )
            for source_task_id, source_obs_id, delta, kind in wall_time_rows
        )

    async def _assess_budget_rows(
        self,
        session: AsyncSession,
        *,
        budget_rows: list[AnsichTaskBudgetRow],
        asserted_at: datetime,
        incomplete_tasks: frozenset[str],
        global_loss: bool,
    ) -> int:
        changed = 0
        for budget_row in budget_rows:
            usage_row = await session.get(
                AnsichTaskUsageRow,
                (
                    budget_row.task_id,
                    budget_row.dimension,
                    budget_row.aggregation_scope,
                ),
            )
            budget = TaskBudgetView(
                entity_id=budget_row.entity_id,
                task_id=budget_row.task_id,
                dimension=budget_row.dimension,
                aggregation_scope=budget_row.aggregation_scope,
                warning_limit=budget_row.warning_limit,
                hard_limit=budget_row.hard_limit,
                enforcement=budget_row.enforcement,
                source_kind=cast(BudgetSourceKind, budget_row.source_kind),
                requested_value=budget_row.requested_value,
                effective_value=budget_row.effective_value,
                configured_obs_id=budget_row.configured_obs_id,
            )
            usage = None
            usage_evidence: tuple[str, ...] = ()
            if usage_row is not None:
                usage = TaskUsageValue(
                    dimension=usage_row.dimension,
                    aggregation_scope=usage_row.aggregation_scope,
                    value=usage_row.value,
                    as_of=_as_utc(usage_row.as_of),
                    complete_through_ingest_seq=usage_row.complete_through_ingest_seq,
                )
                usage_evidence = await self._budget_usage_evidence(
                    session,
                    aggregate_task_id=budget_row.task_id,
                    dimension=budget_row.dimension,
                    aggregation_scope=budget_row.aggregation_scope,
                )
            belief = assess_budget_health(
                budget,
                usage,
                now=asserted_at,
                usage_complete=(not global_loss and budget_row.task_id not in incomplete_tasks),
                usage_evidence_obs_ids=usage_evidence,
            )
            field_name = f"budget_health:{belief.dimension}:{belief.aggregation_scope}"
            value_json = {
                "value": belief.value,
                "dimension": belief.dimension,
                "aggregation_scope": belief.aggregation_scope,
                "usage_value": belief.usage_value,
                "warning_limit": belief.warning_limit,
                "hard_limit": belief.hard_limit,
                "overshoot": belief.overshoot,
                "as_of_known": belief.as_of is not None,
            }
            current = await session.get(
                AnsichCurrentBeliefRow,
                (budget_row.task_id, field_name),
            )
            current_assertion = None
            current_evidence: tuple[str, ...] = ()
            if current is not None:
                current_assertion = await session.get(
                    AnsichBeliefAssertionRow,
                    current.assertion_id,
                )
                current_evidence = tuple((await session.execute(select(AnsichBeliefEvidenceRow.obs_id).where(AnsichBeliefEvidenceRow.assertion_id == current.assertion_id).order_by(AnsichBeliefEvidenceRow.ordinal))).scalars())
            if current_assertion is not None and current_assertion.value_json == value_json and current_evidence == belief.evidence_obs_ids and current is not None and current.resolver_version == belief.selected_by.version:
                continue
            assertion = AnsichBeliefAssertionRow(
                assertion_id=new_id(),
                subject_id=budget_row.task_id,
                field_name=field_name,
                value_json=value_json,
                as_of=belief.as_of or asserted_at,
                asserted_at=belief.asserted_at,
                source_name=belief.source.name,
                source_version=belief.source.version,
                assessor_name=belief.source.name,
                assessor_version=belief.source.version,
                config_hash=canonical_config_hash(
                    {
                        "dimension": budget.dimension,
                        "aggregation_scope": budget.aggregation_scope,
                        "warning_limit": budget.warning_limit,
                        "hard_limit": budget.hard_limit,
                        "enforcement": budget.enforcement,
                    }
                ),
                authority_class="configured_rule",
                fidelity_class=belief.fidelity_class,
                confidence=None,
            )
            session.add(assertion)
            for ordinal, obs_id in enumerate(belief.evidence_obs_ids):
                session.add(
                    AnsichBeliefEvidenceRow(
                        assertion_id=assertion.assertion_id,
                        obs_id=obs_id,
                        evidence_role="supporting",
                        ordinal=ordinal,
                    )
                )
            if current is None:
                session.add(
                    AnsichCurrentBeliefRow(
                        subject_id=budget_row.task_id,
                        field_name=field_name,
                        assertion_id=assertion.assertion_id,
                        resolver_name=belief.selected_by.name,
                        resolver_version=belief.selected_by.version,
                    )
                )
            else:
                current.assertion_id = assertion.assertion_id
                current.resolver_name = belief.selected_by.name
                current.resolver_version = belief.selected_by.version
            changed += 1
        return changed

    async def get_task_heartbeat_belief(
        self,
        task_id: str,
        *,
        now: datetime | None = None,
    ) -> HeartbeatBelief | None:
        async with self._session_factory() as session:
            current = await session.get(
                AnsichCurrentBeliefRow,
                (task_id, "heartbeat"),
            )
            if current is None:
                return None
            assertion = await session.get(
                AnsichBeliefAssertionRow,
                current.assertion_id,
            )
            if assertion is None:
                return None
            evidence = tuple((await session.execute(select(AnsichBeliefEvidenceRow.obs_id).where(AnsichBeliefEvidenceRow.assertion_id == assertion.assertion_id).order_by(AnsichBeliefEvidenceRow.ordinal))).scalars())
            value = str(assertion.value_json["value"])
            as_of = None if value == "unknown" else _as_utc(assertion.as_of)
            age_reference = _as_utc(assertion.asserted_at) if now is None else now
            age_ms = None if as_of is None else max(0, int((age_reference - as_of).total_seconds() * 1000))
            return HeartbeatBelief(
                value=cast(Literal["unknown", "fresh", "stale"], value),
                as_of=as_of,
                asserted_at=_as_utc(assertion.asserted_at),
                age_ms=age_ms,
                source=NamedVersion(
                    name=assertion.source_name,
                    version=assertion.source_version,
                ),
                fidelity_class="rule",
                selected_by=NamedVersion(
                    name=current.resolver_name,
                    version=current.resolver_version,
                ),
                evidence_obs_ids=evidence,
            )

    async def get_task_budget_health(
        self,
        task_id: str,
    ) -> tuple[BudgetHealthBelief, ...]:
        async with self._session_factory() as session:
            rows = list(
                (
                    await session.execute(
                        select(AnsichCurrentBeliefRow, AnsichBeliefAssertionRow)
                        .join(
                            AnsichBeliefAssertionRow,
                            AnsichBeliefAssertionRow.assertion_id == AnsichCurrentBeliefRow.assertion_id,
                        )
                        .where(
                            AnsichCurrentBeliefRow.subject_id == task_id,
                            AnsichCurrentBeliefRow.field_name.like("budget_health:%"),
                        )
                    )
                ).all()
            )
            beliefs: list[BudgetHealthBelief] = []
            for current, assertion in rows:
                evidence = tuple((await session.execute(select(AnsichBeliefEvidenceRow.obs_id).where(AnsichBeliefEvidenceRow.assertion_id == assertion.assertion_id).order_by(AnsichBeliefEvidenceRow.ordinal))).scalars())
                value_json = assertion.value_json
                as_of_known = value_json.get("as_of_known")
                if as_of_known is None:
                    as_of_known = value_json.get("value") != "unknown" and value_json.get("usage_value") is not None
                beliefs.append(
                    BudgetHealthBelief(
                        dimension=value_json["dimension"],
                        aggregation_scope=value_json["aggregation_scope"],
                        value=value_json["value"],
                        usage_value=value_json.get("usage_value"),
                        warning_limit=value_json.get("warning_limit"),
                        hard_limit=value_json.get("hard_limit"),
                        overshoot=value_json.get("overshoot"),
                        as_of=(_as_utc(assertion.as_of) if as_of_known else None),
                        asserted_at=_as_utc(assertion.asserted_at),
                        source=NamedVersion(
                            name=assertion.source_name,
                            version=assertion.source_version,
                        ),
                        fidelity_class="rule",
                        selected_by=NamedVersion(
                            name=current.resolver_name,
                            version=current.resolver_version,
                        ),
                        evidence_obs_ids=evidence,
                    )
                )
        beliefs.sort(
            key=lambda item: (
                _USAGE_DIMENSION_ORDER[item.dimension],
                item.aggregation_scope,
            )
        )
        return tuple(beliefs)

    async def _refresh_active_task_read_model(
        self,
        *,
        now: datetime,
        lost_ranges: tuple[LostRange, ...],
    ) -> None:
        async with self._session_factory() as session:
            running_task_ids = tuple((await session.execute(select(AnsichTaskSummaryRow.task_id).where(AnsichTaskSummaryRow.control_value == "running"))).scalars())

        views: list[ActiveTaskView] = []
        metrics = self.get_projection_metrics()
        for task_id in running_task_ids:
            task = await self.get_task(task_id)
            if task is None:
                continue
            heartbeat = await self.get_task_heartbeat_belief(task_id, now=now)
            if heartbeat is None:
                heartbeat = assess_heartbeat(
                    None,
                    now=now,
                    stale_after_seconds=self._heartbeat_stale_after_seconds,
                )
            usage = await self.get_task_usage(task_id)
            budgets = await self.get_task_budgets(task_id)
            budget_health = await self.get_task_budget_health(task_id)
            async with self._session_factory() as session:
                scope_rows = list(
                    (
                        await session.execute(
                            select(AnsichScopeRow)
                            .join(
                                AnsichRelationRow,
                                AnsichRelationRow.object_id == AnsichScopeRow.entity_id,
                            )
                            .where(
                                AnsichRelationRow.subject_id == task_id,
                                AnsichRelationRow.predicate == "within_scope",
                            )
                        )
                    ).scalars()
                )
                scopes = {row.scope_kind: row.display_label for row in scope_rows}
                step = await session.scalar(
                    select(AnsichStepRow)
                    .where(
                        AnsichStepRow.task_id == task_id,
                        AnsichStepRow.status.not_in(("closed", "model_failed")),
                    )
                    .order_by(AnsichStepRow.step_seq.desc())
                    .limit(1)
                )
                tool = None
                if step is not None:
                    tool = await session.scalar(
                        select(AnsichToolCallRow)
                        .where(
                            AnsichToolCallRow.step_id == step.entity_id,
                            AnsichToolCallRow.execution_status.in_(("issued", "acting")),
                        )
                        .order_by(AnsichToolCallRow.call_seq.desc())
                        .limit(1)
                    )
                evidence_obs_id = None
                if tool is not None:
                    evidence_obs_id = tool.started_obs_id or tool.issued_obs_id
                if evidence_obs_id is None and step is not None:
                    evidence_obs_id = step.started_obs_id
                action_observation = None if evidence_obs_id is None else await session.scalar(select(AnsichObservationRow).where(AnsichObservationRow.obs_id == evidence_obs_id))
                running_transition = await session.scalar(
                    select(AnsichTransitionRow)
                    .where(
                        AnsichTransitionRow.subject_id == task_id,
                        AnsichTransitionRow.field_name == "control",
                        AnsichTransitionRow.to_value == "running",
                    )
                    .order_by(AnsichTransitionRow.occurred_at.desc())
                    .limit(1)
                )
                last_evidence_at = await session.scalar(select(func.max(AnsichObservationRow.occurred_at)).where(AnsichObservationRow.task_id == task_id))

            dwell = assess_dwell(
                since=(None if action_observation is None else _as_utc(action_observation.occurred_at)),
                evidence_obs_id=evidence_obs_id,
                now=now,
                long_dwell_seconds=self._long_dwell_seconds,
            )
            started_at = task.control.as_of if running_transition is None else _as_utc(running_transition.occurred_at)
            duration_ms = 0 if started_at is None else max(0, int((now - started_at).total_seconds() * 1000))
            task_lost_ranges = tuple(item for item in lost_ranges if item.task_id is None or item.task_id == task_id)
            views.append(
                ActiveTaskView(
                    task_id=task_id,
                    run_id=task.source_id,
                    source_kind=task.source_kind,
                    owner_id=scopes.get("owner"),
                    thread_id=scopes.get("thread"),
                    agent_id=None,
                    control=task.control,
                    current_step=(
                        None
                        if step is None
                        else ActiveStepView(
                            step_id=step.entity_id,
                            step_seq=step.step_seq,
                            actor_kind=step.actor_kind,
                            status=step.status,
                        )
                    ),
                    current_tool=(
                        None
                        if tool is None
                        else ActiveToolView(
                            tool_call_id=tool.entity_id,
                            tool_name=tool.tool_name,
                            call_seq=tool.call_seq,
                            status=tool.execution_status,
                        )
                    ),
                    dwell=dwell,
                    heartbeat=heartbeat,
                    usage=usage,
                    budgets=budgets,
                    budget_health=budget_health,
                    duration_ms=duration_ms,
                    observability_status=task.observability_status,
                    projection_watermark=metrics.get("watermark"),
                    projection_lag_ms=int(metrics.get("lag_ms", 0)),
                    lost_ranges=task_lost_ranges,
                    last_evidence_at=(task.control.as_of if last_evidence_at is None else _as_utc(last_evidence_at)),
                    updated_at=now,
                )
            )

        async with self._session_factory() as session, session.begin():
            if running_task_ids:
                await session.execute(delete(AnsichActiveTaskReadModelRow).where(AnsichActiveTaskReadModelRow.task_id.not_in(running_task_ids)))
            else:
                await session.execute(delete(AnsichActiveTaskReadModelRow))
            for view in views:
                budget_status = "unknown"
                for candidate in ("exceeded", "warning", "unknown", "within"):
                    if any(belief.value == candidate for belief in view.budget_health):
                        budget_status = candidate
                        break
                values = {
                    "run_id": view.run_id,
                    "source_kind": view.source_kind,
                    "owner_id": view.owner_id,
                    "thread_id": view.thread_id,
                    "agent_id": view.agent_id,
                    "control_value": view.control.value,
                    "current_step_id": (None if view.current_step is None else view.current_step.step_id),
                    "current_tool_call_id": (None if view.current_tool is None else view.current_tool.tool_call_id),
                    "heartbeat_value": view.heartbeat.value,
                    "budget_status": budget_status,
                    "duration_ms": view.duration_ms,
                    "observability_status": view.observability_status,
                    "projection_watermark": view.projection_watermark,
                    "projection_lag_ms": view.projection_lag_ms,
                    "control_json": view.control.model_dump(mode="json"),
                    "current_step_json": (None if view.current_step is None else view.current_step.model_dump(mode="json")),
                    "current_tool_json": (None if view.current_tool is None else view.current_tool.model_dump(mode="json")),
                    "dwell_json": view.dwell.model_dump(mode="json"),
                    "heartbeat_json": view.heartbeat.model_dump(mode="json"),
                    "usage_json": view.usage.model_dump(mode="json"),
                    "budgets_json": view.budgets.model_dump(mode="json"),
                    "budget_health_json": [item.model_dump(mode="json") for item in view.budget_health],
                    "lost_ranges_json": [item.model_dump(mode="json") for item in view.lost_ranges],
                    "last_evidence_at": view.last_evidence_at,
                }
                row = await session.get(
                    AnsichActiveTaskReadModelRow,
                    view.task_id,
                )
                if row is None:
                    session.add(
                        AnsichActiveTaskReadModelRow(
                            task_id=view.task_id,
                            updated_at=view.updated_at,
                            **values,
                        )
                    )
                elif any(not _read_model_values_equal(getattr(row, key), value) for key, value in values.items()):
                    for key, value in values.items():
                        setattr(row, key, value)
                    row.updated_at = view.updated_at

    async def list_active_tasks(
        self,
        *,
        limit: int = 100,
        owner_id: str | None = None,
        agent_id: str | None = None,
        control: ControlValue | None = None,
        heartbeat_status: str | None = None,
        budget_status: str | None = None,
        min_duration_ms: int | None = None,
        max_duration_ms: int | None = None,
        observability_status: str | None = None,
        cursor: tuple[datetime, str] | None = None,
    ) -> list[ActiveTaskView]:
        if limit < 1:
            raise ValueError("limit must be positive")
        active_child_count = (
            select(func.count())
            .select_from(AnsichTaskSpawnRow)
            .join(
                AnsichTaskSummaryRow,
                AnsichTaskSummaryRow.task_id == AnsichTaskSpawnRow.child_task_id,
            )
            .where(
                AnsichTaskSpawnRow.parent_task_id == AnsichActiveTaskReadModelRow.task_id,
                AnsichTaskSummaryRow.control_value == "running",
            )
            .correlate(AnsichActiveTaskReadModelRow)
            .scalar_subquery()
        )
        statement = select(
            AnsichActiveTaskReadModelRow,
            active_child_count.label("active_child_count"),
        )
        if owner_id is not None:
            statement = statement.where(AnsichActiveTaskReadModelRow.owner_id == owner_id)
        if agent_id is not None:
            statement = statement.where(AnsichActiveTaskReadModelRow.agent_id == agent_id)
        if control is not None:
            statement = statement.where(AnsichActiveTaskReadModelRow.control_value == control)
        if heartbeat_status is not None:
            statement = statement.where(AnsichActiveTaskReadModelRow.heartbeat_value == heartbeat_status)
        if budget_status is not None:
            statement = statement.where(AnsichActiveTaskReadModelRow.budget_status == budget_status)
        if min_duration_ms is not None:
            statement = statement.where(AnsichActiveTaskReadModelRow.duration_ms >= min_duration_ms)
        if max_duration_ms is not None:
            statement = statement.where(AnsichActiveTaskReadModelRow.duration_ms <= max_duration_ms)
        if observability_status is not None:
            statement = statement.where(AnsichActiveTaskReadModelRow.observability_status == observability_status)
        if cursor is not None:
            cursor_time, cursor_task_id = cursor
            statement = statement.where(
                or_(
                    AnsichActiveTaskReadModelRow.last_evidence_at < cursor_time,
                    and_(
                        AnsichActiveTaskReadModelRow.last_evidence_at == cursor_time,
                        AnsichActiveTaskReadModelRow.task_id > cursor_task_id,
                    ),
                )
            )
        statement = statement.order_by(
            AnsichActiveTaskReadModelRow.last_evidence_at.desc(),
            AnsichActiveTaskReadModelRow.task_id,
        ).limit(limit)
        async with self._session_factory() as session:
            rows = list((await session.execute(statement)).all())
        return [self._active_task_view(row, active_child_count=int(child_count or 0)) for row, child_count in rows]

    @staticmethod
    def _active_task_view(
        row: AnsichActiveTaskReadModelRow,
        *,
        active_child_count: int = 0,
    ) -> ActiveTaskView:
        def strict_model(model_type, value):
            return model_type.model_validate_json(json.dumps(value))

        return ActiveTaskView(
            task_id=row.task_id,
            run_id=row.run_id,
            source_kind=row.source_kind,
            owner_id=row.owner_id,
            thread_id=row.thread_id,
            agent_id=row.agent_id,
            control=ControlBelief.model_validate(row.control_json),
            current_step=(None if row.current_step_json is None else strict_model(ActiveStepView, row.current_step_json)),
            current_tool=(None if row.current_tool_json is None else strict_model(ActiveToolView, row.current_tool_json)),
            dwell=strict_model(DwellBelief, row.dwell_json),
            heartbeat=strict_model(HeartbeatBelief, row.heartbeat_json),
            usage=strict_model(TaskUsageView, row.usage_json),
            active_child_count=active_child_count,
            budgets=strict_model(TaskBudgetsView, row.budgets_json),
            budget_health=tuple(strict_model(BudgetHealthBelief, item) for item in row.budget_health_json),
            duration_ms=row.duration_ms,
            observability_status=row.observability_status,
            projection_watermark=row.projection_watermark,
            projection_lag_ms=row.projection_lag_ms,
            lost_ranges=tuple(LostRange.model_validate(item) for item in row.lost_ranges_json),
            last_evidence_at=_as_utc(row.last_evidence_at),
            updated_at=_as_utc(row.updated_at),
        )

    async def list_timeline(
        self,
        task_id: str,
        *,
        limit: int,
        cursor: tuple[datetime, int] | None = None,
    ) -> list[tuple[int, ObservationEnvelope]]:
        statement = select(AnsichObservationRow).where(AnsichObservationRow.task_id == task_id)
        if cursor is not None:
            occurred_at, ingest_seq = cursor
            statement = statement.where(
                or_(
                    AnsichObservationRow.occurred_at > occurred_at,
                    and_(
                        AnsichObservationRow.occurred_at == occurred_at,
                        AnsichObservationRow.ingest_seq > ingest_seq,
                    ),
                )
            )
        async with self._session_factory() as session:
            rows = list(
                (
                    await session.execute(
                        statement.order_by(
                            AnsichObservationRow.occurred_at,
                            AnsichObservationRow.ingest_seq,
                        ).limit(limit)
                    )
                ).scalars()
            )
        return [(row.ingest_seq, self._observation_from_row(row)) for row in rows]

    async def get_max_step_seq(self, task_id: str) -> int:
        async with self._session_factory() as session:
            value = await session.scalar(select(func.max(AnsichStepRow.step_seq)).where(AnsichStepRow.task_id == task_id))
        return int(value or 0)

    async def list_content_occurrences(self, task_id: str) -> list[ContentOccurrenceView]:
        async with self._session_factory() as session:
            rows = list(
                (
                    await session.execute(
                        select(AnsichContentOccurrenceRow)
                        .where(AnsichContentOccurrenceRow.task_id == task_id)
                        .order_by(
                            AnsichContentOccurrenceRow.source_identity,
                            AnsichContentOccurrenceRow.content_hash,
                            AnsichContentOccurrenceRow.kind,
                        )
                    )
                ).scalars()
            )
        return [
            ContentOccurrenceView(
                task_id=row.task_id,
                source_identity=row.source_identity,
                content_hash=row.content_hash,
                kind=row.kind,
                block_id=row.block_id,
                producer_obs_id=row.producer_obs_id,
            )
            for row in rows
        ]

    async def get_latest_context_state(self, task_id: str) -> ContextStateView | None:
        async with self._session_factory() as session:
            state = await session.scalar(
                select(AnsichContextStateRow)
                .join(
                    AnsichObservationRow,
                    AnsichObservationRow.obs_id == AnsichContextStateRow.created_obs_id,
                )
                .where(
                    AnsichContextStateRow.task_id == task_id,
                    AnsichContextStateRow.created_obs_id.is_not(None),
                )
                .order_by(AnsichObservationRow.ingest_seq.desc())
                .limit(1)
            )
            return None if state is None else await self._context_state_view(session, state)

    async def list_steps(self, task_id: str) -> list[StepView]:
        async with self._session_factory() as session:
            rows = list((await session.execute(select(AnsichStepRow).where(AnsichStepRow.task_id == task_id).order_by(AnsichStepRow.step_seq))).scalars())
            return [await self._step_view(session, row) for row in rows]

    async def list_system_operations(self, task_id: str) -> list[LlmAttemptView]:
        async with self._session_factory() as session:
            rows = list(
                (
                    await session.execute(
                        select(AnsichLlmAttemptRow)
                        .join(
                            AnsichObservationRow,
                            AnsichObservationRow.obs_id == AnsichLlmAttemptRow.request_obs_id,
                        )
                        .where(
                            AnsichLlmAttemptRow.task_id == task_id,
                            AnsichLlmAttemptRow.step_id.is_(None),
                        )
                        .order_by(AnsichObservationRow.ingest_seq, AnsichLlmAttemptRow.attempt_no)
                    )
                ).scalars()
            )
            return [self._attempt_view(row) for row in rows]

    async def get_step(self, step_id: str) -> StepView | None:
        async with self._session_factory() as session:
            row = await session.get(AnsichStepRow, step_id)
            return None if row is None else await self._step_view(session, row)

    async def get_tool_call(self, tool_call_id: str) -> ToolCallView | None:
        async with self._session_factory() as session:
            row = await session.get(AnsichToolCallRow, tool_call_id)
            return None if row is None else await self._tool_call_view(session, row)

    async def get_task_scopes(self, task_id: str) -> TaskScopesView:
        async with self._session_factory() as session:
            rows = list(
                (
                    await session.execute(
                        select(AnsichScopeRow, AnsichRelationRow)
                        .join(
                            AnsichRelationRow,
                            AnsichRelationRow.object_id == AnsichScopeRow.entity_id,
                        )
                        .where(
                            AnsichRelationRow.subject_id == task_id,
                            AnsichRelationRow.predicate == "within_scope",
                        )
                        .order_by(
                            AnsichScopeRow.scope_kind,
                            AnsichScopeRow.display_label,
                            AnsichScopeRow.entity_id,
                        )
                    )
                ).all()
            )
        return TaskScopesView(
            task_id=task_id,
            scopes=tuple(
                TaskScopeView(
                    scope_id=scope.entity_id,
                    scope_kind=scope.scope_kind,
                    external_ref_hash=scope.external_ref_hash,
                    display_label=scope.display_label,
                    parent_scope_id=scope.parent_scope_id,
                    created_obs_id=scope.created_obs_id,
                    relation_role=relation.relation_role,
                    relation_obs_id=relation.asserted_obs_id,
                    inherited_from_task_id=relation.inherited_from_task_id,
                )
                for scope, relation in rows
                if relation.relation_role is not None
            ),
        )

    async def get_tool_authorization(
        self,
        tool_call_id: str,
    ) -> ToolAuthorizationView | None:
        async with self._session_factory() as session:
            if await session.get(AnsichToolCallRow, tool_call_id) is None:
                return None
            pairs = list(
                (
                    await session.execute(
                        select(
                            AnsichAuthorizationSnapshotRow,
                            AnsichToolCallAuthorizationRow,
                        )
                        .join(
                            AnsichToolCallAuthorizationRow,
                            AnsichToolCallAuthorizationRow.snapshot_id == AnsichAuthorizationSnapshotRow.snapshot_id,
                        )
                        .where(AnsichToolCallAuthorizationRow.tool_call_id == tool_call_id)
                        .order_by(
                            AnsichAuthorizationSnapshotRow.evaluated_at,
                            AnsichAuthorizationSnapshotRow.snapshot_id,
                        )
                    )
                ).all()
            )
            snapshots: list[AuthorizationSnapshot] = []
            for row, binding in pairs:
                scope_rows = list(
                    (
                        await session.execute(
                            select(AnsichAuthorizationScopeRow)
                            .where(AnsichAuthorizationScopeRow.snapshot_id == row.snapshot_id)
                            .order_by(
                                AnsichAuthorizationScopeRow.scope_role,
                                AnsichAuthorizationScopeRow.ordinal,
                            )
                        )
                    ).scalars()
                )
                permission_rows = list((await session.execute(select(AnsichAuthorizationPermissionRow).where(AnsichAuthorizationPermissionRow.snapshot_id == row.snapshot_id).order_by(AnsichAuthorizationPermissionRow.ordinal))).scalars())
                evidence_obs_ids = tuple(dict.fromkeys((row.evaluated_obs_id, binding.relation_obs_id)))
                snapshots.append(
                    AuthorizationSnapshot(
                        snapshot_id=row.snapshot_id,
                        tool_call_id=row.tool_call_id,
                        principal_scope_ids=tuple(item.scope_id for item in scope_rows if item.scope_role == "principal"),
                        policy_id=row.policy_id,
                        policy_version=row.policy_version,
                        policy_hash=row.policy_hash,
                        decision=row.decision,
                        details_available=row.details_available,
                        effective_permissions=tuple(
                            AuthorizationPermission(
                                resource=item.resource,
                                action=item.action,
                                scope_id=item.scope_id,
                                effect=item.effect,
                            )
                            for item in permission_rows
                        ),
                        resource_scope_ids=tuple(item.scope_id for item in scope_rows if item.scope_role == "resource"),
                        reason_codes=tuple(row.reason_codes_json),
                        evaluated_at=_as_utc(row.evaluated_at),
                        evidence_obs_ids=evidence_obs_ids,
                    )
                )
        return ToolAuthorizationView(
            tool_call_id=tool_call_id,
            snapshots=tuple(snapshots),
            current_decision=(snapshots[-1].decision if snapshots else "unknown"),
        )

    async def get_tool_effects(
        self,
        tool_call_id: str,
    ) -> ToolEffectsView | None:
        async with self._session_factory() as session:
            if await session.get(AnsichToolCallRow, tool_call_id) is None:
                return None
            rows = list(
                (
                    await session.execute(
                        select(AnsichToolEffectRow)
                        .where(AnsichToolEffectRow.tool_call_id == tool_call_id)
                        .order_by(
                            AnsichToolEffectRow.source_obs_id,
                            AnsichToolEffectRow.effect_id,
                        )
                    )
                ).scalars()
            )
        effects = tuple(
            ToolEffect(
                effect_id=row.effect_id,
                tool_call_id=row.tool_call_id,
                effect_class=row.effect_class,
                phase=row.phase,
                scope_id=row.scope_id,
                target_hash=row.target_hash,
                target_preview=row.target_preview,
                fidelity_class=row.fidelity_class,
                source_obs_id=row.source_obs_id,
                result_metadata=dict(row.result_metadata_json),
            )
            for row in rows
        )
        if any(item.result_metadata.get("coverage") == "complete" for item in effects):
            coverage = "complete"
        elif effects:
            coverage = "partial"
        else:
            coverage = "unknown"
        return ToolEffectsView(
            tool_call_id=tool_call_id,
            effects=effects,
            coverage=coverage,
        )

    async def get_step_context(self, step_id: str) -> ContextSnapshotView | None:
        async with self._session_factory() as session:
            step = await session.get(AnsichStepRow, step_id)
            if step is None or step.effective_context_snapshot_id is None:
                return None
            snapshot_id = step.effective_context_snapshot_id
        return await self.get_context_snapshot(snapshot_id)

    async def get_context_snapshot(
        self,
        snapshot_id: str,
    ) -> ContextSnapshotView | None:
        async with self._session_factory() as session:
            snapshot = await session.get(AnsichContextSnapshotRow, snapshot_id)
            if snapshot is None:
                return None
            status = snapshot.status
            if snapshot.state_id is not None:
                state = await session.get(AnsichContextStateRow, snapshot.state_id)
                state_view = None if state is None else await self._context_state_view(session, state)
                if state_view is None:
                    items: list[ContextSnapshotItemView] = []
                    status = "incomplete"
                else:
                    items = await self._context_snapshot_items_for_state(session, state_view)
                    status = "complete" if state_view.status == "complete" else "incomplete"
            else:
                item_rows = list(
                    (
                        await session.execute(
                            select(AnsichContextSnapshotItemRow, AnsichContentBlockRow)
                            .join(
                                AnsichContentBlockRow,
                                AnsichContentBlockRow.entity_id == AnsichContextSnapshotItemRow.content_block_id,
                            )
                            .where(AnsichContextSnapshotItemRow.snapshot_id == snapshot.entity_id)
                            .order_by(AnsichContextSnapshotItemRow.ordinal)
                        )
                    ).all()
                )
                missing_rows = list(
                    (await session.execute(select(AnsichContextSnapshotMissingItemRow).where(AnsichContextSnapshotMissingItemRow.snapshot_id == snapshot.entity_id).order_by(AnsichContextSnapshotMissingItemRow.ordinal))).scalars()
                )
                items = [
                    ContextSnapshotItemView(
                        ordinal=item.ordinal,
                        channel=item.channel,
                        role=item.role,
                        name=item.name,
                        message_id=item.message_id,
                        source_identity=item.source_identity,
                        block_id=block.entity_id,
                        kind=block.kind,
                        content_hash=block.content_hash,
                        visible_bytes=item.visible_bytes,
                        estimated_tokens=item.estimated_tokens,
                        metadata=item.metadata_json,
                        sensitivity_flags=tuple(block.sensitivity_flags_json),
                        payload_available=True,
                    )
                    for item, block in item_rows
                ]
                items.extend(
                    ContextSnapshotItemView(
                        ordinal=item.ordinal,
                        channel=cast(Literal["message", "tool_schema"], item.channel),
                        role=cast(Literal["system", "user", "assistant", "tool"] | None, item.role),
                        name=item.name,
                        message_id=item.message_id,
                        source_identity=item.source_identity,
                        block_id=item.expected_content_block_id,
                        kind=None,
                        content_hash=None,
                        visible_bytes=item.visible_bytes,
                        estimated_tokens=item.estimated_tokens,
                        metadata=item.metadata_json,
                        payload_available=False,
                        resolution_status="missing",
                    )
                    for item in missing_rows
                )
                items.sort(key=lambda item: item.ordinal)
            return ContextSnapshotView(
                snapshot_id=snapshot.entity_id,
                task_id=snapshot.task_id,
                step_id=snapshot.step_id,
                operation_id=snapshot.operation_id,
                attempt_no=snapshot.attempt_no,
                request_obs_id=snapshot.request_obs_id,
                message_count=snapshot.message_count,
                tool_schema_count=snapshot.tool_schema_count,
                visible_bytes=snapshot.visible_bytes,
                estimated_tokens=snapshot.estimated_tokens,
                estimator_name=snapshot.estimator_name,
                estimator_version=snapshot.estimator_version,
                adapter_name=snapshot.adapter_name,
                adapter_version=snapshot.adapter_version,
                configured_model=snapshot.configured_model,
                response_format=snapshot.response_format_json,
                generation_settings=snapshot.generation_settings_json,
                redactions=tuple(snapshot.redactions_json),
                warnings=tuple(snapshot.warnings_json),
                items=tuple(items),
                status=cast(Literal["complete", "incomplete"], status),
            )

    async def _context_state_view(
        self,
        session: AsyncSession,
        state: AnsichContextStateRow,
    ) -> ContextStateView:
        try:
            items = await self._materialize_context_state(session, state.state_id, frozenset())
        except ValueError:
            items = ()
        return ContextStateView(
            state_id=state.state_id,
            task_id=state.task_id,
            state_hash=state.state_hash or "",
            parent_state_id=state.parent_state_id,
            chain_depth=state.chain_depth,
            is_checkpoint=state.is_checkpoint,
            status=cast(Literal["complete", "incomplete", "missing"], state.status),
            items=items,
        )

    async def _materialize_context_state(
        self,
        session: AsyncSession,
        state_id: str,
        visited: frozenset[str],
    ) -> tuple[ContextStateItem, ...]:
        if state_id in visited:
            raise ValueError("ContextState parent cycle detected")
        state = await session.get(AnsichContextStateRow, state_id)
        if state is None or state.status == "missing":
            raise ValueError(f"ContextState is missing: {state_id}")
        if state.is_checkpoint:
            rows = list((await session.execute(select(AnsichContextStateCheckpointItemRow).where(AnsichContextStateCheckpointItemRow.state_id == state_id).order_by(AnsichContextStateCheckpointItemRow.ordinal))).scalars())
            return tuple(
                ContextStateItem(
                    ordinal=row.ordinal,
                    channel=cast(Literal["message", "tool_schema"], row.channel),
                    role=cast(Literal["system", "user", "assistant", "tool"] | None, row.role),
                    message_id=row.message_id,
                    source_identity=row.source_identity,
                    name=row.name,
                    block_id=row.block_id,
                    visible_bytes=row.visible_bytes,
                    estimated_tokens=row.estimated_tokens,
                    metadata=row.metadata_json,
                )
                for row in rows
            )
        if state.parent_state_id is None:
            raise ValueError(f"delta ContextState has no parent: {state_id}")
        parent = await self._materialize_context_state(session, state.parent_state_id, visited | {state_id})
        rows = list((await session.execute(select(AnsichContextStateDeltaRow).where(AnsichContextStateDeltaRow.state_id == state_id).order_by(AnsichContextStateDeltaRow.operation_ordinal))).scalars())
        operations = tuple(self._context_state_delta_from_row(row) for row in rows)
        return materialize_context_state(parent, operations, item_count=state.item_count)

    @staticmethod
    def _context_state_delta_from_row(row: AnsichContextStateDeltaRow) -> ContextStateDelta:
        item = None
        if row.block_id is not None:
            item = ContextStateItem(
                ordinal=int(row.target_ordinal or 0),
                channel=cast(Literal["message", "tool_schema"], row.channel),
                role=cast(Literal["system", "user", "assistant", "tool"] | None, row.role),
                message_id=row.message_id,
                source_identity=row.source_identity,
                name=row.name,
                block_id=row.block_id,
                visible_bytes=int(row.visible_bytes or 0),
                estimated_tokens=int(row.estimated_tokens or 0),
                metadata=dict(row.metadata_json or {}),
            )
        return ContextStateDelta(
            op=cast(Literal["append", "remove", "replace", "reorder"], row.operation),
            source_ordinal=row.source_ordinal,
            target_ordinal=row.target_ordinal,
            item=item,
        )

    async def _context_snapshot_items_for_state(
        self,
        session: AsyncSession,
        state: ContextStateView,
    ) -> list[ContextSnapshotItemView]:
        block_ids = [item.block_id for item in state.items]
        blocks: dict[str, AnsichContentBlockRow] = {}
        if block_ids:
            rows = list((await session.execute(select(AnsichContentBlockRow).where(AnsichContentBlockRow.entity_id.in_(block_ids)))).scalars())
            blocks = {row.entity_id: row for row in rows}
        return [
            ContextSnapshotItemView(
                ordinal=item.ordinal,
                channel=item.channel,
                role=item.role,
                name=item.name,
                message_id=item.message_id,
                source_identity=item.source_identity,
                block_id=item.block_id,
                kind=blocks[item.block_id].kind if item.block_id in blocks else None,
                content_hash=blocks[item.block_id].content_hash if item.block_id in blocks else None,
                visible_bytes=item.visible_bytes,
                estimated_tokens=item.estimated_tokens,
                metadata=item.metadata,
                sensitivity_flags=tuple(blocks[item.block_id].sensitivity_flags_json) if item.block_id in blocks else (),
                payload_available=item.block_id in blocks,
                resolution_status="available" if item.block_id in blocks else "missing",
            )
            for item in state.items
        ]

    async def get_content_block_payload(self, block_id: str) -> ContentBlockPayloadView | None:
        async with self._session_factory() as session:
            block = await session.get(AnsichContentBlockRow, block_id)
            if block is None:
                return None
            if block.blob_key is not None:
                blob = await session.get(AnsichContentBlobRow, block.blob_key)
                if blob is None or blob.payload_status != "available":
                    return None
                body_bytes = await self._content_blob_bytes(session, blob)
                body = body_bytes.decode("utf-8") if blob.content_type.startswith("text/plain") else json.loads(body_bytes.decode("utf-8"))
                return ContentBlockPayloadView(block_id=block_id, content_type=blob.content_type, body=body)
            observation = await session.scalar(select(AnsichObservationRow).where(AnsichObservationRow.obs_id == block.payload_obs_id))
            if observation is None or observation.payload_json is None or "body" not in observation.payload_json:
                if observation is None or observation.payload_ref_id is None:
                    return None
                payload = await session.get(AnsichPayloadRow, observation.payload_ref_id)
                if payload is None:
                    return None
                decoded = json.loads(payload.body.decode(payload.encoding))
                if not isinstance(decoded, dict) or "body" not in decoded:
                    return None
                return ContentBlockPayloadView(block_id=block_id, body=decoded["body"])
            return ContentBlockPayloadView(block_id=block_id, body=observation.payload_json["body"])

    async def get_context_compression(
        self,
        compression_id: str,
    ) -> ContextCompressionView | None:
        async with self._session_factory() as session:
            compression = await session.get(
                AnsichContextCompressionRow,
                compression_id,
            )
            if compression is None:
                return None
            item_rows = list(
                (
                    await session.execute(
                        select(AnsichContextCompressionItemRow)
                        .where(AnsichContextCompressionItemRow.compression_id == compression_id)
                        .order_by(
                            case(
                                (AnsichContextCompressionItemRow.disposition == "source", 0),
                                (AnsichContextCompressionItemRow.disposition == "preserved", 1),
                                else_=2,
                            ),
                            AnsichContextCompressionItemRow.ordinal,
                        )
                    )
                ).scalars()
            )
            summary_block_id = compression.summary_block_id
            task_id = compression.task_id
            operation_id = compression.operation_id
            before_tokens = compression.before_tokens
            after_tokens = compression.after_tokens
            before_visible_bytes = compression.before_visible_bytes
            after_visible_bytes = compression.after_visible_bytes
            algorithm = compression.algorithm
            algorithm_version = compression.algorithm_version
            source_obs_id = compression.source_obs_id
            stored_status = compression.status

        block_ids = tuple(dict.fromkeys([summary_block_id, *[item.block_id for item in item_rows]]))
        blocks = {block.block_id: block for block in await self.get_content_blocks(block_ids)}
        summary_block = blocks.get(summary_block_id)
        if summary_block is None:
            return None
        items = tuple(
            ContextCompressionItemView(
                disposition=cast(CompressionDisposition, item.disposition),
                ordinal=item.ordinal,
                block=blocks[item.block_id],
            )
            for item in item_rows
            if item.block_id in blocks
        )
        status = "complete" if stored_status == "complete" and len(items) == len(item_rows) else "incomplete"
        return ContextCompressionView(
            compression_id=compression_id,
            task_id=task_id,
            summary_operation_id=operation_id,
            summary_block=summary_block,
            before_tokens=before_tokens,
            after_tokens=after_tokens,
            before_visible_bytes=before_visible_bytes,
            after_visible_bytes=after_visible_bytes,
            algorithm=algorithm,
            algorithm_version=algorithm_version,
            source_obs_id=source_obs_id,
            status=cast(Literal["complete", "incomplete"], status),
            items=items,
        )

    async def list_context_compressions(
        self,
        task_id: str,
        *,
        limit: int = 100,
        cursor: tuple[datetime, str] | None = None,
    ) -> list[ContextCompressionSummaryView]:
        statement = _list_context_compression_summaries_statement(
            task_id=task_id,
            limit=limit,
            cursor=cursor,
        )
        async with self._session_factory() as session:
            rows = list((await session.execute(statement)).all())
        return [
            ContextCompressionSummaryView(
                compression_id=compression.entity_id,
                task_id=compression.task_id,
                summary_operation_id=compression.operation_id,
                summary_block_id=compression.summary_block_id,
                before_tokens=compression.before_tokens,
                after_tokens=compression.after_tokens,
                before_visible_bytes=compression.before_visible_bytes,
                after_visible_bytes=compression.after_visible_bytes,
                algorithm=compression.algorithm,
                algorithm_version=compression.algorithm_version,
                source_obs_id=compression.source_obs_id,
                occurred_at=_as_utc(occurred_at),
                status=cast(
                    Literal["complete", "incomplete"],
                    compression.status,
                ),
            )
            for compression, occurred_at in rows
        ]

    async def get_content_blocks(
        self,
        block_ids: tuple[str, ...],
    ) -> list[ContentBlockView]:
        if not block_ids:
            return []
        async with self._session_factory() as session:
            rows = list(
                (
                    await session.execute(
                        select(
                            AnsichContentBlockRow,
                            AnsichBlockProducerRow,
                            AnsichObservationRow,
                            AnsichContentBlobRow,
                        )
                        .outerjoin(
                            AnsichBlockProducerRow,
                            AnsichBlockProducerRow.block_id == AnsichContentBlockRow.entity_id,
                        )
                        .join(
                            AnsichObservationRow,
                            AnsichObservationRow.obs_id == AnsichContentBlockRow.producer_obs_id,
                        )
                        .outerjoin(
                            AnsichContentBlobRow,
                            AnsichContentBlobRow.blob_key == AnsichContentBlockRow.blob_key,
                        )
                        .where(AnsichContentBlockRow.entity_id.in_(block_ids))
                    )
                ).all()
            )
        by_id = {
            block.entity_id: ContentBlockView(
                block_id=block.entity_id,
                kind=block.kind,
                content_hash=block.content_hash,
                byte_size=block.byte_size,
                token_estimate=block.token_estimate,
                sensitivity_flags=tuple(block.sensitivity_flags_json),
                payload_status=cast(
                    Literal["available", "missing"],
                    "available" if blob is None else blob.payload_status,
                ),
                producer=ContentProducerView(
                    producer_kind=(observation.producer_name if producer is None else producer.producer_kind),
                    producer_entity_id=(None if producer is None else producer.producer_entity_id),
                    producer_obs_id=(observation.obs_id if producer is None else producer.producer_obs_id),
                ),
            )
            for block, producer, observation, blob in rows
        }
        return [by_id[block_id] for block_id in block_ids if block_id in by_id]

    async def list_content_derivations(
        self,
        block_ids: tuple[str, ...],
        direction: LineageDirection,
    ) -> list[ContentDerivationView]:
        if not block_ids:
            return []
        endpoint = AnsichContentBlockDerivationRow.derived_block_id if direction == "backward" else AnsichContentBlockDerivationRow.source_block_id
        async with self._session_factory() as session:
            rows = list(
                (
                    await session.execute(
                        select(AnsichContentBlockDerivationRow)
                        .where(endpoint.in_(block_ids))
                        .order_by(
                            AnsichContentBlockDerivationRow.derived_block_id,
                            AnsichContentBlockDerivationRow.source_block_id,
                            AnsichContentBlockDerivationRow.transform_kind,
                        )
                    )
                ).scalars()
            )
        return [
            ContentDerivationView(
                derived_block_id=row.derived_block_id,
                source_block_id=row.source_block_id,
                transform_kind=cast(ToolTransformKind, row.transform_kind),
                transform_version=row.transform_version,
                established_obs_id=row.established_obs_id,
                source_role=cast(ContentDerivationSourceRole, row.source_role),
                ordinal=row.ordinal,
            )
            for row in rows
        ]

    async def list_snapshot_exposures(
        self,
        root_block_id: str,
        descendant_block_ids: tuple[str, ...],
    ) -> list[PossibleExposureItemView]:
        if not descendant_block_ids:
            return []
        async with self._session_factory() as session:
            root_block = await session.get(AnsichContentBlockRow, root_block_id)
            if root_block is None:
                return []
            root_observation = await session.scalar(select(AnsichObservationRow).where(AnsichObservationRow.obs_id == root_block.producer_obs_id))
            if root_observation is None:
                return []
            rows = list(
                (
                    await session.execute(
                        select(
                            AnsichContextSnapshotBlockMembershipRow,
                            AnsichContextSnapshotRow,
                            AnsichStepRow,
                            AnsichObservationRow,
                        )
                        .join(
                            AnsichContextSnapshotRow,
                            AnsichContextSnapshotRow.entity_id == AnsichContextSnapshotBlockMembershipRow.snapshot_id,
                        )
                        .join(
                            AnsichStepRow,
                            AnsichStepRow.entity_id == AnsichContextSnapshotRow.step_id,
                        )
                        .join(
                            AnsichObservationRow,
                            AnsichObservationRow.obs_id == AnsichContextSnapshotRow.request_obs_id,
                        )
                        .where(AnsichContextSnapshotBlockMembershipRow.content_block_id.in_(descendant_block_ids))
                        .order_by(
                            AnsichStepRow.step_seq,
                            AnsichContextSnapshotRow.entity_id,
                            AnsichContextSnapshotBlockMembershipRow.ordinal,
                            AnsichContextSnapshotBlockMembershipRow.content_block_id,
                        )
                    )
                ).all()
            )
        return [
            PossibleExposureItemView(
                task_id=snapshot.task_id,
                step_id=step.entity_id,
                step_seq=step.step_seq,
                snapshot_id=snapshot.entity_id,
                snapshot_ordinal=item.ordinal,
                descendant_block_id=item.content_block_id,
                ordering=("later" if request.occurred_at > root_observation.occurred_at else "unknown"),
            )
            for item, snapshot, step, request in rows
        ]

    @staticmethod
    async def _content_blob_bytes(session: AsyncSession, blob: AnsichContentBlobRow) -> bytes:
        if blob.inline_body is not None:
            return bytes(blob.inline_body)
        if blob.payload_ref_id is None:
            raise ValueError(f"Ansich ContentBlob has no payload: {blob.blob_key}")
        payload = await session.get(AnsichPayloadRow, blob.payload_ref_id)
        if payload is None:
            raise ValueError(f"Ansich ContentBlob payload disappeared: {blob.payload_ref_id}")
        return bytes(payload.body)

    @staticmethod
    async def _step_view(session: AsyncSession, step: AnsichStepRow) -> StepView:
        attempt_rows = list((await session.execute(select(AnsichLlmAttemptRow).where(AnsichLlmAttemptRow.step_id == step.entity_id).order_by(AnsichLlmAttemptRow.attempt_no))).scalars())
        attempts = tuple(
            SqlAnsichBackend._attempt_view(
                attempt,
                effective=attempt.attempt_no == step.effective_attempt_no and attempt.status == "success",
            )
            for attempt in attempt_rows
        )
        tool_rows = list((await session.execute(select(AnsichToolCallRow).where(AnsichToolCallRow.step_id == step.entity_id).order_by(AnsichToolCallRow.call_seq))).scalars())
        tool_calls = tuple([await SqlAnsichBackend._tool_call_view(session, row) for row in tool_rows])
        return StepView(
            step_id=step.entity_id,
            task_id=step.task_id,
            step_seq=step.step_seq,
            actor_kind=step.actor_kind,
            status=step.status,
            result=step.result,
            started_obs_id=step.started_obs_id,
            closed_obs_id=step.closed_obs_id,
            effective_attempt_no=step.effective_attempt_no,
            effective_context_snapshot_id=step.effective_context_snapshot_id,
            issued_tools=tuple(step.issued_tools_json),
            attempts=attempts,
            tool_calls=tool_calls,
        )

    @staticmethod
    async def _tool_call_view(
        session: AsyncSession,
        tool_call: AnsichToolCallRow,
    ) -> ToolCallView:
        step = await session.get(AnsichStepRow, tool_call.step_id)
        if step is None:
            raise ValueError(f"Ansich ToolCall step disappeared: {tool_call.step_id}")
        observation_ids = tuple(
            observation_id
            for observation_id in (
                tool_call.issued_obs_id,
                tool_call.started_obs_id,
                tool_call.raw_terminal_obs_id,
                tool_call.visible_result_obs_id,
            )
            if observation_id is not None
        )
        observations: dict[str, AnsichObservationRow] = {}
        if observation_ids:
            rows = list((await session.execute(select(AnsichObservationRow).where(AnsichObservationRow.obs_id.in_(observation_ids)))).scalars())
            observations = {row.obs_id: row for row in rows}

        result_rows = list(
            (
                await session.execute(
                    select(AnsichToolCallResultRow)
                    .where(AnsichToolCallResultRow.tool_call_id == tool_call.entity_id)
                    .order_by(
                        AnsichToolCallResultRow.result_role,
                        AnsichToolCallResultRow.source_obs_id,
                    )
                )
            ).scalars()
        )
        block_ids = tuple({row.content_block_id for row in result_rows})
        blocks: dict[str, AnsichContentBlockRow] = {}
        if block_ids:
            block_rows = list((await session.execute(select(AnsichContentBlockRow).where(AnsichContentBlockRow.entity_id.in_(block_ids)))).scalars())
            blocks = {row.entity_id: row for row in block_rows}
        results = tuple(
            ToolResultView(
                result_role=cast(Literal["raw", "visible"], result.result_role),
                content_block_id=result.content_block_id,
                source_obs_id=result.source_obs_id,
                content_hash=(blocks[result.content_block_id].content_hash if result.content_block_id in blocks else None),
                byte_size=(blocks[result.content_block_id].byte_size if result.content_block_id in blocks else None),
                payload_available=result.content_block_id in blocks,
                metadata=dict(result.metadata_json),
            )
            for result in result_rows
        )
        visible_block_ids = tuple(result.content_block_id for result in result_rows if result.result_role == "visible")
        derivation_rows: list[AnsichContentBlockDerivationRow] = []
        if visible_block_ids:
            derivation_rows = list(
                (
                    await session.execute(
                        select(AnsichContentBlockDerivationRow)
                        .where(AnsichContentBlockDerivationRow.derived_block_id.in_(visible_block_ids))
                        .order_by(
                            AnsichContentBlockDerivationRow.derived_block_id,
                            AnsichContentBlockDerivationRow.source_block_id,
                        )
                    )
                ).scalars()
            )

        issued = observations.get(tool_call.issued_obs_id or "")
        started = observations.get(tool_call.started_obs_id or "")
        terminal = observations.get(tool_call.raw_terminal_obs_id or "")
        visible = observations.get(tool_call.visible_result_obs_id or "")
        fallback = issued or started or terminal or visible
        asserted_at = _as_utc(fallback.recorded_at) if fallback is not None else datetime.now(UTC)

        def belief(
            value: str,
            evidence: AnsichObservationRow | None,
            *,
            resolver: str,
        ) -> ToolBelief:
            return ToolBelief(
                value=value,
                as_of=None if evidence is None else _as_utc(evidence.occurred_at),
                asserted_at=(asserted_at if evidence is None else _as_utc(evidence.recorded_at)),
                source=NamedVersion(
                    name="tool-accountability" if evidence is None else evidence.producer_name,
                    version="1" if evidence is None else evidence.producer_version,
                ),
                selected_by=NamedVersion(name=resolver, version="1"),
                evidence_obs_ids=() if evidence is None else (evidence.obs_id,),
            )

        authorization_evidence = terminal if tool_call.execution_status == "denied" else None
        return ToolCallView(
            tool_call_id=tool_call.entity_id,
            task_id=tool_call.task_id,
            step_id=tool_call.step_id,
            step_seq=step.step_seq,
            call_seq=tool_call.call_seq,
            provider_call_id=tool_call.provider_call_id,
            tool_name=tool_call.tool_name,
            args_hash=tool_call.args_hash,
            args_preview={} if tool_call.args_preview_json is None else tool_call.args_preview_json,
            tool_schema_block_id=tool_call.tool_schema_block_id,
            issued_obs_id=tool_call.issued_obs_id,
            started_obs_id=tool_call.started_obs_id,
            raw_terminal_obs_id=tool_call.raw_terminal_obs_id,
            visible_result_obs_id=tool_call.visible_result_obs_id,
            duration_ms=tool_call.duration_ms,
            authorization=belief(
                "denied" if authorization_evidence is not None else "unknown",
                authorization_evidence,
                resolver="tool-authorization-state",
            ),
            execution=belief(
                tool_call.execution_status,
                terminal or started or issued,
                resolver=("tool-terminal-precedence" if terminal is not None else "tool-execution-state"),
            ),
            visible_result=belief(
                tool_call.visible_result_status,
                visible,
                resolver="tool-visible-result-state",
            ),
            raw_results=tuple(result for result in results if result.result_role == "raw"),
            visible_results=tuple(result for result in results if result.result_role == "visible"),
            derivations=tuple(
                ContentDerivationView(
                    derived_block_id=row.derived_block_id,
                    source_block_id=row.source_block_id,
                    transform_kind=row.transform_kind,
                    transform_version=row.transform_version,
                    established_obs_id=row.established_obs_id,
                )
                for row in derivation_rows
            ),
        )

    @staticmethod
    def _attempt_view(attempt: AnsichLlmAttemptRow, *, effective: bool = False) -> LlmAttemptView:
        return LlmAttemptView(
            attempt_id=attempt.attempt_id,
            task_id=attempt.task_id,
            step_id=attempt.step_id,
            actor_kind=attempt.actor_kind,
            operation_id=attempt.operation_id,
            operation_kind=attempt.operation_kind,
            attempt_no=attempt.attempt_no,
            status=attempt.status,
            request_obs_id=attempt.request_obs_id,
            response_obs_id=attempt.response_obs_id,
            failure_obs_id=attempt.failure_obs_id,
            provider_model=attempt.provider_model,
            usage=dict(attempt.usage_json or {}),
            response_metadata=dict(attempt.response_metadata_json or {}),
            latency_ms=attempt.latency_ms,
            context_snapshot_id=attempt.context_snapshot_id,
            effective=effective,
        )

    @staticmethod
    def _observation_from_row(row: AnsichObservationRow) -> ObservationEnvelope:
        return ObservationEnvelope(
            obs_id=row.obs_id,
            schema_version=row.schema_version,
            kind=row.kind,
            occurred_at=_as_utc(row.occurred_at),
            recorded_at=_as_utc(row.recorded_at),
            task_id=row.task_id,
            step_id=row.step_id,
            subject_type=row.subject_type,
            subject_id=row.subject_id,
            fidelity_class=row.fidelity_class,
            producer=Producer(
                name=row.producer_name,
                version=row.producer_version,
                instance_id=row.producer_instance_id,
            ),
            producer_seq=row.producer_seq,
            source_event_id=row.source_event_id,
            correlation_id=row.correlation_id,
            causation_obs_id=row.causation_obs_id,
            payload=row.payload_json,
            payload_ref_id=row.payload_ref_id,
        )

    async def _project_structural(
        self,
        session: AsyncSession,
        observation: ObservationEnvelope,
    ) -> AnsichTaskRow | None:
        if observation.kind == "agent_release.resolved":
            await self._project_agent_release(session, observation)
            return None
        if observation.kind not in _CONTROL_BY_KIND or observation.payload is None:
            return None
        entity = await session.get(AnsichEntityRow, observation.task_id)
        task = await session.get(AnsichTaskRow, observation.task_id)
        if entity is None:
            session.add(
                AnsichEntityRow(
                    entity_id=observation.task_id,
                    entity_type="task",
                    discovered_obs_id=observation.obs_id,
                )
            )
            # No ORM relationship() links AnsichEntityRow to AnsichTaskRow, so
            # SQLAlchemy's flush does not guarantee this INSERT precedes the
            # FK-dependent one below; flush explicitly to enforce the order.
            await session.flush()
        if task is None:
            task = AnsichTaskRow(
                entity_id=observation.task_id,
                source_kind=str(observation.payload["source_kind"]),
                source_id=str(observation.payload["source_id"]),
                trigger_obs_id=observation.obs_id,
            )
            session.add(task)
        await session.flush()
        await self._project_scopes(session, observation)
        if observation.kind == "task.created" and str(observation.payload.get("source_kind")) == "deerflow_subagent":
            await self._project_task_spawn(session, observation)
        return task

    async def _project_task_spawn(
        self,
        session: AsyncSession,
        observation: ObservationEnvelope,
    ) -> None:
        """Establish a typed parent/child edge and its transitive closure."""

        if observation.payload is None:
            raise ValueError("child task.created requires an inline payload")
        payload = observation.payload
        required = (
            "parent_task_id",
            "spawning_step_id",
            "spawning_tool_call_id",
        )
        missing = [name for name in required if not isinstance(payload.get(name), str)]
        if missing:
            raise ValueError("child task.created is missing spawn identity: " + ", ".join(missing))
        parent_task_id = str(payload["parent_task_id"])
        step_id = str(payload["spawning_step_id"])
        tool_call_id = str(payload["spawning_tool_call_id"])
        child_task_id = observation.task_id
        if parent_task_id == child_task_id:
            raise ValueError("a Task cannot spawn itself")

        parent = await session.get(AnsichTaskRow, parent_task_id)
        step = await session.get(AnsichStepRow, step_id)
        tool_call = await session.get(AnsichToolCallRow, tool_call_id)
        if parent is None or step is None or tool_call is None:
            raise _ProjectionDependencyPending(f"child Task {child_task_id} is waiting for its parent Step/ToolCall")
        if step.task_id != parent_task_id:
            raise ValueError("spawning Step does not belong to the parent Task")
        if tool_call.task_id != parent_task_id or tool_call.step_id != step_id or tool_call.tool_name != "task":
            raise ValueError("spawning ToolCall is not a task ToolCall on the parent Step")

        existing = await session.get(AnsichTaskSpawnRow, child_task_id)
        if existing is not None:
            identity = (
                existing.parent_task_id,
                existing.spawning_step_id,
                existing.spawning_tool_call_id,
            )
            if identity != (parent_task_id, step_id, tool_call_id):
                raise ValueError("child Task already has a different parent")
            return

        if (
            await session.get(
                AnsichTaskAncestryRow,
                (child_task_id, parent_task_id),
            )
            is not None
        ):
            raise ValueError("Task spawn would create an ancestry cycle")

        session.add(
            AnsichTaskSpawnRow(
                parent_task_id=parent_task_id,
                spawning_step_id=step_id,
                spawning_tool_call_id=tool_call_id,
                child_task_id=child_task_id,
                established_obs_id=observation.obs_id,
                subagent_name=(str(payload["subagent_name"]) if isinstance(payload.get("subagent_name"), str) else None),
            )
        )
        ancestors = list((await session.execute(select(AnsichTaskAncestryRow).where(AnsichTaskAncestryRow.descendant_task_id == parent_task_id))).scalars())
        descendants = list((await session.execute(select(AnsichTaskAncestryRow).where(AnsichTaskAncestryRow.ancestor_task_id == child_task_id))).scalars())
        if any(descendant.descendant_task_id == parent_task_id for descendant in descendants):
            raise ValueError("Task spawn would create an ancestry cycle")
        ancestor_depths = [(parent_task_id, 0), *[(row.ancestor_task_id, row.depth) for row in ancestors]]
        descendant_depths = [(child_task_id, 0), *[(row.descendant_task_id, row.depth) for row in descendants]]
        for ancestor_id, ancestor_depth in ancestor_depths:
            for descendant_id, descendant_depth in descendant_depths:
                session.add(
                    AnsichTaskAncestryRow(
                        ancestor_task_id=ancestor_id,
                        descendant_task_id=descendant_id,
                        depth=ancestor_depth + 1 + descendant_depth,
                        established_obs_id=observation.obs_id,
                    )
                )
        await session.flush()
        await self._backfill_spawn_usage(
            session,
            ancestor_task_ids=tuple(item[0] for item in ancestor_depths),
            descendant_task_ids=tuple(item[0] for item in descendant_depths),
            updated_at=observation.recorded_at,
        )

    async def _backfill_spawn_usage(
        self,
        session: AsyncSession,
        *,
        ancestor_task_ids: tuple[str, ...],
        descendant_task_ids: tuple[str, ...],
        updated_at: datetime,
    ) -> None:
        """Fan out already-durable descendant usage after a late spawn edge.

        This read is deliberately NOT locked, unlike the one in
        ``_upsert_high_water_contribution``. It reads the descendants' own self
        rows and writes only ancestor rows — disjoint row sets, since ancestry
        is acyclic and self-free — so it is not a read-modify-write of the rows
        it reads and cannot lose an update. Every write it makes still goes
        through ``_store_usage_contribution``, so a high-water write takes the
        locked max path. A concurrent tick committing between this read and its
        write can therefore only make the copied mark one tick stale, which the
        next tick's own fan-out raises; ``max`` is monotone, so a stale copy can
        never lower an ancestor's mark or over-report. A lock here would also
        not help the sum-type rows: row locks do not block inserts of new rows,
        which is the only way that set changes.
        """

        local_rows = list(
            (
                await session.execute(
                    select(AnsichUsageContributionRow, AnsichObservationRow.kind)
                    .join(
                        AnsichObservationRow,
                        AnsichObservationRow.obs_id == AnsichUsageContributionRow.source_obs_id,
                    )
                    .where(
                        AnsichUsageContributionRow.aggregate_task_id == AnsichUsageContributionRow.source_task_id,
                        AnsichUsageContributionRow.source_task_id.in_(descendant_task_ids),
                    )
                )
            ).all()
        )
        changed: set[tuple[str, str]] = set()
        for ancestor_task_id in ancestor_task_ids:
            for row, source_kind in local_rows:
                inserted = await self._store_usage_contribution(
                    session,
                    aggregate_task_id=ancestor_task_id,
                    source_task_id=row.source_task_id,
                    dimension=row.dimension,
                    source_obs_id=row.source_obs_id,
                    delta=row.delta,
                    as_of=_as_utc(row.as_of),
                    # The descendant's own high-water mark stays a high-water
                    # mark on the new ancestor, so a late spawn edge cannot
                    # reintroduce a second wall_time row for that source.
                    high_water=(source_kind in HIGH_WATER_USAGE_KINDS and row.dimension in MAX_TYPE_USAGE_DIMENSIONS),
                )
                if inserted:
                    changed.add((ancestor_task_id, row.dimension))
        for aggregate_task_id, dimension in changed:
            await self._refresh_usage_summary(
                session,
                task_id=aggregate_task_id,
                dimension=dimension,
                aggregation_scope="inclusive",
                updated_at=updated_at,
            )

    async def _project_agent_release(
        self,
        session: AsyncSession,
        observation: ObservationEnvelope,
    ) -> None:
        if observation.payload is None:
            raise ValueError("agent_release.resolved requires an inline decoded payload")
        task = await session.get(AnsichTaskRow, observation.task_id)
        if task is None:
            raise _ProjectionDependencyPending(f"Ansich task is not projected: {observation.task_id}")
        if observation.payload.get("relation_role") != "executed_by":
            raise ValueError("AgentRelease relation_role must be executed_by")
        release = AgentRelease.model_validate(observation.payload.get("release"))
        validate_agent_release(release)
        manifest = release.manifest
        fingerprint = release.fingerprint
        expected_release_id = release_entity_id(
            manifest.namespace,
            manifest.agent_name,
            fingerprint.release_hash,
        )
        if observation.subject_id != expected_release_id:
            raise ValueError("AgentRelease observation subject does not match release identity")

        row = await session.get(AnsichAgentReleaseRow, expected_release_id)
        if row is None:
            entity = await session.get(AnsichEntityRow, expected_release_id)
            if entity is None:
                session.add(
                    AnsichEntityRow(
                        entity_id=expected_release_id,
                        entity_type="agent_release",
                        discovered_obs_id=observation.obs_id,
                    )
                )
                await session.flush()
            manifest_bytes = canonical_json_bytes(manifest.model_dump(mode="python"))
            manifest_payload_id = release_entity_id(
                manifest.namespace,
                manifest.agent_name,
                f"{fingerprint.release_hash}:manifest:{manifest.schema_version}",
            )
            manifest_payload = await session.get(AnsichPayloadRow, manifest_payload_id)
            if manifest_payload is None:
                session.add(
                    AnsichPayloadRow(
                        payload_id=manifest_payload_id,
                        content_type="application/vnd.ansich.agent-release+json",
                        encoding="utf-8",
                        compression="none",
                        byte_size=len(manifest_bytes),
                        sha256=hashlib.sha256(manifest_bytes).hexdigest(),
                        body=manifest_bytes,
                    )
                )
                # No ORM relationship() links AnsichPayloadRow to
                # AnsichAgentReleaseRow, so SQLAlchemy's flush does not
                # guarantee this INSERT precedes the FK-dependent one below;
                # flush explicitly to enforce the order.
                await session.flush()
            elif manifest_payload.body != manifest_bytes:
                raise ValueError("AgentRelease manifest payload is immutable")
            row = AnsichAgentReleaseRow(
                entity_id=expected_release_id,
                namespace=manifest.namespace,
                agent_name=manifest.agent_name,
                release_hash=fingerprint.release_hash,
                schema_version=manifest.schema_version,
                model_hash=fingerprint.model_hash,
                prompt_hash=fingerprint.prompt_hash,
                tool_catalog_hash=fingerprint.tool_catalog_hash,
                policy_hash=fingerprint.policy_hash,
                runtime_build_id=fingerprint.runtime_build_id,
                manifest_payload_id=manifest_payload_id,
                discovered_obs_id=observation.obs_id,
                created_at=observation.occurred_at,
            )
            session.add(row)
            await session.flush()
            summaries = {
                "model": manifest.model.model_dump(mode="json"),
                "prompt": manifest.prompt.model_dump(
                    mode="json",
                    exclude={"rendered_base_prompt"},
                ),
                "tools": {
                    "items": [
                        tool.model_dump(
                            mode="json",
                            exclude={"argument_schema"},
                        )
                        for tool in manifest.tools
                    ]
                },
                "policy": manifest.policy.model_dump(mode="json"),
                "runtime_build": manifest.runtime_build.model_dump(mode="json"),
            }
            component_hashes = {
                "model": fingerprint.model_hash,
                "prompt": fingerprint.prompt_hash,
                "tools": fingerprint.tool_catalog_hash,
                "policy": fingerprint.policy_hash,
                "runtime_build": fingerprint.runtime_build_id,
            }
            for component_kind, component_hash in component_hashes.items():
                session.add(
                    AnsichAgentReleaseComponentRow(
                        release_id=expected_release_id,
                        component_kind=component_kind,
                        component_hash=component_hash,
                        summary_json=summaries[component_kind],
                    )
                )
        else:
            stored_fingerprint = (
                row.model_hash,
                row.prompt_hash,
                row.tool_catalog_hash,
                row.policy_hash,
                row.runtime_build_id,
                row.release_hash,
            )
            incoming_fingerprint = (
                fingerprint.model_hash,
                fingerprint.prompt_hash,
                fingerprint.tool_catalog_hash,
                fingerprint.policy_hash,
                fingerprint.runtime_build_id,
                fingerprint.release_hash,
            )
            if stored_fingerprint != incoming_fingerprint:
                raise ValueError("AgentRelease identity is immutable")

        binding = await session.get(AnsichTaskAgentReleaseRow, observation.task_id)
        if binding is None:
            session.add(
                AnsichTaskAgentReleaseRow(
                    task_id=observation.task_id,
                    release_id=expected_release_id,
                    relation_role="executed_by",
                    established_obs_id=observation.obs_id,
                )
            )
        elif binding.release_id != expected_release_id:
            raise ValueError("Task starting AgentRelease is immutable")

        relation = await session.scalar(
            select(AnsichRelationRow).where(
                AnsichRelationRow.subject_id == observation.task_id,
                AnsichRelationRow.predicate == "executed_by",
                AnsichRelationRow.object_id == expected_release_id,
            )
        )
        if relation is None:
            relation = AnsichRelationRow(
                relation_id=new_id(),
                subject_id=observation.task_id,
                predicate="executed_by",
                object_id=expected_release_id,
                asserted_obs_id=observation.obs_id,
            )
            session.add(relation)
            await session.flush()
        if (
            await session.get(
                AnsichRelationEvidenceRow,
                (relation.relation_id, observation.obs_id),
            )
            is None
        ):
            session.add(
                AnsichRelationEvidenceRow(
                    relation_id=relation.relation_id,
                    obs_id=observation.obs_id,
                    ordinal=0,
                )
            )

    async def _project_control(
        self,
        session: AsyncSession,
        observation: ObservationEnvelope,
        *,
        ingest_seq: int,
    ) -> None:
        task = await self._project_structural(session, observation)
        if task is None:
            return

        current = await session.get(AnsichCurrentBeliefRow, (observation.task_id, "control"))
        current_assertion = None
        if current is not None:
            current_assertion = await session.get(AnsichBeliefAssertionRow, current.assertion_id)

        assertion = AnsichBeliefAssertionRow(
            assertion_id=new_id(),
            subject_id=observation.task_id,
            field_name="control",
            value_json={"value": _CONTROL_BY_KIND[observation.kind]},
            as_of=observation.occurred_at,
            asserted_at=observation.recorded_at,
            source_name="task-control",
            source_version="1",
            assessor_name="task-control",
            assessor_version="1",
            config_hash=canonical_config_hash({"control_projector": "1"}),
            authority_class="deterministic",
            fidelity_class="hard",
            confidence=None,
        )
        session.add(assertion)
        session.add(
            AnsichBeliefEvidenceRow(
                assertion_id=assertion.assertion_id,
                obs_id=observation.obs_id,
                evidence_role="supporting",
                ordinal=0,
            )
        )
        await session.flush()

        previous_value = "unknown" if current_assertion is None else str(current_assertion.value_json["value"])
        next_value = _CONTROL_BY_KIND[observation.kind]
        if not should_select_control_candidate(
            current_value=None if current_assertion is None else cast(ControlValue, previous_value),
            current_as_of=None if current_assertion is None else _as_utc(current_assertion.as_of),
            candidate_value=cast(ControlValue, next_value),
            candidate_as_of=observation.occurred_at,
        ):
            return

        session.add(
            AnsichTransitionRow(
                transition_id=new_id(),
                subject_id=observation.task_id,
                field_name="control",
                from_value=previous_value,
                to_value=next_value,
                occurred_at=observation.occurred_at,
                evidence_obs_id=observation.obs_id,
            )
        )
        if current is None:
            current = AnsichCurrentBeliefRow(
                subject_id=observation.task_id,
                field_name="control",
                assertion_id=assertion.assertion_id,
                resolver_name="control-state",
                resolver_version="1",
            )
            session.add(current)
        else:
            current.assertion_id = assertion.assertion_id

        summary = await session.get(AnsichTaskSummaryRow, observation.task_id)
        if summary is None:
            session.add(
                AnsichTaskSummaryRow(
                    task_id=observation.task_id,
                    source_kind=task.source_kind,
                    source_id=task.source_id,
                    control_value=next_value,
                    control_as_of=observation.occurred_at,
                    last_evidence_at=observation.occurred_at,
                    assertion_id=assertion.assertion_id,
                    projection_watermark=ingest_seq,
                    observability_status="healthy",
                )
            )
        else:
            summary.control_value = next_value
            summary.control_as_of = observation.occurred_at
            summary.last_evidence_at = observation.occurred_at
            summary.assertion_id = assertion.assertion_id
            summary.projection_watermark = ingest_seq
            summary.updated_at = observation.recorded_at
        if observation.kind in {
            "task.completed",
            "task.failed",
            "task.interrupted",
        }:
            await self._close_settled_acting_steps(
                session,
                task_id=observation.task_id,
                followup_observed=True,
            )
            budget_rows = list((await session.execute(select(AnsichTaskBudgetRow).where(AnsichTaskBudgetRow.task_id == observation.task_id))).scalars())
            await self._assess_budget_rows(
                session,
                budget_rows=budget_rows,
                asserted_at=observation.recorded_at,
                incomplete_tasks=frozenset(),
                global_loss=False,
            )

    async def _project_heartbeat(
        self,
        session: AsyncSession,
        observation: ObservationEnvelope,
    ) -> None:
        """Project heartbeat liveness evidence only.

        ``task.heartbeat`` also belongs to ``_USAGE_PROJECTION_KINDS``, so the
        task-usage projector turns the same observation into a ``wall_time_ms``
        contribution and ``_refresh_usage_summary`` owns the resulting
        ``AnsichTaskUsageRow``. This projector deliberately keeps no wall_time
        summary of its own: two writers on one projection row would silently
        diverge once projection jobs interleave across workers (P8-M1).
        """

        if observation.payload is None:
            raise ValueError("task.heartbeat requires inline projection payload")
        if await session.get(AnsichTaskRow, observation.task_id) is None:
            raise _ProjectionDependencyPending(f"heartbeat observation {observation.obs_id} is waiting for Task {observation.task_id}")
        if await session.get(AnsichTaskHeartbeatRow, observation.obs_id) is not None:
            return
        session.add(
            AnsichTaskHeartbeatRow(
                heartbeat_obs_id=observation.obs_id,
                task_id=observation.task_id,
                occurred_at=observation.occurred_at,
                producer_instance_id=observation.producer.instance_id,
                ownership_epoch=str(observation.payload["ownership_epoch"]),
                elapsed_ms=max(0, int(observation.payload["elapsed_ms"])),
            )
        )

    async def _project_budget(
        self,
        session: AsyncSession,
        observation: ObservationEnvelope,
    ) -> None:
        if observation.payload is None:
            raise ValueError("budget.configured requires inline projection payload")
        if await session.get(AnsichTaskRow, observation.task_id) is None:
            raise _ProjectionDependencyPending(f"budget observation {observation.obs_id} is waiting for Task {observation.task_id}")
        if await session.get(AnsichEntityRow, observation.obs_id) is None:
            session.add(
                AnsichEntityRow(
                    entity_id=observation.obs_id,
                    entity_type="task_budget",
                    discovered_obs_id=observation.obs_id,
                )
            )
            await session.flush()
        if await session.get(AnsichTaskBudgetRow, observation.obs_id) is not None:
            return
        payload = observation.payload
        session.add(
            AnsichTaskBudgetRow(
                entity_id=observation.obs_id,
                task_id=observation.task_id,
                dimension=str(payload["dimension"]),
                aggregation_scope=str(payload["aggregation_scope"]),
                warning_limit=(int(payload["warning_limit"]) if isinstance(payload.get("warning_limit"), int) else None),
                hard_limit=(int(payload["hard_limit"]) if isinstance(payload.get("hard_limit"), int) else None),
                enforcement=payload.get("enforcement") is True,
                source_kind=str(payload["source_kind"]),
                requested_value=(int(payload["requested_value"]) if isinstance(payload.get("requested_value"), int) else None),
                effective_value=int(payload["effective_value"]),
                configured_obs_id=observation.obs_id,
            )
        )

    async def _project_usage(
        self,
        session: AsyncSession,
        observation: ObservationEnvelope,
        *,
        ingest_seq: int,
    ) -> None:
        task = await session.get(AnsichTaskRow, observation.task_id)
        if task is None:
            raise _ProjectionDependencyPending(f"usage observation {observation.obs_id} is waiting for Task {observation.task_id}")

        contributions = list(usage_contributions_for_observation(observation))
        if observation.kind == "tool.started":
            tool_call = await session.get(
                AnsichToolCallRow,
                observation.subject_id,
            )
            if tool_call is None:
                raise _ProjectionDependencyPending(f"usage observation {observation.obs_id} is waiting for ToolCall {observation.subject_id}")
            child_contribution = child_task_contribution_for_tool_started(
                observation,
                tool_name=tool_call.tool_name,
            )
            if child_contribution is not None:
                contributions.append(child_contribution)

        for contribution in contributions:
            if contribution.dimension == "tool_calls_executed":
                existing_tool_contribution = await session.scalar(
                    select(AnsichUsageContributionRow.source_obs_id)
                    .join(
                        AnsichObservationRow,
                        AnsichObservationRow.obs_id == AnsichUsageContributionRow.source_obs_id,
                    )
                    .where(
                        AnsichUsageContributionRow.aggregate_task_id == contribution.source_task_id,
                        AnsichUsageContributionRow.source_task_id == contribution.source_task_id,
                        AnsichUsageContributionRow.dimension == contribution.dimension,
                        AnsichObservationRow.subject_id == observation.subject_id,
                    )
                    .limit(1)
                )
                if existing_tool_contribution is not None:
                    continue
            high_water = observation.kind in HIGH_WATER_USAGE_KINDS and contribution.dimension in MAX_TYPE_USAGE_DIMENSIONS
            ancestor_ids = tuple((await session.execute(select(AnsichTaskAncestryRow.ancestor_task_id).where(AnsichTaskAncestryRow.descendant_task_id == contribution.source_task_id))).scalars())
            targets = (contribution.source_task_id, *ancestor_ids)
            for aggregate_task_id in targets:
                inserted = await self._store_usage_contribution(
                    session,
                    aggregate_task_id=aggregate_task_id,
                    source_task_id=contribution.source_task_id,
                    dimension=contribution.dimension,
                    source_obs_id=contribution.source_obs_id,
                    delta=contribution.delta,
                    as_of=contribution.as_of,
                    high_water=high_water,
                )
                if not inserted:
                    continue
                if aggregate_task_id == contribution.source_task_id:
                    await self._refresh_usage_summary(
                        session,
                        task_id=aggregate_task_id,
                        dimension=contribution.dimension,
                        aggregation_scope="local",
                        updated_at=observation.recorded_at,
                    )
                await self._refresh_usage_summary(
                    session,
                    task_id=aggregate_task_id,
                    dimension=contribution.dimension,
                    aggregation_scope="inclusive",
                    updated_at=observation.recorded_at,
                )

    @classmethod
    async def _store_usage_contribution(
        cls,
        session: AsyncSession,
        *,
        aggregate_task_id: str,
        source_task_id: str,
        dimension: str,
        source_obs_id: str,
        delta: int,
        as_of: datetime,
        high_water: bool,
    ) -> bool:
        """Persist one contribution, returning whether the aggregate changed.

        Sum-type dimensions append an immutable row keyed by
        ``(aggregate, source, dimension, source_obs_id)``. Max-type dimensions
        fed by a repeating tick (``HIGH_WATER_USAGE_KINDS``) instead keep ONE
        row per ``(aggregate, source)``, replaced only when the new observation
        raises the high-water mark — see ``_upsert_high_water_contribution``.
        """

        if not high_water:
            return await cls._insert_usage_contribution(
                session,
                aggregate_task_id=aggregate_task_id,
                source_task_id=source_task_id,
                dimension=dimension,
                source_obs_id=source_obs_id,
                delta=delta,
                as_of=as_of,
            )
        return await cls._upsert_high_water_contribution(
            session,
            aggregate_task_id=aggregate_task_id,
            source_task_id=source_task_id,
            dimension=dimension,
            source_obs_id=source_obs_id,
            delta=delta,
            as_of=as_of,
        )

    @staticmethod
    async def _upsert_high_water_contribution(
        session: AsyncSession,
        *,
        aggregate_task_id: str,
        source_task_id: str,
        dimension: str,
        source_obs_id: str,
        delta: int,
        as_of: datetime,
    ) -> bool:
        """Keep one high-water contribution row per ``(aggregate, source)``.

        The stored row is the lexicographic maximum of
        ``(delta, as_of, source_obs_id)`` over every tick observed so far, which
        makes the update commutative and idempotent: replaying an already-seen
        or an out-of-order tick converges on the same row, so
        ``rebuild_projections()`` reproduces the projection exactly.

        Only rows produced by a ``HIGH_WATER_USAGE_KINDS`` observation take part.
        A terminal ``budget.consumed`` wall_time contribution arrives once per
        Task, keeps its own immutable row, and therefore keeps its own evidence
        alongside the heartbeat mark.
        """

        # Lock the mark BEFORE reading it. Every tick of one Task is an
        # independent projection job that separate leased workers claim
        # concurrently (_claim_projection_job uses skip_locked), and the
        # ancestry fan-out makes sibling Tasks contend for one ancestor's row,
        # yet they all read-modify-write that single row. Under Postgres READ
        # COMMITTED an unlocked reader could load the current mark before a peer
        # commits a higher one and then delete-and-replace it with a lower
        # value — a lost update the ON CONFLICT insert this replaced could not
        # produce, and that a single-loop replay would not reproduce. Locking
        # first makes the second worker block until the first commits, and READ
        # COMMITTED then gives its later statements the committed row. Locking
        # after the read would leave exactly the same window open. FOR UPDATE is
        # a no-op on SQLite, which has a single writer anyway. Same precedent as
        # _recompute_release_quality_stats.
        existing = list(
            (
                await session.execute(
                    select(AnsichUsageContributionRow)
                    .join(
                        AnsichObservationRow,
                        AnsichObservationRow.obs_id == AnsichUsageContributionRow.source_obs_id,
                    )
                    .where(
                        AnsichUsageContributionRow.aggregate_task_id == aggregate_task_id,
                        AnsichUsageContributionRow.source_task_id == source_task_id,
                        AnsichUsageContributionRow.dimension == dimension,
                        AnsichObservationRow.kind.in_(HIGH_WATER_USAGE_KINDS),
                    )
                    .with_for_update(of=AnsichUsageContributionRow)
                )
            ).scalars()
        )
        candidate = (delta, as_of, source_obs_id)
        if existing and max((row.delta, _as_utc(row.as_of), row.source_obs_id) for row in existing) >= candidate:
            return False
        for row in existing:
            await session.delete(row)
        await session.flush()
        session.add(
            AnsichUsageContributionRow(
                aggregate_task_id=aggregate_task_id,
                source_task_id=source_task_id,
                dimension=dimension,
                source_obs_id=source_obs_id,
                delta=delta,
                as_of=as_of,
            )
        )
        await session.flush()
        return True

    @staticmethod
    async def _insert_usage_contribution(
        session: AsyncSession,
        *,
        aggregate_task_id: str,
        source_task_id: str,
        dimension: str,
        source_obs_id: str,
        delta: int,
        as_of: datetime,
    ) -> bool:
        values = {
            "aggregate_task_id": aggregate_task_id,
            "source_task_id": source_task_id,
            "dimension": dimension,
            "source_obs_id": source_obs_id,
            "delta": delta,
            "as_of": as_of,
        }
        dialect_name = session.bind.dialect.name if session.bind is not None else ""
        if dialect_name == "postgresql":
            statement = postgresql_insert(AnsichUsageContributionRow).values(**values)
        elif dialect_name == "sqlite":
            statement = sqlite_insert(AnsichUsageContributionRow).values(**values)
        else:
            raise ValueError(f"unsupported Ansich SQL dialect: {dialect_name}")
        inserted = (
            await session.execute(
                statement.on_conflict_do_nothing(
                    index_elements=[
                        "aggregate_task_id",
                        "source_task_id",
                        "dimension",
                        "source_obs_id",
                    ]
                ).returning(AnsichUsageContributionRow.source_obs_id)
            )
        ).scalar_one_or_none()
        return inserted is not None

    @staticmethod
    async def _refresh_usage_summary(
        session: AsyncSession,
        *,
        task_id: str,
        dimension: str,
        aggregation_scope: AggregationScope,
        updated_at: datetime,
    ) -> None:
        statement = (
            select(AnsichUsageContributionRow, AnsichObservationRow.ingest_seq)
            .join(
                AnsichObservationRow,
                AnsichObservationRow.obs_id == AnsichUsageContributionRow.source_obs_id,
            )
            .where(
                AnsichUsageContributionRow.aggregate_task_id == task_id,
                AnsichUsageContributionRow.dimension == dimension,
            )
        )
        if aggregation_scope == "local":
            statement = statement.where(AnsichUsageContributionRow.source_task_id == task_id)
        rows = list((await session.execute(statement)).all())
        if not rows:
            return
        if dimension == "wall_time_ms":
            latest_by_source: dict[str, int] = {}
            for contribution, _ in rows:
                latest_by_source[contribution.source_task_id] = max(
                    latest_by_source.get(contribution.source_task_id, 0),
                    contribution.delta,
                )
            value = sum(latest_by_source.values())
        else:
            value = sum(contribution.delta for contribution, _ in rows)
        as_of = max(_as_utc(contribution.as_of) for contribution, _ in rows)
        watermark = max(ingest_seq for _, ingest_seq in rows)
        usage = await session.get(
            AnsichTaskUsageRow,
            (task_id, dimension, aggregation_scope),
        )
        if usage is None:
            session.add(
                AnsichTaskUsageRow(
                    task_id=task_id,
                    dimension=dimension,
                    aggregation_scope=aggregation_scope,
                    value=value,
                    as_of=as_of,
                    complete_through_ingest_seq=watermark,
                    updated_at=updated_at,
                )
            )
            return
        usage.value = value
        usage.as_of = as_of
        usage.complete_through_ingest_seq = watermark
        usage.updated_at = updated_at

    async def _project_step(self, session: AsyncSession, observation: ObservationEnvelope) -> bool:
        """Project logical decisions, physical LLM attempts, and request context.

        Projector routing creates jobs only for the event kinds consumed here;
        this guard remains a replay compatibility boundary for unknown kinds.
        """

        if observation.kind not in _STEP_PROJECTION_KINDS:
            return False
        if observation.payload is None:
            raise ValueError(f"{observation.kind} requires inline projection payload")
        if await session.get(AnsichTaskRow, observation.task_id) is None:
            raise _ProjectionDependencyPending(f"Ansich task is not projected: {observation.task_id}")

        payload = observation.payload
        if observation.kind == "step.started":
            if observation.step_id is None:
                raise ValueError("step.started is missing step_id")
            if await session.get(AnsichEntityRow, observation.step_id) is None:
                session.add(
                    AnsichEntityRow(
                        entity_id=observation.step_id,
                        entity_type="step",
                        discovered_obs_id=observation.obs_id,
                    )
                )
            if await session.get(AnsichStepRow, observation.step_id) is None:
                session.add(
                    AnsichStepRow(
                        entity_id=observation.step_id,
                        task_id=observation.task_id,
                        step_seq=int(payload["step_seq"]),
                        actor_kind=str(payload["actor_kind"]),
                        status="deciding",
                        started_obs_id=observation.obs_id,
                        issued_tools_json=[],
                    )
                )
            await self._close_settled_acting_steps(
                session,
                task_id=observation.task_id,
                before_step_seq=int(payload["step_seq"]),
                followup_observed=True,
            )
            return False

        if observation.kind == "step.closed":
            if observation.step_id is None:
                raise ValueError("step.closed is missing step_id")
            step = await session.get(AnsichStepRow, observation.step_id)
            if step is None:
                raise _ProjectionDependencyPending(f"step.started has not been projected: {observation.step_id}")
            result = str(payload["result"])
            step.result = result
            step.status = "model_failed" if result == "model_failed" else "acting" if result == "acting" else "closed"
            step.closed_obs_id = observation.obs_id
            step.issued_tools_json = list(payload.get("issued_tools", []))
            raw_effective_attempt_no = payload.get("effective_attempt_no")
            if isinstance(raw_effective_attempt_no, int):
                attempt = await session.scalar(
                    select(AnsichLlmAttemptRow).where(
                        AnsichLlmAttemptRow.step_id == step.entity_id,
                        AnsichLlmAttemptRow.attempt_no == raw_effective_attempt_no,
                        AnsichLlmAttemptRow.status == "success",
                    )
                )
                if attempt is not None:
                    step.effective_attempt_no = attempt.attempt_no
                    step.effective_context_snapshot_id = attempt.context_snapshot_id
            return False

        if observation.kind == "content.produced":
            if await session.get(AnsichEntityRow, observation.subject_id) is None:
                session.add(
                    AnsichEntityRow(
                        entity_id=observation.subject_id,
                        entity_type="content_block",
                        discovered_obs_id=observation.obs_id,
                    )
                )
            if await session.get(AnsichContentBlockRow, observation.subject_id) is None:
                session.add(
                    AnsichContentBlockRow(
                        entity_id=observation.subject_id,
                        kind=str(payload["kind"]),
                        content_hash=str(payload["content_hash"]),
                        payload_obs_id=observation.obs_id,
                        producer_obs_id=observation.obs_id,
                        blob_key=payload.get("blob_key") if isinstance(payload.get("blob_key"), str) else None,
                        byte_size=int(payload["visible_bytes"]),
                        token_estimate=int(payload["estimated_tokens"]),
                        sensitivity_flags_json=list(payload.get("sensitivity_flags", [])),
                    )
                )
                await session.flush()
            if await session.get(AnsichBlockProducerRow, observation.subject_id) is None:
                producer_entity_id = next(
                    (payload.get(key) for key in ("producer_entity_id", "compression_id", "attempt_id") if isinstance(payload.get(key), str)),
                    None,
                )
                session.add(
                    AnsichBlockProducerRow(
                        block_id=observation.subject_id,
                        producer_kind=str(payload.get("producer_kind") or observation.producer.name),
                        producer_entity_id=producer_entity_id,
                        producer_obs_id=observation.obs_id,
                    )
                )
            raw_derivations = [item for item in payload.get("derivation_sources", []) if isinstance(item, dict)]
            source_block_id = payload.get("source_block_id")
            if isinstance(source_block_id, str):
                raw_derivations.append(
                    {
                        "source_block_id": source_block_id,
                        "transform_kind": payload.get("transform_kind", "unknown"),
                        "transform_version": payload.get("transform_version", "1"),
                        "source_role": payload.get("source_role", "source"),
                        "ordinal": payload.get("source_ordinal"),
                    }
                )
            for derivation in raw_derivations:
                source_block_id = derivation.get("source_block_id")
                if not isinstance(source_block_id, str) or source_block_id == observation.subject_id:
                    continue
                if await session.get(AnsichContentBlockRow, source_block_id) is None:
                    raise _ProjectionDependencyPending(f"source content block has not been projected: {source_block_id}")
                transform_kind = str(derivation.get("transform_kind", "unknown"))
                derivation_key = (
                    observation.subject_id,
                    source_block_id,
                    transform_kind,
                )
                if (
                    await session.get(
                        AnsichContentBlockDerivationRow,
                        derivation_key,
                    )
                    is None
                ):
                    session.add(
                        AnsichContentBlockDerivationRow(
                            derived_block_id=observation.subject_id,
                            source_block_id=source_block_id,
                            transform_kind=transform_kind,
                            transform_version=str(derivation.get("transform_version", "1")),
                            source_role=str(derivation.get("source_role", "source")),
                            ordinal=(int(derivation["ordinal"]) if isinstance(derivation.get("ordinal"), int) else None),
                            established_obs_id=observation.obs_id,
                        )
                    )
            source_identity = payload.get("source_identity")
            if isinstance(source_identity, str) and source_identity:
                occurrence_key = (
                    observation.task_id,
                    source_identity,
                    str(payload["content_hash"]),
                    str(payload["kind"]),
                )
                if await session.get(AnsichContentOccurrenceRow, occurrence_key) is None:
                    session.add(
                        AnsichContentOccurrenceRow(
                            task_id=observation.task_id,
                            source_identity=source_identity,
                            content_hash=str(payload["content_hash"]),
                            kind=str(payload["kind"]),
                            block_id=observation.subject_id,
                            producer_obs_id=observation.obs_id,
                        )
                    )
            missing_items = list((await session.execute(select(AnsichContextSnapshotMissingItemRow).where(AnsichContextSnapshotMissingItemRow.expected_content_block_id == observation.subject_id))).scalars())
            affected_snapshot_ids: set[str] = set()
            for missing in missing_items:
                affected_snapshot_ids.add(missing.snapshot_id)
                if await session.get(AnsichContextSnapshotItemRow, (missing.snapshot_id, missing.ordinal)) is None:
                    session.add(
                        AnsichContextSnapshotItemRow(
                            snapshot_id=missing.snapshot_id,
                            ordinal=missing.ordinal,
                            channel=missing.channel,
                            role=missing.role,
                            name=missing.name,
                            message_id=missing.message_id,
                            source_identity=missing.source_identity,
                            content_block_id=observation.subject_id,
                            visible_bytes=missing.visible_bytes,
                            estimated_tokens=missing.estimated_tokens,
                            metadata_json=missing.metadata_json,
                        )
                    )
                if (
                    await session.get(
                        AnsichContextSnapshotBlockMembershipRow,
                        (missing.snapshot_id, missing.ordinal),
                    )
                    is None
                ):
                    session.add(
                        AnsichContextSnapshotBlockMembershipRow(
                            snapshot_id=missing.snapshot_id,
                            ordinal=missing.ordinal,
                            content_block_id=observation.subject_id,
                        )
                    )
                await session.delete(missing)
            if affected_snapshot_ids:
                await session.flush()
                for snapshot_id in affected_snapshot_ids:
                    remaining = await session.scalar(select(func.count()).select_from(AnsichContextSnapshotMissingItemRow).where(AnsichContextSnapshotMissingItemRow.snapshot_id == snapshot_id))
                    if not remaining:
                        repaired_snapshot = await session.get(AnsichContextSnapshotRow, snapshot_id)
                        if repaired_snapshot is not None:
                            repaired_snapshot.status = "complete"
            state_ids = list((await session.execute(select(AnsichContextStateMissingBlockRow.state_id).where(AnsichContextStateMissingBlockRow.block_id == observation.subject_id))).scalars())
            for state_id in state_ids:
                missing = await session.get(
                    AnsichContextStateMissingBlockRow,
                    (state_id, observation.subject_id),
                )
                if missing is not None:
                    await session.delete(missing)
                await self._refresh_context_state_and_descendants(session, state_id)
            return bool(affected_snapshot_ids or state_ids)

        if observation.kind == "context.state_recorded":
            await self._project_context_state(session, observation)
            return True

        if observation.kind == "context.snapshotted":
            await self._project_context_snapshot(session, observation)
            return True

        if observation.kind == "context.compressed":
            await self._project_context_compression(session, observation)
            return True

        if observation.kind.startswith("tool."):
            await self._project_tool_call(session, observation)
            return False

        attempt = await session.get(AnsichLlmAttemptRow, observation.subject_id)
        if attempt is None:
            actor_kind = "system_operation"
            if observation.step_id is not None:
                step = await session.get(AnsichStepRow, observation.step_id)
                if step is None:
                    raise _ProjectionDependencyPending(f"step.started has not been projected: {observation.step_id}")
                actor_kind = step.actor_kind
            attempt = AnsichLlmAttemptRow(
                attempt_id=observation.subject_id,
                task_id=observation.task_id,
                step_id=observation.step_id,
                actor_kind=str(payload.get("actor_kind", actor_kind)),
                operation_id=payload.get("operation_id") if isinstance(payload.get("operation_id"), str) else None,
                operation_kind=payload.get("operation_kind") if isinstance(payload.get("operation_kind"), str) else None,
                attempt_no=int(payload["attempt_no"]),
                status="incomplete",
            )
            session.add(attempt)

        if observation.kind == "llm.requested":
            attempt.request_obs_id = observation.obs_id
            attempt.actor_kind = str(payload.get("actor_kind", attempt.actor_kind))
            if isinstance(payload.get("operation_id"), str):
                attempt.operation_id = str(payload["operation_id"])
            if isinstance(payload.get("operation_kind"), str):
                attempt.operation_kind = str(payload["operation_kind"])
            if attempt.status == "incomplete":
                attempt.status = "requested"
        elif observation.kind == "llm.responded":
            attempt.response_obs_id = observation.obs_id
            attempt.status = "success"
            attempt.latency_ms = int(payload["latency_ms"])
            attempt.usage_json = dict(payload.get("usage", {}))
            attempt.response_metadata_json = dict(payload.get("response_metadata", {}))
            response_metadata = attempt.response_metadata_json
            reported_model = payload.get("provider_model")
            if not isinstance(reported_model, str):
                reported_model = response_metadata.get("model_name")
            attempt.provider_model = reported_model if isinstance(reported_model, str) else None
        elif observation.kind == "llm.failed":
            attempt.failure_obs_id = observation.obs_id
            attempt.status = "failed"
            attempt.latency_ms = int(payload["latency_ms"])
        return False

    async def _project_tool_call(
        self,
        session: AsyncSession,
        observation: ObservationEnvelope,
    ) -> None:
        if observation.step_id is None or observation.payload is None:
            raise ValueError(f"{observation.kind} requires step_id and payload")
        step = await session.get(AnsichStepRow, observation.step_id)
        if step is None:
            raise _ProjectionDependencyPending(f"step.started has not been projected: {observation.step_id}")
        payload = observation.payload
        tool_call = await session.get(AnsichToolCallRow, observation.subject_id)
        if tool_call is None:
            if await session.get(AnsichEntityRow, observation.subject_id) is None:
                session.add(
                    AnsichEntityRow(
                        entity_id=observation.subject_id,
                        entity_type="tool_call",
                        discovered_obs_id=observation.obs_id,
                    )
                )
            tool_call = AnsichToolCallRow(
                entity_id=observation.subject_id,
                task_id=observation.task_id,
                step_id=observation.step_id,
                call_seq=int(payload.get("call_seq", 0)),
                tool_name="unknown",
                args_hash="",
                execution_status="unknown",
                visible_result_status="unknown",
            )
            session.add(tool_call)
            await session.flush()

        if observation.kind == "tool.issued":
            first_issued_evidence = tool_call.issued_obs_id is None
            tool_call.call_seq = int(payload["call_seq"])
            tool_call.provider_call_id = payload.get("provider_call_id") if isinstance(payload.get("provider_call_id"), str) else None
            tool_call.tool_name = str(payload["tool_name"])
            tool_call.args_hash = str(payload["args_hash"])
            tool_call.args_preview_json = payload.get("args_preview")
            tool_call.tool_schema_block_id = payload.get("tool_schema_block_id") if isinstance(payload.get("tool_schema_block_id"), str) else None
            tool_call.issued_obs_id = observation.obs_id
            if tool_call.execution_status == "unknown":
                tool_call.execution_status = "issued"
            if first_issued_evidence:
                await self._increment_tool_usage(
                    session,
                    observation.task_id,
                    issued=1,
                )
            return
        if observation.kind == "tool.started":
            first_execution_evidence = tool_call.execution_status in {"unknown", "issued"}
            tool_call.started_obs_id = observation.obs_id
            if tool_call.raw_terminal_obs_id is None:
                tool_call.execution_status = "acting"
            if first_execution_evidence:
                await self._increment_tool_usage(
                    session,
                    observation.task_id,
                    executed=1,
                )
            return
        if observation.kind == "tool.result_visible":
            tool_call.visible_result_obs_id = observation.obs_id
            tool_call.visible_result_status = "available"
            result_block_id = payload.get("result_block_id")
            if isinstance(result_block_id, str):
                result_key = (tool_call.entity_id, "visible", observation.obs_id)
                if await session.get(AnsichToolCallResultRow, result_key) is None:
                    session.add(
                        AnsichToolCallResultRow(
                            tool_call_id=tool_call.entity_id,
                            result_role="visible",
                            source_obs_id=observation.obs_id,
                            content_block_id=result_block_id,
                            metadata_json={"transform_kind": payload.get("transform_kind", "unknown")},
                        )
                    )
            source_block_id = payload.get("source_block_id")
            if isinstance(result_block_id, str) and isinstance(source_block_id, str) and result_block_id != source_block_id:
                transform_kind = str(payload.get("transform_kind", "unknown"))
                derivation_key = (result_block_id, source_block_id, transform_kind)
                if await session.get(AnsichContentBlockDerivationRow, derivation_key) is None:
                    session.add(
                        AnsichContentBlockDerivationRow(
                            derived_block_id=result_block_id,
                            source_block_id=source_block_id,
                            transform_kind=transform_kind,
                            transform_version=str(payload.get("transform_version", "1")),
                            established_obs_id=observation.obs_id,
                        )
                    )
            return

        terminal_status = {
            "tool.returned_raw": "returned",
            "tool.denied": "denied",
            "tool.timed_out": "timed_out",
            "tool.cancelled": "cancelled",
            "tool.failed": "failed",
            "tool.unknown_terminal": "unknown_terminal",
        }.get(observation.kind)
        if terminal_status is None:
            return
        previous_terminal_status = tool_call.execution_status if tool_call.raw_terminal_obs_id is not None else None
        assertion = AnsichBeliefAssertionRow(
            assertion_id=new_id(),
            subject_id=tool_call.entity_id,
            field_name="execution",
            value_json={"value": terminal_status},
            as_of=observation.occurred_at,
            asserted_at=observation.recorded_at,
            source_name=observation.producer.name,
            source_version=observation.producer.version,
            assessor_name=observation.producer.name,
            assessor_version=observation.producer.version,
            config_hash=canonical_config_hash({"tool_terminal_precedence": "1"}),
            authority_class="deterministic",
            fidelity_class="hard",
            confidence=None,
        )
        session.add(assertion)
        session.add(
            AnsichBeliefEvidenceRow(
                assertion_id=assertion.assertion_id,
                obs_id=observation.obs_id,
                evidence_role="supporting",
                ordinal=0,
            )
        )
        current_execution = await session.get(
            AnsichCurrentBeliefRow,
            (tool_call.entity_id, "execution"),
        )
        if current_execution is None:
            session.add(
                AnsichCurrentBeliefRow(
                    subject_id=tool_call.entity_id,
                    field_name="execution",
                    assertion_id=assertion.assertion_id,
                    resolver_name="tool-terminal-precedence",
                    resolver_version="1",
                )
            )
        candidate_selected = previous_terminal_status is None or _TOOL_TERMINAL_PRECEDENCE[terminal_status] >= _TOOL_TERMINAL_PRECEDENCE[previous_terminal_status]
        if current_execution is not None and candidate_selected:
            current_execution.assertion_id = assertion.assertion_id
        if previous_terminal_status is not None and previous_terminal_status != terminal_status:
            summary = await session.get(AnsichTaskSummaryRow, observation.task_id)
            if summary is not None:
                summary.observability_status = "degraded"
        first_execution_evidence = terminal_status not in {"denied", "unknown_terminal"} and tool_call.execution_status in {"unknown", "issued", "denied", "unknown_terminal"}
        if candidate_selected:
            tool_call.raw_terminal_obs_id = observation.obs_id
            tool_call.execution_status = terminal_status
        if first_execution_evidence:
            await self._increment_tool_usage(
                session,
                observation.task_id,
                executed=1,
            )
        if candidate_selected and isinstance(payload.get("duration_ms"), int):
            tool_call.duration_ms = int(payload["duration_ms"])
        result_block_id = payload.get("result_block_id")
        if isinstance(result_block_id, str):
            result_key = (tool_call.entity_id, "raw", observation.obs_id)
            if await session.get(AnsichToolCallResultRow, result_key) is None:
                session.add(
                    AnsichToolCallResultRow(
                        tool_call_id=tool_call.entity_id,
                        result_role="raw",
                        source_obs_id=observation.obs_id,
                        content_block_id=result_block_id,
                        metadata_json={key: value for key, value in payload.items() if key not in {"result_block_id", "call_seq"}},
                    )
                )
        later_step_exists = (
            await session.scalar(
                select(AnsichStepRow.entity_id)
                .where(
                    AnsichStepRow.task_id == observation.task_id,
                    AnsichStepRow.step_seq > step.step_seq,
                )
                .limit(1)
            )
            is not None
        )
        summary = await session.get(AnsichTaskSummaryRow, observation.task_id)
        task_is_terminal = summary is not None and summary.control_value in {"completed", "failed", "interrupted"}
        if later_step_exists or task_is_terminal:
            await self._close_settled_acting_steps(
                session,
                task_id=observation.task_id,
                step_id=step.entity_id,
                followup_observed=True,
            )

    @staticmethod
    async def _close_settled_acting_steps(
        session: AsyncSession,
        *,
        task_id: str,
        step_id: str | None = None,
        before_step_seq: int | None = None,
        followup_observed: bool,
    ) -> None:
        if not followup_observed:
            return
        statement = select(AnsichStepRow).where(
            AnsichStepRow.task_id == task_id,
            AnsichStepRow.status == "acting",
        )
        if step_id is not None:
            statement = statement.where(AnsichStepRow.entity_id == step_id)
        if before_step_seq is not None:
            statement = statement.where(AnsichStepRow.step_seq < before_step_seq)
        steps = list((await session.execute(statement)).scalars())
        for acting_step in steps:
            issued_count = await session.scalar(select(func.count()).select_from(AnsichToolCallRow).where(AnsichToolCallRow.step_id == acting_step.entity_id))
            unsettled_count = await session.scalar(
                select(func.count())
                .select_from(AnsichToolCallRow)
                .where(
                    AnsichToolCallRow.step_id == acting_step.entity_id,
                    AnsichToolCallRow.raw_terminal_obs_id.is_(None),
                )
            )
            if int(issued_count or 0) > 0 and int(unsettled_count or 0) == 0:
                acting_step.status = "closed"

    @staticmethod
    async def _increment_tool_usage(
        session: AsyncSession,
        task_id: str,
        *,
        issued: int = 0,
        executed: int = 0,
    ) -> None:
        await session.execute(
            update(AnsichTaskSummaryRow)
            .where(AnsichTaskSummaryRow.task_id == task_id)
            .values(
                tool_calls_issued=AnsichTaskSummaryRow.tool_calls_issued + issued,
                tool_calls_executed=AnsichTaskSummaryRow.tool_calls_executed + executed,
            )
        )

    async def _ensure_context_state_placeholder(
        self,
        session: AsyncSession,
        *,
        state_id: str,
        task_id: str,
        discovered_obs_id: str,
    ) -> AnsichContextStateRow:
        if await session.get(AnsichEntityRow, state_id) is None:
            session.add(
                AnsichEntityRow(
                    entity_id=state_id,
                    entity_type="context_state",
                    discovered_obs_id=discovered_obs_id,
                )
            )
        state = await session.get(AnsichContextStateRow, state_id)
        if state is None:
            state = AnsichContextStateRow(
                state_id=state_id,
                task_id=task_id,
                state_hash=None,
                parent_state_id=None,
                created_obs_id=None,
                chain_depth=0,
                item_count=0,
                is_checkpoint=False,
                status="missing",
            )
            session.add(state)
            await session.flush()
        elif state.task_id != task_id:
            raise ValueError("ContextState placeholder belongs to a different task")
        return state

    async def _project_context_state(
        self,
        session: AsyncSession,
        observation: ObservationEnvelope,
    ) -> None:
        if observation.payload is None:
            raise ValueError("context.state_recorded is missing payload")
        payload = observation.payload
        parent_state_id = payload.get("parent_state_id") if isinstance(payload.get("parent_state_id"), str) else None
        if parent_state_id == observation.subject_id:
            raise ValueError("ContextState cannot parent itself")
        if parent_state_id is not None:
            await self._ensure_context_state_placeholder(
                session,
                state_id=parent_state_id,
                task_id=observation.task_id,
                discovered_obs_id=observation.obs_id,
            )
        state = await self._ensure_context_state_placeholder(
            session,
            state_id=observation.subject_id,
            task_id=observation.task_id,
            discovered_obs_id=observation.obs_id,
        )
        state_hash = str(payload["state_hash"])
        if state.created_obs_id is not None:
            if state.state_hash != state_hash:
                raise ValueError("ContextState ID collision")
            return
        is_checkpoint = bool(payload["is_checkpoint"])
        if is_checkpoint != (parent_state_id is None):
            raise ValueError("ContextState checkpoint/parent shape is inconsistent")
        state.state_hash = state_hash
        state.parent_state_id = parent_state_id
        state.created_obs_id = observation.obs_id
        state.chain_depth = int(payload["chain_depth"])
        state.item_count = int(payload["item_count"])
        state.is_checkpoint = is_checkpoint
        state.status = "incomplete"
        state.created_at = observation.recorded_at

        if is_checkpoint:
            items = tuple(ContextStateItem.model_validate(item) for item in payload.get("checkpoint_items", []))
            if len(items) != state.item_count:
                raise ValueError("ContextState checkpoint item_count mismatch")
            for item in items:
                session.add(
                    AnsichContextStateCheckpointItemRow(
                        state_id=state.state_id,
                        ordinal=item.ordinal,
                        channel=item.channel,
                        role=item.role,
                        message_id=item.message_id,
                        source_identity=item.source_identity,
                        name=item.name,
                        block_id=item.block_id,
                        visible_bytes=item.visible_bytes,
                        estimated_tokens=item.estimated_tokens,
                        metadata_json=item.metadata,
                    )
                )
        else:
            operations = tuple(ContextStateDelta.model_validate(item) for item in payload.get("delta", []))
            for operation_ordinal, operation in enumerate(operations):
                item = operation.item
                session.add(
                    AnsichContextStateDeltaRow(
                        state_id=state.state_id,
                        operation_ordinal=operation_ordinal,
                        operation=operation.op,
                        source_ordinal=operation.source_ordinal,
                        target_ordinal=operation.target_ordinal,
                        channel=None if item is None else item.channel,
                        role=None if item is None else item.role,
                        message_id=None if item is None else item.message_id,
                        source_identity=None if item is None else item.source_identity,
                        name=None if item is None else item.name,
                        block_id=None if item is None else item.block_id,
                        visible_bytes=None if item is None else item.visible_bytes,
                        estimated_tokens=None if item is None else item.estimated_tokens,
                        metadata_json=None if item is None else item.metadata,
                    )
                )
        await session.flush()
        await self._refresh_context_state_and_descendants(session, state.state_id)

    async def _refresh_context_state_and_descendants(
        self,
        session: AsyncSession,
        root_state_id: str,
    ) -> None:
        pending = [root_state_id]
        visited: set[str] = set()
        while pending:
            state_id = pending.pop(0)
            if state_id in visited:
                continue
            visited.add(state_id)
            state = await session.get(AnsichContextStateRow, state_id)
            if state is None or state.created_obs_id is None or state.state_hash is None:
                continue
            state.status = "incomplete"
            await session.flush()
            try:
                items = await self._materialize_context_state(session, state_id, frozenset())
            except ValueError:
                items = ()
            if items:
                if len(items) != state.item_count or context_state_hash(items) != state.state_hash:
                    raise ValueError("ContextState materialization does not match its declared hash")
            elif state.item_count != 0:
                children = list((await session.execute(select(AnsichContextStateRow.state_id).where(AnsichContextStateRow.parent_state_id == state_id))).scalars())
                pending.extend(children)
                continue
            await session.execute(delete(AnsichContextStateMissingBlockRow).where(AnsichContextStateMissingBlockRow.state_id == state_id))
            block_ids = {item.block_id for item in items}
            available: set[str] = set()
            if block_ids:
                available = set((await session.execute(select(AnsichContentBlockRow.entity_id).where(AnsichContentBlockRow.entity_id.in_(block_ids)))).scalars())
            for block_id in sorted(block_ids - available):
                session.add(
                    AnsichContextStateMissingBlockRow(
                        state_id=state_id,
                        block_id=block_id,
                    )
                )
            state.status = "complete" if block_ids == available else "incomplete"
            await session.execute(update(AnsichContextSnapshotRow).where(AnsichContextSnapshotRow.state_id == state_id).values(status="complete" if state.status == "complete" else "incomplete"))
            snapshot_ids = list((await session.execute(select(AnsichContextSnapshotRow.entity_id).where(AnsichContextSnapshotRow.state_id == state_id))).scalars())
            for snapshot_id in snapshot_ids:
                await self._sync_snapshot_block_memberships(
                    session,
                    snapshot_id=snapshot_id,
                    items=items,
                    available_block_ids=available,
                )
            children = list((await session.execute(select(AnsichContextStateRow.state_id).where(AnsichContextStateRow.parent_state_id == state_id))).scalars())
            pending.extend(children)

    @staticmethod
    async def _sync_snapshot_block_memberships(
        session: AsyncSession,
        *,
        snapshot_id: str,
        items: tuple[ContextStateItem, ...],
        available_block_ids: set[str] | None = None,
    ) -> None:
        available = available_block_ids
        if available is None:
            block_ids = {item.block_id for item in items}
            available = set((await session.execute(select(AnsichContentBlockRow.entity_id).where(AnsichContentBlockRow.entity_id.in_(block_ids)))).scalars()) if block_ids else set()
        for item in items:
            if item.block_id not in available:
                continue
            key = (snapshot_id, item.ordinal)
            existing = await session.get(
                AnsichContextSnapshotBlockMembershipRow,
                key,
            )
            if existing is None:
                session.add(
                    AnsichContextSnapshotBlockMembershipRow(
                        snapshot_id=snapshot_id,
                        ordinal=item.ordinal,
                        content_block_id=item.block_id,
                    )
                )
            elif existing.content_block_id != item.block_id:
                raise ValueError("snapshot block membership conflicts with existing ordinal")

    async def _project_context_snapshot(
        self,
        session: AsyncSession,
        observation: ObservationEnvelope,
    ) -> None:
        if observation.payload is None:
            raise ValueError("context.snapshotted is missing payload")
        payload = observation.payload
        attempt_id = str(payload["attempt_id"])
        attempt = await session.get(AnsichLlmAttemptRow, attempt_id)
        if attempt is None:
            raise _ProjectionDependencyPending(f"llm.requested has not been projected: {attempt_id}")
        state_id = payload.get("state_id") if isinstance(payload.get("state_id"), str) else None
        state = None
        if state_id is not None:
            state = await self._ensure_context_state_placeholder(
                session,
                state_id=state_id,
                task_id=observation.task_id,
                discovered_obs_id=observation.obs_id,
            )

        window = await session.scalar(select(AnsichContextWindowRow).where(AnsichContextWindowRow.task_id == observation.task_id))
        if window is None:
            window_id = new_id()
            session.add(
                AnsichEntityRow(
                    entity_id=window_id,
                    entity_type="context_window",
                    discovered_obs_id=observation.obs_id,
                )
            )
            await session.flush()
            window = AnsichContextWindowRow(
                entity_id=window_id,
                task_id=observation.task_id,
                capacity_tokens=None,
                estimator_name=str(payload["estimator_name"]),
                estimator_version=str(payload["estimator_version"]),
            )
            session.add(window)

        if await session.get(AnsichEntityRow, observation.subject_id) is None:
            session.add(
                AnsichEntityRow(
                    entity_id=observation.subject_id,
                    entity_type="context_snapshot",
                    discovered_obs_id=observation.obs_id,
                )
            )
        snapshot = await session.get(AnsichContextSnapshotRow, observation.subject_id)
        if snapshot is None:
            if observation.causation_obs_id is None:
                raise ValueError("context.snapshotted is missing request causation")
            snapshot = AnsichContextSnapshotRow(
                entity_id=observation.subject_id,
                task_id=observation.task_id,
                step_id=observation.step_id,
                operation_id=payload.get("operation_id") if isinstance(payload.get("operation_id"), str) else None,
                state_id=state_id,
                attempt_no=int(payload["attempt_no"]),
                request_obs_id=observation.causation_obs_id,
                message_count=int(payload["message_count"]),
                tool_schema_count=int(payload["tool_schema_count"]),
                visible_bytes=int(payload["visible_bytes"]),
                estimated_tokens=int(payload["estimated_tokens"]),
                estimator_name=str(payload["estimator_name"]),
                estimator_version=str(payload["estimator_version"]),
                adapter_name=str(payload["adapter_name"]),
                adapter_version=str(payload["adapter_version"]),
                configured_model=payload.get("configured_model") if isinstance(payload.get("configured_model"), str) else None,
                response_format_json=payload.get("response_format"),
                generation_settings_json=dict(payload.get("generation_settings", {})),
                redactions_json=list(payload.get("redactions", [])),
                warnings_json=list(payload.get("warnings", [])),
                status="complete" if state is None or state.status == "complete" else "incomplete",
            )
            session.add(snapshot)
            await session.flush()

        if state_id is not None:
            await self._link_attempt_context_snapshot(
                session,
                attempt=attempt,
                snapshot_id=snapshot.entity_id,
            )
            if state is not None and state.created_obs_id is not None:
                try:
                    items = await self._materialize_context_state(
                        session,
                        state_id,
                        frozenset(),
                    )
                except ValueError:
                    items = ()
                await self._sync_snapshot_block_memberships(
                    session,
                    snapshot_id=snapshot.entity_id,
                    items=items,
                )
            return

        for raw_item in payload.get("items", []):
            if not isinstance(raw_item, dict):
                continue
            block_id = str(raw_item["block_id"])
            if await session.get(AnsichContentBlockRow, block_id) is None:
                ordinal = int(raw_item["ordinal"])
                if await session.get(AnsichContextSnapshotMissingItemRow, (snapshot.entity_id, ordinal)) is None:
                    session.add(
                        AnsichContextSnapshotMissingItemRow(
                            snapshot_id=snapshot.entity_id,
                            ordinal=ordinal,
                            expected_content_block_id=block_id,
                            channel=str(raw_item["channel"]),
                            role=raw_item.get("role") if isinstance(raw_item.get("role"), str) else None,
                            name=raw_item.get("name") if isinstance(raw_item.get("name"), str) else None,
                            message_id=raw_item.get("message_id") if isinstance(raw_item.get("message_id"), str) else None,
                            source_identity=raw_item.get("source_identity") if isinstance(raw_item.get("source_identity"), str) else None,
                            visible_bytes=int(raw_item["visible_bytes"]),
                            estimated_tokens=int(raw_item["estimated_tokens"]),
                            metadata_json=dict(raw_item.get("metadata", {})),
                        )
                    )
                snapshot.status = "incomplete"
                continue
            ordinal = int(raw_item["ordinal"])
            if await session.get(AnsichContextSnapshotItemRow, (snapshot.entity_id, ordinal)) is None:
                session.add(
                    AnsichContextSnapshotItemRow(
                        snapshot_id=snapshot.entity_id,
                        ordinal=ordinal,
                        channel=str(raw_item["channel"]),
                        role=raw_item.get("role") if isinstance(raw_item.get("role"), str) else None,
                        name=raw_item.get("name") if isinstance(raw_item.get("name"), str) else None,
                        message_id=raw_item.get("message_id") if isinstance(raw_item.get("message_id"), str) else None,
                        source_identity=raw_item.get("source_identity") if isinstance(raw_item.get("source_identity"), str) else None,
                        content_block_id=block_id,
                        visible_bytes=int(raw_item["visible_bytes"]),
                        estimated_tokens=int(raw_item["estimated_tokens"]),
                        metadata_json=dict(raw_item.get("metadata", {})),
                    )
                )
            if (
                await session.get(
                    AnsichContextSnapshotBlockMembershipRow,
                    (snapshot.entity_id, ordinal),
                )
                is None
            ):
                session.add(
                    AnsichContextSnapshotBlockMembershipRow(
                        snapshot_id=snapshot.entity_id,
                        ordinal=ordinal,
                        content_block_id=block_id,
                    )
                )
        await self._link_attempt_context_snapshot(
            session,
            attempt=attempt,
            snapshot_id=snapshot.entity_id,
        )

    @staticmethod
    async def _link_attempt_context_snapshot(
        session: AsyncSession,
        *,
        attempt: AnsichLlmAttemptRow,
        snapshot_id: str,
    ) -> None:
        attempt.context_snapshot_id = snapshot_id
        if attempt.step_id is None:
            return
        step = await session.get(AnsichStepRow, attempt.step_id)
        if step is not None and step.effective_attempt_no == attempt.attempt_no:
            step.effective_context_snapshot_id = snapshot_id

    async def _project_context_compression(
        self,
        session: AsyncSession,
        observation: ObservationEnvelope,
    ) -> None:
        if observation.payload is None:
            raise ValueError("context.compressed is missing payload")
        payload = observation.payload
        summary_block_id = payload.get("summary_block_id")
        if not isinstance(summary_block_id, str):
            raise ValueError("context.compressed is missing summary_block_id")
        if await session.get(AnsichContentBlockRow, summary_block_id) is None:
            raise _ProjectionDependencyPending(f"summary content block has not been projected: {summary_block_id}")
        raw_items = payload.get("items", [])
        if not isinstance(raw_items, list):
            raise ValueError("context.compressed items must be a list")
        compression_status = payload.get("status", "complete")
        if compression_status not in {"complete", "incomplete"}:
            raise ValueError(f"invalid context compression status: {compression_status}")
        block_ids = {str(item["block_id"]) for item in raw_items if isinstance(item, dict) and isinstance(item.get("block_id"), str)}
        available_block_ids = set((await session.execute(select(AnsichContentBlockRow.entity_id).where(AnsichContentBlockRow.entity_id.in_(block_ids)))).scalars()) if block_ids else set()
        missing_block_ids = block_ids - available_block_ids
        if missing_block_ids:
            raise _ProjectionDependencyPending("compression content blocks have not been projected: " + ",".join(sorted(missing_block_ids)))

        if await session.get(AnsichEntityRow, observation.subject_id) is None:
            session.add(
                AnsichEntityRow(
                    entity_id=observation.subject_id,
                    entity_type="context_compression",
                    discovered_obs_id=observation.obs_id,
                )
            )
        compression = await session.get(
            AnsichContextCompressionRow,
            observation.subject_id,
        )
        if compression is None:
            compression = AnsichContextCompressionRow(
                entity_id=observation.subject_id,
                task_id=observation.task_id,
                operation_id=(payload.get("summary_operation_id") if isinstance(payload.get("summary_operation_id"), str) else None),
                summary_block_id=summary_block_id,
                before_tokens=int(payload["before_tokens"]),
                after_tokens=int(payload["after_tokens"]),
                before_visible_bytes=int(payload.get("before_visible_bytes", 0)),
                after_visible_bytes=int(payload.get("after_visible_bytes", 0)),
                algorithm=str(payload["algorithm"]),
                algorithm_version=str(payload["algorithm_version"]),
                source_obs_id=observation.obs_id,
                status=cast(Literal["complete", "incomplete"], compression_status),
            )
            session.add(compression)
            await session.flush()

        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                raise ValueError("context.compressed item must be an object")
            disposition = raw_item.get("disposition")
            if disposition not in {"source", "preserved", "removed"}:
                raise ValueError(f"invalid context compression disposition: {disposition}")
            block_id = raw_item.get("block_id")
            if not isinstance(block_id, str):
                raise ValueError("context.compressed item is missing block_id")
            ordinal = int(raw_item["ordinal"])
            item_key = (compression.entity_id, disposition, ordinal)
            existing_item = await session.get(
                AnsichContextCompressionItemRow,
                item_key,
            )
            if existing_item is None:
                session.add(
                    AnsichContextCompressionItemRow(
                        compression_id=compression.entity_id,
                        disposition=disposition,
                        ordinal=ordinal,
                        block_id=block_id,
                    )
                )
            elif existing_item.block_id != block_id:
                raise ValueError("context compression membership conflicts with existing ordinal")
            if disposition != "source" or block_id == summary_block_id:
                continue
            derivation_key = (summary_block_id, block_id, "compressed")
            if await session.get(AnsichContentBlockDerivationRow, derivation_key) is None:
                session.add(
                    AnsichContentBlockDerivationRow(
                        derived_block_id=summary_block_id,
                        source_block_id=block_id,
                        transform_kind="compressed",
                        transform_version=str(payload["algorithm_version"]),
                        source_role="source",
                        ordinal=ordinal,
                        established_obs_id=observation.obs_id,
                    )
                )

    async def _project_scopes(self, session: AsyncSession, observation: ObservationEnvelope) -> None:
        if observation.payload is None:
            return
        scopes = (
            ("owner", "owner", observation.payload.get("owner_id")),
            ("thread", "conversation", observation.payload.get("thread_id")),
            (
                "workspace",
                "execution_workspace",
                observation.payload.get("workspace_ref"),
            ),
            (
                "sandbox",
                "sandbox_boundary",
                observation.payload.get("sandbox_ref"),
            ),
            (
                "authorization",
                "auth_context",
                observation.payload.get("authorization_ref"),
            ),
            (
                "external_origin",
                "trigger_origin",
                observation.payload.get("external_origin_ref"),
            ),
        )
        for scope_kind, relation_role, raw_scope_value in scopes:
            if not isinstance(raw_scope_value, str) or not raw_scope_value:
                continue
            external_ref_hash = scope_reference_hash(scope_kind, raw_scope_value)
            scope = await session.scalar(
                select(AnsichScopeRow).where(
                    AnsichScopeRow.scope_kind == scope_kind,
                    AnsichScopeRow.external_ref_hash == external_ref_hash,
                )
            )
            if scope is None:
                scope_id = scope_entity_id(scope_kind, external_ref_hash)
                session.add(
                    AnsichEntityRow(
                        entity_id=scope_id,
                        entity_type="scope",
                        discovered_obs_id=observation.obs_id,
                    )
                )
                scope = AnsichScopeRow(
                    entity_id=scope_id,
                    scope_kind=scope_kind,
                    scope_value=None,
                    external_ref_hash=external_ref_hash,
                    display_label=scope_display_label(scope_kind, raw_scope_value),
                    parent_scope_id=None,
                    created_obs_id=observation.obs_id,
                )
                session.add(scope)
                await session.flush()
            relation = await session.scalar(
                select(AnsichRelationRow).where(
                    AnsichRelationRow.subject_id == observation.task_id,
                    AnsichRelationRow.predicate == "within_scope",
                    AnsichRelationRow.object_id == scope.entity_id,
                )
            )
            if relation is None:
                relation = AnsichRelationRow(
                    relation_id=new_id(),
                    subject_id=observation.task_id,
                    predicate="within_scope",
                    object_id=scope.entity_id,
                    asserted_obs_id=observation.obs_id,
                    relation_role=relation_role,
                    inherited_from_task_id=None,
                )
                session.add(relation)
                await session.flush()
            elif relation.relation_role not in {None, relation_role}:
                raise ValueError("within_scope relation role conflicts with existing edge")
            elif relation.relation_role is None:
                relation.relation_role = relation_role
            evidence = await session.get(
                AnsichRelationEvidenceRow,
                (relation.relation_id, observation.obs_id),
            )
            if evidence is None:
                session.add(
                    AnsichRelationEvidenceRow(
                        relation_id=relation.relation_id,
                        obs_id=observation.obs_id,
                        ordinal=0,
                    )
                )

    #: Metrics whose monotonic growth is worth tracking as a leak signal. Only
    #: these drive ``consecutive_growth_count`` / ``growth_started_at``; every
    #: other metric keeps its latest value and window minimum without a trend.
    _GROWTH_TRACKED_METRICS = frozenset({"fd_open"})

    async def _project_environment(
        self,
        session: AsyncSession,
        observation: ObservationEnvelope,
    ) -> None:
        """Materialize one ``environment.sampled`` Observation.

        Writes at most three rows: the ``(Scope, environment_scope)`` coverage
        declaration, one current-state row per metric for continuous coverage,
        and one per-tool-call row for ``per_command`` coverage. Every write is
        replay-safe — a same-obs redelivery and a late sample are both no-ops,
        so ``rebuild_projections()`` reconstructs identical rows.
        """

        from ansich.environment import EnvironmentSamplePayload

        # strict=False: producers serialize the window datetimes as ISO strings.
        payload = EnvironmentSamplePayload.model_validate(observation.payload, strict=False)
        scope_id = observation.subject_id
        if await session.get(AnsichEntityRow, scope_id) is None:
            raise _ProjectionDependencyPending(f"environment sample {observation.obs_id} is waiting for Scope {scope_id}")

        coverage = await session.get(AnsichEnvironmentCoverageRow, (scope_id, payload.environment_scope), with_for_update=True)
        if coverage is None:
            session.add(
                AnsichEnvironmentCoverageRow(
                    scope_id=scope_id,
                    environment_scope=payload.environment_scope,
                    coverage=payload.coverage,
                    provider=payload.provider,
                    as_of=observation.occurred_at,
                    last_obs_id=observation.obs_id,
                    updated_at=observation.recorded_at,
                )
            )
        elif coverage.last_obs_id != observation.obs_id and observation.occurred_at >= _as_utc(coverage.as_of):
            coverage.coverage = payload.coverage
            coverage.provider = payload.provider
            coverage.as_of = observation.occurred_at
            coverage.last_obs_id = observation.obs_id
            coverage.updated_at = observation.recorded_at

        if payload.coverage == "per_command":
            existing = await session.get(AnsichToolEnvSampleRow, payload.tool_call_id)
            if existing is None:
                metrics = payload.metrics
                session.add(
                    AnsichToolEnvSampleRow(
                        tool_call_id=payload.tool_call_id,
                        task_id=observation.task_id,
                        scope_id=scope_id,
                        io_read_bytes=(metrics["io_read_bytes"].value if "io_read_bytes" in metrics else None),
                        io_write_bytes=(metrics["io_write_bytes"].value if "io_write_bytes" in metrics else None),
                        fd_peak=(metrics["fd_open"].value if "fd_open" in metrics else None),
                        sample_count=payload.window.sample_count,
                        started_at=payload.window.started_at,
                        ended_at=payload.window.ended_at,
                        obs_id=observation.obs_id,
                    )
                )
            # A per-command sample describes one tool call's own window, not the
            # Scope's continuous trend, so it never moves the state row.
            return

        if payload.coverage == "uninstrumented":
            return

        for metric, value in payload.metrics.items():
            # Lock the row BEFORE reading it: sibling projections of the same
            # Scope can land on this row concurrently and every branch below is
            # a read-modify-write, so an unlocked read would lose an update
            # under Postgres READ COMMITTED. Same discipline as
            # _upsert_high_water_contribution; FOR UPDATE is a no-op on SQLite.
            row = await session.get(AnsichEnvironmentStateRow, (scope_id, payload.environment_scope, metric), with_for_update=True)
            if row is None:
                session.add(
                    AnsichEnvironmentStateRow(
                        scope_id=scope_id,
                        environment_scope=payload.environment_scope,
                        metric=metric,
                        latest_value=value.value,
                        limit_value=value.limit,
                        as_of=observation.occurred_at,
                        window_started_at=payload.window.started_at,
                        window_min_value=value.value,
                        sample_count=payload.window.sample_count,
                        consecutive_growth_count=0,
                        growth_started_at=None,
                        last_obs_id=observation.obs_id,
                        provider=payload.provider,
                        updated_at=observation.recorded_at,
                    )
                )
                continue
            if row.last_obs_id == observation.obs_id or observation.occurred_at < _as_utc(row.as_of):
                # Same-obs redelivery, or a sample older than what the row
                # already reflects: no-op, so a replay is deterministic.
                continue
            if metric in self._GROWTH_TRACKED_METRICS and value.value > row.latest_value:
                if row.consecutive_growth_count == 0:
                    row.growth_started_at = observation.occurred_at
                row.consecutive_growth_count += 1
                # A continuing run keeps its running minimum, which — because
                # every sample in the run is strictly larger than the previous
                # one — is exactly the value the run started from.
                row.window_min_value = min(row.window_min_value, value.value)
            else:
                row.consecutive_growth_count = 0
                row.growth_started_at = None
                # The streak broke, so re-anchor the baseline to this sample.
                # Keeping a lifetime minimum here (fd=50 at container start,
                # steady working set 400) would make the leak rule's
                # ``latest - window_min`` compare against a dip nobody is
                # growing away from any more, and any later six-sample wobble
                # would read as suspected. Semantics after this reset:
                # "minimum since the current growth run began", derived only
                # from this row's own ordered inputs, so a replay is
                # deterministic.
                row.window_min_value = value.value
            row.latest_value = value.value
            row.limit_value = value.limit
            row.as_of = observation.occurred_at
            row.sample_count += payload.window.sample_count
            row.last_obs_id = observation.obs_id
            row.provider = payload.provider
            row.updated_at = observation.recorded_at

    async def _project_safety(
        self,
        session: AsyncSession,
        observation: ObservationEnvelope,
    ) -> None:
        if observation.kind == "scope.snapshotted":
            await self._project_scope_snapshot(session, observation)
        elif observation.kind.startswith("authorization."):
            await self._project_authorization_snapshot(session, observation)
        elif observation.kind.startswith("effect."):
            await self._project_tool_effect(session, observation)

    async def _project_scope_snapshot(
        self,
        session: AsyncSession,
        observation: ObservationEnvelope,
    ) -> None:
        payload = observation.payload or {}
        scope = ScopeDescriptor.model_validate(payload.get("scope"), strict=False)
        if scope.created_obs_id != observation.obs_id:
            raise ValueError("Scope created_obs_id must identify scope.snapshotted")
        if scope.parent_scope_id is not None and await session.get(AnsichScopeRow, scope.parent_scope_id) is None:
            raise _ProjectionDependencyPending(f"Scope {scope.scope_id} is waiting for parent {scope.parent_scope_id}")
        entity = await session.get(AnsichEntityRow, scope.scope_id)
        row = await session.get(AnsichScopeRow, scope.scope_id)
        if entity is None:
            session.add(
                AnsichEntityRow(
                    entity_id=scope.scope_id,
                    entity_type="scope",
                    discovered_obs_id=observation.obs_id,
                )
            )
            # No ORM relationship() links AnsichEntityRow to AnsichScopeRow, so
            # SQLAlchemy's flush does not guarantee this INSERT precedes the
            # FK-dependent one below; flush explicitly to enforce the order.
            await session.flush()
        if row is None:
            row = AnsichScopeRow(
                entity_id=scope.scope_id,
                scope_kind=scope.scope_kind,
                scope_value=None,
                external_ref_hash=scope.external_ref_hash,
                display_label=scope.display_label,
                parent_scope_id=scope.parent_scope_id,
                created_obs_id=observation.obs_id,
            )
            session.add(row)
        elif (
            row.scope_kind,
            row.external_ref_hash,
            row.display_label,
            row.parent_scope_id,
        ) != (
            scope.scope_kind,
            scope.external_ref_hash,
            scope.display_label,
            scope.parent_scope_id,
        ):
            raise ValueError("Scope identity conflicts with existing descriptor")
        await session.flush()

        relation_role = payload.get("relation_role")
        if not isinstance(relation_role, str):
            return
        subject_id = payload.get("within_scope_subject_id", observation.task_id)
        if not isinstance(subject_id, str):
            raise ValueError("scope.snapshotted within_scope subject must be a string")
        if await session.get(AnsichEntityRow, subject_id) is None:
            raise _ProjectionDependencyPending(f"Scope {scope.scope_id} is waiting for subject {subject_id}")
        inherited_from = payload.get("inherited_from_task_id")
        if inherited_from is not None and not isinstance(inherited_from, str):
            raise ValueError("scope inherited_from_task_id must be a string")
        relation = await session.scalar(
            select(AnsichRelationRow).where(
                AnsichRelationRow.subject_id == subject_id,
                AnsichRelationRow.predicate == "within_scope",
                AnsichRelationRow.object_id == scope.scope_id,
            )
        )
        if relation is None:
            relation = AnsichRelationRow(
                relation_id=new_id(),
                subject_id=subject_id,
                predicate="within_scope",
                object_id=scope.scope_id,
                asserted_obs_id=observation.obs_id,
                relation_role=relation_role,
                inherited_from_task_id=inherited_from,
            )
            session.add(relation)
            await session.flush()
        elif (
            relation.relation_role,
            relation.inherited_from_task_id,
        ) != (relation_role, inherited_from):
            raise ValueError("within_scope relation conflicts with existing role")
        if (
            await session.get(
                AnsichRelationEvidenceRow,
                (relation.relation_id, observation.obs_id),
            )
            is None
        ):
            session.add(
                AnsichRelationEvidenceRow(
                    relation_id=relation.relation_id,
                    obs_id=observation.obs_id,
                    ordinal=0,
                )
            )

    async def _project_authorization_snapshot(
        self,
        session: AsyncSession,
        observation: ObservationEnvelope,
    ) -> None:
        snapshot = AuthorizationSnapshot.model_validate((observation.payload or {}).get("snapshot"), strict=False)
        if await session.get(AnsichToolCallRow, snapshot.tool_call_id) is None:
            raise _ProjectionDependencyPending(f"AuthorizationSnapshot {snapshot.snapshot_id} is waiting for ToolCall")
        referenced_scope_ids = (
            *snapshot.principal_scope_ids,
            *snapshot.resource_scope_ids,
            *(permission.scope_id for permission in snapshot.effective_permissions if permission.scope_id is not None),
        )
        for scope_id in dict.fromkeys(referenced_scope_ids):
            if await session.get(AnsichScopeRow, scope_id) is None:
                raise _ProjectionDependencyPending(f"AuthorizationSnapshot {snapshot.snapshot_id} is waiting for Scope {scope_id}")

        entity = await session.get(AnsichEntityRow, snapshot.snapshot_id)
        row = await session.get(AnsichAuthorizationSnapshotRow, snapshot.snapshot_id)
        if entity is None:
            session.add(
                AnsichEntityRow(
                    entity_id=snapshot.snapshot_id,
                    entity_type="authorization_snapshot",
                    discovered_obs_id=observation.obs_id,
                )
            )
            # No ORM relationship() links AnsichEntityRow to
            # AnsichAuthorizationSnapshotRow, so SQLAlchemy's flush does not
            # guarantee this INSERT precedes the FK-dependent one below;
            # flush explicitly to enforce the order (see root-cause note in
            # ansich/docs/plans/human-followups.md).
            await session.flush()
        if row is None:
            row = AnsichAuthorizationSnapshotRow(
                snapshot_id=snapshot.snapshot_id,
                tool_call_id=snapshot.tool_call_id,
                policy_id=snapshot.policy_id,
                policy_version=snapshot.policy_version,
                policy_hash=snapshot.policy_hash,
                decision=snapshot.decision,
                details_available=snapshot.details_available,
                reason_codes_json=list(snapshot.reason_codes),
                evaluated_at=snapshot.evaluated_at,
                evaluated_obs_id=observation.obs_id,
                payload_id=None,
            )
            session.add(row)
        elif (
            row.tool_call_id,
            row.policy_id,
            row.policy_version,
            row.policy_hash,
            row.decision,
            row.details_available,
            tuple(row.reason_codes_json),
            _as_utc(row.evaluated_at),
        ) != (
            snapshot.tool_call_id,
            snapshot.policy_id,
            snapshot.policy_version,
            snapshot.policy_hash,
            snapshot.decision,
            snapshot.details_available,
            snapshot.reason_codes,
            snapshot.evaluated_at,
        ):
            raise ValueError("AuthorizationSnapshot conflicts with existing immutable row")
        await session.flush()

        for scope_role, scope_ids in (
            ("principal", snapshot.principal_scope_ids),
            ("resource", snapshot.resource_scope_ids),
        ):
            for ordinal, scope_id in enumerate(scope_ids):
                key = (snapshot.snapshot_id, scope_role, ordinal)
                existing_scope = await session.get(AnsichAuthorizationScopeRow, key)
                if existing_scope is None:
                    session.add(
                        AnsichAuthorizationScopeRow(
                            snapshot_id=snapshot.snapshot_id,
                            scope_role=scope_role,
                            ordinal=ordinal,
                            scope_id=scope_id,
                        )
                    )
                elif existing_scope.scope_id != scope_id:
                    raise ValueError("Authorization scope ordinal is immutable")
        for ordinal, permission in enumerate(snapshot.effective_permissions):
            key = (snapshot.snapshot_id, ordinal)
            existing_permission = await session.get(AnsichAuthorizationPermissionRow, key)
            permission_value = (
                permission.resource,
                permission.action,
                permission.scope_id,
                permission.effect,
            )
            if existing_permission is None:
                session.add(
                    AnsichAuthorizationPermissionRow(
                        snapshot_id=snapshot.snapshot_id,
                        ordinal=ordinal,
                        resource=permission.resource,
                        action=permission.action,
                        scope_id=permission.scope_id,
                        effect=permission.effect,
                    )
                )
            elif (
                existing_permission.resource,
                existing_permission.action,
                existing_permission.scope_id,
                existing_permission.effect,
            ) != permission_value:
                raise ValueError("Authorization permission ordinal is immutable")

        binding = await session.get(
            AnsichToolCallAuthorizationRow,
            (snapshot.tool_call_id, snapshot.snapshot_id),
        )
        if binding is None:
            session.add(
                AnsichToolCallAuthorizationRow(
                    tool_call_id=snapshot.tool_call_id,
                    snapshot_id=snapshot.snapshot_id,
                    relation_obs_id=observation.obs_id,
                )
            )
        elif observation.kind != "authorization.evaluated":
            binding.relation_obs_id = observation.obs_id

    async def _project_tool_effect(
        self,
        session: AsyncSession,
        observation: ObservationEnvelope,
    ) -> None:
        effect = ToolEffect.model_validate((observation.payload or {}).get("effect"), strict=False)
        if await session.get(AnsichToolCallRow, effect.tool_call_id) is None:
            raise _ProjectionDependencyPending(f"Effect {effect.effect_id} is waiting for ToolCall")
        if effect.scope_id is not None and await session.get(AnsichScopeRow, effect.scope_id) is None:
            raise _ProjectionDependencyPending(f"Effect {effect.effect_id} is waiting for Scope {effect.scope_id}")
        entity = await session.get(AnsichEntityRow, effect.effect_id)
        row = await session.get(AnsichToolEffectRow, effect.effect_id)
        if entity is None:
            session.add(
                AnsichEntityRow(
                    entity_id=effect.effect_id,
                    entity_type="effect",
                    discovered_obs_id=observation.obs_id,
                )
            )
            # No ORM relationship() links AnsichEntityRow to
            # AnsichToolEffectRow, so SQLAlchemy's flush does not guarantee
            # this INSERT precedes the FK-dependent one below; flush
            # explicitly to enforce the order.
            await session.flush()
        effect_value = (
            effect.tool_call_id,
            effect.effect_class,
            effect.phase,
            effect.scope_id,
            effect.target_hash,
            effect.target_preview,
            effect.fidelity_class,
            effect.source_obs_id,
            effect.result_metadata,
        )
        if row is None:
            session.add(
                AnsichToolEffectRow(
                    effect_id=effect.effect_id,
                    tool_call_id=effect.tool_call_id,
                    effect_class=effect.effect_class,
                    phase=effect.phase,
                    scope_id=effect.scope_id,
                    target_hash=effect.target_hash,
                    target_preview=effect.target_preview,
                    fidelity_class=effect.fidelity_class,
                    source_obs_id=effect.source_obs_id,
                    result_metadata_json=effect.result_metadata,
                )
            )
        elif (
            row.tool_call_id,
            row.effect_class,
            row.phase,
            row.scope_id,
            row.target_hash,
            row.target_preview,
            row.fidelity_class,
            row.source_obs_id,
            row.result_metadata_json,
        ) != effect_value:
            raise ValueError("ToolEffect conflicts with existing immutable row")

    async def _project_evaluation(
        self,
        session: AsyncSession,
        observation: ObservationEnvelope,
    ) -> None:
        # _claim_projection_job already hydrates an externalized payload from
        # ansich_payloads before handing the envelope over, so this projector
        # always sees the decoded record. It re-validates the subject/task
        # cross-checks because that hydration uses model_copy, which does not
        # re-run the envelope validators.
        if observation.payload is None:
            raise ValueError("evaluation.recorded requires an inline decoded payload")
        record = EvaluationRecord.model_validate(observation.payload.get("evaluation"), strict=False)
        if record.subject_type != observation.subject_type or record.subject_id != observation.subject_id:
            raise ValueError("evaluation payload subject must match the Observation subject")
        if record.task_id != observation.task_id:
            raise ValueError("evaluation payload task must match the Observation task")
        if await session.get(AnsichEntityRow, record.subject_id) is None:
            raise _ProjectionDependencyPending(f"Evaluation {observation.obs_id} is waiting for subject Entity {record.subject_id}")

        step_row: AnsichStepRow | None = None
        if record.dimension == "earliest_erroneous_step":
            # The record validator already guarantees a Task subject plus a
            # non-empty Step id in ``actual``; ownership is a projection-time
            # fact (R10).
            step_row = await session.get(AnsichStepRow, record.actual)
            if step_row is None:
                raise _ProjectionDependencyPending(f"Evaluation {observation.obs_id} is waiting for Step {record.actual}")
            if step_row.task_id != record.task_id:
                raise ValueError("earliest erroneous step must belong to the evaluated Task")

        authority_class = _evaluation_authority_class(record)
        await self._upsert_evaluation_index(
            session,
            observation,
            record,
            authority_class=authority_class,
        )

        if record.dimension in _EVALUATION_QUALITY_DIMENSIONS:
            value: dict[str, object] = {
                "verdict": record.verdict,
                "score": record.score,
                "scale": None if record.scale is None else record.scale.model_dump(mode="json"),
                "evaluation_kind": record.evaluation_kind,
                "cohort_key": record.cohort_key,
                "suite": record.suite,
            }
        elif step_row is not None:
            value = {
                "step_id": step_row.entity_id,
                "step_seq": step_row.step_seq,
                "verdict": record.verdict,
            }
        else:
            # ``custom`` carries no named semantics, so it stays an indexed
            # observation instead of becoming a Belief claim.
            return

        await self._persist_assessment(
            session,
            Assessment(
                subject_id=record.subject_id,
                field_name=f"quality.{record.dimension}",
                value=value,
                as_of=record.occurred_at,
                asserted_at=datetime.now(UTC),
                assessor=record.assessor,
                config_hash=_EVALUATION_PROJECTOR_CONFIG_HASH,
                authority_class=authority_class,
                fidelity_class=record.fidelity_class,
                evidence=(EvidenceRef(obs_id=observation.obs_id),),
            ),
        )

        if record.subject_type != "task" or record.dimension not in _EVALUATION_QUALITY_DIMENSIONS:
            return
        release_id = await session.scalar(
            select(AnsichRelationRow.object_id).where(
                AnsichRelationRow.subject_id == record.task_id,
                AnsichRelationRow.predicate == "executed_by",
            )
        )
        if release_id is None:
            # A Task without a starting AgentRelease binding still gets its
            # index row and Belief; only the release rollup is skipped (R9).
            return
        # The rollup reads the current Belief this projection just resolved, so
        # make that write visible instead of relying on autoflush ordering.
        await session.flush()
        await self._recompute_release_quality_stats(
            session,
            release_id=release_id,
            cohort_key=record.cohort_key or "",
            dimension=record.dimension,
        )

    @staticmethod
    async def _upsert_evaluation_index(
        session: AsyncSession,
        observation: ObservationEnvelope,
        record: EvaluationRecord,
        *,
        authority_class: AuthorityClass,
    ) -> None:
        values: dict[str, object] = {
            "subject_type": record.subject_type,
            "subject_id": record.subject_id,
            "task_id": record.task_id,
            "evaluation_kind": record.evaluation_kind,
            "dimension": record.dimension,
            "verdict": record.verdict,
            "score": record.score,
            "scale_min": None if record.scale is None else record.scale.min,
            "scale_max": None if record.scale is None else record.scale.max,
            "scale_higher_is_better": None if record.scale is None else record.scale.higher_is_better,
            "assessor_name": record.assessor.name,
            "assessor_version": record.assessor.version,
            "authority_class": authority_class,
            # The Observation column is Literal["hard"]; the evaluation's real
            # fidelity only exists inside the payload.
            "fidelity_class": record.fidelity_class,
            "cohort_key": record.cohort_key,
            "suite_id": record.suite,
            "suite_version": record.suite_version,
            "case_id": record.case_id,
            "occurred_at": record.occurred_at,
            "projector_version": _EVALUATION_PROJECTOR_VERSION,
        }
        row = await session.get(AnsichEvaluationIndexRow, observation.obs_id)
        if row is None:
            session.add(
                AnsichEvaluationIndexRow(
                    evaluation_obs_id=observation.obs_id,
                    **values,
                )
            )
            await session.flush()
            return
        stored = {name: getattr(row, name) for name in values}
        stored["occurred_at"] = _as_utc(row.occurred_at)
        if stored != {**values, "occurred_at": _as_utc(record.occurred_at)}:
            raise ValueError("Evaluation index row conflicts with an existing projection")

    async def _recompute_release_quality_stats(
        self,
        session: AsyncSession,
        *,
        release_id: str,
        cohort_key: str,
        dimension: str,
    ) -> None:
        """Rebuild one ``(release, cohort, dimension)`` cell from scratch.

        The cell's population is every Task bound to the release that carries
        an index row in this cohort and dimension; each such Task contributes
        exactly one sample, taken from its CURRENT ``quality.<dimension>``
        Belief so retained conflicting assertions never double-count.
        """

        # Lock the cell BEFORE reading its inputs. Evaluations for different
        # Tasks of one release are independent projection jobs that separate
        # leased workers claim concurrently (_claim_projection_job uses
        # skip_locked), yet they all read-modify-write this single
        # release-scoped row. Under Postgres READ COMMITTED an unlocked reader
        # could load the index rows before a peer commits its own and then
        # overwrite the cell with an aggregate that excludes it — a lost update
        # that a single-loop replay would not reproduce. Locking first makes the
        # second worker block until the first commits, and READ COMMITTED then
        # gives its later statements the committed inputs. Locking after the
        # read would leave exactly the same window open. FOR UPDATE is a no-op
        # on SQLite, which has a single writer anyway.
        cell = await session.scalar(
            select(AnsichReleaseQualityStatsRow)
            .where(
                AnsichReleaseQualityStatsRow.release_id == release_id,
                AnsichReleaseQualityStatsRow.cohort_key == cohort_key,
                AnsichReleaseQualityStatsRow.dimension == dimension,
            )
            .with_for_update()
        )
        release_task_ids = select(AnsichRelationRow.subject_id).where(
            AnsichRelationRow.predicate == "executed_by",
            AnsichRelationRow.object_id == release_id,
        )
        index_rows = list(
            (
                await session.execute(
                    select(
                        AnsichEvaluationIndexRow.subject_id,
                        AnsichEvaluationIndexRow.occurred_at,
                    )
                    .where(
                        AnsichEvaluationIndexRow.subject_type == "task",
                        AnsichEvaluationIndexRow.subject_id.in_(release_task_ids),
                        AnsichEvaluationIndexRow.dimension == dimension,
                        func.coalesce(AnsichEvaluationIndexRow.cohort_key, "") == cohort_key,
                    )
                    # Deterministic tiebreak for the retained scale below.
                    .order_by(AnsichEvaluationIndexRow.evaluation_obs_id)
                )
            ).all()
        )

        field_name = f"quality.{dimension}"
        as_of: datetime | None = None
        seen_task_ids: set[str] = set()
        verdicts: list[str | None] = []
        scores: list[float] = []
        scales: list[tuple[float | None, float | None, bool | None]] = []
        for task_id, occurred_at in index_rows:
            occurred = _as_utc(occurred_at)
            as_of = occurred if as_of is None else max(as_of, occurred)
            if task_id in seen_task_ids:
                continue
            seen_task_ids.add(task_id)
            current = await session.get(AnsichCurrentBeliefRow, (task_id, field_name))
            if current is None:
                continue
            assertion = await session.get(AnsichBeliefAssertionRow, current.assertion_id)
            if assertion is None:
                continue
            selected = assertion.value_json or {}
            verdict = selected.get("verdict")
            verdicts.append(verdict if isinstance(verdict, str) else None)
            score = selected.get("score")
            scale = selected.get("scale")
            if isinstance(score, int | float) and not isinstance(score, bool) and isinstance(scale, dict):
                scores.append(float(score))
                key = (scale.get("min"), scale.get("max"), scale.get("higher_is_better"))
                if key not in scales:
                    scales.append(key)

        if not verdicts or as_of is None:
            # Nothing left to aggregate: the cell must not survive as a stale
            # read model.
            if cell is not None:
                await session.delete(cell)
            return

        # Scores on different scales are not commensurable; keep the counts and
        # the first observed scale, but refuse to publish a mixed-scale sum.
        mixed_scales = len(scales) > 1
        cell_values: dict[str, object] = {
            "assessed_count": len(verdicts),
            "pass_count": sum(1 for verdict in verdicts if verdict == "pass"),
            "fail_count": sum(1 for verdict in verdicts if verdict == "fail"),
            "partial_count": sum(1 for verdict in verdicts if verdict == "partial"),
            "score_sum": None if mixed_scales or not scores else float(sum(scores)),
            "score_count": 0 if mixed_scales or not scores else len(scores),
            "scale_min": scales[0][0] if scales else None,
            "scale_max": scales[0][1] if scales else None,
            # The retained scale is the full triple the mixed-scale check keys
            # on; storing only the range would let a comparison treat opposite
            # polarities as one scale.
            "scale_higher_is_better": scales[0][2] if scales else None,
            "as_of": as_of,
            "projector_version": _EVALUATION_PROJECTOR_VERSION,
        }
        if cell is None:
            # A row that does not exist yet cannot be locked, so two concurrent
            # first writers can still both reach this insert. The composite
            # primary key makes one of them lose with an IntegrityError, which
            # the job machinery treats as an ordinary retryable projection error
            # (attempts < projector_max_attempts leaves the job pending). The
            # retry finds the committed row, takes the lock above, and
            # recomputes over the now-complete inputs, so the race costs one
            # attempt rather than correctness.
            session.add(
                AnsichReleaseQualityStatsRow(
                    release_id=release_id,
                    cohort_key=cohort_key,
                    dimension=dimension,
                    **cell_values,
                )
            )
            await session.flush()
            return
        for column_name, column_value in cell_values.items():
            setattr(cell, column_name, column_value)
