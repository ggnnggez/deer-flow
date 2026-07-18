export type AnsichControlValue =
  | "unknown"
  | "created"
  | "running"
  | "completed"
  | "failed"
  | "interrupted";

export type AnsichTaskLifecycleScope = "all" | "active" | "terminal";

export type AnsichObservationKind =
  | "task.created"
  | "task.started"
  | "task.completed"
  | "task.failed"
  | "task.interrupted"
  | "task.heartbeat"
  | "budget.configured"
  | "budget.consumed"
  | "step.started"
  | "step.closed"
  | "llm.requested"
  | "llm.responded"
  | "llm.failed"
  | "content.produced"
  | "context.state_recorded"
  | "context.snapshotted"
  | "context.compressed"
  | "tool.issued"
  | "tool.started"
  | "tool.returned_raw"
  | "tool.result_visible"
  | "tool.denied"
  | "tool.timed_out"
  | "tool.cancelled"
  | "tool.failed"
  | "tool.unknown_terminal"
  | "operator.action_requested"
  | "operator.action_succeeded"
  | "operator.action_failed"
  | "operator.alert_acknowledged"
  | "operator.alert_dismissed"
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
  observability_status: "healthy" | "degraded";
  tool_calls_issued: number;
  tool_calls_executed: number;
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
    | "tool_call"
    | "content_block"
    | "context_state"
    | "context_snapshot"
    | "context_compression"
    | "alert";
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
  queue_bytes: number;
  queue_byte_capacity: number;
  accepted_count: number;
  dropped_count: number;
  lost_ranges: AnsichLostRange[];
  watermark: number | null;
  lag_ms: number;
  failed_jobs: number;
  loss_detected: boolean;
  range_known: boolean;
  storage_available: boolean;
  queue_high_watermark: number;
  queue_byte_high_watermark: number;
  snapshot_request_count: number;
  snapshot_observations_accepted: number;
  snapshot_observations_dropped: number;
  snapshot_count: number;
  snapshot_item_count: number;
  snapshot_visible_bytes: number;
  incomplete_snapshot_count: number;
  missing_content_block_count: number;
}

export interface AnsichTaskListResponse {
  items: AnsichTask[];
  next_cursor: string | null;
  projection_status: AnsichHealth;
}

export interface AnsichTaskResponse {
  task: AnsichTask;
  behavior: AnsichBeliefAssertion | null;
  projection_status: AnsichHealth;
}

export type AnsichUsageDimension =
  | "input_tokens"
  | "output_tokens"
  | "total_tokens"
  | "llm_attempts"
  | "steps"
  | "tool_calls_issued"
  | "tool_calls_executed"
  | "wall_time_ms"
  | "child_tasks_spawned";

export interface AnsichTaskUsageValue {
  dimension: AnsichUsageDimension;
  aggregation_scope: "local" | "inclusive";
  value: number;
  as_of: string;
  complete_through_ingest_seq: number;
}

export interface AnsichTaskUsage {
  task_id: string;
  local: AnsichTaskUsageValue[];
  inclusive_status: "not_available";
}

export interface AnsichTaskBudget {
  entity_id: string;
  task_id: string;
  dimension: AnsichUsageDimension;
  aggregation_scope: "local" | "inclusive";
  warning_limit: number | null;
  hard_limit: number | null;
  enforcement: boolean;
  source_kind: "release_default" | "runtime_override" | "shadow";
  requested_value: number | null;
  effective_value: number;
  configured_obs_id: string;
}

export interface AnsichTaskBudgets {
  task_id: string;
  budgets: AnsichTaskBudget[];
}

export interface AnsichRuleBeliefBase {
  asserted_at: string;
  source: AnsichNamedVersion;
  fidelity_class: "rule";
  selected_by: AnsichNamedVersion;
  evidence_obs_ids: string[];
}

export interface AnsichHeartbeatBelief extends AnsichRuleBeliefBase {
  value: "unknown" | "fresh" | "stale";
  as_of: string | null;
  age_ms: number | null;
}

export interface AnsichDwellBelief extends AnsichRuleBeliefBase {
  value: "unknown" | "normal" | "long";
  since: string | null;
  duration_ms: number | null;
}

export interface AnsichBudgetHealthBelief extends AnsichRuleBeliefBase {
  dimension: AnsichUsageDimension;
  aggregation_scope: "local" | "inclusive";
  value: "unknown" | "within" | "warning" | "exceeded";
  usage_value: number | null;
  warning_limit: number | null;
  hard_limit: number | null;
  overshoot: number | null;
  as_of: string | null;
}

export interface AnsichActiveTask {
  task_id: string;
  run_id: string;
  source_kind: string;
  owner_id: string | null;
  thread_id: string | null;
  agent_id: string | null;
  control: AnsichControlBelief;
  current_step: {
    step_id: string;
    step_seq: number;
    actor_kind: string;
    status: string;
  } | null;
  current_tool: {
    tool_call_id: string;
    tool_name: string;
    call_seq: number;
    status: string;
  } | null;
  dwell: AnsichDwellBelief;
  heartbeat: AnsichHeartbeatBelief;
  usage: AnsichTaskUsage;
  budgets: AnsichTaskBudgets;
  budget_health: AnsichBudgetHealthBelief[];
  duration_ms: number;
  observability_status: "healthy" | "degraded";
  projection_watermark: number | null;
  projection_lag_ms: number;
  lost_ranges: AnsichLostRange[];
  last_evidence_at: string;
  updated_at: string;
}

export interface AnsichActiveTaskListResponse {
  items: AnsichActiveTask[];
  next_cursor: string | null;
  projection_status: AnsichHealth;
  updated_at: string | null;
}

export type AnsichAlertType =
  | "budget_warning"
  | "budget_exceeded"
  | "exact_repetition"
  | "tool_frequency"
  | "heartbeat_missing"
  | "long_dwell"
  | "observability_degradation"
  | "projection_failure";

export type AnsichAlertWorkflowState =
  | "open"
  | "acknowledged"
  | "dismissed"
  | "resolved";

export interface AnsichBeliefAssertion {
  assertion_id: string;
  subject_id: string;
  field_name: string;
  value: Record<string, unknown>;
  as_of: string;
  asserted_at: string;
  assessor: AnsichNamedVersion;
  config_hash: string;
  authority_class:
    | "human_override"
    | "deterministic"
    | "configured_rule"
    | "automated";
  fidelity_class: "hard" | "rule" | "soft";
  confidence: number | null;
  evidence_obs_ids: string[];
}

export interface AnsichAlertSummary {
  alert_id: string;
  subject_id: string;
  alert_type: AnsichAlertType;
  episode: number;
  severity: "info" | "warning" | "critical";
  workflow_state: AnsichAlertWorkflowState;
  workflow_version: number;
  shadow: boolean;
  opened_at: string;
  as_of: string;
  updated_at: string;
  resolved_at: string | null;
  rule: AnsichNamedVersion;
  rule_config_hash: string;
  stable_condition_key: string;
  source_assertion_id: string;
  resolution_reason: string | null;
  dismissal_reason: string | null;
  evidence_count: number;
}

export interface AnsichAlertWorkflowEvent {
  event_id: string;
  obs_id: string;
  action: string;
  from_state: AnsichAlertWorkflowState;
  to_state: AnsichAlertWorkflowState;
  workflow_version: number;
  reason: string | null;
  operator_id: string | null;
  occurred_at: string;
}

export interface AnsichAlertDetail {
  alert: AnsichAlertSummary;
  source_belief: AnsichBeliefAssertion;
  evidence: AnsichObservation[];
  current_beliefs: AnsichBeliefAssertion[];
  workflow_history: AnsichAlertWorkflowEvent[];
  available_actions: Array<
    "acknowledge" | "dismiss" | "interrupt" | "rollback"
  >;
}

export interface AnsichAlertListResponse {
  items: AnsichAlertSummary[];
  next_cursor: string | null;
  projection_status: AnsichHealth;
}

export interface AnsichAlertDetailResponse {
  alert: AnsichAlertDetail;
  projection_status: AnsichHealth;
}

export interface AnsichAlertWorkflowResponse {
  alert: AnsichAlertSummary;
  projection_status: AnsichHealth;
}

export interface AnsichOperatorAction {
  action_id?: string;
  task_id: string;
  action_type: "interrupt" | "rollback";
  idempotency_key: string;
  status: "requested" | "succeeded" | "failed";
  requested_obs_id?: string | null;
  terminal_obs_id?: string | null;
  result: Record<string, unknown> | null;
  created_at?: string;
  updated_at?: string;
}

export interface AnsichOperatorActionResponse {
  action: AnsichOperatorAction;
  audit_status: "recorded" | "degraded";
  idempotent_replay: boolean;
}

export interface AnsichTaskUsageResponse {
  usage: AnsichTaskUsage;
  projection_status: AnsichHealth;
}

export interface AnsichTaskBudgetsResponse {
  budgets: AnsichTaskBudgets;
  health: AnsichBudgetHealthBelief[];
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
  tool_calls: AnsichToolCall[];
}

export interface AnsichToolBelief {
  value: string;
  as_of: string | null;
  asserted_at: string;
  source: AnsichNamedVersion;
  fidelity_class: "hard";
  selected_by: AnsichNamedVersion;
  evidence_obs_ids: string[];
}

export interface AnsichToolResult {
  result_role: "raw" | "visible";
  content_block_id: string;
  source_obs_id: string;
  content_hash: string | null;
  byte_size: number | null;
  payload_available: boolean;
  metadata: Record<string, unknown>;
}

export interface AnsichContentDerivation {
  derived_block_id: string;
  source_block_id: string;
  transform_kind:
    | "unchanged"
    | "error_normalized"
    | "sanitized"
    | "truncated"
    | "externalized"
    | "coalesced"
    | "clarification_card"
    | "compressed"
    | "memory_injected"
    | "skill_injected"
    | "vision_converted"
    | "copied"
    | "unknown";
  transform_version: string;
  established_obs_id: string;
  source_role: "source" | "preserved" | "removed" | "supporting";
  ordinal: number | null;
}

export interface AnsichContentBlock {
  block_id: string;
  kind: string;
  content_hash: string;
  byte_size: number;
  token_estimate: number;
  sensitivity_flags: string[];
  payload_status: "available" | "missing";
  producer: {
    producer_kind: string;
    producer_entity_id: string | null;
    producer_obs_id: string;
  } | null;
}

export interface AnsichLineageNode extends AnsichContentBlock {
  depth: number;
}

export interface AnsichLineageGap {
  block_id: string;
  depth: number;
  reason: "missing_content_block";
}

export interface AnsichContentLineage {
  semantic: "provenance";
  root_block_id: string;
  direction: "backward" | "forward";
  nodes: AnsichLineageNode[];
  edges: AnsichContentDerivation[];
  truncated: boolean;
  truncation_reason: "max_depth" | "max_nodes" | null;
  unknown_gaps: AnsichLineageGap[];
}

export interface AnsichPossibleExposureItem {
  task_id: string;
  step_id: string;
  step_seq: number;
  snapshot_id: string;
  snapshot_ordinal: number;
  descendant_block_id: string;
  descendant_depth: number;
  ordering: "later" | "unknown";
}

export interface AnsichPossibleExposures {
  semantic: "possible_exposure";
  root_block_id: string;
  nodes: AnsichLineageNode[];
  edges: AnsichContentDerivation[];
  items: AnsichPossibleExposureItem[];
  truncated: boolean;
  truncation_reason: "max_depth" | "max_nodes" | null;
  unknown_gaps: AnsichLineageGap[];
}

export interface AnsichContextCompressionItem {
  disposition: "source" | "preserved" | "removed";
  ordinal: number;
  block: AnsichContentBlock;
}

export interface AnsichContextCompression {
  compression_id: string;
  task_id: string;
  summary_operation_id: string | null;
  summary_block: AnsichContentBlock;
  before_tokens: number;
  after_tokens: number;
  before_visible_bytes: number;
  after_visible_bytes: number;
  algorithm: string;
  algorithm_version: string;
  source_obs_id: string;
  status: "complete" | "incomplete";
  items: AnsichContextCompressionItem[];
}

export interface AnsichContextCompressionSummary {
  compression_id: string;
  task_id: string;
  summary_operation_id: string | null;
  summary_block_id: string;
  before_tokens: number;
  after_tokens: number;
  before_visible_bytes: number;
  after_visible_bytes: number;
  algorithm: string;
  algorithm_version: string;
  source_obs_id: string;
  occurred_at: string;
  status: "complete" | "incomplete";
}

export interface AnsichToolCall {
  tool_call_id: string;
  task_id: string;
  step_id: string;
  step_seq: number;
  call_seq: number;
  provider_call_id: string | null;
  tool_name: string;
  args_hash: string;
  args_preview: unknown;
  tool_schema_block_id: string | null;
  issued_obs_id: string | null;
  started_obs_id: string | null;
  raw_terminal_obs_id: string | null;
  visible_result_obs_id: string | null;
  duration_ms: number | null;
  authorization: AnsichToolBelief;
  execution: AnsichToolBelief;
  visible_result: AnsichToolBelief;
  raw_results: AnsichToolResult[];
  visible_results: AnsichToolResult[];
  derivations: AnsichContentDerivation[];
}

export interface AnsichContextItem {
  ordinal: number;
  channel: "message" | "tool_schema";
  role: "system" | "user" | "assistant" | "tool" | null;
  name: string | null;
  message_id: string | null;
  source_identity: string | null;
  block_id: string;
  kind: string | null;
  content_hash: string | null;
  visible_bytes: number;
  estimated_tokens: number;
  metadata: Record<string, unknown>;
  sensitivity_flags: string[];
  payload_available: boolean;
  resolution_status: "available" | "missing";
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
  status: "complete" | "incomplete";
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

export interface AnsichContentLineageResponse {
  lineage: AnsichContentLineage;
  projection_status: AnsichHealth;
}

export interface AnsichPossibleExposuresResponse {
  exposures: AnsichPossibleExposures;
  projection_status: AnsichHealth;
}

export interface AnsichContextCompressionResponse {
  compression: AnsichContextCompression;
  projection_status: AnsichHealth;
}

export interface AnsichContextCompressionListResponse {
  items: AnsichContextCompressionSummary[];
  next_cursor: string | null;
  projection_status: AnsichHealth;
}

export interface AnsichToolCallResponse {
  tool_call: AnsichToolCall;
  projection_status: AnsichHealth;
}

export interface AnsichToolResultPayloadResponse {
  raw_result?: AnsichToolResult;
  visible_result?: AnsichToolResult;
  raw_payload?: AnsichContentPayloadResponse["payload"];
  visible_payload?: AnsichContentPayloadResponse["payload"];
}
