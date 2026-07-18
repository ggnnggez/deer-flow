from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from ansich.alerts.episodes import (
    AlertSeverity,
    AlertType,
    AlertWorkflowState,
)
from ansich.assessment.base import AuthorityClass, FidelityClass
from ansich.contracts import NamedVersion, ObservationEnvelope


class BeliefAssertionView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    assertion_id: str
    subject_id: str
    field_name: str
    value: dict[str, object]
    as_of: datetime
    asserted_at: datetime
    assessor: NamedVersion
    config_hash: str
    authority_class: AuthorityClass
    fidelity_class: FidelityClass
    confidence: float | None = None
    evidence_obs_ids: tuple[str, ...]


class AlertSummaryView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    alert_id: str
    subject_id: str
    alert_type: AlertType
    episode: int
    severity: AlertSeverity
    workflow_state: AlertWorkflowState
    workflow_version: int
    shadow: bool
    opened_at: datetime
    as_of: datetime
    updated_at: datetime
    resolved_at: datetime | None = None
    rule: NamedVersion
    rule_config_hash: str
    stable_condition_key: str
    source_assertion_id: str
    resolution_reason: str | None = None
    dismissal_reason: str | None = None
    evidence_count: int


class AlertWorkflowEventView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    event_id: str
    obs_id: str
    action: str
    from_state: AlertWorkflowState
    to_state: AlertWorkflowState
    workflow_version: int
    reason: str | None = None
    operator_id: str | None = None
    occurred_at: datetime


class AlertDetailView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    alert: AlertSummaryView
    source_belief: BeliefAssertionView
    evidence: tuple[ObservationEnvelope, ...]
    current_beliefs: tuple[BeliefAssertionView, ...]
    workflow_history: tuple[AlertWorkflowEventView, ...]
    available_actions: tuple[
        Literal[
            "acknowledge",
            "dismiss",
            "interrupt",
            "rollback",
        ],
        ...,
    ]
