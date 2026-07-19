from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ansich.contracts import ObservationEnvelope, UsageDimension

AggregationScope = Literal["local", "inclusive"]

_STRUCTURAL_DIMENSION_BY_KIND: dict[str, UsageDimension] = {
    "llm.requested": "llm_attempts",
    "step.started": "steps",
    "tool.issued": "tool_calls_issued",
    "tool.started": "tool_calls_executed",
    "tool.returned_raw": "tool_calls_executed",
    "tool.timed_out": "tool_calls_executed",
    "tool.cancelled": "tool_calls_executed",
    "tool.failed": "tool_calls_executed",
}

_BUDGET_CONSUMED_USAGE_DIMENSIONS: frozenset[UsageDimension] = frozenset({"wall_time_ms", "child_tasks_spawned"})


class UsageContribution(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    task_id: str
    source_task_id: str
    dimension: UsageDimension
    source_obs_id: str
    delta: int = Field(ge=0)
    as_of: datetime


class TaskUsageValue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    dimension: UsageDimension
    aggregation_scope: AggregationScope
    value: int = Field(ge=0)
    as_of: datetime
    complete_through_ingest_seq: int = Field(ge=1)


class TaskUsageView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    task_id: str
    local: tuple[TaskUsageValue, ...]
    inclusive_status: Literal["not_available"] = "not_available"


def usage_contributions_for_observation(
    observation: ObservationEnvelope,
) -> tuple[UsageContribution, ...]:
    """Extract independent local-usage deltas from one durable observation."""
    structural_dimension = _STRUCTURAL_DIMENSION_BY_KIND.get(observation.kind)
    if structural_dimension is not None:
        return (_contribution(observation, structural_dimension, 1),)
    if observation.kind == "budget.consumed" and observation.payload is not None:
        dimension = observation.payload.get("dimension")
        delta = observation.payload.get("delta")
        if dimension in _BUDGET_CONSUMED_USAGE_DIMENSIONS and isinstance(delta, int) and not isinstance(delta, bool) and delta >= 0:
            return (_contribution(observation, dimension, delta),)
    if observation.kind != "llm.responded" or observation.payload is None:
        return ()
    usage = observation.payload.get("usage")
    if not isinstance(usage, dict):
        return ()
    contributions: list[UsageContribution] = []
    for dimension in ("input_tokens", "output_tokens", "total_tokens"):
        value = usage.get(dimension)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            continue
        contributions.append(_contribution(observation, dimension, value))
    return tuple(contributions)


def child_task_contribution_for_tool_started(
    observation: ObservationEnvelope,
    *,
    tool_name: str,
) -> UsageContribution | None:
    """Count an accepted DeerFlow ``task`` tool execution as one child spawn."""
    if observation.kind != "tool.started" or tool_name != "task":
        return None
    return _contribution(observation, "child_tasks_spawned", 1)


def _contribution(
    observation: ObservationEnvelope,
    dimension: UsageDimension,
    delta: int,
) -> UsageContribution:
    return UsageContribution(
        task_id=observation.task_id,
        source_task_id=observation.task_id,
        dimension=dimension,
        source_obs_id=observation.obs_id,
        delta=delta,
        as_of=observation.occurred_at,
    )
