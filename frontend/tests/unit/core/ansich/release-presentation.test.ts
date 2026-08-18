import { describe, expect, it } from "@rstest/core";

import {
  formatObservedDelta,
  getAgentReleaseDiffGroups,
  qualityComparisonReasonKey,
  qualityComparisonState,
  qualityScaleDirection,
} from "@/core/ansich/release-presentation";
import type {
  AnsichAgentReleaseComparison,
  AnsichQualityComparison,
} from "@/core/ansich/types";

function comparison(): AnsichAgentReleaseComparison {
  return {
    left_release_hash: "left",
    right_release_hash: "right",
    changed_components: ["model", "tools"],
    model: [{ path: "effective", left: "model-a", right: "model-b" }],
    prompt: [],
    tools: {
      added: [{ source: "builtin", name: "new_tool" }],
      removed: [],
      schema_changed: [],
      description_changed: [],
      source_changed: [
        {
          name: "search",
          left_source: "builtin",
          right_source: "mcp:web",
        },
      ],
    },
    policy: [],
    build: [],
    quality_status: "unassessed",
  };
}

describe("Agent release comparison presentation", () => {
  it("keeps typed tool source changes distinct and omits unchanged groups", () => {
    const groups = getAgentReleaseDiffGroups(comparison());

    expect(groups.map((group) => group.component)).toEqual(["model", "tools"]);
    expect(groups[1]?.items).toEqual([
      {
        kind: "added",
        path: "builtin:new_tool",
        left: null,
        right: "present",
      },
      {
        kind: "source_changed",
        path: "search",
        left: "builtin",
        right: "mcp:web",
      },
    ]);
  });
});

function qualityComparison(
  overrides: Partial<AnsichQualityComparison> = {},
): AnsichQualityComparison {
  return {
    dimension: "correctness",
    cohort_key: "ansich-regression@2026.08.1",
    comparison_status: "comparable",
    reason: null,
    observed_delta: 0.125,
    left_sample_count: 12,
    right_sample_count: 15,
    coverage: {
      min_samples: 5,
      unexplained_loss: false,
      left: { present: true, assessed_count: 12, scale: null },
      right: { present: true, assessed_count: 15, scale: null },
    },
    resolver: { name: "ansich-default", version: "2" },
    ...overrides,
  };
}

/** Build a coverage block whose two cells carry the given scale polarity. */
function coverageWithPolarity(
  left: boolean | null,
  right: boolean | null,
): Record<string, unknown> {
  const cell = (higherIsBetter: boolean | null) => ({
    present: true,
    assessed_count: 12,
    scale:
      higherIsBetter === null
        ? null
        : { min: 0, max: 1, higher_is_better: higherIsBetter },
  });
  return {
    min_samples: 5,
    unexplained_loss: false,
    left: cell(left),
    right: cell(right),
  };
}

describe("Release quality comparison presentation", () => {
  it("keeps the three row states distinct, including a comparable pair with nothing measured", () => {
    expect(qualityComparisonState(qualityComparison())).toBe("comparable");
    // Zero is a measured difference, not an absence of one.
    expect(
      qualityComparisonState(qualityComparison({ observed_delta: 0 })),
    ).toBe("comparable");
    expect(
      qualityComparisonState(
        qualityComparison({
          comparison_status: "not_comparable",
          reason: "insufficient_samples",
          observed_delta: null,
        }),
      ),
    ).toBe("not_comparable");
    // A refusal is a refusal even if a delta somehow rode along with it.
    expect(
      qualityComparisonState(
        qualityComparison({
          comparison_status: "not_comparable",
          reason: "scale_mismatch",
          observed_delta: 0.4,
        }),
      ),
    ).toBe("not_comparable");
    // Comparable, but no delta was produced: neutral, never a verdict.
    expect(
      qualityComparisonState(qualityComparison({ observed_delta: null })),
    ).toBe("unassessed");
  });

  it("maps every machine-readable refusal to its own copy key and never guesses", () => {
    const key = (reason: string | null) =>
      qualityComparisonReasonKey(
        qualityComparison({ comparison_status: "not_comparable", reason }),
      );

    expect(key("no_shared_cohort")).toBe("qualityReasonNoSharedCohort");
    expect(key("scale_mismatch")).toBe("qualityReasonScaleMismatch");
    expect(key("insufficient_samples")).toBe(
      "qualityReasonInsufficientSamples",
    );
    expect(key("observability_loss")).toBe("qualityReasonObservabilityLoss");
    // The contract types `reason` as an open string: an unknown or absent code
    // must degrade to explicit unknown copy rather than to a known refusal.
    expect(key("something_new")).toBe("qualityReasonUnknown");
    expect(key(null)).toBe("qualityReasonUnknown");
  });

  it("formats the observed delta with an explicit sign and no direction claim", () => {
    expect(formatObservedDelta(0.125)).toBe("+0.125");
    expect(formatObservedDelta(2)).toBe("+2");
    expect(formatObservedDelta(-0.05)).toBe("-0.05");
    expect(formatObservedDelta(0.16666666)).toBe("+0.167");
    // Exactly zero has no direction, so it carries no sign.
    expect(formatObservedDelta(0)).toBe("0");
    // Rounds below the rendered precision: still no direction claim.
    expect(formatObservedDelta(-0.0001)).toBe("0");
    expect(formatObservedDelta(null)).toBe("—");
    expect(formatObservedDelta(Number.NaN)).toBe("—");
    expect(formatObservedDelta(Number.POSITIVE_INFINITY)).toBe("—");
  });

  it("reads scale polarity only when both sides state the same one", () => {
    expect(
      qualityScaleDirection(
        qualityComparison({ coverage: coverageWithPolarity(true, true) }),
      ),
    ).toBe("higher_is_better");
    expect(
      qualityScaleDirection(
        qualityComparison({ coverage: coverageWithPolarity(false, false) }),
      ),
    ).toBe("lower_is_better");
    // Disagreeing or absent polarity is unknown — never inferred from the sign.
    expect(
      qualityScaleDirection(
        qualityComparison({ coverage: coverageWithPolarity(true, false) }),
      ),
    ).toBe("unknown");
    expect(
      qualityScaleDirection(
        qualityComparison({ coverage: coverageWithPolarity(null, true) }),
      ),
    ).toBe("unknown");
    // A verdict-only cohort carries no scale at all.
    expect(qualityScaleDirection(qualityComparison())).toBe("unknown");
    expect(qualityScaleDirection(qualityComparison({ coverage: {} }))).toBe(
      "unknown",
    );
    expect(
      qualityScaleDirection(
        qualityComparison({
          coverage: { left: "nonsense", right: 3 } as Record<string, unknown>,
        }),
      ),
    ).toBe("unknown");
  });
});
