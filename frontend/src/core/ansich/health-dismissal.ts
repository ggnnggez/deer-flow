import type { AnsichHealthSnapshot } from "./presentation";

const HEALTH_DISMISSAL_VERSION = 1;
const HEALTH_DISMISSAL_PREFIX = "deerflow:ansich-health-dismissed:v1";

export type AnsichHealthDismissalStorage = Pick<
  Storage,
  "getItem" | "setItem" | "removeItem"
>;

export function getSessionAnsichHealthStorage(): AnsichHealthDismissalStorage | null {
  try {
    if (typeof window === "undefined") {
      return null;
    }
    return window.sessionStorage;
  } catch {
    return null;
  }
}

/**
 * One storage key per health-line scope. The Operations page and each Task page
 * answer different questions, so dismissing one must never silence another.
 */
export function buildAnsichHealthDismissalKey(
  taskId: string | null | undefined,
): string {
  return taskId
    ? `${HEALTH_DISMISSAL_PREFIX}:task:${encodeURIComponent(taskId)}`
    : `${HEALTH_DISMISSAL_PREFIX}:system`;
}

const listeners = new Set<() => void>();

/**
 * A page can mount more than one health line for the same scope (the Task page
 * renders one under the hero and the Evaluations panel renders its own). They
 * subscribe here so a dismissal taken in one is reflected in all of them, since
 * a same-document `sessionStorage` write fires no `storage` event.
 */
export function subscribeAnsichHealthDismissals(
  listener: () => void,
): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function notify(): void {
  for (const listener of listeners) {
    listener();
  }
}

export function readAnsichHealthDismissal(
  storage: AnsichHealthDismissalStorage | null | undefined,
  key: string,
): AnsichHealthSnapshot | null {
  try {
    if (!storage) {
      return null;
    }
    const raw = storage.getItem(key);
    if (!raw) {
      return null;
    }

    const parsed = JSON.parse(raw) as {
      version?: unknown;
      failedJobs?: unknown;
      lostObservations?: unknown;
      status?: unknown;
    };
    if (
      parsed.version !== HEALTH_DISMISSAL_VERSION ||
      typeof parsed.failedJobs !== "number" ||
      typeof parsed.lostObservations !== "number" ||
      (parsed.status !== "healthy" &&
        parsed.status !== "degraded" &&
        parsed.status !== "failed" &&
        parsed.status !== "stopped")
    ) {
      return null;
    }

    return {
      failedJobs: parsed.failedJobs,
      lostObservations: parsed.lostObservations,
      status: parsed.status,
    };
  } catch {
    return null;
  }
}

export function writeAnsichHealthDismissal(
  storage: AnsichHealthDismissalStorage | null | undefined,
  key: string,
  snapshot: AnsichHealthSnapshot,
): void {
  try {
    storage?.setItem(
      key,
      JSON.stringify({ version: HEALTH_DISMISSAL_VERSION, ...snapshot }),
    );
  } catch {
    // A full or blocked sessionStorage only costs the collapsed state.
  }
  notify();
}

export function clearAnsichHealthDismissal(
  storage: AnsichHealthDismissalStorage | null | undefined,
  key: string,
): void {
  try {
    storage?.removeItem(key);
  } catch {
    // Ignore: an unreachable record simply keeps the banner expanded.
  }
  notify();
}
