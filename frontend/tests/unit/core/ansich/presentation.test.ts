import { describe, expect, it } from "@rstest/core";

import {
  getAlertPresentationCategory,
  countMissingContextItems,
  countLostObservations,
  evaluationDimensionLabelKey,
  formatEvaluationVerdict,
  getBudgetPresentation,
  formatAnsichTimestamp,
  isProjectionHardFailure,
  lostRangesForTask,
  projectionHealthWorsened,
  taskFailedJobCount,
  qualityBeliefTone,
  resolveProjectionHealthDisplay,
  shortId,
  selectPrimarySignal,
  systemProjectionScope,
  taskProjectionScope,
  isProjectionAttention,
} from "@/core/ansich/presentation";
import {
  ANSICH_PRODUCED_ALERT_TYPES,
  type AnsichLostRange,
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

describe("evaluationDimensionLabelKey", () => {
  it("names each contract dimension", () => {
    expect(evaluationDimensionLabelKey("correctness")).toBe(
      "dimensionCorrectness",
    );
    expect(evaluationDimensionLabelKey("completeness")).toBe(
      "dimensionCompleteness",
    );
    expect(evaluationDimensionLabelKey("relevance")).toBe("dimensionRelevance");
    expect(evaluationDimensionLabelKey("safety")).toBe("dimensionSafety");
    expect(evaluationDimensionLabelKey("efficiency")).toBe(
      "dimensionEfficiency",
    );
    expect(evaluationDimensionLabelKey("earliest_erroneous_step")).toBe(
      "dimensionEarliestErroneousStep",
    );
  });

  it("falls back to the custom label for an unknown dimension", () => {
    expect(evaluationDimensionLabelKey("tone_of_voice")).toBe(
      "dimensionCustom",
    );
    expect(evaluationDimensionLabelKey("")).toBe("dimensionCustom");
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

function lostRange(
  first: number,
  last: number,
  taskId: string | null,
): AnsichLostRange {
  return {
    first_sequence: first,
    last_sequence: last,
    task_id: taskId,
    producer_name: null,
    producer_instance_id: null,
  };
}

function projectionHealth(
  overrides: Partial<{
    status: "healthy" | "degraded" | "failed" | "stopped";
    failed_jobs: number;
    lost_ranges: AnsichLostRange[];
    storage_available: boolean;
  }> = {},
) {
  return {
    status: "healthy" as const,
    failed_jobs: 0,
    lost_ranges: [] as AnsichLostRange[],
    storage_available: true,
    ...overrides,
  };
}

describe("isProjectionHardFailure", () => {
  it("is true only when the projection itself cannot be trusted", () => {
    expect(isProjectionHardFailure(projectionHealth())).toBe(false);
    expect(
      isProjectionHardFailure(projectionHealth({ status: "degraded" })),
    ).toBe(false);
    expect(
      isProjectionHardFailure(projectionHealth({ status: "failed" })),
    ).toBe(true);
    expect(
      isProjectionHardFailure(projectionHealth({ status: "stopped" })),
    ).toBe(true);
    expect(
      isProjectionHardFailure(projectionHealth({ storage_available: false })),
    ).toBe(true);
  });
});

describe("lostRangesForTask", () => {
  it("never attributes an unattributed loss range to a Task", () => {
    const ranges = [
      lostRange(1, 2, "task-1"),
      lostRange(5, 9, null),
      lostRange(20, 20, "task-2"),
    ];

    expect(lostRangesForTask(ranges, "task-1")).toEqual([
      lostRange(1, 2, "task-1"),
    ]);
    expect(lostRangesForTask(ranges, "task-3")).toEqual([]);
  });
});

describe("taskProjectionScope", () => {
  it("ignores global degradation that does not touch this Task", () => {
    const scope = taskProjectionScope(
      projectionHealth({
        status: "degraded",
        failed_jobs: 7,
        lost_ranges: [lostRange(1, 4, "other-task"), lostRange(9, 9, null)],
      }),
      "task-1",
      { count: 0, truncated: false },
    );

    expect(scope.kind).toBe("task");
    expect(scope.attention).toBe(false);
    expect(scope.hardFailure).toBe(false);
    expect(scope.failedJobs).toBe(0);
    expect(scope.lostObservations).toBe(0);
    expect(scope.attentionCount).toBe(0);
  });

  it("reports this Task's own failed jobs and lost observations only", () => {
    const scope = taskProjectionScope(
      projectionHealth({
        status: "degraded",
        failed_jobs: 7,
        lost_ranges: [lostRange(1, 3, "task-1"), lostRange(50, 90, "other")],
      }),
      "task-1",
      { count: 2, truncated: false },
    );

    expect(scope.attention).toBe(true);
    expect(scope.failedJobs).toBe(2);
    expect(scope.lostObservations).toBe(3);
    expect(scope.attentionCount).toBe(5);
    expect(scope.status).toBe("degraded");
  });

  it("marks a truncated failed-job page so the count reads as a floor", () => {
    const scope = taskProjectionScope(projectionHealth(), "task-1", {
      count: 50,
      truncated: true,
    });

    expect(scope.attention).toBe(true);
    expect(scope.failedJobsTruncated).toBe(true);
  });

  it("surfaces a system-level hard failure even when the Task looks clean", () => {
    const scope = taskProjectionScope(
      projectionHealth({ storage_available: false }),
      "task-1",
      { count: 0, truncated: false },
    );

    expect(scope.attention).toBe(true);
    expect(scope.hardFailure).toBe(true);
    expect(scope.attentionCount).toBe(0);
  });

  it("inherits the system status when the projection itself stopped", () => {
    const scope = taskProjectionScope(
      projectionHealth({ status: "stopped" }),
      "task-1",
      { count: 0, truncated: false },
    );

    expect(scope.hardFailure).toBe(true);
    expect(scope.status).toBe("stopped");
  });

  it("carries an unknown failure count instead of reporting zero failures", () => {
    const scope = taskProjectionScope(projectionHealth(), "task-1", {
      count: null,
      truncated: false,
    });

    // Unknown is not failing: it must not promote a banner or inflate the badge.
    expect(scope.failedJobs).toBeNull();
    expect(scope.attention).toBe(false);
    expect(scope.attentionCount).toBe(0);
    expect(scope.status).toBe("healthy");
  });

  it("still reports a lost range while the failure count is unknown", () => {
    const scope = taskProjectionScope(
      projectionHealth({ lost_ranges: [lostRange(1, 2, "task-1")] }),
      "task-1",
      { count: null, truncated: false },
    );

    expect(scope.attention).toBe(true);
    expect(scope.attentionCount).toBe(2);
  });
});

describe("taskFailedJobCount", () => {
  it("reports an unknown count while the request has produced no answer", () => {
    // TanStack leaves `data` undefined both while pending and after a failed
    // request, and this hook does not retry: collapsing either into 0 would
    // turn "we do not know" into "this Task has no failures".
    expect(taskFailedJobCount(undefined)).toBeNull();
    expect(taskFailedJobCount({ data: undefined })).toBeNull();
  });

  it("reports the answered count, including a genuine zero", () => {
    expect(taskFailedJobCount({ data: { items: [] } })).toBe(0);
    expect(taskFailedJobCount({ data: { items: [{}, {}] } })).toBe(2);
  });
});

describe("systemProjectionScope", () => {
  it("counts every failed job and lost observation, attributed or not", () => {
    const scope = systemProjectionScope(
      projectionHealth({
        status: "degraded",
        failed_jobs: 3,
        lost_ranges: [lostRange(1, 2, "task-1"), lostRange(5, 5, null)],
      }),
    );

    expect(scope.kind).toBe("system");
    expect(scope.attention).toBe(true);
    expect(scope.failedJobs).toBe(3);
    expect(scope.lostObservations).toBe(3);
    expect(scope.attentionCount).toBe(6);
  });
});

describe("projectionHealthWorsened", () => {
  const snapshot = {
    failedJobs: 2,
    lostObservations: 1,
    status: "degraded" as const,
  };

  it("is false when nothing got worse", () => {
    expect(projectionHealthWorsened(snapshot, snapshot)).toBe(false);
    expect(
      projectionHealthWorsened(snapshot, {
        failedJobs: 1,
        lostObservations: 0,
        status: "healthy",
      }),
    ).toBe(false);
  });

  it("is true when a count rises or the status degrades further", () => {
    expect(
      projectionHealthWorsened(snapshot, { ...snapshot, failedJobs: 3 }),
    ).toBe(true);
    expect(
      projectionHealthWorsened(snapshot, { ...snapshot, lostObservations: 2 }),
    ).toBe(true);
    expect(
      projectionHealthWorsened(snapshot, { ...snapshot, status: "failed" }),
    ).toBe(true);
    expect(
      projectionHealthWorsened(snapshot, { ...snapshot, status: "stopped" }),
    ).toBe(true);
  });

  it("ranks failed and stopped as equally bad", () => {
    expect(
      projectionHealthWorsened(
        { ...snapshot, status: "failed" },
        { ...snapshot, status: "stopped" },
      ),
    ).toBe(false);
  });

  it("treats an unknown failure count on either side as no change", () => {
    expect(
      projectionHealthWorsened(snapshot, { ...snapshot, failedJobs: null }),
    ).toBe(false);
    expect(
      projectionHealthWorsened({ ...snapshot, failedJobs: null }, snapshot),
    ).toBe(false);
    expect(
      projectionHealthWorsened(
        { ...snapshot, failedJobs: null },
        { ...snapshot, failedJobs: null, lostObservations: 9 },
      ),
    ).toBe(true);
  });
});

describe("resolveProjectionHealthDisplay", () => {
  const attentionScope = taskProjectionScope(projectionHealth(), "task-1", {
    count: 2,
    truncated: false,
  });

  it("shows the banner when nothing was dismissed", () => {
    expect(resolveProjectionHealthDisplay(attentionScope, null)).toEqual({
      line: "banner",
      showBadge: false,
      dismissible: true,
      clearDismissal: false,
    });
  });

  it("hides the banner behind the badge once dismissed at this state", () => {
    expect(
      resolveProjectionHealthDisplay(attentionScope, attentionScope.snapshot),
    ).toEqual({
      line: "none",
      showBadge: true,
      dismissible: true,
      clearDismissal: false,
    });
  });

  it("brings the banner back and drops the record when the state worsens", () => {
    const worse = taskProjectionScope(projectionHealth(), "task-1", {
      count: 3,
      truncated: false,
    });

    expect(
      resolveProjectionHealthDisplay(worse, attentionScope.snapshot),
    ).toEqual({
      line: "banner",
      showBadge: false,
      dismissible: true,
      clearDismissal: true,
    });
  });

  it("keeps a dismissed Task collapsed while unrelated global health degrades", () => {
    // The headline promise: another Task's failures are not this Task's news.
    const globallyWorse = taskProjectionScope(
      projectionHealth({ status: "degraded", failed_jobs: 40 }),
      "task-1",
      { count: 2, truncated: false },
    );

    expect(
      resolveProjectionHealthDisplay(globallyWorse, attentionScope.snapshot),
    ).toEqual({
      line: "none",
      showBadge: true,
      dismissible: true,
      clearDismissal: false,
    });
  });

  it("never offers dismissal for a hard failure and drops any stale record", () => {
    const hard = taskProjectionScope(
      projectionHealth({ status: "stopped", storage_available: false }),
      "task-1",
      { count: 0, truncated: false },
    );

    expect(resolveProjectionHealthDisplay(hard, null)).toEqual({
      line: "banner",
      showBadge: false,
      dismissible: false,
      clearDismissal: false,
    });
    expect(
      resolveProjectionHealthDisplay(hard, attentionScope.snapshot),
    ).toEqual({
      line: "banner",
      showBadge: false,
      dismissible: false,
      clearDismissal: true,
    });
  });

  it("clears the record on recovery so the next incident starts as a banner", () => {
    const clean = taskProjectionScope(projectionHealth(), "task-1", {
      count: 0,
      truncated: false,
    });

    expect(
      resolveProjectionHealthDisplay(clean, attentionScope.snapshot),
    ).toEqual({
      // Back to the plain completeness line, and the record is gone.
      line: "healthy",
      showBadge: false,
      dismissible: false,
      clearDismissal: true,
    });
  });
});

describe("an unanswered failed-job request never becomes a clean bill of health", () => {
  function lineFor(result: { data?: { items: unknown[] } } | undefined) {
    const scope = taskProjectionScope(projectionHealth(), "task-1", {
      count: taskFailedJobCount(result),
      truncated: false,
    });
    return resolveProjectionHealthDisplay(scope, null).line;
  }

  it("renders the neutral line while the count is still pending", () => {
    expect(lineFor(undefined)).toBe("unknown");
  });

  it("renders the neutral line after the request failed", () => {
    expect(lineFor({ data: undefined })).toBe("unknown");
  });

  it("claims completeness only once an answered zero arrives", () => {
    expect(lineFor({ data: { items: [] } })).toBe("healthy");
  });

  it("promotes the banner once an answered failure arrives", () => {
    expect(lineFor({ data: { items: [{}] } })).toBe("banner");
  });
});
