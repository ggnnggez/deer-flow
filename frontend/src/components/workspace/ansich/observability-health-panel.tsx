"use client";

import { AlertTriangleIcon, CircleHelpIcon, DatabaseIcon } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  ANSICH_UNKNOWN_VALUE,
  formatAnsichCount,
  getDatabaseHealthPresentation,
  type AnsichProjectorRow,
} from "@/core/ansich/presentation";
import type { AnsichHealthResponse } from "@/core/ansich/types";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

function formatLag(lagMs: number | null): string {
  if (lagMs === null) return ANSICH_UNKNOWN_VALUE;
  if (lagMs < 1000) return `${lagMs} ms`;
  return `${(lagMs / 1000).toFixed(1)} s`;
}

/**
 * Operations' database/projection view (RB11②).
 *
 * The boundary with `AnsichSystemHealthDrawer` is deliberate and is the reason
 * this is a second component rather than more rows in that one: the drawer is
 * the **process/collection wall** — this worker's queue, its writer, its
 * producer ledger, its own advisory failed-job count — while this panel is the
 * **store's** answer, read live across every worker from the job tables. Under
 * several Gateway workers the two legitimately disagree, and merging them would
 * turn one worker's private view into a claim about the system.
 *
 * Two wordings this panel owes the reader. `complete_through` is a *continuity*
 * mark — nothing below it is still owed — so it is labelled "settled through"
 * and never as progress; it reads lower than a per-worker progress number
 * whenever anything is outstanding, and that is the correction, not a
 * regression. And the database failed-job count is authoritative across workers
 * while the process one is this worker's own sighting, so the two are never
 * given the same label.
 */
export function AnsichObservabilityHealthPanel({
  health,
  isPending,
}: {
  health: AnsichHealthResponse | undefined;
  isPending: boolean;
}) {
  const { t } = useI18n();
  const copy = t.ansich.observabilityHealth;

  if (isPending || !health) {
    return (
      <section
        aria-labelledby="ansich-observability-health-title"
        className="space-y-3"
      >
        <h2 id="ansich-observability-health-title" className="sr-only">
          {copy.title}
        </h2>
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-40 w-full" />
      </section>
    );
  }

  const database = getDatabaseHealthPresentation(health.database);

  return (
    <section
      aria-labelledby="ansich-observability-health-title"
      className="space-y-4"
    >
      <div className="flex flex-wrap items-center gap-2">
        <h2
          id="ansich-observability-health-title"
          className="flex items-center gap-2 text-base font-semibold"
        >
          <DatabaseIcon className="size-4" aria-hidden />
          {copy.title}
        </h2>
        <Badge
          variant="outline"
          className={cn(
            database.reachable
              ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
              : "border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-300",
          )}
        >
          {database.reachable ? copy.reachable : copy.unreachable}
        </Badge>
      </div>
      <p className="text-muted-foreground text-sm">{copy.description}</p>

      {!database.reachable ? (
        <div
          role="status"
          className="flex items-start gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-amber-700 dark:text-amber-300"
        >
          <AlertTriangleIcon className="mt-0.5 size-4 shrink-0" aria-hidden />
          <span>{copy.unreachableNote}</span>
        </div>
      ) : null}

      <div className="grid gap-3 rounded-lg border p-4 sm:grid-cols-2 lg:grid-cols-4">
        <Metric
          label={copy.databaseLag}
          value={formatLag(database.lagMs)}
          description={copy.metricDescriptions.databaseLag}
          unknown={database.lagMs === null}
        />
        <Metric
          label={copy.databaseFailedJobs}
          value={formatAnsichCount(database.failedJobs)}
          description={copy.metricDescriptions.databaseFailedJobs}
          unknown={database.failedJobs === null}
          tone={
            database.failedJobs !== null && database.failedJobs > 0
              ? "attention"
              : "normal"
          }
        />
        <Metric
          label={copy.settledThrough}
          value={formatAnsichCount(database.settledThrough)}
          description={copy.metricDescriptions.settledThrough}
          unknown={database.settledThrough === null}
        />
        <Metric
          label={copy.outstanding}
          value={formatAnsichCount(database.outstanding)}
          description={copy.metricDescriptions.outstanding}
          unknown={database.outstanding === null}
        />
      </div>

      <div className="rounded-lg border">
        <div className="flex flex-wrap items-center gap-2 border-b px-4 py-3">
          <h3 className="text-sm font-medium">{copy.projectors}</h3>
          <MetricHelp description={copy.metricDescriptions.projectors} />
        </div>
        {database.projectors.length === 0 ? (
          <p className="text-muted-foreground p-4 text-sm">
            {database.reachable ? copy.projectorsEmpty : copy.projectorsUnknown}
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-muted-foreground text-xs">
                <tr>
                  <th className="px-4 py-2 font-medium">{copy.projector}</th>
                  <th className="px-4 py-2 font-medium">{copy.pending}</th>
                  <th className="px-4 py-2 font-medium">{copy.retry}</th>
                  <th className="px-4 py-2 font-medium">{copy.processing}</th>
                  <th className="px-4 py-2 font-medium">{copy.failed}</th>
                  <th className="px-4 py-2 font-medium">
                    <span className="flex items-center gap-1">
                      {copy.settledThrough}
                      <MetricHelp
                        description={copy.metricDescriptions.settledThrough}
                      />
                    </span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {database.projectors.map((row) => (
                  <ProjectorRow key={row.key} row={row} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* The process half stays readable when the store is not — mirroring the
          endpoint, which answers with the process block either way. It is
          labelled as this worker's own view so it is never mistaken for the
          authoritative numbers above. */}
      <div className="grid gap-3 rounded-lg border p-4 sm:grid-cols-2 lg:grid-cols-4">
        <div className="text-muted-foreground col-span-full text-xs font-medium uppercase">
          {copy.processSection}
        </div>
        <Metric
          label={copy.collectorStatus}
          value={t.ansich.health[health.status]}
          description={copy.metricDescriptions.collectorStatus}
        />
        <Metric
          label={copy.processFailedJobs}
          value={formatAnsichCount(health.failed_jobs)}
          description={copy.metricDescriptions.processFailedJobs}
        />
        <Metric
          label={copy.processLag}
          value={formatLag(health.lag_ms)}
          description={copy.metricDescriptions.processLag}
        />
        <Metric
          label={copy.staleCompletions}
          value={formatAnsichCount(database.staleCompletions)}
          description={copy.metricDescriptions.staleCompletions}
          unknown={database.staleCompletions === null}
        />
      </div>
    </section>
  );
}

function ProjectorRow({ row }: { row: AnsichProjectorRow }) {
  return (
    <tr className="border-t">
      <td className="px-4 py-2">
        <div className="font-mono text-xs font-medium">{row.name}</div>
        <div className="text-muted-foreground font-mono text-xs">
          @{row.version}
        </div>
      </td>
      <td className="px-4 py-2 font-mono tabular-nums">
        {formatAnsichCount(row.pending)}
      </td>
      <td className="px-4 py-2 font-mono tabular-nums">
        {formatAnsichCount(row.retry)}
      </td>
      <td className="px-4 py-2 font-mono tabular-nums">
        {formatAnsichCount(row.processing)}
      </td>
      <td
        className={cn(
          "px-4 py-2 font-mono tabular-nums",
          row.attention && "text-destructive font-medium",
        )}
      >
        {formatAnsichCount(row.failed)}
      </td>
      <td className="px-4 py-2 font-mono tabular-nums">
        {formatAnsichCount(row.completeThrough)}
      </td>
    </tr>
  );
}

function Metric({
  label,
  value,
  description,
  unknown = false,
  tone = "normal",
}: {
  label: string;
  value: string;
  description: string;
  unknown?: boolean;
  tone?: "normal" | "attention";
}) {
  return (
    <div className="flex flex-col gap-0.5 text-sm">
      <span className="text-muted-foreground flex items-center gap-1 text-xs">
        {label}
        <MetricHelp description={description} />
      </span>
      <span
        className={cn(
          "font-mono font-medium tabular-nums",
          unknown && "text-muted-foreground",
          tone === "attention" && "text-destructive",
        )}
      >
        {value}
      </span>
    </div>
  );
}

function MetricHelp({ description }: { description: string }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          aria-label={description}
          className="hover:text-foreground focus-visible:ring-ring rounded-sm outline-none focus-visible:ring-2"
        >
          <CircleHelpIcon className="size-3.5" aria-hidden />
        </button>
      </TooltipTrigger>
      <TooltipContent className="max-w-72">{description}</TooltipContent>
    </Tooltip>
  );
}
