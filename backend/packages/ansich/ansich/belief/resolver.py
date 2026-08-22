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
    #: Retained Assertions this resolution did **not** select. It counts rows,
    #: not disagreements, and the distinction is load-bearing: two Assertions
    #: carrying the *same* value still count as one conflict here, because the
    #: field's question is "how much was retained and set aside", not "how many
    #: rivals disagreed". ``test_conflicting_assertion_count_counts_retained_non_selected_assertions``
    #: pins exactly that, with four same-valued Assertions counting three.
    #:
    #: One consequence is worth knowing before reading a number off a panel
    #: (F10-35): a first-write race on the operations tick leaves an extra
    #: same-verdict Assertion behind — one per losing writer — and each of those
    #: raises this count by one. A `heartbeat` Belief can therefore report a
    #: conflict when nothing ever disagreed about the heartbeat. That is not a
    #: miscount under the definition above, but it does mean a small non-zero
    #: count on a periodic Belief is as likely to be a past collision as a real
    #: dispute. Narrowing the field to "disagreeing Assertions" would be a
    #: different contract than the one this codebase, its pin, and the frontend's
    #: conflict badge already carry, so it is deliberately not done here.
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
