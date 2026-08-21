import { describe, expect, it } from "@rstest/core";

import {
  ANSICH_UNKNOWN_VALUE,
  formatAnsichCount,
  getDatabaseHealthPresentation,
} from "@/core/ansich/presentation";
import type { AnsichDatabaseHealth } from "@/core/ansich/types";

function reachable(
  overrides: Partial<AnsichDatabaseHealth> = {},
): AnsichDatabaseHealth {
  return {
    status: "reachable",
    projectors: [
      {
        projector_name: "task-structural",
        projector_version: "1",
        pending: 2,
        retry: 1,
        processing: 1,
        failed: 0,
        complete_through: 41,
      },
      {
        projector_name: "task-usage",
        projector_version: "1",
        pending: 0,
        retry: 0,
        processing: 0,
        failed: 3,
        complete_through: 12,
      },
    ],
    lag_ms: 1_200,
    failed_jobs: 3,
    stale_completion_count: 0,
    ...overrides,
  };
}

describe("formatAnsichCount", () => {
  it("renders an unknown number as an explicit marker, never as zero", () => {
    expect(formatAnsichCount(null)).toBe(ANSICH_UNKNOWN_VALUE);
    expect(formatAnsichCount(undefined)).toBe(ANSICH_UNKNOWN_VALUE);
    expect(ANSICH_UNKNOWN_VALUE).not.toBe("0");
  });

  it("renders a real zero as zero", () => {
    expect(formatAnsichCount(0)).toBe("0");
  });

  it("groups large counts", () => {
    expect(formatAnsichCount(1234)).toBe((1234).toLocaleString());
  });
});

describe("getDatabaseHealthPresentation", () => {
  it("keeps retry as its own bucket beside pending", () => {
    const view = getDatabaseHealthPresentation(reachable());
    const [structural] = view.projectors;
    expect(structural?.pending).toBe(2);
    expect(structural?.retry).toBe(1);
    expect(structural?.processing).toBe(1);
    expect(structural?.failed).toBe(0);
    // Every unsettled bucket is owed work; retry is never folded into pending.
    expect(structural?.outstanding).toBe(4);
  });

  it("preserves the backend's projector order and identifies each version", () => {
    const view = getDatabaseHealthPresentation(reachable());
    expect(view.projectors.map((row) => row.key)).toEqual([
      "task-structural@1",
      "task-usage@1",
    ]);
    expect(view.projectors.map((row) => row.name)).toEqual([
      "task-structural",
      "task-usage",
    ]);
  });

  it("marks only projectors with durably failed jobs as needing attention", () => {
    const view = getDatabaseHealthPresentation(reachable());
    expect(view.projectors.map((row) => row.attention)).toEqual([false, true]);
    expect(view.attention).toBe(true);
  });

  it("does not treat re-armed work as a failure", () => {
    const view = getDatabaseHealthPresentation(
      reachable({
        projectors: [
          {
            projector_name: "task-structural",
            projector_version: "1",
            pending: 0,
            retry: 5,
            processing: 0,
            failed: 0,
            complete_through: 7,
          },
        ],
        failed_jobs: 0,
      }),
    );
    expect(view.projectors[0]?.attention).toBe(false);
    expect(view.attention).toBe(false);
  });

  it("reports the store-wide settled mark as the lowest continuity mark", () => {
    // A single hole holds the whole store's mark down; that is the point of a
    // continuity mark, and taking the maximum would claim settled work nobody
    // has settled.
    expect(getDatabaseHealthPresentation(reachable()).settledThrough).toBe(12);
  });

  it("leaves the settled mark unknown when any projector's own mark is unknown", () => {
    const view = getDatabaseHealthPresentation(
      reachable({
        projectors: [
          {
            projector_name: "task-structural",
            projector_version: "1",
            pending: 0,
            retry: 0,
            processing: 0,
            failed: 0,
            complete_through: null,
          },
          {
            projector_name: "task-usage",
            projector_version: "1",
            pending: 0,
            retry: 0,
            processing: 0,
            failed: 0,
            complete_through: 9,
          },
        ],
      }),
    );
    expect(view.settledThrough).toBeNull();
  });

  it("leaves the settled mark unknown when no projector has ever had a job", () => {
    expect(
      getDatabaseHealthPresentation(reachable({ projectors: [] }))
        .settledThrough,
    ).toBeNull();
  });

  it("gates every number on reachability rather than rendering zeros", () => {
    const view = getDatabaseHealthPresentation({
      status: "unreachable",
      projectors: [],
      lag_ms: null,
      failed_jobs: null,
      stale_completion_count: null,
    });
    expect(view.reachable).toBe(false);
    expect(view.projectors).toEqual([]);
    expect(view.lagMs).toBeNull();
    expect(view.failedJobs).toBeNull();
    expect(view.staleCompletions).toBeNull();
    expect(view.settledThrough).toBeNull();
    expect(view.outstanding).toBeNull();
    // Unreadable is itself the incident: it must not read as a clean store.
    expect(view.attention).toBe(true);
  });

  it("discards numbers an unreachable block should never have carried", () => {
    // Defence in depth: `status` is the field every other one is conditional
    // on, so a block that says unreachable is rendered unknown whatever else
    // it carries.
    const view = getDatabaseHealthPresentation({
      ...reachable(),
      status: "unreachable",
    });
    expect(view.lagMs).toBeNull();
    expect(view.failedJobs).toBeNull();
    expect(view.staleCompletions).toBeNull();
    expect(view.projectors).toEqual([]);
  });

  it("treats an absent block the same as an unreadable one", () => {
    const view = getDatabaseHealthPresentation(undefined);
    expect(view.reachable).toBe(false);
    expect(view.failedJobs).toBeNull();
    expect(view.attention).toBe(true);
  });

  it("keeps a reachable store with nothing outstanding clean", () => {
    const view = getDatabaseHealthPresentation(
      reachable({
        projectors: [
          {
            projector_name: "task-structural",
            projector_version: "1",
            pending: 0,
            retry: 0,
            processing: 0,
            failed: 0,
            complete_through: 88,
          },
        ],
        lag_ms: 0,
        failed_jobs: 0,
      }),
    );
    expect(view.attention).toBe(false);
    expect(view.outstanding).toBe(0);
    expect(view.settledThrough).toBe(88);
    expect(view.lagMs).toBe(0);
  });
});
