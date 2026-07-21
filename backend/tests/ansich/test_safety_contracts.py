from __future__ import annotations

from datetime import UTC, datetime

import pytest
from ansich import (
    AnsichService,
    AuthorizationPermission,
    AuthorizationSnapshot,
    ObservationEnvelope,
    Producer,
    ScopeDescriptor,
    ToolEffect,
    new_id,
    scope_entity_id,
    scope_reference_hash,
)
from pydantic import ValidationError


def test_scope_descriptor_keeps_only_stable_hash_and_controlled_label() -> None:
    absolute_workspace = "/srv/tenants/acme/private-project"

    scope = ScopeDescriptor(
        scope_id="scope-1",
        scope_kind="workspace",
        external_ref_hash=scope_reference_hash("workspace", absolute_workspace),
        display_label="workspace",
        created_obs_id="obs-1",
    )

    encoded = scope.model_dump_json()
    assert scope.external_ref_hash == scope_reference_hash("workspace", absolute_workspace)
    assert absolute_workspace not in encoded
    assert len(scope.external_ref_hash) == 64


@pytest.mark.anyio
async def test_memory_and_sql_backends_share_deterministic_scope_identity() -> None:
    service = AnsichService.in_memory()
    await service.start()
    task_id = new_id()
    workspace = "/srv/tenants/acme/private-project"
    try:
        service.record(
            ObservationEnvelope.task_lifecycle(
                kind="task.created",
                task_id=task_id,
                source_kind="deerflow_run",
                source_id="scope-memory-run",
                occurred_at=datetime.now(UTC),
                source_event_id="scope-memory:created",
                attributes={"workspace_ref": workspace},
            )
        )
        await service.flush_task(task_id)
        scopes = await service.get_task_scopes(task_id)
    finally:
        await service.stop()

    workspace_scope = next(item for item in scopes.scopes if item.scope_kind == "workspace")
    expected_hash = scope_reference_hash("workspace", workspace)
    assert workspace_scope.scope_id == scope_entity_id("workspace", expected_hash)


def test_bool_only_authorization_cannot_invent_effective_permissions() -> None:
    with pytest.raises(ValidationError, match="details_available=false"):
        AuthorizationSnapshot(
            snapshot_id="snapshot-1",
            tool_call_id="tool-call-1",
            principal_scope_ids=("owner-scope",),
            policy_id="sandbox-policy",
            policy_version="1",
            policy_hash="a" * 64,
            decision="allowed",
            details_available=False,
            effective_permissions=(
                AuthorizationPermission(
                    resource="workspace",
                    action="write",
                    scope_id="workspace-scope",
                    effect="filesystem_write",
                ),
            ),
            resource_scope_ids=("workspace-scope",),
            reason_codes=("provider_bool_only",),
            evaluated_at=datetime.now(UTC),
            evidence_obs_ids=("obs-1",),
        )


def test_authorization_snapshot_rejects_credential_like_resource_values() -> None:
    with pytest.raises(ValidationError, match="credential-like material"):
        AuthorizationSnapshot(
            snapshot_id="snapshot-1",
            tool_call_id="tool-call-1",
            policy_id="sandbox-policy",
            policy_version="1",
            policy_hash="a" * 64,
            decision="denied",
            details_available=True,
            effective_permissions=(
                AuthorizationPermission(
                    resource="Authorization: Bearer abcdefghijklmnopqrstuvwxyz012345",
                    action="read",
                    effect="network_read",
                ),
            ),
            reason_codes=("policy_denied",),
            evaluated_at=datetime.now(UTC),
            evidence_obs_ids=("obs-1",),
        )


def test_tool_effect_requires_explicit_phase_class_and_fidelity() -> None:
    effect = ToolEffect(
        effect_id="effect-1",
        tool_call_id="tool-call-1",
        effect_class="filesystem_write",
        phase="observed",
        scope_id="sandbox-scope",
        target_hash="b" * 64,
        target_preview="workspace/report.md",
        fidelity_class="hard",
        source_obs_id="obs-1",
        result_metadata={"status": "written"},
    )

    assert effect.phase == "observed"
    assert effect.effect_class == "filesystem_write"
    assert effect.fidelity_class == "hard"


def test_tool_effect_rejects_credential_like_target_or_result_metadata() -> None:
    with pytest.raises(ValidationError, match="credential-like material"):
        ToolEffect(
            effect_id="effect-secret",
            tool_call_id="tool-call-1",
            effect_class="network_read",
            phase="observed",
            target_preview="Authorization: Bearer abcdefghijklmnopqrstuvwxyz012345",
            fidelity_class="hard",
            source_obs_id="obs-secret",
            result_metadata={"status": "read"},
        )

    with pytest.raises(ValidationError, match="credential-like material"):
        ToolEffect(
            effect_id="effect-secret-metadata",
            tool_call_id="tool-call-1",
            effect_class="external_write",
            phase="observed",
            target_preview="remote-record",
            fidelity_class="hard",
            source_obs_id="obs-secret-metadata",
            result_metadata={"credential": "abcdefghijklmnopqrstuvwxyz012345"},
        )


def test_safety_observation_rejects_decision_kind_that_conflicts_with_snapshot() -> None:
    task_id = new_id()
    tool_call_id = new_id()
    snapshot = AuthorizationSnapshot(
        snapshot_id=new_id(),
        tool_call_id=tool_call_id,
        policy_id="sandbox-policy",
        policy_version="1",
        policy_hash="a" * 64,
        decision="denied",
        details_available=False,
        reason_codes=("outside_workspace",),
        evaluated_at=datetime.now(UTC),
        evidence_obs_ids=(),
    )

    with pytest.raises(ValidationError, match="does not match snapshot decision"):
        ObservationEnvelope(
            kind="authorization.allowed",
            occurred_at=datetime.now(UTC),
            task_id=task_id,
            subject_type="authorization_snapshot",
            subject_id=snapshot.snapshot_id,
            producer=Producer(name="authz-probe", version="1", instance_id="worker"),
            source_event_id="authorization:allowed",
            correlation_id="run-1",
            payload={"snapshot": snapshot.model_dump(mode="json")},
        )


def test_safety_observation_rejects_effect_kind_that_conflicts_with_phase() -> None:
    task_id = new_id()
    tool_call_id = new_id()
    effect = ToolEffect(
        effect_id=new_id(),
        tool_call_id=tool_call_id,
        effect_class="process_execute",
        phase="intended",
        fidelity_class="declared",
        source_obs_id=new_id(),
    )

    with pytest.raises(ValidationError, match="does not match effect phase"):
        ObservationEnvelope(
            kind="effect.observed",
            occurred_at=datetime.now(UTC),
            task_id=task_id,
            subject_type="effect",
            subject_id=effect.effect_id,
            producer=Producer(name="effect-probe", version="1", instance_id="worker"),
            source_event_id="effect:observed",
            correlation_id="run-1",
            payload={"effect": effect.model_dump(mode="json")},
        )
