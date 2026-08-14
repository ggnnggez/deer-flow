import type {
  TrajectoryRecordKind,
  TrajectoryRecordStatus,
  TrajectoryTurn,
} from "./types";

export interface TrajectoryTimelineSpan {
  id: string;
  kind: TrajectoryRecordKind;
  label: string;
  step?: number;
  status?: TrajectoryRecordStatus;
  startedAt: number;
  completedAt: number;
  durationMs: number;
  leftPercent: number;
  widthPercent: number;
  ttftPercent?: number;
}

export interface TrajectoryTimelineLane {
  id: string;
  label: string;
  spans: TrajectoryTimelineSpan[];
}

export interface TrajectoryTimelineModel {
  startedAt: number;
  completedAt: number;
  durationMs: number;
  lanes: TrajectoryTimelineLane[];
}

/** Build a real-time Trajectory domain from records carrying journal timing. */
export function deriveTrajectoryTimeline(
  turns: readonly TrajectoryTurn[],
): TrajectoryTimelineModel | null {
  const records = turns
    .flatMap((turn) => turn.records)
    .filter(
      (record) =>
        (record.kind === "assistant" || record.kind === "tool") &&
        record.timing !== undefined,
    );
  if (records.length === 0) {
    return null;
  }

  const startedAt = Math.min(
    ...records.map((record) => record.timing!.started_at),
  );
  const completedAt = Math.max(
    ...records.map((record) => record.timing!.completed_at),
  );
  const durationMs = completedAt - startedAt;
  const scaleDuration = Math.max(durationMs, 1);
  const lanes = new Map<string, TrajectoryTimelineLane>();

  for (const record of records) {
    const timing = record.timing!;
    const laneId =
      record.kind === "assistant"
        ? "assistant"
        : `tool:${record.toolName ?? record.label}`;
    let lane = lanes.get(laneId);
    if (!lane) {
      lane = {
        id: laneId,
        label:
          record.kind === "assistant"
            ? record.label
            : `TOOL · ${record.toolName ?? record.label}`,
        spans: [],
      };
      lanes.set(laneId, lane);
    }
    lane.spans.push({
      id: record.id,
      kind: record.kind,
      label: record.label,
      ...(record.step === undefined ? {} : { step: record.step }),
      ...(record.status === undefined ? {} : { status: record.status }),
      startedAt: timing.started_at,
      completedAt: timing.completed_at,
      durationMs: timing.duration_ms,
      leftPercent: ((timing.started_at - startedAt) / scaleDuration) * 100,
      widthPercent: (timing.duration_ms / scaleDuration) * 100,
      ...(timing.ttft_ms === undefined || timing.duration_ms === 0
        ? {}
        : { ttftPercent: (timing.ttft_ms / timing.duration_ms) * 100 }),
    });
  }

  return {
    startedAt,
    completedAt,
    durationMs,
    lanes: [...lanes.values()],
  };
}
