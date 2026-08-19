"use client";

import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useAnsichTaskEnvironment } from "@/core/ansich/hooks";
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

import { formatBytes } from "./system-health-drawer";

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
  return metric.endsWith("_bytes") ? formatBytes(value) : value.toLocaleString();
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
          locale={locale}
        />
      ))}
    </div>
  );
}

function EnvironmentScopeCard({
  scope,
  locale,
}: {
  scope: AnsichEnvironmentScope;
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
              <MetricRow key={metric.metric} metric={metric} locale={locale} />
            ))
          ) : (
            <div className="text-muted-foreground text-sm">
              {t.ansich.evidenceInsufficient}
            </div>
          )}
        </div>

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
  locale,
}: {
  metric: AnsichEnvironmentMetric;
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
        <span className="tabular-nums">
          {formatMetricValue(metric.metric, metric.latest_value)}
          {metric.limit !== null
            ? ` / ${formatMetricValue(metric.metric, metric.limit)}${
                ratio !== null ? ` (${ratio}%)` : ""
              }`
            : ""}
        </span>
      </div>
      <div className="text-muted-foreground mt-1 text-xs">
        {t.ansich.asOf}: {formatAnsichTimestamp(metric.as_of, locale)}
      </div>
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
  return (
    <Link
      href="/workspace/ansich/operations"
      className="hover:bg-accent/40 flex flex-wrap items-center justify-between gap-2 rounded-lg border p-3 text-sm transition-colors"
    >
      <span>{typeLabel}</span>
      <span className="text-muted-foreground flex items-center gap-2 text-xs">
        <Badge
          variant={alert.severity === "critical" ? "destructive" : "secondary"}
        >
          {t.ansich.alertSeverity[
            alert.severity as "info" | "warning" | "critical"
          ] ?? alert.severity}
        </Badge>
        {formatAnsichTimestamp(alert.opened_at, locale)}
      </span>
    </Link>
  );
}
