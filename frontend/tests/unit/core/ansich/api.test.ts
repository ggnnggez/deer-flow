import { beforeEach, describe, expect, it, rs } from "@rstest/core";

rs.mock("@/core/api/fetcher", () => ({
  fetch: rs.fn(),
}));

import {
  AnsichApiError,
  acknowledgeAnsichAlert,
  dismissAnsichAlert,
  executeAnsichTaskAction,
  fetchAnsichAlert,
  fetchAnsichAlerts,
  fetchAnsichActiveTasks,
  fetchAnsichContentExposures,
  fetchAnsichContentLineage,
  fetchAnsichContentPayload,
  fetchAnsichContextCompression,
  fetchAnsichContextSnapshot,
  fetchAnsichStep,
  fetchAnsichStepContext,
  fetchAnsichTask,
  fetchAnsichTaskCompressions,
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

  it("requests terminal Task history before pagination", async () => {
    mockedFetch.mockResolvedValue(
      jsonResponse({ items: [], projection_status: { status: "healthy" } }),
    );

    await fetchAnsichTasks(75, "terminal");

    expect(mockedFetch).toHaveBeenCalledWith(
      expect.stringContaining(
        "/api/ansich/tasks?limit=75&lifecycle_scope=terminal",
      ),
    );
  });

  it("continues terminal Task history from an opaque cursor", async () => {
    mockedFetch.mockResolvedValue(
      jsonResponse({ items: [], projection_status: { status: "healthy" } }),
    );

    await fetchAnsichTasks(75, "terminal", "cursor/with spaces");

    expect(mockedFetch).toHaveBeenCalledWith(
      expect.stringContaining("&cursor=cursor%2Fwith+spaces"),
    );
  });

  it("pages Task compression summaries independently from timeline", async () => {
    mockedFetch.mockResolvedValue(
      jsonResponse({ items: [], projection_status: { status: "healthy" } }),
    );

    await fetchAnsichTaskCompressions(
      "task/with spaces",
      25,
      "cursor/with spaces",
    );

    expect(mockedFetch).toHaveBeenCalledWith(
      expect.stringContaining(
        "/api/ansich/tasks/task%2Fwith%20spaces/context-compressions?limit=25&cursor=cursor%2Fwith+spaces",
      ),
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

  it("uses the Phase 6 alert and operator action endpoints", async () => {
    mockedFetch.mockResolvedValue(jsonResponse({}));

    await fetchAnsichAlerts(25, {
      alertType: "exact_repetition",
      workflowState: "open",
      taskId: "task/one",
      cursor: "next page",
    });
    await fetchAnsichAlert("alert/one");
    await acknowledgeAnsichAlert("alert/one", 2);
    await dismissAnsichAlert("alert/one", 3, "expected maintenance");
    await executeAnsichTaskAction("task/one", "rollback", "rollback-once");

    expect(mockedFetch.mock.calls[0]?.[0]).toEqual(
      expect.stringContaining(
        "/api/ansich/operations/alerts?limit=25&type=exact_repetition&state=open&task=task%2Fone&cursor=next+page",
      ),
    );
    expect(mockedFetch.mock.calls[1]?.[0]).toEqual(
      expect.stringContaining("/api/ansich/operations/alerts/alert%2Fone"),
    );
    expect(mockedFetch.mock.calls[2]?.[1]).toMatchObject({
      method: "POST",
      body: JSON.stringify({ workflow_version: 2 }),
    });
    expect(mockedFetch.mock.calls[3]?.[1]).toMatchObject({
      method: "POST",
      body: JSON.stringify({
        workflow_version: 3,
        reason: "expected maintenance",
      }),
    });
    expect(mockedFetch.mock.calls[4]?.[1]).toMatchObject({
      method: "POST",
      headers: { "Idempotency-Key": "rollback-once" },
    });
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
