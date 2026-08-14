import type {
  TrajectoryRecord,
  TrajectoryRecordStatus,
  TrajectoryTurn,
} from "./types";

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
    }
  | {
      id: string;
      type: "step";
      turn: TrajectoryTurn;
      step: number;
      status: TrajectoryRecordStatus;
      records: readonly TrajectoryRecord[];
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

function stepStatus(records: readonly TrajectoryRecord[]) {
  if (records.some((record) => record.status === "error")) {
    return "error";
  }
  if (records.some((record) => record.status === "running")) {
    return "running";
  }
  if (records.some((record) => record.status === "incomplete")) {
    return "incomplete";
  }
  return "complete";
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
    let currentStep: number | undefined;
    for (const record of records) {
      if (record.step !== undefined && record.step !== currentStep) {
        currentStep = record.step;
        const stepRecords = records.filter(
          (candidate) => candidate.step === currentStep,
        );
        rows.push({
          id: `step:${turn.id}:${currentStep}`,
          type: "step",
          turn,
          step: currentStep,
          status: stepStatus(stepRecords),
          records: stepRecords,
        });
      }
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
