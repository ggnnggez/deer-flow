import { useCallback, useEffect, useMemo, useState } from "react";

import { ApiError, fetchTaskResidency, fetchThreadTasks } from "./api";
import { ResidencyBoard } from "./board";
import type { ResidencyResponse, ResidencyTask } from "./contracts";
import { formatTimestamp, messages, shortId } from "./i18n";
import { Button, Skeleton } from "./ui";

/**
 * The page: pick a recorded task (by conversation or by id), read its
 * residency, show the board. URL state (`?thread=`, `?task=`, `?step=`) is
 * mirrored with `history.replaceState` so a view can be linked to.
 */

export interface AppProps {
  base: string;
  locale: string | undefined;
  signal: AbortSignal;
  initialThreadId: string | null;
  initialTaskId: string | null;
  initialStepSeq: number | null;
}

type LoadState<T> = { status: "idle" } | { status: "loading" } | { status: "error"; message: string } | { status: "ready"; data: T };

function describeError(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return `${fallback} (${error.status}: ${error.message})`;
  if (error instanceof Error) return `${fallback} (${error.message})`;
  return fallback;
}

function syncUrl(threadId: string | null, taskId: string | null) {
  const url = new URL(window.location.href);
  if (threadId) url.searchParams.set("thread", threadId);
  else url.searchParams.delete("thread");
  if (taskId) url.searchParams.set("task", taskId);
  else url.searchParams.delete("task");
  window.history.replaceState(window.history.state, "", url);
}

export function ResidencyApp({ base, locale, signal, initialThreadId, initialTaskId, initialStepSeq }: AppProps) {
  const t = useMemo(() => messages(locale), [locale]);
  const [threadId, setThreadId] = useState(initialThreadId);
  const [taskId, setTaskId] = useState(initialTaskId);
  const [threadInput, setThreadInput] = useState(initialThreadId ?? "");
  const [taskInput, setTaskInput] = useState(initialTaskId ?? "");
  const [tasks, setTasks] = useState<LoadState<ResidencyTask[]>>({ status: "idle" });
  const [residency, setResidency] = useState<LoadState<ResidencyResponse>>({ status: "idle" });
  const [refreshing, setRefreshing] = useState(false);

  const loadTasks = useCallback(
    async (thread: string) => {
      setTasks({ status: "loading" });
      try {
        const response = await fetchThreadTasks(base, thread, signal);
        setTasks({ status: "ready", data: response.tasks });
        return response.tasks;
      } catch (error) {
        if (signal.aborted) return [];
        setTasks({ status: "error", message: describeError(error, t.loadFailed) });
        return [];
      }
    },
    [base, signal, t.loadFailed],
  );

  const loadResidency = useCallback(
    async (task: string, quiet = false) => {
      if (quiet) setRefreshing(true);
      else setResidency({ status: "loading" });
      try {
        const data = await fetchTaskResidency(base, task, signal);
        setResidency({ status: "ready", data });
      } catch (error) {
        if (signal.aborted) return;
        setResidency({ status: "error", message: describeError(error, t.loadFailed) });
      } finally {
        setRefreshing(false);
      }
    },
    [base, signal, t.loadFailed],
  );

  useEffect(() => {
    void (async () => {
      if (threadId) {
        const list = await loadTasks(threadId);
        if (!taskId && list.length > 0) {
          const lead = list.find((task) => task.kind === "lead") ?? list[0]!;
          setTaskId(lead.task_id);
          setTaskInput(lead.task_id);
        }
      }
    })();
    // The initial read only: later thread changes go through the form handlers.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    syncUrl(threadId, taskId);
    if (taskId) void loadResidency(taskId);
    else setResidency({ status: "idle" });
  }, [taskId, threadId, loadResidency]);

  const submitThread = useCallback(() => {
    const next = threadInput.trim();
    setThreadId(next || null);
    setTaskId(null);
    setTaskInput("");
    if (next) {
      void loadTasks(next).then((list) => {
        const lead = list.find((task) => task.kind === "lead") ?? list[0];
        if (lead) {
          setTaskId(lead.task_id);
          setTaskInput(lead.task_id);
        }
      });
    } else {
      setTasks({ status: "idle" });
    }
  }, [loadTasks, threadInput]);

  const submitTask = useCallback(() => {
    const next = taskInput.trim();
    setTaskId(next || null);
  }, [taskInput]);

  const status = residency.status === "ready" ? residency.data.projection_status : null;

  return (
    <div className="space-y-4" data-residency-app>
      <form
        className="flex flex-wrap items-end gap-3 text-xs"
        onSubmit={(event) => {
          event.preventDefault();
          submitThread();
        }}
      >
        <label className="flex flex-col gap-1">
          <span className="text-muted-foreground">{t.threadLabel}</span>
          <input
            className="bg-background h-8 w-72 rounded-md border px-2 font-mono"
            value={threadInput}
            onChange={(event) => setThreadInput(event.target.value)}
            spellCheck={false}
          />
        </label>
        <Button size="sm" type="submit">
          {t.load}
        </Button>
        <label className="flex flex-col gap-1">
          <span className="text-muted-foreground">{t.taskLabel}</span>
          <input
            className="bg-background h-8 w-72 rounded-md border px-2 font-mono"
            value={taskInput}
            onChange={(event) => setTaskInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                submitTask();
              }
            }}
            spellCheck={false}
          />
        </label>
        <Button size="sm" onClick={submitTask}>
          {t.load}
        </Button>
      </form>
      {tasks.status === "loading" ? <Skeleton className="h-8 w-full" /> : null}
      {tasks.status === "error" ? <p className="text-destructive text-xs">{tasks.message}</p> : null}
      {tasks.status === "ready" ? (
        <div className="space-y-1">
          <div className="text-muted-foreground text-[10px] font-semibold tracking-wide uppercase">{t.tasks}</div>
          {tasks.data.length === 0 ? (
            <p className="text-muted-foreground text-xs">{t.noTasks}</p>
          ) : (
            <ul className="flex flex-wrap gap-1.5" data-residency-tasks>
              {tasks.data.map((task) => (
                <li key={task.task_id}>
                  <button
                    type="button"
                    aria-pressed={task.task_id === taskId}
                    onClick={() => {
                      setTaskId(task.task_id);
                      setTaskInput(task.task_id);
                    }}
                    title={`${task.task_id} · ${formatTimestamp(task.started_at, locale)}`}
                    className={
                      task.task_id === taskId
                        ? "bg-primary text-primary-foreground rounded-full border px-2 py-0.5 text-xs"
                        : "hover:bg-muted rounded-full border px-2 py-0.5 text-xs"
                    }
                  >
                    {task.kind === "lead" ? t.taskKindLead : t.taskKindSubagent}
                    {task.agent_name ? ` · ${task.agent_name}` : ""} · <span className="font-mono">{shortId(task.task_id)}</span>
                    {task.outcome ? ` · ${task.outcome}` : ""}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}
      {status && !status.running ? <p className="text-xs text-amber-600">{t.recordingOff}</p> : null}
      {status && status.dropped > 0 ? <p className="text-xs text-amber-600">{t.dropped(status.dropped)}</p> : null}
      {residency.status === "loading" ? <Skeleton className="h-64 w-full" /> : null}
      {residency.status === "error" ? <p className="text-destructive rounded-md border p-3 text-sm">{residency.message}</p> : null}
      {residency.status === "ready" && taskId ? (
        <ResidencyBoard
          key={taskId}
          response={residency.data}
          locale={locale}
          t={t}
          refreshing={refreshing}
          onRefresh={() => void loadResidency(taskId, true)}
          seedStepSeq={initialStepSeq}
        />
      ) : null}
    </div>
  );
}
