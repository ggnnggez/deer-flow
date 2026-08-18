from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from ansich import AuthorizationSnapshot, ToolEffect
from ansich.alerts import alert_conditions_from_assessment
from ansich.assessment.scope_safety import assess_scope_safety


def _snapshot(*, decision: str, resource_scope_ids: tuple[str, ...] = ()):
    return AuthorizationSnapshot(
        snapshot_id=f"snapshot-{decision}",
        tool_call_id="tool-call",
        policy_id="policy",
        policy_version="1",
        policy_hash="a" * 64,
        decision=decision,
        details_available=bool(resource_scope_ids),
        resource_scope_ids=resource_scope_ids,
        reason_codes=(decision,),
        evaluated_at=datetime.now(UTC),
        evidence_obs_ids=(f"auth-{decision}",),
    )


def _effect(
    effect_class: str,
    phase: str,
    *,
    scope_id: str | None = None,
    source_obs_id: str,
):
    return ToolEffect(
        effect_id=f"effect-{source_obs_id}",
        tool_call_id="tool-call",
        effect_class=effect_class,
        phase=phase,
        scope_id=scope_id,
        fidelity_class="hard" if effect_class != "unknown" else "unknown",
        source_obs_id=source_obs_id,
    )


def _present(result) -> set[str]:
    return {item.value["conclusion"] for item in result.conclusions if item.value["value"] == "present"}


def test_explicit_deny_is_policy_denial_but_not_realized_violation() -> None:
    result = assess_scope_safety(
        tool_call_id="tool-call",
        authorization_snapshots=(_snapshot(decision="denied"),),
        effects=(
            _effect(
                "filesystem_write",
                "intended",
                scope_id="outside",
                source_obs_id="intent",
            ),
        ),
        now=datetime.now(UTC),
    )

    assert _present(result) == {"policy_denial"}


def test_observed_effect_outside_allowed_resource_scope_is_realized_violation() -> None:
    result = assess_scope_safety(
        tool_call_id="tool-call",
        authorization_snapshots=(_snapshot(decision="allowed", resource_scope_ids=("workspace",)),),
        effects=(
            _effect(
                "filesystem_write",
                "intended",
                scope_id="outside",
                source_obs_id="intent",
            ),
            _effect(
                "filesystem_write",
                "observed",
                scope_id="outside",
                source_obs_id="observed",
            ),
        ),
        now=datetime.now(UTC),
    )

    assert _present(result) == {"realized_scope_violation"}


def test_unknown_observed_effect_is_unverified_not_realized() -> None:
    result = assess_scope_safety(
        tool_call_id="tool-call",
        authorization_snapshots=(_snapshot(decision="unknown"),),
        effects=(
            _effect("unknown", "potential", source_obs_id="potential"),
            _effect("unknown", "observed", source_obs_id="observed"),
        ),
        now=datetime.now(UTC),
    )

    assert _present(result) == {"unverified_effect"}
    unverified = next(item for item in result.conclusions if item.value["conclusion"] == "unverified_effect")
    conditions = alert_conditions_from_assessment(
        unverified,
        source_assertion_id="assertion-unverified",
    )
    assert len(conditions) == 1
    assert conditions[0].alert_type == "unverified_effect"
    assert conditions[0].active is True


def test_hard_observed_effect_clears_unverified_when_no_unknown_range_remains() -> None:
    result = assess_scope_safety(
        tool_call_id="tool-call",
        authorization_snapshots=(_snapshot(decision="allowed", resource_scope_ids=("workspace",)),),
        effects=(
            _effect("filesystem_read", "potential", source_obs_id="potential"),
            _effect(
                "filesystem_read",
                "observed",
                scope_id="workspace",
                source_obs_id="observed",
            ),
        ),
        now=datetime.now(UTC),
    )

    assert _present(result) == set()
    assert all(item.value["value"] == "cleared" for item in result.conclusions)


@pytest.mark.parametrize("effect_class", ["filesystem_delete", "permission_change"])
def test_new_effect_classes_are_concrete_not_unknown_handled(effect_class: str) -> None:
    """`filesystem_delete`/`permission_change` must count as concrete observations."""

    result = assess_scope_safety(
        tool_call_id="tool-call",
        authorization_snapshots=(_snapshot(decision="allowed", resource_scope_ids=("workspace",)),),
        effects=(
            _effect(effect_class, "potential", source_obs_id="potential"),
            _effect(effect_class, "intended", scope_id="workspace", source_obs_id="intent"),
            _effect(effect_class, "observed", scope_id="workspace", source_obs_id="observed"),
        ),
        now=datetime.now(UTC),
    )

    assert _present(result) == set()
    assert all(item.value["value"] == "cleared" for item in result.conclusions)


@pytest.mark.parametrize("effect_class", ["filesystem_delete", "permission_change"])
def test_new_effect_classes_outside_allowed_scope_are_realized_violations(effect_class: str) -> None:
    result = assess_scope_safety(
        tool_call_id="tool-call",
        authorization_snapshots=(_snapshot(decision="allowed", resource_scope_ids=("workspace",)),),
        effects=(
            _effect(effect_class, "intended", scope_id="outside", source_obs_id="intent"),
            _effect(effect_class, "observed", scope_id="outside", source_obs_id="observed"),
        ),
        now=datetime.now(UTC),
    )

    assert _present(result) == {"realized_scope_violation"}


def test_latest_authorization_snapshot_supersedes_an_older_denial() -> None:
    older_denial = _snapshot(decision="denied")
    latest_allow = _snapshot(
        decision="allowed",
        resource_scope_ids=("workspace",),
    ).model_copy(
        update={
            "snapshot_id": "snapshot-latest-allow",
            "evaluated_at": older_denial.evaluated_at + timedelta(microseconds=1),
        }
    )
    result = assess_scope_safety(
        tool_call_id="tool-call",
        authorization_snapshots=(older_denial, latest_allow),
        effects=(
            _effect(
                "filesystem_read",
                "intended",
                scope_id="workspace",
                source_obs_id="intent",
            ),
            _effect(
                "filesystem_read",
                "observed",
                scope_id="workspace",
                source_obs_id="observed",
            ),
        ),
        now=datetime.now(UTC),
    )

    assert _present(result) == set()


def test_bool_only_allow_cannot_verify_a_concrete_observed_effect_scope() -> None:
    result = assess_scope_safety(
        tool_call_id="tool-call",
        authorization_snapshots=(_snapshot(decision="allowed"),),
        effects=(
            _effect(
                "filesystem_write",
                "intended",
                source_obs_id="intent",
            ),
            _effect(
                "filesystem_write",
                "observed",
                source_obs_id="observed",
            ),
        ),
        now=datetime.now(UTC),
    )

    assert _present(result) == {"unverified_effect"}


def test_unknown_decision_does_not_produce_policy_denial() -> None:
    result = assess_scope_safety(
        tool_call_id="tool-call",
        authorization_snapshots=(_snapshot(decision="unknown"),),
        effects=(),
        now=datetime.now(UTC),
    )
    assert "policy_denial" not in _present(result)


def test_allowed_but_blocked_call_does_not_produce_policy_denial() -> None:
    # A guardrail-allowed call blocked downstream still records decision="allowed";
    # scope-safety must not read that as a policy denial (H1).
    result = assess_scope_safety(
        tool_call_id="tool-call",
        authorization_snapshots=(_snapshot(decision="allowed"),),
        effects=(),
        now=datetime.now(UTC),
    )
    assert "policy_denial" not in _present(result)
