from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ansich.budget import BudgetHealthBelief, TaskBudgetsView
from ansich.contracts import ControlBelief, LostRange, NamedVersion
from ansich.heartbeat import TaskHeartbeatView
from ansich.usage import TaskUsageView


class HeartbeatBelief(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    value: Literal["unknown", "fresh", "stale"]
    as_of: datetime | None
    asserted_at: datetime
    age_ms: int | None = Field(default=None, ge=0)
    source: NamedVersion
    fidelity_class: Literal["rule"] = "rule"
    selected_by: NamedVersion
    evidence_obs_ids: tuple[str, ...]


class DwellBelief(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    value: Literal["unknown", "normal", "long"]
    since: datetime | None
    duration_ms: int | None = Field(default=None, ge=0)
    asserted_at: datetime
    source: NamedVersion
    fidelity_class: Literal["rule"] = "rule"
    selected_by: NamedVersion
    evidence_obs_ids: tuple[str, ...]


class ActiveStepView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    step_id: str
    step_seq: int = Field(ge=1)
    actor_kind: str
    status: str


class ActiveToolView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    tool_call_id: str
    tool_name: str
    call_seq: int = Field(ge=1)
    status: str


class ActiveTaskView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    task_id: str
    run_id: str
    source_kind: str
    owner_id: str | None = None
    thread_id: str | None = None
    agent_id: str | None = None
    control: ControlBelief
    current_step: ActiveStepView | None = None
    current_tool: ActiveToolView | None = None
    dwell: DwellBelief
    heartbeat: HeartbeatBelief
    usage: TaskUsageView
    active_child_count: int = Field(default=0, ge=0)
    budgets: TaskBudgetsView
    budget_health: tuple[BudgetHealthBelief, ...]
    duration_ms: int = Field(ge=0)
    observability_status: Literal["healthy", "degraded"]
    projection_watermark: int | None = Field(default=None, ge=1)
    projection_lag_ms: int = Field(ge=0)
    lost_ranges: tuple[LostRange, ...]
    last_evidence_at: datetime
    updated_at: datetime


def heartbeat_assessor_version(stale_after_seconds: int) -> str:
    digest = hashlib.sha256(f"heartbeat@1:stale_after_seconds={stale_after_seconds}".encode()).hexdigest()[:12]
    return f"1:{digest}"


def assess_heartbeat(
    heartbeat: TaskHeartbeatView | None,
    *,
    now: datetime,
    stale_after_seconds: int,
) -> HeartbeatBelief:
    if stale_after_seconds < 1:
        raise ValueError("stale_after_seconds must be positive")
    selected_by = NamedVersion(
        name="heartbeat-state",
        version=heartbeat_assessor_version(stale_after_seconds),
    )
    if heartbeat is None:
        return HeartbeatBelief(
            value="unknown",
            as_of=None,
            asserted_at=now,
            age_ms=None,
            source=NamedVersion(name="heartbeat", version="1"),
            selected_by=selected_by,
            evidence_obs_ids=(),
        )
    age = max(timedelta(0), now - heartbeat.occurred_at)
    age_ms = int(age.total_seconds() * 1000)
    return HeartbeatBelief(
        value=("stale" if age > timedelta(seconds=stale_after_seconds) else "fresh"),
        as_of=heartbeat.occurred_at,
        asserted_at=now,
        age_ms=age_ms,
        source=NamedVersion(name="heartbeat", version="1"),
        selected_by=selected_by,
        evidence_obs_ids=(heartbeat.heartbeat_obs_id,),
    )


def assess_dwell(
    *,
    since: datetime | None,
    evidence_obs_id: str | None,
    now: datetime,
    long_dwell_seconds: int,
) -> DwellBelief:
    if long_dwell_seconds < 1:
        raise ValueError("long_dwell_seconds must be positive")
    version = hashlib.sha256(f"dwell@1:long_dwell_seconds={long_dwell_seconds}".encode()).hexdigest()[:12]
    selected_by = NamedVersion(name="dwell-state", version=f"1:{version}")
    if since is None or evidence_obs_id is None:
        return DwellBelief(
            value="unknown",
            since=None,
            duration_ms=None,
            asserted_at=now,
            source=NamedVersion(name="transition-dwell", version="1"),
            selected_by=selected_by,
            evidence_obs_ids=(),
        )
    duration = max(timedelta(0), now - since)
    return DwellBelief(
        value=("long" if duration > timedelta(seconds=long_dwell_seconds) else "normal"),
        since=since,
        duration_ms=int(duration.total_seconds() * 1000),
        asserted_at=now,
        source=NamedVersion(name="transition-dwell", version="1"),
        selected_by=selected_by,
        evidence_obs_ids=(evidence_obs_id,),
    )
