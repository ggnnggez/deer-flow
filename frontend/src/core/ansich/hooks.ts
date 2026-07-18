import { useQuery } from "@tanstack/react-query";

import {
  fetchAnsichStepContext,
  fetchAnsichActiveTasks,
  fetchAnsichTaskSteps,
  fetchAnsichTaskBudgets,
  fetchAnsichTask,
  fetchAnsichTaskTimeline,
  fetchAnsichTaskUsage,
  fetchAnsichTasks,
} from "./api";
import type { AnsichActiveTaskListResponse, AnsichTaskResponse } from "./types";

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

export function useAnsichTasks(limit = 100, enabled = true) {
  return useQuery({
    queryKey: ["ansich", "tasks", { limit }],
    queryFn: () => fetchAnsichTasks(limit),
    enabled,
    retry: false,
    refetchInterval: REFRESH_INTERVAL_MS,
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
