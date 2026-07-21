"use client";

import { useState } from "react";

import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { countLostObservations } from "@/core/ansich/presentation";
import type { AnsichHealth } from "@/core/ansich/types";
import { useI18n } from "@/core/i18n/hooks";

import { AnsichFailedJobsDialog } from "./failed-jobs-dialog";

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KiB", "MiB", "GiB"];
  let value = bytes / 1024;
  let unit = units[0];
  for (let index = 1; index < units.length && value >= 1024; index += 1) {
    value /= 1024;
    unit = units[index];
  }
  return `${value >= 10 || Number.isInteger(value) ? value.toFixed(0) : value.toFixed(1)} ${unit}`;
}

/**
 * Full projection-health metric wall (IA §5.2): the complete queue, watermark,
 * snapshot and failed-job detail lives here behind an explicit "System details"
 * drawer instead of tiling every metric at page top.
 */
export function AnsichSystemHealthDrawer({
  health,
  taskId,
  open,
  onOpenChange,
}: {
  health: AnsichHealth;
  taskId?: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useI18n();
  const lostCount = countLostObservations(health.lost_ranges);
  const [failedJobsOpen, setFailedJobsOpen] = useState(false);

  return (
    <>
      <Sheet open={open} onOpenChange={onOpenChange}>
        <SheetContent className="w-full gap-0 overflow-y-auto sm:max-w-md">
          <SheetHeader>
            <SheetTitle>{t.ansich.systemDetails}</SheetTitle>
            <SheetDescription>
              {t.ansich.projection} · {t.ansich.health[health.status]}
            </SheetDescription>
          </SheetHeader>
          <div className="grid grid-cols-2 gap-x-6 gap-y-3 px-4 pb-6">
            <HealthMetric
              label={t.ansich.queue}
              value={`${health.queue_depth}/${health.queue_capacity}`}
            />
            <HealthMetric
              label={t.ansich.queueHighWatermark}
              value={String(health.queue_high_watermark)}
            />
            <HealthMetric
              label={t.ansich.queueBytes}
              value={`${formatBytes(health.queue_bytes)}/${formatBytes(health.queue_byte_capacity)}`}
            />
            <HealthMetric
              label={t.ansich.queueByteHighWatermark}
              value={formatBytes(health.queue_byte_high_watermark)}
            />
            <HealthMetric
              label={t.ansich.watermark}
              value={
                health.watermark === null ? "—" : String(health.watermark)
              }
            />
            <HealthMetric label={t.ansich.lag} value={`${health.lag_ms} ms`} />
            <button
              type="button"
              onClick={() => setFailedJobsOpen(true)}
              disabled={health.failed_jobs === 0}
              className="flex items-baseline gap-2 text-left text-sm disabled:cursor-default"
            >
              <span className="text-muted-foreground">
                {t.ansich.failedJobs}
              </span>
              <span
                className={
                  health.failed_jobs > 0
                    ? "text-destructive font-mono font-medium tabular-nums underline"
                    : "font-mono font-medium tabular-nums"
                }
              >
                {health.failed_jobs}
              </span>
            </button>
            <HealthMetric
              label={t.ansich.accepted}
              value={String(health.accepted_count)}
            />
            <HealthMetric
              label={t.ansich.dropped}
              value={String(health.dropped_count)}
            />
            <HealthMetric label={t.ansich.lost} value={String(lostCount)} />
            <HealthMetric
              label={t.ansich.snapshotRequests}
              value={`${health.snapshot_request_count} (${health.snapshot_observations_accepted}/${health.snapshot_observations_dropped})`}
            />
            <HealthMetric
              label={t.ansich.snapshotItems}
              value={String(health.snapshot_item_count)}
            />
            <HealthMetric
              label={t.ansich.incompleteSnapshots}
              value={String(health.incomplete_snapshot_count)}
            />
            <HealthMetric
              label={t.ansich.missingBlocks}
              value={String(health.missing_content_block_count)}
            />
          </div>
        </SheetContent>
      </Sheet>
      <AnsichFailedJobsDialog
        open={failedJobsOpen}
        onOpenChange={setFailedJobsOpen}
        taskId={taskId}
      />
    </>
  );
}

function HealthMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-0.5 text-sm">
      <span className="text-muted-foreground text-xs">{label}</span>
      <span className="font-mono font-medium tabular-nums">{value}</span>
    </div>
  );
}
