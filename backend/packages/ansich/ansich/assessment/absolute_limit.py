from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from ansich.assessment.base import (
    Assessment,
    AssessorDescriptor,
    EvidenceRef,
    canonical_config_hash,
)
from ansich.budget import TaskBudgetView, assess_budget_health
from ansich.contracts import NamedVersion, UsageDimension
from ansich.usage import AggregationScope, TaskUsageValue

ABSOLUTE_LIMIT_ASSESSOR = AssessorDescriptor(
    name="absolute-limit",
    version="1.0.0",
    input_observation_kinds=("budget.configured", "budget.consumed"),
    output_field="budget_health:*|behavior",
    authority_class="configured_rule",
    fidelity_class="rule",
)
_RUNAWAY_LIMIT_DIMENSIONS = frozenset(
    {
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "steps",
        "wall_time_ms",
    }
)


class AbsoluteLimitAssessmentResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    budget_health: tuple[Assessment, ...]
    behavior: Assessment


def assess_absolute_limits(
    *,
    task_id: str,
    budgets: Sequence[TaskBudgetView],
    usage: Sequence[TaskUsageValue],
    now: datetime,
    usage_complete: bool = True,
    usage_evidence: Mapping[
        tuple[UsageDimension, AggregationScope],
        tuple[str, ...],
    ]
    | None = None,
) -> AbsoluteLimitAssessmentResult:
    usage_by_key = {(item.dimension, item.aggregation_scope): item for item in usage}
    evidence_by_key = usage_evidence or {}
    budget_assessments: list[Assessment] = []
    exceeded: list[tuple[TaskBudgetView, Assessment]] = []
    ordered_budgets = sorted(
        budgets,
        key=lambda item: (item.dimension, item.aggregation_scope, item.entity_id),
    )
    for budget in ordered_budgets:
        key = (budget.dimension, budget.aggregation_scope)
        usage_value = usage_by_key.get(key)
        evidence_ids = evidence_by_key.get(key, ())
        health = assess_budget_health(
            budget,
            usage_value,
            now=now,
            usage_complete=usage_complete,
            usage_evidence_obs_ids=evidence_ids,
        )
        shadow = not budget.enforcement
        value: dict[str, object] = {
            "value": health.value,
            "dimension": budget.dimension,
            "aggregation_scope": budget.aggregation_scope,
            "usage_value": health.usage_value,
            "warning_limit": health.warning_limit,
            "hard_limit": health.hard_limit,
            "overshoot": health.overshoot,
            "enforcement": budget.enforcement,
            "shadow": shadow,
        }
        config_hash = canonical_config_hash(
            {
                "dimension": budget.dimension,
                "aggregation_scope": budget.aggregation_scope,
                "warning_limit": budget.warning_limit,
                "hard_limit": budget.hard_limit,
                "enforcement": budget.enforcement,
                "source_kind": budget.source_kind,
            }
        )
        assessment = Assessment(
            subject_id=task_id,
            field_name=(f"budget_health:{budget.dimension}:{budget.aggregation_scope}"),
            value=value,
            as_of=health.as_of or now,
            asserted_at=now,
            assessor=NamedVersion(
                name=ABSOLUTE_LIMIT_ASSESSOR.name,
                version=ABSOLUTE_LIMIT_ASSESSOR.version,
            ),
            config_hash=config_hash,
            authority_class=ABSOLUTE_LIMIT_ASSESSOR.authority_class,
            fidelity_class=ABSOLUTE_LIMIT_ASSESSOR.fidelity_class,
            evidence=tuple(EvidenceRef(obs_id=obs_id) for obs_id in health.evidence_obs_ids),
        )
        budget_assessments.append(assessment)
        if health.value == "exceeded" and budget.dimension in _RUNAWAY_LIMIT_DIMENSIONS:
            exceeded.append((budget, assessment))

    behavior_evidence: list[EvidenceRef] = []
    seen_obs_ids: set[str] = set()
    for _, assessment in exceeded:
        for evidence in assessment.evidence:
            if evidence.obs_id not in seen_obs_ids:
                behavior_evidence.append(evidence)
                seen_obs_ids.add(evidence.obs_id)
    shadow = bool(exceeded) and all(not budget.enforcement for budget, _ in exceeded)
    behavior_value: dict[str, object] = {
        "value": "runaway" if exceeded else "unassessed",
        "reason": ("absolute_limit" if exceeded else "absolute_limit_not_exceeded"),
        "breaches": [
            {
                "dimension": budget.dimension,
                "aggregation_scope": budget.aggregation_scope,
                "usage_value": assessment.value["usage_value"],
                "hard_limit": budget.hard_limit,
                "overshoot": assessment.value["overshoot"],
                "enforcement": budget.enforcement,
                "shadow": not budget.enforcement,
            }
            for budget, assessment in exceeded
        ],
        "shadow": shadow,
    }
    behavior_as_of = max(
        (assessment.as_of for _, assessment in exceeded),
        default=now,
    )
    behavior = Assessment(
        subject_id=task_id,
        field_name="behavior",
        value=behavior_value,
        as_of=behavior_as_of,
        asserted_at=now,
        assessor=NamedVersion(
            name=ABSOLUTE_LIMIT_ASSESSOR.name,
            version=ABSOLUTE_LIMIT_ASSESSOR.version,
        ),
        config_hash=canonical_config_hash({"budget_config_hashes": [assessment.config_hash for assessment in budget_assessments]}),
        authority_class=ABSOLUTE_LIMIT_ASSESSOR.authority_class,
        fidelity_class=ABSOLUTE_LIMIT_ASSESSOR.fidelity_class,
        evidence=tuple(behavior_evidence),
    )
    return AbsoluteLimitAssessmentResult(
        budget_health=tuple(budget_assessments),
        behavior=behavior,
    )
