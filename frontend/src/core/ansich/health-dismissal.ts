import type { AnsichHealthSnapshot, AnsichHealthStatus } from "./presentation";
import { ANSICH_HEALTH_STATUSES } from "./types";

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

/**
 * Whether a persisted record's status is one the Collector can actually report.
 * It reads the contract's own list rather than restating the values here: a
 * second literal list drifts, and this one already did — a record dismissed at
 * `recovering` failed validation and re-promoted its banner once the lifecycle
 * states landed.
 */
function isHealthStatus(value: unknown): value is AnsichHealthStatus {
  return (
    typeof value === "string" &&
    (ANSICH_HEALTH_STATUSES as readonly string[]).includes(value)
  );
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
      // `null` is a recorded unknown and must survive the round trip as one.
      !(typeof parsed.failedJobs === "number" || parsed.failedJobs === null) ||
      typeof parsed.lostObservations !== "number" ||
      !isHealthStatus(parsed.status)
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
