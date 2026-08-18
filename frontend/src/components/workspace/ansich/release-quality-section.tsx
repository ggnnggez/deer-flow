"use client";

import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { evaluationDimensionLabelKey } from "@/core/ansich/presentation";
import {
  formatObservedDelta,
  qualityComparisonReasonKey,
  qualityComparisonState,
  qualityScaleDirection,
} from "@/core/ansich/release-presentation";
import type { AnsichQualityComparison } from "@/core/ansich/types";
import { useI18n } from "@/core/i18n/hooks";

/**
 * The semantic quality half of a release-to-release comparison.
 *
 * It is a card of its own so semantic quality stays visually partitioned from
 * the operational/structural diff (spec §7): a prompt hash changing and a
 * measured evaluation differing are different kinds of claim and must not read
 * as one list of changes.
 *
 * The whole block is optional in the response — an older backend, or one
 * without evaluation storage, omits it — and absence is rendered as nothing at
 * all rather than as "no quality difference".
 */
export function AnsichReleaseQualitySection({
  quality,
}: {
  quality?: { comparisons: AnsichQualityComparison[]; cohort: string | null };
}) {
  const { t } = useI18n();
  if (!quality) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t.ansich.qualityTitle}</CardTitle>
        <CardDescription>{t.ansich.qualityDescription}</CardDescription>
      </CardHeader>
      <CardContent>
        {quality.comparisons.length === 0 ? (
          <p className="text-muted-foreground text-sm">
            {t.ansich.qualityNoComparisons}
          </p>
        ) : (
          <ul aria-label={t.ansich.qualityTitle} className="space-y-3">
            {quality.comparisons.map((item) => (
              <QualityComparisonRow
                key={`${item.dimension}:${item.cohort_key}`}
                item={item}
              />
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

/**
 * One `(dimension, cohort)` row in one of three deliberately distinct states
 * (spec §8): an observed delta with its sample counts, a muted refusal with the
 * localized reason — muted, never the error colour, because declining to
 * compare is not a failure — or a neutral unassessed marker when the pair was
 * comparable but produced no delta.
 */
function QualityComparisonRow({ item }: { item: AnsichQualityComparison }) {
  const { t } = useI18n();
  const state = qualityComparisonState(item);
  const labelKey = evaluationDimensionLabelKey(item.dimension);
  const label = t.ansich[labelKey];
  const direction = qualityScaleDirection(item);
  const resolver = `${item.resolver.name}@${item.resolver.version}`;

  return (
    <li aria-label={label} className="space-y-2 rounded-lg border p-3 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-baseline gap-2">
          <span className="font-medium">{label}</span>
          {labelKey === "dimensionCustom" ? (
            <code className="text-muted-foreground text-xs">
              {item.dimension}
            </code>
          ) : null}
          {/* The empty cohort key is the explicit declared-no-cohort bucket,
              which is a sample list rather than a comparison population. */}
          <Badge variant="outline">
            {item.cohort_key === ""
              ? t.ansich.qualityNoCohort
              : item.cohort_key}
          </Badge>
        </div>
        {state === "comparable" ? (
          <span className="flex flex-wrap items-baseline gap-2">
            <span className="text-muted-foreground text-xs">
              {t.ansich.qualityObservedDelta}
            </span>
            <span className="font-mono font-medium tabular-nums">
              {formatObservedDelta(item.observed_delta)}
            </span>
          </span>
        ) : state === "not_comparable" ? (
          <span className="text-muted-foreground">
            {t.ansich.qualityNotComparable}
          </span>
        ) : (
          <span className="text-muted-foreground">
            {t.ansich.qualityUnassessed}
          </span>
        )}
      </div>

      {state === "comparable" ? (
        <div className="text-muted-foreground flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
          <span>
            {t.ansich.qualitySamples}:{" "}
            <span className="font-mono">
              {item.left_sample_count} → {item.right_sample_count}
            </span>
          </span>
          {/* Polarity is reported only when both coverage cells state it; the
              delta's own sign never implies which direction is better. */}
          {direction === "higher_is_better" ? (
            <span>{t.ansich.qualityScaleHigherIsBetter}</span>
          ) : direction === "lower_is_better" ? (
            <span>{t.ansich.qualityScaleLowerIsBetter}</span>
          ) : null}
        </div>
      ) : null}

      {state === "not_comparable" ? (
        <p className="text-muted-foreground text-xs">
          {t.ansich[qualityComparisonReasonKey(item)]}
        </p>
      ) : null}

      <div className="text-muted-foreground text-xs">
        {t.ansich.resolver}: <span className="font-mono">{resolver}</span>
      </div>
    </li>
  );
}
