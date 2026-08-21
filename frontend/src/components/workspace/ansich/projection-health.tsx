"use client";

import {
  ActivityIcon,
  AlertTriangleIcon,
  CircleHelpIcon,
  XIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  buildAnsichHealthDismissalKey,
  clearAnsichHealthDismissal,
  getSessionAnsichHealthStorage,
  readAnsichHealthDismissal,
  subscribeAnsichHealthDismissals,
  writeAnsichHealthDismissal,
} from "@/core/ansich/health-dismissal";
import { useAnsichFailedJobs } from "@/core/ansich/hooks";
import {
  formatAnsichLag,
  resolveProjectionHealthDisplay,
  systemProjectionScope,
  taskFailedJobCount,
  taskProjectionScope,
  type AnsichHealthSnapshot,
  type AnsichProjectionHealthLine,
  type AnsichProjectionScope,
} from "@/core/ansich/presentation";
import type { AnsichHealth } from "@/core/ansich/types";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

import { AnsichFailedJobsDialog } from "./failed-jobs-dialog";
import { AnsichSystemHealthDrawer } from "./system-health-drawer";

/**
 * A modest page of one Task's failed jobs — enough to size the warning without
 * pulling the whole failure list into a polled query. A full page is reported
 * as `50+`, never as an exact total the response cannot support.
 */
const TASK_FAILED_JOB_LIMIT = 50;

export interface AnsichProjectionHealthState {
  /** Null until projection health has loaded for this page. */
  scope: AnsichProjectionScope | null;
  /** Which inline line to render; `none` while collapsed behind the badge. */
  line: AnsichProjectionHealthLine;
  /** The banner is collapsed and its badge belongs in the page title row. */
  badgeVisible: boolean;
  dismissible: boolean;
  dismiss: () => void;
  restore: () => void;
}

/**
 * Own one page's health line: which scope it speaks for and whether the
 * operator has collapsed it (IA §5.2). Pages lift this so the badge can live in
 * their title row while the banner stays in its normal slot.
 *
 * Pass `taskId` for a Task-scoped line: it then reports that Task's own failed
 * jobs and lost ranges instead of every Task's, and inherits system state only
 * for a hard failure that makes the Task's own numbers untrustworthy.
 */
export function useAnsichProjectionHealth({
  health,
  taskId,
  enabled = true,
  polling = false,
}: {
  health: AnsichHealth | null | undefined;
  taskId?: string;
  enabled?: boolean;
  polling?: boolean;
}): AnsichProjectionHealthState {
  const failedJobsQuery = useAnsichFailedJobs(
    taskId,
    TASK_FAILED_JOB_LIMIT,
    enabled && Boolean(taskId),
    polling,
  );
  const dismissalKey = buildAnsichHealthDismissalKey(taskId);
  const [dismissed, setDismissed] = useState<AnsichHealthSnapshot | null>(null);

  // Read after mount, not during render: the same page is prerendered on the
  // server, where sessionStorage does not exist.
  useEffect(() => {
    const sync = () =>
      setDismissed(
        readAnsichHealthDismissal(
          getSessionAnsichHealthStorage(),
          dismissalKey,
        ),
      );
    sync();
    return subscribeAnsichHealthDismissals(sync);
  }, [dismissalKey]);

  const taskFailedJobs = taskFailedJobCount(failedJobsQuery);
  const scope = useMemo(() => {
    if (!health) return null;
    return taskId
      ? taskProjectionScope(health, taskId, {
          count: taskFailedJobs,
          // A scope pinned at `50+` cannot re-promote on further growth: past
          // the page limit the count stops moving. Deliberate — the banner is
          // already open at that size, and the drawer holds the real list.
          truncated:
            taskFailedJobs !== null && taskFailedJobs >= TASK_FAILED_JOB_LIMIT,
        })
      : systemProjectionScope(health);
  }, [health, taskFailedJobs, taskId]);

  const display = scope
    ? resolveProjectionHealthDisplay(scope, dismissed)
    : null;
  const clearDismissal = display?.clearDismissal ?? false;

  useEffect(() => {
    if (clearDismissal) {
      clearAnsichHealthDismissal(getSessionAnsichHealthStorage(), dismissalKey);
    }
  }, [clearDismissal, dismissalKey]);

  const snapshot = scope?.snapshot ?? null;
  const dismiss = useCallback(() => {
    if (!snapshot) return;
    writeAnsichHealthDismissal(
      getSessionAnsichHealthStorage(),
      dismissalKey,
      snapshot,
    );
  }, [dismissalKey, snapshot]);

  const restore = useCallback(() => {
    clearAnsichHealthDismissal(getSessionAnsichHealthStorage(), dismissalKey);
  }, [dismissalKey]);

  return {
    scope,
    line: display?.line ?? "none",
    badgeVisible: Boolean(display?.showBadge),
    dismissible: Boolean(display?.dismissible),
    dismiss,
    restore,
  };
}

/**
 * The collapsed form of the banner: an amber count in the page title row. It
 * carries the state in its accessible name, so collapsing the banner moves the
 * warning rather than removing it from the page.
 *
 * A scope can warrant attention with nothing to count — a degraded projection
 * that has not yet failed a job or lost a range — so the badge falls back to
 * naming that status rather than advertising a meaningless zero.
 */
export function AnsichHealthBadge({
  scope,
  onClick,
}: {
  scope: AnsichProjectionScope;
  onClick: () => void;
}) {
  const { t } = useI18n();
  const counted = scope.attentionCount > 0;
  const text = counted
    ? scope.attentionCount.toLocaleString()
    : t.ansich.health[scope.status];
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={
        counted
          ? t.ansich.healthBadgeLabel(text)
          : t.ansich.healthBadgeStatusLabel(text)
      }
      className="focus-visible:ring-ring inline-flex items-center gap-1 rounded-full border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-xs font-medium text-amber-700 tabular-nums outline-none hover:bg-amber-500/20 focus-visible:ring-2 dark:text-amber-300"
    >
      <AlertTriangleIcon className="size-3.5" aria-hidden />
      {text}
    </button>
  );
}

/**
 * Projection health at L0 (IA §5.2): a compact "Data healthy · lag 1.2s" status
 * line by default, promoted to a page-level banner when this page's own scope
 * warrants attention. The full metric wall lives in the System details drawer
 * and never competes with task cards at page top.
 *
 * On a Task page the numbers are that Task's own; a system-level hard failure
 * still appears, labeled as system-level, because the Task's data comes from
 * the same projection and must not be reported as clean. When the Task's
 * failure count is unknown the line stays neutral rather than green: an
 * unanswered request is not a clean bill of health. Neither is a collector that
 * is still starting or shutting down, so those name the phase in the same
 * neutral treatment instead of claiming the data is complete.
 */
export function AnsichProjectionHealthBanner({
  health,
  scope,
  line,
  taskId,
  onDismiss,
}: {
  health: AnsichHealth;
  scope: AnsichProjectionScope;
  line: AnsichProjectionHealthLine;
  taskId?: string;
  onDismiss?: () => void;
}) {
  const { t } = useI18n();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [failedJobsOpen, setFailedJobsOpen] = useState(false);
  const isTaskScope = scope.kind === "task";

  if (line === "none") return null;

  return (
    <>
      {line === "banner" ? (
        <div
          role="status"
          className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm"
        >
          <div className="flex items-center gap-2 font-medium text-amber-700 dark:text-amber-300">
            <AlertTriangleIcon className="size-4" aria-hidden />
            {scope.hardFailure && isTaskScope
              ? `${t.ansich.healthSystemLevel} · ${t.ansich.projection}: ${t.ansich.health[health.status]}`
              : isTaskScope
                ? t.ansich.healthTaskAttention
                : `${t.ansich.projection}: ${t.ansich.health[health.status]}`}
          </div>
          <div className="text-muted-foreground flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
            {scope.failedJobs === null ? (
              // An absent chip would read as "no failed jobs"; say so instead.
              <span className="italic">{t.ansich.healthCountUnavailable}</span>
            ) : scope.failedJobs > 0 ? (
              <button
                type="button"
                onClick={() => setFailedJobsOpen(true)}
                className="text-destructive font-medium underline"
              >
                {t.ansich.failedJobs}: {scope.failedJobs}
                {scope.failedJobsTruncated ? "+" : ""}
              </button>
            ) : null}
            {scope.lostObservations > 0 ? (
              <span>
                {t.ansich.lost}: {scope.lostObservations}
              </span>
            ) : null}
            {!health.storage_available ? (
              <span className="text-destructive font-medium">
                {t.ansich.health.stopped}
              </span>
            ) : null}
            <span>
              {t.ansich.lag} {formatAnsichLag(health.lag_ms)}
            </span>
          </div>
          <div className="ms-auto flex items-center gap-1">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setDrawerOpen(true)}
            >
              {t.ansich.systemDetails}
            </Button>
            {onDismiss ? (
              <Button
                variant="ghost"
                size="icon"
                className="size-8"
                aria-label={t.ansich.healthDismissLabel}
                title={t.ansich.healthDismissLabel}
                onClick={onDismiss}
              >
                <XIcon />
              </Button>
            ) : null}
          </div>
          {scope.hardFailure && isTaskScope ? (
            <p className="text-muted-foreground basis-full text-xs">
              {t.ansich.healthSystemLevelNote}
            </p>
          ) : null}
        </div>
      ) : (
        <div className="text-muted-foreground flex items-center gap-2 text-sm">
          {line === "healthy" ? (
            <ActivityIcon className="size-4 text-emerald-600" aria-hidden />
          ) : (
            <CircleHelpIcon className="size-4" aria-hidden />
          )}
          <span
            className={cn(
              "font-medium",
              line === "healthy" ? "text-foreground" : "text-muted-foreground",
            )}
          >
            {line === "phase"
              ? // A lifecycle phase names itself: the status word is the whole
                // information, and it is not a claim about the data.
                `${t.ansich.projection}: ${t.ansich.health[health.status]}`
              : line === "unknown"
                ? t.ansich.healthCountUnavailable
                : isTaskScope
                  ? t.ansich.healthTaskComplete
                  : t.ansich.dataHealthy}
          </span>
          <span aria-hidden>·</span>
          <span className="tabular-nums">
            {t.ansich.lag} {formatAnsichLag(health.lag_ms)}
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
      <AnsichFailedJobsDialog
        open={failedJobsOpen}
        onOpenChange={setFailedJobsOpen}
        taskId={taskId}
      />
    </>
  );
}
