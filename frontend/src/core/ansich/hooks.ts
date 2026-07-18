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
  fetchAnsichAlert,
  fetchAnsichAlerts,
  fetchAnsichStepContext,
  fetchAnsichActiveTasks,
  fetchAnsichTaskCompressions,
  fetchAnsichTaskSteps,
  fetchAnsichTaskBudgets,
  fetchAnsichTask,
  fetchAnsichTaskTimeline,
  fetchAnsichTaskUsage,
  fetchAnsichTasks,
} from "./api";
import type {
  AnsichActiveTaskListResponse,
  AnsichAlertListResponse,
  AnsichContextCompressionListResponse,
  AnsichTaskLifecycleScope,
  AnsichTaskListResponse,
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
    queryFn: ({ pageParam }) => fetchAnsichTasks(limit, "terminal", pageParam),
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
) {
  return useQuery({
    queryKey: ["ansich", "tasks", taskId, "usage"],
    queryFn: () => fetchAnsichTaskUsage(taskId),
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
