import { describe, expect, it } from "@rstest/core";

import { buildSparklinePath } from "@/components/workspace/ansich/sparkline";

const BOX = { width: 100, height: 20 };

function evenSeries(values: number[], stepMs = 60_000) {
  return values.map((value, index) => ({ ts: index * stepMs, value }));
}

describe("buildSparklinePath", () => {
  it("returns nothing for an empty series", () => {
    const geometry = buildSparklinePath([], BOX);
    expect(geometry.segments).toEqual([]);
    expect(geometry.dots).toEqual([]);
    expect(geometry.limitY).toBeNull();
  });

  it("draws one unbroken segment for evenly spaced samples", () => {
    const geometry = buildSparklinePath(evenSeries([10, 20, 30]), BOX);
    expect(geometry.segments).toHaveLength(1);
    expect(geometry.min).toBe(10);
    expect(geometry.max).toBe(30);
    // Oldest point at x=0, newest at the right edge.
    expect(geometry.segments[0]).toMatch(/^M0\.00 /);
    expect(geometry.segments[0]).toContain("L100.00 ");
  });

  it("maps a rising series to a falling y (SVG y grows downward)", () => {
    const geometry = buildSparklinePath(evenSeries([0, 100]), {
      ...BOX,
      padding: 0,
    });
    expect(geometry.segments[0]).toBe("M0.00 20.00 L100.00 0.00");
  });

  it("breaks the line across a gap wider than 3x the median interval", () => {
    // Intervals: 60s, 60s, 600s, 60s -> median 60s, threshold 180s.
    const points = [
      { ts: 0, value: 1 },
      { ts: 60_000, value: 2 },
      { ts: 120_000, value: 3 },
      { ts: 720_000, value: 4 },
      { ts: 780_000, value: 5 },
    ];
    const geometry = buildSparklinePath(points, BOX);
    expect(geometry.segments).toHaveLength(2);
    expect(geometry.dots).toEqual([]);
  });

  it("does not break on a gap at exactly the 3x threshold", () => {
    const points = [
      { ts: 0, value: 1 },
      { ts: 60_000, value: 2 },
      { ts: 240_000, value: 3 },
    ];
    // Intervals 60s and 180s -> median 120s, threshold 360s: no break.
    expect(buildSparklinePath(points, BOX).segments).toHaveLength(1);
  });

  it("keeps a point stranded between two gaps as a dot rather than dropping it", () => {
    // Median interval 60s; the lone sample at t=60min is isolated by an
    // outage on either side.
    const points = [
      { ts: 0, value: 1 },
      { ts: 60_000, value: 2 },
      { ts: 120_000, value: 3 },
      { ts: 180_000, value: 4 },
      { ts: 3_600_000, value: 9 },
      { ts: 7_200_000, value: 5 },
      { ts: 7_260_000, value: 6 },
      { ts: 7_320_000, value: 7 },
    ];
    const geometry = buildSparklinePath(points, BOX);
    expect(geometry.segments).toHaveLength(2);
    expect(geometry.dots).toHaveLength(1);
  });

  it("never interpolates: a gap produces two paths, not one longer path", () => {
    const gapped = buildSparklinePath(
      [
        { ts: 0, value: 1 },
        { ts: 60_000, value: 2 },
        { ts: 60_000 * 40, value: 3 },
        { ts: 60_000 * 41, value: 4 },
      ],
      BOX,
    );
    const contiguous = buildSparklinePath(evenSeries([1, 2, 3, 4]), BOX);
    expect(contiguous.segments).toHaveLength(1);
    expect(gapped.segments).toHaveLength(2);
  });

  it("centres a flat series instead of dividing by a zero span", () => {
    const geometry = buildSparklinePath(evenSeries([7, 7, 7]), {
      ...BOX,
      padding: 0,
    });
    expect(geometry.segments[0]).toBe("M0.00 10.00 L50.00 10.00 L100.00 10.00");
  });

  it("spaces identically timestamped points evenly rather than stacking them", () => {
    const geometry = buildSparklinePath(
      [
        { ts: 5, value: 1 },
        { ts: 5, value: 2 },
        { ts: 5, value: 3 },
      ],
      { ...BOX, padding: 0 },
    );
    expect(geometry.segments[0]).toContain("M0.00 ");
    expect(geometry.segments[0]).toContain("L50.00 ");
    expect(geometry.segments[0]).toContain("L100.00 ");
  });

  it("widens the domain for a limit above every reading and places its line", () => {
    const geometry = buildSparklinePath(evenSeries([10, 20]), {
      ...BOX,
      padding: 0,
      limit: 100,
    });
    expect(geometry.limitY).toBe(0);
    // The readings are compressed toward the bottom by the widened domain.
    expect(geometry.segments[0]).toBe("M0.00 20.00 L100.00 17.78");
  });

  it("omits the reference line when no limit was reported", () => {
    expect(buildSparklinePath(evenSeries([1, 2]), BOX).limitY).toBeNull();
  });
});
