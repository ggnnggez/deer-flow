import type {
  AnsichAlertType,
  AnsichLostRange,
  AnsichQualityBelief,
} from "./types";

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
    case "attempted_scope_violation":
    case "realized_scope_violation":
    case "unverified_effect":
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

/**
 * Shorten a UUID/hash to its leading segment for L1 display. The full value
 * stays reachable via Copy / Technical details (IA §4.2 "downgrade, not delete").
 */
export function shortId(id: string, length = 8): string {
  if (id.length <= length) return id;
  return id.slice(0, length);
}

export type AnsichSignalSeverity = "critical" | "warning" | "info" | "none";

export type AnsichPrimarySignalKind =
  | "behavior"
  | "budget"
  | "scope"
  | "heartbeat"
  | "observability"
  | "healthy";

export interface AnsichPrimarySignal {
  severity: AnsichSignalSeverity;
  kind: AnsichPrimarySignalKind;
}

export interface PrimarySignalInputs {
  behaviorState?: "runaway" | "normal" | "unknown" | null;
  budgetHealth?: ReadonlyArray<{
    value: "unknown" | "within" | "warning" | "exceeded";
  }>;
  scopeSafety?: { realizedViolation?: boolean; attemptedViolation?: boolean };
  heartbeat?: "unknown" | "fresh" | "stale" | null;
  observability?: "healthy" | "degraded";
}

/**
 * Select the single primary signal to surface for a Task, by a fixed priority
 * over signals that the backend has already resolved (IA §5.3). This is a
 * presentation selection, NOT a new authority rule: it never invents severity,
 * only ranks existing typed beliefs/health. UI-2 replaces it with a versioned
 * backend resolver. Returns null when no usable evidence exists — the caller
 * must render "Insufficient evidence", never a green healthy placeholder
 * (IA §6.2 / §7.3).
 */
export function selectPrimarySignal(
  inputs: PrimarySignalInputs,
): AnsichPrimarySignal | null {
  const budgets = inputs.budgetHealth ?? [];
  const hasExceeded = budgets.some((item) => item.value === "exceeded");
  const hasWarning = budgets.some((item) => item.value === "warning");

  if (inputs.behaviorState === "runaway") {
    return { severity: "critical", kind: "behavior" };
  }
  if (hasExceeded) return { severity: "critical", kind: "budget" };
  if (inputs.scopeSafety?.realizedViolation) {
    return { severity: "critical", kind: "scope" };
  }
  if (inputs.scopeSafety?.attemptedViolation) {
    return { severity: "warning", kind: "scope" };
  }
  if (inputs.heartbeat === "stale") {
    return { severity: "warning", kind: "heartbeat" };
  }
  if (inputs.observability === "degraded") {
    return { severity: "warning", kind: "observability" };
  }
  if (hasWarning) return { severity: "warning", kind: "budget" };

  // Healthy requires positive evidence; unknown/missing is not healthy.
  const positiveEvidence =
    budgets.some((item) => item.value === "within") ||
    inputs.heartbeat === "fresh" ||
    inputs.observability === "healthy";
  if (positiveEvidence) return { severity: "none", kind: "healthy" };
  return null;
}

/**
 * Whether projection health warrants a page-level banner rather than a compact
 * status line (IA §5.2): non-healthy status, any failed job, any lost range, or
 * storage unavailable. A healthy line must never hide these.
 */
export function isProjectionAttention(health: {
  status: "healthy" | "degraded" | "failed" | "stopped";
  failed_jobs: number;
  lost_ranges: unknown[];
  storage_available: boolean;
}): boolean {
  return (
    health.status !== "healthy" ||
    health.failed_jobs > 0 ||
    health.lost_ranges.length > 0 ||
    !health.storage_available
  );
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

/**
 * Render one evaluation's outcome. A recorded verdict is the assessor's own
 * word and always wins; a score renders against its scale maximum only when the
 * whole scale is known, because a bare number out of an unknown range is not a
 * comparable fact. An evaluation with neither renders as an explicit dash — it
 * is never summarized into a pass.
 */
export function formatEvaluationVerdict(
  verdict: string | null,
  score: number | null,
  scaleMin: number | null,
  scaleMax: number | null,
): string {
  if (verdict) return verdict;
  if (score === null) return "—";
  if (scaleMin === null || scaleMax === null) return String(score);
  return `${score} / ${scaleMax}`;
}

/** The i18n key naming one evaluation dimension. */
export type AnsichDimensionLabelKey =
  | "dimensionCorrectness"
  | "dimensionCompleteness"
  | "dimensionRelevance"
  | "dimensionSafety"
  | "dimensionEfficiency"
  | "dimensionEarliestErroneousStep"
  | "dimensionCustom";

const DIMENSION_LABEL_KEYS: Record<string, AnsichDimensionLabelKey> = {
  correctness: "dimensionCorrectness",
  completeness: "dimensionCompleteness",
  relevance: "dimensionRelevance",
  safety: "dimensionSafety",
  efficiency: "dimensionEfficiency",
  earliest_erroneous_step: "dimensionEarliestErroneousStep",
};

/**
 * Name one evaluation dimension for display. The contract's dimension set is
 * open, so an unrecognized dimension is labeled as custom and rendered beside
 * its raw key rather than being hidden or silently mapped onto a known one.
 */
export function evaluationDimensionLabelKey(
  dimension: string,
): AnsichDimensionLabelKey {
  return DIMENSION_LABEL_KEYS[dimension] ?? "dimensionCustom";
}

export type AnsichQualityBeliefTone =
  | "pass"
  | "fail"
  | "partial"
  | "unassessed"
  | "unknown";

/**
 * Classify one quality Belief for display. The backend's `unassessed` flag is
 * checked before any value inspection, so a dimension nothing assessed can
 * never be dressed up as a verdict. A value without a recognized verdict is
 * `unknown`, never a pass: absence of evidence is not evidence of success
 * (IA §6.2 / §7.3).
 */
export function qualityBeliefTone(
  belief: AnsichQualityBelief,
): AnsichQualityBeliefTone {
  if (belief.unassessed) return "unassessed";
  const verdict = belief.value.verdict;
  if (verdict === "pass" || verdict === "fail" || verdict === "partial") {
    return verdict;
  }
  return "unknown";
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
