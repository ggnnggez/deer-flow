"use client";

import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  useAnsichEnvironmentHistory,
  useAnsichTaskEnvironment,
  useAnsichTaskToolEnvSamples,
} from "@/core/ansich/hooks";
import {
  coverageBadge,
  environmentBeliefBadge,
  environmentScopeBadge,
  formatAnsichTimestamp,
  type AnsichEnvironmentBadge,
} from "@/core/ansich/presentation";
import type {
  AnsichAlertType,
  AnsichEnvironmentAlertSummary,
  AnsichEnvironmentBelief,
  AnsichEnvironmentMetric,
  AnsichEnvironmentScope,
} from "@/core/ansich/types";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

import { AnsichSparkline } from "./sparkline";
import { formatBytes } from "./system-health-drawer";

//: The trend window every continuous-coverage metric row requests.
const TREND_WINDOW_MINUTES = 60;

const TONE_STYLES: Record<AnsichEnvironmentBadge["tone"], string> = {
  positive:
    "border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
  neutral: "text-muted-foreground",
  warning:
    "border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-300",
  critical: "border-red-500/40 bg-red-500/10 text-red-700 dark:text-red-300",
};

function ToneBadge({ badge }: { badge: AnsichEnvironmentBadge }) {
  return (
    <Badge variant="outline" className={cn(TONE_STYLES[badge.tone])}>
      {badge.label}
    </Badge>
  );
}

function formatMetricValue(metric: string, value: number): string {
  return metric.endsWith("_bytes")
    ? formatBytes(value)
    : value.toLocaleString();
}

/**
 * Task detail's "Runtime environment" panel (Task 11): one card per
 * `(Scope, environment_scope)` coverage row, each carrying its own coverage/
 * scope-tier badges, current metrics, categorical Belief state, and any
 * environment Alerts opened against that Scope. Reuses the house
 * `signal-badge.tsx`/`status-badge.tsx` convention of pairing a tone with an
 * explicit label; unknown never renders as blank or positive (IA §6.2/§7.3).
 */
export function AnsichEnvironmentPanel({
  taskId,
  polling,
}: {
  taskId: string;
  polling: boolean;
}) {
  const { t, locale } = useI18n();
  const query = useAnsichTaskEnvironment(taskId, true, polling);

  if (query.isPending) {
    return <Skeleton className="h-48 w-full" />;
  }
  if (query.error) {
    return (
      <div className="text-destructive rounded-lg border p-4 text-sm">
        {query.error.message}
      </div>
    );
  }

  const scopes = query.data?.scopes ?? [];
  if (scopes.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>{t.ansich.environment}</CardTitle>
        </CardHeader>
        <CardContent className="text-muted-foreground text-sm">
          {t.ansich.environmentEmpty}
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      {scopes.map((scope) => (
        <EnvironmentScopeCard
          key={`${scope.scope_id}:${scope.environment_scope}`}
          scope={scope}
          taskId={taskId}
          locale={locale}
        />
      ))}
    </div>
  );
}

function EnvironmentScopeCard({
  scope,
  taskId,
  locale,
}: {
  scope: AnsichEnvironmentScope;
  taskId: string;
  locale: string;
}) {
  const { t } = useI18n();
  const scopeBadge = environmentScopeBadge(scope.environment_scope);
  const coverageTone = coverageBadge(scope.coverage);

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle>{scope.display_label}</CardTitle>
          <div className="flex flex-wrap items-center gap-2">
            <ToneBadge badge={scopeBadge} />
            <ToneBadge badge={coverageTone} />
          </div>
        </div>
        <div className="text-muted-foreground text-xs">{scope.provider}</div>
      </CardHeader>
      <CardContent className="space-y-4">
        {scope.environment_scope === "process_group" ? (
          <p className="text-muted-foreground text-xs">
            {t.ansich.environmentProcessGroupNote}
          </p>
        ) : null}

        <div className="space-y-2">
          <div className="text-muted-foreground text-xs font-medium">
            {t.ansich.environmentMetrics}
          </div>
          {scope.metrics.length ? (
            scope.metrics.map((metric) => (
              <MetricRow
                key={metric.metric}
                metric={metric}
                scopeId={scope.scope_id}
                environmentScope={scope.environment_scope}
                // A trend curve is only meaningful where the collector runs
                // continuously; per_command rows are one command's own window
                // and get their own sequence section below instead.
                trendEnabled={scope.coverage === "continuous"}
                locale={locale}
              />
            ))
          ) : (
            <div className="text-muted-foreground text-sm">
              {t.ansich.evidenceInsufficient}
            </div>
          )}
        </div>

        {scope.coverage === "per_command" ? (
          <PerCommandTrends taskId={taskId} />
        ) : null}

        <div className="space-y-2">
          <div className="text-muted-foreground text-xs font-medium">
            {t.ansich.environmentBeliefs}
          </div>
          {scope.beliefs.length ? (
            scope.beliefs.map((belief) => (
              <BeliefRow key={belief.field_name} belief={belief} />
            ))
          ) : (
            <div className="text-muted-foreground text-sm">
              {t.ansich.evidenceInsufficient}
            </div>
          )}
        </div>

        {scope.alerts.length ? (
          <div className="space-y-2">
            <div className="text-muted-foreground text-xs font-medium">
              {t.ansich.alerts}
            </div>
            {scope.alerts.map((alert) => (
              <AlertRow key={alert.alert_id} alert={alert} locale={locale} />
            ))}
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

function MetricRow({
  metric,
  scopeId,
  environmentScope,
  trendEnabled,
  locale,
}: {
  metric: AnsichEnvironmentMetric;
  scopeId: string;
  environmentScope: string;
  trendEnabled: boolean;
  locale: string;
}) {
  const { t } = useI18n();
  const ratio =
    metric.limit !== null && metric.limit > 0
      ? Math.round((metric.latest_value / metric.limit) * 100)
      : null;
  return (
    <div className="rounded-lg border p-3 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-mono text-xs">{metric.metric}</span>
        <span className="flex items-center gap-3">
          {trendEnabled ? (
            <MetricTrend
              scopeId={scopeId}
              environmentScope={environmentScope}
              metric={metric.metric}
            />
          ) : null}
          <span className="tabular-nums">
            {formatMetricValue(metric.metric, metric.latest_value)}
            {metric.limit !== null
              ? ` / ${formatMetricValue(metric.metric, metric.limit)}${
                  ratio !== null ? ` (${ratio}%)` : ""
                }`
              : ""}
          </span>
        </span>
      </div>
      <div className="text-muted-foreground mt-1 text-xs">
        {t.ansich.asOf}: {formatAnsichTimestamp(metric.as_of, locale)}
      </div>
    </div>
  );
}

/**
 * One metric's 60-minute curve, loaded lazily beside its current value.
 *
 * Fails quiet: a failed or empty history leaves the row exactly as it was
 * before this addition. A one-point series renders nothing too — a single
 * reading drawn as a "curve" is noise, not a trend.
 */
function MetricTrend({
  scopeId,
  environmentScope,
  metric,
}: {
  scopeId: string;
  environmentScope: string;
  metric: string;
}) {
  const { t } = useI18n();
  const query = useAnsichEnvironmentHistory(
    scopeId,
    environmentScope,
    metric,
    TREND_WINDOW_MINUTES,
  );

  if (query.isPending) {
    return <Skeleton className="h-7 w-[120px]" />;
  }
  if (query.error || !query.data) return null;

  const points = query.data.points.map((point) => ({
    ts: new Date(point.occurred_at).getTime(),
    value: point.value,
  }));
  if (points.length < 2) return null;
  // Every sample carries its own limit; the newest one is the reference the
  // current value is judged against, and an absent limit draws no line.
  const limit = query.data.points[query.data.points.length - 1]?.limit ?? null;
  const first = points[0]!.value;
  const last = points[points.length - 1]!.value;
  const title = [
    `${metric} · ${t.ansich.environmentTrend}`,
    `${points.length} · ${formatMetricValue(metric, first)} → ${formatMetricValue(metric, last)}`,
    query.data.truncated ? t.ansich.environmentTrendTruncated : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return <AnsichSparkline points={points} limit={limit} title={title} />;
}

/**
 * The local sandbox's per-command sequence: one point per finished command.
 *
 * The x axis is command order, not wall-clock time — these samples describe
 * each command's own window, so spacing them by timestamp would suggest a
 * continuous measurement that was never taken.
 */
function PerCommandTrends({ taskId }: { taskId: string }) {
  const { t } = useI18n();
  const query = useAnsichTaskToolEnvSamples(taskId);

  if (query.isPending) {
    return <Skeleton className="h-20 w-full" />;
  }
  if (query.error || !query.data) return null;

  const samples = query.data.samples;
  if (samples.length < 2) return null;

  const series: { metric: string; values: (number | null)[] }[] = [
    { metric: "fd_peak", values: samples.map((item) => item.fd_peak) },
    {
      metric: "io_read_bytes",
      values: samples.map((item) => item.io_read_bytes),
    },
    {
      metric: "io_write_bytes",
      values: samples.map((item) => item.io_write_bytes),
    },
  ];

  return (
    <div className="space-y-2">
      <div className="text-muted-foreground text-xs font-medium">
        {t.ansich.environmentPerCommand}
      </div>
      <p className="text-muted-foreground text-xs">
        {t.ansich.environmentPerCommandOrderNote}
      </p>
      {series.map(({ metric, values }) => (
        <PerCommandRow key={metric} metric={metric} values={values} />
      ))}
    </div>
  );
}

function PerCommandRow({
  metric,
  values,
}: {
  metric: string;
  values: (number | null)[];
}) {
  // A command whose sampler reported nothing for this counter is dropped, not
  // read as 0 — missing is not zero. Its ordinal is preserved as the x value
  // so the surrounding commands do not silently close the gap.
  const points = values
    .map((value, index) => ({ ts: index, value }))
    .filter(
      (point): point is { ts: number; value: number } => point.value !== null,
    );
  if (points.length < 2) return null;
  const last = points[points.length - 1]!.value;
  const title = `${metric} · ${points.length} · ${formatMetricValue(metric, last)}`;

  return (
    <div className="flex items-center justify-between gap-3 rounded-lg border p-3 text-sm">
      <span className="font-mono text-xs">{metric}</span>
      <span className="flex items-center gap-3">
        <AnsichSparkline points={points} title={title} />
        <span className="tabular-nums">{formatMetricValue(metric, last)}</span>
      </span>
    </div>
  );
}

function BeliefRow({ belief }: { belief: AnsichEnvironmentBelief }) {
  const rawValue =
    typeof belief.value.value === "string" ? belief.value.value : "unknown";
  const badge = environmentBeliefBadge(belief.field_name, rawValue);
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border p-3 text-sm">
      <span className="font-mono text-xs">{belief.field_name}</span>
      <ToneBadge badge={badge} />
    </div>
  );
}

function AlertRow({
  alert,
  locale,
}: {
  alert: AnsichEnvironmentAlertSummary;
  locale: string;
}) {
  const { t } = useI18n();
  const typeLabel =
    t.ansich.alertTypeLabel[alert.alert_type as AnsichAlertType] ??
    alert.alert_type;
  // Rendered only from the backend's own recorded set — never derived from
  // evidence Observations, whose task_id only names the one Task that
  // happened to record a given sample, not the full running set. Absent/null
  // means the read model never recorded one: render nothing, no fallback.
  const affected = alert.possibly_affected_task_ids;
  return (
    <div className="space-y-2 rounded-lg border p-3 text-sm">
      <Link
        href="/workspace/ansich/operations"
        className="hover:text-accent-foreground flex flex-wrap items-center justify-between gap-2 transition-colors"
      >
        <span>{typeLabel}</span>
        <span className="text-muted-foreground flex items-center gap-2 text-xs">
          <Badge
            variant={
              alert.severity === "critical" ? "destructive" : "secondary"
            }
          >
            {t.ansich.alertSeverity[
              alert.severity as "info" | "warning" | "critical"
            ] ?? alert.severity}
          </Badge>
          {formatAnsichTimestamp(alert.opened_at, locale)}
        </span>
      </Link>
      {affected?.length ? (
        <div className="space-y-1">
          <div className="text-muted-foreground text-xs">
            {t.ansich.environmentPossiblyAffectedTitle}
          </div>
          <div className="flex flex-wrap gap-1">
            {affected.map((taskId) => (
              <Link
                key={taskId}
                href={`/workspace/ansich/tasks/${encodeURIComponent(taskId)}`}
              >
                <Badge variant="outline" className="font-mono">
                  {taskId}
                </Badge>
              </Link>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}
