/** The read contracts served by the extension's admin routes under `/api/context-residency/`. */

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
  /**
   * The model's context window in tokens when the host's model config (or the
   * extension's options) declared it; `null` when unknown. 100% of the
   * composition bar.
   */
  context_window_tokens?: number | null;
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

export interface ThroughputPoint {
  /** UTC minute bucket, `YYYY-MM-DDTHH:MMZ`. */
  minute: string;
  events: number;
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
  queue_capacity?: number;
  flush_interval_ms?: number;
  table_prefix?: string;
  started_at?: string | null;
  uptime_seconds?: number | null;
  last_flush_at?: string | null;
  last_event_at?: string | null;
  last_drop_at?: string | null;
  last_batch_events?: number;
  last_batch_ms?: number;
  throughput?: ThroughputPoint[];
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

/** One row of `GET /api/context-residency/tasks`: the task plus the counts a reader locates it by. */
export interface TaskListItem extends ResidencyTask {
  steps: number;
  attempts: number;
  incomplete_attempts: number;
  compactions: number;
  /** The largest recorded request of the task, and that request's window and composition by kind. */
  peak_tokens: number;
  peak_attempt_id: string | null;
  peak_context_window: number | null;
  peak_by_kind: Record<string, number>;
  last_attempt_at: string | null;
  /** Null while no stop event was recorded. */
  duration_seconds: number | null;
}

export type TaskSort = "started" | "last" | "duration" | "attempts" | "compactions" | "incomplete" | "peak";

export interface TaskListResponse {
  tasks: TaskListItem[];
  total: number;
  limit: number;
  offset: number;
  sort: string;
  direction: "asc" | "desc";
  projection_status: ProjectionStatus | null;
}

export type HealthLevel = "ok" | "warning" | "error";

export interface HealthDiagnostic {
  level: HealthLevel;
  code: string;
  title: string;
  detail: string;
  remedy: string | null;
  affected: string[];
}

export interface HealthStorage {
  backend: string;
  database: string | null;
  file_bytes: number | null;
  table_prefix: string;
  rows: Record<string, number>;
  earliest_task_started_at: string | null;
}

export interface HealthQuality {
  attempts_total: number;
  attempts_complete: number;
  attempts_incomplete: number;
  compactions_total: number;
  compactions_with_task: number;
  compactions_positioned: number;
  compactions_unanchored: number;
  tasks_open: number;
  tasks_stale: number;
  stale_after_minutes: number;
}

export interface HealthConfig {
  enabled: boolean;
  max_attempts: number;
  queue_capacity: number;
  flush_interval_ms: number;
  stale_task_after_minutes: number;
  context_windows: Record<string, number>;
  default_context_window: number | null;
  table_prefix: string;
  extension_version: string | null;
  api_version: string | null;
  placements: string[];
  scopes: string[];
}

/** `GET /api/context-residency/health`: the extension's own recording state. */
export interface HealthResponse {
  generated_at: string;
  status: ProjectionStatus;
  /** Null while the service has no database. */
  storage: HealthStorage | null;
  quality: HealthQuality | null;
  diagnostics: HealthDiagnostic[];
  config: HealthConfig;
  throughput: ThroughputPoint[];
}
