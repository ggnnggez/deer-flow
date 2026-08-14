import { describe, expect, it } from "@rstest/core";

import { buildTrajectoryRows } from "@/core/trajectory/rows";
import type { TrajectoryTurn } from "@/core/trajectory/types";

const TURNS: TrajectoryTurn[] = [
  {
    id: "turn-1",
    number: 1,
    records: [
      {
        id: "message:user-1",
        kind: "user",
        label: "USER",
        content: "Inspect the project",
      },
      {
        id: "tool:call-1",
        kind: "tool",
        label: "bash",
        content: "rg --files",
        result: "README.md",
      },
    ],
  },
  {
    id: "turn-2",
    number: 2,
    records: [
      {
        id: "message:user-2",
        kind: "user",
        label: "USER",
        content: "Explain the result",
      },
    ],
  },
];

describe("buildTrajectoryRows", () => {
  it("keeps collapsed turns as headers and expands matching records for search", () => {
    expect(
      buildTrajectoryRows(TURNS, {
        collapsedTurnIds: new Set(["turn-1"]),
        query: "",
      }).map((row) => row.id),
    ).toEqual(["turn:turn-1", "turn:turn-2", "record:message:user-2"]);

    expect(
      buildTrajectoryRows(TURNS, {
        collapsedTurnIds: new Set(["turn-1"]),
        query: "readme",
      }).map((row) => row.id),
    ).toEqual(["turn:turn-1", "record:tool:call-1"]);
  });

  it("inserts step headers and summarizes the visible tool lifecycle", () => {
    const turns: TrajectoryTurn[] = [
      {
        id: "turn-steps",
        number: 1,
        records: [
          { id: "user", kind: "user", label: "USER", content: "Check it" },
          {
            id: "assistant-1",
            kind: "assistant",
            label: "ASSISTANT",
            content: "Running checks",
            status: "complete",
            step: 1,
          },
          {
            id: "tool-1",
            kind: "tool",
            label: "bash",
            content: "pnpm test",
            status: "running",
            step: 1,
          },
          {
            id: "assistant-2",
            kind: "assistant",
            label: "ASSISTANT",
            content: "Inspecting output",
            status: "complete",
            step: 2,
          },
        ],
      },
    ];

    const rows = buildTrajectoryRows(turns, {
      collapsedTurnIds: new Set(),
      query: "",
    });

    expect(rows.map((row) => row.id)).toEqual([
      "turn:turn-steps",
      "record:user",
      "step:turn-steps:1",
      "record:assistant-1",
      "record:tool-1",
      "step:turn-steps:2",
      "record:assistant-2",
    ]);
    expect(rows.find((row) => row.id === "step:turn-steps:1")).toMatchObject({
      type: "step",
      step: 1,
      status: "running",
    });
  });
});
