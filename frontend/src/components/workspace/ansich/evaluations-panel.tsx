"use client";

import { AlertTriangleIcon } from "lucide-react";
import { useState } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { fetchAnsichEvaluationPayload } from "@/core/ansich/api";
import { useAnsichTaskEvaluations } from "@/core/ansich/hooks";
import {
  type AnsichQualityBeliefTone,
  evaluationDimensionLabelKey,
  formatAnsichTimestamp,
  formatEvaluationVerdict,
  qualityBeliefTone,
} from "@/core/ansich/presentation";
import type {
  AnsichEvaluation,
  AnsichQualityBelief,
} from "@/core/ansich/types";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

import {
  AnsichProjectionHealthBanner,
  useAnsichProjectionHealth,
} from "./projection-health";
import { AnsichShortId } from "./short-id";
import { AnsichTechnicalEvidence } from "./technical-evidence";

/**
 * Verdict colour per resolved tone. `unassessed` and `unknown` deliberately
 * share the neutral muted treatment (IA §6.2/§7.3): a dimension nothing
 * assessed is not a pass, so it may never borrow the pass or fail colour.
 */
const TONE_STYLES: Record<AnsichQualityBeliefTone, string> = {
  pass: "text-emerald-700 dark:text-emerald-300",
  fail: "text-destructive",
  partial: "text-amber-700 dark:text-amber-300",
  unassessed: "text-muted-foreground",
  unknown: "text-muted-foreground",
};

function optionalString(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function optionalNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** Read one scale bound out of an untyped Belief value. */
function scaleBound(
  value: Record<string, unknown>,
  bound: string,
): number | null {
  const scale = value.scale;
  if (typeof scale !== "object" || scale === null) return null;
  return optionalNumber((scale as Record<string, unknown>)[bound]);
}

function namedVersion(
  name: string | null,
  version: string | null,
): string | null {
  if (!name) return null;
  return version ? `${name}@${version}` : name;
}

/**
 * The Task's quality Beliefs plus the evaluation rows behind them (R6/R11).
 *
 * The list is metadata only. `expected`/`actual`/`rationale` are bodies and
 * follow the repo-wide raw-payload rule: never polled, never prefetched, loaded
 * one Observation at a time through the audited `no-store` route after an
 * explicit operator click.
 */
export function AnsichEvaluationsPanel({
  taskId,
  polling = true,
}: {
  taskId: string;
  polling?: boolean;
}) {
  const { t } = useI18n();
  const query = useAnsichTaskEvaluations(taskId, true, polling);
  const health = query.data?.projection_status ?? null;
  const projectionHealth = useAnsichProjectionHealth({
    health,
    taskId,
    polling,
  });

  if (query.isPending) {
    return <Skeleton className="h-64 w-full" />;
  }
  if (query.error) {
    return (
      <Alert variant="destructive">
        <AlertTriangleIcon />
        <AlertDescription>{query.error.message}</AlertDescription>
      </Alert>
    );
  }

  const beliefs = query.data?.quality_beliefs ?? [];
  const evaluations = query.data?.evaluations ?? [];

  return (
    <div className="space-y-4">
      {health && projectionHealth.visible && projectionHealth.scope ? (
        <AnsichProjectionHealthBanner
          health={health}
          scope={projectionHealth.scope}
          taskId={taskId}
          onDismiss={
            projectionHealth.dismissible ? projectionHealth.dismiss : undefined
          }
        />
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>{t.ansich.evaluationsTitle}</CardTitle>
        </CardHeader>
        <CardContent>
          <ul aria-label={t.ansich.evaluationsTitle} className="space-y-3">
            {beliefs.map((belief) => (
              <QualityBeliefRow key={belief.dimension} belief={belief} />
            ))}
          </ul>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t.ansich.evaluationsRecorded}</CardTitle>
        </CardHeader>
        <CardContent>
          {evaluations.length === 0 ? (
            <p className="text-muted-foreground text-sm">
              {t.ansich.evaluationsNoRecords}
            </p>
          ) : (
            <ul aria-label={t.ansich.evaluationsRecorded} className="space-y-3">
              {evaluations.map((evaluation) => (
                <RecordedEvaluationRow
                  key={evaluation.evaluation_obs_id}
                  evaluation={evaluation}
                />
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function QualityBeliefRow({ belief }: { belief: AnsichQualityBelief }) {
  const { t, locale } = useI18n();
  const tone = qualityBeliefTone(belief);
  const labelKey = evaluationDimensionLabelKey(belief.dimension);
  const label = t.ansich[labelKey];
  const verdict = formatEvaluationVerdict(
    optionalString(belief.value.verdict),
    optionalNumber(belief.value.score),
    scaleBound(belief.value, "min"),
    scaleBound(belief.value, "max"),
  );
  const assessor = namedVersion(belief.source.name, belief.source.version);
  const resolver = belief.resolver
    ? namedVersion(belief.resolver.name, belief.resolver.version)
    : null;

  return (
    <li aria-label={label} className="space-y-2 rounded-lg border p-3 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-baseline gap-2">
          <span className="font-medium">{label}</span>
          {labelKey === "dimensionCustom" ? (
            <code className="text-muted-foreground text-xs">
              {belief.dimension}
            </code>
          ) : null}
        </div>
        <span className={cn("font-medium", TONE_STYLES[tone])}>
          {belief.unassessed ? t.ansich.evaluationsUnassessed : verdict}
        </span>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="outline">{belief.authority_class}</Badge>
        <Badge variant="outline">{belief.fidelity_class}</Badge>
        {belief.conflicting_assertion_count > 0 ? (
          <Badge
            variant="outline"
            className="border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-300"
          >
            {t.ansich.evaluationsConflicts}:{" "}
            {belief.conflicting_assertion_count}
          </Badge>
        ) : null}
      </div>
      <div className="text-muted-foreground flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
        <span>
          {t.ansich.evaluationsAssessor}:{" "}
          <span className="font-mono">
            {assessor ?? t.ansich.evidenceInsufficient}
          </span>
        </span>
        <span>
          {t.ansich.resolver}:{" "}
          <span className="font-mono">
            {resolver ?? t.ansich.evidenceInsufficient}
          </span>
        </span>
      </div>
      <AnsichTechnicalEvidence>
        <dl className="grid gap-x-6 gap-y-2 text-xs sm:grid-cols-2">
          <TechRow
            label={t.ansich.asOf}
            value={formatAnsichTimestamp(belief.as_of, locale)}
          />
          <div className="flex flex-wrap gap-2 sm:col-span-2">
            <dt className="text-muted-foreground">
              {t.ansich.evaluationsEvidence}
            </dt>
            <dd className="flex flex-wrap gap-2">
              {belief.evidence_obs_ids.length === 0 ? (
                <span className="text-muted-foreground">
                  {t.ansich.evidenceInsufficient}
                </span>
              ) : (
                belief.evidence_obs_ids.map((obsId) => (
                  <AnsichShortId key={obsId} value={obsId} />
                ))
              )}
            </dd>
          </div>
        </dl>
      </AnsichTechnicalEvidence>
    </li>
  );
}

function RecordedEvaluationRow({
  evaluation,
}: {
  evaluation: AnsichEvaluation;
}) {
  const { t, locale } = useI18n();
  const [bodies, setBodies] = useState<Record<string, unknown> | undefined>(
    undefined,
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const labelKey = evaluationDimensionLabelKey(evaluation.dimension);
  const verdict = formatEvaluationVerdict(
    evaluation.verdict,
    evaluation.score,
    evaluation.scale_min,
    evaluation.scale_max,
  );

  // Lazy by construction: the bodies are requested only here, never with the
  // polled list and never into the query cache.
  async function loadBodies() {
    setLoading(true);
    setError(null);
    try {
      const response = await fetchAnsichEvaluationPayload(
        evaluation.evaluation_obs_id,
      );
      setBodies(response.payload.evaluation ?? {});
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t.ansich.loadFailed);
    } finally {
      setLoading(false);
    }
  }

  return (
    <li className="space-y-2 rounded-lg border p-3 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="outline">{evaluation.evaluation_kind}</Badge>
          <span className="font-medium">{t.ansich[labelKey]}</span>
          <span className="text-muted-foreground">{verdict}</span>
        </div>
        <span className="text-muted-foreground text-xs">
          {formatAnsichTimestamp(evaluation.occurred_at, locale)}
        </span>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {evaluation.cohort_key ? (
          <Badge variant="outline">{evaluation.cohort_key}</Badge>
        ) : null}
        {evaluation.suite_id ? (
          <Badge variant="outline">
            {namedVersion(evaluation.suite_id, evaluation.suite_version)}
          </Badge>
        ) : null}
        {bodies === undefined ? (
          <Button
            size="sm"
            variant="outline"
            className="ms-auto"
            disabled={loading}
            onClick={loadBodies}
          >
            {loading ? t.ansich.loading : t.ansich.evaluationsExpectedActual}
          </Button>
        ) : null}
      </div>
      {error ? <div className="text-destructive text-xs">{error}</div> : null}
      {bodies !== undefined ? (
        <dl className="grid gap-x-6 gap-y-2 text-xs">
          <BodyRow
            label={t.ansich.evaluationsExpected}
            value={optionalString(bodies.expected)}
          />
          <BodyRow
            label={t.ansich.evaluationsActual}
            value={optionalString(bodies.actual)}
          />
          <BodyRow
            label={t.ansich.evaluationsRationale}
            value={optionalString(bodies.rationale)}
          />
        </dl>
      ) : null}
      <AnsichTechnicalEvidence>
        <dl className="grid gap-x-6 gap-y-2 text-xs sm:grid-cols-2">
          <TechRow
            label={t.ansich.evaluationsAssessor}
            value={
              namedVersion(
                evaluation.assessor_name,
                evaluation.assessor_version,
              ) ?? t.ansich.evidenceInsufficient
            }
          />
          <TechRow
            label={t.ansich.fidelity}
            value={`${evaluation.authority_class} · ${evaluation.fidelity_class}`}
          />
          <div className="flex flex-wrap gap-2 sm:col-span-2">
            <dt className="text-muted-foreground">
              {t.ansich.evaluationsEvidence}
            </dt>
            <dd>
              <AnsichShortId value={evaluation.evaluation_obs_id} />
            </dd>
          </div>
        </dl>
      </AnsichTechnicalEvidence>
    </li>
  );
}

/**
 * One evaluation body field. `expected`/`actual`/`rationale` are optional in
 * the contract, so an absent one reads as "not available" — the assessor
 * recorded nothing here, which is not the same claim as missing evidence.
 */
function BodyRow({ label, value }: { label: string; value: string | null }) {
  const { t } = useI18n();
  return (
    <div className="flex flex-wrap gap-2">
      <dt className="text-muted-foreground shrink-0">{label}</dt>
      <dd className="min-w-0 break-words whitespace-pre-wrap">
        {value ?? t.ansich.notAvailable}
      </dd>
    </div>
  );
}

function TechRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex gap-2">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="font-mono break-all">{value}</dd>
    </div>
  );
}
