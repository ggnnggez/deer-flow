"use client";

import { AlertCircleIcon } from "lucide-react";
import { useEffect, useState } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  AnsichAlertPanel,
  AnsichProjectionHealth,
  AnsichActiveTaskRow,
  AnsichTaskRow,
} from "@/components/workspace/ansich";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import {
  useAnsichActiveTasks,
  useAnsichAlerts,
  useAnsichTaskHistory,
} from "@/core/ansich/hooks";
import { useAuth } from "@/core/auth/AuthProvider";
import { useI18n } from "@/core/i18n/hooks";

export default function AnsichOperationsPage() {
  const { t } = useI18n();
  const { user } = useAuth();
  const isAdmin = user?.system_role === "admin";
  const [selectedView, setSelectedView] = useState<
    "active" | "history" | "alerts"
  >("active");
  const activeTasksQuery = useAnsichActiveTasks(
    100,
    isAdmin && selectedView === "active",
  );
  const historyTasksQuery = useAnsichTaskHistory(
    100,
    isAdmin && selectedView === "history",
  );
  const alertsQuery = useAnsichAlerts(
    100,
    isAdmin && selectedView === "alerts",
  );
  const historyPages = historyTasksQuery.data?.pages ?? [];
  const historyTasks = historyPages.flatMap((page) => page.items);
  const alertPages = alertsQuery.data?.pages ?? [];
  const alerts = alertPages.flatMap((page) => page.items);
  const selectedProjectionStatus =
    selectedView === "active"
      ? activeTasksQuery.data?.projection_status
      : selectedView === "history"
        ? historyPages.at(-1)?.projection_status
        : alertPages.at(-1)?.projection_status;
  const selectedError =
    selectedView === "active"
      ? activeTasksQuery.error
      : selectedView === "history"
        ? historyTasksQuery.error
        : alertsQuery.error;

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
          ) : selectedError ? (
            <Alert variant="destructive">
              <AlertCircleIcon />
              <AlertTitle>{t.ansich.loadFailed}</AlertTitle>
              <AlertDescription>{selectedError.message}</AlertDescription>
            </Alert>
          ) : (
            <>
              {selectedProjectionStatus ? (
                <AnsichProjectionHealth health={selectedProjectionStatus} />
              ) : (
                <Skeleton className="h-18 w-full" />
              )}

              <Tabs
                value={selectedView}
                onValueChange={(value) =>
                  setSelectedView(value as "active" | "history" | "alerts")
                }
                className="space-y-4"
              >
                <TabsList variant="line">
                  <TabsTrigger value="active">
                    {t.ansich.runningTasks}
                  </TabsTrigger>
                  <TabsTrigger value="history">
                    {t.ansich.taskHistory}
                  </TabsTrigger>
                  <TabsTrigger value="alerts">{t.ansich.alerts}</TabsTrigger>
                </TabsList>
                <TabsContent value="active">
                  <section aria-labelledby="ansich-active-task-list-title">
                    <h2 id="ansich-active-task-list-title" className="sr-only">
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
                      {activeTasksQuery.isPending ? (
                        <TaskListSkeleton />
                      ) : activeTasksQuery.data?.items.length ? (
                        activeTasksQuery.data.items.map((task) => (
                          <AnsichActiveTaskRow key={task.task_id} task={task} />
                        ))
                      ) : (
                        <EmptyTaskList message={t.ansich.noActiveTasks} />
                      )}
                    </div>
                  </section>
                </TabsContent>
                <TabsContent value="history">
                  <section aria-labelledby="ansich-task-history-title">
                    <h2 id="ansich-task-history-title" className="sr-only">
                      {t.ansich.taskHistory}
                    </h2>
                    <div className="text-muted-foreground mb-2 hidden grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)_auto_minmax(10rem,auto)_auto] gap-3 px-4 text-xs font-medium md:grid">
                      <span>{t.ansich.task}</span>
                      <span>{t.ansich.source}</span>
                      <span>{t.ansich.control}</span>
                      <span>{t.ansich.asOf}</span>
                      <span className="w-4" />
                    </div>
                    <div className="space-y-2">
                      {historyTasksQuery.isPending ? (
                        <TaskListSkeleton />
                      ) : historyTasks.length ? (
                        historyTasks.map((task) => (
                          <AnsichTaskRow key={task.task_id} task={task} />
                        ))
                      ) : (
                        <EmptyTaskList message={t.ansich.noHistoricalTasks} />
                      )}
                      {historyTasksQuery.hasNextPage ? (
                        <div className="flex justify-center pt-2">
                          <Button
                            variant="outline"
                            disabled={historyTasksQuery.isFetchingNextPage}
                            onClick={() =>
                              void historyTasksQuery.fetchNextPage()
                            }
                          >
                            {t.common.loadMore}
                          </Button>
                        </div>
                      ) : null}
                    </div>
                  </section>
                </TabsContent>
                <TabsContent value="alerts">
                  <AnsichAlertPanel
                    alerts={alerts}
                    isPending={alertsQuery.isPending}
                    hasNextPage={Boolean(alertsQuery.hasNextPage)}
                    isFetchingNextPage={alertsQuery.isFetchingNextPage}
                    onLoadMore={() => void alertsQuery.fetchNextPage()}
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

function TaskListSkeleton() {
  return Array.from({ length: 4 }, (_, index) => (
    <Skeleton key={index} className="h-20 w-full" />
  ));
}

function EmptyTaskList({ message }: { message: string }) {
  return (
    <div className="text-muted-foreground rounded-lg border border-dashed p-10 text-center text-sm">
      {message}
    </div>
  );
}
