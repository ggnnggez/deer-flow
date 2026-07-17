export type AnsichControlValue =
  | "unknown"
  | "created"
  | "running"
  | "completed"
  | "failed"
  | "interrupted";

export type AnsichObservationKind =
  | "task.created"
  | "task.started"
  | "task.completed"
  | "task.failed"
  | "task.interrupted"
  | "step.started"
  | "step.closed"
  | "llm.requested"
  | "llm.responded"
  | "llm.failed"
  | "content.produced"
  | "context.snapshotted"
  | "observability.degraded";

export interface AnsichNamedVersion {
  name: string;
  version: string;
}

export interface AnsichProducer extends AnsichNamedVersion {
  instance_id: string;
}

export interface AnsichControlBelief {
  value: AnsichControlValue;
  as_of: string | null;
  asserted_at: string;
  source: AnsichNamedVersion;
  fidelity_class: "hard";
  selected_by: AnsichNamedVersion;
  evidence_obs_ids: string[];
}

export interface AnsichTask {
  task_id: string;
  source_kind: string;
  source_id: string;
  control: AnsichControlBelief;
}

export interface AnsichObservation {
  ingest_seq: number;
  obs_id: string;
  schema_version: number;
  kind: AnsichObservationKind;
  occurred_at: string;
  recorded_at: string;
  task_id: string;
  step_id: string | null;
  subject_type:
    | "task"
    | "step"
    | "llm_attempt"
    | "content_block"
    | "context_snapshot";
  subject_id: string;
  fidelity_class: "hard";
  producer: AnsichProducer;
  producer_seq: number;
  source_event_id: string;
  correlation_id: string;
  causation_obs_id: string | null;
  payload: Record<string, unknown> | null;
  payload_ref_id: string | null;
}

export interface AnsichLostRange {
  first_sequence: number;
  last_sequence: number;
  task_id: string | null;
  producer_name: string | null;
  producer_instance_id: string | null;
}

export interface AnsichHealth {
  status: "healthy" | "degraded" | "failed" | "stopped";
  queue_depth: number;
  queue_capacity: number;
  accepted_count: number;
  dropped_count: number;
  lost_ranges: AnsichLostRange[];
  watermark: number | null;
  lag_ms: number;
  failed_jobs: number;
  loss_detected: boolean;
  range_known: boolean;
  storage_available: boolean;
}

export interface AnsichTaskListResponse {
  items: AnsichTask[];
  next_cursor: string | null;
  projection_status: AnsichHealth;
}

export interface AnsichTaskResponse {
  task: AnsichTask;
  projection_status: AnsichHealth;
}

export interface AnsichTimelineResponse {
  items: AnsichObservation[];
  next_cursor: string | null;
  projection_status: AnsichHealth;
}

export interface AnsichLlmAttempt {
  attempt_id: string;
  task_id: string;
  step_id: string | null;
  actor_kind: "lead_agent" | "subagent" | "system_operation";
  operation_id: string | null;
  operation_kind:
    | "title"
    | "summarization"
    | "memory"
    | "goal"
    | "other"
    | null;
  attempt_no: number;
  status: "requested" | "success" | "failed" | "incomplete";
  request_obs_id: string | null;
  response_obs_id: string | null;
  failure_obs_id: string | null;
  provider_model: string | null;
  usage: Record<string, number>;
  response_metadata: Record<string, unknown>;
  latency_ms: number | null;
  context_snapshot_id: string | null;
  effective: boolean;
}

export interface AnsichStep {
  step_id: string;
  task_id: string;
  step_seq: number;
  actor_kind: "lead_agent" | "subagent";
  status: "deciding" | "acting" | "closed" | "model_failed";
  result: "acting" | "final_answer" | "model_failed" | null;
  started_obs_id: string;
  closed_obs_id: string | null;
  effective_attempt_no: number | null;
  effective_context_snapshot_id: string | null;
  issued_tools: Array<Record<string, unknown>>;
  attempts: AnsichLlmAttempt[];
}

export interface AnsichContextItem {
  ordinal: number;
  channel: "message" | "tool_schema";
  role: "system" | "user" | "assistant" | "tool" | null;
  name: string | null;
  block_id: string;
  kind: string;
  content_hash: string;
  visible_bytes: number;
  estimated_tokens: number;
  metadata: Record<string, unknown>;
  sensitivity_flags: string[];
  payload_available: boolean;
  body: null;
}

export interface AnsichContextSnapshot {
  snapshot_id: string;
  task_id: string;
  step_id: string | null;
  operation_id: string | null;
  attempt_no: number;
  request_obs_id: string;
  message_count: number;
  tool_schema_count: number;
  visible_bytes: number;
  estimated_tokens: number;
  estimator_name: string;
  estimator_version: string;
  adapter_name: string;
  adapter_version: string;
  configured_model: string | null;
  response_format: unknown;
  generation_settings: Record<string, unknown>;
  redactions: Array<Record<string, unknown>>;
  warnings: string[];
  items: AnsichContextItem[];
}

export interface AnsichStepsResponse {
  items: AnsichStep[];
  system_operations: AnsichLlmAttempt[];
  projection_status: AnsichHealth;
}

export interface AnsichStepResponse {
  step: AnsichStep;
  projection_status: AnsichHealth;
}

export interface AnsichContextResponse {
  context: AnsichContextSnapshot;
  projection_status: AnsichHealth;
}

export interface AnsichContentPayloadResponse {
  payload: {
    block_id: string;
    content_type: string;
    body: unknown;
  };
}
