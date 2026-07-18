from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from ansich.assessment.base import (
    Assessment,
    AssessorDescriptor,
    EvidenceRef,
    canonical_config_hash,
    canonical_json_bytes,
)
from ansich.contracts import NamedVersion

ACTION_REPETITION_ASSESSOR = AssessorDescriptor(
    name="action-repetition",
    version="1.0.0",
    input_observation_kinds=("step.closed", "tool.issued"),
    output_field="behavior",
    authority_class="configured_rule",
    fidelity_class="rule",
)


def tool_action_signature(
    tool_name: str,
    args: object,
    *,
    known_secrets: Sequence[str] = (),
) -> str:
    payload = {
        "tool": tool_name,
        "args": args,
    }
    return hashlib.sha256(
        canonical_json_bytes(
            payload,
            filter_secret_fields=True,
            known_secrets=known_secrets,
        )
    ).hexdigest()


def step_action_signature(tool_signatures: Sequence[str]) -> str:
    return hashlib.sha256(canonical_json_bytes({"tools": sorted(tool_signatures)})).hexdigest()


class ToolAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    tool_name: str = Field(min_length=1)
    args: object
    evidence_obs_id: str = Field(min_length=1)
    known_secrets: tuple[str, ...] = ()

    @property
    def signature(self) -> str:
        return tool_action_signature(
            self.tool_name,
            self.args,
            known_secrets=self.known_secrets,
        )


class StepAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    step_id: str = Field(min_length=1)
    step_seq: int = Field(ge=1)
    occurred_at: datetime
    signature: str = Field(pattern=r"^[0-9a-f]{64}$")
    tool_signatures: tuple[str, ...]
    evidence: tuple[EvidenceRef, ...]


def build_step_action(
    *,
    step_id: str,
    step_seq: int,
    occurred_at: datetime,
    tools: Sequence[ToolAction],
) -> StepAction:
    ordered = sorted(
        ((tool.signature, tool.evidence_obs_id) for tool in tools),
        key=lambda item: (item[0], item[1]),
    )
    signatures = tuple(signature for signature, _ in ordered)
    return StepAction(
        step_id=step_id,
        step_seq=step_seq,
        occurred_at=occurred_at,
        signature=step_action_signature(signatures),
        tool_signatures=signatures,
        evidence=tuple(EvidenceRef(obs_id=obs_id) for _, obs_id in ordered),
    )


def assess_action_repetition(
    *,
    task_id: str,
    steps: Sequence[StepAction],
    now: datetime,
    exact_repetition_window: int,
) -> Assessment:
    if exact_repetition_window < 2:
        raise ValueError("exact_repetition_window must be at least two")
    ordered = sorted(steps, key=lambda item: item.step_seq)
    if len({step.step_seq for step in ordered}) != len(ordered):
        raise ValueError("Step sequence must be unique")
    config_hash = canonical_config_hash({"exact_repetition_window": exact_repetition_window})
    if not ordered or not ordered[-1].tool_signatures:
        return Assessment(
            subject_id=task_id,
            field_name="behavior",
            value={
                "value": "unassessed",
                "reason": "no_tool_action",
                "repeat_count": 0,
                "window": exact_repetition_window,
                "shadow": False,
            },
            as_of=now if not ordered else ordered[-1].occurred_at,
            asserted_at=now,
            assessor=NamedVersion(
                name=ACTION_REPETITION_ASSESSOR.name,
                version=ACTION_REPETITION_ASSESSOR.version,
            ),
            config_hash=config_hash,
            authority_class=ACTION_REPETITION_ASSESSOR.authority_class,
            fidelity_class=ACTION_REPETITION_ASSESSOR.fidelity_class,
        )

    last_signature = ordered[-1].signature
    repeated: list[StepAction] = []
    for step in reversed(ordered):
        if not step.tool_signatures or step.signature != last_signature:
            break
        repeated.append(step)
    repeated.reverse()
    repeat_count = len(repeated)
    runaway = repeat_count >= exact_repetition_window
    supporting_steps = repeated[-exact_repetition_window:] if runaway else repeated
    return Assessment(
        subject_id=task_id,
        field_name="behavior",
        value={
            "value": "runaway" if runaway else "unassessed",
            "reason": ("exact_repetition" if runaway else "exact_repetition_not_met"),
            "repeat_count": repeat_count,
            "window": exact_repetition_window,
            "signature": last_signature,
            "shadow": False,
        },
        as_of=ordered[-1].occurred_at,
        asserted_at=now,
        assessor=NamedVersion(
            name=ACTION_REPETITION_ASSESSOR.name,
            version=ACTION_REPETITION_ASSESSOR.version,
        ),
        config_hash=config_hash,
        authority_class=ACTION_REPETITION_ASSESSOR.authority_class,
        fidelity_class=ACTION_REPETITION_ASSESSOR.fidelity_class,
        evidence=tuple(evidence for step in supporting_steps for evidence in step.evidence),
    )
