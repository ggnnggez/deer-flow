import type { TrajectoryRecord, TrajectoryTurn } from "./types";

export type TrajectoryRow =
  | {
      id: string;
      type: "turn";
      turn: TrajectoryTurn;
    }
  | {
      id: string;
      type: "record";
      turn: TrajectoryTurn;
      record: TrajectoryRecord;
    };

export interface TrajectoryRowOptions {
  collapsedTurnIds: ReadonlySet<string>;
  query: string;
}

function matches(record: TrajectoryRecord, query: string) {
  const searchable = [
    record.label,
    record.content,
    record.result,
    record.toolName,
  ]
    .filter((value): value is string => typeof value === "string")
    .join("\n")
    .toLocaleLowerCase();
  return searchable.includes(query);
}

/** Flatten turns into the stable row sequence consumed by the virtual list. */
export function buildTrajectoryRows(
  turns: TrajectoryTurn[],
  { collapsedTurnIds, query }: TrajectoryRowOptions,
): TrajectoryRow[] {
  const normalizedQuery = query.trim().toLocaleLowerCase();
  const rows: TrajectoryRow[] = [];

  for (const turn of turns) {
    const records = normalizedQuery
      ? turn.records.filter((record) => matches(record, normalizedQuery))
      : turn.records;
    if (normalizedQuery && records.length === 0) {
      continue;
    }
    rows.push({ id: `turn:${turn.id}`, type: "turn", turn });
    if (!normalizedQuery && collapsedTurnIds.has(turn.id)) {
      continue;
    }
    for (const record of records) {
      rows.push({
        id: `record:${record.id}`,
        type: "record",
        turn,
        record,
      });
    }
  }

  return rows;
}
