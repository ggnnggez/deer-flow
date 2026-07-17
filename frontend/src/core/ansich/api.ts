import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type {
  AnsichTaskListResponse,
  AnsichTaskResponse,
  AnsichTimelineResponse,
  AnsichHealth,
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
): Promise<AnsichTaskListResponse> {
  const response = await fetch(ansichUrl(`/tasks?limit=${limit}`));
  if (!response.ok) {
    await throwAnsichApiError(
      response,
      `Failed to load Ansich tasks: ${response.statusText}`,
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
