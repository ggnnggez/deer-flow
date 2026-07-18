from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ansich.assessment.base import (
    Assessment,
    AssessorDescriptor,
    EvidenceRef,
    canonical_config_hash,
)
from ansich.contracts import NamedVersion

TOOL_FREQUENCY_ASSESSOR = AssessorDescriptor(
    name="tool-frequency",
    version="1.0.0",
    input_observation_kinds=("tool.issued",),
    output_field="tool_frequency:*",
    authority_class="configured_rule",
    fidelity_class="rule",
)


class ToolOccurrence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    tool_name: str = Field(min_length=1)
    occurred_at: datetime
    evidence_obs_id: str = Field(min_length=1)

    @field_validator("occurred_at")
    @classmethod
    def _occurred_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Tool occurrence timestamp must be timezone-aware")
        return value


def assess_tool_frequency(
    *,
    task_id: str,
    occurrences: Sequence[ToolOccurrence],
    now: datetime,
    window_seconds: int,
    threshold: int,
) -> tuple[Assessment, ...]:
    if window_seconds < 1:
        raise ValueError("window_seconds must be positive")
    if threshold < 1:
        raise ValueError("threshold must be positive")
    lower_bound = now - timedelta(seconds=window_seconds)
    grouped: dict[str, list[ToolOccurrence]] = defaultdict(list)
    for occurrence in occurrences:
        if lower_bound <= occurrence.occurred_at <= now:
            grouped[occurrence.tool_name].append(occurrence)

    assessments: list[Assessment] = []
    for tool_name in sorted(grouped):
        items = sorted(
            grouped[tool_name],
            key=lambda item: (item.occurred_at, item.evidence_obs_id),
        )
        config_hash = canonical_config_hash(
            {
                "tool_name": tool_name,
                "window_seconds": window_seconds,
                "threshold": threshold,
            }
        )
        assessments.append(
            Assessment(
                subject_id=task_id,
                field_name=f"tool_frequency:{tool_name}",
                value={
                    "value": "high" if len(items) >= threshold else "normal",
                    "tool_name": tool_name,
                    "count": len(items),
                    "window_seconds": window_seconds,
                    "threshold": threshold,
                    "shadow": False,
                },
                as_of=items[-1].occurred_at,
                asserted_at=now,
                assessor=NamedVersion(
                    name=TOOL_FREQUENCY_ASSESSOR.name,
                    version=TOOL_FREQUENCY_ASSESSOR.version,
                ),
                config_hash=config_hash,
                authority_class=TOOL_FREQUENCY_ASSESSOR.authority_class,
                fidelity_class=TOOL_FREQUENCY_ASSESSOR.fidelity_class,
                evidence=tuple(EvidenceRef(obs_id=item.evidence_obs_id) for item in items),
            )
        )
    return tuple(assessments)
