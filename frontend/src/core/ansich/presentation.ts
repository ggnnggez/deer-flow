import type {
  AnsichAlertType,
  AnsichDatabaseHealth,
  AnsichHealth,
  AnsichLostRange,
  AnsichProducerHealth,
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
    case "environment_pressure":
    case "environment_leak_suspected":
    // The process-subject pair (P11-B §3). They join the same category as the
    // environment Alerts they sit beside: signals an operator acts on that are
    // not a claim about how one Agent behaved. Neither is runaway behavior, and
    // neither is a liveness rule about a Task.
    case "projection_failure":
    case "observability_degradation":
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
 * The transient lifecycle phases: nothing has run yet, or an orderly stop is in
 * progress (its failure tier is `stopped`, one transition later). Neither is an
 * incident — a banner on every process start and stop is exactly what teaches
 * operators to ignore the banner — and neither is a clean bill of health, since
 * a projector that has not begun has produced no evidence of completeness.
 * They are a symmetric pair and are never split.
 */
const LIFECYCLE_PHASE_STATUSES: ReadonlySet<AnsichHealthStatus> = new Set([
  "starting",
  "shutting_down",
]);

/**
 * Whether this status is a lifecycle phase rather than a claim about the data.
 */
export function isProjectionLifecyclePhase(
  status: AnsichHealthStatus,
): boolean {
  return LIFECYCLE_PHASE_STATUSES.has(status);
}

/**
 * The statuses that are not, by themselves, an incident: a clean projection and
 * the two lifecycle phases. `recovering` is deliberately absent — nothing is
 * failing right now, but the incident that caused it is not over.
 */
const NON_ATTENTION_HEALTH_STATUSES: ReadonlySet<AnsichHealthStatus> = new Set([
  "healthy",
  ...LIFECYCLE_PHASE_STATUSES,
]);

/**
 * Whether projection health warrants a page-level banner rather than a compact
 * status line (IA §5.2): a status that names an incident, any failed job, any
 * lost range, or storage unavailable. A healthy line must never hide these.
 *
 * A lifecycle phase excuses only the status. A failed job or a lost range
 * recorded during one is evidence in its own right and still raises the banner.
 */
export function isProjectionAttention(health: {
  status: AnsichHealthStatus;
  failed_jobs: number;
  lost_ranges: unknown[];
  storage_available: boolean;
}): boolean {
  return (
    !NON_ATTENTION_HEALTH_STATUSES.has(health.status) ||
    health.failed_jobs > 0 ||
    health.lost_ranges.length > 0 ||
    !health.storage_available
  );
}

/**
 * The collector's lifecycle states, taken straight from the contract so the two
 * cannot drift: the backend derives all seven (spec 11 §2) and the UI has to be
 * able to name every one it can be handed.
 */
export type AnsichHealthStatus = AnsichHealth["status"];

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

/**
 * The severity order a dismissal is compared across. `recovering` sits between
 * healthy and degraded: nothing is failing right now, but the incident is not
 * over. `failed` and `stopped` are equally bad — both mean the projection
 * cannot be trusted at all.
 *
 * `starting` and `shutting_down` are deliberately absent rather than ranked
 * alongside healthy. They are lifecycle phases, not tiers of an incident, so
 * they take part in no comparison at all — the same posture as an unknown
 * failure count, which is no number rather than a small one.
 */
const HEALTH_STATUS_RANK: Partial<Record<AnsichHealthStatus, number>> = {
  healthy: 0,
  recovering: 1,
  degraded: 2,
  failed: 3,
  stopped: 3,
};

/**
 * Whether the status alone got worse. A status this build cannot rank — a
 * lifecycle phase, or one a newer build wrote into the record — yields no
 * verdict in either direction: calling it worse would re-promote the banner on
 * every poll, and calling it better would be a claim just as unfounded.
 */
function healthStatusWorsened(
  dismissed: AnsichHealthStatus,
  current: AnsichHealthStatus,
): boolean {
  const before = HEALTH_STATUS_RANK[dismissed];
  const after = HEALTH_STATUS_RANK[current];
  if (before === undefined || after === undefined) return false;
  return after > before;
}

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
    healthStatusWorsened(dismissed.status, current.status)
  );
}

/**
 * The inline health line this scope renders: the attention banner, the
 * completeness claim, the neutral line naming a lifecycle phase, the neutral
 * line for a scope whose failure count is unknown, or nothing at all while the
 * banner is collapsed behind its badge.
 */
export type AnsichProjectionHealthLine =
  | "banner"
  | "healthy"
  | "phase"
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
 * incident opens as a banner again rather than silently as a badge — but only a
 * recovery a real count can vouch for: unknown is not a rise, not completeness,
 * and not recovery either. Neither is a lifecycle phase, which acknowledges
 * nothing and claims nothing.
 */
export function resolveProjectionHealthDisplay(
  scope: AnsichProjectionScope,
  dismissed: AnsichHealthSnapshot | null,
): AnsichProjectionHealthDisplay {
  if (!scope.attention) {
    // A phase outranks an unknown count as the reason for making no claim: it
    // is the more specific answer, and it is the one an operator can act on.
    const phase = isProjectionLifecyclePhase(scope.status);
    const unknown = scope.failedJobs === null;
    return {
      // Neither a scope in a lifecycle phase nor one that cannot count its
      // failed jobs may claim completeness.
      line: phase ? "phase" : unknown ? "unknown" : "healthy",
      showBadge: false,
      dismissible: false,
      // Nor is either one a recovery: keep the record until a real count says
      // so. Clearing here would let the pending window after a reload — where
      // sessionStorage survives but the query cache does not — discard a
      // dismissal, making its lifetime a request race.
      clearDismissal: !phase && !unknown && dismissed !== null,
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

/**
 * How many producer rows the System details drawer lists before it starts
 * counting the rest. The Collector's ledger is bounded but still far larger
 * than a drawer should tile.
 */
export const ANSICH_PRODUCER_ROW_LIMIT = 8;

export interface AnsichBoundedProducers {
  rows: AnsichProducerHealth[];
  /** Producers the table did not list. Rendered, never silently dropped. */
  hiddenCount: number;
}

/**
 * The producer rows worth showing first — the ones dropping the most — plus how
 * many were left out, because a truncated table with nothing to say about the
 * remainder reads as the whole ledger.
 *
 * Ties fall back to producer identity, the same key the Collector orders its
 * own ledger by, so two reads of an unchanged ledger render the same table
 * rather than one that reshuffles with arrival order.
 */
export function topProducersByDropped(
  producers: readonly AnsichProducerHealth[],
  limit: number = ANSICH_PRODUCER_ROW_LIMIT,
): AnsichBoundedProducers {
  const ordered = [...producers].sort(
    (left, right) =>
      right.dropped_count - left.dropped_count ||
      left.producer_name.localeCompare(right.producer_name) ||
      left.producer_instance_id.localeCompare(right.producer_instance_id),
  );
  const kept = Math.max(0, limit);
  return {
    rows: ordered.slice(0, kept),
    hiddenCount: Math.max(0, ordered.length - kept),
  };
}

/**
 * What an unknown number renders as. The database block's `null` means unknown
 * and never zero, so it needs a mark of its own: rendering it as `0` would
 * report "nothing is behind, nothing has failed" about a store nobody could
 * read.
 */
export const ANSICH_UNKNOWN_VALUE = "—";

/**
 * Render a quantity, keeping unknown (`null`) visibly distinct from zero.
 *
 * The locale is the app's, passed in the way `formatAnsichTimestamp` already
 * takes it — a bare `toLocaleString()` would group by whatever locale the
 * browser runs in, which is not necessarily one this app offers.
 */
export function formatAnsichCount(
  value: number | null | undefined,
  locale: string,
): string {
  if (value === null || value === undefined) return ANSICH_UNKNOWN_VALUE;
  return value.toLocaleString(locale === "zh-CN" ? "zh-CN" : "en-US");
}

/**
 * Render an ingest-sequence mark: plain digits, never grouped.
 *
 * A sequence is a position in the stream, not a quantity — it gets compared
 * against the raw `ingest_seq` in a log line or an API response, and thousands
 * separators only make the reader strip them back out.
 */
export function formatAnsichSequence(value: number | null | undefined): string {
  return value === null || value === undefined
    ? ANSICH_UNKNOWN_VALUE
    : String(value);
}

/**
 * The one lag rendering for every Ansich surface (health line, System details
 * drawer, Observability panel). Sub-second lag stays in milliseconds because
 * that is the range where the exact number matters; past a second the reader
 * wants the magnitude. Two views one click apart must not disagree about what
 * the same `lag_ms` says.
 */
export function formatAnsichLag(lagMs: number | null | undefined): string {
  if (lagMs === null || lagMs === undefined) return ANSICH_UNKNOWN_VALUE;
  if (lagMs < 1000) return `${lagMs}ms`;
  return `${(lagMs / 1000).toFixed(1)}s`;
}

/** One projector's row in the Observability health panel. */
export interface AnsichProjectorRow {
  /** `name@version` — stable across reads, unique per registered projector. */
  key: string;
  name: string;
  version: string;
  pending: number;
  retry: number;
  processing: number;
  failed: number;
  /** Every unsettled bucket summed. `retry` is owed work, so it counts here. */
  outstanding: number;
  /**
   * The continuity mark: nothing at or below this ingest sequence is still owed
   * by this projector. Not a maximum and not progress.
   */
  completeThrough: number | null;
  /** A durably failed job — the one bucket an operator has to act on. */
  attention: boolean;
}

export interface AnsichDatabaseHealthPresentation {
  reachable: boolean;
  projectors: AnsichProjectorRow[];
  /** Age of the oldest unsettled job's Observation. */
  lagMs: number | null;
  /** Authoritative across every worker, unlike the process-local count. */
  failedJobs: number | null;
  /** This worker's own dropped writes after a lease takeover. */
  staleCompletions: number | null;
  /**
   * The store-wide continuity mark: the lowest per-projector mark, because the
   * store owes nothing below a sequence only if every projector owes nothing
   * below it. Unknown when any projector's own mark is unknown, or when no
   * projector has ever had a job.
   */
  settledThrough: number | null;
  /** Total unsettled jobs across projectors; unknown when unreadable. */
  outstanding: number | null;
  /** Unreadable storage, or any durably failed job. */
  attention: boolean;
}

/**
 * The single unreadable answer, handed to every caller by reference and frozen
 * so one consumer cannot mutate the object — or its `projectors` array — into
 * something the next reader receives.
 */
const UNREADABLE_DATABASE_HEALTH: AnsichDatabaseHealthPresentation = {
  reachable: false,
  projectors: [],
  lagMs: null,
  failedJobs: null,
  staleCompletions: null,
  settledThrough: null,
  outstanding: null,
  attention: true,
};
Object.freeze(UNREADABLE_DATABASE_HEALTH.projectors);
Object.freeze(UNREADABLE_DATABASE_HEALTH);

/**
 * Project the additive `database` block into what the panel renders.
 *
 * `status` gates everything: an `unreachable` block — or an absent one, from a
 * backend that predates the merge — yields unknown for every number rather than
 * a zero, whatever numbers the payload happened to carry. Unreadable is itself
 * an incident, so it warrants attention on its own; it is never a clean store.
 *
 * Projector order is the backend's (registration order), not a ranking: the row
 * that needs attention is marked, not moved, so an operator reading the panel
 * twice sees the same table.
 */
export function getDatabaseHealthPresentation(
  database: AnsichDatabaseHealth | null | undefined,
): AnsichDatabaseHealthPresentation {
  if (database?.status !== "reachable") {
    return UNREADABLE_DATABASE_HEALTH;
  }
  const projectors = database.projectors.map((projector) => ({
    key: `${projector.projector_name}@${projector.projector_version}`,
    name: projector.projector_name,
    version: projector.projector_version,
    pending: projector.pending,
    retry: projector.retry,
    processing: projector.processing,
    failed: projector.failed,
    outstanding:
      projector.pending +
      projector.retry +
      projector.processing +
      projector.failed,
    completeThrough: projector.complete_through,
    attention: projector.failed > 0,
  }));
  const marks = projectors.map((row) => row.completeThrough);
  const knownMarks = marks.filter((mark): mark is number => mark !== null);
  // A projector whose own mark is unknown leaves the store-wide one unknown:
  // taking the minimum of the rest would claim continuity nobody vouched for.
  const settledThrough =
    marks.length > 0 && knownMarks.length === marks.length
      ? Math.min(...knownMarks)
      : null;
  return {
    reachable: true,
    projectors,
    lagMs: database.lag_ms,
    failedJobs: database.failed_jobs,
    staleCompletions: database.stale_completion_count,
    settledThrough,
    outstanding: projectors.reduce((total, row) => total + row.outstanding, 0),
    attention:
      (database.failed_jobs ?? 0) > 0 ||
      projectors.some((row) => row.attention),
  };
}

/**
 * The three states the panel's headline badge can be in.
 *
 * `healthy` and `attention` are both reachable stores, and keeping them apart is
 * the point: a store that answers while three jobs have durably failed — the
 * exact condition `projection_failure` opens an Alert for — must not present as
 * a green "reachable" headline just because the connection worked. `unreadable`
 * is its own third state, not a worse `attention`: nothing is known there.
 */
export type AnsichDatabaseHealthBadge = "healthy" | "attention" | "unreadable";

export function databaseHealthBadge(
  database: AnsichDatabaseHealthPresentation,
): AnsichDatabaseHealthBadge {
  if (!database.reachable) return "unreadable";
  return database.attention ? "attention" : "healthy";
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

/**
 * Presentation tone for the environment badges below. `positive` is reserved
 * for evidence that actively earns it (continuous coverage, an `ok`/`none`
 * belief); an absence of instrumentation or judgement is `neutral`, never
 * `positive` — IA §6.2/§7.3's "never green for missing evidence" rule extended
 * to environment observability.
 */
export type AnsichEnvironmentBadgeTone =
  | "positive"
  | "neutral"
  | "warning"
  | "critical";

export interface AnsichEnvironmentBadge {
  label: string;
  tone: AnsichEnvironmentBadgeTone;
}

/**
 * Label the semantic tier of an environment sample (concepts §9.6 /
 * environment-observability design §3.2 point 1). This distinction must never
 * be lost between projection, assessor, API, and UI: `container` is a real
 * sandbox-wide reading, `process_group` is one command's own snapshot (it
 * cannot see standing state), and `host_shared` is shared with every other
 * process on the host and must never be presented as a sandbox metric.
 *
 * Labels are fixed Chinese copy per the environment-observability spec's copy
 * discipline, independent of the active UI locale — these are new,
 * domain-specific technical marks with no established bilingual precedent yet
 * (unlike `alertTypeLabel`, which reuses the existing i18n table).
 */
export function environmentScopeBadge(scope: string): AnsichEnvironmentBadge {
  switch (scope) {
    case "container":
      return { label: "容器实测", tone: "positive" };
    case "process_group":
      return { label: "进程组快照", tone: "neutral" };
    case "host_shared":
      return { label: "宿主共享", tone: "neutral" };
    default:
      return { label: scope, tone: "neutral" };
  }
}

/**
 * Label how a `(Scope, environment_scope)` card was observed. `uninstrumented`
 * renders as an explicit "未观测" — never ok/green — because no instrumentation
 * is not evidence of a healthy environment (same discipline as
 * `isProjectionHardFailure` refusing to read missing evidence as clean).
 */
export function coverageBadge(coverage: string): AnsichEnvironmentBadge {
  switch (coverage) {
    case "continuous":
      return { label: "连续采样", tone: "positive" };
    case "per_command":
      return { label: "单命令采样", tone: "neutral" };
    case "uninstrumented":
      return { label: "未观测", tone: "neutral" };
    default:
      return { label: coverage, tone: "neutral" };
  }
}

const ENVIRONMENT_BELIEF_BADGES: Record<string, AnsichEnvironmentBadge> = {
  ok: { label: "正常", tone: "positive" },
  warning: { label: "预警", tone: "warning" },
  critical: { label: "严重", tone: "critical" },
  none: { label: "正常", tone: "positive" },
  suspected: { label: "严重", tone: "critical" },
  unknown: { label: "未知", tone: "neutral" },
};

/**
 * Label one environment Belief's categorical state. `environment_pressure:*`
 * Beliefs use the `ok/warning/critical/unknown` family; `environment_leak:*`
 * Beliefs use their own `none/suspected/unknown` family (assess_environment_leak
 * never emits ok/warning/critical). Any value outside a field's own family
 * — including a raw, unassessed synthesized Belief — renders as the neutral
 * "未知" mark, never a blank or a borrowed positive color (concepts 第 9 条第
 * 6 款: unknown is a first-class value, not a missing row).
 */
export function environmentBeliefBadge(
  fieldName: string,
  rawValue: string,
): AnsichEnvironmentBadge {
  if (fieldName.startsWith("environment_leak:")) {
    if (rawValue === "none" || rawValue === "suspected") {
      return ENVIRONMENT_BELIEF_BADGES[rawValue]!;
    }
    return ENVIRONMENT_BELIEF_BADGES.unknown!;
  }
  if (rawValue === "ok" || rawValue === "warning" || rawValue === "critical") {
    return ENVIRONMENT_BELIEF_BADGES[rawValue]!;
  }
  return ENVIRONMENT_BELIEF_BADGES.unknown!;
}
