import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type {
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
  AnsichTimelineResponse,
  AnsichHealth,
  AnsichToolCallResponse,
  AnsichToolResultPayloadResponse,
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
): Promise<AnsichTaskListResponse> {
  const query = new URLSearchParams({ limit: String(limit) });
  if (lifecycleScope !== "all") {
    query.set("lifecycle_scope", lifecycleScope);
  }
  if (cursor) {
    query.set("cursor", cursor);
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

export async function fetchAnsichTaskUsage(
  taskId: string,
): Promise<AnsichTaskUsageResponse> {
  const response = await fetch(
    ansichUrl(`/tasks/${encodeURIComponent(taskId)}/usage`),
  );
  if (!response.ok) {
    await throwAnsichApiError(
      response,
      `Failed to load Ansich usage: ${response.statusText}`,
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
