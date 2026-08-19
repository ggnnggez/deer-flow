from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ansich.assessment.base import (
    Assessment,
    EvidenceRef,
    canonical_config_hash,
)
from ansich.contracts import NamedVersion

EnvironmentScopeKind = Literal["container", "process_group", "host_shared"]
EnvironmentCoverage = Literal["continuous", "per_command", "uninstrumented"]

_METRIC_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class EnvironmentMetric(_FrozenModel):
    value: int = Field(ge=0)
    limit: int | None = Field(default=None, ge=0)


class EnvironmentWindow(_FrozenModel):
    started_at: datetime
    ended_at: datetime
    sample_count: int = Field(ge=0)

    @model_validator(mode="after")
    def _validate_window(self) -> Self:
        if self.ended_at < self.started_at:
            raise ValueError("environment window ended_at must not precede started_at")
        return self


class EnvironmentSamplePayload(_FrozenModel):
    environment_scope: EnvironmentScopeKind
    coverage: EnvironmentCoverage
    window: EnvironmentWindow
    provider: str = Field(min_length=1, max_length=64)
    metrics: dict[str, EnvironmentMetric] = Field(default_factory=dict)
    tool_call_id: str | None = None

    @model_validator(mode="after")
    def _validate_marks(self) -> Self:
        for name in self.metrics:
            if not _METRIC_NAME.match(name):
                raise ValueError(f"environment metric name is not canonical: {name!r}")
        if self.coverage == "uninstrumented":
            if self.metrics:
                raise ValueError("uninstrumented environment sample must not carry metrics")
            if self.window.sample_count != 0:
                raise ValueError("uninstrumented environment sample must declare sample_count=0")
        elif not self.metrics:
            raise ValueError("instrumented environment sample requires at least one metric")
        if self.coverage == "per_command":
            if self.tool_call_id is None:
                raise ValueError("per_command environment sample requires tool_call_id")
            if self.environment_scope != "process_group":
                raise ValueError("per_command environment sample must be process_group scoped")
        elif self.tool_call_id is not None:
            raise ValueError("tool_call_id is only valid for per_command coverage")
        return self


EnvironmentPressureState = Literal["ok", "warning", "critical", "unknown"]
EnvironmentLeakState = Literal["none", "suspected", "unknown"]

#: One assessor produces both environment fields. Its identity is part of every
#: Alert key (``alert_key_for`` hashes ``rule_name``), so the two field families
#: stay distinguishable through their stable condition keys, not through
#: separate rule names.
ENVIRONMENT_PRESSURE_ASSESSOR = NamedVersion(name="environment-pressure", version="1")

#: Metrics judged as "closeness to a saturation point" rather than raw level.
_PSI_METRICS = frozenset({"psi_io_some_avg10_milli", "psi_memory_some_avg10_milli"})

#: Every metric ``environment-pressure@1`` has a rule for (mirrors
#: ``_pressure_state``'s branching). Read-side callers (the Gateway task
#: environment view) use this to decide which ``environment_pressure:{metric}``
#: Belief dimensions to expect for an observed metric, without duplicating the
#: rule's own branching.
PRESSURE_RULED_METRICS: frozenset[str] = frozenset({"fd_open", "disk_free_bytes"}) | _PSI_METRICS

#: The leak rule is only defined for a Scope whose whole process tree is
#: observed for the whole window. ``process_group`` sees one command's own fds
#: (the count legitimately returns to zero between calls) and ``host_shared``
#: mixes in every other process on the box, so neither can support "this Agent
#: is leaking". Feeding either one in is a caller error the rule refuses rather
#: than answers.
LEAK_ELIGIBLE_ENVIRONMENT_SCOPES: frozenset[str] = frozenset({"container"})


class EnvironmentMetricView(_FrozenModel):
    """One (Scope, environment_scope, metric) reading for the Gateway read side.

    Mirrors ``ansich_environment_state`` columns directly; ``limit`` is
    ``None`` when the projector never observed a limit for this metric.
    """

    metric: str
    latest_value: int = Field(ge=0)
    limit: int | None = Field(default=None, ge=0)
    as_of: datetime
    sample_count: int = Field(ge=0)
    window_started_at: datetime
    consecutive_growth_count: int = Field(ge=0)


class EnvironmentBeliefView(_FrozenModel):
    """The current Belief for one environment field on one Scope.

    An ``environment_pressure``/``environment_leak`` dimension nothing has
    assessed yet is synthesized the same way ``unassessed_quality_belief``
    synthesizes a missing quality dimension: ``source=NamedVersion(name="none",
    version="1")``, unknown authority/fidelity, no ``as_of``/``asserted_at``,
    and no evidence — so a Scope with data but no judgement yet is never
    silently omitted (concepts 第 9 条第 6 款).
    """

    field_name: str
    value: dict[str, object]
    as_of: datetime | None = None
    asserted_at: datetime | None = None
    source: NamedVersion
    authority_class: str
    fidelity_class: str
    evidence_obs_ids: tuple[str, ...] = ()


class EnvironmentAlertSummaryView(_FrozenModel):
    """One environment Alert episode summary, scoped to a Scope subject.

    ``possibly_affected_task_ids`` mirrors ``AnsichAlertReadModelRow`` verbatim:
    the Tasks the assessor found ``running`` in this Scope at the moment the
    triggering sample was recorded (correlation, not causality — same
    discipline as ``possible_exposure``). ``None`` means the read model never
    recorded a set (e.g. an older Alert, or none were running); it is never
    invented from evidence Observations, whose ``task_id`` only names the one
    Task that happened to record a given sample, not the full running set.
    """

    alert_id: str
    alert_type: str
    severity: str
    workflow_state: str
    opened_at: datetime
    resolved_at: datetime | None = None
    possibly_affected_task_ids: tuple[str, ...] | None = None


class EnvironmentScopeView(_FrozenModel):
    """One (Scope, environment_scope) card: coverage, metrics, Beliefs, Alerts.

    A Scope entity can carry more than one ``environment_scope`` coverage row
    (e.g. continuous ``container`` collection alongside per-command
    ``process_group`` samples for individual tool calls), so the read side is
    keyed one card per ``ansich_environment_coverage`` row rather than one per
    Scope entity.
    """

    scope_id: str
    scope_kind: str
    display_label: str
    environment_scope: str
    coverage: str
    provider: str
    metrics: tuple[EnvironmentMetricView, ...] = ()
    beliefs: tuple[EnvironmentBeliefView, ...] = ()
    alerts: tuple[EnvironmentAlertSummaryView, ...] = ()


class TaskEnvironmentView(_FrozenModel):
    """A Task's environment observability: every attached Scope's card(s)."""

    task_id: str
    scopes: tuple[EnvironmentScopeView, ...] = ()


class EnvironmentHistoryPoint(_FrozenModel):
    """One historical reading of a single metric on one Scope.

    ``limit`` is whatever that sample itself reported, so a limit that moved
    mid-window is visible instead of being flattened to the current one; it is
    ``None`` when the sample carried no limit.
    """

    occurred_at: datetime
    value: int = Field(ge=0)
    limit: int | None = Field(default=None, ge=0)


class EnvironmentHistoryView(_FrozenModel):
    """A bounded ``(Scope, environment_scope, metric)`` trend window.

    Points are ordered oldest-first. A sample that did not carry the requested
    metric is **skipped**, never reported as ``0`` — missing is not zero
    (concepts 第 9 条第 6 款), so a gap in this series is an honest gap the
    renderer must not interpolate across. ``truncated`` says the window held
    more surviving points than ``max_points`` and the **newest** ones were
    kept.
    """

    scope_id: str
    environment_scope: str
    metric: str
    window_minutes: int = Field(ge=1)
    truncated: bool = False
    points: tuple[EnvironmentHistoryPoint, ...] = ()


class ToolEnvSampleView(_FrozenModel):
    """One per-command sample in a Task's command sequence.

    Narrower than ``ToolEnvironmentSampleView`` on purpose: the Task-scoped
    sequence read needs only what a per-command trend renders, not the
    scope/obs identity a single-ToolCall lookup returns.
    """

    tool_call_id: str
    started_at: datetime
    ended_at: datetime
    sample_count: int = Field(ge=0)
    fd_peak: int | None = Field(default=None, ge=0)
    io_read_bytes: int | None = Field(default=None, ge=0)
    io_write_bytes: int | None = Field(default=None, ge=0)


class TaskToolEnvSamplesView(_FrozenModel):
    """A Task's per-command samples in execution order (oldest first)."""

    task_id: str
    truncated: bool = False
    samples: tuple[ToolEnvSampleView, ...] = ()


class ToolEnvironmentSampleView(_FrozenModel):
    """One per-tool-call environment sample (mirrors ``ansich_tool_env_samples``)."""

    tool_call_id: str
    task_id: str
    scope_id: str
    io_read_bytes: int | None = None
    io_write_bytes: int | None = None
    fd_peak: int | None = None
    sample_count: int = Field(ge=0)
    started_at: datetime
    ended_at: datetime
    obs_id: str


class EnvironmentThresholds(BaseModel):
    """Rule thresholds for ``environment-pressure@1``.

    Field names mirror ``AnsichAssessorConfig``'s ``environment_*`` knobs with
    the prefix dropped. The whole model is the assessor's config identity: its
    canonical hash goes on every Assertion, so changing one threshold starts a
    new assertion lineage instead of silently re-labelling the old one.

    Deliberately not ``strict``: the DeerFlow config layer types the ratios as
    floats, and an operator writing ``1`` in YAML must not become a validation
    error at service assembly.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    fd_warn_ratio: float = Field(default=0.8, gt=0, le=1)
    fd_critical_ratio: float = Field(default=0.95, gt=0, le=1)
    disk_free_warn_ratio: float = Field(default=0.10, gt=0, le=1)
    disk_free_critical_ratio: float = Field(default=0.05, gt=0, le=1)
    psi_warn_milli: int = Field(default=40_000, ge=1)
    psi_critical_milli: int = Field(default=80_000, ge=1)
    leak_min_samples: int = Field(default=6, ge=1)
    leak_window_seconds: int = Field(default=60, ge=1)
    leak_min_growth: int = Field(default=50, ge=1)

    @model_validator(mode="after")
    def _validate_ordering(self) -> Self:
        if self.fd_warn_ratio >= self.fd_critical_ratio:
            raise ValueError("fd_warn_ratio must be less than fd_critical_ratio")
        if self.psi_warn_milli >= self.psi_critical_milli:
            raise ValueError("psi_warn_milli must be less than psi_critical_milli")
        if self.disk_free_critical_ratio >= self.disk_free_warn_ratio:
            raise ValueError("disk_free_critical_ratio must be less than disk_free_warn_ratio")
        return self


def _pressure_state(
    metric: str,
    value: int,
    limit: int | None,
    thresholds: EnvironmentThresholds,
) -> EnvironmentPressureState | None:
    """Return the categorical pressure state, or ``None`` for an unruled metric.

    ``None`` means "v1 has no pressure rule for this metric" (e.g. the
    per-command IO counters), which is different from ``"unknown"`` — the
    former produces no Assertion at all, the latter produces one that says the
    rule could not decide.
    """

    if metric == "fd_open":
        if limit is None or limit <= 0:
            return "unknown"
        ratio = value / limit
        return "critical" if ratio >= thresholds.fd_critical_ratio else "warning" if ratio >= thresholds.fd_warn_ratio else "ok"
    if metric == "disk_free_bytes":
        # Inverted direction: the "limit" is the total size and the value is
        # what is left, so a *small* ratio is the bad end.
        if limit is None or limit <= 0:
            return "unknown"
        ratio = value / limit
        return "critical" if ratio <= thresholds.disk_free_critical_ratio else "warning" if ratio <= thresholds.disk_free_warn_ratio else "ok"
    if metric in _PSI_METRICS:
        return "critical" if value >= thresholds.psi_critical_milli else "warning" if value >= thresholds.psi_warn_milli else "ok"
    return None


def _environment_value(
    *,
    state: str,
    metric: str,
    environment_scope: str,
    coverage: str,
) -> dict[str, object]:
    """Build the Assertion value.

    Only stable categorical fields belong here. The current numbers live in
    ``ansich_environment_state`` and the affected Task ids on the Alert read
    model, because transition-only assertion appending is a direct consequence
    of this dict not moving while the state does not move.
    """

    return {
        "value": state,
        "metric": metric,
        "environment_scope": environment_scope,
        "coverage": coverage,
    }


def assess_environment_pressure(
    *,
    scope_id: str,
    metric: str,
    environment_scope: str,
    coverage: str,
    latest_value: int,
    limit: int | None,
    as_of: datetime,
    last_obs_id: str | None,
    now: datetime,
    sample_interval_seconds: int,
    thresholds: EnvironmentThresholds,
) -> Assessment | None:
    """Judge one ``(Scope, environment_scope, metric)`` reading.

    Returns ``None`` when v1 has no rule for the metric, and for
    ``per_command`` coverage, which describes one tool call's own window rather
    than the Scope's standing condition and is a read-side fact only.
    """

    if sample_interval_seconds < 1:
        raise ValueError("sample_interval_seconds must be positive")
    if coverage == "per_command":
        return None
    state = _pressure_state(metric, latest_value, limit, thresholds)
    if state is None:
        return None
    if coverage != "continuous":
        # "uninstrumented" (an explicit declaration that nothing is observed)
        # and any unrecognized coverage both mean the rule cannot see enough.
        # Downgrading to unknown here — never to "ok" — is what keeps an
        # unobserved Scope from reading as a healthy one.
        state = "unknown"
    elif now - as_of > timedelta(seconds=3 * sample_interval_seconds):
        # Three missed sampling intervals: the reading describes the past, not
        # the present, so the state is unknown regardless of what it said.
        state = "unknown"
    evidence = () if last_obs_id is None else (EvidenceRef(obs_id=last_obs_id),)
    return Assessment(
        subject_id=scope_id,
        field_name=f"environment_pressure:{metric}",
        value=_environment_value(
            state=state,
            metric=metric,
            environment_scope=environment_scope,
            coverage=coverage,
        ),
        as_of=as_of,
        asserted_at=now,
        assessor=ENVIRONMENT_PRESSURE_ASSESSOR,
        config_hash=canonical_config_hash(thresholds.model_dump()),
        authority_class="configured_rule",
        fidelity_class="rule",
        evidence=evidence,
    )


def assess_environment_leak(
    *,
    scope_id: str,
    environment_scope: str,
    coverage: str,
    consecutive_growth_count: int,
    growth_started_at: datetime | None,
    window_min_value: int,
    latest_value: int,
    as_of: datetime,
    last_obs_id: str | None,
    now: datetime,
    thresholds: EnvironmentThresholds,
) -> Assessment | None:
    """Judge sustained monotonic ``fd_open`` growth for one Scope.

    Returns ``None`` — no Assertion at all — for every input the rule is not
    defined over: a ``process_group`` or ``host_shared`` environment scope, and
    any coverage other than ``continuous``.

    ``consecutive_growth_count`` is maintained by the environment projector,
    which discards out-of-order samples; the count therefore under-reports and
    this rule can fire later than an ideal one would. That direction is
    conservative (a late leak suspicion, never a fabricated one), so it is left
    uncompensated on purpose.
    """

    if environment_scope not in LEAK_ELIGIBLE_ENVIRONMENT_SCOPES:
        return None
    if coverage != "continuous":
        return None
    window = timedelta(seconds=thresholds.leak_window_seconds)
    state: EnvironmentLeakState
    if now - as_of > window:
        # The growth window is stale: whatever trend it recorded may already
        # have ended, so the rule reports unknown rather than a stale verdict.
        state = "unknown"
    elif consecutive_growth_count >= thresholds.leak_min_samples and growth_started_at is not None and as_of - growth_started_at >= window and latest_value - window_min_value >= thresholds.leak_min_growth:
        state = "suspected"
    else:
        state = "none"
    evidence = () if last_obs_id is None else (EvidenceRef(obs_id=last_obs_id),)
    return Assessment(
        subject_id=scope_id,
        field_name="environment_leak:fd_open",
        value=_environment_value(
            state=state,
            metric="fd_open",
            environment_scope=environment_scope,
            coverage=coverage,
        ),
        as_of=as_of,
        asserted_at=now,
        assessor=ENVIRONMENT_PRESSURE_ASSESSOR,
        config_hash=canonical_config_hash(thresholds.model_dump()),
        authority_class="configured_rule",
        fidelity_class="rule",
        evidence=evidence,
    )
