/** The read contract served by `GET /api/context-residency/tasks/{task_id}`. */

export interface ResidencyMember {
  ordinal: number;
  block_id: string;
  estimated_tokens: number;
  visible_bytes: number;
  resolution_status: "available" | "missing";
}

export interface ResidencyAttempt {
  attempt_id: string;
  step_id: string;
  step_seq: number;
  attempt_no: number;
  effective: boolean;
  snapshot_id: string;
  /** Inventory completeness — not the provider call's outcome. */
  status: "complete" | "incomplete";
  outcome?: string | null;
  occurred_at: string | null;
  model_name?: string | null;
  estimated_tokens: number;
  visible_bytes: number;
  message_count: number;
  tool_schema_count: number;
  members: ResidencyMember[];
}

export interface ResidencyBlockMeta {
  block_id: string;
  kind: string | null;
  role: string | null;
  name: string | null;
  channel: "message" | "tool_schema";
  content_hash: string | null;
  source_identity: string | null;
  summary_content_hash?: string | null;
}

export interface ResidencyCompression {
  compression_id: string;
  summary_block_id: string | null;
  occurred_at: string | null;
  status: string;
  before_tokens: number;
  after_tokens: number;
  removed_block_ids: string[];
  preserved_block_ids: string[];
  positioned_before_attempt_id: string | null;
  compacted_count?: number;
  kept_count?: number;
}

export interface ResidencyTask {
  task_id: string;
  run_id: string;
  thread_id: string;
  kind: string;
  parent_task_id: string | null;
  agent_name: string | null;
  started_at: string;
  stopped_at: string | null;
  outcome: string | null;
}

export interface ProjectionStatus {
  enabled: boolean;
  running: boolean;
  queue_depth: number;
  accepted: number;
  dropped: number;
  flushed: number;
  write_failures: number;
  estimator: string;
  max_attempts: number;
}

export interface ResidencyResponse {
  task_id: string;
  task: ResidencyTask;
  attempts: ResidencyAttempt[];
  blocks: Record<string, ResidencyBlockMeta>;
  compressions: ResidencyCompression[];
  attempts_truncated: boolean;
  projection_status: ProjectionStatus | null;
}

export interface ThreadTasksResponse {
  thread_id: string;
  tasks: ResidencyTask[];
  projection_status: ProjectionStatus | null;
}
