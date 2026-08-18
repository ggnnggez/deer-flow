import { describe, expect, it } from "@rstest/core";

import {
  getAlertPresentationCategory,
  countMissingContextItems,
  countLostObservations,
  formatEvaluationVerdict,
  getBudgetPresentation,
  formatAnsichTimestamp,
  qualityBeliefTone,
  shortId,
  selectPrimarySignal,
  isProjectionAttention,
} from "@/core/ansich/presentation";
import {
  ANSICH_PRODUCED_ALERT_TYPES,
  type AnsichQualityBelief,
} from "@/core/ansich/types";

describe("Ansich presentation", () => {
  it("counts every observation represented by inclusive lost ranges", () => {
    expect(
      countLostObservations([
        {
          first_sequence: 4,
          last_sequence: 4,
          task_id: "task-1",
          producer_name: "test",
          producer_instance_id: "local",
        },
        {
          first_sequence: 8,
          last_sequence: 10,
          task_id: null,
          producer_name: null,
          producer_instance_id: null,
        },
      ]),
    ).toBe(4);
  });

  it("keeps an invalid timestamp visible instead of hiding evidence", () => {
    expect(formatAnsichTimestamp("not-a-timestamp", "en-US")).toBe(
      "not-a-timestamp",
    );
    expect(formatAnsichTimestamp(null, "en-US")).toBe("—");
  });

  it("counts ordinal-preserving missing context entries", () => {
    expect(
      countMissingContextItems([
        { resolution_status: "available" },
        { resolution_status: "missing" },
        { resolution_status: "missing" },
      ]),
    ).toBe(2);
  });

  it("does not invent a healthy budget bar without configuration or complete usage", () => {
    expect(getBudgetPresentation(undefined, undefined)).toEqual({
      status: "unconfigured",
      percent: null,
      overshoot: null,
    });
    expect(
      getBudgetPresentation(
        { hard_limit: null },
        { value: "unknown", usage_value: null, overshoot: null },
      ),
    ).toEqual({
      status: "unconfigured",
      percent: null,
      overshoot: null,
    });
    expect(
      getBudgetPresentation(
        { hard_limit: 100 },
        { value: "unknown", usage_value: null, overshoot: null },
      ),
    ).toEqual({
      status: "unknown",
      percent: null,
      overshoot: null,
    });
    expect(
      getBudgetPresentation(
        { hard_limit: 100 },
        { value: "exceeded", usage_value: 107, overshoot: 7 },
      ),
    ).toEqual({ status: "exceeded", percent: 107, overshoot: 7 });
  });

  it("advertises only alert types with implemented producers", () => {
    expect(ANSICH_PRODUCED_ALERT_TYPES).toEqual([
      "budget_warning",
      "budget_exceeded",
      "exact_repetition",
      "tool_frequency",
      "heartbeat_missing",
      "long_dwell",
      "configuration_drift",
      "attempted_scope_violation",
      "realized_scope_violation",
      "unverified_effect",
    ]);
    expect(getAlertPresentationCategory("exact_repetition")).toBe("runaway");
    expect(getAlertPresentationCategory("budget_exceeded")).toBe("runaway");
    expect(getAlertPresentationCategory("tool_frequency")).toBe("operational");
    expect(getAlertPresentationCategory("long_dwell")).toBe("operational");
    expect(getAlertPresentationCategory("heartbeat_missing")).toBe("liveness");
    expect(getAlertPresentationCategory("configuration_drift")).toBe(
      "operational",
    );
    expect(getAlertPresentationCategory("attempted_scope_violation")).toBe(
      "operational",
    );
    expect(getAlertPresentationCategory("realized_scope_violation")).toBe(
      "operational",
    );
    expect(getAlertPresentationCategory("unverified_effect")).toBe(
      "operational",
    );
  });
});

describe("shortId", () => {
  it("truncates a long UUID to the leading segment", () => {
    expect(shortId("a82f1234-5678-90ab-cdef-000000000000")).toBe("a82f1234");
  });
  it("returns short values unchanged", () => {
    expect(shortId("abc")).toBe("abc");
    expect(shortId("")).toBe("");
  });
  it("respects a custom length", () => {
    expect(shortId("a82f1234-5678", 4)).toBe("a82f");
  });
});

describe("selectPrimarySignal", () => {
  it("ranks behavior runaway above an exceeded budget", () => {
    expect(
      selectPrimarySignal({
        behaviorState: "runaway",
        budgetHealth: [{ value: "exceeded" }],
      }),
    ).toEqual({ severity: "critical", kind: "behavior" });
  });

  it("reports an exceeded budget as critical when behavior is normal", () => {
    expect(
      selectPrimarySignal({
        behaviorState: "normal",
        budgetHealth: [{ value: "within" }, { value: "exceeded" }],
      }),
    ).toEqual({ severity: "critical", kind: "budget" });
  });

  it("reports a realized scope violation as critical", () => {
    expect(
      selectPrimarySignal({ scopeSafety: { realizedViolation: true } }),
    ).toEqual({ severity: "critical", kind: "scope" });
  });

  it("ranks a stale heartbeat above a budget warning", () => {
    expect(
      selectPrimarySignal({
        heartbeat: "stale",
        budgetHealth: [{ value: "warning" }],
      }),
    ).toEqual({ severity: "warning", kind: "heartbeat" });
  });

  it("reports degraded observability as a warning", () => {
    expect(selectPrimarySignal({ observability: "degraded" })).toEqual({
      severity: "warning",
      kind: "observability",
    });
  });

  it("reports healthy only from positive evidence", () => {
    expect(
      selectPrimarySignal({
        observability: "healthy",
        heartbeat: "fresh",
        budgetHealth: [{ value: "within" }],
      }),
    ).toEqual({ severity: "none", kind: "healthy" });
  });

  it("returns null (insufficient evidence) when nothing is known", () => {
    expect(selectPrimarySignal({})).toBeNull();
    expect(
      selectPrimarySignal({ behaviorState: "unknown", heartbeat: "unknown" }),
    ).toBeNull();
  });
});

describe("formatEvaluationVerdict", () => {
  it("prefers the recorded verdict over a score", () => {
    expect(formatEvaluationVerdict("fail", 9, 0, 10)).toBe("fail");
  });

  it("renders a scored evaluation against its scale maximum", () => {
    expect(formatEvaluationVerdict(null, 7, 0, 10)).toBe("7 / 10");
    expect(formatEvaluationVerdict("", 3, 1, 5)).toBe("3 / 5");
  });

  it("renders a bare score when the scale is not fully known", () => {
    expect(formatEvaluationVerdict(null, 7, null, null)).toBe("7");
    expect(formatEvaluationVerdict(null, 7, 0, null)).toBe("7");
    expect(formatEvaluationVerdict(null, 0, null, 10)).toBe("0");
  });

  it("renders a dash when neither a verdict nor a score exists", () => {
    expect(formatEvaluationVerdict(null, null, 0, 10)).toBe("—");
    expect(formatEvaluationVerdict("", null, null, null)).toBe("—");
  });
});

describe("qualityBeliefTone", () => {
  const belief = (
    overrides: Partial<AnsichQualityBelief> = {},
  ): AnsichQualityBelief => ({
    dimension: "task_success",
    value: { verdict: "pass" },
    source: { name: "suite-runner", version: "1.0.0" },
    authority_class: "deterministic",
    fidelity_class: "hard",
    as_of: "2026-08-18T00:00:00Z",
    resolver: { name: "ansich.belief", version: "2" },
    conflicting_assertion_count: 0,
    evidence_obs_ids: ["obs-1"],
    unassessed: false,
    ...overrides,
  });

  it("reports unassessed before inspecting any value", () => {
    expect(
      qualityBeliefTone(
        belief({ unassessed: true, value: { verdict: "pass" } }),
      ),
    ).toBe("unassessed");
    expect(
      qualityBeliefTone(
        belief({
          unassessed: true,
          value: { status: "unassessed" },
          authority_class: "unknown",
          fidelity_class: "unknown",
          as_of: null,
          resolver: null,
          evidence_obs_ids: [],
        }),
      ),
    ).toBe("unassessed");
  });

  it("maps an asserted verdict onto its tone", () => {
    expect(qualityBeliefTone(belief({ value: { verdict: "pass" } }))).toBe(
      "pass",
    );
    expect(qualityBeliefTone(belief({ value: { verdict: "fail" } }))).toBe(
      "fail",
    );
    expect(qualityBeliefTone(belief({ value: { verdict: "partial" } }))).toBe(
      "partial",
    );
  });

  it("never infers a pass from a missing or unusable verdict", () => {
    expect(qualityBeliefTone(belief({ value: {} }))).toBe("unknown");
    expect(qualityBeliefTone(belief({ value: { verdict: null } }))).toBe(
      "unknown",
    );
    expect(qualityBeliefTone(belief({ value: { verdict: "unknown" } }))).toBe(
      "unknown",
    );
    expect(qualityBeliefTone(belief({ value: { verdict: 1 } }))).toBe(
      "unknown",
    );
    expect(qualityBeliefTone(belief({ value: { score: 10 } }))).toBe("unknown");
    expect(qualityBeliefTone(belief({ value: { status: "unassessed" } }))).toBe(
      "unknown",
    );
  });
});

describe("isProjectionAttention", () => {
  const base = {
    status: "healthy" as const,
    failed_jobs: 0,
    lost_ranges: [] as unknown[],
    storage_available: true,
  };
  it("is false for a fully healthy projection", () => {
    expect(isProjectionAttention(base)).toBe(false);
  });
  it("is true on non-healthy status, failed jobs, lost ranges, or lost storage", () => {
    expect(isProjectionAttention({ ...base, status: "degraded" })).toBe(true);
    expect(isProjectionAttention({ ...base, failed_jobs: 1 })).toBe(true);
    expect(isProjectionAttention({ ...base, lost_ranges: [{}] })).toBe(true);
    expect(isProjectionAttention({ ...base, storage_available: false })).toBe(
      true,
    );
  });
});
