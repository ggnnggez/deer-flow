import { useQuery } from "@tanstack/react-query";

import {
  fetchAnsichTask,
  fetchAnsichTaskTimeline,
  fetchAnsichTasks,
} from "./api";

const REFRESH_INTERVAL_MS = 5_000;

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
    refetchInterval: REFRESH_INTERVAL_MS,
    refetchIntervalInBackground: false,
  });
}

export function useAnsichTaskTimeline(taskId: string, enabled = true) {
  return useQuery({
    queryKey: ["ansich", "tasks", taskId, "timeline"],
    queryFn: () => fetchAnsichTaskTimeline(taskId),
    enabled: enabled && Boolean(taskId),
    retry: false,
    refetchInterval: REFRESH_INTERVAL_MS,
    refetchIntervalInBackground: false,
  });
}
