import { describe, expect, it } from "@rstest/core";

import {
  getAlertPresentationCategory,
  countMissingContextItems,
  countLostObservations,
  getBudgetPresentation,
  formatAnsichTimestamp,
} from "@/core/ansich/presentation";
import { ANSICH_PRODUCED_ALERT_TYPES } from "@/core/ansich/types";

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
