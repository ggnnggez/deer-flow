import { describe, expect, it } from "@rstest/core";

import { deriveTrajectoryTimeline } from "@/core/trajectory/timeline";
import type { TrajectoryTurn } from "@/core/trajectory/types";

describe("deriveTrajectoryTimeline", () => {
  it("places recorded Assistant and Tool spans on one absolute time domain", () => {
    const turns: TrajectoryTurn[] = [
      {
        id: "turn-1",
        number: 1,
        records: [
          {
            id: "assistant-1",
            kind: "assistant",
            label: "ASSISTANT",
            content: "Working",
            step: 1,
            timing: {
              started_at: 1_000,
              first_token_at: 1_250,
              completed_at: 2_000,
              duration_ms: 1_000,
              ttft_ms: 250,
            },
          },
          {
            id: "tool-bash",
            kind: "tool",
            label: "bash",
            toolName: "bash",
            content: "pnpm test",
            step: 1,
            timing: {
              started_at: 2_100,
              completed_at: 2_900,
              duration_ms: 800,
            },
          },
          {
            id: "tool-search",
            kind: "tool",
            label: "web_search",
            toolName: "web_search",
            content: "DeerFlow",
            step: 1,
            timing: {
              started_at: 2_200,
              completed_at: 2_600,
              duration_ms: 400,
            },
          },
        ],
      },
    ];

    const timeline = deriveTrajectoryTimeline(turns);

    expect(timeline).toMatchObject({
      startedAt: 1_000,
      completedAt: 2_900,
      durationMs: 1_900,
    });
    expect(timeline?.lanes.map((lane) => lane.id)).toEqual([
      "assistant",
      "tool:bash",
      "tool:web_search",
    ]);
    expect(timeline?.lanes[0]?.spans[0]).toMatchObject({
      id: "assistant-1",
      leftPercent: 0,
      ttftPercent: 25,
    });
    expect(timeline?.lanes[0]?.spans[0]?.widthPercent).toBeCloseTo(52.63, 2);
    expect(timeline?.lanes[1]?.spans[0]?.leftPercent).toBeCloseTo(57.89, 2);
    expect(timeline?.lanes[1]?.spans[0]?.widthPercent).toBeCloseTo(42.11, 2);
  });
});
