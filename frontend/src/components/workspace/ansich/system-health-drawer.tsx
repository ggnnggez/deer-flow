"use client";

import { useState } from "react";

import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import {
  countLostObservations,
  formatAnsichLag,
  formatAnsichTimestamp,
  shortId,
  topProducersByDropped,
} from "@/core/ansich/presentation";
import type { AnsichHealth } from "@/core/ansich/types";
import { useI18n } from "@/core/i18n/hooks";

import { AnsichFailedJobsDialog } from "./failed-jobs-dialog";
import { AnsichMetricHelp } from "./metric-help";

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
 *
 * Everything here is the **process/collection wall**: one worker's queue, its
 * writer, its producer ledger, and its own advisory failed-job count. The
 * store's answer — per-projector job buckets, the continuity mark, the
 * authoritative failed-job count read live across every worker — belongs to
 * `AnsichObservabilityHealthPanel` (RB11③) and is deliberately not merged in
 * here: under several Gateway workers the two views legitimately disagree, and
 * one worker's private numbers must not be dressed up as the system's.
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
  const { t, locale } = useI18n();
  const lostCount = countLostObservations(health.lost_ranges);
  const producers = topProducersByDropped(health.producers);
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
          <div className="grid grid-cols-2 gap-x-6 gap-y-3 px-4">
            <HealthMetric
              label={t.ansich.queue}
              value={`${health.queue_depth}/${health.queue_capacity}`}
              description={t.ansich.systemMetricDescriptions.queue}
            />
            <HealthMetric
              label={t.ansich.queueHighWatermark}
              value={String(health.queue_high_watermark)}
              description={t.ansich.systemMetricDescriptions.queueHighWatermark}
            />
            <HealthMetric
              label={t.ansich.queueBytes}
              value={`${formatBytes(health.queue_bytes)}/${formatBytes(health.queue_byte_capacity)}`}
              description={t.ansich.systemMetricDescriptions.queueBytes}
            />
            <HealthMetric
              label={t.ansich.queueByteHighWatermark}
              value={formatBytes(health.queue_byte_high_watermark)}
              description={
                t.ansich.systemMetricDescriptions.queueByteHighWatermark
              }
            />
            <HealthMetric
              label={t.ansich.watermark}
              value={health.watermark === null ? "—" : String(health.watermark)}
              description={t.ansich.systemMetricDescriptions.watermark}
            />
            <HealthMetric
              label={t.ansich.lag}
              value={formatAnsichLag(health.lag_ms)}
              description={t.ansich.systemMetricDescriptions.lag}
            />
            <div className="flex flex-col gap-0.5 text-sm">
              <span className="text-muted-foreground flex items-center gap-1 text-xs">
                {t.ansich.failedJobs}
                <AnsichMetricHelp
                  description={t.ansich.systemMetricDescriptions.failedJobs}
                />
              </span>
              <button
                type="button"
                onClick={() => setFailedJobsOpen(true)}
                disabled={health.failed_jobs === 0}
                className={
                  health.failed_jobs > 0
                    ? "text-destructive w-fit font-mono font-medium tabular-nums underline"
                    : "w-fit cursor-default font-mono font-medium tabular-nums"
                }
              >
                {health.failed_jobs}
              </button>
            </div>
            <HealthMetric
              label={t.ansich.accepted}
              value={String(health.accepted_count)}
              description={t.ansich.systemMetricDescriptions.accepted}
            />
            <HealthMetric
              label={t.ansich.dropped}
              value={String(health.dropped_count)}
              description={t.ansich.systemMetricDescriptions.dropped}
            />
            <HealthMetric
              label={t.ansich.lost}
              value={String(lostCount)}
              description={t.ansich.systemMetricDescriptions.lost}
            />
            <HealthMetric
              label={t.ansich.unreportedGlobalLoss}
              value={String(health.unreported_global_lost_range_count)}
              description={
                t.ansich.systemMetricDescriptions.unreportedGlobalLoss
              }
            />
            <HealthMetric
              label={t.ansich.snapshotRequests}
              value={`${health.snapshot_request_count} (${health.snapshot_observations_accepted}/${health.snapshot_observations_dropped})`}
              description={t.ansich.systemMetricDescriptions.snapshotRequests}
            />
            <HealthMetric
              label={t.ansich.snapshotItems}
              value={String(health.snapshot_item_count)}
              description={t.ansich.systemMetricDescriptions.snapshotItems}
            />
            <HealthMetric
              label={t.ansich.incompleteSnapshots}
              value={String(health.incomplete_snapshot_count)}
              description={
                t.ansich.systemMetricDescriptions.incompleteSnapshots
              }
            />
            <HealthMetric
              label={t.ansich.missingBlocks}
              value={String(health.missing_content_block_count)}
              description={t.ansich.systemMetricDescriptions.missingBlocks}
            />
          </div>
          <div className="px-4 pt-5">
            <div className="text-muted-foreground text-xs font-medium uppercase">
              {t.ansich.writer}
            </div>
            <div className="mt-2 grid grid-cols-2 gap-x-6 gap-y-3">
              <HealthMetric
                label={t.ansich.writerConsecutiveFailures}
                value={String(health.writer.consecutive_failures)}
                description={
                  t.ansich.systemMetricDescriptions.writerConsecutiveFailures
                }
              />
              <HealthMetric
                label={t.ansich.writerBackoffUntil}
                value={formatAnsichTimestamp(
                  health.writer.backoff_until,
                  locale,
                )}
                description={
                  t.ansich.systemMetricDescriptions.writerBackoffUntil
                }
              />
              <HealthMetric
                label={t.ansich.rowsInFlight}
                value={String(health.writer.in_flight_count)}
                description={t.ansich.systemMetricDescriptions.rowsInFlight}
              />
              <HealthMetric
                label={t.ansich.isolatedDrops}
                value={String(health.writer.poison_observation_count)}
                description={t.ansich.systemMetricDescriptions.isolatedDrops}
              />
            </div>
          </div>
          <div className="px-4 pt-5 pb-6">
            <div className="text-muted-foreground flex items-center gap-1 text-xs font-medium uppercase">
              {t.ansich.producers}
              <AnsichMetricHelp
                description={t.ansich.systemMetricDescriptions.producers}
              />
            </div>
            {producers.rows.length === 0 ? (
              <p className="text-muted-foreground mt-2 text-xs">
                {t.ansich.producersEmpty}
              </p>
            ) : (
              <div className="mt-2 overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead className="text-muted-foreground">
                    <tr>
                      <th className="p-2">{t.ansich.producer}</th>
                      <th className="p-2">{t.ansich.accepted}</th>
                      <th className="p-2">{t.ansich.dropped}</th>
                      <th className="p-2">{t.ansich.serializationFailures}</th>
                      <th className="p-2">{t.ansich.lastSuccessfulFlush}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {producers.rows.map((producer) => (
                      <tr
                        key={`${producer.producer_name}:${producer.producer_instance_id}`}
                        className="border-t"
                      >
                        <td className="p-2">
                          <div className="font-mono">
                            {producer.producer_name}
                          </div>
                          <div
                            className="text-muted-foreground font-mono"
                            title={producer.producer_instance_id}
                          >
                            {shortId(producer.producer_instance_id)}
                          </div>
                        </td>
                        <td className="p-2 font-mono tabular-nums">
                          {producer.accepted_count}
                        </td>
                        <td
                          className={
                            producer.dropped_count > 0
                              ? "text-destructive p-2 font-mono font-medium tabular-nums"
                              : "p-2 font-mono tabular-nums"
                          }
                        >
                          {producer.dropped_count}
                        </td>
                        <td className="p-2 font-mono tabular-nums">
                          {producer.serialization_failures}
                        </td>
                        <td className="p-2">
                          {formatAnsichTimestamp(
                            producer.last_successful_flush_at,
                            locale,
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {producers.hiddenCount > 0 ? (
              <p className="text-muted-foreground mt-2 text-xs">
                {t.ansich.producersMore(producers.hiddenCount.toLocaleString())}
              </p>
            ) : null}
            <div className="mt-3">
              <HealthMetric
                label={t.ansich.producerEvictions}
                value={String(health.evicted_producer_count)}
                description={
                  t.ansich.systemMetricDescriptions.producerEvictions
                }
              />
            </div>
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

function HealthMetric({
  label,
  value,
  description,
}: {
  label: string;
  value: string;
  description?: string;
}) {
  return (
    <div className="flex flex-col gap-0.5 text-sm">
      <span className="text-muted-foreground flex items-center gap-1 text-xs">
        {label}
        {description ? <AnsichMetricHelp description={description} /> : null}
      </span>
      <span className="font-mono font-medium tabular-nums">{value}</span>
    </div>
  );
}
