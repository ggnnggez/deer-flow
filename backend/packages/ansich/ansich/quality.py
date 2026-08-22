"""Release quality read models and the pure cohort comparability rules.

Framework-independent by construction: this module owns the decision of *when*
two AgentReleases may be compared on semantic quality, so the rule cannot drift
between the HTTP layer and a UI. Loading the cells is the storage adapter's job.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ansich.belief.resolver import DEFAULT_RESOLVER
from ansich.contracts import NamedVersion

ComparisonStatus = Literal["comparable", "not_comparable"]
#: Machine-readable refusals. A caller must be able to branch on why a
#: comparison was declined without parsing prose.
ComparisonReason = Literal[
    "no_shared_cohort",
    "scale_mismatch",
    "insufficient_samples",
    "observability_loss",
]
COMPARISON_REASONS: tuple[ComparisonReason, ...] = (
    "no_shared_cohort",
    "scale_mismatch",
    "insufficient_samples",
    "observability_loss",
)
#: Evaluations that declare no cohort aggregate under this sentinel. It is a
#: sample list, never a comparison population: the same key on two releases says
#: nothing about the two sample sets sharing a suite, version, or case set.
NO_COHORT_KEY = ""


class ReleaseQualityDimensionView(BaseModel):
    """One ``(cohort, dimension)`` quality cell of one AgentRelease."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    dimension: str
    cohort_key: str
    assessed_count: int = Field(ge=0)
    pass_count: int = Field(ge=0)
    fail_count: int = Field(ge=0)
    partial_count: int = Field(ge=0)
    mean_score: float | None = None
    scale: dict[str, object] | None = None
    as_of: datetime


class ReleaseQualityView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    release_id: str
    cohorts: tuple[ReleaseQualityDimensionView, ...] = ()


class QualityComparisonView(BaseModel):
    """One dimension of a release-to-release quality comparison.

    ``observed_delta`` is exactly that — an observed difference, never a
    significance claim. It is populated only when the pair is comparable.

    ``resolver`` names **the Belief resolver this store currently selects
    with** — the active-version selection, or the code default when nothing was
    activated — and it is deliberately not a per-cell claim. Each aggregated
    assertion carries its own resolver on its ``ansich_current_beliefs`` row,
    and after an active-version switch (or during the bounded window in which
    two workers have not yet converged on one) those rows can legitimately
    disagree with each other and with this field. Read it as "the precedence
    semantics in force for this comparison", never as "the version that
    selected every assertion underneath it"; the per-row stamp is where that
    question is answered.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    dimension: str
    cohort_key: str
    comparison_status: ComparisonStatus
    reason: str | None = None
    observed_delta: float | None = None
    left_sample_count: int = Field(ge=0)
    right_sample_count: int = Field(ge=0)
    coverage: dict[str, object]
    resolver: NamedVersion


def compare_release_quality(
    left: Sequence[ReleaseQualityDimensionView],
    right: Sequence[ReleaseQualityDimensionView],
    *,
    min_samples: int,
    unexplained_loss: bool,
    resolver: NamedVersion = DEFAULT_RESOLVER,
) -> tuple[QualityComparisonView, ...]:
    """Compare two releases' quality cells under the cohort comparability rules.

    A pair is comparable only when every condition holds: the same non-empty
    cohort key (so the same suite/version/case set or an explicitly declared
    cohort), the same dimension, the same score scale, at least ``min_samples``
    assessed samples on both sides, and no unexplained observability loss.
    Every other outcome is ``not_comparable`` with a specific machine-readable
    ``reason`` — the point is to decline the comparison, not to average all
    production Tasks together.

    Reason precedence follows the order the conditions are written in the
    specification (cohort, then scale, then samples, then loss), so a pair that
    fails several conditions reports the earliest one; the coverage block always
    carries the full picture, including ``unexplained_loss``.

    The delta is ``right - left`` on the mean score when both sides carry one,
    and on the pass rate (``pass_count / assessed_count``) otherwise, which is
    the only comparable summary a verdict-only cohort has.

    ``resolver`` is stamped onto every comparison and defaults to the code
    default. A caller with a store to consult should pass that store's **active**
    resolver instead: since the active-version row exists, the build's default
    and what the store actually selects with are two different facts, and
    reading a constant here while the store had been switched made the field a
    claim nobody had checked. This module stays framework-independent — it takes
    the answer, it does not go looking for it.
    """

    left_cells = {(cell.dimension, cell.cohort_key): cell for cell in left}
    right_cells = {(cell.dimension, cell.cohort_key): cell for cell in right}
    comparisons: list[QualityComparisonView] = []
    for dimension, cohort_key in sorted(left_cells.keys() | right_cells.keys()):
        left_cell = left_cells.get((dimension, cohort_key))
        right_cell = right_cells.get((dimension, cohort_key))
        reason = _comparison_reason(
            left_cell,
            right_cell,
            cohort_key=cohort_key,
            min_samples=min_samples,
            unexplained_loss=unexplained_loss,
        )
        comparisons.append(
            QualityComparisonView(
                dimension=dimension,
                cohort_key=cohort_key,
                comparison_status="not_comparable" if reason is not None else "comparable",
                reason=reason,
                observed_delta=None if reason is not None else _observed_delta(left_cell, right_cell),
                left_sample_count=0 if left_cell is None else left_cell.assessed_count,
                right_sample_count=0 if right_cell is None else right_cell.assessed_count,
                coverage=_coverage(
                    left_cell,
                    right_cell,
                    min_samples=min_samples,
                    unexplained_loss=unexplained_loss,
                ),
                # The resolver in force for this comparison; see the field's
                # note on why that is not the same as "what selected every
                # assertion underneath".
                resolver=resolver,
            )
        )
    return tuple(comparisons)


def _comparison_reason(
    left: ReleaseQualityDimensionView | None,
    right: ReleaseQualityDimensionView | None,
    *,
    cohort_key: str,
    min_samples: int,
    unexplained_loss: bool,
) -> ComparisonReason | None:
    if cohort_key == NO_COHORT_KEY:
        return "no_shared_cohort"
    if left is None or right is None:
        return "no_shared_cohort"
    if left.scale != right.scale:
        # Includes a scored cohort facing a verdict-only one: different
        # measurements, not a smaller sample of the same measurement.
        return "scale_mismatch"
    if left.assessed_count < min_samples or right.assessed_count < min_samples:
        return "insufficient_samples"
    if unexplained_loss:
        return "observability_loss"
    return None


def _observed_delta(
    left: ReleaseQualityDimensionView | None,
    right: ReleaseQualityDimensionView | None,
) -> float | None:
    if left is None or right is None:
        return None
    if left.mean_score is not None and right.mean_score is not None:
        return right.mean_score - left.mean_score
    left_rate = _pass_rate(left)
    right_rate = _pass_rate(right)
    if left_rate is None or right_rate is None:
        return None
    return right_rate - left_rate


def _pass_rate(cell: ReleaseQualityDimensionView) -> float | None:
    if cell.assessed_count <= 0:
        return None
    return cell.pass_count / cell.assessed_count


def _coverage(
    left: ReleaseQualityDimensionView | None,
    right: ReleaseQualityDimensionView | None,
    *,
    min_samples: int,
    unexplained_loss: bool,
) -> dict[str, object]:
    return {
        "min_samples": min_samples,
        "unexplained_loss": unexplained_loss,
        "left": _cell_coverage(left),
        "right": _cell_coverage(right),
    }


def _cell_coverage(cell: ReleaseQualityDimensionView | None) -> dict[str, object]:
    if cell is None:
        return {
            "present": False,
            "assessed_count": 0,
            "pass_count": 0,
            "fail_count": 0,
            "partial_count": 0,
            "mean_score": None,
            "scale": None,
            "as_of": None,
        }
    return {
        "present": True,
        "assessed_count": cell.assessed_count,
        "pass_count": cell.pass_count,
        "fail_count": cell.fail_count,
        "partial_count": cell.partial_count,
        "mean_score": cell.mean_score,
        "scale": None if cell.scale is None else dict(cell.scale),
        "as_of": cell.as_of.isoformat(),
    }
