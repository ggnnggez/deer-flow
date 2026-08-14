"use client";

import type { Message } from "@langchain/langgraph-sdk";
import { useVirtualizer } from "@tanstack/react-virtual";
import {
  BotIcon,
  ChevronDownIcon,
  ChevronRightIcon,
  Clock3Icon,
  Loader2Icon,
  SearchIcon,
  SettingsIcon,
  TerminalIcon,
  UserIcon,
  WrenchIcon,
  XIcon,
} from "lucide-react";
import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useI18n } from "@/core/i18n/hooks";
import {
  buildTrajectoryRows,
  projectTrajectory,
  type TrajectoryRecord,
  type TrajectoryRecordKind,
} from "@/core/trajectory";
import { cn } from "@/lib/utils";

const ROW_OVERSCAN = 12;
const BOTTOM_FOLLOW_THRESHOLD = 24;

const RECORD_ICONS: Record<TrajectoryRecordKind, ReactNode> = {
  assistant: <BotIcon className="size-3.5" />,
  system: <SettingsIcon className="size-3.5" />,
  tool: <WrenchIcon className="size-3.5" />,
  user: <UserIcon className="size-3.5" />,
};

function formatTokenCount(value: number) {
  return value.toLocaleString();
}

function preview(value: string, limit = 360) {
  const normalized = value.replace(/\s+/g, " ").trim();
  return normalized.length > limit
    ? `${normalized.slice(0, limit).trimEnd()}…`
    : normalized;
}

function RecordDetails({
  onClose,
  record,
}: {
  onClose: () => void;
  record: TrajectoryRecord;
}) {
  const { t } = useI18n();
  return (
    <aside
      aria-label={t.trajectory.details}
      className="bg-background absolute inset-y-0 right-0 z-20 flex w-[min(90%,32rem)] flex-col border-l shadow-xl lg:static lg:z-auto lg:w-auto lg:shadow-none"
    >
      <header className="flex h-11 shrink-0 items-center gap-2 border-b px-3">
        <span className="text-muted-foreground">
          {RECORD_ICONS[record.kind]}
        </span>
        <div className="min-w-0 flex-1 truncate text-sm font-medium">
          {record.label}
        </div>
        <Button
          aria-label={t.common.close}
          size="icon-sm"
          variant="ghost"
          onClick={onClose}
        >
          <XIcon />
        </Button>
      </header>
      <div className="min-h-0 flex-1 space-y-5 overflow-auto p-4 text-sm">
        {record.usage && (
          <section>
            <h3 className="text-muted-foreground mb-2 text-xs font-medium uppercase">
              {t.tokenUsage.title}
            </h3>
            <dl className="grid grid-cols-3 gap-2">
              {[
                [t.trajectory.inputTokens, record.usage.inputTokens],
                [t.trajectory.outputTokens, record.usage.outputTokens],
                [t.trajectory.totalTokens, record.usage.totalTokens],
              ].map(([label, value]) => (
                <div key={String(label)} className="bg-muted/50 rounded-md p-2">
                  <dt className="text-muted-foreground text-xs">{label}</dt>
                  <dd className="mt-1 font-mono tabular-nums">
                    {formatTokenCount(Number(value))}
                  </dd>
                </div>
              ))}
            </dl>
          </section>
        )}
        <DetailBlock
          label={record.kind === "tool" ? t.trajectory.request : record.label}
          value={record.content}
        />
        {record.result !== undefined && (
          <DetailBlock label={t.trajectory.result} value={record.result} />
        )}
      </div>
    </aside>
  );
}

function DetailBlock({ label, value }: { label: string; value: string }) {
  return (
    <section>
      <h3 className="text-muted-foreground mb-2 text-xs font-medium uppercase">
        {label}
      </h3>
      <pre className="bg-muted/50 max-h-96 overflow-auto rounded-lg p-3 font-mono text-xs leading-relaxed break-words whitespace-pre-wrap">
        {value || "—"}
      </pre>
    </section>
  );
}

export function TrajectoryView({
  hasMoreHistory,
  isHistoryLoading,
  isStreaming,
  loadMoreHistory,
  messages,
}: {
  hasMoreHistory?: boolean;
  isHistoryLoading?: boolean;
  isStreaming?: boolean;
  loadMoreHistory?: () => void;
  messages: Message[];
}) {
  const { t } = useI18n();
  const turns = useMemo(() => projectTrajectory(messages), [messages]);
  const [query, setQuery] = useState("");
  const [collapsedTurnIds, setCollapsedTurnIds] = useState<ReadonlySet<string>>(
    () => new Set(),
  );
  const [selectedRecordId, setSelectedRecordId] = useState<string | null>(null);
  const rows = useMemo(
    () => buildTrajectoryRows(turns, { collapsedTurnIds, query }),
    [collapsedTurnIds, query, turns],
  );
  const selectedRecord = useMemo(
    () =>
      turns
        .flatMap((turn) => turn.records)
        .find((record) => record.id === selectedRecordId) ?? null,
    [selectedRecordId, turns],
  );
  const scrollerRef = useRef<HTMLDivElement>(null);
  const followsTail = useRef(true);
  const initialized = useRef(false);
  const olderAnchor = useRef<number | null>(null);
  const virtualizer = useVirtualizer({
    count: rows.length,
    estimateSize: (index) => (rows[index]?.type === "turn" ? 42 : 76),
    getItemKey: (index) => rows[index]?.id ?? index,
    getScrollElement: () => scrollerRef.current,
    overscan: ROW_OVERSCAN,
  });

  useEffect(() => {
    if (selectedRecordId !== null && selectedRecord === null) {
      setSelectedRecordId(null);
    }
  }, [selectedRecord, selectedRecordId]);

  useLayoutEffect(() => {
    const scroller = scrollerRef.current;
    if (!scroller || rows.length === 0) {
      return;
    }
    if (!initialized.current || followsTail.current) {
      initialized.current = true;
      virtualizer.scrollToIndex(rows.length - 1, { align: "end" });
    }
  }, [rows.length, virtualizer]);

  useLayoutEffect(() => {
    const scroller = scrollerRef.current;
    if (!scroller || isHistoryLoading || olderAnchor.current === null) {
      return;
    }
    scroller.scrollTop += scroller.scrollHeight - olderAnchor.current;
    olderAnchor.current = null;
  }, [isHistoryLoading, rows.length]);

  const allCollapsed =
    turns.length > 0 && collapsedTurnIds.size === turns.length;
  const visibleItems = virtualizer.getVirtualItems();
  const totalDuration = turns.reduce(
    (sum, turn) => sum + Math.max(turn.durationSeconds ?? 1, 1),
    0,
  );

  return (
    <section
      aria-label={t.trajectory.title}
      className="bg-background relative flex size-full min-h-0 flex-col overflow-hidden"
    >
      <div className="flex h-11 shrink-0 items-center gap-2 border-b px-3">
        <div className="relative max-w-sm min-w-36 flex-1">
          <SearchIcon className="text-muted-foreground pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2" />
          <Input
            aria-label={t.trajectory.searchPlaceholder}
            className="h-8 pl-8 text-xs"
            placeholder={t.trajectory.searchPlaceholder}
            type="search"
            value={query}
            onChange={(event) => setQuery(event.currentTarget.value)}
          />
        </div>
        <Button
          aria-label={
            allCollapsed ? t.trajectory.expandAll : t.trajectory.collapseAll
          }
          className="text-xs"
          disabled={turns.length === 0 || query.trim().length > 0}
          size="sm"
          variant="ghost"
          onClick={() =>
            setCollapsedTurnIds(
              allCollapsed ? new Set() : new Set(turns.map((turn) => turn.id)),
            )
          }
        >
          {allCollapsed ? <ChevronRightIcon /> : <ChevronDownIcon />}
          <span className="hidden sm:inline">
            {allCollapsed ? t.trajectory.expandAll : t.trajectory.collapseAll}
          </span>
        </Button>
      </div>

      {turns.length > 0 && (
        <div
          aria-label={`${t.trajectory.title} overview`}
          className="bg-muted/30 flex h-8 shrink-0 gap-px border-b px-3 py-2"
          role="img"
        >
          {turns.map((turn) => (
            <span
              key={turn.id}
              className="bg-primary/45 min-w-px rounded-sm"
              style={{
                flexGrow:
                  Math.max(turn.durationSeconds ?? 1, 1) / totalDuration,
              }}
              title={`${t.trajectory.turn(turn.number)} · ${
                turn.durationSeconds === undefined
                  ? t.trajectory.running
                  : t.trajectory.seconds(turn.durationSeconds)
              }`}
            />
          ))}
        </div>
      )}

      <div
        className={cn(
          "relative grid min-h-0 flex-1",
          selectedRecord && "lg:grid-cols-[minmax(0,1fr)_minmax(20rem,34%)]",
        )}
      >
        <div
          ref={scrollerRef}
          className="min-h-0 overflow-auto overscroll-contain"
          data-testid="trajectory-scroll"
          onScroll={(event) => {
            const element = event.currentTarget;
            followsTail.current =
              element.scrollHeight - element.clientHeight - element.scrollTop <=
              BOTTOM_FOLLOW_THRESHOLD;
          }}
        >
          {hasMoreHistory && (
            <div className="flex h-10 items-center justify-center border-b">
              <Button
                disabled={isHistoryLoading}
                size="sm"
                variant="ghost"
                onClick={() => {
                  const scroller = scrollerRef.current;
                  if (scroller) {
                    olderAnchor.current = scroller.scrollHeight;
                  }
                  loadMoreHistory?.();
                }}
              >
                {isHistoryLoading && <Loader2Icon className="animate-spin" />}
                {isHistoryLoading
                  ? t.trajectory.loadingEarlier
                  : t.trajectory.loadEarlier}
              </Button>
            </div>
          )}
          {rows.length === 0 ? (
            <div className="text-muted-foreground flex h-full min-h-48 items-center justify-center p-8 text-sm">
              {turns.length === 0 ? t.trajectory.empty : t.trajectory.noMatches}
            </div>
          ) : (
            <div
              aria-label={t.trajectory.title}
              className="relative w-full"
              role="list"
              style={{ height: virtualizer.getTotalSize() }}
            >
              {visibleItems.map((item) => {
                const row = rows[item.index];
                if (!row) {
                  return null;
                }
                return (
                  <div
                    key={row.id}
                    ref={virtualizer.measureElement}
                    className="absolute top-0 left-0 w-full"
                    data-index={item.index}
                    role="listitem"
                    style={{ transform: `translateY(${item.start}px)` }}
                  >
                    {row.type === "turn" ? (
                      <button
                        className="bg-muted/80 hover:bg-muted sticky top-0 flex h-10 w-full items-center gap-2 border-b px-3 text-left backdrop-blur"
                        type="button"
                        onClick={() =>
                          setCollapsedTurnIds((current) => {
                            const next = new Set(current);
                            if (next.has(row.turn.id)) {
                              next.delete(row.turn.id);
                            } else {
                              next.add(row.turn.id);
                            }
                            return next;
                          })
                        }
                      >
                        {collapsedTurnIds.has(row.turn.id) && !query.trim() ? (
                          <ChevronRightIcon className="size-3.5" />
                        ) : (
                          <ChevronDownIcon className="size-3.5" />
                        )}
                        <span className="text-xs font-semibold">
                          {t.trajectory.turn(row.turn.number)}
                        </span>
                        <span className="text-muted-foreground text-[11px]">
                          {t.trajectory.records(row.turn.records.length)}
                        </span>
                        <span className="ml-auto flex items-center gap-3 font-mono text-[11px] tabular-nums">
                          {row.turn.usage && (
                            <span>
                              {formatTokenCount(row.turn.usage.totalTokens)} tk
                            </span>
                          )}
                          {row.turn.durationSeconds !== undefined && (
                            <span className="text-muted-foreground flex items-center gap-1">
                              <Clock3Icon className="size-3" />
                              {t.trajectory.seconds(row.turn.durationSeconds)}
                            </span>
                          )}
                        </span>
                      </button>
                    ) : (
                      <button
                        aria-pressed={selectedRecordId === row.record.id}
                        className="hover:bg-muted/45 aria-pressed:bg-primary/5 grid min-h-16 w-full grid-cols-[7rem_minmax(0,1fr)_auto] items-start gap-3 border-b px-3 py-2.5 text-left sm:grid-cols-[8rem_minmax(0,1fr)_auto]"
                        type="button"
                        onClick={() => setSelectedRecordId(row.record.id)}
                      >
                        <span className="text-muted-foreground flex min-w-0 items-center gap-1.5 text-[11px] font-semibold">
                          {RECORD_ICONS[row.record.kind]}
                          <span className="truncate">{row.record.label}</span>
                        </span>
                        <span className="min-w-0">
                          <span className="block truncate text-xs leading-5">
                            {preview(row.record.content) ||
                              (row.record.kind === "tool"
                                ? row.record.toolName
                                : "—")}
                          </span>
                          {row.record.result !== undefined && (
                            <span className="text-muted-foreground mt-0.5 block truncate font-mono text-[11px]">
                              {preview(row.record.result, 240) || "—"}
                            </span>
                          )}
                        </span>
                        <span className="text-muted-foreground flex items-center gap-2 font-mono text-[10px] tabular-nums">
                          {row.record.usage && (
                            <span>
                              {formatTokenCount(row.record.usage.totalTokens)}{" "}
                              tk
                            </span>
                          )}
                          {row.record.kind === "tool" && (
                            <TerminalIcon className="size-3" />
                          )}
                        </span>
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
          )}
          {isStreaming && rows.length > 0 && (
            <div className="text-muted-foreground flex h-8 items-center gap-2 border-t px-3 text-xs">
              <Loader2Icon className="size-3 animate-spin" />
              {t.trajectory.running}
            </div>
          )}
        </div>
        {selectedRecord && (
          <RecordDetails
            record={selectedRecord}
            onClose={() => setSelectedRecordId(null)}
          />
        )}
      </div>
    </section>
  );
}
