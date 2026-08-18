import type {
  AnsichAgentReleaseComparison,
  AnsichQualityComparison,
  AnsichReleaseFieldChange,
} from "./types";

export interface AnsichReleaseDiffItem {
  kind:
    | "changed"
    | "added"
    | "removed"
    | "schema_changed"
    | "description_changed"
    | "source_changed";
  path: string;
  left: unknown;
  right: unknown;
}

export interface AnsichReleaseDiffGroup {
  component: "model" | "prompt" | "tools" | "policy" | "runtime_build";
  items: AnsichReleaseDiffItem[];
}

function fieldItems(changes: AnsichReleaseFieldChange[]) {
  return changes.map((change) => ({ kind: "changed" as const, ...change }));
}

function toolItems(
  tools: AnsichAgentReleaseComparison["tools"],
): AnsichReleaseDiffItem[] {
  return [
    ...tools.added.map((tool) => ({
      kind: "added" as const,
      path: `${tool.source}:${tool.name}`,
      left: null,
      right: "present",
    })),
    ...tools.removed.map((tool) => ({
      kind: "removed" as const,
      path: `${tool.source}:${tool.name}`,
      left: "present",
      right: null,
    })),
    ...tools.schema_changed.map((tool) => ({
      kind: "schema_changed" as const,
      path: `${tool.source}:${tool.name}`,
      left: tool.left,
      right: tool.right,
    })),
    ...tools.description_changed.map((tool) => ({
      kind: "description_changed" as const,
      path: `${tool.source}:${tool.name}`,
      left: tool.left,
      right: tool.right,
    })),
    ...tools.source_changed.map((tool) => ({
      kind: "source_changed" as const,
      path: tool.name,
      left: tool.left_source,
      right: tool.right_source,
    })),
  ];
}

export function getAgentReleaseDiffGroups(
  comparison: AnsichAgentReleaseComparison,
): AnsichReleaseDiffGroup[] {
  const groups: AnsichReleaseDiffGroup[] = [
    { component: "model", items: fieldItems(comparison.model) },
    { component: "prompt", items: fieldItems(comparison.prompt) },
    { component: "tools", items: toolItems(comparison.tools) },
    { component: "policy", items: fieldItems(comparison.policy) },
    { component: "runtime_build", items: fieldItems(comparison.build) },
  ];
  return groups.filter((group) => group.items.length > 0);
}

/**
 * How one quality dimension row must be presented. The three states are
 * deliberately separate vocabularies (spec §8): a refused comparison is not a
 * bad result, and a pair nothing measured is not a neutral good one, so neither
 * may borrow the delta's treatment.
 */
export type AnsichQualityComparisonState =
  | "comparable"
  | "not_comparable"
  | "unassessed";

/**
 * Classify one dimension of a release-to-release quality comparison.
 *
 * The backend's refusal wins before any value inspection, so a `reason` can
 * never be dressed up as a measurement. A comparable pair that produced no
 * delta is `unassessed`: something was comparable in principle but nothing was
 * observed, which is not the same claim as "no difference".
 */
export function qualityComparisonState(
  item: AnsichQualityComparison,
): AnsichQualityComparisonState {
  if (item.comparison_status !== "comparable") return "not_comparable";
  return typeof item.observed_delta === "number" &&
    Number.isFinite(item.observed_delta)
    ? "comparable"
    : "unassessed";
}

/** The i18n key naming one machine-readable comparability refusal. */
export type AnsichQualityReasonLabelKey =
  | "qualityReasonNoSharedCohort"
  | "qualityReasonScaleMismatch"
  | "qualityReasonInsufficientSamples"
  | "qualityReasonObservabilityLoss"
  | "qualityReasonUnknown";

const QUALITY_REASON_LABEL_KEYS: Record<string, AnsichQualityReasonLabelKey> = {
  no_shared_cohort: "qualityReasonNoSharedCohort",
  scale_mismatch: "qualityReasonScaleMismatch",
  insufficient_samples: "qualityReasonInsufficientSamples",
  observability_loss: "qualityReasonObservabilityLoss",
};

/**
 * Name why a comparison was declined. The contract types `reason` as an open
 * string so a newer backend can add refusals, so an unrecognized or absent code
 * degrades to explicit unknown copy instead of being mapped onto a known one.
 */
export function qualityComparisonReasonKey(
  item: AnsichQualityComparison,
): AnsichQualityReasonLabelKey {
  if (item.reason === null) return "qualityReasonUnknown";
  return QUALITY_REASON_LABEL_KEYS[item.reason] ?? "qualityReasonUnknown";
}

/** Decimal places the observed delta is rendered with. */
const OBSERVED_DELTA_PRECISION = 3;

/**
 * Render an observed delta with an explicit sign.
 *
 * v1 reports the observed difference only — never a significance claim and
 * never a better/worse verdict, because the delta's polarity belongs to the
 * scale, not to this number. A value that rounds to zero at the rendered
 * precision loses its sign rather than claiming a direction the digits do not
 * show, and an absent or non-finite delta renders as an explicit dash.
 */
export function formatObservedDelta(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return "—";
  const factor = 10 ** OBSERVED_DELTA_PRECISION;
  const rounded = Math.round(value * factor) / factor;
  if (rounded === 0) return "0";
  return rounded > 0 ? `+${rounded}` : String(rounded);
}

/**
 * Which direction of a scored dimension is the better one, when the payload
 * says so. `unknown` is the honest default — it is never inferred from the
 * delta's sign or from the dimension's name.
 */
export type AnsichQualityScaleDirection =
  | "higher_is_better"
  | "lower_is_better"
  | "unknown";

function cellScalePolarity(
  coverage: Record<string, unknown>,
  side: "left" | "right",
): boolean | null {
  const cell = coverage[side];
  if (typeof cell !== "object" || cell === null) return null;
  const scale = (cell as Record<string, unknown>).scale;
  if (typeof scale !== "object" || scale === null) return null;
  const polarity = (scale as Record<string, unknown>).higher_is_better;
  return typeof polarity === "boolean" ? polarity : null;
}

/**
 * Read the scale polarity both cells of one comparison carry.
 *
 * The backend ships polarity inside each coverage cell's `scale`
 * (`{min, max, higher_is_better}`), but only for scored cohorts — a
 * verdict-only cohort has no scale, and its delta is a pass-rate difference.
 * Both sides must state the same polarity for it to be reported: a missing,
 * non-boolean, or disagreeing value is `unknown`, so the UI can annotate the
 * scale without ever guessing which way is better.
 */
export function qualityScaleDirection(
  item: AnsichQualityComparison,
): AnsichQualityScaleDirection {
  const coverage = item.coverage;
  if (typeof coverage !== "object" || coverage === null) return "unknown";
  const left = cellScalePolarity(coverage, "left");
  const right = cellScalePolarity(coverage, "right");
  if (left === null || right === null || left !== right) return "unknown";
  return left ? "higher_is_better" : "lower_is_better";
}
