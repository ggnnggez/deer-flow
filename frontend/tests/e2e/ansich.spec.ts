import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

const TASK_ID = "8a54d86c-b524-4f18-83e8-79b729c2a695";
const STEP_ID = "bb24aa10-f647-4c07-959a-0594087c818c";
const BLOCK_ID = "d62dc6fd-4a91-4d32-95ae-3be8e1ddb1a9";
const TOOL_CALL_ID = "3d4a8ed4-3996-41cb-9181-558ca744867b";
const TOOL_RAW_BLOCK_ID = "967ddaf9-057c-4b8c-88f7-a59476eb50d5";
const TOOL_VISIBLE_BLOCK_ID = "bb695124-12f7-48fd-bc4e-54058924d85a";
const COMPRESSION_ID = "ac695124-12f7-48fd-bc4e-54058924d85a";
const SUMMARY_BLOCK_ID = "cc695124-12f7-48fd-bc4e-54058924d85a";
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
  queue_high_watermark: 2,
  snapshot_request_count: 1,
  snapshot_observations_accepted: 3,
  snapshot_observations_dropped: 0,
  snapshot_count: 1,
  snapshot_item_count: 1,
  snapshot_visible_bytes: 11,
  incomplete_snapshot_count: 0,
  missing_content_block_count: 0,
};
const TASK = {
  task_id: TASK_ID,
  source_kind: "deerflow_run",
  source_id: "run-e2e",
  tool_calls_issued: 1,
  tool_calls_executed: 1,
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
          {
            ingest_seq: 4,
            obs_id: "23bd27c7-51b1-4164-9380-b98c40c2bfe0",
            schema_version: 1,
            kind: "context.compressed",
            occurred_at: "2026-07-17T12:00:04Z",
            recorded_at: "2026-07-17T12:00:04Z",
            task_id: TASK_ID,
            step_id: null,
            subject_type: "context_compression",
            subject_id: COMPRESSION_ID,
            fidelity_class: "hard",
            producer: {
              name: "deerflow-context-compression-observer",
              version: "1",
              instance_id: "e2e",
            },
            producer_seq: 4,
            source_event_id: `context-compression:${COMPRESSION_ID}`,
            correlation_id: TASK_ID,
            causation_obs_id: null,
            payload: { summary_block_id: SUMMARY_BLOCK_ID },
            payload_ref_id: null,
          },
        ],
        projection_status: HEALTH,
      }),
    }),
  );
  await page.route(`**/api/ansich/tasks/${TASK_ID}/steps`, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: [
          {
            step_id: STEP_ID,
            task_id: TASK_ID,
            step_seq: 1,
            actor_kind: "lead_agent",
            status: "closed",
            result: "final_answer",
            started_obs_id: "09b3076b-e600-4761-9fe7-228486a35e6d",
            closed_obs_id: "20fc41b9-cb32-4dfd-b3ce-a8412964cba2",
            effective_attempt_no: 2,
            effective_context_snapshot_id:
              "bd7e11c4-c8bc-4326-a59e-78b55f848e7e",
            issued_tools: [],
            tool_calls: [
              {
                tool_call_id: TOOL_CALL_ID,
                task_id: TASK_ID,
                step_id: STEP_ID,
                step_seq: 1,
                call_seq: 1,
                provider_call_id: "provider-e2e-tool",
                tool_name: "web_search",
                args_hash:
                  "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                args_preview: { query: "Ansich" },
                tool_schema_block_id: null,
                issued_obs_id: "67b85846-5df6-4830-a01f-369af7ca3a8c",
                started_obs_id: "0284b2b7-8858-4ee5-b5e3-af0bf80898d4",
                raw_terminal_obs_id: "d23a9970-dc7c-4183-9e2b-c33399331e84",
                visible_result_obs_id: "16ba49a8-b1f7-48a8-adc3-a5af3fb0fa1e",
                duration_ms: 14,
                authorization: {
                  value: "unknown",
                  as_of: null,
                  asserted_at: "2026-07-17T12:00:02Z",
                  source: { name: "tool-accountability", version: "1" },
                  fidelity_class: "hard",
                  selected_by: {
                    name: "tool-authorization-state",
                    version: "1",
                  },
                  evidence_obs_ids: [],
                },
                execution: {
                  value: "returned",
                  as_of: "2026-07-17T12:00:02Z",
                  asserted_at: "2026-07-17T12:00:02Z",
                  source: { name: "deerflow-tool-observer", version: "1" },
                  fidelity_class: "hard",
                  selected_by: {
                    name: "tool-execution-state",
                    version: "1",
                  },
                  evidence_obs_ids: ["d23a9970-dc7c-4183-9e2b-c33399331e84"],
                },
                visible_result: {
                  value: "available",
                  as_of: "2026-07-17T12:00:02Z",
                  asserted_at: "2026-07-17T12:00:02Z",
                  source: { name: "deerflow-tool-observer", version: "1" },
                  fidelity_class: "hard",
                  selected_by: {
                    name: "tool-visible-result-state",
                    version: "1",
                  },
                  evidence_obs_ids: ["16ba49a8-b1f7-48a8-adc3-a5af3fb0fa1e"],
                },
                raw_results: [
                  {
                    result_role: "raw",
                    content_block_id: TOOL_RAW_BLOCK_ID,
                    source_obs_id: "d23a9970-dc7c-4183-9e2b-c33399331e84",
                    content_hash:
                      "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                    byte_size: 32,
                    payload_available: true,
                    metadata: {},
                  },
                ],
                visible_results: [
                  {
                    result_role: "visible",
                    content_block_id: TOOL_VISIBLE_BLOCK_ID,
                    source_obs_id: "16ba49a8-b1f7-48a8-adc3-a5af3fb0fa1e",
                    content_hash:
                      "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
                    byte_size: 28,
                    payload_available: true,
                    metadata: { transform_kind: "sanitized" },
                  },
                ],
                derivations: [
                  {
                    derived_block_id: TOOL_VISIBLE_BLOCK_ID,
                    source_block_id: TOOL_RAW_BLOCK_ID,
                    transform_kind: "sanitized",
                    transform_version: "1",
                    established_obs_id: "16ba49a8-b1f7-48a8-adc3-a5af3fb0fa1e",
                  },
                ],
              },
            ],
            attempts: [
              {
                attempt_id: "57d838c5-60d3-4925-a2e7-a8dd35dd40b3",
                task_id: TASK_ID,
                step_id: STEP_ID,
                actor_kind: "lead_agent",
                operation_id: null,
                operation_kind: null,
                attempt_no: 1,
                status: "failed",
                request_obs_id: "5f65d20a-f8a0-4ae0-8198-27b4549dc9c9",
                response_obs_id: null,
                failure_obs_id: "0c3f4ed5-e37b-4d50-b851-83f6086c0350",
                provider_model: "test-model",
                latency_ms: 12,
                context_snapshot_id: null,
                effective: false,
              },
              {
                attempt_id: "c06acdf0-bd33-463c-9077-8a10d274202f",
                task_id: TASK_ID,
                step_id: STEP_ID,
                actor_kind: "lead_agent",
                operation_id: null,
                operation_kind: null,
                attempt_no: 2,
                status: "success",
                request_obs_id: "1ac856d9-5480-4842-abd3-a56698f3438c",
                response_obs_id: "366c52fe-5579-469e-b2e5-314b8c0626a6",
                failure_obs_id: null,
                provider_model: "test-model",
                latency_ms: 8,
                context_snapshot_id: "bd7e11c4-c8bc-4326-a59e-78b55f848e7e",
                effective: true,
              },
            ],
          },
        ],
        system_operations: [],
        projection_status: HEALTH,
      }),
    }),
  );
  await page.route(`**/api/ansich/steps/${STEP_ID}/context`, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        context: {
          snapshot_id: "bd7e11c4-c8bc-4326-a59e-78b55f848e7e",
          task_id: TASK_ID,
          step_id: STEP_ID,
          operation_id: null,
          attempt_no: 2,
          request_obs_id: "1ac856d9-5480-4842-abd3-a56698f3438c",
          message_count: 1,
          tool_schema_count: 0,
          visible_bytes: 11,
          estimated_tokens: 3,
          estimator_name: "utf8-bytes-div4",
          estimator_version: "1",
          adapter_name: "test.Model",
          adapter_version: "unknown",
          configured_model: "test-model",
          response_format: null,
          generation_settings: {},
          redactions: [],
          warnings: [],
          status: "complete",
          items: [
            {
              ordinal: 0,
              channel: "message",
              role: "user",
              name: null,
              message_id: "message-e2e",
              source_identity: "message:message-e2e:occurrence:1:content:0",
              block_id: BLOCK_ID,
              kind: "user_input",
              content_hash:
                "5ca1ab1e00000000000000000000000000000000000000000000000000000000",
              visible_bytes: 11,
              estimated_tokens: 3,
              metadata: {},
              sensitivity_flags: [],
              payload_available: true,
              resolution_status: "available",
              body: null,
            },
          ],
        },
        projection_status: HEALTH,
      }),
    }),
  );
  await page.route(
    `**/api/ansich/content-blocks/${BLOCK_ID}/payload`,
    (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          payload: {
            block_id: BLOCK_ID,
            content_type: "application/json",
            body: "inspect me",
          },
        }),
      }),
  );
  let lineageRequests = 0;
  await page.route(
    `**/api/ansich/content-blocks/${BLOCK_ID}/lineage?*`,
    (route) => {
      lineageRequests += 1;
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          lineage: {
            semantic: "provenance",
            root_block_id: BLOCK_ID,
            direction: "backward",
            nodes: [
              {
                block_id: BLOCK_ID,
                kind: "user_input",
                content_hash:
                  "5ca1ab1e00000000000000000000000000000000000000000000000000000000",
                byte_size: 11,
                token_estimate: 3,
                sensitivity_flags: [],
                payload_status: "available",
                producer: {
                  producer_kind: "gateway_input",
                  producer_entity_id: null,
                  producer_obs_id: "13bd27c7-51b1-4164-9380-b98c40c2bfe0",
                },
                depth: 0,
              },
            ],
            edges: [],
            truncated: false,
            truncation_reason: null,
            unknown_gaps: [],
          },
          projection_status: HEALTH,
        }),
      });
    },
  );
  await page.route(
    `**/api/ansich/context-compressions/${COMPRESSION_ID}`,
    (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          compression: {
            compression_id: COMPRESSION_ID,
            task_id: TASK_ID,
            summary_operation_id: "dc695124-12f7-48fd-bc4e-54058924d85a",
            summary_block: {
              block_id: SUMMARY_BLOCK_ID,
              kind: "summary",
              content_hash:
                "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
              byte_size: 18,
              token_estimate: 5,
              sensitivity_flags: [],
              payload_status: "available",
              producer: null,
            },
            before_tokens: 120,
            after_tokens: 30,
            before_visible_bytes: 480,
            after_visible_bytes: 120,
            algorithm: "deerflow_summarization_middleware",
            algorithm_version: "1",
            source_obs_id: "23bd27c7-51b1-4164-9380-b98c40c2bfe0",
            status: "complete",
            items: [
              {
                disposition: "source",
                ordinal: 0,
                block: {
                  block_id: BLOCK_ID,
                  kind: "user_input",
                  content_hash:
                    "5ca1ab1e00000000000000000000000000000000000000000000000000000000",
                  byte_size: 11,
                  token_estimate: 3,
                  sensitivity_flags: [],
                  payload_status: "available",
                  producer: null,
                },
              },
            ],
          },
          projection_status: HEALTH,
        }),
      }),
  );
  await page.route(
    `**/api/ansich/tool-calls/${TOOL_CALL_ID}/raw-result`,
    (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          raw_payload: {
            block_id: TOOL_RAW_BLOCK_ID,
            content_type: "application/json",
            body: { content: "raw tool output" },
          },
        }),
      }),
  );
  await page.route(
    `**/api/ansich/tool-calls/${TOOL_CALL_ID}/visible-result`,
    (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          visible_payload: {
            block_id: TOOL_VISIBLE_BLOCK_ID,
            content_type: "application/json",
            body: { content: "sanitized tool output" },
          },
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
  await expect(page.getByText("task-control@1", { exact: true })).toBeVisible();
  await page.getByRole("tab", { name: "Lifecycle timeline" }).click();
  await expect(page.getByText("task.completed", { exact: true })).toBeVisible();
  await page.getByRole("tab", { name: "Steps" }).click();
  await expect(page.getByText("Step #1", { exact: true })).toBeVisible();
  await expect(page.getByText("Effective", { exact: true })).toBeVisible();
  await expect(page.getByText("Authorization", { exact: true })).toBeVisible();
  await expect(page.getByText("unknown", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Load raw result" }).click();
  await expect(page.getByText('"raw tool output"')).toBeVisible();
  await page.getByRole("button", { name: "Load model-visible result" }).click();
  await expect(page.getByText('"sanitized tool output"')).toBeVisible();
  await page.getByRole("tab", { name: "Context & lineage" }).click();
  expect(lineageRequests).toBe(0);
  await page.getByRole("button", { name: "Trace sources" }).click();
  await expect(page.getByText("provenance", { exact: true })).toBeVisible();
  expect(lineageRequests).toBe(1);
  await page.getByRole("button", { name: "Load compression #1" }).click();
  await expect(page.getByText("source", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Load raw payload" }).click();
  await expect(page.getByText('"inspect me"')).toBeVisible();
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
