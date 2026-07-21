import { beforeEach, describe, expect, it, rs } from "@rstest/core";

rs.mock("@/core/config", () => ({
  getBackendBaseURL: () => "http://backend.test",
}));

rs.mock("@/core/api/fetcher", () => ({
  fetch: rs.fn(),
}));

import {
  fetchAnsichFailedJobDetail,
  fetchAnsichFailedJobs,
  retryAnsichFailedJobs,
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

describe("ansich failed-job api", () => {
  beforeEach(() => {
    mockedFetch.mockReset();
  });

  it("fetchAnsichFailedJobs omits the task filter when taskId is not given", async () => {
    mockedFetch.mockResolvedValue(
      jsonResponse({ items: [], projection_status: {} }),
    );
    await fetchAnsichFailedJobs();
    const [url] = mockedFetch.mock.calls[0] as [string];
    expect(url).toBe(
      "http://backend.test/api/ansich/operations/failed-jobs?limit=100",
    );
  });

  it("fetchAnsichFailedJobs includes the task filter when taskId is given", async () => {
    mockedFetch.mockResolvedValue(
      jsonResponse({ items: [], projection_status: {} }),
    );
    await fetchAnsichFailedJobs("task-1", 50);
    const [url] = mockedFetch.mock.calls[0] as [string];
    expect(url).toBe(
      "http://backend.test/api/ansich/operations/failed-jobs?limit=50&task=task-1",
    );
  });

  it("fetchAnsichFailedJobDetail requests the given job id and kind", async () => {
    mockedFetch.mockResolvedValue(
      jsonResponse({ job: {}, projection_status: {} }),
    );
    await fetchAnsichFailedJobDetail("job-1", "assessor");
    const [url] = mockedFetch.mock.calls[0] as [string];
    expect(url).toBe(
      "http://backend.test/api/ansich/operations/failed-jobs/job-1?kind=assessor",
    );
  });

  it("retryAnsichFailedJobs POSTs without a query string when global", async () => {
    mockedFetch.mockResolvedValue(
      jsonResponse({ retried: 0, projection_status: {} }),
    );
    await retryAnsichFailedJobs();
    const [url, init] = mockedFetch.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(
      "http://backend.test/api/ansich/operations/failed-jobs/retry",
    );
    expect(init.method).toBe("POST");
  });

  it("retryAnsichFailedJobs POSTs with the task filter when scoped", async () => {
    mockedFetch.mockResolvedValue(
      jsonResponse({ retried: 1, projection_status: {} }),
    );
    await retryAnsichFailedJobs("task-1");
    const [url] = mockedFetch.mock.calls[0] as [string];
    expect(url).toBe(
      "http://backend.test/api/ansich/operations/failed-jobs/retry?task=task-1",
    );
  });
});
