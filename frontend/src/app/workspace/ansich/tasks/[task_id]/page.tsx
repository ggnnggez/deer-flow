"use client";

import { AlertCircleIcon, ArrowLeftIcon } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  AnsichContextPanel,
  AnsichBudgetPanel,
  AnsichObservationTimeline,
  AnsichProjectionHealth,
  AnsichStepsPanel,
  AnsichStatusBadge,
} from "@/components/workspace/ansich";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { useAnsichTask, useAnsichTaskTimeline } from "@/core/ansich/hooks";
import { formatAnsichTimestamp } from "@/core/ansich/presentation";
import { useAuth } from "@/core/auth/AuthProvider";
import { useI18n } from "@/core/i18n/hooks";

export default function AnsichTaskDetailPage() {
  const { t, locale } = useI18n();
  const { user } = useAuth();
  const params = useParams<{ task_id: string }>();
  const taskId = params.task_id;
  const isAdmin = user?.system_role === "admin";
  const taskQuery = useAnsichTask(taskId, isAdmin);
  const task = taskQuery.data?.task;
  const taskIsRunning = task?.control.value === "running";
  const timelineQuery = useAnsichTaskTimeline(taskId, isAdmin, taskIsRunning);
  const health =
    timelineQuery.data?.projection_status ??
    taskQuery.data?.projection_status ??
    null;
  const queryError = taskQuery.error ?? timelineQuery.error;
  const compressionIds = (timelineQuery.data?.items ?? [])
    .filter((observation) => observation.kind === "context.compressed")
    .map((observation) => observation.subject_id);

  useEffect(() => {
    document.title = `${t.ansich.task} ${taskId} - ${t.pages.appName}`;
  }, [t.ansich.task, t.pages.appName, taskId]);

  return (
    <WorkspaceContainer>
      <WorkspaceHeader />
      <WorkspaceBody className="overflow-y-auto">
        <div className="mx-auto flex w-full max-w-(--container-width-lg) flex-col gap-5 p-4 sm:p-6">
          <div>
            <Button variant="ghost" size="sm" className="-ml-3" asChild>
              <Link href="/workspace/ansich/operations">
                <ArrowLeftIcon />
                {t.ansich.backToOperations}
              </Link>
            </Button>
          </div>

          {!isAdmin ? (
            <Alert>
              <AlertCircleIcon />
              <AlertTitle>{t.ansich.title}</AlertTitle>
              <AlertDescription>{t.ansich.adminOnly}</AlertDescription>
            </Alert>
          ) : queryError ? (
            <Alert variant="destructive">
              <AlertCircleIcon />
              <AlertTitle>{t.ansich.loadFailed}</AlertTitle>
              <AlertDescription>{queryError.message}</AlertDescription>
            </Alert>
          ) : !task ? (
            <TaskDetailSkeleton />
          ) : (
            <>
              <header className="space-y-2">
                <div className="flex flex-wrap items-center gap-3">
                  <h1 className="font-mono text-xl font-semibold break-all">
                    {task.task_id}
                  </h1>
                  <AnsichStatusBadge value={task.control.value} />
                </div>
                <p className="text-muted-foreground text-sm">
                  {task.source_kind}: {task.source_id}
                </p>
              </header>

              {health && <AnsichProjectionHealth health={health} />}

              <Tabs defaultValue="overview" className="space-y-4">
                <TabsList className="h-auto flex-wrap">
                  <TabsTrigger value="overview">
                    {t.ansich.overview}
                  </TabsTrigger>
                  <TabsTrigger value="timeline">
                    {t.ansich.timeline}
                  </TabsTrigger>
                  <TabsTrigger value="steps">{t.ansich.steps}</TabsTrigger>
                  <TabsTrigger value="budgets">{t.ansich.budgets}</TabsTrigger>
                  <TabsTrigger value="context">
                    {t.ansich.contextAndLineage}
                  </TabsTrigger>
                </TabsList>

                <TabsContent value="overview">
                  <Card>
                    <CardHeader>
                      <CardTitle>{t.ansich.currentBelief}</CardTitle>
                      <CardDescription>
                        {t.ansich.asOf}:{" "}
                        {formatAnsichTimestamp(task.control.as_of, locale)}
                      </CardDescription>
                    </CardHeader>
                    <CardContent className="grid gap-5 text-sm sm:grid-cols-2">
                      <BeliefField
                        label={t.ansich.control}
                        value={t.ansich.status[task.control.value]}
                      />
                      <BeliefField
                        label={t.ansich.fidelity}
                        value={task.control.fidelity_class}
                        mono
                      />
                      <BeliefField
                        label={t.ansich.source}
                        value={`${task.control.source.name}@${task.control.source.version}`}
                        mono
                      />
                      <BeliefField
                        label={t.ansich.resolver}
                        value={`${task.control.selected_by.name}@${task.control.selected_by.version}`}
                        mono
                      />
                      <div className="sm:col-span-2">
                        <div className="text-muted-foreground mb-2 text-xs">
                          {t.ansich.evidence}
                        </div>
                        <div className="flex flex-wrap gap-2">
                          {task.control.evidence_obs_ids.map((obsId) => (
                            <code
                              key={obsId}
                              className="bg-muted rounded px-2 py-1 text-xs"
                            >
                              {obsId}
                            </code>
                          ))}
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                </TabsContent>

                <TabsContent value="timeline" className="space-y-3">
                  {timelineQuery.isPending ? (
                    <Skeleton className="h-48 w-full" />
                  ) : (
                    <AnsichObservationTimeline
                      observations={timelineQuery.data?.items ?? []}
                    />
                  )}
                </TabsContent>

                <TabsContent value="steps">
                  <AnsichStepsPanel taskId={taskId} polling={taskIsRunning} />
                </TabsContent>

                <TabsContent value="budgets">
                  <AnsichBudgetPanel taskId={taskId} polling={taskIsRunning} />
                </TabsContent>

                <TabsContent value="context">
                  <AnsichContextPanel
                    taskId={taskId}
                    compressionIds={compressionIds}
                    polling={taskIsRunning}
                  />
                </TabsContent>
              </Tabs>
            </>
          )}
        </div>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}

function BeliefField({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div>
      <div className="text-muted-foreground mb-1 text-xs">{label}</div>
      <div className={mono ? "font-mono break-all" : ""}>{value}</div>
    </div>
  );
}

function TaskDetailSkeleton() {
  return (
    <div className="space-y-5">
      <Skeleton className="h-10 w-2/3" />
      <Skeleton className="h-18 w-full" />
      <Skeleton className="h-56 w-full" />
    </div>
  );
}
