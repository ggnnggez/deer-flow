"use client";

import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import {
  useAnsichFailedJobDetail,
  useAnsichFailedJobs,
  useAnsichRetryFailedJobs,
} from "@/core/ansich/hooks";
import { formatAnsichTimestamp } from "@/core/ansich/presentation";
import type { AnsichFailedJob } from "@/core/ansich/types";
import { useI18n } from "@/core/i18n/hooks";

export function AnsichFailedJobsDialog({
  open,
  onOpenChange,
  taskId,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  taskId?: string;
}) {
  const { t, locale } = useI18n();
  const jobsQuery = useAnsichFailedJobs(taskId, 100, open);
  const retryMutation = useAnsichRetryFailedJobs();
  const [expandedJobId, setExpandedJobId] = useState<string | null>(null);
  const jobs = jobsQuery.data?.items ?? [];
  const failingTaskIds = Array.from(new Set(jobs.map((job) => job.task_id)));

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[80vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t.ansich.failedJobsDialogTitle}</DialogTitle>
          <DialogDescription>
            {taskId
              ? t.ansich.failedJobsDialogDescriptionTask
              : t.ansich.failedJobsDialogDescriptionGlobal}
          </DialogDescription>
        </DialogHeader>
        {jobsQuery.isPending ? (
          <Skeleton className="h-32 w-full" />
        ) : jobs.length === 0 ? (
          <p className="text-muted-foreground text-sm">
            {t.ansich.failedJobsEmpty}
          </p>
        ) : (
          <div className="space-y-2">
            {taskId ? (
              <Button
                size="sm"
                variant="outline"
                disabled={retryMutation.isPending}
                onClick={() => retryMutation.mutate({ taskId })}
              >
                {t.ansich.failedJobRetryTask}
              </Button>
            ) : (
              <div className="flex flex-wrap gap-2">
                {failingTaskIds.map((id) => (
                  <Button
                    key={id}
                    size="sm"
                    variant="outline"
                    disabled={retryMutation.isPending}
                    onClick={() => retryMutation.mutate({ taskId: id })}
                  >
                    {t.ansich.failedJobRetryTask} · {id.slice(0, 8)}
                  </Button>
                ))}
              </div>
            )}
            {jobs.map((job) => (
              <FailedJobRow
                key={job.job_id}
                job={job}
                locale={locale}
                expanded={expandedJobId === job.job_id}
                onToggle={() =>
                  setExpandedJobId((current) =>
                    current === job.job_id ? null : job.job_id,
                  )
                }
              />
            ))}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

function FailedJobRow({
  job,
  locale,
  expanded,
  onToggle,
}: {
  job: AnsichFailedJob;
  locale: string;
  expanded: boolean;
  onToggle: () => void;
}) {
  const { t } = useI18n();
  const detailQuery = useAnsichFailedJobDetail(job.job_id, job.kind, expanded);
  return (
    <div className="rounded-lg border p-3">
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center justify-between gap-3 text-left"
      >
        <span className="min-w-0">
          <span className="block truncate text-sm font-medium">
            {job.name}@{job.version}
          </span>
          <span className="text-muted-foreground mt-1 block text-xs">
            {t.ansich.failedJobKindLabel[job.kind]} · {t.ansich.task}{" "}
            {job.task_id.slice(0, 8)} · {t.ansich.failedJobAttempts}:{" "}
            {job.attempts}
          </span>
        </span>
        <Badge variant="outline">
          {formatAnsichTimestamp(job.available_at, locale)}
        </Badge>
      </button>
      {job.last_error ? (
        <p className="text-destructive mt-2 truncate text-xs">
          {job.last_error}
        </p>
      ) : null}
      {expanded ? (
        <div className="mt-2 space-y-1 border-t pt-2">
          {detailQuery.isPending ? (
            <Skeleton className="h-16 w-full" />
          ) : (
            (detailQuery.data?.job.errors ?? []).map((error, index) => (
              <div key={index} className="text-xs">
                <span className="font-medium">
                  {t.ansich.failedJobAttempts} #{error.attempt} ·{" "}
                  {formatAnsichTimestamp(error.occurred_at, locale)}
                </span>
                <p className="text-muted-foreground">
                  {error.error_type}: {error.message}
                </p>
              </div>
            ))
          )}
        </div>
      ) : null}
    </div>
  );
}
