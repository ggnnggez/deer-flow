import { describe, expect, it } from "@rstest/core";

import {
  ANSICH_UNKNOWN_VALUE,
  databaseHealthBadge,
  formatAnsichCount,
  formatAnsichLag,
  formatAnsichSequence,
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
    active_versions: [
      {
        component_kind: "projector",
        component_name: "task-structural",
        active_version: "1",
        code_default_version: "1",
        origin: "code_default",
        activated_at: null,
        activated_by: null,
        audit_obs_id: null,
      },
      {
        component_kind: "resolver",
        component_name: "ansich-default",
        active_version: "1.0.0",
        code_default_version: "2.0.0",
        origin: "activated_audited",
        activated_at: "2026-08-22T09:00:00Z",
        activated_by: "operator@example.com",
        audit_obs_id: "3f2504e0-4f89-41d3-9a0c-0305e82c3301",
      },
    ],
    ...overrides,
  };
}

describe("formatAnsichCount", () => {
  it("renders an unknown number as an explicit marker, never as zero", () => {
    expect(formatAnsichCount(null, "en-US")).toBe(ANSICH_UNKNOWN_VALUE);
    expect(formatAnsichCount(undefined, "en-US")).toBe(ANSICH_UNKNOWN_VALUE);
    expect(ANSICH_UNKNOWN_VALUE).not.toBe("0");
  });

  it("renders a real zero as zero", () => {
    expect(formatAnsichCount(0, "en-US")).toBe("0");
  });

  it("groups a quantity by the app locale, not the browser's", () => {
    // Pinned literally: `toLocaleString()` with no argument would follow
    // whatever locale the browser happens to run in, so a zh-CN reader on a
    // de-DE machine would get German separators inside an app that never
    // offered German.
    expect(formatAnsichCount(1234567, "en-US")).toBe("1,234,567");
    expect(formatAnsichCount(1234567, "zh-CN")).toBe("1,234,567");
  });

  it("falls back to the default locale for one it does not offer", () => {
    expect(formatAnsichCount(1234567, "de-DE")).toBe("1,234,567");
  });
});

describe("formatAnsichSequence", () => {
  it("renders a sequence mark ungrouped — it is a position, not a quantity", () => {
    // An ingest sequence is compared against raw `ingest_seq` values in logs
    // and API responses, which carry no separators.
    expect(formatAnsichSequence(1234567)).toBe("1234567");
  });

  it("keeps unknown distinct from zero here too", () => {
    expect(formatAnsichSequence(null)).toBe(ANSICH_UNKNOWN_VALUE);
    expect(formatAnsichSequence(0)).toBe("0");
  });
});

describe("formatAnsichLag", () => {
  it("splits sub-second from second lag, the way the health line already does", () => {
    expect(formatAnsichLag(450)).toBe("450ms");
    expect(formatAnsichLag(1200)).toBe("1.2s");
    expect(formatAnsichLag(0)).toBe("0ms");
  });

  it("renders unknown lag as the unknown marker", () => {
    expect(formatAnsichLag(null)).toBe(ANSICH_UNKNOWN_VALUE);
  });
});

describe("databaseHealthBadge", () => {
  it("separates a store that needs attention from a healthy one", () => {
    // A reachable store with durably failed jobs is not a green headline: the
    // condition the projection_failure Alert exists for must be visible in the
    // one badge an operator scans.
    expect(
      databaseHealthBadge(getDatabaseHealthPresentation(reachable())),
    ).toBe("attention");
  });

  it("calls a reachable store with nothing owed healthy", () => {
    expect(
      databaseHealthBadge(
        getDatabaseHealthPresentation(
          reachable({
            projectors: [
              {
                projector_name: "task-structural",
                projector_version: "1",
                pending: 0,
                retry: 2,
                processing: 1,
                failed: 0,
                complete_through: 88,
              },
            ],
            failed_jobs: 0,
          }),
        ),
      ),
    ).toBe("healthy");
  });

  it("keeps an unreadable store its own state, distinct from both", () => {
    expect(databaseHealthBadge(getDatabaseHealthPresentation(undefined))).toBe(
      "unreadable",
    );
  });

  it("never calls an unknown failed-job count healthy", () => {
    // `null` means unknown here and nowhere means zero. A `?? 0` would coerce
    // this into "no failed jobs" and hand back a green headline built on a
    // number nobody read — the one thing the block's own contract forbids, and
    // the opposite of what the `unreachable` branch does with the same
    // uncertainty. Unknown belongs in `attention`, not in a fourth state: the
    // badge's job is "does an operator need to look at this", and the answer
    // for an unreadable count is yes, exactly as for a nonzero one.
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
        failed_jobs: null,
      }),
    );

    expect(view.failedJobs).toBeNull();
    expect(view.attention).toBe(true);
    expect(databaseHealthBadge(view)).not.toBe("healthy");
    expect(databaseHealthBadge(view)).toBe("attention");
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
      active_versions: null,
    });
    expect(view.reachable).toBe(false);
    expect(view.projectors).toEqual([]);
    expect(view.lagMs).toBeNull();
    expect(view.failedJobs).toBeNull();
    expect(view.staleCompletions).toBeNull();
    expect(view.settledThrough).toBeNull();
    expect(view.outstanding).toBeNull();
    // `null`, never `[]`: an empty list would read as "this store runs no
    // versioned components", which is a configuration claim about a block
    // nobody could read.
    expect(view.activeVersions).toBeNull();
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
    expect(view.activeVersions).toBeNull();
  });

  it("marks a component nobody switched as running the code default", () => {
    const rows = getDatabaseHealthPresentation(reachable()).activeVersions;
    expect(rows).not.toBeNull();
    const projector = rows!.find((row) => row.kind === "projector")!;
    expect(projector.key).toBe("projector/task-structural");
    expect(projector.isCodeDefault).toBe(true);
    expect(projector.origin).toBe("code_default");
    expect(projector.version).toBe(projector.codeDefault);
    // Nobody activated it, so there is no actor and no timestamp to show —
    // never a placeholder name, never an epoch date.
    expect(projector.activatedBy).toBeNull();
    expect(projector.activatedAt).toBeNull();
  });

  it("keeps a deliberate switch apart from the default it deviates from", () => {
    const rows = getDatabaseHealthPresentation(reachable()).activeVersions!;
    const resolver = rows.find((row) => row.kind === "resolver")!;
    expect(resolver.isCodeDefault).toBe(false);
    expect(resolver.version).toBe("1.0.0");
    expect(resolver.codeDefault).toBe("2.0.0");
    expect(resolver.activatedBy).toBe("operator@example.com");
  });

  it("renders a missing active-version field as unknown rather than empty", () => {
    // A backend that predates the field, or a block whose read failed: either
    // way the panel must say "unknown", not "no components".
    const view = getDatabaseHealthPresentation(
      reachable({ active_versions: null }),
    );
    expect(view.reachable).toBe(true);
    expect(view.activeVersions).toBeNull();
  });

  it("keeps the two degraded audit states distinguishable", () => {
    // "The evidence expired under retention" and "there never was any" are
    // different answers to whether the switch was authorised, and the latch
    // column exists precisely so they do not collapse into one.
    const rows = getDatabaseHealthPresentation(
      reachable({
        active_versions: [
          {
            component_kind: "resolver",
            component_name: "ansich-default",
            active_version: "1.0.0",
            code_default_version: "2.0.0",
            origin: "activated_expired",
            activated_at: "2026-08-22T09:00:00Z",
            activated_by: "operator",
            audit_obs_id: null,
          },
          {
            component_kind: "projector",
            component_name: "task-step",
            active_version: "1",
            code_default_version: "1",
            origin: "activated_unaudited",
            activated_at: "2026-08-22T09:00:00Z",
            activated_by: "operator",
            audit_obs_id: null,
          },
        ],
      }),
    ).activeVersions!;
    expect(rows.map((row) => row.origin)).toEqual([
      "activated_expired",
      "activated_unaudited",
    ]);
    expect(rows.every((row) => row.isCodeDefault)).toBe(false);
  });

  it("treats an absent block the same as an unreadable one", () => {
    const view = getDatabaseHealthPresentation(undefined);
    expect(view.reachable).toBe(false);
    expect(view.failedJobs).toBeNull();
    expect(view.attention).toBe(true);
  });

  it("hands back an unreadable view nobody can mutate for the next reader", () => {
    // The unreadable answer is one shared singleton, so a consumer that pushed
    // into `projectors` would corrupt every later read.
    const view = getDatabaseHealthPresentation(undefined);
    expect(Object.isFrozen(view)).toBe(true);
    expect(Object.isFrozen(view.projectors)).toBe(true);
    expect(() => view.projectors.push({} as never)).toThrow();
    expect(getDatabaseHealthPresentation(null).projectors).toEqual([]);
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
