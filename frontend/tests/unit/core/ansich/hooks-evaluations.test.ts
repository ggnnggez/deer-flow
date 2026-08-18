import { beforeEach, describe, expect, it, rs } from "@rstest/core";
import { useQuery } from "@tanstack/react-query";

// Hoisted by the runner ahead of the imports above: the hooks are called
// directly, outside React, so what each one hands to TanStack Query is
// observable without a renderer (the suite has no DOM/renderHook harness).
rs.mock("@tanstack/react-query", () => ({
  useQuery: rs.fn(),
  useInfiniteQuery: rs.fn(),
  useMutation: rs.fn(),
  useQueryClient: rs.fn(),
}));

import {
  useAnsichReleaseQuality,
  useAnsichStepEvaluations,
  useAnsichTaskEvaluations,
} from "@/core/ansich/hooks";

const mockedUseQuery = rs.mocked(useQuery);

/** The queryKey the hook actually handed to TanStack Query. */
function capturedQueryKey(callIndex = 0): unknown[] {
  const options = mockedUseQuery.mock.calls[callIndex]?.[0] as
    | { queryKey?: unknown[] }
    | undefined;
  return options?.queryKey ?? [];
}

describe("Ansich evaluation query keys", () => {
  beforeEach(() => {
    mockedUseQuery.mockReset();
  });

  it("keys Task evaluations under the shared Task namespace", () => {
    useAnsichTaskEvaluations("task/one");

    expect(capturedQueryKey()).toEqual([
      "ansich",
      "tasks",
      "task/one",
      "evaluations",
    ]);
  });

  it("keys Step evaluations under the shared Step namespace", () => {
    useAnsichStepEvaluations("step/one");

    expect(capturedQueryKey()).toEqual([
      "ansich",
      "steps",
      "step/one",
      "evaluations",
    ]);
  });

  it("keys release quality under the shared AgentRelease namespace, per cohort", () => {
    useAnsichReleaseQuality("release/one", "suite@1.0");
    useAnsichReleaseQuality("release/one", null);

    expect(capturedQueryKey(0)).toEqual([
      "ansich",
      "agent-releases",
      "release/one",
      "quality",
      "suite@1.0",
    ]);
    expect(capturedQueryKey(1)).toEqual([
      "ansich",
      "agent-releases",
      "release/one",
      "quality",
      null,
    ]);
  });

  it("stays reachable from the operator invalidation prefixes", () => {
    // `useAnsichRetryFailedJobs` invalidates ["ansich", "tasks"] — retrying a
    // failed assessor job is exactly what repairs a missing evaluation — and
    // `useAnsichTaskAction` invalidates ["ansich", "tasks", taskId]. TanStack
    // matches by key prefix, so the evaluation caches must start with them.
    useAnsichTaskEvaluations("task/one");

    const key = capturedQueryKey();
    expect(key.slice(0, 2)).toEqual(["ansich", "tasks"]);
    expect(key.slice(0, 3)).toEqual(["ansich", "tasks", "task/one"]);
  });
});
