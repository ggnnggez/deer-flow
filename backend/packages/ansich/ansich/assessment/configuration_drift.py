from __future__ import annotations

from datetime import datetime
from typing import Literal

from ansich.assessment.base import (
    Assessment,
    AssessorDescriptor,
    EvidenceRef,
    canonical_config_hash,
)
from ansich.contracts import NamedVersion

CONFIGURATION_DRIFT_ASSESSOR = AssessorDescriptor(
    name="configuration-drift",
    version="1.1.0",
    input_observation_kinds=("agent_release.resolved", "llm.responded"),
    output_field="configuration_drift",
    authority_class="configured_rule",
    fidelity_class="rule",
)


def _normalized_model(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if not normalized:
        return None
    return normalized.removeprefix("models/")


def assess_configuration_drift(
    *,
    task_id: str,
    effective_model: str,
    expected_model_source: Literal["provider_model", "registry_alias"],
    provider_reported_model: str | None,
    response_obs_id: str | None,
    as_of: datetime,
    asserted_at: datetime,
) -> Assessment:
    expected = _normalized_model(effective_model)
    reported = _normalized_model(provider_reported_model)
    if reported is None or expected is None:
        value = "unknown"
    elif expected == reported or reported.endswith(f"/{expected}"):
        value = "matched"
    elif expected_model_source == "registry_alias":
        value = "unknown"
    elif any(reported.startswith(f"{expected}{separator}") for separator in ("-", ".", ":")):
        value = "matched"
    else:
        value = "mismatch"
    evidence = () if response_obs_id is None else (EvidenceRef(obs_id=response_obs_id, role="provider_report"),)
    return Assessment(
        subject_id=task_id,
        field_name="configuration_drift",
        value={
            "value": value,
            "effective_model": effective_model,
            "expected_model_source": expected_model_source,
            "provider_reported_model": provider_reported_model,
        },
        as_of=as_of,
        asserted_at=asserted_at,
        assessor=NamedVersion(
            name=CONFIGURATION_DRIFT_ASSESSOR.name,
            version=CONFIGURATION_DRIFT_ASSESSOR.version,
        ),
        config_hash=canonical_config_hash(
            {
                "normalization": "lowercase-strip-models-prefix-provider-revision-v2",
                "revision_separators": ["-", ".", ":"],
            }
        ),
        authority_class=CONFIGURATION_DRIFT_ASSESSOR.authority_class,
        fidelity_class=CONFIGURATION_DRIFT_ASSESSOR.fidelity_class,
        evidence=evidence,
    )


__all__ = ["CONFIGURATION_DRIFT_ASSESSOR", "assess_configuration_drift"]
