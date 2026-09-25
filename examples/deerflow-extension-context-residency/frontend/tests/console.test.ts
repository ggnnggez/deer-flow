import { describe, expect, it } from "vitest";

import { taskListSearchParams } from "../src/api";
import {
  formatPercent,
  groupTasksByThread,
  healthLevel,
  minuteKey,
  peakLaneStack,
  rangeSince,
  secondsBetween,
  sparklinePath,
  throughputSeries,
  windowComposition,
} from "../src/console";
import type { HealthDiagnostic, TaskListItem } from "../src/contracts";

function item(overrides: Partial<TaskListItem>): TaskListItem {
  return {
    task_id: "task",
    run_id: "run",
    thread_id: "thread",
    kind: "lead",
    parent_task_id: null,
    agent_name: null,
    started_at: "2026-09-25T00:00:00+00:00",
    stopped_at: null,
    outcome: null,
    steps: 1,
    attempts: 1,
    incomplete_attempts: 0,
    compactions: 0,
    peak_tokens: 0,
    peak_attempt_id: null,
    peak_context_window: null,
    peak_by_kind: {},
    last_attempt_at: null,
    duration_seconds: null,
    ...overrides,
  };
}

describe("windowComposition", () => {
  const lanes = [
    { lane: "system" as const, size: 300 },
    { lane: "tool_result" as const, size: 200 },
  ];

  it("makes the context window 100% and gives each lane its absolute share of it", () => {
    const composition = windowComposition(lanes, 500, 1000, "tokens");
    expect(composition.basis).toBe("window");
    expect(composition.capacity).toBe(1000);
    expect(composition.segments.map((segment) => segment.share)).toEqual([0.3, 0.2]);
    expect(composition.segments.map((segment) => segment.width)).toEqual([0.3, 0.2]);
    expect(composition.usedShare).toBe(0.5);
    expect(composition.freeShare).toBe(0.5);
    expect(composition.overflow).toBe(false);
  });

  it("falls back to the request as 100% when no window was recorded, and says so", () => {
    const composition = windowComposition(lanes, 500, null, "tokens");
    expect(composition.basis).toBe("request");
    expect(composition.capacity).toBeNull();
    expect(composition.segments.map((segment) => segment.share)).toEqual([0.6, 0.4]);
    expect(composition.freeShare).toBeNull();
    expect(windowComposition(lanes, 500, 0, "tokens").basis).toBe("request");
  });

  it("measures a token window in bytes through the estimator's own ratio", () => {
    const composition = windowComposition([{ lane: "user", size: 2000 }], 2000, 1000, "bytes");
    expect(composition.capacity).toBe(4000);
    expect(composition.segments[0]?.share).toBe(0.5);
  });

  it("flags a request larger than the window and rescales the segments to fill the bar", () => {
    const composition = windowComposition(lanes, 500, 400, "tokens");
    expect(composition.overflow).toBe(true);
    expect(composition.usedShare).toBe(1.25);
    expect(composition.freeShare).toBe(0);
    expect(composition.segments.map((segment) => segment.share)).toEqual([0.75, 0.5]);
    expect(composition.segments.map((segment) => segment.width)).toEqual([0.6, 0.4]);
  });

  it("renders an empty request as all free", () => {
    const composition = windowComposition([], 0, 1000, "tokens");
    expect(composition.segments).toEqual([]);
    expect(composition.freeShare).toBe(1);
  });
});

describe("groupTasksByThread", () => {
  it("keeps conversations in order of first appearance, leads first, subagents under their parent", () => {
    const groups = groupTasksByThread([
      item({ task_id: "lead-b", thread_id: "b", started_at: "2026-09-25T02:00:00+00:00" }),
      item({ task_id: "sub-a-orphan", thread_id: "a", kind: "subagent", parent_task_id: "gone" }),
      item({ task_id: "sub-b", thread_id: "b", kind: "subagent", parent_task_id: "lead-b", started_at: "2026-09-25T02:30:00+00:00" }),
      item({ task_id: "lead-a", thread_id: "a" }),
    ]);
    expect(groups.map((group) => group.threadId)).toEqual(["b", "a"]);
    expect(groups[0]?.rows.map((row) => [row.task.task_id, row.depth])).toEqual([
      ["lead-b", 0],
      ["sub-b", 1],
    ]);
    expect(groups[0]?.latestStartedAt).toBe("2026-09-25T02:30:00+00:00");
    expect(groups[1]?.rows.map((row) => [row.task.task_id, row.depth])).toEqual([
      ["lead-a", 0],
      ["sub-a-orphan", 1],
    ]);
  });
});

describe("taskListSearchParams", () => {
  it("leaves empty filters out and names the server's parameters", () => {
    const params = taskListSearchParams({ query: "  ", kind: "", outcome: "running", since: null, hasCompactions: true, incompleteOnly: false, sort: "peak", direction: "desc", limit: 50, offset: 0 });
    expect(params.toString()).toBe("outcome=running&has_compactions=true&sort=peak&direction=desc&limit=50");
    expect(taskListSearchParams({ query: "abc", offset: 50 }).toString()).toBe("query=abc&offset=50");
  });
});

describe("rangeSince", () => {
  const now = new Date("2026-09-25T12:00:00.500Z");
  it("shapes the bound like the recorder's timestamps", () => {
    expect(rangeSince("24h", now)).toBe("2026-09-24T12:00:00.500000+00:00");
    expect(rangeSince("7d", now)).toBe("2026-09-18T12:00:00.500000+00:00");
    expect(rangeSince("all", now)).toBeNull();
  });
});

describe("throughputSeries", () => {
  it("fills the last hour minute by minute with zeros where nothing was written", () => {
    const now = new Date("2026-09-25T12:30:20Z");
    expect(minuteKey(now)).toBe("2026-09-25T12:30Z");
    const series = throughputSeries(
      [
        { minute: "2026-09-25T12:30Z", events: 4 },
        { minute: "2026-09-25T12:00Z", events: 9 },
        { minute: "2026-09-25T09:00Z", events: 99 },
      ],
      now,
      60,
    );
    expect(series).toHaveLength(60);
    expect(series[59]).toEqual({ minute: "2026-09-25T12:30Z", events: 4 });
    expect(series[29]).toEqual({ minute: "2026-09-25T12:00Z", events: 9 });
    expect(series[0]).toEqual({ minute: "2026-09-25T11:31Z", events: 0 });
    expect(series.reduce((sum, point) => sum + point.events, 0)).toBe(13);
  });

  it("draws the sparkline to one scale", () => {
    const { line, area, max } = sparklinePath([0, 10, 5], 100, 50, 0);
    expect(max).toBe(10);
    expect(line).toBe("M0.0 50.0 L50.0 0.0 L100.0 25.0");
    expect(area.endsWith("L100.0 50.0 L0.0 50.0 Z")).toBe(true);
    expect(sparklinePath([], 100, 50).area).toBe("");
  });
});

describe("healthLevel", () => {
  const diagnostic = (level: HealthDiagnostic["level"]): HealthDiagnostic => ({ level, code: level, title: "", detail: "", remedy: null, affected: [] });
  it("reports the worst level present", () => {
    expect(healthLevel([])).toBe("ok");
    expect(healthLevel([diagnostic("ok"), diagnostic("warning")])).toBe("warning");
    expect(healthLevel([diagnostic("warning"), diagnostic("error")])).toBe("error");
  });
});

describe("peakLaneStack", () => {
  it("folds the index's per-kind sums into lanes in taxonomy order", () => {
    expect(peakLaneStack({ tool_result_visible: 40, system_prompt: 10, tool_schema: 5, tool_request: 3, mystery: 1 })).toEqual([
      { lane: "system", size: 10 },
      { lane: "tool_schema", size: 5 },
      { lane: "assistant", size: 3 },
      { lane: "tool_result", size: 40 },
      { lane: "unknown", size: 1 },
    ]);
  });
});

describe("formatPercent", () => {
  it("never rounds a present share down to nothing", () => {
    expect(formatPercent(0.5)).toBe("50.0%");
    expect(formatPercent(0)).toBe("0.0%");
    expect(formatPercent(12 / 128_000)).toBe("<0.1%");
    expect(formatPercent(84 / 128_000)).toBe("0.1%");
    expect(formatPercent(0.0006)).toBe("0.1%");
    expect(formatPercent(0.004, 0)).toBe("<1%");
    expect(formatPercent(1.146)).toBe("114.6%");
  });
});

describe("secondsBetween", () => {
  it("is whole seconds, never negative, and null when unreadable", () => {
    const now = new Date("2026-09-25T12:00:10Z");
    expect(secondsBetween("2026-09-25T12:00:00+00:00", now)).toBe(10);
    expect(secondsBetween("2026-09-25T12:00:20+00:00", now)).toBe(0);
    expect(secondsBetween("not a date", now)).toBeNull();
    expect(secondsBetween(null, now)).toBeNull();
  });
});
