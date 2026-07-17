import { ActivityIcon, AlertTriangleIcon } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { countLostObservations } from "@/core/ansich/presentation";
import type { AnsichHealth } from "@/core/ansich/types";
import { useI18n } from "@/core/i18n/hooks";

export function AnsichProjectionHealth({ health }: { health: AnsichHealth }) {
  const { t } = useI18n();
  const lostCount = countLostObservations(health.lost_ranges);
  const unhealthy = health.status !== "healthy";

  return (
    <Card className="gap-0 py-4">
      <CardContent className="flex flex-wrap items-center gap-x-6 gap-y-3 px-4 sm:px-6">
        <div className="flex items-center gap-2">
          {unhealthy ? (
            <AlertTriangleIcon className="size-4 text-amber-600" />
          ) : (
            <ActivityIcon className="size-4 text-emerald-600" />
          )}
          <span className="font-medium">{t.ansich.projection}</span>
          <Badge variant={unhealthy ? "outline" : "secondary"}>
            {t.ansich.health[health.status]}
          </Badge>
        </div>
        <HealthMetric
          label={t.ansich.queue}
          value={`${health.queue_depth}/${health.queue_capacity}`}
        />
        <HealthMetric
          label={t.ansich.watermark}
          value={health.watermark === null ? "—" : String(health.watermark)}
        />
        <HealthMetric label={t.ansich.lag} value={`${health.lag_ms} ms`} />
        <HealthMetric
          label={t.ansich.failedJobs}
          value={String(health.failed_jobs)}
        />
        <HealthMetric
          label={t.ansich.accepted}
          value={String(health.accepted_count)}
        />
        <HealthMetric
          label={t.ansich.dropped}
          value={String(health.dropped_count)}
        />
        <HealthMetric label={t.ansich.lost} value={String(lostCount)} />
      </CardContent>
    </Card>
  );
}

function HealthMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline gap-2 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-mono font-medium tabular-nums">{value}</span>
    </div>
  );
}
