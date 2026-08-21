import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type {
  AnsichAlertDetailResponse,
  AnsichAlertListResponse,
  AnsichAlertType,
  AnsichAlertWorkflowResponse,
  AnsichAlertWorkflowState,
  AnsichAgentReleaseComparisonResponse,
  AnsichAgentReleaseListResponse,
  AnsichContentPayloadResponse,
  AnsichActiveTaskListResponse,
  AnsichContentLineageResponse,
  AnsichContextCompressionResponse,
  AnsichContextCompressionListResponse,
  AnsichContextResponse,
  AnsichEnvironmentHistoryResponse,
  AnsichEvaluationPayloadResponse,
  AnsichFailedJobDetailResponse,
  AnsichFailedJobKind,
  AnsichFailedJobsResponse,
  AnsichFailedJobsRetryResponse,
  AnsichPossibleExposuresResponse,
  AnsichReleaseQualityResponse,
  AnsichStepEvaluationsResponse,
  AnsichStepResponse,
  AnsichStepsResponse,
  AnsichTaskEvaluationsResponse,
  AnsichTaskListResponse,
  AnsichTaskLifecycleScope,
  AnsichTaskBudgetsResponse,
  AnsichTaskEnvironmentResponse,
  AnsichTaskToolEnvSamplesResponse,
  AnsichTaskResponse,
  AnsichTaskUsageResponse,
  AnsichTaskAgentReleaseResponse,
  AnsichTimelineResponse,
  AnsichHealth,
  AnsichHealthResponse,
  AnsichToolCallResponse,
  AnsichToolResultPayloadResponse,
  AnsichTaskScopesResponse,
  AnsichToolAuthorizationResponse,
  AnsichToolEffectsResponse,
  AnsichOperatorActionResponse,
  AnsichTaskChildrenResponse,
  AnsichTaskTreeResponse,
} from "./types";

export class AnsichApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly projectionStatus: Partial<AnsichHealth> | null = null,
  ) {
    super(message);
    this.name = "AnsichApiError";
  }
}

async function throwAnsichApiError(
  response: Response,
  fallback: string,
): Promise<never> {
  const body = (await response.json().catch(() => ({}))) as {
    detail?: unknown;
  };
  if (typeof body.detail === "string") {
    throw new AnsichApiError(body.detail, response.status);
  }
  if (typeof body.detail === "object" && body.detail !== null) {
    const detail = body.detail as {
      message?: unknown;
      projection_status?: unknown;
    };
    throw new AnsichApiError(
      typeof detail.message === "string" ? detail.message : fallback,
      response.status,
      typeof detail.projection_status === "object" &&
        detail.projection_status !== null
        ? (detail.projection_status as Partial<AnsichHealth>)
        : null,
    );
  }
  throw new AnsichApiError(fallback, response.status);
}

function ansichUrl(path: string): string {
  return `${getBackendBaseURL()}/api/ansich${path}`;
}

export async function fetchAnsichTasks(
  limit = 100,
  lifecycleScope: AnsichTaskLifecycleScope = "all",
  cursor?: string,
  rootOnly = false,
): Promise<AnsichTaskListResponse> {
  const query = new URLSearchParams({ limit: String(limit) });
  if (lifecycleScope !== "all") {
    query.set("lifecycle_scope", lifecycleScope);
  }
  if (cursor) {
    query.set("cursor", cursor);
  }
  if (rootOnly) {
    query.set("root_only", "true");
  }
  const response = await fetch(ansichUrl(`/tasks?${query.toString()}`));
  if (!response.ok) {
    await throwAnsichApiError(
      response,
      `Failed to load Ansich tasks: ${response.statusText}`,
    );
  }
  return response.json();
}

export async function fetchAnsichActiveTasks(
  limit = 100,
): Promise<AnsichActiveTaskListResponse> {
  const response = await fetch(
    ansichUrl(`/operations/active-tasks?limit=${limit}`),
  );
  if (!response.ok) {
    await throwAnsichApiError(
      response,
      `Failed to load active Ansich tasks: ${response.statusText}`,
    );
  }
  return response.json();
}

export async function fetchAnsichAgentReleases(
  limit = 100,
): Promise<AnsichAgentReleaseListResponse> {
  const response = await fetch(ansichUrl(`/agent-releases?limit=${limit}`));
  if (!response.ok) {
    await throwAnsichApiError(
      response,
      `Failed to load Ansich Agent releases: ${response.statusText}`,
    );
  }
  return response.json();
}

export async function fetchAnsichTaskAgentRelease(
  taskId: string,
): Promise<AnsichTaskAgentReleaseResponse> {
  const response = await fetch(
    ansichUrl(`/tasks/${encodeURIComponent(taskId)}/agent-release`),
  );
  if (!response.ok) {
    await throwAnsichApiError(
      response,
      `Failed to load Ansich Task Agent release: ${response.statusText}`,
    );
  }
  return response.json();
}

export async function compareAnsichAgentReleases(
  leftReleaseId: string,
  rightReleaseId: string,
  cohort?: string,
): Promise<AnsichAgentReleaseComparisonResponse> {
  const query = new URLSearchParams({
    left: leftReleaseId,
    right: rightReleaseId,
  });
  // An empty cohort is the explicit "declared no cohort" bucket, so only an
  // omitted argument means "every cohort".
  if (cohort !== undefined) {
    query.set("cohort", cohort);
  }
  const response = await fetch(
    ansichUrl(`/agent-releases/compare?${query.toString()}`),
  );
  if (!response.ok) {
    await throwAnsichApiError(
      response,
      `Failed to compare Ansich Agent releases: ${response.statusText}`,
    );
  }
  return response.json();
}

export async function fetchAnsichReleaseQuality(
  releaseId: string,
  cohort?: string,
): Promise<AnsichReleaseQualityResponse> {
  const query = new URLSearchParams();
  // `""` is the no-cohort aggregation sentinel and is a real filter; only an
  // omitted argument asks for every cohort.
  if (cohort !== undefined) {
    query.set("cohort", cohort);
  }
  const suffix = query.toString() ? `?${query.toString()}` : "";
  const response = await fetch(
    ansichUrl(
      `/agent-releases/${encodeURIComponent(releaseId)}/quality${suffix}`,
    ),
  );
  if (!response.ok) {
    await throwAnsichApiError(
      response,
      `Failed to load Ansich Agent release quality: ${response.statusText}`,
    );
  }
  return response.json();
}

export interface AnsichAlertFilters {
  alertType?: AnsichAlertType;
  workflowState?: AnsichAlertWorkflowState;
  taskId?: string;
  severity?: "info" | "warning" | "critical";
  shadow?: boolean;
  cursor?: string;
}

export async function fetchAnsichAlerts(
  limit = 100,
  filters: AnsichAlertFilters = {},
): Promise<AnsichAlertListResponse> {
  const query = new URLSearchParams({ limit: String(limit) });
  if (filters.alertType) query.set("type", filters.alertType);
  if (filters.workflowState) query.set("state", filters.workflowState);
  if (filters.taskId) query.set("task", filters.taskId);
  if (filters.severity) query.set("severity", filters.severity);
  if (filters.shadow !== undefined) {
    query.set("shadow", String(filters.shadow));
  }
  if (filters.cursor) query.set("cursor", filters.cursor);
  const response = await fetch(
    ansichUrl(`/operations/alerts?${query.toString()}`),
  );
  if (!response.ok) {
    await throwAnsichApiError(
      response,
      `Failed to load Ansich alerts: ${response.statusText}`,
    );
  }
  return response.json();
}

export async function fetchAnsichAlert(
  alertId: string,
): Promise<AnsichAlertDetailResponse> {
  const response = await fetch(
    ansichUrl(`/operations/alerts/${encodeURIComponent(alertId)}`),
  );
  if (!response.ok) {
    await throwAnsichApiError(
      response,
      `Failed to load Ansich alert: ${response.statusText}`,
    );
  }
  return response.json();
}

async function changeAnsichAlertWorkflow(
  alertId: string,
  action: "acknowledge" | "dismiss",
  workflowVersion: number,
  reason?: string,
): Promise<AnsichAlertWorkflowResponse> {
  const body =
    action === "dismiss"
      ? { workflow_version: workflowVersion, reason }
      : { workflow_version: workflowVersion };
  const response = await fetch(
    ansichUrl(`/operations/alerts/${encodeURIComponent(alertId)}/${action}`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
  if (!response.ok) {
    await throwAnsichApiError(
      response,
      `Failed to ${action} Ansich alert: ${response.statusText}`,
    );
  }
  return response.json();
}

export async function acknowledgeAnsichAlert(
  alertId: string,
  workflowVersion: number,
): Promise<AnsichAlertWorkflowResponse> {
  return changeAnsichAlertWorkflow(alertId, "acknowledge", workflowVersion);
}

export async function dismissAnsichAlert(
  alertId: string,
  workflowVersion: number,
  reason: string,
): Promise<AnsichAlertWorkflowResponse> {
  return changeAnsichAlertWorkflow(alertId, "dismiss", workflowVersion, reason);
}

/**
 * The one Ansich read that answers while SQL storage is down: process health,
 * plus the additive `database` block whose own `status` says whether the
 * storage half could be read at all. Every other projection read 503s in that
 * situation, which is why this endpoint gets its own query rather than reusing
 * a `projection_status` carried on some other response.
 */
export async function fetchAnsichHealth(): Promise<AnsichHealthResponse> {
  const response = await fetch(ansichUrl("/health"));
  if (!response.ok) {
    await throwAnsichApiError(
      response,
      `Failed to load Ansich health: ${response.statusText}`,
    );
  }
  return response.json();
}

export async function fetchAnsichFailedJobs(
  taskId?: string,
  limit = 100,
): Promise<AnsichFailedJobsResponse> {
  const query = new URLSearchParams({ limit: String(limit) });
  if (taskId) query.set("task", taskId);
  const response = await fetch(
    ansichUrl(`/operations/failed-jobs?${query.toString()}`),
  );
  if (!response.ok) {
    await throwAnsichApiError(
      response,
      `Failed to load Ansich failed jobs: ${response.statusText}`,
    );
  }
  return response.json();
}

export async function fetchAnsichFailedJobDetail(
  jobId: string,
  kind: AnsichFailedJobKind,
): Promise<AnsichFailedJobDetailResponse> {
  const query = new URLSearchParams({ kind });
  const response = await fetch(
    ansichUrl(
      `/operations/failed-jobs/${encodeURIComponent(jobId)}?${query.toString()}`,
    ),
  );
  if (!response.ok) {
    await throwAnsichApiError(
      response,
      `Failed to load Ansich failed job detail: ${response.statusText}`,
    );
  }
  return response.json();
}

export async function retryAnsichFailedJobs(
  taskId?: string,
): Promise<AnsichFailedJobsRetryResponse> {
  const query = new URLSearchParams();
  if (taskId) query.set("task", taskId);
  const suffix = query.toString() ? `?${query.toString()}` : "";
  const response = await fetch(
    ansichUrl(`/operations/failed-jobs/retry${suffix}`),
    {
      method: "POST",
    },
  );
  if (!response.ok) {
    await throwAnsichApiError(
      response,
      `Failed to retry Ansich failed jobs: ${response.statusText}`,
    );
  }
  return response.json();
}

export async function executeAnsichTaskAction(
  taskId: string,
  action: "interrupt" | "rollback",
  idempotencyKey: string,
): Promise<AnsichOperatorActionResponse> {
  const response = await fetch(
    ansichUrl(`/tasks/${encodeURIComponent(taskId)}/actions/${action}`),
    {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
    },
  );
  if (!response.ok) {
    await throwAnsichApiError(
      response,
      `Failed to ${action} Ansich task: ${response.statusText}`,
    );
  }
  return response.json();
}

export async function fetchAnsichTaskUsage(
  taskId: string,
  scope: "local" | "inclusive" = "local",
): Promise<AnsichTaskUsageResponse> {
  const query = new URLSearchParams({ scope });
  const response = await fetch(
    ansichUrl(`/tasks/${encodeURIComponent(taskId)}/usage?${query.toString()}`),
  );
  if (!response.ok) {
    await throwAnsichApiError(
      response,
      `Failed to load Ansich usage: ${response.statusText}`,
    );
  }
  return response.json();
}

export async function fetchAnsichTaskChildren(
  taskId: string,
): Promise<AnsichTaskChildrenResponse> {
  const response = await fetch(
    ansichUrl(`/tasks/${encodeURIComponent(taskId)}/children`),
  );
  if (!response.ok) {
    await throwAnsichApiError(
      response,
      `Failed to load child Ansich tasks: ${response.statusText}`,
    );
  }
  return response.json();
}

export async function fetchAnsichTaskTree(
  taskId: string,
  direction: "ancestors" | "descendants" | "both" = "both",
  depth = 4,
): Promise<AnsichTaskTreeResponse> {
  const query = new URLSearchParams({ direction, depth: String(depth) });
  const response = await fetch(
    ansichUrl(`/tasks/${encodeURIComponent(taskId)}/tree?${query.toString()}`),
  );
  if (!response.ok) {
    await throwAnsichApiError(
      response,
      `Failed to load Ansich task tree: ${response.statusText}`,
    );
  }
  return response.json();
}

export async function fetchAnsichTaskBudgets(
  taskId: string,
): Promise<AnsichTaskBudgetsResponse> {
  const response = await fetch(
    ansichUrl(`/tasks/${encodeURIComponent(taskId)}/budgets`),
  );
  if (!response.ok) {
    await throwAnsichApiError(
      response,
      `Failed to load Ansich budgets: ${response.statusText}`,
    );
  }
  return response.json();
}

export async function fetchAnsichTaskEnvironment(
  taskId: string,
): Promise<AnsichTaskEnvironmentResponse> {
  const response = await fetch(
    ansichUrl(`/tasks/${encodeURIComponent(taskId)}/environment`),
  );
  if (!response.ok) {
    await throwAnsichApiError(
      response,
      `Failed to load Ansich task environment: ${response.statusText}`,
    );
  }
  return response.json();
}

export async function fetchAnsichEnvironmentHistory(
  scopeId: string,
  environmentScope: string,
  metric: string,
  windowMinutes = 60,
): Promise<AnsichEnvironmentHistoryResponse> {
  const query = new URLSearchParams({
    environment_scope: environmentScope,
    metric,
    window_minutes: String(windowMinutes),
  });
  const response = await fetch(
    ansichUrl(
      `/scopes/${encodeURIComponent(scopeId)}/environment/history?${query.toString()}`,
    ),
  );
  if (!response.ok) {
    await throwAnsichApiError(
      response,
      `Failed to load Ansich environment history: ${response.statusText}`,
    );
  }
  return response.json();
}

export async function fetchAnsichTaskToolEnvSamples(
  taskId: string,
): Promise<AnsichTaskToolEnvSamplesResponse> {
  const response = await fetch(
    ansichUrl(`/tasks/${encodeURIComponent(taskId)}/environment/tool-samples`),
  );
  if (!response.ok) {
    await throwAnsichApiError(
      response,
      `Failed to load Ansich per-command environment samples: ${response.statusText}`,
    );
  }
  return response.json();
}

export async function fetchAnsichTask(
  taskId: string,
): Promise<AnsichTaskResponse> {
  const response = await fetch(
    ansichUrl(`/tasks/${encodeURIComponent(taskId)}`),
  );
  if (!response.ok) {
    await throwAnsichApiError(
      response,
      `Failed to load Ansich task: ${response.statusText}`,
    );
  }
  return response.json();
}

export async function fetchAnsichTaskTimeline(
  taskId: string,
): Promise<AnsichTimelineResponse> {
  const response = await fetch(
    ansichUrl(`/tasks/${encodeURIComponent(taskId)}/timeline`),
  );
  if (!response.ok) {
    await throwAnsichApiError(
      response,
      `Failed to load Ansich task timeline: ${response.statusText}`,
    );
  }
  return response.json();
}

export async function fetchAnsichTaskSteps(
  taskId: string,
): Promise<AnsichStepsResponse> {
  const response = await fetch(
    ansichUrl(`/tasks/${encodeURIComponent(taskId)}/steps`),
  );
  if (!response.ok) {
    await throwAnsichApiError(
      response,
      `Failed to load Ansich steps: ${response.statusText}`,
    );
  }
  return response.json();
}

export async function fetchAnsichTaskEvaluations(
  taskId: string,
): Promise<AnsichTaskEvaluationsResponse> {
  const response = await fetch(
    ansichUrl(`/tasks/${encodeURIComponent(taskId)}/evaluations`),
  );
  if (!response.ok) {
    await throwAnsichApiError(
      response,
      `Failed to load Ansich Task evaluations: ${response.statusText}`,
    );
  }
  return response.json();
}

/**
 * Read one evaluation's `expected`/`actual`/`rationale` bodies. Same rule as
 * the raw Tool payloads: fetched only after an explicit admin action, never
 * placed in a polling response or prefetched into a query cache.
 */
export async function fetchAnsichEvaluationPayload(
  obsId: string,
): Promise<AnsichEvaluationPayloadResponse> {
  const response = await fetch(
    ansichUrl(`/evaluations/${encodeURIComponent(obsId)}/payload`),
    { cache: "no-store" },
  );
  if (!response.ok) {
    await throwAnsichApiError(
      response,
      `Failed to load Ansich evaluation payload: ${response.statusText}`,
    );
  }
  return response.json();
}

export async function fetchAnsichStep(
  stepId: string,
): Promise<AnsichStepResponse> {
  const response = await fetch(
    ansichUrl(`/steps/${encodeURIComponent(stepId)}`),
  );
  if (!response.ok) {
    await throwAnsichApiError(
      response,
      `Failed to load Ansich step: ${response.statusText}`,
    );
  }
  return response.json();
}

export async function fetchAnsichStepContext(
  stepId: string,
): Promise<AnsichContextResponse> {
  const response = await fetch(
    ansichUrl(`/steps/${encodeURIComponent(stepId)}/context`),
  );
  if (!response.ok) {
    await throwAnsichApiError(
      response,
      `Failed to load Ansich context: ${response.statusText}`,
    );
  }
  return response.json();
}

export async function fetchAnsichStepEvaluations(
  stepId: string,
): Promise<AnsichStepEvaluationsResponse> {
  const response = await fetch(
    ansichUrl(`/steps/${encodeURIComponent(stepId)}/evaluations`),
  );
  if (!response.ok) {
    await throwAnsichApiError(
      response,
      `Failed to load Ansich Step evaluations: ${response.statusText}`,
    );
  }
  return response.json();
}

export async function fetchAnsichContentPayload(
  blockId: string,
): Promise<AnsichContentPayloadResponse> {
  const response = await fetch(
    ansichUrl(`/content-blocks/${encodeURIComponent(blockId)}/payload`),
  );
  if (!response.ok) {
    await throwAnsichApiError(
      response,
      `Failed to load Ansich raw payload: ${response.statusText}`,
    );
  }
  return response.json();
}

export async function fetchAnsichContentLineage(
  blockId: string,
  direction: "backward" | "forward" = "backward",
  depth = 8,
  nodes = 500,
): Promise<AnsichContentLineageResponse> {
  const response = await fetch(
    ansichUrl(
      `/content-blocks/${encodeURIComponent(blockId)}/lineage?direction=${direction}&depth=${depth}&nodes=${nodes}`,
    ),
  );
  if (!response.ok) {
    await throwAnsichApiError(
      response,
      `Failed to load Ansich content lineage: ${response.statusText}`,
    );
  }
  return response.json();
}

export async function fetchAnsichContentExposures(
  blockId: string,
  depth = 8,
  nodes = 500,
): Promise<AnsichPossibleExposuresResponse> {
  const response = await fetch(
    ansichUrl(
      `/content-blocks/${encodeURIComponent(blockId)}/exposures?depth=${depth}&nodes=${nodes}`,
    ),
  );
  if (!response.ok) {
    await throwAnsichApiError(
      response,
      `Failed to load Ansich possible exposures: ${response.statusText}`,
    );
  }
  return response.json();
}

export async function fetchAnsichContextSnapshot(
  snapshotId: string,
): Promise<AnsichContextResponse> {
  const response = await fetch(
    ansichUrl(`/context-snapshots/${encodeURIComponent(snapshotId)}`),
  );
  if (!response.ok) {
    await throwAnsichApiError(
      response,
      `Failed to load Ansich ContextSnapshot: ${response.statusText}`,
    );
  }
  return response.json();
}

export async function fetchAnsichContextCompression(
  compressionId: string,
): Promise<AnsichContextCompressionResponse> {
  const response = await fetch(
    ansichUrl(`/context-compressions/${encodeURIComponent(compressionId)}`),
  );
  if (!response.ok) {
    await throwAnsichApiError(
      response,
      `Failed to load Ansich ContextCompression: ${response.statusText}`,
    );
  }
  return response.json();
}

export async function fetchAnsichTaskCompressions(
  taskId: string,
  limit = 100,
  cursor?: string,
): Promise<AnsichContextCompressionListResponse> {
  const query = new URLSearchParams({ limit: String(limit) });
  if (cursor) {
    query.set("cursor", cursor);
  }
  const response = await fetch(
    ansichUrl(
      `/tasks/${encodeURIComponent(taskId)}/context-compressions?${query.toString()}`,
    ),
  );
  if (!response.ok) {
    await throwAnsichApiError(
      response,
      `Failed to load Ansich ContextCompressions: ${response.statusText}`,
    );
  }
  return response.json();
}

export async function fetchAnsichToolCall(
  toolCallId: string,
): Promise<AnsichToolCallResponse> {
  const response = await fetch(
    ansichUrl(`/tool-calls/${encodeURIComponent(toolCallId)}`),
  );
  if (!response.ok) {
    await throwAnsichApiError(
      response,
      `Failed to load Ansich ToolCall: ${response.statusText}`,
    );
  }
  return response.json();
}

export async function fetchAnsichTaskScopes(
  taskId: string,
): Promise<AnsichTaskScopesResponse> {
  const response = await fetch(
    ansichUrl(`/tasks/${encodeURIComponent(taskId)}/scopes`),
  );
  if (!response.ok) {
    await throwAnsichApiError(
      response,
      `Failed to load Ansich Scopes: ${response.statusText}`,
    );
  }
  return response.json();
}

export async function fetchAnsichToolAuthorization(
  toolCallId: string,
): Promise<AnsichToolAuthorizationResponse> {
  const response = await fetch(
    ansichUrl(`/tool-calls/${encodeURIComponent(toolCallId)}/authorization`),
  );
  if (!response.ok) {
    await throwAnsichApiError(
      response,
      `Failed to load Ansich authorization: ${response.statusText}`,
    );
  }
  return response.json();
}

export async function fetchAnsichToolEffects(
  toolCallId: string,
): Promise<AnsichToolEffectsResponse> {
  const response = await fetch(
    ansichUrl(`/tool-calls/${encodeURIComponent(toolCallId)}/effects`),
  );
  if (!response.ok) {
    await throwAnsichApiError(
      response,
      `Failed to load Ansich effects: ${response.statusText}`,
    );
  }
  return response.json();
}

export async function fetchAnsichToolRawResult(
  toolCallId: string,
): Promise<AnsichToolResultPayloadResponse> {
  const response = await fetch(
    ansichUrl(`/tool-calls/${encodeURIComponent(toolCallId)}/raw-result`),
    { cache: "no-store" },
  );
  if (!response.ok) {
    await throwAnsichApiError(
      response,
      `Failed to load Ansich raw tool result: ${response.statusText}`,
    );
  }
  return response.json();
}

export async function fetchAnsichToolVisibleResult(
  toolCallId: string,
): Promise<AnsichToolResultPayloadResponse> {
  const response = await fetch(
    ansichUrl(`/tool-calls/${encodeURIComponent(toolCallId)}/visible-result`),
    { cache: "no-store" },
  );
  if (!response.ok) {
    await throwAnsichApiError(
      response,
      `Failed to load Ansich visible tool result: ${response.statusText}`,
    );
  }
  return response.json();
}
