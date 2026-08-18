import { beforeEach, describe, expect, it, rs } from "@rstest/core";

rs.mock("@/core/api/fetcher", () => ({
  fetch: rs.fn(),
}));

import {
  AnsichApiError,
  compareAnsichAgentReleases,
  fetchAnsichReleaseQuality,
  fetchAnsichStepEvaluations,
  fetchAnsichTaskEvaluations,
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

const unassessedBelief = {
  dimension: "task_success",
  value: { status: "unassessed" },
  source: { name: "none", version: "0" },
  authority_class: "unknown",
  fidelity_class: "unknown",
  as_of: null,
  resolver: null,
  conflicting_assertion_count: 0,
  evidence_obs_ids: [],
  unassessed: true,
};

const evaluationRow = {
  evaluation_obs_id: "obs-1",
  subject_type: "task",
  subject_id: "task/one",
  task_id: "task/one",
  evaluation_kind: "benchmark_assertion",
  dimension: "task_success",
  verdict: "pass",
  score: 7,
  scale_min: 0,
  scale_max: 10,
  scale_higher_is_better: true,
  assessor_name: "suite-runner",
  assessor_version: "1.0.0",
  authority_class: "deterministic",
  fidelity_class: "hard",
  cohort_key: "suite@1.0",
  suite_id: "suite",
  suite_version: "1.0",
  case_id: "case-1",
  occurred_at: "2026-08-18T00:00:00Z",
};

describe("Ansich evaluation API", () => {
  beforeEach(() => {
    mockedFetch.mockReset();
  });

  it("reads a Task's quality Beliefs and evaluation rows from one GET", async () => {
    const body = {
      task_id: "task/one",
      quality_beliefs: [unassessedBelief],
      evaluations: [evaluationRow],
      projection_status: { status: "healthy" },
    };
    mockedFetch.mockResolvedValue(jsonResponse(body));

    const result = await fetchAnsichTaskEvaluations("task/one");

    expect(mockedFetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/ansich/tasks/task%2Fone/evaluations"),
    );
    expect(mockedFetch.mock.calls[0]?.[1]).toBeUndefined();
    expect(result).toEqual(body);
  });

  it("reads Step evaluations from the Step-scoped endpoint", async () => {
    const body = {
      step_id: "step/one",
      evaluations: [{ ...evaluationRow, subject_type: "step" }],
      projection_status: { status: "healthy" },
    };
    mockedFetch.mockResolvedValue(jsonResponse(body));

    const result = await fetchAnsichStepEvaluations("step/one");

    expect(mockedFetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/ansich/steps/step%2Fone/evaluations"),
    );
    expect(mockedFetch.mock.calls[0]?.[1]).toBeUndefined();
    expect(result).toEqual(body);
  });

  it("omits the cohort filter from release quality when none is selected", async () => {
    mockedFetch.mockResolvedValue(
      jsonResponse({
        release_id: "release/one",
        cohorts: [],
        projection_status: { status: "healthy" },
      }),
    );

    await fetchAnsichReleaseQuality("release/one");

    const url = mockedFetch.mock.calls[0]?.[0] as string;
    expect(url).toContain("/api/ansich/agent-releases/release%2Fone/quality");
    expect(url).not.toContain("cohort");
  });

  it("threads a selected cohort onto the release quality query", async () => {
    mockedFetch.mockResolvedValue(
      jsonResponse({
        release_id: "release/one",
        cohorts: [
          {
            dimension: "task_success",
            cohort_key: "suite@1.0",
            assessed_count: 4,
            pass_count: 3,
            fail_count: 1,
            partial_count: 0,
            mean_score: 7.5,
            scale: { min: 0, max: 10, higher_is_better: true },
            as_of: "2026-08-18T00:00:00Z",
          },
        ],
        projection_status: { status: "healthy" },
      }),
    );

    const result = await fetchAnsichReleaseQuality("release/one", "suite@1.0");

    expect(mockedFetch.mock.calls[0]?.[0]).toEqual(
      expect.stringContaining(
        "/api/ansich/agent-releases/release%2Fone/quality?cohort=suite%401.0",
      ),
    );
    expect(result.cohorts[0]?.cohort_key).toBe("suite@1.0");
  });

  it("keeps the empty no-cohort sentinel as an explicit filter", async () => {
    mockedFetch.mockResolvedValue(
      jsonResponse({
        release_id: "release/one",
        cohorts: [],
        projection_status: { status: "healthy" },
      }),
    );

    await fetchAnsichReleaseQuality("release/one", "");

    expect(mockedFetch.mock.calls[0]?.[0]).toEqual(
      expect.stringContaining(
        "/api/ansich/agent-releases/release%2Fone/quality?cohort=",
      ),
    );
  });

  it("compares releases without a cohort parameter by default", async () => {
    mockedFetch.mockResolvedValue(jsonResponse({}));

    await compareAnsichAgentReleases("release/left", "release right");

    const url = mockedFetch.mock.calls[0]?.[0] as string;
    expect(url).toContain(
      "/api/ansich/agent-releases/compare?left=release%2Fleft&right=release+right",
    );
    expect(url).not.toContain("cohort");
  });

  it("threads an explicit comparison cohort onto the compare query", async () => {
    mockedFetch.mockResolvedValue(jsonResponse({}));

    await compareAnsichAgentReleases(
      "release/left",
      "release/right",
      "suite@1.0",
    );

    expect(mockedFetch.mock.calls[0]?.[0]).toEqual(
      expect.stringContaining(
        "/api/ansich/agent-releases/compare?left=release%2Fleft&right=release%2Fright&cohort=suite%401.0",
      ),
    );
  });

  it("tolerates a comparison payload that carries no quality block", async () => {
    const body = {
      comparison: { changed_components: [] },
      projection_status: { status: "healthy" },
    };
    mockedFetch.mockResolvedValue(jsonResponse(body));

    const result = await compareAnsichAgentReleases("left", "right");

    expect(result.quality).toBeUndefined();
  });

  it("returns the typed quality comparison block when the backend sends one", async () => {
    mockedFetch.mockResolvedValue(
      jsonResponse({
        comparison: { changed_components: [] },
        quality: {
          comparisons: [
            {
              dimension: "task_success",
              cohort_key: "",
              comparison_status: "not_comparable",
              reason: "no_shared_cohort",
              observed_delta: null,
              left_sample_count: 2,
              right_sample_count: 0,
              coverage: { unexplained_loss: false },
              resolver: { name: "ansich.quality", version: "1" },
            },
          ],
          cohort: null,
        },
        projection_status: { status: "healthy" },
      }),
    );

    const result = await compareAnsichAgentReleases("left", "right");

    expect(result.quality?.cohort).toBeNull();
    expect(result.quality?.comparisons[0]?.reason).toBe("no_shared_cohort");
  });

  it("preserves projection health when an evaluation query is rejected", async () => {
    mockedFetch.mockResolvedValue({
      ok: false,
      status: 503,
      statusText: "Service Unavailable",
      json: async () => ({
        detail: {
          message: "Ansich evaluation query failed",
          projection_status: { status: "failed", failed_jobs: 3 },
        },
      }),
    } as Response);

    try {
      await fetchAnsichTaskEvaluations("task/one");
      throw new Error("expected fetchAnsichTaskEvaluations to reject");
    } catch (error) {
      expect(error).toBeInstanceOf(AnsichApiError);
      expect(error).toMatchObject({
        message: "Ansich evaluation query failed",
        status: 503,
        projectionStatus: { status: "failed", failed_jobs: 3 },
      });
    }
  });

  it("surfaces a plain gateway detail from a rejected Step evaluation query", async () => {
    mockedFetch.mockResolvedValue({
      ok: false,
      status: 404,
      statusText: "Not Found",
      json: async () => ({ detail: "Ansich Step not found" }),
    } as Response);

    await expect(fetchAnsichStepEvaluations("step/one")).rejects.toThrow(
      "Ansich Step not found",
    );
  });

  it("surfaces a plain gateway detail from a rejected release quality query", async () => {
    mockedFetch.mockResolvedValue({
      ok: false,
      status: 403,
      statusText: "Forbidden",
      json: async () => ({ detail: "Administrator access required" }),
    } as Response);

    await expect(fetchAnsichReleaseQuality("release/one")).rejects.toThrow(
      "Administrator access required",
    );
  });
});
