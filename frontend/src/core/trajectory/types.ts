import type { TokenUsage } from "@/core/messages/usage";

export type TrajectoryRecordKind = "assistant" | "system" | "tool" | "user";
export type TrajectoryRecordStatus =
  | "complete"
  | "error"
  | "incomplete"
  | "running";

export interface TrajectoryRecord {
  id: string;
  kind: TrajectoryRecordKind;
  label: string;
  content: string;
  messageId?: string;
  result?: string;
  status?: TrajectoryRecordStatus;
  step?: number;
  toolCallId?: string;
  toolName?: string;
  usage?: TokenUsage;
}

export interface TrajectoryTurn {
  id: string;
  number: number;
  durationSeconds?: number;
  usage?: TokenUsage;
  records: TrajectoryRecord[];
}
