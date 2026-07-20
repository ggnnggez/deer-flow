import { ChevronRightIcon } from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { formatDuration } from "@/core/ansich/presentation";
import type {
  AnsichActiveTask,
  AnsichBudgetHealthBelief,
} from "@/core/ansich/types";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

import { AnsichStatusBadge } from "./status-badge";

const HEALTH_ORDER: Record<AnsichBudgetHealthBelief["value"], number> = {
  exceeded: 3,
  warning: 2,
  unknown: 1,
  within: 0,
};

export function AnsichActiveTaskRow({ task }: { task: AnsichActiveTask }) {
  const { t } = useI18n();
  const usage = Object.fromEntries(
    task.usage.local.map((item) => [item.dimension, item.value]),
  );
  const budgetHealth = [...task.budget_health].sort(
    (left, right) => HEALTH_ORDER[right.value] - HEALTH_ORDER[left.value],
  )[0];
  const action = task.current_tool
    ? `${task.current_tool.tool_name} · ${task.current_tool.status}`
    : task.current_step
      ? `Step ${task.current_step.step_seq} · ${task.current_step.status}`
      : t.ansich.evidenceInsufficient;

  return (
    <Link
      href={`/workspace/ansich/tasks/${encodeURIComponent(task.task_id)}`}
      className="hover:bg-muted/50 focus-visible:ring-ring grid gap-3 rounded-lg border p-4 transition-colors focus-visible:ring-2 focus-visible:outline-none md:grid-cols-[minmax(12rem,1.35fr)_minmax(9rem,1fr)_auto_auto_minmax(10rem,1fr)_minmax(9rem,auto)_auto] md:items-center"
    >
      <div className="min-w-0 space-y-1">
        <div className="truncate font-mono text-sm" title={task.task_id}>
          {task.task_id}
        </div>
        <div className="text-muted-foreground truncate text-xs">
          {task.owner_id ?? t.ansich.evidenceInsufficient} · {task.run_id}
        </div>
      </div>
      <div className="min-w-0">
        <div className="truncate text-sm" title={action}>
          {action}
        </div>
        <div className="text-muted-foreground text-xs">
          {t.ansich.dwell}: {formatDuration(task.dwell.duration_ms)}
        </div>
      </div>
      <AnsichStatusBadge value={task.control.value} />
      <div className="space-y-1">
        <RuleBadge
          label={t.ansich.heartbeatState[task.heartbeat.value]}
          state={task.heartbeat.value}
        />
        <div className="text-muted-foreground text-xs tabular-nums">
          {formatDuration(task.heartbeat.age_ms)}
        </div>
      </div>
      <div className="text-xs tabular-nums">
        <div>
          {usage.total_tokens ?? "?"} tok · {usage.steps ?? "?"} step
        </div>
        <div className="text-muted-foreground">
          {usage.tool_calls_executed ?? "?"}/{usage.tool_calls_issued ?? "?"}{" "}
          tools
        </div>
        {task.active_child_count ? (
          <div className="text-muted-foreground">
            {t.ansich.activeChildren.replace(
              "{count}",
              task.active_child_count.toLocaleString(),
            )}
          </div>
        ) : null}
      </div>
      {budgetHealth ? (
        <RuleBadge
          label={t.ansich.budgetState[budgetHealth.value]}
          state={budgetHealth.value}
        />
      ) : (
        <Badge variant="outline" className="text-muted-foreground">
          {t.ansich.unconfigured}
        </Badge>
      )}
      <div className="flex items-center justify-end gap-2">
        <Badge
          variant="outline"
          className={cn(
            task.observability_status === "degraded"
              ? "border-amber-500/40 text-amber-700 dark:text-amber-300"
              : "text-muted-foreground",
          )}
        >
          {t.ansich.health[task.observability_status]}
        </Badge>
        <ChevronRightIcon className="text-muted-foreground size-4" />
      </div>
    </Link>
  );
}

function RuleBadge({ label, state }: { label: string; state: string }) {
  return (
    <Badge
      variant="outline"
      className={cn(
        state === "stale" || state === "exceeded"
          ? "border-red-500/40 bg-red-500/10 text-red-700 dark:text-red-300"
          : state === "warning" || state === "long"
            ? "border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-300"
            : state === "fresh" || state === "within"
              ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
              : "text-muted-foreground",
      )}
    >
      {label}
    </Badge>
  );
}
