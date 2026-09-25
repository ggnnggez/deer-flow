import type { HealthDiagnostic, HealthLevel, TaskListItem, ThroughputPoint } from "./contracts";
import { RESIDENCY_LANE_ORDER, residencyLane, type ResidencyLane, type ResidencyMeasure } from "./residency";

/**
 * Pure helpers behind the console page: the composition bar's window rule,
 * the task index grouping, the time-range filter, and the health view's
 * throughput series. No DOM, no fetch — everything here is unit-tested.
 */

/** The estimator's own ratio (`utf8-bytes-div4`): a window declared in tokens, measured in bytes. */
export const BYTES_PER_TOKEN = 4;

export type CompositionBasis = "window" | "request";

export interface CompositionSegment {
  lane: ResidencyLane;
  size: number;
  /** Absolute share of the basis: of the context window, or of the request when the window is unknown. */
  share: number;
  /** The fraction of the bar's track this segment paints (segments are rescaled to fill it on overflow). */
  width: number;
}

export interface WindowComposition {
  basis: CompositionBasis;
  /** The window in the chosen measure; null when unknown. */
  capacity: number | null;
  used: number;
  usedShare: number | null;
  freeShare: number | null;
  overflow: boolean;
  segments: CompositionSegment[];
}

/**
 * The composition bar's rule: 100% is the model's context window, and each
 * lane shows its absolute share of that window, with the remainder free. When
 * no window was recorded the bar falls back to the request itself as 100% and
 * says so — a window is never guessed from a model name.
 */
export function windowComposition(
  laneSizes: ReadonlyArray<{ lane: ResidencyLane; size: number }>,
  used: number,
  contextWindowTokens: number | null | undefined,
  measure: ResidencyMeasure,
): WindowComposition {
  const window = typeof contextWindowTokens === "number" && contextWindowTokens > 0 ? contextWindowTokens : null;
  if (window === null) {
    return {
      basis: "request",
      capacity: null,
      used,
      usedShare: null,
      freeShare: null,
      overflow: false,
      segments: laneSizes.map(({ lane, size }) => {
        const share = used > 0 ? size / used : 0;
        return { lane, size, share, width: share };
      }),
    };
  }
  const capacity = measure === "tokens" ? window : window * BYTES_PER_TOKEN;
  const usedShare = used / capacity;
  const overflow = used > capacity;
  return {
    basis: "window",
    capacity,
    used,
    usedShare,
    freeShare: Math.max(0, 1 - usedShare),
    overflow,
    segments: laneSizes.map(({ lane, size }) => ({
      lane,
      size,
      share: size / capacity,
      width: overflow ? (used > 0 ? size / used : 0) : size / capacity,
    })),
  };
}

export interface TaskGroupRow {
  task: TaskListItem;
  depth: 0 | 1;
}

export interface TaskGroup {
  threadId: string;
  rows: TaskGroupRow[];
  latestStartedAt: string | null;
}

/**
 * Group one page of the task index by conversation, in order of first
 * appearance (the server already sorted the page). Inside a group the leads
 * keep their order, each followed by the subagents that name it as parent;
 * subagents whose parent is not on the page are appended, still indented.
 */
export function groupTasksByThread(tasks: readonly TaskListItem[]): TaskGroup[] {
  const groups = new Map<string, TaskListItem[]>();
  for (const task of tasks) {
    const bucket = groups.get(task.thread_id);
    if (bucket) bucket.push(task);
    else groups.set(task.thread_id, [task]);
  }
  return [...groups].map(([threadId, members]) => {
    const leads = members.filter((task) => task.kind === "lead");
    const subs = members.filter((task) => task.kind !== "lead");
    const rows: TaskGroupRow[] = [];
    const placed = new Set<string>();
    for (const lead of leads) {
      rows.push({ task: lead, depth: 0 });
      for (const sub of subs) {
        if (sub.parent_task_id === lead.task_id) {
          rows.push({ task: sub, depth: 1 });
          placed.add(sub.task_id);
        }
      }
    }
    for (const sub of subs) if (!placed.has(sub.task_id)) rows.push({ task: sub, depth: 1 });
    const latestStartedAt = members.reduce<string | null>((latest, task) => (latest === null || task.started_at > latest ? task.started_at : latest), null);
    return { threadId, rows, latestStartedAt };
  });
}

export type TaskRange = "24h" | "7d" | "all";

/**
 * The `since` bound for a range, shaped like the recorder's own timestamps
 * (`isoformat()` with microseconds and `+00:00`) so the server's string
 * comparison orders the two the same way.
 */
export function rangeSince(range: TaskRange, now: Date): string | null {
  const hours = range === "24h" ? 24 : range === "7d" ? 24 * 7 : null;
  if (hours === null) return null;
  return new Date(now.getTime() - hours * 3_600_000).toISOString().replace("Z", "000+00:00");
}

/** The backend's minute bucket key, `YYYY-MM-DDTHH:MMZ` in UTC. */
export function minuteKey(date: Date): string {
  return `${date.toISOString().slice(0, 16)}Z`;
}

/** One value per minute for the last `minutes` minutes, oldest first, zero where the writer wrote nothing. */
export function throughputSeries(points: readonly ThroughputPoint[], now: Date, minutes = 60): ThroughputPoint[] {
  const byMinute = new Map(points.map((point) => [point.minute, point.events]));
  const series: ThroughputPoint[] = [];
  for (let back = minutes - 1; back >= 0; back -= 1) {
    const minute = minuteKey(new Date(now.getTime() - back * 60_000));
    series.push({ minute, events: byMinute.get(minute) ?? 0 });
  }
  return series;
}

/** SVG path data for a sparkline drawn to one scale (0 … max) inside width × height. */
export function sparklinePath(values: readonly number[], width: number, height: number, pad = 4): { line: string; area: string; max: number } {
  const max = Math.max(1, ...values);
  const count = values.length;
  const x = (index: number) => (count <= 1 ? pad : pad + (index / (count - 1)) * (width - pad * 2));
  const y = (value: number) => height - pad - (value / max) * (height - pad * 2);
  const line = values.map((value, index) => `${index === 0 ? "M" : "L"}${x(index).toFixed(1)} ${y(value).toFixed(1)}`).join(" ");
  const area = count > 0 ? `${line} L${x(count - 1).toFixed(1)} ${y(0).toFixed(1)} L${x(0).toFixed(1)} ${y(0).toFixed(1)} Z` : "";
  return { line, area, max };
}

export function healthLevel(diagnostics: readonly HealthDiagnostic[]): HealthLevel {
  if (diagnostics.some((item) => item.level === "error")) return "error";
  if (diagnostics.some((item) => item.level === "warning")) return "warning";
  return "ok";
}

/** The peak request's composition by lane, from the index's per-kind sums (tool schemas carry the `tool_schema` kind). */
export function peakLaneStack(peakByKind: Record<string, number>): Array<{ lane: ResidencyLane; size: number }> {
  const totals = new Map<ResidencyLane, number>();
  for (const [kind, size] of Object.entries(peakByKind)) {
    const lane = residencyLane({ kind, channel: kind === "tool_schema" ? "tool_schema" : "message" });
    totals.set(lane, (totals.get(lane) ?? 0) + size);
  }
  return RESIDENCY_LANE_ORDER.filter((lane) => totals.has(lane)).map((lane) => ({ lane, size: totals.get(lane)! }));
}

export function formatTokens(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}k`;
  return String(value);
}

/** A share as a percentage; anything positive that would round to zero prints as "<0.1%" rather than "0.0%". */
export function formatPercent(fraction: number, digits = 1): string {
  const percent = fraction * 100;
  const floor = 10 ** -digits;
  if (percent > 0 && percent < floor / 2) return `<${floor.toFixed(digits)}%`;
  return `${percent.toFixed(digits)}%`;
}

export function formatBytes(value: number): string {
  if (value >= 1_073_741_824) return `${(value / 1_073_741_824).toFixed(1)} GB`;
  if (value >= 1_048_576) return `${(value / 1_048_576).toFixed(1)} MB`;
  if (value >= 1_024) return `${(value / 1_024).toFixed(1)} KB`;
  return `${value} B`;
}

/** Whole seconds between two ISO timestamps, or null when either is missing or unreadable. */
export function secondsBetween(from: string | null | undefined, to: Date): number | null {
  if (!from) return null;
  const start = new Date(from).getTime();
  if (Number.isNaN(start)) return null;
  return Math.max(0, Math.round((to.getTime() - start) / 1000));
}
