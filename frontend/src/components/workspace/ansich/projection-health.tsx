"use client";

import { ActivityIcon, AlertTriangleIcon } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  isProjectionAttention,
  countLostObservations,
} from "@/core/ansich/presentation";
import type { AnsichHealth } from "@/core/ansich/types";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

import { AnsichSystemHealthDrawer } from "./system-health-drawer";

function formatLag(lagMs: number): string {
  if (lagMs < 1000) return `${lagMs}ms`;
  return `${(lagMs / 1000).toFixed(1)}s`;
}

/**
 * Projection health at L0 (IA §5.2): a compact "Data healthy · lag 1.2s"
 * status line by default, promoted to a page-level banner when attention is
 * warranted. The full metric wall lives in the System details drawer and never
 * competes with task cards at page top.
 */
export function AnsichProjectionHealth({
  health,
  taskId,
}: {
  health: AnsichHealth;
  taskId?: string;
}) {
  const { t } = useI18n();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const attention = isProjectionAttention(health);
  const lostCount = countLostObservations(health.lost_ranges);

  return (
    <>
      {attention ? (
        <div
          role="status"
          className="border-amber-500/40 bg-amber-500/10 flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg border p-3 text-sm"
        >
          <div className="flex items-center gap-2 font-medium text-amber-700 dark:text-amber-300">
            <AlertTriangleIcon className="size-4" />
            {t.ansich.projection}: {t.ansich.health[health.status]}
          </div>
          <div className="text-muted-foreground flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
            {health.failed_jobs > 0 ? (
              <span className="text-destructive font-medium">
                {t.ansich.failedJobs}: {health.failed_jobs}
              </span>
            ) : null}
            {lostCount > 0 ? (
              <span>
                {t.ansich.lost}: {lostCount}
              </span>
            ) : null}
            {!health.storage_available ? (
              <span className="text-destructive font-medium">
                {t.ansich.health.stopped}
              </span>
            ) : null}
            <span>
              {t.ansich.lag} {formatLag(health.lag_ms)}
            </span>
          </div>
          <Button
            variant="outline"
            size="sm"
            className="ms-auto"
            onClick={() => setDrawerOpen(true)}
          >
            {t.ansich.systemDetails}
          </Button>
        </div>
      ) : (
        <div className="text-muted-foreground flex items-center gap-2 text-sm">
          <ActivityIcon className="size-4 text-emerald-600" />
          <span className={cn("text-foreground font-medium")}>
            {t.ansich.dataHealthy}
          </span>
          <span aria-hidden>·</span>
          <span className="tabular-nums">
            {t.ansich.lag} {formatLag(health.lag_ms)}
          </span>
          <Button
            variant="ghost"
            size="sm"
            className="text-muted-foreground ms-1 h-auto px-1.5 py-0.5"
            onClick={() => setDrawerOpen(true)}
          >
            {t.ansich.systemDetails}
          </Button>
        </div>
      )}
      <AnsichSystemHealthDrawer
        health={health}
        taskId={taskId}
        open={drawerOpen}
        onOpenChange={setDrawerOpen}
      />
    </>
  );
}
