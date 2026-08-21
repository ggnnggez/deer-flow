from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ansich.assessment.base import Assessment, EvidenceRef
from ansich.contracts import NamedVersion

AlertType = Literal[
    "budget_warning",
    "budget_exceeded",
    "exact_repetition",
    "tool_frequency",
    "heartbeat_missing",
    "long_dwell",
    "configuration_drift",
    "attempted_scope_violation",
    "realized_scope_violation",
    "unverified_effect",
    "environment_pressure",
    "environment_leak_suspected",
    "observability_degradation",
    "projection_failure",
]
AlertSeverity = Literal["info", "warning", "critical"]
AlertWorkflowState = Literal[
    "open",
    "acknowledged",
    "dismissed",
    "resolved",
]


def alert_key_for(
    *,
    alert_type: AlertType,
    subject_id: str,
    rule_name: str,
    stable_condition_key: str,
) -> str:
    identity = "\x1f".join((alert_type, subject_id, rule_name, stable_condition_key))
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


class AlertCondition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    alert_type: AlertType
    subject_id: str = Field(min_length=1)
    rule: NamedVersion
    rule_config_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    stable_condition_key: str = Field(min_length=1)
    active: bool
    source_assertion_id: str = Field(min_length=1)
    as_of: datetime
    severity: AlertSeverity
    shadow: bool
    evidence: tuple[EvidenceRef, ...] = ()

    @field_validator("as_of")
    @classmethod
    def _as_of_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Alert condition timestamp must be timezone-aware")
        return value

    @property
    def alert_key(self) -> str:
        return alert_key_for(
            alert_type=self.alert_type,
            subject_id=self.subject_id,
            rule_name=self.rule.name,
            stable_condition_key=self.stable_condition_key,
        )


class AlertEpisode(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    alert_id: str = Field(min_length=1)
    alert_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    episode: int = Field(ge=1)
    alert_type: AlertType
    subject_id: str = Field(min_length=1)
    rule: NamedVersion
    rule_config_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    stable_condition_key: str = Field(min_length=1)
    source_assertion_id: str = Field(min_length=1)
    opened_at: datetime
    as_of: datetime
    updated_at: datetime
    resolved_at: datetime | None = None
    resolution_reason: str | None = None
    workflow_state: AlertWorkflowState = "open"
    workflow_version: int = Field(default=1, ge=1)
    dismissal_reason: str | None = None
    severity: AlertSeverity
    shadow: bool
    evidence: tuple[EvidenceRef, ...] = ()

    @field_validator("opened_at", "as_of", "updated_at", "resolved_at")
    @classmethod
    def _timestamps_are_aware(
        cls,
        value: datetime | None,
    ) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("Alert timestamps must be timezone-aware")
        return value


class AlertReconciliation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    change: Literal["opened", "confirmed", "resolved", "noop"]
    alert: AlertEpisode | None


class AlertWorkflowConflict(Exception):
    def __init__(self, current: AlertEpisode):
        super().__init__("Alert workflow version does not match the current episode")
        self.current = current


def _matching_episodes(
    episodes: Sequence[AlertEpisode],
    alert_key: str,
) -> list[AlertEpisode]:
    return sorted(
        (episode for episode in episodes if episode.alert_key == alert_key),
        key=lambda item: (item.episode, item.opened_at, item.alert_id),
    )


def reconcile_alert_episode(
    episodes: Sequence[AlertEpisode],
    condition: AlertCondition,
    *,
    now: datetime,
    alert_id_factory: Callable[[], str],
) -> AlertReconciliation:
    matching = _matching_episodes(episodes, condition.alert_key)
    current = matching[-1] if matching else None
    unresolved = current if current is not None and current.workflow_state != "resolved" and current.resolved_at is None else None

    if condition.active:
        if unresolved is not None:
            return AlertReconciliation(
                change="confirmed",
                alert=unresolved.model_copy(
                    update={
                        "rule": condition.rule,
                        "rule_config_hash": condition.rule_config_hash,
                        "source_assertion_id": condition.source_assertion_id,
                        "as_of": condition.as_of,
                        "updated_at": now,
                        "severity": condition.severity,
                        "shadow": condition.shadow,
                        "evidence": condition.evidence,
                    }
                ),
            )
        episode = 1 if current is None else current.episode + 1
        return AlertReconciliation(
            change="opened",
            alert=AlertEpisode(
                alert_id=alert_id_factory(),
                alert_key=condition.alert_key,
                episode=episode,
                alert_type=condition.alert_type,
                subject_id=condition.subject_id,
                rule=condition.rule,
                rule_config_hash=condition.rule_config_hash,
                stable_condition_key=condition.stable_condition_key,
                source_assertion_id=condition.source_assertion_id,
                opened_at=now,
                as_of=condition.as_of,
                updated_at=now,
                severity=condition.severity,
                shadow=condition.shadow,
                evidence=condition.evidence,
            ),
        )

    if unresolved is None:
        return AlertReconciliation(change="noop", alert=current)
    return AlertReconciliation(
        change="resolved",
        alert=resolve_alert_episode(
            unresolved,
            now=now,
            reason="condition_cleared",
        ),
    )


def reconcile_alert_conditions(
    episodes: Sequence[AlertEpisode],
    conditions: Sequence[AlertCondition],
    *,
    now: datetime,
    alert_id_factory: Callable[[], str],
) -> tuple[AlertReconciliation, ...]:
    """Reconcile one exhaustive assessor result against existing episodes.

    Conditions define the evaluated subject/rule/type scopes. Any unresolved
    episode in one of those scopes whose stable key is no longer reported is
    resolved, which lets an exact-repetition Alert recover when the repeated
    action changes to a different signature.
    """

    working = list(episodes)
    changes: list[AlertReconciliation] = []
    reported_keys = {condition.alert_key for condition in conditions}
    evaluated_scopes = {(condition.subject_id, condition.rule.name, condition.alert_type) for condition in conditions}

    def apply_change(change: AlertReconciliation) -> None:
        changes.append(change)
        if change.alert is None:
            return
        for index, existing in enumerate(working):
            if existing.alert_id == change.alert.alert_id:
                working[index] = change.alert
                return
        working.append(change.alert)

    for condition in conditions:
        apply_change(
            reconcile_alert_episode(
                working,
                condition,
                now=now,
                alert_id_factory=alert_id_factory,
            )
        )

    for alert in tuple(working):
        scope = (alert.subject_id, alert.rule.name, alert.alert_type)
        if scope in evaluated_scopes and alert.alert_key not in reported_keys and alert.workflow_state != "resolved" and alert.resolved_at is None:
            apply_change(
                AlertReconciliation(
                    change="resolved",
                    alert=resolve_alert_episode(
                        alert,
                        now=now,
                        reason="condition_cleared",
                    ),
                )
            )
    return tuple(changes)


def _require_workflow_version(
    alert: AlertEpisode,
    expected_workflow_version: int,
) -> None:
    if alert.workflow_version != expected_workflow_version:
        raise AlertWorkflowConflict(alert)
    if alert.workflow_state == "resolved" or alert.resolved_at is not None:
        raise ValueError("resolved Alert episodes cannot be changed")


def acknowledge_alert(
    alert: AlertEpisode,
    *,
    expected_workflow_version: int,
    now: datetime,
) -> AlertEpisode:
    _require_workflow_version(alert, expected_workflow_version)
    return alert.model_copy(
        update={
            "workflow_state": "acknowledged",
            "workflow_version": alert.workflow_version + 1,
            "updated_at": now,
        }
    )


def dismiss_alert(
    alert: AlertEpisode,
    *,
    expected_workflow_version: int,
    now: datetime,
    reason: str,
) -> AlertEpisode:
    _require_workflow_version(alert, expected_workflow_version)
    if not reason.strip():
        raise ValueError("dismissal reason must be non-empty")
    return alert.model_copy(
        update={
            "workflow_state": "dismissed",
            "workflow_version": alert.workflow_version + 1,
            "dismissal_reason": reason,
            "updated_at": now,
        }
    )


def resolve_alert_episode(
    alert: AlertEpisode,
    *,
    now: datetime,
    reason: str,
) -> AlertEpisode:
    if alert.workflow_state == "resolved":
        return alert
    if not reason.strip():
        raise ValueError("resolution reason must be non-empty")
    return alert.model_copy(
        update={
            "workflow_state": "resolved",
            "workflow_version": alert.workflow_version + 1,
            "resolved_at": now,
            "resolution_reason": reason,
            "updated_at": now,
        }
    )


def _condition(
    assessment: Assessment,
    *,
    source_assertion_id: str,
    alert_type: AlertType,
    stable_condition_key: str,
    active: bool,
    severity: AlertSeverity,
) -> AlertCondition:
    return AlertCondition(
        alert_type=alert_type,
        subject_id=assessment.subject_id,
        rule=assessment.assessor,
        rule_config_hash=assessment.config_hash,
        stable_condition_key=stable_condition_key,
        active=active,
        source_assertion_id=source_assertion_id,
        as_of=assessment.as_of,
        severity=severity,
        shadow=bool(assessment.value.get("shadow", False)),
        evidence=assessment.evidence,
    )


def alert_conditions_from_assessment(
    assessment: Assessment,
    *,
    source_assertion_id: str,
) -> tuple[AlertCondition, ...]:
    value = assessment.value.get("value")
    if assessment.field_name.startswith("budget_health:"):
        dimension = str(assessment.value.get("dimension", "unknown"))
        scope = str(assessment.value.get("aggregation_scope", "unknown"))
        condition_key = f"budget:{dimension}:{scope}"
        return (
            _condition(
                assessment,
                source_assertion_id=source_assertion_id,
                alert_type="budget_warning",
                stable_condition_key=condition_key,
                active=value == "warning",
                severity="warning",
            ),
            _condition(
                assessment,
                source_assertion_id=source_assertion_id,
                alert_type="budget_exceeded",
                stable_condition_key=condition_key,
                active=value == "exceeded",
                severity="critical",
            ),
        )
    if assessment.field_name.startswith("tool_frequency:"):
        tool_name = str(assessment.value.get("tool_name", "unknown"))
        return (
            _condition(
                assessment,
                source_assertion_id=source_assertion_id,
                alert_type="tool_frequency",
                stable_condition_key=f"tool:{tool_name}",
                active=value == "high",
                severity="warning",
            ),
        )
    if assessment.field_name == "behavior" and assessment.assessor.name == "action-repetition":
        signature = str(assessment.value.get("signature", "unknown"))
        return (
            _condition(
                assessment,
                source_assertion_id=source_assertion_id,
                alert_type="exact_repetition",
                stable_condition_key=f"signature:{signature}",
                active=(value == "runaway" and assessment.value.get("reason") == "exact_repetition"),
                severity="critical",
            ),
        )
    if assessment.field_name == "heartbeat":
        return (
            _condition(
                assessment,
                source_assertion_id=source_assertion_id,
                alert_type="heartbeat_missing",
                stable_condition_key="task-heartbeat",
                active=value == "stale",
                severity="critical",
            ),
        )
    if assessment.field_name == "dwell":
        return (
            _condition(
                assessment,
                source_assertion_id=source_assertion_id,
                alert_type="long_dwell",
                stable_condition_key="task-dwell",
                active=value == "long",
                severity="warning",
            ),
        )
    if assessment.field_name == "configuration_drift":
        return (
            _condition(
                assessment,
                source_assertion_id=source_assertion_id,
                alert_type="configuration_drift",
                stable_condition_key="provider-model",
                active=value == "mismatch",
                severity="warning",
            ),
        )
    if assessment.field_name.startswith("scope_safety:"):
        conclusion = str(assessment.value.get("conclusion", "unknown"))
        if conclusion not in {
            "attempted_scope_violation",
            "realized_scope_violation",
            "unverified_effect",
        }:
            return ()
        severity: AlertSeverity = "critical" if conclusion == "realized_scope_violation" else "warning"
        return (
            _condition(
                assessment,
                source_assertion_id=source_assertion_id,
                alert_type=conclusion,  # type: ignore[arg-type]
                stable_condition_key=conclusion,
                active=value == "present",
                severity=severity,
            ),
        )
    if assessment.field_name.startswith("environment_pressure:"):
        metric = assessment.field_name.split(":", 1)[1]
        # "unknown" is deliberately inactive: an unobserved Scope is not a
        # healthy one, but it is also not evidence of pressure, so it resolves
        # an open episode rather than sustaining it.
        pressure_severity: AlertSeverity = "critical" if value == "critical" else "warning"
        return (
            _condition(
                assessment,
                source_assertion_id=source_assertion_id,
                alert_type="environment_pressure",
                stable_condition_key=f"env:{metric}",
                active=value in {"warning", "critical"},
                severity=pressure_severity,
            ),
        )
    if assessment.field_name.startswith("projection_failure:"):
        # RB3④. The stable key rides in the value rather than being parsed back
        # out of the field name: the field name is bounded to the Assertion
        # column's 64 characters and degrades to a digest for a long projector
        # identity, so it is not always invertible. The producer that built the
        # Assessment knows the readable key and says so.
        return (
            _condition(
                assessment,
                source_assertion_id=source_assertion_id,
                alert_type="projection_failure",
                stable_condition_key=str(assessment.value.get("condition_key", "unknown")),
                active=value == "failing",
                # A durably failed projection leaves the raw Observation intact
                # and is recoverable by `retry_failed_projections`, so it is a
                # warning: the read model is incomplete, not the ledger.
                severity="warning",
            ),
        )
    if assessment.field_name.startswith("observability_degradation:"):
        return (
            _condition(
                assessment,
                source_assertion_id=source_assertion_id,
                alert_type="observability_degradation",
                stable_condition_key=str(assessment.value.get("condition_key", "unknown")),
                active=value == "degraded",
                # Loss is irrecoverable — there is no retry that brings a
                # charged range back — so this one outranks a failed projection.
                severity="critical",
            ),
        )
    if assessment.field_name == "environment_leak:fd_open":
        return (
            _condition(
                assessment,
                source_assertion_id=source_assertion_id,
                alert_type="environment_leak_suspected",
                stable_condition_key="env-leak:fd_open",
                active=value == "suspected",
                severity="warning",
            ),
        )
    return ()
