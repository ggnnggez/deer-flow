import { describe, expect, it } from "@rstest/core";

import {
  activeTasksRefreshInterval,
  taskListRefreshInterval,
  taskDetailRefreshInterval,
  taskReleaseRefreshInterval,
} from "@/core/ansich/hooks";
import type {
  AnsichActiveTaskListResponse,
  AnsichTaskResponse,
  AnsichTaskAgentReleaseResponse,
} from "@/core/ansich/types";

describe("Ansich polling policy", () => {
  it("polls active work at 5s, idle lists at 10s, and pauses hidden pages", () => {
    const running = {
      items: [{ control: { value: "running" } }],
    } as AnsichActiveTaskListResponse;
    const idle = { items: [] } as unknown as AnsichActiveTaskListResponse;

    expect(activeTasksRefreshInterval(running, true)).toBe(5_000);
    expect(activeTasksRefreshInterval(idle, true)).toBe(10_000);
    expect(activeTasksRefreshInterval(running, false)).toBe(false);
  });

  it("stops task-detail polling once the Task is terminal", () => {
    const running = {
      task: { control: { value: "running" } },
    } as AnsichTaskResponse;
    const completed = {
      task: { control: { value: "completed" } },
    } as AnsichTaskResponse;

    expect(taskDetailRefreshInterval(running, true)).toBe(5_000);
    expect(taskDetailRefreshInterval(completed, true)).toBe(false);
    expect(taskDetailRefreshInterval(running, false)).toBe(false);
  });

  it("does not poll terminal Task history", () => {
    expect(taskListRefreshInterval("terminal", true)).toBe(false);
    expect(taskListRefreshInterval("all", true)).toBe(5_000);
    expect(taskListRefreshInterval("all", false)).toBe(false);
  });

  it("polls a running Task only until its immutable release binding arrives", () => {
    const unresolved = { binding: null } as AnsichTaskAgentReleaseResponse;
    const resolved = {
      binding: { release: { summary: { release_id: "release" } } },
    } as AnsichTaskAgentReleaseResponse;

    expect(taskReleaseRefreshInterval(unresolved, true, true)).toBe(5_000);
    expect(taskReleaseRefreshInterval(resolved, true, true)).toBe(false);
    expect(taskReleaseRefreshInterval(unresolved, false, true)).toBe(false);
    expect(taskReleaseRefreshInterval(unresolved, true, false)).toBe(false);
  });
});
