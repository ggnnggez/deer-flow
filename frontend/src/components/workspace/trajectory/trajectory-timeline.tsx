"use client";

import { Clock3Icon } from "lucide-react";

import { useI18n } from "@/core/i18n/hooks";
import type {
  TrajectoryTimelineModel,
  TrajectoryTimelineSpan,
} from "@/core/trajectory";
import { cn } from "@/lib/utils";

function formatMilliseconds(milliseconds: number) {
  if (milliseconds < 1_000) {
    return `${Math.round(milliseconds)} ms`;
  }
  return `${(milliseconds / 1_000).toFixed(milliseconds < 10_000 ? 1 : 0)} s`;
}

function spanDescription(
  span: TrajectoryTimelineSpan,
  stepLabel: string,
  ttftLabel: string,
) {
  return [
    span.label,
    span.step === undefined ? undefined : `${stepLabel} ${span.step}`,
    formatMilliseconds(span.durationMs),
    span.ttftPercent === undefined
      ? undefined
      : `${ttftLabel} ${formatMilliseconds(
          span.durationMs * (span.ttftPercent / 100),
        )}`,
  ]
    .filter(Boolean)
    .join(" · ");
}

export function TrajectoryTimeline({
  model,
  onSelect,
  selectedRecordId,
}: {
  model: TrajectoryTimelineModel | null;
  onSelect: (recordId: string) => void;
  selectedRecordId: string | null;
}) {
  const { t } = useI18n();

  if (!model) {
    return (
      <div className="text-muted-foreground flex h-10 shrink-0 items-center gap-2 border-b px-3 text-xs">
        <Clock3Icon className="size-3.5" />
        {t.trajectory.timingUnavailable}
      </div>
    );
  }

  return (
    <section
      aria-label={t.trajectory.timeline}
      className="bg-muted/15 shrink-0 border-b"
    >
      <div className="flex h-8 items-center gap-4 border-b px-3 text-[10px]">
        <span className="font-medium">{t.trajectory.timeline}</span>
        <span className="text-muted-foreground font-mono tabular-nums">
          {formatMilliseconds(model.durationMs)}
        </span>
        <span className="ml-auto flex items-center gap-3">
          <span className="flex items-center gap-1">
            <span className="size-2 rounded-sm bg-amber-400" />
            {t.trajectory.ttft}
          </span>
          <span className="flex items-center gap-1">
            <span className="bg-primary size-2 rounded-sm" />
            {t.trajectory.generation}
          </span>
          <span className="flex items-center gap-1">
            <span className="size-2 rounded-sm bg-sky-500" />
            {t.trajectory.toolExecution}
          </span>
        </span>
      </div>
      <div className="max-h-44 overflow-y-auto py-1">
        <div className="grid grid-cols-[7rem_minmax(0,1fr)] items-center px-3 text-[9px]">
          <span />
          <div className="text-muted-foreground flex justify-between font-mono tabular-nums">
            <span>0</span>
            <span>{formatMilliseconds(model.durationMs / 2)}</span>
            <span>{formatMilliseconds(model.durationMs)}</span>
          </div>
        </div>
        {model.lanes.map((lane) => (
          <div
            key={lane.id}
            className="grid h-8 grid-cols-[7rem_minmax(0,1fr)] items-center gap-2 px-3"
          >
            <span className="text-muted-foreground truncate text-[10px] font-medium">
              {lane.label}
            </span>
            <div className="bg-border/45 relative h-5 rounded-sm bg-[linear-gradient(to_right,transparent_49.8%,var(--border)_50%,transparent_50.2%)]">
              {lane.spans.map((span) => {
                const description = spanDescription(
                  span,
                  t.trajectory.stepLabel,
                  t.trajectory.ttft,
                );
                return (
                  <button
                    key={span.id}
                    aria-label={description}
                    aria-pressed={selectedRecordId === span.id}
                    className={cn(
                      "group absolute inset-y-0.5 min-w-1 overflow-visible rounded-sm ring-offset-1 transition hover:z-10 hover:ring-2 focus-visible:z-10 focus-visible:ring-2 focus-visible:outline-none",
                      span.kind === "assistant" && "bg-primary",
                      span.kind === "tool" && "bg-sky-500",
                      span.status === "error" && "bg-destructive",
                      selectedRecordId === span.id && "z-10 ring-2",
                    )}
                    style={{
                      left: `${span.leftPercent}%`,
                      width: `${Math.max(span.widthPercent, 0.25)}%`,
                    }}
                    title={description}
                    type="button"
                    onClick={() => onSelect(span.id)}
                  >
                    {span.kind === "assistant" &&
                      span.ttftPercent !== undefined && (
                        <span
                          aria-hidden="true"
                          className="absolute inset-y-0 left-0 rounded-l-sm bg-amber-400"
                          style={{ width: `${span.ttftPercent}%` }}
                        />
                      )}
                    <span className="bg-popover text-popover-foreground pointer-events-none absolute bottom-[calc(100%+6px)] left-1/2 z-20 hidden w-max max-w-64 -translate-x-1/2 rounded-md border px-2 py-1 text-[10px] shadow-md group-hover:block group-focus-visible:block">
                      {description}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
