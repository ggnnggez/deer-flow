import { beforeEach, describe, expect, it, rs } from "@rstest/core";

rs.mock("@/core/api/fetcher", () => ({
  fetch: rs.fn(),
}));

import {
  AnsichApiError,
  fetchAnsichActiveTasks,
  fetchAnsichContentExposures,
  fetchAnsichContentLineage,
  fetchAnsichContentPayload,
  fetchAnsichContextCompression,
  fetchAnsichContextSnapshot,
  fetchAnsichStep,
  fetchAnsichStepContext,
  fetchAnsichTask,
  fetchAnsichTaskSteps,
  fetchAnsichTaskTimeline,
  fetchAnsichTasks,
  fetchAnsichTaskBudgets,
  fetchAnsichTaskUsage,
} from "@/core/ansich/api";
import { fetch } from "@/core/api/fetcher";

const mockedFetch = rs.mocked(fetch);

function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    statusText: "OK",
    json: async () => body,
  } as Response;
}

describe("Ansich API", () => {
  beforeEach(() => {
    mockedFetch.mockReset();
  });

  it("loads the operations task list with an explicit bounded limit", async () => {
    mockedFetch.mockResolvedValue(
      jsonResponse({ items: [], projection_status: { status: "healthy" } }),
    );

    await fetchAnsichTasks(75);

    expect(mockedFetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/ansich/tasks?limit=75"),
    );
  });

  it("uses the Phase 5 active, usage, and budget endpoints", async () => {
    mockedFetch.mockResolvedValue(jsonResponse({}));
    const taskId = "task/operations";

    await fetchAnsichActiveTasks(75);
    await fetchAnsichTaskUsage(taskId);
    await fetchAnsichTaskBudgets(taskId);

    const encoded = encodeURIComponent(taskId);
    expect(mockedFetch.mock.calls.map((call) => call[0])).toEqual([
      expect.stringContaining("/api/ansich/operations/active-tasks?limit=75"),
      expect.stringContaining(`/api/ansich/tasks/${encoded}/usage`),
      expect.stringContaining(`/api/ansich/tasks/${encoded}/budgets`),
    ]);
  });

  it("URL-encodes a task ID for both task and timeline requests", async () => {
    mockedFetch.mockResolvedValue(
      jsonResponse({ task: {}, projection_status: { status: "healthy" } }),
    );
    const taskId = "task/with spaces";

    await fetchAnsichTask(taskId);
    await fetchAnsichTaskTimeline(taskId);

    const encoded = encodeURIComponent(taskId);
    const taskUrl = mockedFetch.mock.calls[0]?.[0];
    const timelineUrl = mockedFetch.mock.calls[1]?.[0];
    expect(typeof taskUrl).toBe("string");
    expect(typeof timelineUrl).toBe("string");
    expect(taskUrl as string).toContain(`/api/ansich/tasks/${encoded}`);
    expect(timelineUrl as string).toContain(
      `/api/ansich/tasks/${encoded}/timeline`,
    );
  });

  it("surfaces the gateway detail when a query is rejected", async () => {
    mockedFetch.mockResolvedValue({
      ok: false,
      status: 403,
      statusText: "Forbidden",
      json: async () => ({ detail: "Administrator access required" }),
    } as Response);

    await expect(fetchAnsichTasks()).rejects.toThrow(
      "Administrator access required",
    );
  });

  it("uses distinct encoded endpoints for steps, context inventory, and raw payload", async () => {
    mockedFetch.mockResolvedValue(jsonResponse({}));
    const identifier = "id/with spaces";

    await fetchAnsichTaskSteps(identifier);
    await fetchAnsichStep(identifier);
    await fetchAnsichStepContext(identifier);
    await fetchAnsichContentPayload(identifier);

    const encoded = encodeURIComponent(identifier);
    expect(mockedFetch.mock.calls.map((call) => call[0])).toEqual([
      expect.stringContaining(`/api/ansich/tasks/${encoded}/steps`),
      expect.stringContaining(`/api/ansich/steps/${encoded}`),
      expect.stringContaining(`/api/ansich/steps/${encoded}/context`),
      expect.stringContaining(`/api/ansich/content-blocks/${encoded}/payload`),
    ]);
  });

  it("loads lineage, possible exposure, snapshot, and compression details lazily by identifier", async () => {
    mockedFetch.mockResolvedValue(jsonResponse({}));
    const identifier = "lineage/id with spaces";

    await fetchAnsichContentLineage(identifier, "backward", 4, 80);
    await fetchAnsichContentExposures(identifier, 6, 120);
    await fetchAnsichContextSnapshot(identifier);
    await fetchAnsichContextCompression(identifier);

    const encoded = encodeURIComponent(identifier);
    expect(mockedFetch.mock.calls.map((call) => call[0])).toEqual([
      expect.stringContaining(
        `/api/ansich/content-blocks/${encoded}/lineage?direction=backward&depth=4&nodes=80`,
      ),
      expect.stringContaining(
        `/api/ansich/content-blocks/${encoded}/exposures?depth=6&nodes=120`,
      ),
      expect.stringContaining(`/api/ansich/context-snapshots/${encoded}`),
      expect.stringContaining(`/api/ansich/context-compressions/${encoded}`),
    ]);
  });

  it("preserves projection health from a storage-unavailable response", async () => {
    mockedFetch.mockResolvedValue({
      ok: false,
      status: 503,
      statusText: "Service Unavailable",
      json: async () => ({
        detail: {
          message: "Ansich storage is unavailable",
          projection_status: { status: "failed", failed_jobs: 2 },
        },
      }),
    } as Response);

    try {
      await fetchAnsichTasks();
      throw new Error("expected fetchAnsichTasks to reject");
    } catch (error) {
      expect(error).toBeInstanceOf(AnsichApiError);
      expect(error).toMatchObject({
        message: "Ansich storage is unavailable",
        status: 503,
        projectionStatus: { status: "failed", failed_jobs: 2 },
      });
    }
  });
});
