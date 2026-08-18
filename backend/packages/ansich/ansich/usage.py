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

#: Token dimensions an ``llm.responded`` usage payload may report. Both the
#: local usage contributions and the by-model breakdown read exactly these, so
#: the two cannot drift apart.
LLM_TOKEN_USAGE_DIMENSIONS: tuple[UsageDimension, ...] = ("input_tokens", "output_tokens", "total_tokens")

#: Dimensions whose contributions carry a *cumulative* measurement rather than
#: an increment: ``delta`` is the total observed so far for that source Task, so
#: aggregation takes the maximum per source Task and only then sums across
#: sources. Every other dimension is a sum-type delta.
MAX_TYPE_USAGE_DIMENSIONS: frozenset[UsageDimension] = frozenset({"wall_time_ms"})

#: Observation kinds that re-report a max-type dimension on every tick of one
#: Task. Their contributions must be stored as a single high-water mark per
#: ``(aggregate Task, source Task)`` — appending one durable row per tick makes
#: both the write volume and the summary refresh grow with the tick count
#: (phase-8 review followup M2, direction ①).
HIGH_WATER_USAGE_KINDS: frozenset[str] = frozenset({"task.heartbeat"})


class UsageContribution(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    aggregate_task_id: str
    source_task_id: str
    dimension: UsageDimension
    source_obs_id: str
    delta: int = Field(ge=0)
    as_of: datetime

    @property
    def task_id(self) -> str:
        """Compatibility alias for pre-Phase-8 local-only consumers."""

        return self.aggregate_task_id


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
    inclusive: tuple[TaskUsageValue, ...] = ()
    inclusive_status: Literal["available"] = "available"


class TaskUsageByModelView(BaseModel):
    """One provider-model bucket of a Task's own LLM attempt token usage.

    ``provider_model`` is the identity the provider reported on
    ``llm.responded``. Attempts that never produced one — requested but never
    answered, failed, or answered without a model identity — are kept together
    in the explicit ``None`` bucket instead of being dropped; the bucket is
    part of the answer, not a gap in it. Aggregation is LOCAL only: an attempt
    belongs to the Task that made it, so nothing fans out through Task
    ancestry.

    ``attempt_count`` counts every attempt in the bucket. The token sums count
    only what was actually recorded — an attempt that reported no value for a
    dimension contributes nothing to it rather than a zero, and a dimension no
    attempt in the bucket recorded stays ``None``, because absent usage is
    unknown and not zero. ``attempts_with_usage`` reports how many attempts
    contributed at least one recorded dimension, so a bucket whose usage is
    only partially reported cannot be read as a complete total.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    provider_model: str | None
    attempt_count: int = Field(ge=0)
    attempts_with_usage: int = Field(ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)


class TaskUsageSourceView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    source_task_id: str
    values: tuple[TaskUsageValue, ...]


class TaskUsageBreakdownView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    task_id: str
    scope: AggregationScope
    sources: tuple[TaskUsageSourceView, ...]


def usage_contributions_for_observation(
    observation: ObservationEnvelope,
) -> tuple[UsageContribution, ...]:
    """Extract independent local-usage deltas from one durable observation."""
    if observation.kind == "task.heartbeat" and observation.payload is not None:
        elapsed_ms = observation.payload.get("elapsed_ms")
        if isinstance(elapsed_ms, int) and not isinstance(elapsed_ms, bool) and elapsed_ms >= 0:
            return (_contribution(observation, "wall_time_ms", elapsed_ms),)
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
    for dimension in LLM_TOKEN_USAGE_DIMENSIONS:
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
        aggregate_task_id=observation.task_id,
        source_task_id=observation.task_id,
        dimension=dimension,
        source_obs_id=observation.obs_id,
        delta=delta,
        as_of=observation.occurred_at,
    )
