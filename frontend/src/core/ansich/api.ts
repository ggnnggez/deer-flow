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
  AnsichPossibleExposuresResponse,
  AnsichStepResponse,
  AnsichStepsResponse,
  AnsichTaskListResponse,
  AnsichTaskLifecycleScope,
  AnsichTaskBudgetsResponse,
  AnsichTaskResponse,
  AnsichTaskUsageResponse,
  AnsichTaskAgentReleaseResponse,
  AnsichTimelineResponse,
  AnsichHealth,
  AnsichToolCallResponse,
  AnsichToolResultPayloadResponse,
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
): Promise<AnsichAgentReleaseComparisonResponse> {
  const query = new URLSearchParams({
    left: leftReleaseId,
    right: rightReleaseId,
  });
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
