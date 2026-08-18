from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field

from ansich.assessment.base import Assessment, AuthorityClass, EvidenceRef
from ansich.contracts import NamedVersion

DEFAULT_RESOLVER = NamedVersion(name="ansich-default", version="2.0.0")
RESOLVER_V1 = NamedVersion(name="ansich-default", version="1.0.0")

# Retained verbatim so v1 resolutions stay reproducible via the explicit
# ``resolver=RESOLVER_V1`` argument. ``soft_human`` is deliberately absent.
_AUTHORITY_PRIORITY_V1: dict[AuthorityClass, int] = {
    "human_override": 4,
    "deterministic": 3,
    "configured_rule": 2,
    "automated": 1,
}
_AUTHORITY_PRIORITY_V2: dict[AuthorityClass, int] = {
    "human_override": 5,
    "deterministic": 4,
    "configured_rule": 3,
    "soft_human": 2,
    "automated": 1,
}
_AUTHORITY_PRIORITY_BY_VERSION: dict[str, dict[AuthorityClass, int]] = {
    RESOLVER_V1.version: _AUTHORITY_PRIORITY_V1,
    DEFAULT_RESOLVER.version: _AUTHORITY_PRIORITY_V2,
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
    conflicting_assertion_count: int = Field(ge=0)


def resolve_current_belief(
    assertions: Sequence[BeliefAssertion],
    *,
    resolver: NamedVersion = DEFAULT_RESOLVER,
) -> ResolvedBelief:
    if not assertions:
        raise ValueError("at least one Belief Assertion is required")
    priority = _AUTHORITY_PRIORITY_BY_VERSION.get(resolver.version)
    if priority is None:
        raise ValueError(f"unsupported belief resolver {resolver.name}@{resolver.version}")
    subject_id = assertions[0].subject_id
    field_name = assertions[0].field_name
    if any(item.subject_id != subject_id or item.field_name != field_name for item in assertions):
        raise ValueError("Belief Assertions must share subject and field")
    for item in assertions:
        if item.authority_class not in priority:
            raise ValueError(f"authority class {item.authority_class} is not resolvable under {resolver.name}@{resolver.version}")

    selected = max(
        assertions,
        key=lambda item: (
            priority[item.authority_class],
            item.as_of,
            item.asserted_at,
            item.assertion_id,
        ),
    )
    return ResolvedBelief(
        subject_id=subject_id,
        field_name=field_name,
        selected=selected,
        resolver=resolver,
        evidence=selected.evidence,
        conflicting_assertion_count=len(assertions) - 1,
    )
