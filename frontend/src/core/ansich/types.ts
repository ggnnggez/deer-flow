export type AnsichControlValue =
  | "unknown"
  | "created"
  | "running"
  | "completed"
  | "failed"
  | "interrupted";

export type AnsichLifecycleKind =
  | "task.created"
  | "task.started"
  | "task.completed"
  | "task.failed"
  | "task.interrupted";

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
  obs_id: string;
  schema_version: number;
  kind: AnsichLifecycleKind;
  occurred_at: string;
  recorded_at: string;
  task_id: string;
  subject_type: "task";
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
  projection_status: AnsichHealth;
}
