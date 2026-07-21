import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import {
  acknowledgeAnsichAlert,
  dismissAnsichAlert,
  executeAnsichTaskAction,
  compareAnsichAgentReleases,
  fetchAnsichAlert,
  fetchAnsichAlerts,
  fetchAnsichFailedJobDetail,
  fetchAnsichFailedJobs,
  fetchAnsichStepContext,
  fetchAnsichActiveTasks,
  fetchAnsichAgentReleases,
  fetchAnsichTaskCompressions,
  fetchAnsichTaskSteps,
  fetchAnsichTaskBudgets,
  fetchAnsichTask,
  fetchAnsichTaskTimeline,
  fetchAnsichTaskUsage,
  fetchAnsichTaskAgentRelease,
  fetchAnsichTasks,
  fetchAnsichTaskTree,
  fetchAnsichTaskScopes,
  fetchAnsichToolAuthorization,
  fetchAnsichToolEffects,
  retryAnsichFailedJobs,
} from "./api";
import type {
  AnsichActiveTaskListResponse,
  AnsichAlertListResponse,
  AnsichContextCompressionListResponse,
  AnsichFailedJobKind,
  AnsichTaskLifecycleScope,
  AnsichTaskListResponse,
  AnsichTaskAgentReleaseResponse,
  AnsichTaskResponse,
} from "./types";

const REFRESH_INTERVAL_MS = 5_000;
const IDLE_REFRESH_INTERVAL_MS = 10_000;

export function activeTasksRefreshInterval(
  data: AnsichActiveTaskListResponse | undefined,
  pageVisible: boolean,
): number | false {
  if (!pageVisible) return false;
  return data?.items.some((task) => task.control.value === "running")
    ? REFRESH_INTERVAL_MS
    : IDLE_REFRESH_INTERVAL_MS;
}

export function taskDetailRefreshInterval(
  data: AnsichTaskResponse | undefined,
  pageVisible: boolean,
): number | false {
  if (!pageVisible || (data && data.task.control.value !== "running")) {
    return false;
  }
  return REFRESH_INTERVAL_MS;
}

export function taskListRefreshInterval(
  lifecycleScope: AnsichTaskLifecycleScope,
  pageVisible: boolean,
): number | false {
  if (!pageVisible || lifecycleScope === "terminal") return false;
  return REFRESH_INTERVAL_MS;
}

export function taskReleaseRefreshInterval(
  data: AnsichTaskAgentReleaseResponse | undefined,
  pageVisible: boolean,
  taskRunning: boolean,
): number | false {
  if (!pageVisible || !taskRunning || data?.binding) return false;
  return REFRESH_INTERVAL_MS;
}

function pageIsVisible(): boolean {
  return typeof document === "undefined" || !document.hidden;
}

export function useAnsichActiveTasks(limit = 100, enabled = true) {
  return useQuery({
    queryKey: ["ansich", "operations", "active-tasks", { limit }],
    queryFn: () => fetchAnsichActiveTasks(limit),
    enabled,
    retry: false,
    refetchInterval: (query) =>
      activeTasksRefreshInterval(query.state.data, pageIsVisible()),
    refetchIntervalInBackground: false,
  });
}

export function useAnsichAlerts(limit = 100, enabled = true) {
  return useInfiniteQuery<
    AnsichAlertListResponse,
    Error,
    { pages: AnsichAlertListResponse[]; pageParams: Array<string | undefined> },
    readonly ["ansich", "operations", "alerts", { limit: number }],
    string | undefined
  >({
    queryKey: ["ansich", "operations", "alerts", { limit }] as const,
    queryFn: ({ pageParam }) => fetchAnsichAlerts(limit, { cursor: pageParam }),
    initialPageParam: undefined,
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
    enabled,
    retry: false,
    refetchInterval: () => (pageIsVisible() ? REFRESH_INTERVAL_MS : false),
    refetchIntervalInBackground: false,
  });
}

export function useAnsichAlert(alertId: string | null, enabled = true) {
  return useQuery({
    queryKey: ["ansich", "operations", "alerts", alertId],
    queryFn: () => fetchAnsichAlert(alertId ?? ""),
    enabled: enabled && Boolean(alertId),
    retry: false,
  });
}

export function useAnsichAlertWorkflow() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: {
      alertId: string;
      workflowVersion: number;
      action: "acknowledge" | "dismiss";
      reason?: string;
    }) =>
      input.action === "acknowledge"
        ? acknowledgeAnsichAlert(input.alertId, input.workflowVersion)
        : dismissAnsichAlert(
            input.alertId,
            input.workflowVersion,
            input.reason ?? "",
          ),
    onSettled: async (_data, _error, input) => {
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["ansich", "operations", "alerts"],
        }),
        queryClient.invalidateQueries({
          queryKey: ["ansich", "operations", "alerts", input.alertId],
        }),
      ]);
    },
  });
}

export function useAnsichFailedJobs(
  taskId: string | undefined,
  limit = 100,
  enabled = true,
) {
  return useQuery({
    queryKey: [
      "ansich",
      "operations",
      "failed-jobs",
      taskId ?? null,
      { limit },
    ],
    queryFn: () => fetchAnsichFailedJobs(taskId, limit),
    enabled,
    retry: false,
  });
}

export function useAnsichFailedJobDetail(
  jobId: string,
  kind: AnsichFailedJobKind,
  enabled = true,
) {
  return useQuery({
    queryKey: ["ansich", "operations", "failed-jobs", jobId, kind],
    queryFn: () => fetchAnsichFailedJobDetail(jobId, kind),
    enabled: enabled && Boolean(jobId),
    retry: false,
  });
}

export function useAnsichRetryFailedJobs() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { taskId?: string }) =>
      retryAnsichFailedJobs(input.taskId),
    onSettled: async () => {
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["ansich", "operations", "failed-jobs"],
        }),
        queryClient.invalidateQueries({
          queryKey: ["ansich", "operations", "active-tasks"],
        }),
        queryClient.invalidateQueries({ queryKey: ["ansich", "tasks"] }),
        queryClient.invalidateQueries({
          queryKey: ["ansich", "operations", "alerts"],
        }),
      ]);
    },
  });
}

export function useAnsichTaskAction() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: {
      taskId: string;
      action: "interrupt" | "rollback";
      idempotencyKey: string;
    }) =>
      executeAnsichTaskAction(input.taskId, input.action, input.idempotencyKey),
    onSettled: async (_data, _error, input) => {
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["ansich", "operations"],
        }),
        queryClient.invalidateQueries({
          queryKey: ["ansich", "tasks", input.taskId],
        }),
      ]);
    },
  });
}

export function useAnsichTasks(
  limit = 100,
  enabled = true,
  lifecycleScope: AnsichTaskLifecycleScope = "all",
) {
  return useQuery({
    queryKey: ["ansich", "tasks", { limit, lifecycleScope }],
    queryFn: () => fetchAnsichTasks(limit, lifecycleScope),
    enabled,
    retry: false,
    refetchInterval: () =>
      taskListRefreshInterval(lifecycleScope, pageIsVisible()),
    refetchIntervalInBackground: false,
  });
}

export function useAnsichTaskHistory(limit = 100, enabled = true) {
  return useInfiniteQuery<
    AnsichTaskListResponse,
    Error,
    { pages: AnsichTaskListResponse[]; pageParams: Array<string | undefined> },
    readonly ["ansich", "tasks", "history", { limit: number }],
    string | undefined
  >({
    queryKey: ["ansich", "tasks", "history", { limit }] as const,
    queryFn: ({ pageParam }) =>
      fetchAnsichTasks(limit, "terminal", pageParam, true),
    initialPageParam: undefined,
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
    enabled,
    retry: false,
    refetchInterval: false,
    refetchIntervalInBackground: false,
  });
}

export function useAnsichTask(taskId: string, enabled = true) {
  return useQuery({
    queryKey: ["ansich", "tasks", taskId],
    queryFn: () => fetchAnsichTask(taskId),
    enabled: enabled && Boolean(taskId),
    retry: false,
    refetchInterval: (query) =>
      taskDetailRefreshInterval(query.state.data, pageIsVisible()),
    refetchIntervalInBackground: false,
  });
}

export function useAnsichTaskAgentRelease(
  taskId: string,
  enabled = true,
  polling = false,
) {
  return useQuery({
    queryKey: ["ansich", "tasks", taskId, "agent-release"],
    queryFn: () => fetchAnsichTaskAgentRelease(taskId),
    enabled: enabled && Boolean(taskId),
    retry: false,
    refetchInterval: (query) =>
      taskReleaseRefreshInterval(query.state.data, pageIsVisible(), polling),
    refetchIntervalInBackground: false,
  });
}

export function useAnsichAgentReleases(limit = 100, enabled = true) {
  return useQuery({
    queryKey: ["ansich", "agent-releases", { limit }],
    queryFn: () => fetchAnsichAgentReleases(limit),
    enabled,
    retry: false,
  });
}

export function useAnsichAgentReleaseComparison(
  leftReleaseId: string | null,
  rightReleaseId: string | null,
  enabled = true,
) {
  return useQuery({
    queryKey: [
      "ansich",
      "agent-releases",
      "compare",
      leftReleaseId,
      rightReleaseId,
    ],
    queryFn: () =>
      compareAnsichAgentReleases(leftReleaseId ?? "", rightReleaseId ?? ""),
    enabled:
      enabled &&
      Boolean(leftReleaseId) &&
      Boolean(rightReleaseId) &&
      leftReleaseId !== rightReleaseId,
    retry: false,
  });
}

export function useAnsichTaskTimeline(
  taskId: string,
  enabled = true,
  polling = true,
) {
  return useQuery({
    queryKey: ["ansich", "tasks", taskId, "timeline"],
    queryFn: () => fetchAnsichTaskTimeline(taskId),
    enabled: enabled && Boolean(taskId),
    retry: false,
    refetchInterval: () =>
      polling && pageIsVisible() ? REFRESH_INTERVAL_MS : false,
    refetchIntervalInBackground: false,
  });
}

export function useAnsichTaskCompressions(
  taskId: string,
  limit = 100,
  enabled = true,
  polling = true,
) {
  return useInfiniteQuery<
    AnsichContextCompressionListResponse,
    Error,
    {
      pages: AnsichContextCompressionListResponse[];
      pageParams: Array<string | undefined>;
    },
    readonly [
      "ansich",
      "tasks",
      string,
      "context-compressions",
      { limit: number },
    ],
    string | undefined
  >({
    queryKey: [
      "ansich",
      "tasks",
      taskId,
      "context-compressions",
      { limit },
    ] as const,
    queryFn: ({ pageParam }) =>
      fetchAnsichTaskCompressions(taskId, limit, pageParam),
    initialPageParam: undefined,
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
    enabled: enabled && Boolean(taskId),
    retry: false,
    refetchInterval: () =>
      polling && pageIsVisible() ? REFRESH_INTERVAL_MS : false,
    refetchIntervalInBackground: false,
  });
}

export function useAnsichTaskSteps(
  taskId: string,
  enabled = true,
  polling = true,
) {
  return useQuery({
    queryKey: ["ansich", "tasks", taskId, "steps"],
    queryFn: () => fetchAnsichTaskSteps(taskId),
    enabled: enabled && Boolean(taskId),
    retry: false,
    refetchInterval: () =>
      polling && pageIsVisible() ? REFRESH_INTERVAL_MS : false,
    refetchIntervalInBackground: false,
  });
}

export function useAnsichStepContext(
  stepId: string | null,
  enabled = true,
  polling = true,
) {
  return useQuery({
    queryKey: ["ansich", "steps", stepId, "context"],
    queryFn: () => fetchAnsichStepContext(stepId ?? ""),
    enabled: enabled && Boolean(stepId),
    retry: false,
    refetchInterval: () =>
      polling && pageIsVisible() ? REFRESH_INTERVAL_MS : false,
    refetchIntervalInBackground: false,
  });
}

export function useAnsichTaskUsage(
  taskId: string,
  enabled = true,
  polling = true,
  scope: "local" | "inclusive" = "local",
) {
  return useQuery({
    queryKey: ["ansich", "tasks", taskId, "usage", scope],
    queryFn: () => fetchAnsichTaskUsage(taskId, scope),
    enabled: enabled && Boolean(taskId),
    retry: false,
    refetchInterval: () =>
      polling && pageIsVisible() ? REFRESH_INTERVAL_MS : false,
    refetchIntervalInBackground: false,
  });
}

export function useAnsichTaskTree(
  taskId: string,
  enabled = true,
  polling = true,
) {
  return useQuery({
    queryKey: ["ansich", "tasks", taskId, "tree", "both", 4],
    queryFn: () => fetchAnsichTaskTree(taskId, "both", 4),
    enabled: enabled && Boolean(taskId),
    retry: false,
    refetchInterval: () =>
      polling && pageIsVisible() ? REFRESH_INTERVAL_MS : false,
    refetchIntervalInBackground: false,
  });
}

export function useAnsichTaskBudgets(
  taskId: string,
  enabled = true,
  polling = true,
) {
  return useQuery({
    queryKey: ["ansich", "tasks", taskId, "budgets"],
    queryFn: () => fetchAnsichTaskBudgets(taskId),
    enabled: enabled && Boolean(taskId),
    retry: false,
    refetchInterval: () =>
      polling && pageIsVisible() ? REFRESH_INTERVAL_MS : false,
    refetchIntervalInBackground: false,
  });
}

export function useAnsichTaskScopes(
  taskId: string,
  enabled = true,
  polling = true,
) {
  return useQuery({
    queryKey: ["ansich", "tasks", taskId, "scopes"],
    queryFn: () => fetchAnsichTaskScopes(taskId),
    enabled: enabled && Boolean(taskId),
    retry: false,
    refetchInterval: () =>
      polling && pageIsVisible() ? REFRESH_INTERVAL_MS : false,
    refetchIntervalInBackground: false,
  });
}

export function useAnsichToolAuthorization(
  toolCallId: string,
  enabled = true,
  polling = true,
) {
  return useQuery({
    queryKey: ["ansich", "tool-calls", toolCallId, "authorization"],
    queryFn: () => fetchAnsichToolAuthorization(toolCallId),
    enabled: enabled && Boolean(toolCallId),
    retry: false,
    refetchInterval: () =>
      polling && pageIsVisible() ? REFRESH_INTERVAL_MS : false,
    refetchIntervalInBackground: false,
  });
}

export function useAnsichToolEffects(
  toolCallId: string,
  enabled = true,
  polling = true,
) {
  return useQuery({
    queryKey: ["ansich", "tool-calls", toolCallId, "effects"],
    queryFn: () => fetchAnsichToolEffects(toolCallId),
    enabled: enabled && Boolean(toolCallId),
    retry: false,
    refetchInterval: () =>
      polling && pageIsVisible() ? REFRESH_INTERVAL_MS : false,
    refetchIntervalInBackground: false,
  });
}
