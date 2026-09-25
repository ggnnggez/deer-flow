import type { HealthResponse, ResidencyResponse, TaskListResponse, TaskSort, ThreadTasksResponse } from "./contracts";

/**
 * The extension's own routes, called with the host session. The backend base
 * is where this module was served from: the host loads `assets-v1` modules
 * from `<backend>/api/plugins/<namespace>/assets/…`, so everything before
 * `/api/plugins/` is the backend origin plus any path prefix.
 */
export function backendBaseFromModuleUrl(moduleUrl: string): string {
  const marker = moduleUrl.indexOf("/api/plugins/");
  return marker >= 0 ? moduleUrl.slice(0, marker) : "";
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

async function getJson<T>(url: string, signal: AbortSignal | undefined): Promise<T> {
  const response = await fetch(url, { credentials: "include", signal, headers: { Accept: "application/json" } });
  if (!response.ok) {
    let detail = `${response.status}`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* not JSON */
    }
    throw new ApiError(response.status, detail);
  }
  return (await response.json()) as T;
}

export function fetchTaskResidency(base: string, taskId: string, signal?: AbortSignal): Promise<ResidencyResponse> {
  return getJson(`${base}/api/context-residency/tasks/${encodeURIComponent(taskId)}`, signal);
}

export function fetchThreadTasks(base: string, threadId: string, signal?: AbortSignal): Promise<ThreadTasksResponse> {
  return getJson(`${base}/api/context-residency/threads/${encodeURIComponent(threadId)}/tasks`, signal);
}

export interface TaskListQuery {
  query?: string;
  kind?: "" | "lead" | "subagent";
  outcome?: "" | "running" | "completed" | "failed" | "aborted";
  /** ISO timestamp; only tasks started at or after it. */
  since?: string | null;
  hasCompactions?: boolean;
  incompleteOnly?: boolean;
  sort?: TaskSort;
  direction?: "asc" | "desc";
  limit?: number;
  offset?: number;
}

/** The query string for the task index; empty filters are left out so the server applies its defaults. */
export function taskListSearchParams(query: TaskListQuery): URLSearchParams {
  const params = new URLSearchParams();
  const text = query.query?.trim();
  if (text) params.set("query", text);
  if (query.kind) params.set("kind", query.kind);
  if (query.outcome) params.set("outcome", query.outcome);
  if (query.since) params.set("since", query.since);
  if (query.hasCompactions) params.set("has_compactions", "true");
  if (query.incompleteOnly) params.set("incomplete_only", "true");
  if (query.sort) params.set("sort", query.sort);
  if (query.direction) params.set("direction", query.direction);
  if (query.limit !== undefined) params.set("limit", String(query.limit));
  if (query.offset) params.set("offset", String(query.offset));
  return params;
}

export function fetchTaskList(base: string, query: TaskListQuery, signal?: AbortSignal): Promise<TaskListResponse> {
  const params = taskListSearchParams(query).toString();
  return getJson(`${base}/api/context-residency/tasks${params ? `?${params}` : ""}`, signal);
}

export function fetchHealth(base: string, signal?: AbortSignal): Promise<HealthResponse> {
  return getJson(`${base}/api/context-residency/health`, signal);
}
