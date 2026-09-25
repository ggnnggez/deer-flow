import type { ResidencyResponse, ThreadTasksResponse } from "./contracts";

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
