import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

const TASK_ID = "8a54d86c-b524-4f18-83e8-79b729c2a695";
const HEALTH = {
  status: "healthy",
  queue_depth: 0,
  queue_capacity: 10_000,
  accepted_count: 3,
  dropped_count: 0,
  lost_ranges: [],
  watermark: 3,
  lag_ms: 0,
  failed_jobs: 0,
  loss_detected: false,
  range_known: true,
  storage_available: true,
};
const TASK = {
  task_id: TASK_ID,
  source_kind: "deerflow_run",
  source_id: "run-e2e",
  control: {
    value: "completed",
    as_of: "2026-07-17T12:00:03Z",
    asserted_at: "2026-07-17T12:00:03Z",
    source: { name: "task-control", version: "1" },
    fidelity_class: "hard",
    selected_by: { name: "control-state", version: "1" },
    evidence_obs_ids: ["13bd27c7-51b1-4164-9380-b98c40c2bfe0"],
  },
};

test("admin navigates from Ansich operations to evidence-backed Task detail", async ({
  page,
}) => {
  mockLangGraphAPI(page, { threads: [] });
  await page.route("**/api/ansich/tasks?*", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: [TASK],
        next_cursor: null,
        projection_status: HEALTH,
      }),
    }),
  );
  await page.route(`**/api/ansich/tasks/${TASK_ID}`, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ task: TASK, projection_status: HEALTH }),
    }),
  );
  await page.route(`**/api/ansich/tasks/${TASK_ID}/timeline`, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: [
          {
            obs_id: "13bd27c7-51b1-4164-9380-b98c40c2bfe0",
            schema_version: 1,
            kind: "task.completed",
            occurred_at: "2026-07-17T12:00:03Z",
            recorded_at: "2026-07-17T12:00:03Z",
            task_id: TASK_ID,
            subject_type: "task",
            subject_id: TASK_ID,
            fidelity_class: "hard",
            producer: {
              name: "deerflow-task-control",
              version: "1",
              instance_id: "e2e",
            },
            producer_seq: 3,
            source_event_id: "run:run-e2e:task:terminal:completed",
            correlation_id: "run-e2e",
            causation_obs_id: null,
            payload: {
              source_kind: "deerflow_run",
              source_id: "run-e2e",
            },
            payload_ref_id: null,
          },
        ],
        projection_status: HEALTH,
      }),
    }),
  );

  await page.goto("/workspace/chats/new");
  await page.getByRole("link", { name: "Ansich" }).click();
  await page.waitForURL("**/workspace/ansich/operations");
  await expect(page.getByRole("heading", { name: "Operations" })).toBeVisible();
  await expect(page.getByText("Healthy", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: new RegExp(TASK_ID) }).click();

  await page.waitForURL(`**/workspace/ansich/tasks/${TASK_ID}`);
  await expect(page.getByRole("heading", { name: TASK_ID })).toBeVisible();
  await expect(page.getByText("task.completed", { exact: true })).toBeVisible();
  await expect(page.getByText("task-control@1", { exact: true })).toBeVisible();
});

test("operations page preserves storage-unavailable detail from a 503", async ({
  page,
}) => {
  mockLangGraphAPI(page, { threads: [] });
  await page.route("**/api/ansich/tasks?*", (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({
        detail: {
          message: "Ansich storage is unavailable",
          projection_status: { ...HEALTH, status: "failed" },
        },
      }),
    }),
  );

  await page.goto("/workspace/ansich/operations");

  await expect(page.getByText("Ansich storage is unavailable")).toBeVisible();
});
