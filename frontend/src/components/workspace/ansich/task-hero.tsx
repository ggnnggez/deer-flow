"use client";

import type { ReactNode } from "react";

import { formatDuration } from "@/core/ansich/presentation";
import type { AnsichPrimarySignal } from "@/core/ansich/presentation";
import type { AnsichTask } from "@/core/ansich/types";
import { useI18n } from "@/core/i18n/hooks";

import { AnsichShortId } from "./short-id";
import { AnsichSignalBadge } from "./signal-badge";
import { AnsichStatusBadge } from "./status-badge";
import { AnsichTechnicalEvidence } from "./technical-evidence";

/**
 * Sticky Task header (IA §6.1): a human-recognizable actor/source plus short id,
 * control + duration, child count and the highest-priority open signal on the
 * first line; full UUID/source_id/thread/owner move into Technical details.
 */
export function AnsichTaskHero({
  task,
  actor,
  durationMs,
  childCount,
  primarySignal,
  technicalDetails,
  actions,
}: {
  task: AnsichTask;
  actor: string | null;
  durationMs: number | null;
  childCount: number | null;
  primarySignal: AnsichPrimarySignal | null;
  technicalDetails?: ReactNode;
  actions?: ReactNode;
}) {
  const { t } = useI18n();

  return (
    <header className="bg-background/95 supports-[backdrop-filter]:bg-background/80 sticky top-0 z-10 space-y-3 border-b pb-4 backdrop-blur">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="truncate text-lg font-semibold">
              {actor ?? task.source_kind}
            </h1>
            <span className="text-muted-foreground text-sm">
              {task.source_kind}
            </span>
            <AnsichShortId value={task.task_id} label={t.ansich.task} />
          </div>
          <div className="text-muted-foreground flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
            {childCount ? (
              <span>{t.ansich.childTasksCount(childCount.toLocaleString())}</span>
            ) : null}
            {durationMs !== null ? (
              <span className="tabular-nums">{formatDuration(durationMs)}</span>
            ) : null}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <AnsichStatusBadge value={task.control.value} />
          <AnsichSignalBadge signal={primarySignal} />
          {actions}
        </div>
      </div>
      {technicalDetails ? (
        <AnsichTechnicalEvidence label={t.ansich.technicalDetails}>
          {technicalDetails}
        </AnsichTechnicalEvidence>
      ) : null}
    </header>
  );
}
