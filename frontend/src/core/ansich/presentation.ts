import type { AnsichAlertType, AnsichLostRange } from "./types";

export type AnsichAlertPresentationCategory =
  | "runaway"
  | "operational"
  | "liveness";

export function getAlertPresentationCategory(
  alertType: AnsichAlertType,
): AnsichAlertPresentationCategory {
  switch (alertType) {
    case "budget_warning":
    case "budget_exceeded":
    case "exact_repetition":
      return "runaway";
    case "tool_frequency":
    case "long_dwell":
    case "configuration_drift":
      return "operational";
    case "heartbeat_missing":
      return "liveness";
  }
}

export interface BudgetPresentation {
  status: "unconfigured" | "unknown" | "within" | "warning" | "exceeded";
  percent: number | null;
  overshoot: number | null;
}

export function getBudgetPresentation(
  budget: { hard_limit: number | null } | undefined,
  health:
    | {
        value: "unknown" | "within" | "warning" | "exceeded";
        usage_value: number | null;
        overshoot: number | null;
      }
    | undefined,
): BudgetPresentation {
  const hardLimit = budget?.hard_limit;
  if (hardLimit === undefined || hardLimit === null) {
    return { status: "unconfigured", percent: null, overshoot: null };
  }
  if (!health || health.value === "unknown" || health.usage_value === null) {
    return { status: "unknown", percent: null, overshoot: null };
  }
  const percent =
    hardLimit === 0
      ? health.usage_value > 0
        ? 100
        : 0
      : Math.round((health.usage_value / hardLimit) * 100);
  return {
    status: health.value,
    percent,
    overshoot: health.overshoot,
  };
}

export function formatDuration(milliseconds: number | null): string {
  if (milliseconds === null) return "—";
  const seconds = Math.floor(milliseconds / 1_000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ${seconds % 60}s`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m`;
}

export function countMissingContextItems(
  items: Array<{ resolution_status: "available" | "missing" }>,
): number {
  return items.filter((item) => item.resolution_status === "missing").length;
}

export function countLostObservations(ranges: AnsichLostRange[]): number {
  return ranges.reduce(
    (total, range) =>
      total + Math.max(0, range.last_sequence - range.first_sequence + 1),
    0,
  );
}

export function formatAnsichTimestamp(
  value: string | null,
  locale: string,
): string {
  if (!value) {
    return "—";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat(locale === "zh-CN" ? "zh-CN" : "en-US", {
    dateStyle: "medium",
    timeStyle: "medium",
  }).format(date);
}
