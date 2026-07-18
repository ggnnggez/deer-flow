from datetime import UTC, datetime, timedelta

import pytest
from ansich.alerts.episodes import (
    AlertCondition,
    AlertWorkflowConflict,
    acknowledge_alert,
    alert_conditions_from_assessment,
    dismiss_alert,
    reconcile_alert_conditions,
    reconcile_alert_episode,
    resolve_alert_episode,
)
from ansich.assessment.base import Assessment, EvidenceRef, canonical_config_hash

NOW = datetime(2026, 7, 18, 16, 0, tzinfo=UTC)


def _condition(
    *,
    active: bool = True,
    assertion_id: str = "assertion-1",
    evidence: tuple[str, ...] = ("obs-1",),
) -> AlertCondition:
    return AlertCondition(
        alert_type="exact_repetition",
        subject_id="task-1",
        rule={"name": "action-repetition", "version": "1.0.0"},
        rule_config_hash=canonical_config_hash({"window": 5}),
        stable_condition_key="signature:same-action",
        active=active,
        source_assertion_id=assertion_id,
        as_of=NOW,
        severity="critical",
        shadow=False,
        evidence=tuple(EvidenceRef(obs_id=obs_id) for obs_id in evidence),
    )


def _ids():
    values = iter(("alert-1", "alert-2", "alert-3"))
    return lambda: next(values)


def test_repeated_confirmation_updates_one_open_episode_without_bumping_workflow() -> None:
    id_factory = _ids()
    opened = reconcile_alert_episode(
        (),
        _condition(),
        now=NOW,
        alert_id_factory=id_factory,
    )
    confirmed = reconcile_alert_episode(
        (opened.alert,),
        _condition(
            assertion_id="assertion-2",
            evidence=("obs-1", "obs-2"),
        ).model_copy(update={"as_of": NOW + timedelta(seconds=1)}),
        now=NOW + timedelta(seconds=1),
        alert_id_factory=id_factory,
    )

    assert opened.change == "opened"
    assert opened.alert.alert_id == "alert-1"
    assert opened.alert.episode == 1
    assert confirmed.change == "confirmed"
    assert confirmed.alert.alert_id == "alert-1"
    assert confirmed.alert.episode == 1
    assert confirmed.alert.source_assertion_id == "assertion-2"
    assert [item.obs_id for item in confirmed.alert.evidence] == [
        "obs-1",
        "obs-2",
    ]
    assert confirmed.alert.workflow_version == 1


def test_recovery_resolves_and_recurrence_opens_the_next_episode() -> None:
    id_factory = _ids()
    opened = reconcile_alert_episode(
        (),
        _condition(),
        now=NOW,
        alert_id_factory=id_factory,
    ).alert
    resolved = reconcile_alert_episode(
        (opened,),
        _condition(active=False, assertion_id="assertion-clear"),
        now=NOW + timedelta(minutes=1),
        alert_id_factory=id_factory,
    )
    recurred = reconcile_alert_episode(
        (resolved.alert,),
        _condition(assertion_id="assertion-recurred", evidence=("obs-3",)),
        now=NOW + timedelta(minutes=2),
        alert_id_factory=id_factory,
    )

    assert resolved.change == "resolved"
    assert resolved.alert.workflow_state == "resolved"
    assert resolved.alert.resolution_reason == "condition_cleared"
    assert recurred.change == "opened"
    assert recurred.alert.alert_id == "alert-2"
    assert recurred.alert.episode == 2


def test_acknowledge_and_dismiss_use_optimistic_workflow_versions() -> None:
    opened = reconcile_alert_episode(
        (),
        _condition(),
        now=NOW,
        alert_id_factory=_ids(),
    ).alert
    acknowledged = acknowledge_alert(
        opened,
        expected_workflow_version=1,
        now=NOW + timedelta(seconds=1),
    )

    assert acknowledged.workflow_state == "acknowledged"
    assert acknowledged.workflow_version == 2
    assert acknowledged.source_assertion_id == opened.source_assertion_id
    with pytest.raises(AlertWorkflowConflict) as conflict:
        dismiss_alert(
            acknowledged,
            expected_workflow_version=1,
            now=NOW + timedelta(seconds=2),
            reason="false_positive",
        )
    assert conflict.value.current == acknowledged

    dismissed = dismiss_alert(
        acknowledged,
        expected_workflow_version=2,
        now=NOW + timedelta(seconds=2),
        reason="expected_batch_activity",
    )
    assert dismissed.workflow_state == "dismissed"
    assert dismissed.workflow_version == 3
    assert dismissed.dismissal_reason == "expected_batch_activity"
    assert dismissed.resolved_at is None


def test_dismissed_condition_stays_suppressed_until_recovery_then_can_recur() -> None:
    id_factory = _ids()
    opened = reconcile_alert_episode(
        (),
        _condition(),
        now=NOW,
        alert_id_factory=id_factory,
    ).alert
    dismissed = dismiss_alert(
        opened,
        expected_workflow_version=1,
        now=NOW + timedelta(seconds=1),
        reason="known_test",
    )
    confirmed = reconcile_alert_episode(
        (dismissed,),
        _condition(assertion_id="assertion-still-active"),
        now=NOW + timedelta(seconds=2),
        alert_id_factory=id_factory,
    ).alert
    cleared = reconcile_alert_episode(
        (confirmed,),
        _condition(active=False, assertion_id="assertion-clear"),
        now=NOW + timedelta(seconds=3),
        alert_id_factory=id_factory,
    ).alert
    recurred = reconcile_alert_episode(
        (cleared,),
        _condition(assertion_id="assertion-new-episode"),
        now=NOW + timedelta(seconds=4),
        alert_id_factory=id_factory,
    ).alert

    assert confirmed.alert_id == opened.alert_id
    assert confirmed.workflow_state == "dismissed"
    assert cleared.workflow_state == "resolved"
    assert recurred.alert_id == "alert-2"
    assert recurred.episode == 2


def test_terminal_resolution_keeps_the_source_fact_and_reason() -> None:
    opened = reconcile_alert_episode(
        (),
        _condition(),
        now=NOW,
        alert_id_factory=_ids(),
    ).alert

    resolved = resolve_alert_episode(
        opened,
        now=NOW + timedelta(minutes=1),
        reason="task_terminal",
    )

    assert resolved.workflow_state == "resolved"
    assert resolved.resolution_reason == "task_terminal"
    assert resolved.source_assertion_id == "assertion-1"
    assert resolved.evidence == opened.evidence


def _assessment(
    *,
    field_name: str,
    value: dict[str, object],
    assessor_name: str,
) -> Assessment:
    return Assessment(
        subject_id="task-1",
        field_name=field_name,
        value=value,
        as_of=NOW,
        asserted_at=NOW,
        assessor={"name": assessor_name, "version": "1.0.0"},
        config_hash=canonical_config_hash({"field": field_name}),
        authority_class="configured_rule",
        fidelity_class="rule",
        evidence=(EvidenceRef(obs_id="obs-assessment"),),
    )


def test_budget_crossing_emits_separate_warning_and_exceeded_conditions() -> None:
    assessment = _assessment(
        field_name="budget_health:steps:local",
        assessor_name="absolute-limit",
        value={
            "value": "exceeded",
            "dimension": "steps",
            "aggregation_scope": "local",
            "shadow": True,
        },
    )

    conditions = alert_conditions_from_assessment(
        assessment,
        source_assertion_id="assertion-budget",
    )

    assert [item.alert_type for item in conditions] == [
        "budget_warning",
        "budget_exceeded",
    ]
    assert [item.active for item in conditions] == [False, True]
    assert all(item.shadow for item in conditions)


def test_frequency_assessment_never_becomes_exact_repetition_alert() -> None:
    assessment = _assessment(
        field_name="tool_frequency:web_search",
        assessor_name="tool-frequency",
        value={
            "value": "high",
            "tool_name": "web_search",
            "count": 30,
            "shadow": False,
        },
    )

    conditions = alert_conditions_from_assessment(
        assessment,
        source_assertion_id="assertion-frequency",
    )

    assert len(conditions) == 1
    assert conditions[0].alert_type == "tool_frequency"
    assert conditions[0].active is True


def test_exhaustive_reconciliation_resolves_an_old_signature_when_action_changes() -> None:
    id_factory = _ids()
    opened = reconcile_alert_episode(
        (),
        _condition(),
        now=NOW,
        alert_id_factory=id_factory,
    ).alert
    changed_action = _assessment(
        field_name="behavior",
        assessor_name="action-repetition",
        value={
            "value": "unassessed",
            "reason": "exact_repetition_not_met",
            "signature": "different-action",
            "shadow": False,
        },
    )
    conditions = alert_conditions_from_assessment(
        changed_action,
        source_assertion_id="assertion-changed",
    )

    changes = reconcile_alert_conditions(
        (opened,),
        conditions,
        now=NOW + timedelta(minutes=1),
        alert_id_factory=id_factory,
    )

    assert len(conditions) == 1
    assert conditions[0].active is False
    assert any(item.change == "resolved" and item.alert is not None and item.alert.alert_id == opened.alert_id for item in changes)
