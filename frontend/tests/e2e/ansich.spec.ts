import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

const TASK_ID = "8a54d86c-b524-4f18-83e8-79b729c2a695";
const CHILD_TASK_ID = "6a54d86c-b524-4f18-83e8-79b729c2a696";
const HISTORY_TASK_ID = "7b43c75b-a413-4e07-92d7-68a618b1f584";
const STEP_ID = "bb24aa10-f647-4c07-959a-0594087c818c";
const BLOCK_ID = "d62dc6fd-4a91-4d32-95ae-3be8e1ddb1a9";
const TOOL_CALL_ID = "3d4a8ed4-3996-41cb-9181-558ca744867b";
const TOOL_RAW_BLOCK_ID = "967ddaf9-057c-4b8c-88f7-a59476eb50d5";
const TOOL_VISIBLE_BLOCK_ID = "bb695124-12f7-48fd-bc4e-54058924d85a";
const CHILD_OUTPUT_BLOCK_ID = "fd1a78d9-e7bb-4df7-b024-175dccbcac82";
const COMPRESSION_ID = "ac695124-12f7-48fd-bc4e-54058924d85a";
const OLDER_COMPRESSION_ID = "9c695124-12f7-48fd-bc4e-54058924d85a";
const SUMMARY_BLOCK_ID = "cc695124-12f7-48fd-bc4e-54058924d85a";
const ALERT_ID = "ec695124-12f7-48fd-bc4e-54058924d85a";
const RELEASE_ID = "fc695124-12f7-48fd-bc4e-54058924d85a";
const OTHER_RELEASE_ID = "0d695124-12f7-48fd-bc4e-54058924d85a";
const RELEASE_HASH = "a".repeat(64);
const OTHER_RELEASE_HASH = "b".repeat(64);
const HEALTH = {
  status: "healthy",
  queue_depth: 0,
  queue_capacity: 10_000,
  queue_bytes: 1024,
  queue_byte_capacity: 67_108_864,
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
  queue_byte_high_watermark: 2048,
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
  observability_status: "healthy",
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
const HISTORY_TASK = {
  ...TASK,
  task_id: HISTORY_TASK_ID,
  source_id: "run-e2e-history-page-2",
};
const ACTIVE_TASK = {
  ...TASK,
  run_id: "run-e2e",
  owner_id: "owner-e2e",
  thread_id: "thread-e2e",
  agent_id: null,
  control: { ...TASK.control, value: "running" },
  current_step: {
    step_id: STEP_ID,
    step_seq: 1,
    actor_kind: "lead_agent",
    status: "acting",
  },
  current_tool: null,
  dwell: {
    value: "normal",
    since: "2026-07-17T12:00:02Z",
    duration_ms: 1_000,
    asserted_at: "2026-07-17T12:00:03Z",
    source: { name: "transition-dwell", version: "1" },
    fidelity_class: "rule",
    selected_by: { name: "dwell-state", version: "1:test" },
    evidence_obs_ids: ["13bd27c7-51b1-4164-9380-b98c40c2bfe0"],
  },
  heartbeat: {
    value: "fresh",
    as_of: "2026-07-17T12:00:03Z",
    age_ms: 1_000,
    asserted_at: "2026-07-17T12:00:04Z",
    source: { name: "heartbeat", version: "1" },
    fidelity_class: "rule",
    selected_by: { name: "heartbeat-state", version: "1:test" },
    evidence_obs_ids: ["13bd27c7-51b1-4164-9380-b98c40c2bfe0"],
  },
  usage: {
    task_id: TASK_ID,
    local: [],
    inclusive: [],
    inclusive_status: "available",
  },
  active_child_count: 1,
  budgets: { task_id: TASK_ID, budgets: [] },
  budget_health: [],
  duration_ms: 3_000,
  observability_status: "healthy",
  projection_watermark: 3,
  projection_lag_ms: 0,
  lost_ranges: [],
  last_evidence_at: "2026-07-17T12:00:03Z",
  updated_at: "2026-07-17T12:00:04Z",
};

test("admin navigates from Ansich operations to evidence-backed Task detail", async ({
  page,
}) => {
  mockLangGraphAPI(page, { threads: [] });
  await page.route("**/api/ansich/operations/active-tasks?*", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: [ACTIVE_TASK],
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
  await page.route(`**/api/ansich/tasks/${TASK_ID}/tree?*`, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        tree: {
          root_task_id: TASK_ID,
          direction: "both",
          depth: 4,
          nodes: [
            {
              task: TASK,
              agent_release: null,
              heartbeat: null,
              current_step: null,
              usage: {
                task_id: TASK_ID,
                local: [],
                inclusive: [],
                inclusive_status: "available",
              },
            },
            {
              task: {
                ...TASK,
                task_id: CHILD_TASK_ID,
                source_kind: "deerflow_subagent",
                source_id: "provider-task-e2e",
              },
              agent_release: null,
              heartbeat: null,
              current_step: {
                step_id: STEP_ID,
                step_seq: 1,
                actor_kind: "subagent",
                status: "acting",
              },
              usage: {
                task_id: CHILD_TASK_ID,
                local: [],
                inclusive: [],
                inclusive_status: "available",
              },
            },
          ],
          edges: [
            {
              parent_task_id: TASK_ID,
              spawning_step_id: STEP_ID,
              spawning_tool_call_id: TOOL_CALL_ID,
              child_task_id: CHILD_TASK_ID,
              established_obs_id: "spawn-e2e",
              subagent_name: "researcher",
            },
          ],
          truncated: false,
        },
        projection_status: HEALTH,
      }),
    }),
  );
  await page.route(`**/api/ansich/tasks/${TASK_ID}/usage?*`, (route) => {
    const scope = new URL(route.request().url()).searchParams.get("scope");
    const localValue = {
      dimension: "total_tokens",
      aggregation_scope: "local",
      value: 100,
      as_of: "2026-07-17T12:00:03Z",
      complete_through_ingest_seq: 40,
    };
    const inclusiveValue = {
      ...localValue,
      aggregation_scope: "inclusive",
      value: 160,
    };
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        usage: {
          task_id: TASK_ID,
          local: [localValue],
          inclusive: [inclusiveValue],
          inclusive_status: "available",
        },
        scope,
        values: scope === "inclusive" ? [inclusiveValue] : [localValue],
        sources:
          scope === "inclusive"
            ? [
                { source_task_id: TASK_ID, values: [localValue] },
                {
                  source_task_id: CHILD_TASK_ID,
                  values: [{ ...inclusiveValue, value: 60 }],
                },
              ]
            : [{ source_task_id: TASK_ID, values: [localValue] }],
        projection_status: HEALTH,
      }),
    });
  });
  await page.route(`**/api/ansich/tasks/${TASK_ID}/budgets`, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        budgets: { task_id: TASK_ID, budgets: [] },
        health: [],
        projection_status: HEALTH,
      }),
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
  const releaseSummary = {
    release_id: RELEASE_ID,
    namespace: "deerflow",
    agent_name: "lead-agent",
    release_hash: RELEASE_HASH,
    schema_version: 1,
    model_hash: "1".repeat(64),
    prompt_hash: "2".repeat(64),
    tool_catalog_hash: "3".repeat(64),
    policy_hash: "4".repeat(64),
    runtime_build_id: "5".repeat(64),
    created_at: "2026-07-17T12:00:00Z",
    task_count: 2,
    quality_status: "unassessed",
  };
  const releaseManifest = {
    schema_version: 1,
    namespace: "deerflow",
    agent_name: "lead-agent",
    model: {
      requested: "fast",
      effective: "provider/model-v1",
      provider: "provider",
      behavior_parameters: { temperature: 0 },
    },
    prompt: {
      template_id: "lead-v1",
      template_hash: "6".repeat(64),
      rendered_base_prompt_hash: "7".repeat(64),
      rendered_base_prompt_preview: "Controlled system prompt preview",
      soul_hash: null,
      available_skill_catalog_hash: null,
    },
    tools: [
      {
        name: "web_search",
        description: "Search the web",
        argument_schema: {
          type: "object",
          properties: { query: { type: "string" } },
        },
        schema_hash: "8".repeat(64),
        source: "builtin",
        deferred: false,
        behavior_metadata: {},
      },
    ],
    policy: {
      middleware_chain: [],
      values: { non_interactive: false },
    },
    runtime_build: {
      package_version: "2.1.0",
      image_digest: "unknown",
      git_commit: "e2e",
    },
  };
  await page.route(`**/api/ansich/tasks/${TASK_ID}/agent-release`, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        binding: {
          task_id: TASK_ID,
          relation_role: "executed_by",
          established_obs_id: "release-observation-e2e",
          release: { summary: releaseSummary, manifest: releaseManifest },
        },
        provider_drift: {
          assertion_id: "drift-e2e",
          subject_id: TASK_ID,
          field_name: "configuration_drift",
          value: {
            value: "matched",
            effective_model: "provider/model-v1",
            provider_reported_model: "models/provider/model-v1",
          },
          as_of: "2026-07-17T12:00:02Z",
          asserted_at: "2026-07-17T12:00:02Z",
          assessor: { name: "configuration-drift", version: "1.0.0" },
          config_hash: "9".repeat(64),
          authority_class: "configured_rule",
          fidelity_class: "rule",
          confidence: null,
          evidence_obs_ids: ["provider-response-e2e"],
        },
        projection_status: HEALTH,
      }),
    }),
  );
  await page.route("**/api/ansich/agent-releases?*", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: [
          releaseSummary,
          {
            ...releaseSummary,
            release_id: OTHER_RELEASE_ID,
            release_hash: OTHER_RELEASE_HASH,
            model_hash: "0".repeat(64),
          },
        ],
        operational_distributions: { availability: "unavailable" },
        projection_status: HEALTH,
      }),
    }),
  );
  let rawReleaseManifestRequests = 0;
  await page.route(
    `**/api/ansich/agent-releases/${RELEASE_ID}/manifest`,
    (route) => {
      rawReleaseManifestRequests += 1;
      return route.abort();
    },
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
              {
                block_id: CHILD_OUTPUT_BLOCK_ID,
                kind: "assistant_output",
                content_hash:
                  "9ca1ab1e00000000000000000000000000000000000000000000000000000000",
                byte_size: 24,
                token_estimate: 6,
                sensitivity_flags: [],
                payload_status: "available",
                producer: {
                  producer_kind: "subagent_task",
                  producer_entity_id: CHILD_TASK_ID,
                  producer_obs_id: "33bd27c7-51b1-4164-9380-b98c40c2bfe0",
                },
                depth: 1,
              },
            ],
            edges: [
              {
                derived_block_id: BLOCK_ID,
                source_block_id: CHILD_OUTPUT_BLOCK_ID,
                transform_kind: "visible_result",
                transform_version: "1",
                established_obs_id: "43bd27c7-51b1-4164-9380-b98c40c2bfe0",
              },
            ],
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
    `**/api/ansich/tasks/${TASK_ID}/context-compressions?*`,
    (route) => {
      const cursor = new URL(route.request().url()).searchParams.get("cursor");
      const compressionId =
        cursor === null ? COMPRESSION_ID : OLDER_COMPRESSION_ID;
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          items: [
            {
              compression_id: compressionId,
              task_id: TASK_ID,
              summary_operation_id: "dc695124-12f7-48fd-bc4e-54058924d85a",
              summary_block_id: SUMMARY_BLOCK_ID,
              before_tokens: 120,
              after_tokens: 30,
              before_visible_bytes: 480,
              after_visible_bytes: 120,
              algorithm: "deerflow_summarization_middleware",
              algorithm_version: "1",
              source_obs_id: "23bd27c7-51b1-4164-9380-b98c40c2bfe0",
              occurred_at:
                cursor === null
                  ? "2026-07-17T12:00:04Z"
                  : "2026-07-17T11:00:04Z",
              status: "complete",
            },
          ],
          next_cursor: cursor === null ? "older-compressions" : null,
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
  await expect(
    page.getByText("Healthy", { exact: true }).first(),
  ).toBeVisible();
  await expect(page.getByText("Queue bytes", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: new RegExp(TASK_ID) }).click();

  await page.waitForURL(`**/workspace/ansich/tasks/${TASK_ID}`);
  await expect(page.getByRole("heading", { name: TASK_ID })).toBeVisible();
  await expect(page.getByText("Task tree", { exact: true })).toBeVisible();
  await expect(page.getByText(CHILD_TASK_ID, { exact: true })).toBeVisible();
  await expect(page.getByText("task-control@1", { exact: true })).toBeVisible();
  await page.getByRole("tab", { name: "Budgets" }).click();
  await page.getByRole("button", { name: "Inclusive usage" }).click();
  await expect(page.getByText("160", { exact: true })).toBeVisible();
  await page.getByText("Contribution sources by Task", { exact: true }).click();
  await expect(page.getByText(CHILD_TASK_ID, { exact: true })).toBeVisible();
  await expect(
    page.getByText("total_tokens: 60", { exact: true }),
  ).toBeVisible();
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
  await expect(
    page
      .getByRole("link", { name: `subagent_task:${CHILD_TASK_ID}` })
      .first(),
  ).toHaveAttribute("href", `/workspace/ansich/tasks/${CHILD_TASK_ID}`);
  expect(lineageRequests).toBe(1);
  await expect(
    page.getByRole("button", { name: "Load compression #1" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Load more" }).click();
  await expect(
    page.getByRole("button", { name: "Load compression #2" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Load compression #1" }).click();
  await expect(page.getByText("source", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Load raw payload" }).click();
  await expect(page.getByText('"inspect me"')).toBeVisible();
  await page.getByRole("tab", { name: "Agent release" }).click();
  await expect(
    page.getByText("provider/model-v1", { exact: true }).first(),
  ).toBeVisible();
  await expect(
    page.getByText("Controlled system prompt preview", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText(/Quality: Unassessed/).first()).toBeVisible();
  await page.getByText("builtin:web_search", { exact: true }).click();
  await expect(page.getByText('"query"')).toBeVisible();
  expect(rawReleaseManifestRequests).toBe(0);
});

test("operations keeps terminal Task history separate from running work", async ({
  page,
}) => {
  mockLangGraphAPI(page, { threads: [] });
  await page.route("**/api/ansich/operations/active-tasks?*", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: [],
        next_cursor: null,
        projection_status: HEALTH,
      }),
    }),
  );
  await page.route("**/api/ansich/tasks?*", (route) => {
    const query = new URL(route.request().url()).searchParams;
    expect(query.get("lifecycle_scope")).toBe("terminal");
    expect(query.get("root_only")).toBe("true");
    const cursor = query.get("cursor");
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: cursor === null ? [TASK] : [HISTORY_TASK],
        next_cursor: cursor === null ? "history-page-2" : null,
        projection_status: HEALTH,
      }),
    });
  });
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
      body: JSON.stringify({ items: [], projection_status: HEALTH }),
    }),
  );

  await page.goto("/workspace/ansich/operations");
  await expect(
    page.getByText("No Agent tasks are currently running."),
  ).toBeVisible();
  await expect(page.getByText(TASK_ID)).not.toBeVisible();
  await page.getByRole("tab", { name: "Task history" }).click();
  await expect(page.getByText(TASK_ID)).toBeVisible();
  await expect(page.getByText(HISTORY_TASK_ID)).not.toBeVisible();
  await page.getByRole("button", { name: "Load more" }).click();
  await expect(page.getByText(HISTORY_TASK_ID)).toBeVisible();
  await page.getByRole("link", { name: new RegExp(TASK_ID) }).click();

  await page.waitForURL(`**/workspace/ansich/tasks/${TASK_ID}`);
  await expect(page.getByRole("heading", { name: TASK_ID })).toBeVisible();
});

test("operator inspects alert evidence before confirming workflow and runtime actions", async ({
  page,
}) => {
  mockLangGraphAPI(page, { threads: [] });
  let detailRequests = 0;
  let workflowState = "open";
  let workflowVersion = 1;
  let interruptRequests = 0;
  const alertSummary = () => ({
    alert_id: ALERT_ID,
    subject_id: TASK_ID,
    alert_type: "exact_repetition",
    episode: 1,
    severity: "critical",
    workflow_state: workflowState,
    workflow_version: workflowVersion,
    shadow: false,
    opened_at: "2026-07-17T12:00:03Z",
    as_of: "2026-07-17T12:00:03Z",
    updated_at: "2026-07-17T12:00:03Z",
    resolved_at: null,
    rule: { name: "action-repetition", version: "1.0.0" },
    rule_config_hash:
      "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    stable_condition_key: "exact-repetition",
    source_assertion_id: "assertion-e2e",
    resolution_reason: null,
    dismissal_reason: null,
    evidence_count: 1,
  });
  const sourceBelief = {
    assertion_id: "assertion-e2e",
    subject_id: TASK_ID,
    field_name: "behavior_signal:action-repetition",
    value: { value: "runaway", reason: "exact_repetition" },
    as_of: "2026-07-17T12:00:03Z",
    asserted_at: "2026-07-17T12:00:03Z",
    assessor: { name: "action-repetition", version: "1.0.0" },
    config_hash:
      "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    authority_class: "configured_rule",
    fidelity_class: "rule",
    confidence: null,
    evidence_obs_ids: ["13bd27c7-51b1-4164-9380-b98c40c2bfe0"],
  };
  const behaviorBelief = {
    ...sourceBelief,
    assertion_id: "behavior-e2e",
    field_name: "behavior",
    assessor: { name: "behavior-aggregate", version: "1.0.0" },
    value: { value: "runaway", reason: "runaway_signal_present" },
  };
  await page.route("**/api/ansich/operations/active-tasks?*", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: [ACTIVE_TASK],
        next_cursor: null,
        projection_status: HEALTH,
      }),
    }),
  );
  await page.route("**/api/ansich/operations/alerts?*", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: [alertSummary()],
        next_cursor: null,
        projection_status: HEALTH,
      }),
    }),
  );
  await page.route(`**/api/ansich/operations/alerts/${ALERT_ID}`, (route) => {
    detailRequests += 1;
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        alert: {
          alert: alertSummary(),
          source_belief: sourceBelief,
          evidence: [
            {
              ingest_seq: 3,
              obs_id: "13bd27c7-51b1-4164-9380-b98c40c2bfe0",
              schema_version: 1,
              kind: "tool.issued",
              occurred_at: "2026-07-17T12:00:03Z",
              recorded_at: "2026-07-17T12:00:03Z",
              task_id: TASK_ID,
              step_id: STEP_ID,
              subject_type: "tool_call",
              subject_id: TOOL_CALL_ID,
              fidelity_class: "hard",
              producer: {
                name: "deerflow-tool-observer",
                version: "1",
                instance_id: "e2e",
              },
              producer_seq: 3,
              source_event_id: "tool:e2e:issued",
              correlation_id: TASK_ID,
              causation_obs_id: null,
              payload: { tool_name: "web_search" },
              payload_ref_id: null,
            },
          ],
          current_beliefs: [behaviorBelief],
          workflow_history: [],
          available_actions:
            workflowState === "open"
              ? ["acknowledge", "dismiss", "interrupt", "rollback"]
              : ["dismiss", "interrupt", "rollback"],
        },
        projection_status: HEALTH,
      }),
    });
  });
  await page.route(
    `**/api/ansich/operations/alerts/${ALERT_ID}/acknowledge`,
    async (route) => {
      expect(await route.request().postDataJSON()).toEqual({
        workflow_version: 1,
      });
      workflowState = "acknowledged";
      workflowVersion = 2;
      return route.fulfill({
        status: 409,
        contentType: "application/json",
        body: JSON.stringify({
          detail: {
            message: "Ansich Alert workflow version conflict",
            current_alert: alertSummary(),
          },
        }),
      });
    },
  );
  await page.route(
    `**/api/ansich/tasks/${TASK_ID}/actions/interrupt`,
    (route) => {
      interruptRequests += 1;
      expect(route.request().headers()["idempotency-key"]).toBeTruthy();
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          action: {
            action_id: "action-e2e",
            task_id: TASK_ID,
            action_type: "interrupt",
            idempotency_key: route.request().headers()["idempotency-key"],
            status: "succeeded",
            result: { outcome: "cancelled" },
          },
          audit_status: "degraded",
          idempotent_replay: false,
        }),
      });
    },
  );

  await page.goto("/workspace/ansich/operations");
  await page.getByRole("tab", { name: "Alerts" }).click();
  await expect(page.getByText("Exact action repetition")).toBeVisible();
  await expect(page.getByText("Runaway behavior")).toBeVisible();
  expect(detailRequests).toBe(0);
  await page.getByRole("button", { name: /Exact action repetition/ }).click();
  await expect(page.getByText("Source belief")).toBeVisible();
  await expect(page.getByText("tool.issued", { exact: true })).toBeVisible();
  expect(detailRequests).toBe(1);

  await page.getByRole("button", { name: "Acknowledge" }).click();
  const workflowConfirmation = page.getByRole("dialog").last();
  await workflowConfirmation
    .getByRole("button", { name: "Acknowledge" })
    .click();
  await expect(
    page.getByText("Ansich Alert workflow version conflict"),
  ).toBeVisible();
  await workflowConfirmation.getByRole("button", { name: "Cancel" }).click();
  await expect(page.getByText("tool.issued", { exact: true })).toBeVisible();
  await expect.poll(() => detailRequests).toBeGreaterThan(1);
  await expect(
    page
      .getByRole("dialog", { name: "Alert details" })
      .getByText("Acknowledged", { exact: true }),
  ).toBeVisible();

  await page.getByRole("button", { name: "Interrupt" }).click();
  const runtimeConfirmation = page.getByRole("dialog").last();
  await expect(
    runtimeConfirmation.getByText(
      "Interrupt stops this execution and preserves its current checkpoint. It is not a pause operation.",
    ),
  ).toBeVisible();
  await runtimeConfirmation.getByRole("button", { name: "Interrupt" }).click();
  await expect(
    page.getByText(
      "The operator action completed, but its Ansich audit record is degraded.",
    ),
  ).toBeVisible();
  expect(interruptRequests).toBe(1);
});

test("context tab distinguishes failed projection from no observed context", async ({
  page,
}) => {
  mockLangGraphAPI(page, { threads: [] });
  const degradedHealth = { ...HEALTH, status: "degraded", failed_jobs: 1 };
  await page.route("**/api/ansich/operations/active-tasks?*", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: [ACTIVE_TASK],
        next_cursor: null,
        projection_status: degradedHealth,
      }),
    }),
  );
  await page.route(`**/api/ansich/tasks/${TASK_ID}`, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        task: TASK,
        projection_status: degradedHealth,
      }),
    }),
  );
  await page.route(`**/api/ansich/tasks/${TASK_ID}/timeline`, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: [],
        next_cursor: null,
        projection_status: degradedHealth,
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
            effective_attempt_no: 1,
            effective_context_snapshot_id: null,
            issued_tools: [],
            tool_calls: [],
            attempts: [
              {
                attempt_id: "57d838c5-60d3-4925-a2e7-a8dd35dd40b3",
                task_id: TASK_ID,
                step_id: STEP_ID,
                actor_kind: "lead_agent",
                operation_id: null,
                operation_kind: null,
                attempt_no: 1,
                status: "success",
                request_obs_id: "5f65d20a-f8a0-4ae0-8198-27b4549dc9c9",
                response_obs_id: "366c52fe-5579-469e-b2e5-314b8c0626a6",
                failure_obs_id: null,
                provider_model: "test-model",
                latency_ms: 8,
                context_snapshot_id: null,
                effective: true,
              },
            ],
          },
        ],
        system_operations: [],
        projection_status: degradedHealth,
      }),
    }),
  );

  await page.goto("/workspace/chats/new");
  await page.getByRole("link", { name: "Ansich" }).click();
  await page.getByRole("link", { name: new RegExp(TASK_ID) }).click();
  await page.getByRole("tab", { name: "Context & lineage" }).click();

  await expect(
    page.getByText(
      "Effective context is unavailable because Ansich has failed projection jobs. The request may have been recorded but is not queryable until projection recovery succeeds.",
    ),
  ).toBeVisible();
  await expect(
    page.getByText("No effective model context is available yet."),
  ).toHaveCount(0);
});

test("operations page preserves storage-unavailable detail from a 503", async ({
  page,
}) => {
  mockLangGraphAPI(page, { threads: [] });
  await page.route("**/api/ansich/operations/active-tasks?*", (route) =>
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
