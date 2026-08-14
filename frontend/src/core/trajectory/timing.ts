import type { Message } from "@langchain/langgraph-sdk";

import type { RunMessage } from "@/core/threads/types";

export interface TrajectoryTiming {
  started_at: number;
  first_token_at?: number;
  completed_at: number;
  duration_ms: number;
  ttft_ms?: number;
}

function nonNegativeFiniteNumber(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) && value >= 0
    ? value
    : undefined;
}

/** Convert authoritative journal timestamps into the message timing payload. */
export function trajectoryTimingOfRunMessage(
  message: RunMessage,
): TrajectoryTiming | undefined {
  const completedAt = Date.parse(message.created_at);
  const durationMs = nonNegativeFiniteNumber(message.metadata.latency_ms);
  if (!Number.isFinite(completedAt) || durationMs === undefined) {
    return undefined;
  }

  const startedAt = completedAt - durationMs;
  const ttft = nonNegativeFiniteNumber(message.metadata.ttft_ms);
  const ttftMs = ttft !== undefined && ttft <= durationMs ? ttft : undefined;
  return {
    started_at: startedAt,
    ...(ttftMs === undefined ? {} : { first_token_at: startedAt + ttftMs }),
    completed_at: completedAt,
    duration_ms: durationMs,
    ...(ttftMs === undefined ? {} : { ttft_ms: ttftMs }),
  };
}

/** Read a normalized timing payload from an externally sourced message. */
export function trajectoryTimingOfMessage(
  message: Message,
): TrajectoryTiming | undefined {
  const value = message.additional_kwargs?.trajectory_timing;
  if (typeof value !== "object" || value === null) {
    return undefined;
  }
  const record = value as Record<string, unknown>;
  const startedAt = nonNegativeFiniteNumber(record.started_at);
  const completedAt = nonNegativeFiniteNumber(record.completed_at);
  const durationMs = nonNegativeFiniteNumber(record.duration_ms);
  if (
    startedAt === undefined ||
    completedAt === undefined ||
    durationMs === undefined ||
    completedAt < startedAt
  ) {
    return undefined;
  }
  const firstTokenAt = nonNegativeFiniteNumber(record.first_token_at);
  const ttftMs = nonNegativeFiniteNumber(record.ttft_ms);
  const hasValidFirstToken =
    firstTokenAt !== undefined &&
    ttftMs !== undefined &&
    firstTokenAt >= startedAt &&
    firstTokenAt <= completedAt &&
    ttftMs <= durationMs;
  return {
    started_at: startedAt,
    ...(hasValidFirstToken ? { first_token_at: firstTokenAt } : {}),
    completed_at: completedAt,
    duration_ms: durationMs,
    ...(hasValidFirstToken ? { ttft_ms: ttftMs } : {}),
  };
}
