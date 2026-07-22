"use client";

import { AlertCircleIcon, ArrowLeftIcon } from "lucide-react";
import Link from "next/link";
import { useParams, usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  AnsichContextPanel,
  AnsichAgentReleasePanel,
  AnsichBudgetPanel,
  AnsichEvidenceSection,
  AnsichObservationTimeline,
  AnsichProjectionHealth,
  AnsichStepsPanel,
  AnsichTaskDiagnosticStrip,
  AnsichTaskHero,
  AnsichTaskTreePanel,
  AnsichScopeEffectsPanel,
} from "@/components/workspace/ansich";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import {
  useAnsichTask,
  useAnsichTaskBudgets,
  useAnsichTaskCompressions,
  useAnsichTaskSteps,
  useAnsichTaskTimeline,
  useAnsichTaskUsage,
} from "@/core/ansich/hooks";
import {
  formatAnsichTimestamp,
  selectPrimarySignal,
} from "@/core/ansich/presentation";
import type {
  AnsichBeliefAssertion,
  AnsichTaskUsageValue,
  AnsichUsageDimension,
} from "@/core/ansich/types";
import { useAuth } from "@/core/auth/AuthProvider";
import { useI18n } from "@/core/i18n/hooks";

type TaskView = "summary" | "decision" | "resources" | "evidence";
const TASK_VIEWS: TaskView[] = ["summary", "decision", "resources", "evidence"];

function usageValue(
  values: AnsichTaskUsageValue[],
  dimension: AnsichUsageDimension,
): number | null {
  const found = values.find((item) => item.dimension === dimension);
  return found ? found.value : null;
}

/** Best-effort behavior classification from the untyped belief value (UI-1). */
function extractBehaviorState(
  behavior: AnsichBeliefAssertion | null,
): "runaway" | "normal" | "unknown" | null {
  if (!behavior) return null;
  const raw = String(
    (behavior.value.state ??
      behavior.value.classification ??
      behavior.value.behavior ??
      "") as string,
  ).toLowerCase();
  if (raw.includes("runaway")) return "runaway";
  if (raw === "normal" || raw === "nominal" || raw === "within") return "normal";
  return "unknown";
}

export default function AnsichTaskDetailPage() {
  const { t, locale } = useI18n();
  const { user } = useAuth();
  const params = useParams<{ task_id: string }>();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const taskId = params.task_id;
  const isAdmin = user?.system_role === "admin";

  const rawView = searchParams.get("view");
  const view: TaskView = TASK_VIEWS.includes(rawView as TaskView)
    ? (rawView as TaskView)
    : "summary";

  const setView = useCallback(
    (next: string) => {
      const query = new URLSearchParams(searchParams.toString());
      query.set("view", next);
      router.replace(`${pathname}?${query.toString()}`, { scroll: false });
    },
    [pathname, router, searchParams],
  );

  const taskQuery = useAnsichTask(taskId, isAdmin);
  const task = taskQuery.data?.task;
  const behavior = taskQuery.data?.behavior;
  const taskIsRunning = task?.control.value === "running";
  const usageQuery = useAnsichTaskUsage(taskId, isAdmin, taskIsRunning, "local");
  const budgetsQuery = useAnsichTaskBudgets(taskId, isAdmin, taskIsRunning);
  const stepsQuery = useAnsichTaskSteps(taskId, isAdmin, taskIsRunning);
  const timelineQuery = useAnsichTaskTimeline(taskId, isAdmin, taskIsRunning);
  const compressionsQuery = useAnsichTaskCompressions(
    taskId,
    100,
    isAdmin,
    taskIsRunning,
  );
  const health =
    timelineQuery.data?.projection_status ??
    taskQuery.data?.projection_status ??
    null;
  const queryError = taskQuery.error ?? timelineQuery.error;
  const compressionIds = Array.from(
    new Set(
      (compressionsQuery.data?.pages ?? []).flatMap((page) =>
        page.items.map((compression) => compression.compression_id),
      ),
    ),
  );

  useEffect(() => {
    document.title = `${t.ansich.task} ${taskId} - ${t.pages.appName}`;
  }, [t.ansich.task, t.pages.appName, taskId]);

  // Derived first-screen diagnostics (existing per-task queries only).
  const usageValues = usageQuery.data?.values ?? [];
  const budgetHealth = budgetsQuery.data?.health ?? [];
  const durationMs = usageValue(usageValues, "wall_time_ms");
  const childCount = usageValue(usageValues, "child_tasks_spawned");
  const totalTokens = usageValue(usageValues, "total_tokens");
  const primarySignal = task
    ? selectPrimarySignal({
        behaviorState: extractBehaviorState(behavior ?? null),
        budgetHealth,
        observability: task.observability_status,
      })
    : null;
  const latestStep = stepsQuery.data?.items?.at(-1) ?? null;
  const currentActivity = latestStep
    ? {
        label: `${t.ansich.step} ${latestStep.step_seq} · ${latestStep.status}`,
      }
    : null;
  const impact =
    childCount || totalTokens !== null
      ? {
          label:
            totalTokens !== null
              ? `${totalTokens.toLocaleString()} ${t.ansich.tokens}`
              : t.ansich.evidenceInsufficient,
          sublabel: childCount
            ? t.ansich.childTasksCount(childCount.toLocaleString())
            : null,
        }
      : null;

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
              <AnsichTaskHero
                task={task}
                actor={null}
                durationMs={durationMs}
                childCount={childCount}
                primarySignal={primarySignal}
                technicalDetails={
                  <dl className="grid gap-x-6 gap-y-2 text-xs sm:grid-cols-2">
                    <TechRow label={t.ansich.task} value={task.task_id} />
                    <TechRow
                      label={t.ansich.source}
                      value={`${task.source_kind}: ${task.source_id}`}
                    />
                    <TechRow
                      label={t.ansich.resolver}
                      value={`${task.control.selected_by.name}@${task.control.selected_by.version}`}
                    />
                    <TechRow
                      label={t.ansich.fidelity}
                      value={task.control.fidelity_class}
                    />
                  </dl>
                }
              />

              {health && (
                <AnsichProjectionHealth health={health} taskId={taskId} />
              )}

              <Tabs
                value={view}
                onValueChange={setView}
                className="space-y-4"
              >
                <TabsList variant="line">
                  <TabsTrigger value="summary">
                    {t.ansich.viewSummary}
                  </TabsTrigger>
                  <TabsTrigger value="decision">
                    {t.ansich.viewDecisionTrace}
                  </TabsTrigger>
                  <TabsTrigger value="resources">
                    {t.ansich.viewResourcesSafety}
                  </TabsTrigger>
                  <TabsTrigger value="evidence">
                    {t.ansich.viewEvidence}
                  </TabsTrigger>
                </TabsList>

                <TabsContent value="summary" className="space-y-4">
                  <AnsichTaskDiagnosticStrip
                    currentActivity={currentActivity}
                    primarySignal={primarySignal}
                    impact={impact}
                  />
                  <AnsichTaskTreePanel
                    taskId={taskId}
                    polling={taskIsRunning}
                  />
                </TabsContent>

                <TabsContent value="decision">
                  <AnsichStepsPanel taskId={taskId} polling={taskIsRunning} />
                </TabsContent>

                <TabsContent value="resources" className="space-y-4">
                  <AnsichBudgetPanel taskId={taskId} polling={taskIsRunning} />
                  <AnsichScopeEffectsPanel
                    taskId={taskId}
                    polling={taskIsRunning}
                  />
                </TabsContent>

                <TabsContent value="evidence" className="space-y-3">
                  <AnsichEvidenceSection
                    title={t.ansich.timeline}
                    defaultOpen
                  >
                    {timelineQuery.isPending ? (
                      <Skeleton className="h-48 w-full" />
                    ) : (
                      <AnsichObservationTimeline
                        observations={timelineQuery.data?.items ?? []}
                      />
                    )}
                  </AnsichEvidenceSection>
                  <AnsichEvidenceSection
                    title={t.ansich.contextAndLineage}
                    defaultOpen
                  >
                    <AnsichContextPanel
                      taskId={taskId}
                      compressionIds={compressionIds}
                      compressionError={
                        compressionsQuery.error?.message ?? null
                      }
                      compressionHasNextPage={compressionsQuery.hasNextPage}
                      compressionLoadingMore={
                        compressionsQuery.isFetchingNextPage
                      }
                      onLoadMoreCompressions={() =>
                        void compressionsQuery.fetchNextPage()
                      }
                      polling={taskIsRunning}
                    />
                  </AnsichEvidenceSection>
                  <AnsichEvidenceSection title={t.ansich.agentRelease}>
                    <AnsichAgentReleasePanel
                      taskId={taskId}
                      polling={taskIsRunning}
                    />
                  </AnsichEvidenceSection>
                  <AnsichEvidenceSection title={t.ansich.currentBehavior}>
                    <BeliefEvidenceCard behavior={behavior ?? null} />
                  </AnsichEvidenceSection>
                </TabsContent>
              </Tabs>
            </>
          )}
        </div>
      </WorkspaceBody>
    </WorkspaceContainer>
  );

  function BeliefEvidenceCard({
    behavior,
  }: {
    behavior: AnsichBeliefAssertion | null;
  }) {
    if (!behavior) {
      return (
        <div className="text-muted-foreground text-sm">
          {t.ansich.evidenceInsufficient}
        </div>
      );
    }
    return (
      <div className="space-y-3 text-sm">
        <div className="text-muted-foreground text-xs">
          {t.ansich.asOf}: {formatAnsichTimestamp(behavior.as_of, locale)} ·{" "}
          {behavior.assessor.name}@{behavior.assessor.version} ·{" "}
          {behavior.config_hash.slice(0, 12)}
        </div>
        <pre className="bg-muted/60 overflow-x-auto rounded-md p-3 text-xs">
          {JSON.stringify(behavior.value, null, 2)}
        </pre>
      </div>
    );
  }
}

function TechRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex gap-2">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="font-mono break-all">{value}</dd>
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
