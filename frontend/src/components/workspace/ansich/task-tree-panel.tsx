"use client";

import { ChevronRightIcon } from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useAnsichTaskTree } from "@/core/ansich/hooks";
import type { AnsichTaskTreeNode } from "@/core/ansich/types";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

import { AnsichStatusBadge } from "./status-badge";

export function AnsichTaskTreePanel({
  taskId,
  polling,
}: {
  taskId: string;
  polling: boolean;
}) {
  const { t } = useI18n();
  const query = useAnsichTaskTree(taskId, true, polling);
  if (query.isPending) return <Skeleton className="h-32 w-full" />;
  if (query.error) {
    return (
      <div className="text-destructive rounded-lg border p-4 text-sm">
        {query.error.message}
      </div>
    );
  }
  const tree = query.data?.tree;
  if (!tree) return null;
  const depths = new Map<string, number>([[tree.root_task_id, 0]]);
  let remainingPasses = tree.nodes.length;
  while (remainingPasses > 0) {
    for (const edge of tree.edges) {
      const parentDepth = depths.get(edge.parent_task_id);
      const childDepth = depths.get(edge.child_task_id);
      if (parentDepth !== undefined && childDepth === undefined) {
        depths.set(edge.child_task_id, parentDepth + 1);
      } else if (childDepth !== undefined && parentDepth === undefined) {
        depths.set(edge.parent_task_id, childDepth - 1);
      }
    }
    remainingPasses -= 1;
  }
  const nodes = [...tree.nodes].sort((left, right) => {
    const depthDifference =
      (depths.get(left.task.task_id) ?? 0) -
      (depths.get(right.task.task_id) ?? 0);
    return (
      depthDifference || left.task.task_id.localeCompare(right.task.task_id)
    );
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t.ansich.taskTree}</CardTitle>
      </CardHeader>
      <CardContent>
        <details open>
          <summary className="text-muted-foreground mb-3 cursor-pointer text-sm">
            {t.ansich.taskTreeDescription}
          </summary>
          <div className="space-y-2">
            {nodes.map((node) => (
              <TaskTreeRow
                key={node.task.task_id}
                node={node}
                currentTaskId={taskId}
                depth={depths.get(node.task.task_id) ?? 0}
              />
            ))}
            {tree.truncated ? (
              <div className="text-muted-foreground text-xs">
                {t.ansich.taskTreeTruncated}
              </div>
            ) : null}
          </div>
        </details>
      </CardContent>
    </Card>
  );
}

function TaskTreeRow({
  node,
  currentTaskId,
  depth,
}: {
  node: AnsichTaskTreeNode;
  currentTaskId: string;
  depth: number;
}) {
  const { t } = useI18n();
  const local = Object.fromEntries(
    node.usage.local.map((item) => [item.dimension, item.value]),
  );
  const inclusive = Object.fromEntries(
    node.usage.inclusive.map((item) => [item.dimension, item.value]),
  );
  const effectiveModel =
    node.agent_release?.release.manifest.model.effective ??
    t.ansich.evidenceInsufficient;
  const indent = Math.max(0, depth) * 20;

  return (
    <Link
      href={`/workspace/ansich/tasks/${encodeURIComponent(node.task.task_id)}`}
      className={cn(
        "hover:bg-muted/50 flex items-center gap-3 rounded-lg border p-3 transition-colors",
        node.task.task_id === currentTaskId && "border-primary/40 bg-muted/30",
      )}
      style={{ marginLeft: indent }}
    >
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span
            className="truncate font-mono text-xs"
            title={node.task.task_id}
          >
            {node.task.task_id}
          </span>
          <AnsichStatusBadge value={node.task.control.value} />
          <Badge variant="outline">
            {node.task.source_kind === "deerflow_subagent"
              ? "subagent"
              : "lead"}
          </Badge>
        </div>
        <div className="text-muted-foreground mt-1 truncate text-xs">
          {effectiveModel} · {t.ansich.localUsage}: {local.total_tokens ?? "?"}{" "}
          · {t.ansich.inclusiveUsage}: {inclusive.total_tokens ?? "?"}
        </div>
        <div className="text-muted-foreground mt-1 truncate text-xs">
          {node.current_step
            ? `${t.ansich.currentAction}: Step ${node.current_step.step_seq} · ${node.current_step.status}`
            : t.ansich.evidenceInsufficient}
        </div>
      </div>
      <Badge variant="outline">
        {t.ansich.health[node.task.observability_status]}
      </Badge>
      <ChevronRightIcon className="text-muted-foreground size-4" />
    </Link>
  );
}
