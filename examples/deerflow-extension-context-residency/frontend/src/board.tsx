import { RefreshCwIcon, ScissorsIcon } from "lucide-react";
import type { CSSProperties, KeyboardEvent, MutableRefObject, ReactNode } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { formatPercent, windowComposition } from "./console";
import type { ResidencyAttempt, ResidencyResponse } from "./contracts";
import { formatTimestamp, shortId, type Messages } from "./i18n";
import {
  RESIDENCY_LANE_ORDER,
  deriveContextResidency,
  residencyAttemptLaneSizes,
  residencyAttemptTotal,
  residencyMemberSize,
  sortResidencyMembers,
  type ResidencyLane,
  type ResidencyMeasure,
  type ResidencyMemberSort,
  type ResidencyModel,
  type ResidencyRow,
} from "./residency";
import { Badge, Button, cn } from "./ui";

/**
 * The residency board: three synchronized surfaces over one task's recorded
 * request inventories — a per-attempt composition band (the sawtooth is a
 * compaction), a block × attempt residency matrix rendered O(runs), and a
 * three-level drill panel (request composition → block dossier → compaction
 * membership). Each compaction boundary is one dashed rule that runs from
 * its ✂ header marker through the band and every matrix row.
 *
 * Horizontal scale is ONE CSS variable (`--residency-colw`) written
 * imperatively, so cells never recompute their own positions and wheel zoom
 * never re-renders the matrix; the minimap offers drag-select zoom, brush
 * pan and click-reset, and ⌘/Ctrl+wheel zooms anchored at the cursor.
 *
 * Honesty rules are binding: absence inside an incomplete inventory renders
 * as an explicit unknown cell, never a removal; removal causes come only from
 * recorded compaction memberships; totals of incomplete inventories are
 * labeled lower bounds; lane filtering dims, never hides; and the empty state
 * says "no recorded requests", never that the context was untouched.
 */

const BAND_HEIGHT = 96;
const MAX_COLW = 56;
const MIN_COLW = 4;

/** Cool categorical lane palette — never red/amber/green (status channels). */
export const LANE_SEGMENT_CLASS: Record<ResidencyLane, string> = {
  system: "bg-indigo-500/75",
  tool_schema: "bg-slate-400/60",
  memory: "bg-violet-500/75",
  skill: "bg-teal-500/75",
  user: "bg-sky-500/75",
  assistant: "bg-blue-500/75",
  tool_result: "bg-cyan-500/70",
  summary: "bg-purple-500/75",
  middleware: "bg-slate-500/70",
  attachment: "bg-slate-400/50",
  unknown: "bg-muted-foreground/30",
};

/** Canvas colors for the minimap (theme-stable palette hexes). */
const LANE_CANVAS_COLOR: Record<ResidencyLane, string> = {
  system: "#6366f1",
  tool_schema: "#94a3b8",
  memory: "#8b5cf6",
  skill: "#14b8a6",
  user: "#0ea5e9",
  assistant: "#3b82f6",
  tool_result: "#06b6d4",
  summary: "#a855f7",
  middleware: "#64748b",
  attachment: "#94a3b8",
  unknown: "#94a3b8",
};

const HATCH = "bg-[repeating-linear-gradient(135deg,transparent_0_4px,var(--color-border)_4px_6px)]";

type PanelState =
  | { mode: "attempt" }
  | { mode: "block"; blockId: string }
  | { mode: "compression"; compressionId: string };

function formatSize(value: number, measure: ResidencyMeasure): string {
  if (measure === "tokens") return value >= 1000 ? `${(value / 1000).toFixed(1)}k` : String(value);
  return value >= 1024 ? `${(value / 1024).toFixed(1)} KB` : `${value} B`;
}

function formatShare(value: number, total: number): string {
  if (total <= 0) return "—";
  return `${((value / total) * 100).toFixed(1)}%`;
}

function attemptLabel(attempt: ResidencyAttempt): string {
  const base = `S${attempt.step_seq}`;
  return attempt.attempt_no > 1 ? `${base}·a${attempt.attempt_no}` : base;
}

export function laneLabel(t: Messages, lane: ResidencyLane): string {
  switch (lane) {
    case "system":
      return t.laneSystem;
    case "tool_schema":
      return t.laneToolSchema;
    case "memory":
      return t.laneMemory;
    case "skill":
      return t.laneSkill;
    case "user":
      return t.laneUser;
    case "assistant":
      return t.laneAssistant;
    case "tool_result":
      return t.laneToolResult;
    case "summary":
      return t.laneSummary;
    case "middleware":
      return t.laneMiddleware;
    case "attachment":
      return t.laneAttachment;
    case "unknown":
      return t.laneUnknown;
  }
}

/** The block's display identity: recorded name, else kind, else short id. */
function blockTitle(t: Messages, row: ResidencyRow): string {
  if (row.meta?.name) return row.meta.name;
  if (row.meta?.kind) return row.meta.kind;
  return `${t.block} ${shortId(row.blockId)}`;
}

export function ResidencyBoard({
  response,
  locale,
  t,
  onRefresh,
  refreshing,
  seedStepSeq,
}: {
  response: ResidencyResponse;
  locale: string | undefined;
  t: Messages;
  onRefresh: () => void;
  refreshing: boolean;
  /** Which step starts selected (its effective attempt when flagged, else its first). */
  seedStepSeq?: number | null;
}) {
  const model = useMemo(() => deriveContextResidency(response), [response]);
  const [measure, setMeasure] = useState<ResidencyMeasure>("tokens");
  const [selectedAttempt, setSelectedAttempt] = useState<number | null>(() => {
    if (seedStepSeq != null) {
      const effective = model.attempts.findIndex((attempt) => attempt.step_seq === seedStepSeq && attempt.effective);
      const first = model.attempts.findIndex((attempt) => attempt.step_seq === seedStepSeq);
      const resolved = effective >= 0 ? effective : first;
      if (resolved >= 0) return resolved;
    }
    return model.attempts.length > 0 ? model.attempts.length - 1 : null;
  });
  const [panel, setPanel] = useState<PanelState>({ mode: "attempt" });
  const [activeLanes, setActiveLanes] = useState<Set<ResidencyLane>>(() => new Set(RESIDENCY_LANE_ORDER));

  const attemptCount = model.attempts.length;
  const maxTotal = useMemo(
    () => Math.max(1, ...model.attempts.map((attempt) => residencyAttemptTotal(attempt, measure))),
    [model.attempts, measure],
  );
  // Compaction boundaries as attempt indices — the column each recorded
  // compaction is positioned before. Unanchored compactions are listed in
  // the panel, never guessed onto the matrix.
  const boundaryIndices = useMemo(
    () => model.attempts.flatMap((attempt, index) => (model.compressionsBefore.has(attempt.attempt_id) ? [index] : [])),
    [model],
  );

  /* ---- zoom: one CSS variable, written imperatively (no re-render) ---- */
  const scrollerRef = useRef<HTMLDivElement | null>(null);
  const gridRef = useRef<HTMLDivElement | null>(null);
  const colwRef = useRef<number>(24);
  const fitRef = useRef<number>(MIN_COLW);
  const labelWidthRef = useRef<number>(0);

  const updateHeaderDensity = useCallback(() => {
    const grid = gridRef.current;
    if (!grid) return;
    const colw = colwRef.current;
    grid.dataset.density = colw < 16 ? "dense" : colw < 34 ? "mid" : "full";
    const every = colw >= 34 ? 1 : Math.max(1, Math.ceil(38 / colw));
    grid.querySelectorAll<HTMLElement>("[data-attempt-header]").forEach((cell, index) => {
      cell.dataset.lbl = index % every === 0 ? "on" : "off";
    });
  }, []);

  const brushRef = useRef<HTMLDivElement | null>(null);
  const minimapCursorRef = useRef<HTMLDivElement | null>(null);
  const minimapRangeRef = useRef<HTMLDivElement | null>(null);
  const minimapRef = useRef<HTMLDivElement | null>(null);
  const minimapDragRef = useRef<
    { mode: "pan"; startX: number; startScroll: number } | { mode: "select"; anchorX: number; lastX: number } | null
  >(null);

  const updateBrush = useCallback(() => {
    const scroller = scrollerRef.current;
    const brush = brushRef.current;
    const range = minimapRangeRef.current;
    if (!scroller || !brush || attemptCount === 0) return;
    if (minimapDragRef.current?.mode === "select") return;
    const colw = colwRef.current;
    const labelWidth = labelWidthRef.current;
    const start = Math.max(0, scroller.scrollLeft / colw);
    const end = Math.min(attemptCount, (scroller.scrollLeft + scroller.clientWidth - labelWidth) / colw);
    brush.style.left = `${(start / attemptCount) * 100}%`;
    brush.style.width = `${(Math.max(0.4, end - start) / attemptCount) * 100}%`;
    if (range) {
      const first = model.attempts[Math.min(attemptCount - 1, Math.floor(start))];
      const last = model.attempts[Math.min(attemptCount - 1, Math.max(0, Math.ceil(end) - 1))];
      if (first && last) {
        range.textContent = `${attemptLabel(first)} – ${attemptLabel(last)} · ${Math.round(end - start)}/${attemptCount}`;
      }
    }
  }, [attemptCount, model.attempts]);

  const setZoom = useCallback(
    (nextColw: number, anchorIndex?: number, anchorPx?: number) => {
      const scroller = scrollerRef.current;
      const grid = gridRef.current;
      if (!scroller || !grid) return;
      const colw = Math.max(fitRef.current, Math.min(MAX_COLW, nextColw));
      colwRef.current = colw;
      grid.style.setProperty("--residency-colw", `${colw}px`);
      if (anchorIndex !== undefined && anchorPx !== undefined) {
        scroller.scrollLeft = Math.max(0, labelWidthRef.current + anchorIndex * colw - anchorPx);
      }
      updateHeaderDensity();
      updateBrush();
    },
    [updateBrush, updateHeaderDensity],
  );

  const fitColw = useCallback(() => {
    const scroller = scrollerRef.current;
    if (!scroller || attemptCount === 0) return MIN_COLW;
    return Math.max(MIN_COLW, Math.floor((scroller.clientWidth - labelWidthRef.current) / attemptCount));
  }, [attemptCount]);

  /* initial fit + refit on resize */
  useEffect(() => {
    const scroller = scrollerRef.current;
    const grid = gridRef.current;
    if (!scroller || !grid || attemptCount === 0) return;
    const label = grid.querySelector<HTMLElement>("[data-residency-label]");
    labelWidthRef.current = label?.offsetWidth ?? 0;
    fitRef.current = fitColw();
    setZoom(fitRef.current);
    scroller.scrollLeft = 0;
    const observer = new ResizeObserver(() => {
      const wasFit = colwRef.current <= fitRef.current + 0.5;
      fitRef.current = fitColw();
      if (wasFit || colwRef.current < fitRef.current) setZoom(fitRef.current);
      updateBrush();
    });
    observer.observe(scroller);
    return () => observer.disconnect();
  }, [attemptCount, fitColw, setZoom, updateBrush]);

  /* wheel zoom (⌘/Ctrl) anchored at the cursor; plain wheel keeps scrolling */
  useEffect(() => {
    const scroller = scrollerRef.current;
    if (!scroller) return;
    const onWheel = (event: WheelEvent) => {
      if (!(event.ctrlKey || event.metaKey)) return;
      event.preventDefault();
      const rect = scroller.getBoundingClientRect();
      const anchorPx = event.clientX - rect.left;
      const anchorIndex = (scroller.scrollLeft + anchorPx - labelWidthRef.current) / colwRef.current;
      setZoom(colwRef.current * Math.exp(-event.deltaY * 0.0025), anchorIndex, anchorPx);
    };
    const onScroll = () => requestAnimationFrame(updateBrush);
    scroller.addEventListener("wheel", onWheel, { passive: false });
    scroller.addEventListener("scroll", onScroll);
    return () => {
      scroller.removeEventListener("wheel", onWheel);
      scroller.removeEventListener("scroll", onScroll);
    };
  }, [setZoom, updateBrush]);

  /* minimap: canvas painting */
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  useEffect(() => {
    const canvas = canvasRef.current;
    const wrap = minimapRef.current;
    if (!canvas || !wrap || attemptCount === 0) return;
    const width = wrap.clientWidth;
    const height = wrap.clientHeight;
    const ratio = window.devicePixelRatio || 1;
    canvas.width = width * ratio;
    canvas.height = height * ratio;
    const context = canvas.getContext("2d");
    if (!context) return;
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    context.clearRect(0, 0, width, height);
    const columnWidth = width / attemptCount;
    const padding = 3;
    const usable = height - padding * 2;
    model.attempts.forEach((attempt, index) => {
      let y = height - padding;
      for (const { lane, size } of residencyAttemptLaneSizes(attempt, response.blocks, measure)) {
        const segmentHeight = Math.max(0.5, (size / maxTotal) * usable);
        context.fillStyle = LANE_CANVAS_COLOR[lane];
        context.globalAlpha = activeLanes.has(lane) ? 0.8 : 0.15;
        context.fillRect(index * columnWidth, y - segmentHeight, Math.max(1, columnWidth - 0.4), segmentHeight);
        y -= segmentHeight;
      }
      context.globalAlpha = 1;
      if (attempt.status === "incomplete") {
        context.fillStyle = "#d97706";
        context.fillRect(index * columnWidth, 0, Math.max(1.5, columnWidth - 0.4), 2.5);
      }
    });
    context.strokeStyle = LANE_CANVAS_COLOR.summary;
    context.setLineDash([3, 3]);
    context.lineWidth = 1.5;
    for (const index of boundaryIndices) {
      const x = index * columnWidth;
      context.beginPath();
      context.moveTo(x, 0);
      context.lineTo(x, height);
      context.stroke();
    }
    context.setLineDash([]);
    updateBrush();
  }, [activeLanes, attemptCount, boundaryIndices, maxTotal, measure, model, response.blocks, updateBrush]);

  /* minimap gestures: drag-select zoom, brush pan, click reset */
  useEffect(() => {
    const wrap = minimapRef.current;
    const brush = brushRef.current;
    const scroller = scrollerRef.current;
    if (!wrap || !brush || !scroller || attemptCount === 0) return;
    const onPointerDown = (event: PointerEvent) => {
      const rect = wrap.getBoundingClientRect();
      const x = event.clientX - rect.left;
      const brushRect = brush.getBoundingClientRect();
      const inBrush = event.clientX >= brushRect.left && event.clientX <= brushRect.right;
      const viewSpan = (scroller.clientWidth - labelWidthRef.current) / colwRef.current;
      const fullView = viewSpan >= attemptCount - 0.5;
      wrap.setPointerCapture(event.pointerId);
      if (inBrush && !fullView) {
        minimapDragRef.current = { mode: "pan", startX: x, startScroll: scroller.scrollLeft };
      } else {
        minimapDragRef.current = { mode: "select", anchorX: x, lastX: x };
      }
    };
    const onPointerMove = (event: PointerEvent) => {
      const drag = minimapDragRef.current;
      if (!drag) return;
      const rect = wrap.getBoundingClientRect();
      const x = Math.max(0, Math.min(rect.width, event.clientX - rect.left));
      if (drag.mode === "pan") {
        const deltaIndex = ((x - drag.startX) / rect.width) * attemptCount;
        scroller.scrollLeft = drag.startScroll + deltaIndex * colwRef.current;
      } else {
        drag.lastX = x;
        const left = Math.min(drag.anchorX, x);
        const right = Math.max(drag.anchorX, x);
        brush.style.left = `${(left / rect.width) * 100}%`;
        brush.style.width = `${(Math.max(2, right - left) / rect.width) * 100}%`;
      }
    };
    const onPointerUp = () => {
      const drag = minimapDragRef.current;
      minimapDragRef.current = null;
      if (drag?.mode !== "select") {
        updateBrush();
        return;
      }
      const rect = wrap.getBoundingClientRect();
      if (Math.abs(drag.lastX - drag.anchorX) < 3) {
        setZoom(fitRef.current);
        scroller.scrollLeft = 0;
        return;
      }
      const startIndex = Math.max(0, (Math.min(drag.anchorX, drag.lastX) / rect.width) * attemptCount);
      const endIndex = Math.min(attemptCount, (Math.max(drag.anchorX, drag.lastX) / rect.width) * attemptCount);
      const span = Math.max(2, endIndex - startIndex);
      setZoom((scroller.clientWidth - labelWidthRef.current) / span);
      scroller.scrollLeft = startIndex * colwRef.current;
      updateBrush();
    };
    wrap.addEventListener("pointerdown", onPointerDown);
    wrap.addEventListener("pointermove", onPointerMove);
    wrap.addEventListener("pointerup", onPointerUp);
    return () => {
      wrap.removeEventListener("pointerdown", onPointerDown);
      wrap.removeEventListener("pointermove", onPointerMove);
      wrap.removeEventListener("pointerup", onPointerUp);
    };
  }, [attemptCount, setZoom, updateBrush]);

  /* selected-attempt cursor line on the minimap */
  useEffect(() => {
    const cursor = minimapCursorRef.current;
    if (!cursor || attemptCount === 0) return;
    if (selectedAttempt === null) {
      cursor.style.display = "none";
      return;
    }
    cursor.style.display = "block";
    cursor.style.left = `${((selectedAttempt + 0.5) / attemptCount) * 100}%`;
  }, [attemptCount, selectedAttempt]);

  const selectAttempt = useCallback((index: number, keepPanel = false) => {
    setSelectedAttempt(index);
    if (!keepPanel) setPanel({ mode: "attempt" });
    const scroller = scrollerRef.current;
    if (!scroller) return;
    const colw = colwRef.current;
    const labelWidth = labelWidthRef.current;
    const left = labelWidth + index * colw;
    if (left - scroller.scrollLeft < labelWidth) {
      scroller.scrollLeft = index * colw;
    } else if (left + colw - scroller.scrollLeft > scroller.clientWidth) {
      scroller.scrollLeft = left + colw - scroller.clientWidth;
    }
  }, []);

  const onBoardKeyDown = useCallback(
    (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setPanel({ mode: "attempt" });
        return;
      }
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
      if (selectedAttempt === null || attemptCount === 0) return;
      const next = selectedAttempt + (event.key === "ArrowRight" ? 1 : -1);
      if (next < 0 || next >= attemptCount) return;
      event.preventDefault();
      selectAttempt(next);
    },
    [attemptCount, selectAttempt, selectedAttempt],
  );

  const toggleLane = useCallback((lane: ResidencyLane) => {
    setActiveLanes((current) => {
      const allLanes = RESIDENCY_LANE_ORDER;
      if (current.size === allLanes.length) return new Set([lane]);
      const next = new Set(current);
      if (next.has(lane)) {
        next.delete(lane);
        if (next.size === 0) return new Set(allLanes);
      } else {
        next.add(lane);
        if (next.size === allLanes.length) return new Set(allLanes);
      }
      return next;
    });
  }, []);

  const filtering = activeLanes.size < RESIDENCY_LANE_ORDER.length;
  const laneDimmed = useCallback((lane: ResidencyLane) => filtering && !activeLanes.has(lane), [activeLanes, filtering]);
  const presentLanes = useMemo(() => model.lanes.map((group) => group.lane), [model.lanes]);

  if (attemptCount === 0) {
    return (
      <div className="space-y-2" data-residency-empty>
        <p className="text-muted-foreground text-sm">{t.empty}</p>
        {model.attemptsTruncated ? <p className="text-xs text-amber-600">{t.attemptsTruncated}</p> : null}
      </div>
    );
  }

  return (
    <div className="space-y-3" data-residency-board>
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-2">
        <p className="text-muted-foreground max-w-3xl text-xs">{t.coverage}</p>
        <div className="flex shrink-0 items-center gap-2">
          <div className="flex items-center gap-1 rounded-md border p-0.5">
            {(["tokens", "bytes"] as const).map((value) => (
              <Button
                key={value}
                size="sm"
                variant={measure === value ? "secondary" : "ghost"}
                className="h-6 px-2 text-xs"
                aria-pressed={measure === value}
                onClick={() => setMeasure(value)}
              >
                {value}
              </Button>
            ))}
          </div>
          <Button size="sm" variant="ghost" className="h-7 px-2 text-xs" onClick={onRefresh} disabled={refreshing}>
            <RefreshCwIcon className={cn("size-3.5", refreshing && "animate-spin")} />
            {t.refresh}
          </Button>
        </div>
      </div>
      {model.attemptsTruncated ? <p className="text-xs text-amber-600">{t.attemptsTruncated}</p> : null}
      <div className="flex flex-wrap items-center gap-1.5">
        {presentLanes.map((lane) => (
          <button
            key={lane}
            type="button"
            aria-pressed={!filtering || activeLanes.has(lane)}
            onClick={() => toggleLane(lane)}
            className={cn(
              "focus-visible:ring-ring inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs transition-colors focus-visible:ring-2 focus-visible:outline-none",
              laneDimmed(lane) && "opacity-35",
            )}
          >
            <span className={cn("size-2 rounded-[3px]", LANE_SEGMENT_CLASS[lane])} />
            {laneLabel(t, lane)}
          </button>
        ))}
        <span className="text-muted-foreground/70 ml-auto hidden text-[11px] lg:inline">{t.hint}</span>
      </div>
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
        <div className="min-w-0 rounded-md border" tabIndex={0} onKeyDown={onBoardKeyDown} aria-label={t.title}>
          {/* minimap: whole-run overview, drag to zoom a range, click resets */}
          <div ref={minimapRef} className="relative h-12 cursor-crosshair touch-none overflow-hidden border-b select-none">
            <canvas ref={canvasRef} className="block h-full w-full" />
            <div ref={brushRef} className="border-primary bg-primary/10 absolute inset-y-0 cursor-grab border-x" />
            <div ref={minimapCursorRef} className="bg-primary/70 pointer-events-none absolute inset-y-0 w-0.5" />
            <div
              ref={minimapRangeRef}
              className="text-muted-foreground bg-background/70 pointer-events-none absolute top-1 right-2 rounded px-1 font-mono text-[10px]"
            />
          </div>
          <div ref={scrollerRef} className="overflow-x-auto">
            <div
              ref={gridRef}
              className="group/board relative isolate min-w-max"
              style={{ "--residency-colw": "24px" } as CSSProperties}
              data-density="mid"
            >
              {/* compaction boundaries: one dashed rule per boundary attempt,
                  spanning the header, the composition band and every matrix
                  row. It sits beneath the rows (negative z in the grid's own
                  stacking context) so a pill that crosses a boundary reads as
                  intact. `left-44` mirrors the label column's `w-44`. */}
              <div aria-hidden className="pointer-events-none absolute inset-y-0 left-44 -z-10">
                {boundaryIndices.map((index) => (
                  <span
                    key={model.attempts[index]!.attempt_id}
                    data-residency-boundary={index}
                    className="absolute inset-y-0 w-0 border-l-2 border-dashed border-purple-500/50"
                    style={{ left: `calc(${index} * var(--residency-colw))` }}
                  />
                ))}
              </div>
              {/* attempt header row */}
              <div className="flex border-b">
                <div
                  data-residency-label
                  className="bg-card text-muted-foreground sticky left-0 z-[5] w-44 shrink-0 border-r px-3 py-1 text-[11px]"
                >
                  attempt →
                </div>
                {model.attempts.map((attempt, index) => {
                  const compressionsHere = model.compressionsBefore.get(attempt.attempt_id) ?? [];
                  const openCompression = () =>
                    setPanel({ mode: "compression", compressionId: compressionsHere[0]!.compression_id });
                  return (
                    <button
                      key={attempt.attempt_id}
                      type="button"
                      data-attempt-header
                      data-lbl="on"
                      onClick={() => selectAttempt(index)}
                      title={`${attemptLabel(attempt)}${attempt.occurred_at ? ` · ${formatTimestamp(attempt.occurred_at, locale)}` : ""} · ${formatSize(residencyAttemptTotal(attempt, measure), measure)}${attempt.status === "incomplete" ? ` (${t.lowerBound})` : ""}`}
                      className={cn(
                        "group/hcell relative w-(--residency-colw) shrink-0 overflow-visible py-1 text-center",
                        attempt.status === "incomplete" && HATCH,
                        selectedAttempt === index && "bg-primary/10 shadow-[inset_0_-2px_0_var(--color-primary)]",
                      )}
                    >
                      {compressionsHere.length > 0 ? (
                        <span
                          role="button"
                          tabIndex={0}
                          data-residency-compression-marker
                          onClick={(event) => {
                            event.stopPropagation();
                            openCompression();
                          }}
                          onKeyDown={(event) => {
                            if (event.key === "Enter" || event.key === " ") {
                              event.stopPropagation();
                              openCompression();
                            }
                          }}
                          title={t.compression}
                          className="bg-card absolute -top-0.5 left-0 z-[5] inline-flex -translate-x-1/2 items-center gap-0.5 rounded-full border border-purple-500/60 px-1 text-[9px] leading-4 text-purple-600"
                        >
                          <ScissorsIcon className="size-2.5" />
                          {compressionsHere.length > 1 ? `×${compressionsHere.length}` : null}
                        </span>
                      ) : null}
                      <span
                        className={cn(
                          "text-foreground text-[11px] font-medium whitespace-nowrap",
                          selectedAttempt === index ? "text-primary" : "group-data-[lbl=off]/hcell:invisible",
                        )}
                      >
                        {attemptLabel(attempt)}
                      </span>
                      {attempt.status === "incomplete" ? (
                        <span className="absolute top-0.5 right-0.5 size-1.5 rounded-full bg-amber-500" />
                      ) : null}
                    </button>
                  );
                })}
              </div>
              {/* composition band */}
              <div className="flex border-b">
                <div className="bg-card sticky left-0 z-[5] flex w-44 shrink-0 items-end border-r px-3 py-1">
                  <div className="text-muted-foreground text-[11px] leading-tight">
                    <div className="text-foreground/80 font-medium">{t.composition}</div>
                    <div>{measure}</div>
                  </div>
                </div>
                {model.attempts.map((attempt, index) => {
                  const total = residencyAttemptTotal(attempt, measure);
                  const laneSizes = residencyAttemptLaneSizes(attempt, response.blocks, measure);
                  const boundary = model.compressionsBefore.has(attempt.attempt_id);
                  return (
                    <button
                      key={attempt.attempt_id}
                      type="button"
                      onClick={() => selectAttempt(index)}
                      title={`${attemptLabel(attempt)} · ${formatSize(total, measure)} ${measure}${attempt.status === "incomplete" ? ` (${t.lowerBound})` : ""}`}
                      className={cn(
                        "flex w-(--residency-colw) shrink-0 items-end justify-center px-px pt-1.5 group-data-[density=full]/board:px-1",
                        boundary && "border-l-2 border-transparent",
                        attempt.status === "incomplete" && HATCH,
                        selectedAttempt === index && "bg-primary/10",
                      )}
                      style={{ height: BAND_HEIGHT + 8 }}
                    >
                      <span
                        className="flex w-full flex-col justify-end overflow-hidden rounded-t-[2px]"
                        style={{ height: Math.max(4, Math.round((total / maxTotal) * BAND_HEIGHT)) }}
                      >
                        {attempt.status === "incomplete" ? (
                          <span className="h-2 w-full border border-b-0 border-dashed border-amber-500/50 bg-[repeating-linear-gradient(135deg,transparent_0_3px,var(--color-border)_3px_5px)]" />
                        ) : null}
                        {laneSizes.map(({ lane, size }) => (
                          <span
                            key={lane}
                            className={cn("w-full", LANE_SEGMENT_CLASS[lane], laneDimmed(lane) && "opacity-20")}
                            style={{ height: Math.max(2, Math.round((size / maxTotal) * BAND_HEIGHT)) }}
                          />
                        ))}
                      </span>
                    </button>
                  );
                })}
              </div>
              {/* residency matrix, one grid row per block, O(runs) segments */}
              {model.lanes.map((group) => (
                <div key={group.lane} className={cn(laneDimmed(group.lane) && "opacity-35")}>
                  <div className="bg-muted/50 border-b">
                    <div className="bg-muted/50 sticky left-0 z-[5] inline-flex items-center gap-1.5 px-3 py-0.5 text-[10px] font-semibold tracking-wide uppercase">
                      <span className={cn("size-1.5 rounded-[2px]", LANE_SEGMENT_CLASS[group.lane])} />
                      {laneLabel(t, group.lane)}
                      <span className="text-muted-foreground font-normal">· {group.rows.length}</span>
                    </div>
                  </div>
                  {group.rows.map((row) => (
                    <MatrixRow
                      key={row.blockId}
                      row={row}
                      model={model}
                      measure={measure}
                      selectedAttempt={selectedAttempt}
                      onSelectBlock={(blockId, attemptIndex) => {
                        if (attemptIndex !== null) selectAttempt(attemptIndex, true);
                        setPanel({ mode: "block", blockId });
                      }}
                      colwRef={colwRef}
                      title={blockTitle(t, row)}
                    />
                  ))}
                </div>
              ))}
            </div>
          </div>
        </div>
        <Panel
          model={model}
          response={response}
          measure={measure}
          selectedAttempt={selectedAttempt}
          panel={panel}
          locale={locale}
          t={t}
          onSelectAttempt={(index) => selectAttempt(index)}
          onSelectBlock={(blockId) => setPanel({ mode: "block", blockId })}
          onSelectCompression={(compressionId) => setPanel({ mode: "compression", compressionId })}
        />
      </div>
    </div>
  );
}

function MatrixRow({
  row,
  model,
  measure,
  selectedAttempt,
  onSelectBlock,
  colwRef,
  title,
}: {
  row: ResidencyRow;
  model: ResidencyModel;
  measure: ResidencyMeasure;
  selectedAttempt: number | null;
  onSelectBlock: (blockId: string, attemptIndex: number | null) => void;
  colwRef: MutableRefObject<number>;
  title: string;
}) {
  const attemptCount = model.attempts.length;
  return (
    <div className="border-border/50 flex h-7 items-stretch border-b" data-residency-row={row.blockId}>
      <button
        type="button"
        onClick={() => onSelectBlock(row.blockId, null)}
        className="bg-card hover:bg-muted/60 sticky left-0 z-[5] flex w-44 shrink-0 items-center gap-1.5 truncate border-r px-3 text-left text-xs"
        title={title}
      >
        <span className={cn("size-2 shrink-0 rounded-[3px]", LANE_SEGMENT_CLASS[row.lane])} />
        <span className="truncate">{title}</span>
        <span className="text-muted-foreground/70 ml-auto shrink-0 font-mono text-[10px]">
          {formatSize(residencyMemberSize({ estimated_tokens: row.sizeTokens, visible_bytes: row.sizeBytes }, measure), measure)}
        </span>
      </button>
      <div className="relative grid items-center" style={{ gridTemplateColumns: `repeat(${attemptCount}, var(--residency-colw))` }}>
        {selectedAttempt !== null ? (
          <span
            className="bg-primary/8 pointer-events-none absolute inset-y-0"
            style={{ left: `calc(${selectedAttempt} * var(--residency-colw))`, width: "var(--residency-colw)" }}
          />
        ) : null}
        {row.runs.map((run) => (
          <button
            key={`run-${run.start}`}
            type="button"
            data-residency-run
            onClick={(event) => {
              const rect = event.currentTarget.getBoundingClientRect();
              const offset = Math.floor((event.clientX - rect.left) / Math.max(1, colwRef.current));
              onSelectBlock(row.blockId, Math.min(run.end, run.start + Math.max(0, offset)));
            }}
            title={title}
            className={cn("mx-px h-2.5 rounded-full", LANE_SEGMENT_CLASS[row.lane], "hover:ring-primary/40 hover:ring-2")}
            style={{ gridColumn: `${run.start + 1} / ${run.end + 2}`, gridRow: 1 }}
          />
        ))}
        {row.unknownAt.map((index) => (
          <span
            key={`unknown-${index}`}
            data-residency-unknown
            title={`${attemptLabel(model.attempts[index]!)} · ?`}
            className="border-muted-foreground/50 text-muted-foreground mx-0.5 flex h-2.5 items-center justify-center rounded border border-dashed text-[8px] leading-none group-data-[density=dense]/board:text-[0px]"
            style={{ gridColumn: `${index + 1} / ${index + 2}`, gridRow: 1 }}
          >
            ?
          </span>
        ))}
      </div>
    </div>
  );
}

/* ------------------------- drill-down panel ------------------------- */

function Panel({
  model,
  response,
  measure,
  selectedAttempt,
  panel,
  locale,
  t,
  onSelectAttempt,
  onSelectBlock,
  onSelectCompression,
}: {
  model: ResidencyModel;
  response: ResidencyResponse;
  measure: ResidencyMeasure;
  selectedAttempt: number | null;
  panel: PanelState;
  locale: string | undefined;
  t: Messages;
  onSelectAttempt: (index: number) => void;
  onSelectBlock: (blockId: string) => void;
  onSelectCompression: (compressionId: string) => void;
}) {
  const attempt = selectedAttempt !== null ? (model.attempts[selectedAttempt] ?? null) : null;
  return (
    <div className="min-w-0 space-y-3 rounded-md border p-3 text-sm lg:sticky lg:top-4 lg:max-h-[70vh] lg:self-start lg:overflow-y-auto" data-residency-panel={panel.mode}>
      {panel.mode === "attempt" ? (
        attempt ? (
          <AttemptPanel
            attempt={attempt}
            attemptIndex={selectedAttempt!}
            response={response}
            model={model}
            measure={measure}
            locale={locale}
            t={t}
            onSelectBlock={onSelectBlock}
          />
        ) : (
          <p className="text-muted-foreground text-xs">{t.empty}</p>
        )
      ) : panel.mode === "block" ? (
        <BlockPanel
          blockId={panel.blockId}
          model={model}
          measure={measure}
          t={t}
          onSelectAttempt={onSelectAttempt}
          onSelectCompression={onSelectCompression}
          onBack={() => (attempt ? onSelectAttempt(selectedAttempt!) : undefined)}
        />
      ) : (
        <CompressionPanel
          compressionId={panel.compressionId}
          model={model}
          measure={measure}
          locale={locale}
          t={t}
          onSelectBlock={onSelectBlock}
          onSelectAttempt={onSelectAttempt}
        />
      )}
    </div>
  );
}

function PanelHeading({ crumb, onCrumb, title, chips }: { crumb?: string; onCrumb?: () => void; title: ReactNode; chips?: ReactNode }) {
  return (
    <div className="space-y-1">
      {crumb && onCrumb ? (
        <button type="button" onClick={onCrumb} className="text-primary text-xs underline-offset-2 hover:underline">
          ‹ {crumb}
        </button>
      ) : null}
      <div className="flex flex-wrap items-center gap-2 font-medium">
        {title}
        {chips}
      </div>
    </div>
  );
}

function AttemptPanel({
  attempt,
  attemptIndex,
  response,
  model,
  measure,
  locale,
  t,
  onSelectBlock,
}: {
  attempt: ResidencyAttempt;
  attemptIndex: number;
  response: ResidencyResponse;
  model: ResidencyModel;
  measure: ResidencyMeasure;
  locale: string | undefined;
  t: Messages;
  onSelectBlock: (blockId: string) => void;
}) {
  const [memberSort, setMemberSort] = useState<ResidencyMemberSort>("context");
  const total = residencyAttemptTotal(attempt, measure);
  const laneSizes = residencyAttemptLaneSizes(attempt, response.blocks, measure);
  // 100% of the bar is the model's context window when one was recorded; each
  // lane is its absolute share of that window and the rest is free. Without a
  // recorded window the request itself is 100%, and the header says which.
  const composition = windowComposition(laneSizes, total, attempt.context_window_tokens ?? null, measure);
  const incomplete = attempt.status === "incomplete";
  const rowByBlock = new Map(model.rows.map((row) => [row.blockId, row]));
  return (
    <>
      <PanelHeading
        title={
          <>
            {t.snapshot} · {attemptLabel(attempt)}
          </>
        }
        chips={
          <>
            {attempt.attempt_no > 1 ? <Badge>{t.retryAttempt}</Badge> : null}
            <Badge className={cn(incomplete && "border-amber-500/60 text-amber-600")}>{attempt.status}</Badge>
            {attempt.outcome === "failed" ? <Badge className="border-destructive/60 text-destructive">{attempt.outcome}</Badge> : null}
          </>
        }
      />
      <div className="text-muted-foreground text-xs">
        <code>{shortId(attempt.attempt_id)}</code>
        {attempt.occurred_at ? ` · ${formatTimestamp(attempt.occurred_at, locale)}` : null}
        {attempt.model_name ? ` · ${attempt.model_name}` : null}
        {` · ${attempt.message_count} msg · ${attempt.tool_schema_count} schema`}
      </div>
      <div className="text-xs">
        {t.total}:{" "}
        <span className="font-mono font-medium">
          {formatSize(total, measure)}
          {incomplete ? `+ (${t.lowerBound})` : ""} {measure}
        </span>
      </div>
      <div data-residency-composition={composition.basis}>
        <div className="mb-1 flex flex-wrap items-baseline justify-between gap-x-2">
          <div className="text-muted-foreground text-[10px] font-semibold tracking-wide uppercase">{t.composition}</div>
          <div className="text-muted-foreground text-[10px]">
            {composition.capacity !== null ? t.compositionWindow(`${formatSize(composition.capacity, measure)} ${measure}`) : t.compositionRequest}
          </div>
        </div>
        <div className={cn("bg-muted relative flex h-3 overflow-hidden rounded", composition.overflow && "ring-destructive/70 ring-1")}>
          {composition.segments.map(({ lane, size, share, width }) => (
            <span
              key={lane}
              className={LANE_SEGMENT_CLASS[lane]}
              style={{ width: `${width * 100}%` }}
              title={`${laneLabel(t, lane)} · ${formatSize(size, measure)} ${measure} · ${formatPercent(share)}`}
            />
          ))}
          {incomplete ? (
            <span
              className={cn(
                "border border-dashed bg-[repeating-linear-gradient(135deg,transparent_0_3px,var(--color-border)_3px_5px)]",
                composition.basis === "window" ? "w-[4%] shrink-0" : "min-w-[6%] flex-1",
              )}
            />
          ) : null}
        </div>
        <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px]">
          {composition.segments.map(({ lane, share }) => (
            <span key={lane} className="text-muted-foreground inline-flex items-center gap-1">
              <span className={cn("size-1.5 rounded-[2px]", LANE_SEGMENT_CLASS[lane])} />
              {laneLabel(t, lane)} <b className="text-foreground font-medium">{formatPercent(share)}</b>
            </span>
          ))}
          {composition.freeShare !== null ? (
            <span className="text-muted-foreground inline-flex items-center gap-1">
              <span className="bg-muted size-1.5 rounded-[2px] border" />
              {t.free}{" "}
              <b className="text-foreground font-medium">
                {incomplete ? "≤ " : ""}
                {formatPercent(composition.freeShare)}
              </b>
            </span>
          ) : null}
        </div>
        {composition.capacity !== null && composition.usedShare !== null ? (
          <div className="text-muted-foreground mt-1 text-[11px]">
            {t.used}:{" "}
            <span className="text-foreground font-mono font-medium">
              {formatSize(total, measure)}
              {incomplete ? "+" : ""} / {formatSize(composition.capacity, measure)} {measure} · {formatPercent(composition.usedShare)}
            </span>
            {composition.overflow ? <span className="text-destructive ml-2 font-medium">{t.overflow(formatPercent(composition.usedShare - 1))}</span> : null}
          </div>
        ) : null}
      </div>
      <div>
        <div className="mb-1 flex items-center justify-between gap-2">
          <div className="text-muted-foreground text-[10px] font-semibold tracking-wide uppercase">
            {t.members} · <span className="font-normal tracking-normal normal-case">{t.membersOfRequest}</span>
          </div>
          <div className="flex items-center gap-0.5 rounded-md border p-0.5">
            {(["context", "share"] as const).map((value) => (
              <Button
                key={value}
                size="sm"
                variant={memberSort === value ? "secondary" : "ghost"}
                className="h-5 px-1.5 text-[10px]"
                aria-pressed={memberSort === value}
                onClick={() => setMemberSort(value)}
              >
                {value === "context" ? t.sortContext : t.sortShare}
              </Button>
            ))}
          </div>
        </div>
        <ul className="space-y-0.5" aria-label={t.members}>
          {sortResidencyMembers(attempt.members, memberSort, measure).map((member) => {
            const row = rowByBlock.get(member.block_id);
            const size = residencyMemberSize(member, measure);
            return (
              <li key={`${member.ordinal}`}>
                <button
                  type="button"
                  onClick={() => onSelectBlock(member.block_id)}
                  className="hover:bg-muted/60 flex w-full items-center gap-2 rounded px-1 py-0.5 text-left text-xs"
                >
                  <span className="text-muted-foreground/70 w-5 shrink-0 text-right font-mono text-[10px]">{member.ordinal}</span>
                  <span className={cn("size-2 shrink-0 rounded-[3px]", LANE_SEGMENT_CLASS[row?.lane ?? "unknown"])} />
                  <span className="min-w-0 flex-1 truncate">
                    {row ? blockTitle(t, row) : shortId(member.block_id)}
                    {member.resolution_status === "missing" ? (
                      <span className="text-muted-foreground italic"> · {t.memberUnprojected}</span>
                    ) : null}
                  </span>
                  <span className="text-muted-foreground shrink-0 font-mono tabular-nums">{formatSize(size, measure)}</span>
                  <span className="w-12 shrink-0 text-right font-mono font-medium tabular-nums">{formatShare(size, total)}</span>
                </button>
              </li>
            );
          })}
        </ul>
      </div>
      {incomplete ? <p className="border-l-2 border-amber-500/60 pl-2 text-[11px] text-amber-600">{t.incompleteNote}</p> : null}
      {model.unanchoredCompressions.length > 0 && attemptIndex === 0 ? (
        <p className="text-muted-foreground text-[11px]">
          {t.unanchored}: {model.unanchoredCompressions.map((c) => shortId(c.compression_id)).join(", ")}
        </p>
      ) : null}
    </>
  );
}

function BlockPanel({
  blockId,
  model,
  measure,
  t,
  onSelectAttempt,
  onSelectCompression,
  onBack,
}: {
  blockId: string;
  model: ResidencyModel;
  measure: ResidencyMeasure;
  t: Messages;
  onSelectAttempt: (index: number) => void;
  onSelectCompression: (compressionId: string) => void;
  onBack: () => void;
}) {
  const row = model.rows.find((candidate) => candidate.blockId === blockId);
  if (!row) return null;
  const lastAttemptIndex = model.attempts.length - 1;
  const removedCompression = row.removedBy ? model.compressions.find((c) => c.compression_id === row.removedBy) : null;
  const disappearedSilently =
    row.removedBy === null &&
    row.lastSeen >= 0 &&
    row.lastSeen < lastAttemptIndex &&
    // Only claim a disappearance when a later COMPLETE inventory omits it.
    row.presence.slice(row.lastSeen + 1).includes("absent");
  const link = (label: string, onClick: () => void) => (
    <button type="button" className="text-primary underline-offset-2 hover:underline" onClick={onClick}>
      {label}
    </button>
  );
  return (
    <>
      <PanelHeading
        crumb={t.snapshot}
        onCrumb={onBack}
        title={
          <>
            <span className={cn("size-2.5 rounded-[3px]", LANE_SEGMENT_CLASS[row.lane])} />
            <span className="min-w-0 truncate">{blockTitle(t, row)}</span>
          </>
        }
      />
      <div className="text-muted-foreground text-xs">
        {laneLabel(t, row.lane)} · <code>{shortId(row.blockId)}</code>
        {row.meta?.content_hash ? (
          <>
            {" "}
            · <code title={row.meta.content_hash}>{row.meta.content_hash.slice(0, 10)}</code>
          </>
        ) : null}
        {` · ${formatSize(residencyMemberSize({ estimated_tokens: row.sizeTokens, visible_bytes: row.sizeBytes }, measure), measure)} ${measure}`}
      </div>
      <div>
        <div className="text-muted-foreground mb-1 text-[10px] font-semibold tracking-wide uppercase">
          {t.residence} · {model.attempts.length} attempts
        </div>
        <div className="flex gap-px">
          {row.presence.map((presence, index) => (
            <button
              key={index}
              type="button"
              onClick={() => onSelectAttempt(index)}
              title={`${attemptLabel(model.attempts[index]!)} · ${presence}`}
              className={cn(
                "h-2.5 min-w-0.5 flex-1 rounded-[1px]",
                presence === "present" && LANE_SEGMENT_CLASS[row.lane],
                presence === "absent" && "bg-muted",
                presence === "unknown" && "border-muted-foreground/50 border border-dashed bg-transparent",
              )}
            />
          ))}
        </div>
        <div className="text-muted-foreground mt-0.5 flex justify-between text-[10px]">
          <span>{model.attempts[0] ? attemptLabel(model.attempts[0]) : ""}</span>
          <span>{model.attempts[lastAttemptIndex] ? attemptLabel(model.attempts[lastAttemptIndex]) : ""}</span>
        </div>
      </div>
      <dl className="space-y-1.5 text-xs">
        {row.firstSeen >= 0 ? (
          <div>
            <dt className="text-muted-foreground inline">{t.firstSeen}: </dt>
            <dd className="inline">{link(attemptLabel(model.attempts[row.firstSeen]!), () => onSelectAttempt(row.firstSeen))}</dd>
          </div>
        ) : null}
        {removedCompression ? (
          <div>
            <dt className="text-muted-foreground inline">{t.removedBy}: </dt>
            <dd className="inline">
              {link(shortId(removedCompression.compression_id), () => onSelectCompression(removedCompression.compression_id))}
              {removedCompression.summary_block_id ? (
                <>
                  {" "}
                  <span className="text-muted-foreground">→ {t.continuesIn} </span>
                  {link(shortId(removedCompression.summary_block_id), () => onSelectCompression(removedCompression.compression_id))}
                </>
              ) : null}
            </dd>
          </div>
        ) : disappearedSilently ? (
          <div>
            <dt className="text-muted-foreground inline">{t.lastSeen}: </dt>
            <dd className="inline">
              {link(attemptLabel(model.attempts[row.lastSeen]!), () => onSelectAttempt(row.lastSeen))}{" "}
              <span className="text-muted-foreground">· {t.removalUnrecorded}</span>
            </dd>
          </div>
        ) : (
          <div>
            <dd className="text-muted-foreground">{t.stillPresent}</dd>
          </div>
        )}
        {row.preservedBy.length > 0 ? (
          <div>
            <dt className="text-muted-foreground inline">{t.preservedBy}: </dt>
            <dd className="inline">
              {row.preservedBy.map((compressionId, position) => (
                <span key={compressionId}>
                  {position > 0 ? ", " : null}
                  {link(shortId(compressionId), () => onSelectCompression(compressionId))}
                </span>
              ))}
            </dd>
          </div>
        ) : null}
        {row.summaryOf ? (
          <div>
            <dt className="text-muted-foreground inline">{t.summaryOf}: </dt>
            <dd className="inline">{link(shortId(row.summaryOf), () => onSelectCompression(row.summaryOf!))}</dd>
          </div>
        ) : null}
      </dl>
    </>
  );
}

function CompressionPanel({
  compressionId,
  model,
  measure,
  locale,
  t,
  onSelectBlock,
  onSelectAttempt,
}: {
  compressionId: string;
  model: ResidencyModel;
  measure: ResidencyMeasure;
  locale: string | undefined;
  t: Messages;
  onSelectBlock: (blockId: string) => void;
  onSelectAttempt: (index: number) => void;
}) {
  const compression = model.compressions.find((candidate) => candidate.compression_id === compressionId);
  if (!compression) return null;
  const anchorIndex = compression.positioned_before_attempt_id
    ? model.attempts.findIndex((attempt) => attempt.attempt_id === compression.positioned_before_attempt_id)
    : -1;
  const blockLine = (blockId: string) => {
    const row = model.rows.find((candidate) => candidate.blockId === blockId);
    return (
      <li key={blockId}>
        <button
          type="button"
          onClick={() => onSelectBlock(blockId)}
          className="hover:bg-muted/60 flex w-full items-center gap-2 rounded px-1 py-0.5 text-left text-xs"
        >
          <span className={cn("size-2 shrink-0 rounded-[3px]", LANE_SEGMENT_CLASS[row?.lane ?? "unknown"])} />
          <span className="min-w-0 flex-1 truncate">{row ? blockTitle(t, row) : shortId(blockId)}</span>
          {row ? (
            <span className="text-muted-foreground shrink-0 font-mono text-[10px] tabular-nums">
              {formatSize(residencyMemberSize({ estimated_tokens: row.sizeTokens, visible_bytes: row.sizeBytes }, measure), measure)}
            </span>
          ) : null}
        </button>
      </li>
    );
  };
  return (
    <>
      <PanelHeading
        title={
          <>
            <ScissorsIcon className="size-3.5 text-purple-600" />
            {t.compression} {shortId(compression.compression_id)}
          </>
        }
        chips={anchorIndex < 0 ? <Badge className="border-amber-500/60 text-amber-600">{compression.status}</Badge> : null}
      />
      <div className="text-muted-foreground text-xs">
        {compression.occurred_at ? formatTimestamp(compression.occurred_at, locale) : null}
        {anchorIndex >= 0 ? (
          <>
            {" · "}
            {t.positionedBefore}{" "}
            <button type="button" className="text-primary underline-offset-2 hover:underline" onClick={() => onSelectAttempt(anchorIndex)}>
              {attemptLabel(model.attempts[anchorIndex]!)}
            </button>
          </>
        ) : (
          <> · {t.unanchored}</>
        )}
      </div>
      <div className="text-xs">
        {t.compressionScope}:{" "}
        <span className="font-mono">
          {formatSize(compression.before_tokens, "tokens")} → {formatSize(compression.after_tokens, "tokens")} tokens
        </span>
      </div>
      <div>
        <div className="text-muted-foreground mb-1 text-[10px] font-semibold tracking-wide uppercase">
          {t.removed} · {compression.removed_block_ids.length}
        </div>
        <ul className="space-y-0.5">{compression.removed_block_ids.map((blockId) => blockLine(blockId))}</ul>
      </div>
      {compression.preserved_block_ids.length > 0 ? (
        <div>
          <div className="text-muted-foreground mb-1 text-[10px] font-semibold tracking-wide uppercase">
            {t.preserved} · {compression.preserved_block_ids.length}
          </div>
          <ul className="space-y-0.5">{compression.preserved_block_ids.map((blockId) => blockLine(blockId))}</ul>
        </div>
      ) : null}
      <div>
        <div className="text-muted-foreground mb-1 text-[10px] font-semibold tracking-wide uppercase">{t.summaryBlock}</div>
        {compression.summary_block_id ? (
          <ul>{blockLine(compression.summary_block_id)}</ul>
        ) : (
          <p className="text-muted-foreground text-xs">{t.summaryBlockUnknown}</p>
        )}
      </div>
    </>
  );
}
