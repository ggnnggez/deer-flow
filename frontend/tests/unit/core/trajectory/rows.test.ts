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
});
