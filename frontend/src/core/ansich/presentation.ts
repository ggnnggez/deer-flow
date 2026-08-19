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

export type AnsichHealthStatus = "healthy" | "degraded" | "failed" | "stopped";

/** The projection-health fields the scope helpers below actually read. */
export interface AnsichProjectionHealthFacts {
  status: AnsichHealthStatus;
  failed_jobs: number;
  lost_ranges: AnsichLostRange[];
  storage_available: boolean;
}

/**
 * A projection failure no page can see past: storage is unavailable, or the
 * projector itself failed/stopped. A Task-scoped view must surface this even
 * when the Task's own numbers look clean, because those numbers come from the
 * same projection — claiming the Task is fine would be fabricating certainty.
 */
export function isProjectionHardFailure(health: {
  status: AnsichHealthStatus;
  storage_available: boolean;
}): boolean {
  return (
    !health.storage_available ||
    health.status === "failed" ||
    health.status === "stopped"
  );
}

/**
 * The lost ranges attributable to one Task. A range with `task_id: null` is
 * unattributed loss and belongs to the system scope only: counting it against a
 * Task would invent an attribution the projection never recorded.
 */
export function lostRangesForTask(
  ranges: AnsichLostRange[],
  taskId: string,
): AnsichLostRange[] {
  return ranges.filter((range) => range.task_id === taskId);
}

/**
 * The state a dismissal was taken against, and the unit of "got worse".
 *
 * `failedJobs` is `null` when the projection could not answer how many jobs
 * failed. That is not zero, and it is never compared as if it were.
 */
export interface AnsichHealthSnapshot {
  failedJobs: number | null;
  lostObservations: number;
  status: AnsichHealthStatus;
}

/**
 * How many failed jobs a Task has, from its failed-job query result, or `null`
 * when the request has not answered. TanStack leaves `data` undefined both
 * while pending and after a failed request — and this query does not retry —
 * so reading a missing `data` as 0 would turn "we do not know" into a clean
 * bill of health for the Task (IA §5.2: never fabricate certainty).
 */
export function taskFailedJobCount(
  result: { data?: { items: unknown[] } | undefined } | undefined,
): number | null {
  return result?.data ? result.data.items.length : null;
}

/**
 * What one page's health line reports, at that page's scope (IA §5.2). The
 * Operations page speaks for the whole projection; a Task page speaks only for
 * its own Task, plus any system-level hard failure that invalidates it.
 */
export interface AnsichProjectionScope extends AnsichHealthSnapshot {
  kind: "system" | "task";
  /** Warrants a banner rather than the compact healthy line. */
  attention: boolean;
  /** Rule ③: untrustworthy projection, never dismissible. */
  hardFailure: boolean;
  /** The failed-job page filled its limit, so the count is a floor. */
  failedJobsTruncated: boolean;
  /** Failed jobs plus lost Observations — what the collapsed badge counts. */
  attentionCount: number;
  snapshot: AnsichHealthSnapshot;
}

function buildScope(
  kind: "system" | "task",
  snapshot: AnsichHealthSnapshot,
  attention: boolean,
  hardFailure: boolean,
  failedJobsTruncated: boolean,
): AnsichProjectionScope {
  return {
    ...snapshot,
    kind,
    attention,
    hardFailure,
    failedJobsTruncated,
    // An unknown count contributes nothing: the badge may only promise a
    // number it can stand behind.
    attentionCount: (snapshot.failedJobs ?? 0) + snapshot.lostObservations,
    snapshot,
  };
}

/** Projection health for the whole system (Operations page). */
export function systemProjectionScope(
  health: AnsichProjectionHealthFacts,
): AnsichProjectionScope {
  return buildScope(
    "system",
    {
      failedJobs: health.failed_jobs,
      lostObservations: countLostObservations(health.lost_ranges),
      status: health.status,
    },
    isProjectionAttention(health),
    isProjectionHardFailure(health),
    false,
  );
}

/**
 * Projection health for one Task. Global degradation caused by *other* Tasks is
 * deliberately out of scope — that noise is what drove operators to ignore the
 * banner. The system status is inherited only when it is a hard failure, so a
 * dismissed Task banner is never re-promoted by an unrelated incident.
 *
 * `failedJobs.count` comes from a bounded page of this Task's failed jobs, so
 * `truncated` marks the count as a floor rather than a total.
 */
export function taskProjectionScope(
  health: AnsichProjectionHealthFacts,
  taskId: string,
  failedJobs: { count: number | null; truncated: boolean },
): AnsichProjectionScope {
  const hardFailure = isProjectionHardFailure(health);
  const lostObservations = countLostObservations(
    lostRangesForTask(health.lost_ranges, taskId),
  );
  // Unknown is not failing: an unanswered count must not raise a banner by
  // itself. It only blocks the opposite claim, that the Task is complete.
  const localAttention = (failedJobs.count ?? 0) > 0 || lostObservations > 0;
  return buildScope(
    "task",
    {
      failedJobs: failedJobs.count,
      lostObservations,
      status: hardFailure
        ? health.status
        : localAttention
          ? "degraded"
          : "healthy",
    },
    hardFailure || localAttention,
    hardFailure,
    failedJobs.truncated,
  );
}

const HEALTH_STATUS_RANK: Record<AnsichHealthStatus, number> = {
  healthy: 0,
  degraded: 1,
  failed: 2,
  stopped: 2,
};

/**
 * Whether the projection got worse than the state an operator dismissed. Only
 * a rise re-promotes the banner: a steady or improving incident stays collapsed
 * behind its badge.
 *
 * An unknown failure count is handled asymmetrically, because dismissal
 * acknowledges evidence and unknown is the absence of it. A count that *goes*
 * unknown is never a rise — unknown is not a bigger number, it is no number —
 * so it fails open and leaves the banner collapsed. But a snapshot taken while
 * the count was unknown acknowledged no failure count at all, so a count that
 * later resolves with failures in it is new evidence and re-surfaces. Resolving
 * to zero is better news than what was acknowledged and stays collapsed.
 */
export function projectionHealthWorsened(
  dismissed: AnsichHealthSnapshot,
  current: AnsichHealthSnapshot,
): boolean {
  const failedJobsRose =
    current.failedJobs !== null &&
    (dismissed.failedJobs === null
      ? current.failedJobs > 0
      : current.failedJobs > dismissed.failedJobs);
  return (
    failedJobsRose ||
    current.lostObservations > dismissed.lostObservations ||
    HEALTH_STATUS_RANK[current.status] > HEALTH_STATUS_RANK[dismissed.status]
  );
}

/**
 * The inline health line this scope renders: the attention banner, the
 * completeness claim, the neutral line for a scope whose failure count is
 * unknown, or nothing at all while the banner is collapsed behind its badge.
 */
export type AnsichProjectionHealthLine =
  | "banner"
  | "healthy"
  | "unknown"
  | "none";

export interface AnsichProjectionHealthDisplay {
  line: AnsichProjectionHealthLine;
  showBadge: boolean;
  dismissible: boolean;
  /** The stored dismissal no longer describes reality and must be dropped. */
  clearDismissal: boolean;
}

/**
 * Decide what one scope's health line shows given the dismissal an operator
 * took against it. Dismissal hides the banner behind a header badge — it never
 * removes the information from the page — and it is refused outright for a hard
 * failure. A worsening state or a full recovery drops the record, so the next
 * incident opens as a banner again rather than silently as a badge.
 */
export function resolveProjectionHealthDisplay(
  scope: AnsichProjectionScope,
  dismissed: AnsichHealthSnapshot | null,
): AnsichProjectionHealthDisplay {
  if (!scope.attention) {
    return {
      // A scope that cannot count its failed jobs may not claim completeness.
      line: scope.failedJobs === null ? "unknown" : "healthy",
      showBadge: false,
      dismissible: false,
      clearDismissal: dismissed !== null,
    };
  }
  if (scope.hardFailure) {
    return {
      line: "banner",
      showBadge: false,
      dismissible: false,
      clearDismissal: dismissed !== null,
    };
  }
  if (dismissed && !projectionHealthWorsened(dismissed, scope.snapshot)) {
    return {
      line: "none",
      showBadge: true,
      dismissible: true,
      clearDismissal: false,
    };
  }
  return {
    line: "banner",
    showBadge: false,
    dismissible: true,
    clearDismissal: dismissed !== null,
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
