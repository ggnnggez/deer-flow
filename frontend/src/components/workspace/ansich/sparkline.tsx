"use client";

import { cn } from "@/lib/utils";

export interface SparklinePoint {
  /** Epoch milliseconds. */
  ts: number;
  value: number;
}

export interface SparklineGeometry {
  /** One SVG `d` string per unbroken run of two or more points. */
  segments: string[];
  /**
   * Points that ended up alone in their run (both neighbours are across a
   * gap). They are drawn as dots rather than dropped: an observed reading
   * must not disappear just because its neighbours are far away.
   */
  dots: { x: number; y: number }[];
  /** `y` for the limit reference line, or null when no limit was reported. */
  limitY: number | null;
  min: number;
  max: number;
}

/**
 * Project a series onto an inline-SVG coordinate box.
 *
 * Pure on purpose (no DOM, no React) so the projection rules — especially the
 * gap rule — are unit-testable directly.
 *
 * **Gap rule**: consecutive points further apart than `gapFactor` times the
 * median inter-sample interval start a new segment. The series is a record of
 * what was sampled, not a continuous function; drawing a straight line across
 * a sampling outage would invent readings that were never taken. Honest gaps,
 * no interpolation.
 */
export function buildSparklinePath(
  points: SparklinePoint[],
  options: {
    width: number;
    height: number;
    /**
     * Drawn as a dashed reference line. The y domain is widened to include
     * it, so a limit far above every reading is always on screen.
     */
    limit?: number | null;
    gapFactor?: number;
    /** Vertical inset so a stroke at the extremes is not clipped. */
    padding?: number;
  },
): SparklineGeometry {
  const { width, height, limit = null, gapFactor = 3, padding = 1 } = options;
  const empty: SparklineGeometry = {
    segments: [],
    dots: [],
    limitY: null,
    min: 0,
    max: 0,
  };
  if (points.length === 0) return empty;

  const values = points.map((point) => point.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  // The limit widens the y domain so the reference line is visible even when
  // every reading sits far below it.
  const domainMin = limit !== null ? Math.min(min, limit) : min;
  const domainMax = limit !== null ? Math.max(max, limit) : max;
  const span = domainMax - domainMin;
  const top = padding;
  const bottom = Math.max(padding, height - padding);
  const toY = (value: number) =>
    span === 0
      ? (top + bottom) / 2
      : bottom - ((value - domainMin) / span) * (bottom - top);

  const firstTs = points[0]!.ts;
  const lastTs = points[points.length - 1]!.ts;
  const tsSpan = lastTs - firstTs;
  const toX = (point: SparklinePoint, index: number) =>
    // Every point sharing a timestamp (or a single point) degrades to even
    // index spacing rather than collapsing onto one x.
    tsSpan > 0
      ? ((point.ts - firstTs) / tsSpan) * width
      : points.length === 1
        ? width / 2
        : (index / (points.length - 1)) * width;

  const projected = points.map((point, index) => ({
    x: toX(point, index),
    y: toY(point.value),
  }));

  const intervals: number[] = [];
  for (let index = 1; index < points.length; index += 1) {
    intervals.push(points[index]!.ts - points[index - 1]!.ts);
  }
  const sorted = [...intervals].sort((left, right) => left - right);
  const median = sorted.length
    ? sorted.length % 2 === 1
      ? sorted[(sorted.length - 1) / 2]!
      : (sorted[sorted.length / 2 - 1]! + sorted[sorted.length / 2]!) / 2
    : 0;
  const gapThreshold =
    median > 0 ? median * gapFactor : Number.POSITIVE_INFINITY;

  const runs: { x: number; y: number }[][] = [];
  let current: { x: number; y: number }[] = [projected[0]!];
  for (let index = 1; index < projected.length; index += 1) {
    if (intervals[index - 1]! > gapThreshold) {
      runs.push(current);
      current = [];
    }
    current.push(projected[index]!);
  }
  runs.push(current);

  const segments: string[] = [];
  const dots: { x: number; y: number }[] = [];
  for (const run of runs) {
    if (run.length === 1) {
      dots.push(run[0]!);
      continue;
    }
    segments.push(
      run
        .map(
          (node, index) =>
            `${index === 0 ? "M" : "L"}${node.x.toFixed(2)} ${node.y.toFixed(2)}`,
        )
        .join(" "),
    );
  }

  // No range check: the domain above was widened to include the limit, so it
  // is inside it by construction.
  const limitY = limit !== null ? toY(limit) : null;
  return { segments, dots, limitY, min, max };
}

/**
 * A hand-rolled inline-SVG trend curve.
 *
 * Purely presentational: it renders exactly the points it is handed, breaks
 * the line across sampling gaps, and never smooths, resamples, or extrapolates.
 * A series with fewer than two points renders nothing — a single reading is
 * not a trend.
 */
export function AnsichSparkline({
  points,
  width = 120,
  height = 28,
  limit = null,
  title,
  className,
}: {
  points: SparklinePoint[];
  width?: number;
  height?: number;
  limit?: number | null;
  title: string;
  className?: string;
}) {
  if (points.length < 2) return null;
  const geometry = buildSparklinePath(points, { width, height, limit });
  if (geometry.segments.length === 0 && geometry.dots.length === 0) return null;

  return (
    <svg
      role="img"
      aria-label={title}
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      className={cn(
        "text-muted-foreground shrink-0 overflow-visible",
        className,
      )}
    >
      <title>{title}</title>
      {geometry.limitY !== null && (
        <line
          x1={0}
          x2={width}
          y1={geometry.limitY}
          y2={geometry.limitY}
          stroke="currentColor"
          strokeWidth={1}
          strokeDasharray="2 2"
          opacity={0.45}
        />
      )}
      {geometry.segments.map((segment, index) => (
        <path
          key={index}
          d={segment}
          fill="none"
          stroke="currentColor"
          strokeWidth={1.25}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      ))}
      {geometry.dots.map((dot, index) => (
        <circle
          key={index}
          cx={dot.x}
          cy={dot.y}
          r={1.25}
          fill="currentColor"
        />
      ))}
    </svg>
  );
}
