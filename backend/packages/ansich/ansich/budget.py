from __future__ import annotations

import hashlib
import math
from collections.abc import Iterable
from datetime import datetime
from typing import Literal, NamedTuple

from pydantic import BaseModel, ConfigDict, Field

from ansich.contracts import NamedVersion, UsageDimension
from ansich.usage import AggregationScope, TaskUsageValue

BudgetSourceKind = Literal["release_default", "runtime_override", "shadow"]


class WallTimeEvidenceRow(NamedTuple):
    """One ``wall_time_ms`` usage contribution, as the evidence rule sees it."""

    source_task_id: str
    source_obs_id: str
    delta: int
    from_heartbeat: bool


def order_wall_time_evidence(rows: Iterable[WallTimeEvidenceRow]) -> tuple[str, ...]:
    """Order ``wall_time_ms`` evidence the way the absolute-limit rule reads it.

    Wall time is the one dimension whose usage is a maximum rather than a sum,
    so it carries two independent measurements of the same quantity: the
    terminal ``budget.consumed`` contribution (Task monotonic clock, once per
    Task) and the heartbeat high-water mark (one collapsed row per
    ``(aggregate, source)`` since P8-M2). Both are retained so a final interval
    after the last heartbeat cannot erase a terminal breach.

    The order is part of that retention contract: terminal contributions first,
    then one heartbeat mark per source Task keyed by source Task id so an
    ancestry fan-out stays stable. Every writer of a
    ``budget_health:wall_time_ms:*`` Belief Assertion must order evidence
    through this function. Two writers with two orders emit two assertions that
    the Belief resolver then separates on ``asserted_at`` — and because the
    terminal-projection writer asserts at ingest wall time while the
    absolute-limit assessor asserts at event time, that turns the stored
    evidence order into a race between two clocks rather than a property of the
    evidence.
    """

    terminal: list[str] = []
    heartbeat: dict[str, tuple[int, str]] = {}
    for row in rows:
        if row.from_heartbeat:
            previous = heartbeat.get(row.source_task_id)
            if previous is None or row.delta >= previous[0]:
                heartbeat[row.source_task_id] = (row.delta, row.source_obs_id)
        else:
            terminal.append(row.source_obs_id)
    return (*terminal, *(obs_id for _, (_, obs_id) in sorted(heartbeat.items())))


class ResolvedBudget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    dimension: UsageDimension
    aggregation_scope: AggregationScope
    warning_limit: int | None = Field(default=None, ge=0)
    hard_limit: int | None = Field(default=None, ge=0)
    enforcement: bool
    source_kind: BudgetSourceKind
    requested_value: int | None = Field(default=None, ge=0)
    effective_value: int = Field(ge=0)


class TaskBudgetView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    entity_id: str
    task_id: str
    dimension: UsageDimension
    aggregation_scope: AggregationScope
    warning_limit: int | None = Field(default=None, ge=0)
    hard_limit: int | None = Field(default=None, ge=0)
    enforcement: bool
    source_kind: BudgetSourceKind
    requested_value: int | None = Field(default=None, ge=0)
    effective_value: int = Field(ge=0)
    configured_obs_id: str


class TaskBudgetsView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    task_id: str
    budgets: tuple[TaskBudgetView, ...]


class BudgetHealthBelief(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    dimension: UsageDimension
    aggregation_scope: AggregationScope
    value: Literal["unknown", "within", "warning", "exceeded"]
    usage_value: int | None = Field(default=None, ge=0)
    warning_limit: int | None = Field(default=None, ge=0)
    hard_limit: int | None = Field(default=None, ge=0)
    overshoot: int | None = Field(default=None, ge=0)
    as_of: datetime | None
    asserted_at: datetime
    source: NamedVersion
    fidelity_class: Literal["rule"] = "rule"
    selected_by: NamedVersion
    evidence_obs_ids: tuple[str, ...]


def budget_health_assessor_version(budget: TaskBudgetView) -> str:
    policy = f"budget-health@1:dimension={budget.dimension}:scope={budget.aggregation_scope}:warning={budget.warning_limit}:hard={budget.hard_limit}:enforcement={budget.enforcement}"
    return f"1:{hashlib.sha256(policy.encode()).hexdigest()[:12]}"


def assess_budget_health(
    budget: TaskBudgetView,
    usage: TaskUsageValue | None,
    *,
    now: datetime,
    usage_complete: bool = True,
    usage_evidence_obs_ids: tuple[str, ...] = (),
) -> BudgetHealthBelief:
    if usage is not None and (usage.dimension != budget.dimension or usage.aggregation_scope != budget.aggregation_scope):
        raise ValueError("usage and budget dimensions/scopes must match")
    selected_by = NamedVersion(
        name="budget-health-state",
        version=budget_health_assessor_version(budget),
    )
    evidence = (budget.configured_obs_id, *usage_evidence_obs_ids)
    usage_value = None if usage is None else usage.value
    if usage is None or not usage_complete:
        value: Literal["unknown", "within", "warning", "exceeded"] = "unknown"
        overshoot = None
    elif budget.hard_limit is not None and usage.value > budget.hard_limit:
        value = "exceeded"
        overshoot = usage.value - budget.hard_limit
    elif budget.warning_limit is not None and usage.value >= budget.warning_limit:
        value = "warning"
        overshoot = 0
    else:
        value = "within"
        overshoot = 0
    return BudgetHealthBelief(
        dimension=budget.dimension,
        aggregation_scope=budget.aggregation_scope,
        value=value,
        usage_value=usage_value,
        warning_limit=budget.warning_limit,
        hard_limit=budget.hard_limit,
        overshoot=overshoot,
        as_of=None if usage is None else usage.as_of,
        asserted_at=now,
        source=NamedVersion(name="budget-health", version="1"),
        selected_by=selected_by,
        evidence_obs_ids=evidence,
    )


def resolve_budget_limit(
    *,
    dimension: UsageDimension,
    release_default: int | None,
    runtime_override: int | None = None,
    minimum: int = 0,
    maximum: int | None = None,
    warning_fraction: float | None = None,
    hard_fraction: float | None = None,
    enforcement: bool,
    aggregation_scope: AggregationScope = "local",
    shadow: bool = False,
) -> ResolvedBudget | None:
    """Resolve one effective limit without depending on a runtime framework."""
    selected = runtime_override if runtime_override is not None else release_default
    if selected is None:
        return None
    if isinstance(selected, bool) or not isinstance(selected, int):
        raise ValueError("budget values must be integers")
    if minimum < 0 or maximum is not None and maximum < minimum:
        raise ValueError("invalid budget clamp bounds")
    effective = max(minimum, selected)
    if maximum is not None:
        effective = min(effective, maximum)

    def threshold(fraction: float | None) -> int | None:
        if fraction is None:
            return None
        if fraction < 0 or fraction > 1:
            raise ValueError("budget fractions must be between zero and one")
        return math.ceil(effective * fraction)

    return ResolvedBudget(
        dimension=dimension,
        aggregation_scope=aggregation_scope,
        warning_limit=threshold(warning_fraction),
        hard_limit=threshold(hard_fraction),
        enforcement=enforcement,
        source_kind=("shadow" if shadow else "runtime_override" if runtime_override is not None else "release_default"),
        requested_value=runtime_override,
        effective_value=effective,
    )
