import { describe, expect, it } from "@rstest/core";

import {
  ansichExpiredPointCount,
  coverageBadge,
  environmentBeliefBadge,
  environmentScopeBadge,
} from "@/core/ansich/presentation";

describe("environment presentation", () => {
  it("labels the three environment scopes distinctly and honestly", () => {
    expect(environmentScopeBadge("container").label).toBe("容器实测");
    expect(environmentScopeBadge("process_group").label).toBe("进程组快照");
    expect(environmentScopeBadge("host_shared").label).toBe("宿主共享");
  });

  it("renders uninstrumented as explicit 未观测, never ok/green", () => {
    const badge = coverageBadge("uninstrumented");
    expect(badge.label).toBe("未观测");
    expect(badge.tone).not.toBe("positive");
  });

  it("renders continuous coverage as 连续采样", () => {
    const badge = coverageBadge("continuous");
    expect(badge.label).toBe("连续采样");
  });

  it("labels per-command coverage distinctly from continuous/uninstrumented", () => {
    const badge = coverageBadge("per_command");
    expect(badge.label).not.toBe("连续采样");
    expect(badge.label).not.toBe("未观测");
  });

  it("falls back to a neutral badge for an unrecognized scope/coverage value", () => {
    expect(environmentScopeBadge("unknown_scope").tone).toBe("neutral");
    expect(coverageBadge("unknown_coverage").tone).toBe("neutral");
  });

  it("renders pressure belief states across the four-state family", () => {
    expect(
      environmentBeliefBadge("environment_pressure:fd_open", "ok"),
    ).toEqual({ label: "正常", tone: "positive" });
    expect(
      environmentBeliefBadge("environment_pressure:fd_open", "warning"),
    ).toEqual({ label: "预警", tone: "warning" });
    expect(
      environmentBeliefBadge("environment_pressure:fd_open", "critical"),
    ).toEqual({ label: "严重", tone: "critical" });
  });

  it("renders an unassessed/unknown belief as explicit 未知, never blank or positive", () => {
    const badge = environmentBeliefBadge(
      "environment_pressure:fd_open",
      "unknown",
    );
    expect(badge.label).toBe("未知");
    expect(badge.tone).not.toBe("positive");
  });

  it("renders leak beliefs on their own none/suspected/unknown scale", () => {
    expect(environmentBeliefBadge("environment_leak:fd_open", "none")).toEqual({
      label: "正常",
      tone: "positive",
    });
    const suspected = environmentBeliefBadge(
      "environment_leak:fd_open",
      "suspected",
    );
    expect(suspected.label).toBe("严重");
    expect(suspected.tone).toBe("critical");
    const unknown = environmentBeliefBadge(
      "environment_leak:fd_open",
      "unknown",
    );
    expect(unknown.label).toBe("未知");
    expect(unknown.tone).toBe("neutral");
  });
});

describe("ansichExpiredPointCount", () => {
  it("reads an absent counter as none rather than as unknown", () => {
    // A backend that predates the counter sends no key at all, and a missing
    // count is not evidence that anything expired — so the renderer draws no
    // annotation instead of an alarming `undefined`.
    expect(ansichExpiredPointCount(undefined)).toBe(0);
    expect(ansichExpiredPointCount(null)).toBe(0);
    expect(ansichExpiredPointCount({})).toBe(0);
  });

  it("carries a real count through, and a real zero as zero", () => {
    expect(ansichExpiredPointCount({ expired_points: 3 })).toBe(3);
    expect(ansichExpiredPointCount({ expired_points: 0 })).toBe(0);
  });

  it("refuses a value that is not a finite count", () => {
    expect(ansichExpiredPointCount({ expired_points: Number.NaN })).toBe(0);
    expect(ansichExpiredPointCount({ expired_points: -1 })).toBe(0);
  });
});
