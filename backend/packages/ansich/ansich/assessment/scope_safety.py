from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from ansich.assessment.base import (
    Assessment,
    AssessorDescriptor,
    EvidenceRef,
    canonical_config_hash,
)
from ansich.contracts import NamedVersion
from ansich.safety import AuthorizationSnapshot, ToolEffect

ScopeConclusionKind = Literal[
    "policy_denial",
    "attempted_scope_violation",
    "realized_scope_violation",
    "unverified_effect",
]

SCOPE_SAFETY_ASSESSOR = AssessorDescriptor(
    name="scope-safety",
    version="1.0.0",
    input_observation_kinds=(
        "authorization.evaluated",
        "authorization.allowed",
        "authorization.denied",
        "authorization.unknown",
        "effect.potential",
        "effect.intended",
        "effect.observed",
    ),
    output_field="scope_safety:*",
    authority_class="configured_rule",
    fidelity_class="rule",
)


class ScopeSafetyAssessmentResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    conclusions: tuple[Assessment, ...]


def _evidence(*obs_id_groups: tuple[str, ...]) -> tuple[EvidenceRef, ...]:
    return tuple(EvidenceRef(obs_id=obs_id) for obs_id in dict.fromkeys(obs_id for group in obs_id_groups for obs_id in group if obs_id))


def assess_scope_safety(
    *,
    tool_call_id: str,
    authorization_snapshots: tuple[AuthorizationSnapshot, ...],
    effects: tuple[ToolEffect, ...],
    now: datetime,
) -> ScopeSafetyAssessmentResult:
    current_authorization = max(
        authorization_snapshots,
        key=lambda snapshot: (snapshot.evaluated_at, snapshot.snapshot_id),
        default=None,
    )
    denied = (current_authorization,) if current_authorization is not None and current_authorization.decision == "denied" else ()
    allowed = (current_authorization,) if current_authorization is not None and current_authorization.decision == "allowed" else ()
    allowed_scope_ids = frozenset(
        scope_id
        for snapshot in allowed
        for scope_id in (
            *snapshot.resource_scope_ids,
            *(permission.scope_id for permission in snapshot.effective_permissions if permission.scope_id is not None),
        )
    )
    intended = tuple(effect for effect in effects if effect.phase == "intended")
    observed = tuple(effect for effect in effects if effect.phase == "observed")
    concrete_observed = tuple(effect for effect in observed if effect.effect_class != "unknown")
    unknown_observed = tuple(effect for effect in observed if effect.effect_class == "unknown")
    outside_intents = tuple(effect for effect in intended if effect.scope_id is not None and bool(allowed_scope_ids) and effect.scope_id not in allowed_scope_ids)
    outside_observed = tuple(effect for effect in concrete_observed if effect.scope_id is not None and bool(allowed_scope_ids) and effect.scope_id not in allowed_scope_ids)
    attempted = tuple(effect for effect in outside_intents if denied or not any(observed_effect.effect_class == effect.effect_class and observed_effect.scope_id == effect.scope_id for observed_effect in concrete_observed))
    may_have_effect = bool(any(effect.phase in {"potential", "intended"} for effect in effects))
    authorization_incomplete = current_authorization is None or not current_authorization.details_available
    unverified = not denied and may_have_effect and (bool(unknown_observed) or not concrete_observed or authorization_incomplete)

    authorization_evidence = current_authorization.evidence_obs_ids if current_authorization is not None else ()
    evidence_by_kind: dict[ScopeConclusionKind, tuple[EvidenceRef, ...]] = {
        "policy_denial": _evidence(tuple(obs_id for item in denied for obs_id in item.evidence_obs_ids)),
        "attempted_scope_violation": _evidence(
            tuple(item.source_obs_id for item in attempted),
            authorization_evidence,
        ),
        "realized_scope_violation": _evidence(
            tuple(item.source_obs_id for item in outside_observed),
            authorization_evidence,
        ),
        "unverified_effect": _evidence(
            tuple(item.source_obs_id for item in effects if item.phase in {"potential", "intended"} or item.effect_class == "unknown"),
            authorization_evidence,
        ),
    }
    present: dict[ScopeConclusionKind, bool] = {
        "policy_denial": bool(denied),
        "attempted_scope_violation": bool(attempted),
        "realized_scope_violation": bool(outside_observed),
        "unverified_effect": unverified,
    }
    config_hash = canonical_config_hash(
        {
            "assessor": "scope-safety",
            "version": "1.0.0",
            "authority_order": [
                "hard_observed",
                "structured_authorization",
                "declared_potential",
            ],
        }
    )
    conclusions = tuple(
        Assessment(
            subject_id=tool_call_id,
            field_name=f"scope_safety:{kind}",
            value={
                "value": "present" if present[kind] else "cleared",
                "conclusion": kind,
            },
            as_of=now,
            asserted_at=now,
            assessor=NamedVersion(
                name=SCOPE_SAFETY_ASSESSOR.name,
                version=SCOPE_SAFETY_ASSESSOR.version,
            ),
            config_hash=config_hash,
            authority_class=SCOPE_SAFETY_ASSESSOR.authority_class,
            fidelity_class=SCOPE_SAFETY_ASSESSOR.fidelity_class,
            evidence=evidence_by_kind[kind],
        )
        for kind in (
            "policy_denial",
            "attempted_scope_violation",
            "realized_scope_violation",
            "unverified_effect",
        )
    )
    return ScopeSafetyAssessmentResult(conclusions=conclusions)
