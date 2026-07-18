"use client";

import { AlertCircleIcon } from "lucide-react";
import { useEffect } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import {
  AnsichProjectionHealth,
  AnsichActiveTaskRow,
} from "@/components/workspace/ansich";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { useAnsichActiveTasks } from "@/core/ansich/hooks";
import { useAuth } from "@/core/auth/AuthProvider";
import { useI18n } from "@/core/i18n/hooks";

export default function AnsichOperationsPage() {
  const { t } = useI18n();
  const { user } = useAuth();
  const isAdmin = user?.system_role === "admin";
  const tasksQuery = useAnsichActiveTasks(100, isAdmin);

  useEffect(() => {
    document.title = `${t.ansich.title} - ${t.pages.appName}`;
  }, [t.ansich.title, t.pages.appName]);

  return (
    <WorkspaceContainer>
      <WorkspaceHeader />
      <WorkspaceBody className="overflow-y-auto">
        <div className="mx-auto flex w-full max-w-(--container-width-lg) flex-col gap-5 p-4 sm:p-6">
          <header className="space-y-1">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h1 className="text-2xl font-semibold">{t.ansich.title}</h1>
              <span className="text-muted-foreground text-xs">
                {t.ansich.autoRefresh}
              </span>
            </div>
            <p className="text-muted-foreground text-sm">
              {t.ansich.description}
            </p>
          </header>

          {!isAdmin ? (
            <Alert>
              <AlertCircleIcon />
              <AlertTitle>{t.ansich.title}</AlertTitle>
              <AlertDescription>{t.ansich.adminOnly}</AlertDescription>
            </Alert>
          ) : tasksQuery.isError ? (
            <Alert variant="destructive">
              <AlertCircleIcon />
              <AlertTitle>{t.ansich.loadFailed}</AlertTitle>
              <AlertDescription>{tasksQuery.error.message}</AlertDescription>
            </Alert>
          ) : (
            <>
              {tasksQuery.data?.projection_status ? (
                <AnsichProjectionHealth
                  health={tasksQuery.data.projection_status}
                />
              ) : (
                <Skeleton className="h-18 w-full" />
              )}

              <section aria-labelledby="ansich-task-list-title">
                <h2 id="ansich-task-list-title" className="sr-only">
                  {t.ansich.activeTasks}
                </h2>
                <div className="text-muted-foreground mb-2 hidden grid-cols-[minmax(12rem,1.35fr)_minmax(9rem,1fr)_auto_auto_minmax(10rem,1fr)_minmax(9rem,auto)_auto] gap-3 px-4 text-xs font-medium md:grid">
                  <span>{t.ansich.task}</span>
                  <span>{t.ansich.currentAction}</span>
                  <span>{t.ansich.control}</span>
                  <span>{t.ansich.heartbeat}</span>
                  <span>{t.ansich.localUsage}</span>
                  <span>{t.ansich.budget}</span>
                  <span>{t.ansich.projection}</span>
                </div>
                <div className="space-y-2">
                  {tasksQuery.isPending ? (
                    <TaskListSkeleton />
                  ) : tasksQuery.data?.items.length ? (
                    tasksQuery.data.items.map((task) => (
                      <AnsichActiveTaskRow key={task.task_id} task={task} />
                    ))
                  ) : (
                    <div className="text-muted-foreground rounded-lg border border-dashed p-10 text-center text-sm">
                      {t.ansich.noActiveTasks}
                    </div>
                  )}
                </div>
              </section>
            </>
          )}
        </div>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}

function TaskListSkeleton() {
  return Array.from({ length: 4 }, (_, index) => (
    <Skeleton key={index} className="h-20 w-full" />
  ));
}
