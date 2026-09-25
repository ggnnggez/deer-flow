import { ChevronLeftIcon, ChevronRightIcon, RefreshCwIcon, SearchIcon } from "lucide-react";
import type { KeyboardEvent, ReactNode } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ApiError, fetchHealth, fetchTaskList, fetchTaskResidency } from "./api";
import { LANE_SEGMENT_CLASS, ResidencyBoard, laneLabel } from "./board";
import {
  formatBytes,
  formatPercent,
  formatTokens,
  groupTasksByThread,
  healthLevel,
  peakLaneStack,
  rangeSince,
  secondsBetween,
  sparklinePath,
  throughputSeries,
  type TaskRange,
} from "./console";
import type { HealthResponse, ResidencyResponse, TaskListItem, TaskListResponse, TaskSort, ThroughputPoint } from "./contracts";
import { formatClock, formatDuration, formatTimestamp, messages, relativeTime, shortId, type Messages } from "./i18n";
import { Button, Skeleton, cn } from "./ui";

/**
 * The page: a task index to locate a recording, the extension's own health,
 * and the board for one task. URL state (`?tab=`, `?task=`, `?q=`, `?step=`)
 * is mirrored with `history.replaceState` so a view can be linked to; the
 * conversation-menu action arrives as `?thread=`, which becomes the query.
 */

export type Tab = "tasks" | "health" | "board";

export interface AppProps {
  base: string;
  locale: string | undefined;
  signal: AbortSignal;
  initialTab: Tab | null;
  initialQuery: string | null;
  initialTaskId: string | null;
  initialStepSeq: number | null;
}

const PAGE_SIZE = 50;
const HEALTH_POLL_MS = 15_000;
const SEARCH_DEBOUNCE_MS = 200;

type Kind = "" | "lead" | "subagent";
type Outcome = "" | "running" | "completed" | "failed" | "aborted";

interface ListFilters {
  q: string;
  kind: Kind;
  outcome: Outcome;
  range: TaskRange;
  comp: boolean;
  inc: boolean;
  sort: TaskSort;
  dir: "asc" | "desc";
  page: number;
}

interface Loaded<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
}

type LoadState<T> = { status: "idle" } | { status: "loading" } | { status: "error"; message: string } | { status: "ready"; data: T };

function describeError(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return `${fallback} (${error.status}: ${error.message})`;
  if (error instanceof Error) return `${fallback} (${error.message})`;
  return fallback;
}

function syncUrl(tab: Tab, taskId: string | null, query: string) {
  const url = new URL(window.location.href);
  url.searchParams.delete("thread");
  if (tab !== "tasks") url.searchParams.set("tab", tab);
  else url.searchParams.delete("tab");
  if (taskId) url.searchParams.set("task", taskId);
  else url.searchParams.delete("task");
  if (query.trim()) url.searchParams.set("q", query.trim());
  else url.searchParams.delete("q");
  window.history.replaceState(window.history.state, "", url);
}

function taskOutcome(task: TaskListItem): string {
  return task.outcome ?? (task.stopped_at ? "unknown" : "running");
}

export function ResidencyApp({ base, locale, signal, initialTab, initialQuery, initialTaskId, initialStepSeq }: AppProps) {
  const t = useMemo(() => messages(locale), [locale]);
  const [tab, setTab] = useState<Tab>(initialTaskId ? (initialTab ?? "board") : (initialTab === "board" ? "tasks" : (initialTab ?? "tasks")));
  const [filters, setFilters] = useState<ListFilters>({ q: initialQuery ?? "", kind: "", outcome: "", range: "24h", comp: false, inc: false, sort: "started", dir: "desc", page: 1 });
  const [group, setGroup] = useState<"thread" | "flat">("thread");
  const [list, setList] = useState<Loaded<TaskListResponse>>({ data: null, loading: true, error: null });
  const [listVersion, setListVersion] = useState(0);
  const [health, setHealth] = useState<Loaded<HealthResponse>>({ data: null, loading: true, error: null });
  const [healthVersion, setHealthVersion] = useState(0);
  const [healthRefreshedAt, setHealthRefreshedAt] = useState<Date | null>(null);
  const [taskId, setTaskId] = useState(initialTaskId);
  const [residency, setResidency] = useState<LoadState<ResidencyResponse>>({ status: "idle" });
  const [refreshing, setRefreshing] = useState(false);
  const [searchNotice, setSearchNotice] = useState<string | null>(null);
  const listRequest = useRef(0);
  const searchRef = useRef<HTMLInputElement>(null);

  const patchFilters = useCallback((patch: Partial<ListFilters>) => {
    setFilters((current) => ({ ...current, page: 1, ...patch }));
  }, []);

  // The task index: refetched (debounced) whenever a filter changes.
  useEffect(() => {
    const id = ++listRequest.current;
    setList((current) => ({ ...current, loading: true }));
    const timer = window.setTimeout(() => {
      fetchTaskList(
        base,
        {
          query: filters.q,
          kind: filters.kind,
          outcome: filters.outcome,
          since: rangeSince(filters.range, new Date()),
          hasCompactions: filters.comp,
          incompleteOnly: filters.inc,
          sort: filters.sort,
          direction: filters.dir,
          limit: PAGE_SIZE,
          offset: (filters.page - 1) * PAGE_SIZE,
        },
        signal,
      )
        .then((data) => {
          if (id === listRequest.current) setList({ data, loading: false, error: null });
        })
        .catch((error: unknown) => {
          if (signal.aborted || id !== listRequest.current) return;
          setList((current) => ({ ...current, loading: false, error: describeError(error, t.loadFailed) }));
        });
    }, SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [base, signal, filters, listVersion, t.loadFailed]);

  // Health: once for the tab's warning dot, then polled while the tab is open.
  useEffect(() => {
    let cancelled = false;
    const load = () => {
      fetchHealth(base, signal)
        .then((data) => {
          if (cancelled) return;
          setHealth({ data, loading: false, error: null });
          setHealthRefreshedAt(new Date());
        })
        .catch((error: unknown) => {
          if (cancelled || signal.aborted) return;
          setHealth((current) => ({ ...current, loading: false, error: describeError(error, t.loadFailed) }));
        });
    };
    load();
    const timer = tab === "health" ? window.setInterval(load, HEALTH_POLL_MS) : null;
    return () => {
      cancelled = true;
      if (timer !== null) window.clearInterval(timer);
    };
  }, [base, signal, tab, healthVersion, t.loadFailed]);

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
    if (taskId) void loadResidency(taskId);
    else setResidency({ status: "idle" });
  }, [taskId, loadResidency]);

  useEffect(() => {
    syncUrl(tab, taskId, filters.q);
  }, [tab, taskId, filters.q]);

  // "/" focuses the search from anywhere on the page (the surface lives in a shadow root, so look at the composed target).
  useEffect(() => {
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key !== "/" || event.isComposing || event.metaKey || event.ctrlKey || event.altKey) return;
      const target = event.composedPath()[0];
      if (target instanceof HTMLElement && ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) return;
      event.preventDefault();
      searchRef.current?.focus();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  const openTask = useCallback((id: string) => {
    setTaskId(id);
    setTab("board");
  }, []);

  const searchChanged = useCallback(
    (value: string) => {
      setSearchNotice(null);
      patchFilters({ q: value });
      const exact = list.data?.tasks.find((task) => task.task_id === value.trim());
      if (exact) openTask(exact.task_id);
    },
    [list.data, openTask, patchFilters],
  );

  const searchSubmitted = useCallback(async () => {
    const value = filters.q.trim();
    if (!value) return;
    const exact = list.data?.tasks.find((task) => task.task_id === value);
    if (exact) {
      openTask(exact.task_id);
      return;
    }
    if (/\s/.test(value)) return;
    try {
      const data = await fetchTaskResidency(base, value, signal);
      setResidency({ status: "ready", data });
      openTask(value);
    } catch (error) {
      if (signal.aborted) return;
      setSearchNotice(error instanceof ApiError && error.status === 404 ? t.searchNotFound(value) : describeError(error, t.loadFailed));
    }
  }, [base, filters.q, list.data, openTask, signal, t]);

  const level = health.data ? healthLevel(health.data.diagnostics) : "ok";
  const status = residency.status === "ready" ? residency.data.projection_status : list.data?.projection_status ?? null;
  const selectedTask = residency.status === "ready" ? residency.data.task : list.data?.tasks.find((task) => task.task_id === taskId) ?? null;

  return (
    <div className="space-y-4" data-residency-app>
      <p className="text-muted-foreground max-w-[68ch] text-sm">{t.lede}</p>
      <nav role="tablist" className="flex gap-1 border-b" aria-label={t.title}>
        <TabButton selected={tab === "tasks"} onClick={() => setTab("tasks")} label={t.tabTasks} count={list.data ? String(list.data.total) : null} controls="ctxres-tasks" />
        <TabButton selected={tab === "health"} onClick={() => setTab("health")} label={t.tabHealth} dot={level === "ok" ? null : level} controls="ctxres-health" />
        <TabButton selected={tab === "board"} onClick={() => taskId && setTab("board")} label={t.tabBoard} count={taskId ? shortId(taskId, 12) : t.noTaskSelected} disabled={!taskId} controls="ctxres-board" />
      </nav>

      {tab === "tasks" ? (
        <section id="ctxres-tasks" role="tabpanel" className="space-y-3" data-residency-tab="tasks">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <label className="bg-background focus-within:ring-ring flex h-8 min-w-0 flex-[1_1_280px] items-center gap-2 rounded-md border px-2 focus-within:ring-1">
              <SearchIcon className="text-muted-foreground size-3.5 shrink-0" aria-hidden />
              <input
                ref={searchRef}
                type="search"
                className="placeholder:text-muted-foreground min-w-0 flex-1 bg-transparent font-mono text-xs outline-none placeholder:font-sans"
                placeholder={t.searchPlaceholder}
                value={filters.q}
                autoComplete="off"
                spellCheck={false}
                onChange={(event) => searchChanged(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault();
                    void searchSubmitted();
                  }
                }}
                aria-label={t.searchPlaceholder}
              />
              <kbd className="text-muted-foreground rounded border px-1 font-mono text-[10px]">/</kbd>
            </label>
            <Select value={filters.kind} onChange={(value) => patchFilters({ kind: value as Kind })} options={[["", t.allKinds], ["lead", t.taskKindLead], ["subagent", t.taskKindSubagent]]} label={t.colTask} />
            <Select
              value={filters.outcome}
              onChange={(value) => patchFilters({ outcome: value as Outcome })}
              options={[["", t.allOutcomes], ["running", t.outcomeRunning], ["completed", t.outcomeCompleted], ["failed", t.outcomeFailed], ["aborted", t.outcomeAborted]]}
              label={t.colOutcome}
            />
            <Select value={filters.range} onChange={(value) => patchFilters({ range: value as TaskRange })} options={[["24h", t.range24h], ["7d", t.range7d], ["all", t.rangeAll]]} label={t.colStarted} />
            <Check checked={filters.comp} onChange={(comp) => patchFilters({ comp })} label={t.onlyCompactions} />
            <Check checked={filters.inc} onChange={(inc) => patchFilters({ inc })} label={t.onlyIncomplete} />
            <div className="bg-background inline-flex overflow-hidden rounded-md border" role="group">
              {(["thread", "flat"] as const).map((value) => (
                <button
                  key={value}
                  type="button"
                  aria-pressed={group === value}
                  onClick={() => setGroup(value)}
                  className={cn("h-7 px-2.5 text-xs", group === value ? "bg-muted font-semibold" : "text-muted-foreground hover:bg-muted/60")}
                >
                  {value === "thread" ? t.groupByThread : t.flat}
                </button>
              ))}
            </div>
            <Button size="sm" variant="ghost" onClick={() => setListVersion((n) => n + 1)} aria-label={t.refresh} title={t.refresh}>
              <RefreshCwIcon className={cn("size-3.5", list.loading && "animate-spin")} aria-hidden />
            </Button>
          </div>
          {searchNotice ? <p className="text-xs text-amber-600">{searchNotice}</p> : null}
          {list.error ? <p className="text-destructive text-xs">{list.error}</p> : null}
          {status && !status.running ? <p className="text-xs text-amber-600">{t.recordingOff}</p> : null}
          {list.data ? (
            <TaskTable
              response={list.data}
              filters={filters}
              group={group}
              loading={list.loading}
              locale={locale}
              t={t}
              selectedId={taskId}
              onSort={(sort) => patchFilters({ sort, dir: filters.sort === sort && filters.dir === "desc" ? "asc" : "desc" })}
              onSelect={(id) => setTaskId(id)}
              onOpen={openTask}
              onPage={(page) => setFilters((current) => ({ ...current, page }))}
              onShowAll={() => patchFilters({ range: "all" })}
            />
          ) : list.loading ? (
            <Skeleton className="h-64 w-full" />
          ) : null}
        </section>
      ) : null}

      {tab === "health" ? (
        <section id="ctxres-health" role="tabpanel" data-residency-tab="health">
          {health.error ? <p className="text-destructive mb-3 text-xs">{health.error}</p> : null}
          {health.data ? (
            <HealthView health={health.data} refreshedAt={healthRefreshedAt} loading={health.loading} locale={locale} t={t} onRefresh={() => setHealthVersion((n) => n + 1)} />
          ) : health.loading ? (
            <Skeleton className="h-64 w-full" />
          ) : null}
        </section>
      ) : null}

      {tab === "board" && taskId ? (
        <section id="ctxres-board" role="tabpanel" className="space-y-3" data-residency-tab="board">
          <div className="text-muted-foreground flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
            <Button size="sm" variant="ghost" className="h-7 px-2" onClick={() => setTab("tasks")}>
              <ChevronLeftIcon className="size-3.5" aria-hidden /> {t.backToList}
            </Button>
            <code className="text-foreground" title={taskId}>
              {taskId}
            </code>
            {selectedTask ? (
              <>
                <span>{selectedTask.kind === "lead" ? t.taskKindLead : t.taskKindSubagent}</span>
                {selectedTask.agent_name ? <span>{selectedTask.agent_name}</span> : null}
                <span>
                  {t.colThread} <code>{selectedTask.thread_id}</code>
                </span>
                <span title={formatTimestamp(selectedTask.started_at, locale)}>{relativeTime(selectedTask.started_at, new Date(), t)}</span>
              </>
            ) : null}
          </div>
          {status && !status.running ? <p className="text-xs text-amber-600">{t.recordingOff}</p> : null}
          {status && status.dropped > 0 ? <p className="text-xs text-amber-600">{t.dropped(status.dropped)}</p> : null}
          {residency.status === "loading" ? <Skeleton className="h-64 w-full" /> : null}
          {residency.status === "error" ? <p className="text-destructive rounded-md border p-3 text-sm">{residency.message}</p> : null}
          {residency.status === "ready" ? (
            <ResidencyBoard key={taskId} response={residency.data} locale={locale} t={t} refreshing={refreshing} onRefresh={() => void loadResidency(taskId, true)} seedStepSeq={initialStepSeq} />
          ) : null}
        </section>
      ) : null}
    </div>
  );
}

function TabButton({ selected, onClick, label, count, dot, disabled, controls }: { selected: boolean; onClick: () => void; label: string; count?: string | null; dot?: "warning" | "error" | null; disabled?: boolean; controls: string }) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={selected}
      aria-controls={controls}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "-mb-px inline-flex items-center gap-2 border-b-2 px-3 pt-2 pb-2.5 text-sm",
        selected ? "border-primary text-foreground font-semibold" : "text-muted-foreground border-transparent",
        disabled ? "cursor-default opacity-55" : "hover:text-foreground",
      )}
    >
      {dot ? <span className={cn("size-2 rounded-full", dot === "error" ? "bg-red-500 ring-[3px] ring-red-500/20" : "bg-amber-500 ring-[3px] ring-amber-500/20")} /> : null}
      {label}
      {count ? <span className="bg-muted text-muted-foreground rounded-full px-1.5 py-px font-mono text-[11px] font-medium">{count}</span> : null}
    </button>
  );
}

function Select({ value, onChange, options, label }: { value: string; onChange: (value: string) => void; options: Array<[string, string]>; label: string }) {
  return (
    <select value={value} onChange={(event) => onChange(event.target.value)} aria-label={label} className="bg-background h-8 rounded-md border px-2 text-xs">
      {options.map(([key, text]) => (
        <option key={key} value={key}>
          {text}
        </option>
      ))}
    </select>
  );
}

function Check({ checked, onChange, label }: { checked: boolean; onChange: (checked: boolean) => void; label: string }) {
  return (
    <label className="text-muted-foreground inline-flex items-center gap-1.5 whitespace-nowrap">
      <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} className="accent-blue-600" />
      {label}
    </label>
  );
}

const SORTABLE: Array<{ key: TaskSort; label: (t: Messages) => string; align?: "right" }> = [
  { key: "started", label: (t) => t.colStarted },
  { key: "duration", label: (t) => t.colDuration, align: "right" },
  { key: "attempts", label: (t) => t.colSteps, align: "right" },
  { key: "compactions", label: (t) => t.colCompactions, align: "right" },
  { key: "incomplete", label: (t) => t.colInventory },
  { key: "peak", label: (t) => t.colPeak },
];

function TaskTable({
  response,
  filters,
  group,
  loading,
  locale,
  t,
  selectedId,
  onSort,
  onSelect,
  onOpen,
  onPage,
  onShowAll,
}: {
  response: TaskListResponse;
  filters: ListFilters;
  group: "thread" | "flat";
  loading: boolean;
  locale: string | undefined;
  t: Messages;
  selectedId: string | null;
  onSort: (sort: TaskSort) => void;
  onSelect: (id: string) => void;
  onOpen: (id: string) => void;
  onPage: (page: number) => void;
  onShowAll: () => void;
}) {
  const now = new Date();
  const tasks = response.tasks;
  const threads = new Set(tasks.map((task) => task.thread_id)).size;
  const running = tasks.filter((task) => taskOutcome(task) === "running").length;
  const compactions = tasks.reduce((sum, task) => sum + task.compactions, 0);
  const incompleteTasks = tasks.filter((task) => task.incomplete_attempts > 0).length;
  const pages = Math.max(1, Math.ceil(response.total / PAGE_SIZE));
  const from = response.total === 0 ? 0 : response.offset + 1;
  const to = Math.min(response.total, response.offset + tasks.length);
  const rows = group === "thread" ? groupTasksByThread(tasks) : [{ threadId: null, rows: tasks.map((task) => ({ task, depth: 0 as const })), latestStartedAt: null }];
  const header = (key: TaskSort, label: string, align?: "right") => {
    const active = filters.sort === key;
    return (
      <th key={key} scope="col" className={cn("bg-card sticky top-0 px-2.5 py-2 text-[11px] font-semibold tracking-wide uppercase", align === "right" && "text-right")}>
        <button type="button" onClick={() => onSort(key)} className={cn("inline-flex items-center gap-1 hover:underline", active ? "text-foreground" : "text-muted-foreground")} aria-sort={active ? (filters.dir === "asc" ? "ascending" : "descending") : "none"}>
          {label}
          <span className="text-[10px]">{active ? (filters.dir === "asc" ? "↑" : "↓") : "↕"}</span>
        </button>
      </th>
    );
  };
  return (
    <div className="space-y-2">
      <div className="text-muted-foreground flex flex-wrap gap-x-4 gap-y-1 text-xs" data-residency-summary>
        <span>
          <b className="text-foreground font-semibold">{tasks.length}</b> {t.onThisPage}
        </span>
        <span>{t.summaryThreads(threads)}</span>
        <span>{t.summaryRunning(running)}</span>
        <span>{t.summaryCompactions(compactions)}</span>
        <span className={cn(incompleteTasks > 0 && "text-amber-600")}>{t.summaryIncomplete(incompleteTasks)}</span>
      </div>
      <div className={cn("bg-card overflow-x-auto rounded-md border", loading && "opacity-60")}>
        <table className="w-full min-w-[960px] border-collapse text-xs" data-residency-task-table>
          <thead>
            <tr className="border-b text-left">
              <th scope="col" className="bg-card text-muted-foreground sticky top-0 px-2.5 py-2 text-[11px] font-semibold tracking-wide uppercase">
                {t.colTask}
              </th>
              <th scope="col" className="bg-card text-muted-foreground sticky top-0 px-2.5 py-2 text-[11px] font-semibold tracking-wide uppercase">
                {t.colThread}
              </th>
              {SORTABLE.map((column) => header(column.key, column.label(t), column.align))}
              <th scope="col" className="bg-card text-muted-foreground sticky top-0 px-2.5 py-2 text-[11px] font-semibold tracking-wide uppercase">
                {t.colOutcome}
              </th>
              <th scope="col" className="bg-card sticky top-0" />
            </tr>
          </thead>
          <tbody>
            {tasks.length === 0 ? (
              <tr>
                <td colSpan={10} className="text-muted-foreground px-4 py-8 text-center">
                  {t.emptyList}
                  {filters.range !== "all" ? (
                    <>
                      {" "}
                      <button type="button" className="text-blue-600 underline-offset-2 hover:underline" onClick={onShowAll}>
                        {t.showAllTime}
                      </button>
                    </>
                  ) : null}
                </td>
              </tr>
            ) : (
              rows.map((section) => (
                <TableSection key={section.threadId ?? "flat"} section={section} now={now} locale={locale} t={t} selectedId={selectedId} onSelect={onSelect} onOpen={onOpen} />
              ))
            )}
          </tbody>
        </table>
      </div>
      <div className="text-muted-foreground flex flex-wrap items-center justify-between gap-2 px-0.5 text-xs">
        <span>{t.pageInfo(from, to, response.total, PAGE_SIZE)}</span>
        <div className="flex gap-1" role="navigation">
          <Button size="sm" className="h-6 min-w-6 px-1.5" disabled={filters.page <= 1} onClick={() => onPage(filters.page - 1)} aria-label="‹">
            <ChevronLeftIcon className="size-3.5" aria-hidden />
          </Button>
          {pageNumbers(filters.page, pages).map((page) => (
            <Button key={page} size="sm" variant={page === filters.page ? "secondary" : "outline"} className="h-6 min-w-6 px-1.5 font-mono" aria-current={page === filters.page ? "page" : undefined} onClick={() => onPage(page)}>
              {page}
            </Button>
          ))}
          <Button size="sm" className="h-6 min-w-6 px-1.5" disabled={filters.page >= pages} onClick={() => onPage(filters.page + 1)} aria-label="›">
            <ChevronRightIcon className="size-3.5" aria-hidden />
          </Button>
        </div>
      </div>
    </div>
  );
}

function pageNumbers(current: number, pages: number): number[] {
  const start = Math.max(1, Math.min(current - 3, pages - 6));
  const end = Math.min(pages, start + 6);
  const numbers: number[] = [];
  for (let page = start; page <= end; page += 1) numbers.push(page);
  return numbers;
}

function TableSection({
  section,
  now,
  locale,
  t,
  selectedId,
  onSelect,
  onOpen,
}: {
  section: { threadId: string | null; rows: Array<{ task: TaskListItem; depth: 0 | 1 }>; latestStartedAt: string | null };
  now: Date;
  locale: string | undefined;
  t: Messages;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onOpen: (id: string) => void;
}) {
  return (
    <>
      {section.threadId ? (
        <tr className="bg-muted/60 text-muted-foreground border-t" data-residency-thread-group={section.threadId}>
          <td colSpan={10} className="px-2.5 py-1.5">
            {t.colThread} <b className="text-foreground font-mono font-medium">{section.threadId}</b> · {t.tasksInThread(section.rows.length)} · {t.latest} {relativeTime(section.latestStartedAt, now, t)} ·{" "}
            <a className="text-blue-600 underline-offset-2 hover:underline" href={`/workspace/chats/${encodeURIComponent(section.threadId)}`}>
              {t.openInChat}
            </a>
          </td>
        </tr>
      ) : null}
      {section.rows.map(({ task, depth }) => (
        <TaskRow key={task.task_id} task={task} depth={depth} now={now} locale={locale} t={t} selected={task.task_id === selectedId} onSelect={() => onSelect(task.task_id)} onOpen={() => onOpen(task.task_id)} />
      ))}
    </>
  );
}

const OUTCOME_CLASS: Record<string, string> = {
  completed: "bg-emerald-500/10 text-emerald-700",
  running: "bg-blue-500/10 text-blue-600",
  failed: "bg-red-500/10 text-red-600",
  aborted: "bg-amber-500/10 text-amber-600",
};

function outcomeLabel(t: Messages, outcome: string): string {
  switch (outcome) {
    case "running":
      return t.outcomeRunning;
    case "completed":
      return t.outcomeCompleted;
    case "failed":
      return t.outcomeFailed;
    case "aborted":
      return t.outcomeAborted;
    default:
      return outcome;
  }
}

function TaskRow({ task, depth, now, locale, t, selected, onSelect, onOpen }: { task: TaskListItem; depth: 0 | 1; now: Date; locale: string | undefined; t: Messages; selected: boolean; onSelect: () => void; onOpen: () => void }) {
  const outcome = taskOutcome(task);
  const retries = Math.max(0, task.attempts - task.steps);
  const complete = task.attempts - task.incomplete_attempts;
  const completeShare = task.attempts > 0 ? complete / task.attempts : 1;
  const stack = peakLaneStack(task.peak_by_kind);
  const stackTotal = stack.reduce((sum, item) => sum + item.size, 0);
  const duration = task.duration_seconds !== null ? formatDuration(task.duration_seconds, t) : t.runningFor(formatDuration(secondsBetween(task.started_at, now) ?? 0, t));
  const onKey = (event: KeyboardEvent<HTMLTableRowElement>) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onOpen();
    }
  };
  return (
    <tr
      tabIndex={0}
      data-residency-task-row={task.task_id}
      aria-selected={selected}
      onClick={onSelect}
      onDoubleClick={onOpen}
      onKeyDown={onKey}
      className={cn("hover:bg-muted/50 cursor-pointer border-b whitespace-nowrap", selected && "bg-primary/10")}
    >
      <td className={cn("px-2.5 py-2", depth === 1 && "pl-7")}>
        {depth === 1 ? <span className="text-muted-foreground/70">↳ </span> : null}
        <span className="font-mono" title={task.task_id}>
          {shortId(task.task_id, 12)}
          {task.task_id.length > 12 ? "…" : ""}
        </span>
        <span className={cn("ml-1.5 rounded border px-1.5 py-px text-[10px] tracking-wide uppercase", task.kind === "lead" ? "border-blue-500/60 text-blue-600" : "text-muted-foreground")}>
          {task.kind === "lead" ? "lead" : "sub"}
        </span>
        {task.agent_name ? <span className="text-muted-foreground ml-1.5">{task.agent_name}</span> : null}
      </td>
      <td className="px-2.5 py-2">
        <span className="font-mono" title={task.thread_id}>
          {shortId(task.thread_id, 14)}
        </span>
      </td>
      <td className="px-2.5 py-2 tabular-nums" title={formatTimestamp(task.started_at, locale)}>
        {relativeTime(task.started_at, now, t)}
      </td>
      <td className="px-2.5 py-2 text-right tabular-nums">{duration}</td>
      <td className="px-2.5 py-2 text-right tabular-nums">
        {task.steps} / {task.attempts}
        {retries > 0 ? (
          <span className="text-muted-foreground ml-1" title={t.retries(retries)}>
            ↻{retries}
          </span>
        ) : null}
      </td>
      <td className="px-2.5 py-2 text-right tabular-nums">{task.compactions > 0 ? <span className="font-semibold text-violet-600">✂ {task.compactions}</span> : <span className="text-muted-foreground/60">–</span>}</td>
      <td className="px-2.5 py-2">
        <span className={cn("inline-flex items-center gap-1.5", task.incomplete_attempts > 0 && "text-amber-600")}>
          <span className="bg-muted flex h-1.5 w-16 overflow-hidden rounded-full">
            <i className="block h-full bg-emerald-500" style={{ width: `${completeShare * 100}%` }} />
            {task.incomplete_attempts > 0 ? <i className="block h-full bg-[repeating-linear-gradient(135deg,var(--color-amber-500,#f59e0b)_0_3px,transparent_3px_5px)]" style={{ width: `${(1 - completeShare) * 100}%` }} /> : null}
          </span>
          <span className="tabular-nums">{task.incomplete_attempts > 0 ? t.inventoryIncomplete(task.incomplete_attempts) : t.inventoryComplete}</span>
        </span>
      </td>
      <td className="px-2.5 py-2">
        <span className="inline-flex items-center gap-2">
          <span className="tabular-nums">{formatTokens(task.peak_tokens)}</span>
          {stackTotal > 0 ? (
            <span className="flex h-2 w-16 overflow-hidden rounded-[2px]" title={`${t.peakStackTitle}: ${stack.map((item) => `${laneLabel(t, item.lane)} ${formatPercent(item.size / stackTotal, 0)}`).join(" · ")}`}>
              {stack.map((item) => (
                <i key={item.lane} className={cn("block h-full", LANE_SEGMENT_CLASS[item.lane])} style={{ width: `${(item.size / stackTotal) * 100}%` }} />
              ))}
            </span>
          ) : null}
          {task.peak_context_window ? <span className="text-muted-foreground text-[11px] tabular-nums">{t.peakOfWindow(formatPercent(task.peak_tokens / task.peak_context_window))}</span> : null}
        </span>
      </td>
      <td className="px-2.5 py-2">
        <span className={cn("inline-flex items-center gap-1.5 rounded-full px-2 py-px text-[11px] font-medium", OUTCOME_CLASS[outcome] ?? "bg-muted text-muted-foreground")}>
          <span className="size-1.5 rounded-full bg-current" />
          {outcomeLabel(t, outcome)}
        </span>
      </td>
      <td className="px-2.5 py-2 text-right">
        <Button
          size="sm"
          className="h-6 px-2 text-[11px]"
          onClick={(event) => {
            event.stopPropagation();
            onOpen();
          }}
        >
          {t.openBoard}
        </Button>
      </td>
    </tr>
  );
}

/* ----------------------------------------------------------------------- */
/* Health                                                                   */
/* ----------------------------------------------------------------------- */

function HealthView({ health, refreshedAt, loading, locale, t, onRefresh }: { health: HealthResponse; refreshedAt: Date | null; loading: boolean; locale: string | undefined; t: Messages; onRefresh: () => void }) {
  const now = new Date();
  const status = health.status;
  const storage = health.storage;
  const quality = health.quality;
  const config = health.config;
  const state = status.running ? "running" : status.enabled ? "stopped" : "disabled";
  const series = useMemo(() => throughputSeries(health.throughput, new Date()), [health.throughput]);
  const peak = series.reduce((best, point) => (point.events > best.events ? point : best), series[0] ?? { minute: "", events: 0 });
  const current = series[series.length - 1]?.events ?? 0;
  const rows = storage?.rows ?? {};
  const prefix = storage?.table_prefix ?? status.table_prefix ?? "ctxres_";
  const tasksRows = rows[`${prefix}tasks`] ?? 0;
  const attemptsRows = rows[`${prefix}attempts`] ?? 0;
  const membersRows = rows[`${prefix}members`] ?? 0;
  const compactionsRows = rows[`${prefix}compactions`] ?? 0;
  return (
    <div className="space-y-3" data-residency-health={state}>
      <div className="bg-card flex flex-wrap items-center gap-x-4 gap-y-2 rounded-md border px-3.5 py-3 text-xs">
        <span className="inline-flex items-center gap-2 text-sm font-semibold">
          <span className={cn("size-2.5 rounded-full ring-4", state === "running" ? "bg-emerald-500 ring-emerald-500/15" : state === "stopped" ? "bg-red-500 ring-red-500/15" : "bg-muted-foreground ring-muted-foreground/15")} />
          {state === "running" ? t.recording : state === "stopped" ? t.notRecording : t.recordingDisabled}
        </span>
        <div className="text-muted-foreground flex flex-wrap gap-x-3.5 gap-y-1">
          <span>
            {t.database} <b className="text-foreground font-medium">{storage?.backend ?? "—"}</b>
          </span>
          <span>
            {t.tablePrefix} <code>{prefix}</code>
          </span>
          <span>
            {t.lastWrite} <b className="text-foreground font-medium tabular-nums">{relativeTime(status.last_flush_at, now, t)}</b>
          </span>
          <span>
            {t.lastEvent} <b className="text-foreground font-medium tabular-nums">{relativeTime(status.last_event_at, now, t)}</b>
          </span>
          <span>
            {t.uptime} <b className="text-foreground font-medium tabular-nums">{status.uptime_seconds != null ? formatDuration(status.uptime_seconds, t) : "—"}</b>
          </span>
        </div>
        <span className="flex-1" />
        <Button size="sm" className="h-7" onClick={onRefresh}>
          <RefreshCwIcon className={cn("size-3.5", loading && "animate-spin")} aria-hidden />
          {refreshedAt ? t.refreshedAt(formatClock(refreshedAt.toISOString(), locale)) : t.refresh}
        </Button>
      </div>

      <div className="grid grid-cols-[repeat(auto-fit,minmax(150px,1fr))] gap-2.5">
        <Tile label={t.queueDepth} value={<>{status.queue_depth} <span className="text-muted-foreground text-xs font-normal">/ {status.queue_capacity ?? "?"}</span></>} sub={t.flushEvery(status.flush_interval_ms ?? config.flush_interval_ms)} />
        <Tile label={t.accepted} value={status.accepted} sub={t.sinceStart} />
        <Tile label={t.written} value={status.flushed} sub={status.last_batch_events ? t.lastBatch(status.last_batch_events, status.last_batch_ms ?? 0) : t.noBatchYet} />
        <Tile label={t.droppedTile} value={status.dropped} warn={status.dropped > 0} sub={status.dropped > 0 ? t.lastDropAt(formatClock(status.last_drop_at ?? null, locale)) : t.noDrops} />
        <Tile label={t.writeFailures} value={status.write_failures} warn={status.write_failures > 0} sub={t.writeFailuresSub} />
        <Tile label={t.estimator} value={<code className="text-[13px] break-all">{status.estimator}</code>} sub={t.readCap(status.max_attempts)} />
      </div>

      <div className="grid grid-cols-[repeat(auto-fit,minmax(320px,1fr))] gap-3">
        <PanelCard title={t.throughput} sub={t.throughputSub}>
          <Sparkline series={series} label={t.throughputSub} />
          <dl className="mt-2 grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-xs">
            <dt className="text-muted-foreground">{t.peakPerMinute}</dt>
            <dd className="tabular-nums">
              {t.perMinute(peak.events)}
              {peak.events > 0 ? ` (${formatClock(peak.minute.replace("Z", ":00Z"), locale)})` : ""}
            </dd>
            <dt className="text-muted-foreground">{t.currentPerMinute}</dt>
            <dd className="tabular-nums">{t.perMinute(current)}</dd>
          </dl>
        </PanelCard>

        <PanelCard title={t.storage} sub={t.storageSub}>
          {storage ? (
            <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1.5 text-xs">
              <dt>
                <code>{prefix}tasks</code>
              </dt>
              <dd className="tabular-nums">
                {t.rows(tasksRows)} · {t.openTasks(quality?.tasks_open ?? 0)}
              </dd>
              <dt>
                <code>{prefix}attempts</code>
              </dt>
              <dd className="tabular-nums">
                {t.rows(attemptsRows)} · {t.avgPerTask(tasksRows > 0 ? (attemptsRows / tasksRows).toFixed(1) : "0")}
              </dd>
              <dt>
                <code>{prefix}members</code>
              </dt>
              <dd className="tabular-nums">
                {t.rows(membersRows)} · {t.avgPerAttempt(attemptsRows > 0 ? (membersRows / attemptsRows).toFixed(1) : "0")}
              </dd>
              <dt>
                <code>{prefix}compactions</code>
              </dt>
              <dd className="tabular-nums">{t.rows(compactionsRows)}</dd>
              <dt className="text-muted-foreground">{t.databaseFile}</dt>
              <dd className="font-mono break-all">
                {storage.database ?? storage.backend}
                {storage.file_bytes != null ? ` · ${formatBytes(storage.file_bytes)}` : ""}
              </dd>
              <dt className="text-muted-foreground">{t.earliestRecord}</dt>
              <dd className="tabular-nums">{formatTimestamp(storage.earliest_task_started_at, locale)}</dd>
              <dt className="text-muted-foreground">{t.retention}</dt>
              <dd>{t.retentionNone}</dd>
            </dl>
          ) : (
            <p className="text-muted-foreground text-xs">{t.noStorage}</p>
          )}
        </PanelCard>

        <PanelCard title={t.quality} sub={t.qualitySub}>
          {quality ? (
            <div className="space-y-2.5">
              <QualityRow label={t.qComplete} value={`${quality.attempts_complete} / ${quality.attempts_total}${quality.attempts_total > 0 ? ` · ${formatPercent(quality.attempts_complete / quality.attempts_total)}` : ""}`} fraction={quality.attempts_total > 0 ? quality.attempts_complete / quality.attempts_total : 1} />
              <QualityRow label={t.qIncomplete} value={String(quality.attempts_incomplete)} fraction={quality.attempts_total > 0 ? quality.attempts_incomplete / quality.attempts_total : 0} warn={quality.attempts_incomplete > 0} />
              <QualityRow label={t.qPositioned} value={`${quality.compactions_positioned} / ${quality.compactions_total}`} fraction={quality.compactions_total > 0 ? quality.compactions_positioned / quality.compactions_total : 1} />
              <QualityRow label={t.qUnanchored} value={String(quality.compactions_unanchored)} fraction={quality.compactions_total > 0 ? quality.compactions_unanchored / quality.compactions_total : 0} warn={quality.compactions_unanchored > 0} />
              <QualityRow label={t.qStale(quality.stale_after_minutes)} value={String(quality.tasks_stale)} fraction={tasksRows > 0 ? quality.tasks_stale / tasksRows : 0} warn={quality.tasks_stale > 0} />
            </div>
          ) : (
            <p className="text-muted-foreground text-xs">{t.noStorage}</p>
          )}
        </PanelCard>

        <PanelCard title={t.diagnostics} sub={t.items(health.diagnostics.length)}>
          <ul className="space-y-2" data-residency-diagnostics>
            {health.diagnostics.map((diagnostic) => {
              const copy = t.diagnosticCopy(diagnostic, health);
              return (
                <li
                  key={diagnostic.code}
                  data-level={diagnostic.level}
                  className={cn("grid grid-cols-[8px_1fr] gap-2.5 rounded-md border px-3 py-2.5", diagnostic.level === "warning" && "border-amber-500/60 bg-amber-500/10", diagnostic.level === "error" && "border-red-500/60 bg-red-500/10")}
                >
                  <i className={cn("mt-1.5 size-2 rounded-full", diagnostic.level === "ok" ? "bg-emerald-500" : diagnostic.level === "warning" ? "bg-amber-500" : "bg-red-500")} />
                  <div className="min-w-0">
                    <b className="block text-sm font-semibold">{copy.title}</b>
                    <p className="text-muted-foreground mt-0.5 text-xs">{copy.detail}</p>
                    {copy.remedy ? (
                      <p className="mt-1 text-xs">
                        {t.remedy}: {copy.remedy}
                      </p>
                    ) : null}
                    {diagnostic.affected.length > 0 ? (
                      <p className="mt-1 font-mono text-xs break-all">
                        {t.affectedTasks}: {diagnostic.affected.map((id) => shortId(id, 12)).join(", ")}
                      </p>
                    ) : null}
                  </div>
                </li>
              );
            })}
          </ul>
        </PanelCard>
      </div>

      <PanelCard title={t.configEcho} sub={t.configEchoSub}>
        <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 font-mono text-xs">
          <dt className="text-muted-foreground">enabled</dt>
          <dd>{String(config.enabled)}</dd>
          <dt className="text-muted-foreground">max_attempts</dt>
          <dd>{config.max_attempts}</dd>
          <dt className="text-muted-foreground">queue_capacity</dt>
          <dd>{config.queue_capacity}</dd>
          <dt className="text-muted-foreground">flush_interval_ms</dt>
          <dd>{config.flush_interval_ms}</dd>
          <dt className="text-muted-foreground">stale_task_after_minutes</dt>
          <dd>{config.stale_task_after_minutes}</dd>
          <dt className="text-muted-foreground">context_windows</dt>
          <dd className="break-all">{Object.keys(config.context_windows).length > 0 ? JSON.stringify(config.context_windows) : t.notConfigured}</dd>
          <dt className="text-muted-foreground">default_context_window</dt>
          <dd>{config.default_context_window ?? t.notConfigured}</dd>
          <dt className="text-muted-foreground">table_prefix</dt>
          <dd>{config.table_prefix}</dd>
          <dt className="text-muted-foreground font-sans">{t.extensionVersion}</dt>
          <dd>{config.extension_version ? `deerflow-extension-context-residency ${config.extension_version}` : t.unknownVersion}</dd>
          <dt className="text-muted-foreground font-sans">{t.apiVersion}</dt>
          <dd>{config.api_version ?? "—"}</dd>
          <dt className="text-muted-foreground font-sans">{t.placements}</dt>
          <dd>{[...config.placements, config.scopes.join(" + ")].join(" · ")}</dd>
        </dl>
      </PanelCard>
    </div>
  );
}

function Tile({ label, value, sub, warn }: { label: string; value: ReactNode; sub: string; warn?: boolean }) {
  return (
    <div className={cn("bg-card min-w-0 rounded-md border px-3.5 py-3", warn && "border-amber-500")}>
      <div className="text-muted-foreground flex justify-between gap-1.5 text-[11px] font-semibold tracking-wide uppercase">
        {label}
        {warn ? <span aria-hidden>⚠</span> : null}
      </div>
      <div className={cn("mt-1 text-2xl font-semibold tabular-nums", warn && "text-amber-600")}>{value}</div>
      <div className="text-muted-foreground mt-0.5 text-xs">{sub}</div>
    </div>
  );
}

function PanelCard({ title, sub, children }: { title: string; sub: string; children: ReactNode }) {
  return (
    <section className="bg-card min-w-0 rounded-md border p-3.5">
      <h2 className="text-muted-foreground mb-2.5 flex flex-wrap items-baseline justify-between gap-2 text-[11px] font-semibold tracking-wide uppercase">
        {title}
        <span className="font-normal tracking-normal normal-case">{sub}</span>
      </h2>
      {children}
    </section>
  );
}

function QualityRow({ label, value, fraction, warn }: { label: string; value: string; fraction: number; warn?: boolean }) {
  return (
    <div className="grid grid-cols-[1fr_max-content] items-center gap-x-2.5 gap-y-1 text-xs">
      <span className="text-muted-foreground">{label}</span>
      <span className={cn("font-semibold tabular-nums", warn && "text-amber-600")}>{value}</span>
      <span className="bg-muted col-span-2 h-1.5 overflow-hidden rounded-full">
        <i className={cn("block h-full", warn ? "bg-amber-500" : "bg-emerald-500")} style={{ width: `${Math.min(100, Math.max(0, fraction * 100))}%` }} />
      </span>
    </div>
  );
}

function Sparkline({ series, label }: { series: ThroughputPoint[]; label: string }) {
  const width = 600;
  const height = 88;
  const pad = 4;
  const values = series.map((point) => point.events);
  const { line, area, max } = sparklinePath(values, width, height, pad);
  const y = (value: number) => height - pad - (value / max) * (height - pad * 2);
  return (
    <div className="relative">
      <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" className="block h-22 w-full" role="img" aria-label={label}>
        {[0, max / 2, max].map((value) => (
          <line key={value} x1={pad} x2={width - pad} y1={y(value)} y2={y(value)} className="stroke-border" strokeWidth={1} vectorEffect="non-scaling-stroke" />
        ))}
        <path d={area} className="fill-indigo-500/15" />
        <path d={line} className="fill-none stroke-indigo-500" strokeWidth={1.6} strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
      </svg>
      <span className="text-muted-foreground absolute top-0 right-1 font-mono text-[10px]">{max}</span>
      <span className="text-muted-foreground absolute right-1 bottom-0 font-mono text-[10px]">0</span>
    </div>
  );
}
