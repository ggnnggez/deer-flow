import { ChevronRightIcon } from "lucide-react";
import Link from "next/link";

import { formatAnsichTimestamp } from "@/core/ansich/presentation";
import type { AnsichTask } from "@/core/ansich/types";
import { useI18n } from "@/core/i18n/hooks";

import { AnsichStatusBadge } from "./status-badge";

export function AnsichTaskRow({ task }: { task: AnsichTask }) {
  const { t, locale } = useI18n();

  return (
    <Link
      href={`/workspace/ansich/tasks/${encodeURIComponent(task.task_id)}`}
      className="hover:bg-muted/50 focus-visible:ring-ring grid gap-3 rounded-lg border p-4 transition-colors focus-visible:ring-2 focus-visible:outline-none md:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)_auto_minmax(10rem,auto)_auto] md:items-center"
    >
      <div className="min-w-0">
        <div className="text-muted-foreground text-xs md:hidden">
          {t.ansich.task}
        </div>
        <div className="truncate font-mono text-sm" title={task.task_id}>
          {task.task_id}
        </div>
      </div>
      <div className="min-w-0">
        <div className="text-muted-foreground text-xs md:hidden">
          {t.ansich.source}
        </div>
        <div className="truncate text-sm" title={task.source_id}>
          <span className="text-muted-foreground">{task.source_kind}:</span>{" "}
          <span className="font-mono">{task.source_id}</span>
        </div>
      </div>
      <AnsichStatusBadge value={task.control.value} />
      <div className="text-sm tabular-nums">
        <div className="text-muted-foreground text-xs md:hidden">
          {t.ansich.asOf}
        </div>
        {formatAnsichTimestamp(task.control.as_of, locale)}
      </div>
      <ChevronRightIcon className="text-muted-foreground hidden size-4 md:block" />
    </Link>
  );
}
