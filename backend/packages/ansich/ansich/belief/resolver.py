from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field

from ansich.assessment.base import Assessment, AuthorityClass, EvidenceRef
from ansich.contracts import NamedVersion

DEFAULT_RESOLVER = NamedVersion(name="ansich-default", version="1.0.0")
_AUTHORITY_PRIORITY: dict[AuthorityClass, int] = {
    "human_override": 4,
    "deterministic": 3,
    "configured_rule": 2,
    "automated": 1,
}


class BeliefAssertion(Assessment):
    assertion_id: str = Field(min_length=1)

    @classmethod
    def from_assessment(
        cls,
        assessment: Assessment,
        *,
        assertion_id: str,
    ) -> BeliefAssertion:
        return cls(
            assertion_id=assertion_id,
            **assessment.model_dump(),
        )


class ResolvedBelief(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    subject_id: str
    field_name: str
    selected: BeliefAssertion
    resolver: NamedVersion
    evidence: tuple[EvidenceRef, ...]


def resolve_current_belief(
    assertions: Sequence[BeliefAssertion],
) -> ResolvedBelief:
    if not assertions:
        raise ValueError("at least one Belief Assertion is required")
    subject_id = assertions[0].subject_id
    field_name = assertions[0].field_name
    if any(item.subject_id != subject_id or item.field_name != field_name for item in assertions):
        raise ValueError("Belief Assertions must share subject and field")

    selected = max(
        assertions,
        key=lambda item: (
            _AUTHORITY_PRIORITY[item.authority_class],
            item.as_of,
            item.asserted_at,
            item.assertion_id,
        ),
    )
    return ResolvedBelief(
        subject_id=subject_id,
        field_name=field_name,
        selected=selected,
        resolver=DEFAULT_RESOLVER,
        evidence=selected.evidence,
    )
