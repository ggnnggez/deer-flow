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
  | "agent_release.resolved"
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
    | "agent_release"
    | "alert"
    | "scope";
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

/**
 * Every lifecycle state the Collector derives (spec 11 §2), as a runtime list so
 * code that has to *validate* one — a persisted dismissal record, say — reuses
 * the contract instead of restating it as a second literal list that can drift.
 */
export const ANSICH_HEALTH_STATUSES = [
  "starting",
  "healthy",
  "degraded",
  "recovering",
  "failed",
  "shutting_down",
  "stopped",
] as const;

/**
 * One producer instance's own accounting. The ledger is bounded in the
 * Collector, and an entry evicted from it is counted in
 * `AnsichHealth.evicted_producer_count` rather than disappearing silently.
 *
 * `last_accepted_sequence` and `last_successful_flush_at` are `null` when this
 * producer has never had one — never a zero or an epoch, which would read as a
 * real reading.
 */
export interface AnsichProducerHealth {
  producer_name: string;
  producer_instance_id: string;
  accepted_count: number;
  dropped_count: number;
  last_accepted_sequence: number | null;
  serialization_failures: number;
  last_successful_flush_at: string | null;
}

/**
 * The persistence writer's own state.
 *
 * `in_flight_count` is every outstanding row — the writer's parked batches and
 * a terminal flush barrier's own write alike. Those rows have left
 * `queue_depth`, so this is the only place they are visible; it is not a
 * writer-backlog gauge.
 *
 * `poison_observation_count` counts rows storage kept refusing individually,
 * which were dropped alone so their batch-mates could land. It is a monotonic
 * row count and nothing more: it does not separate a handful of unwritable rows
 * from a longer storage incident.
 */
export interface AnsichWriterHealth {
  consecutive_failures: number;
  backoff_until: string | null;
  in_flight_count: number;
  poison_observation_count: number;
}

export interface AnsichHealth {
  status: (typeof ANSICH_HEALTH_STATUSES)[number];
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
  producers: AnsichProducerHealth[];
  writer: AnsichWriterHealth;
  /**
   * How many times the bounded producer ledger evicted an entry — eviction
   * events, not distinct producers lost, since the same producer can be evicted
   * and re-created repeatedly.
   */
  evicted_producer_count: number;
  /**
   * Loss with no Task to subject an `observability.degraded` Observation
   * against, so nothing has written it into the Observation stream. Counted
   * here so the gap is visible rather than inferred from its absence elsewhere.
   */
  unreported_global_lost_range_count: number;
}

/**
 * One projector's job ledger as the database holds it (P11-B §4).
 *
 * The four counts are the whole unsettled split, and `retry` is a bucket of its
 * own: a job a hard error re-armed is work still owed, not work never started,
 * so folding it into `pending` would make re-armed jobs disappear from this
 * view while they are still outstanding.
 *
 * `complete_through` is a **continuity** mark, not progress. It is the last
 * ingest sequence below which this projector owes nothing — one durably failed
 * job holds it down no matter how far past that hole the projector has
 * otherwise run, which is exactly what makes it readable as "nothing below here
 * is owed". It is therefore lower than a per-worker progress number whenever
 * anything is outstanding, and must never be labelled as progress. `null` only
 * when the store holds no Observations at all.
 */
export interface AnsichProjectorHealth {
  projector_name: string;
  projector_version: string;
  pending: number;
  retry: number;
  processing: number;
  failed: number;
  complete_through: number | null;
}

/**
 * Database-side projection truth, merged into `GET /health` beside the process
 * block (P11-B §4).
 *
 * `status` is the field every other one is conditional on: when it is
 * `unreachable` the projector rows are empty and every number is `null`. `null`
 * means unknown here and nowhere means zero — a block that could not be read
 * must never render as "0ms behind, 0 failed jobs". The process block is still
 * served in full either way, because `GET /health` stays the one Ansich route
 * that answers while storage is down; the panel mirrors that by keeping the
 * process-side numbers visible under an explicit unreachable banner.
 *
 * `failed_jobs` here is the **authoritative** count, read live from both job
 * tables across every worker; `AnsichHealth.failed_jobs` keeps its name and its
 * process-local, advisory meaning. `stale_completion_count` is the one field in
 * this block that is not database truth at all: it is the reporting worker's
 * own count of writes dropped because the job had been taken over.
 */
/**
 * Where one component's running version came from, and how well the switch is
 * evidenced.
 *
 * - `code_default` — no stored row. The build's own default runs; nobody
 *   activated anything, so nothing is owed an audit. This is the ordinary
 *   state, not a missing one: the table records *deviations* from the default.
 * - `activated_audited` — a deliberate switch with its audit Observation still
 *   in the store.
 * - `activated_expired` — a deliberate switch whose audit Observation has aged
 *   out under retention. The selection stands; only the evidence pointer is
 *   gone.
 * - `activated_unaudited` — the row was written while the audit write was
 *   degraded, so no Observation was ever recorded. This is the one value that
 *   should prompt a question.
 */
export type AnsichActiveVersionOrigin =
  | "code_default"
  | "activated_audited"
  | "activated_expired"
  | "activated_unaudited";

/**
 * Which version of one versioned component the store says is authoritative.
 *
 * Reported for every component the build knows, including those with no stored
 * row — such a component appears at its `code_default_version` with
 * `origin: "code_default"`. Both versions are carried because "what runs" and
 * "what would run untouched" are different questions, and they are legitimately
 * equal (an operator may deliberately activate the version that is already the
 * default, which leaves a row and an audit trail saying so).
 *
 * `activated_at` / `activated_by` / `audit_obs_id` are `null` for a code
 * default because nobody activated it — never an epoch date, never a
 * placeholder actor.
 */
export interface AnsichActiveVersion {
  component_kind: "projector" | "resolver";
  component_name: string;
  active_version: string;
  code_default_version: string;
  origin: AnsichActiveVersionOrigin;
  activated_at: string | null;
  activated_by: string | null;
  audit_obs_id: string | null;
}

export interface AnsichDatabaseHealth {
  status: "reachable" | "unreachable";
  projectors: AnsichProjectorHealth[];
  lag_ms: number | null;
  failed_jobs: number | null;
  stale_completion_count: number | null;
  /**
   * `null` means the block could not be read, exactly like the numbers above.
   * An **empty array is impossible**: a reachable store always answers with one
   * entry per component the build knows, so there is no state where the block
   * is readable and the list is legitimately empty. Rendering `null` as "no
   * versions" would report an outage as a configuration.
   */
  active_versions: AnsichActiveVersion[] | null;
}

/**
 * What `GET /api/ansich/health` answers: the process block every other Ansich
 * response already carries as `projection_status`, plus the additive database
 * block merged at the route.
 */
export interface AnsichHealthResponse extends AnsichHealth {
  database: AnsichDatabaseHealth;
}

export type AnsichFailedJobKind = "projection" | "assessor";

export interface AnsichFailedJob {
  job_id: string;
  kind: AnsichFailedJobKind;
  name: string;
  version: string;
  task_id: string;
  status: string;
  attempts: number;
  last_error: string | null;
  available_at: string;
}

export interface AnsichFailedJobError {
  attempt: number;
  error_type: string;
  message: string;
  occurred_at: string;
}

export interface AnsichFailedJobDetail extends AnsichFailedJob {
  errors: AnsichFailedJobError[];
}

export interface AnsichFailedJobsResponse {
  items: AnsichFailedJob[];
  projection_status: AnsichHealth;
}

export interface AnsichFailedJobDetailResponse {
  job: AnsichFailedJobDetail;
  projection_status: AnsichHealth;
}

export interface AnsichFailedJobsRetryResponse {
  /** Rows the re-arm changed. A re-arm count, never a completion claim. */
  retried: number;
  /**
   * Jobs the store still owed when the retry returned — every projection or
   * assessor job left pending/retry/processing, including work this retry did
   * not touch. Read beside `retried`: a re-armed job is projected afterwards,
   * so `retried` alone cannot say the failures are gone.
   */
  unsettled: number;
  projection_status: AnsichHealth;
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
  inclusive: AnsichTaskUsageValue[];
  inclusive_status: "available";
}

export interface AnsichTaskUsageSource {
  source_task_id: string;
  values: AnsichTaskUsageValue[];
}

export interface AnsichTaskSpawn {
  parent_task_id: string;
  spawning_step_id: string;
  spawning_tool_call_id: string;
  child_task_id: string;
  established_obs_id: string;
  subagent_name: string | null;
}

export interface AnsichTaskTreeNode {
  task: AnsichTask;
  agent_release: AnsichTaskAgentReleaseResponse["binding"];
  heartbeat: AnsichHeartbeatBelief | null;
  current_step: {
    step_id: string;
    step_seq: number;
    actor_kind: string;
    status: string;
  } | null;
  usage: AnsichTaskUsage;
}

export interface AnsichTaskTree {
  root_task_id: string;
  direction: "ancestors" | "descendants" | "both";
  depth: number;
  nodes: AnsichTaskTreeNode[];
  edges: AnsichTaskSpawn[];
  truncated: boolean;
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
  active_child_count: number;
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

/**
 * Every Alert type that has a producer behind it, which is exactly what the UI
 * may advertise as a filter. The last two are the process-subject pair
 * (P11-B §3): they are opened by the periodic operations pass against the host
 * Scope rather than by anything one Task did.
 */
export const ANSICH_PRODUCED_ALERT_TYPES = [
  "budget_warning",
  "budget_exceeded",
  "exact_repetition",
  "tool_frequency",
  "heartbeat_missing",
  "long_dwell",
  "configuration_drift",
  "attempted_scope_violation",
  "realized_scope_violation",
  "unverified_effect",
  "environment_pressure",
  "environment_leak_suspected",
  "projection_failure",
  "observability_degradation",
] as const;

export type AnsichAlertType = (typeof ANSICH_PRODUCED_ALERT_TYPES)[number];

export type AnsichAlertWorkflowState =
  | "open"
  | "acknowledged"
  | "dismissed"
  | "resolved";

/**
 * Every authority class the backend Belief resolver can attach to an assertion.
 * `soft_human` is emitted by resolver v2 (a human annotation that is not a hard
 * override), and `unknown` is carried by synthesized unassessed quality Beliefs
 * — absence of an assessment is a first-class state, not a missing field.
 */
export type AnsichAuthorityClass =
  | "human_override"
  | "deterministic"
  | "configured_rule"
  | "automated"
  | "soft_human"
  | "unknown";

/**
 * Belief/evaluation fidelity. `unknown` belongs to synthesized unassessed
 * quality Beliefs, which have no assessment to take a fidelity from.
 */
export type AnsichFidelityClass = "hard" | "rule" | "soft" | "unknown";

export interface AnsichBeliefAssertion {
  assertion_id: string;
  subject_id: string;
  field_name: string;
  value: Record<string, unknown>;
  as_of: string;
  asserted_at: string;
  assessor: AnsichNamedVersion;
  config_hash: string;
  authority_class: AnsichAuthorityClass;
  fidelity_class: AnsichFidelityClass;
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
  scope: "local" | "inclusive";
  values: AnsichTaskUsageValue[];
  sources: AnsichTaskUsageSource[];
  projection_status: AnsichHealth;
}

export interface AnsichTaskChildrenResponse {
  items: AnsichTaskSpawn[];
  projection_status: AnsichHealth;
}

export interface AnsichTaskTreeResponse {
  tree: AnsichTaskTree;
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
  // Additive: null when no per-command environment sample was recorded for
  // this ToolCall (e.g. non-bash tools, or a provider without instrumentation).
  environment_sample: AnsichToolEnvironmentSample | null;
  projection_status: AnsichHealth;
}

// --- Environment observability (OS-level signals: fd/io/memory/disk/pressure) ---

export type AnsichEnvironmentScopeKind =
  | "container"
  | "process_group"
  | "host_shared";

export type AnsichEnvironmentCoverage =
  | "continuous"
  | "per_command"
  | "uninstrumented";

export interface AnsichEnvironmentMetric {
  metric: string;
  latest_value: number;
  limit: number | null;
  as_of: string;
  sample_count: number;
  window_started_at: string;
  consecutive_growth_count: number;
}

export interface AnsichEnvironmentBelief {
  field_name: string;
  value: Record<string, unknown>;
  as_of: string | null;
  asserted_at: string | null;
  source: AnsichNamedVersion;
  authority_class: string;
  fidelity_class: string;
  evidence_obs_ids: string[];
}

export interface AnsichEnvironmentAlertSummary {
  alert_id: string;
  alert_type: string;
  severity: string;
  workflow_state: string;
  opened_at: string;
  resolved_at: string | null;
  // The Tasks the assessor found `running` in this Scope when the triggering
  // sample was recorded (correlation, not causality). `null` means the read
  // model never recorded a set — render nothing, never a fallback derived
  // from evidence Observations (those only name the one Task that happened
  // to record a given sample, not the full running set).
  possibly_affected_task_ids: string[] | null;
}

export interface AnsichEnvironmentScope {
  scope_id: string;
  scope_kind: string;
  display_label: string;
  environment_scope: string;
  coverage: string;
  provider: string;
  metrics: AnsichEnvironmentMetric[];
  beliefs: AnsichEnvironmentBelief[];
  alerts: AnsichEnvironmentAlertSummary[];
}

export interface AnsichTaskEnvironmentResponse {
  task_id: string;
  scopes: AnsichEnvironmentScope[];
}

export interface AnsichEnvironmentHistoryPoint {
  occurred_at: string;
  value: number;
  // Whatever that sample itself reported; null when it carried no limit.
  limit: number | null;
}

export interface AnsichEnvironmentHistoryResponse {
  scope_id: string;
  environment_scope: string;
  metric: string;
  window_minutes: number;
  // The window held more surviving points than `max_points`; the newest were
  // kept. Older readings exist but are not in this series.
  truncated: boolean;
  // Oldest first. A sample that never reported this metric is absent, never
  // present as a 0 — a gap here is an honest gap, not a zero reading.
  points: AnsichEnvironmentHistoryPoint[];
}

export interface AnsichToolEnvSample {
  tool_call_id: string;
  started_at: string;
  ended_at: string;
  sample_count: number;
  fd_peak: number | null;
  io_read_bytes: number | null;
  io_write_bytes: number | null;
}

export interface AnsichTaskToolEnvSamplesResponse {
  task_id: string;
  truncated: boolean;
  // In execution order (oldest first).
  samples: AnsichToolEnvSample[];
}

export interface AnsichToolEnvironmentSample {
  tool_call_id: string;
  task_id: string;
  scope_id: string;
  io_read_bytes: number | null;
  io_write_bytes: number | null;
  fd_peak: number | null;
  sample_count: number;
  started_at: string;
  ended_at: string;
  obs_id: string;
}

export interface AnsichTaskScope {
  scope_id: string;
  scope_kind:
    | "owner"
    | "thread"
    | "workspace"
    | "sandbox"
    | "authorization"
    | "external_origin"
    | "host";
  external_ref_hash: string;
  display_label: string;
  parent_scope_id: string | null;
  created_obs_id: string;
  relation_role: string;
  relation_obs_id: string;
  inherited_from_task_id: string | null;
}

export interface AnsichTaskScopesResponse {
  scopes: { task_id: string; scopes: AnsichTaskScope[] };
  projection_status: AnsichHealth;
}

export interface AnsichAuthorizationPermission {
  resource: string;
  action: string;
  scope_id: string | null;
  effect: string;
}

export interface AnsichAuthorizationSnapshot {
  snapshot_id: string;
  tool_call_id: string;
  principal_scope_ids: string[];
  policy_id: string;
  policy_version: string;
  policy_hash: string;
  decision: "allowed" | "denied" | "unknown";
  details_available: boolean;
  effective_permissions: AnsichAuthorizationPermission[];
  resource_scope_ids: string[];
  reason_codes: string[];
  evaluated_at: string;
  evidence_obs_ids: string[];
}

export interface AnsichToolAuthorizationResponse {
  authorization: {
    tool_call_id: string;
    snapshots: AnsichAuthorizationSnapshot[];
    current_decision: "allowed" | "denied" | "unknown";
  } | null;
  projection_status: AnsichHealth;
}

export interface AnsichToolEffect {
  effect_id: string;
  tool_call_id: string;
  effect_class: string;
  phase: "potential" | "intended" | "observed";
  scope_id: string | null;
  target_hash: string | null;
  target_preview: string | null;
  fidelity_class: string;
  source_obs_id: string;
  result_metadata: Record<string, unknown>;
}

export interface AnsichToolEffectsResponse {
  effects: {
    tool_call_id: string;
    effects: AnsichToolEffect[];
    coverage: "complete" | "partial" | "unknown";
  } | null;
  projection_status: AnsichHealth;
}

export interface AnsichToolResultPayloadResponse {
  raw_result?: AnsichToolResult;
  visible_result?: AnsichToolResult;
  raw_payload?: AnsichContentPayloadResponse["payload"];
  visible_payload?: AnsichContentPayloadResponse["payload"];
}

export interface AnsichAgentReleaseSummary {
  release_id: string;
  namespace: string;
  agent_name: string;
  release_hash: string;
  schema_version: number;
  model_hash: string;
  prompt_hash: string;
  tool_catalog_hash: string;
  policy_hash: string;
  runtime_build_id: string;
  created_at: string;
  task_count: number;
  quality_status: "unassessed";
}

export interface AnsichAgentReleaseManifest {
  schema_version: number;
  namespace: string;
  agent_name: string;
  model: {
    requested: string | null;
    effective: string;
    provider: string | null;
    behavior_parameters: Record<string, unknown>;
  };
  prompt: {
    template_id: string;
    template_hash: string;
    rendered_base_prompt_hash: string;
    rendered_base_prompt_preview: string;
    soul_hash: string | null;
    available_skill_catalog_hash: string | null;
  };
  tools: Array<{
    name: string;
    description: string;
    argument_schema: Record<string, unknown>;
    schema_hash: string;
    source: string;
    deferred: boolean;
    behavior_metadata: Record<string, unknown>;
  }>;
  policy: {
    middleware_chain: Array<{
      name: string;
      public_parameters: Record<string, unknown>;
    }>;
    values: Record<string, unknown>;
  };
  runtime_build: {
    package_version: string;
    image_digest: string;
    git_commit: string;
  };
}

export interface AnsichAgentReleaseDetail {
  summary: AnsichAgentReleaseSummary;
  manifest: AnsichAgentReleaseManifest;
}

export interface AnsichAgentReleaseListResponse {
  items: AnsichAgentReleaseSummary[];
  operational_distributions: { availability: "unavailable" };
  projection_status: AnsichHealth;
}

export interface AnsichTaskAgentReleaseResponse {
  binding: {
    task_id: string;
    relation_role: "executed_by";
    established_obs_id: string;
    release: AnsichAgentReleaseDetail;
  } | null;
  provider_drift: AnsichBeliefAssertion | null;
  projection_status: AnsichHealth;
}

export interface AnsichReleaseFieldChange {
  path: string;
  left: unknown;
  right: unknown;
}

export interface AnsichAgentReleaseComparison {
  left_release_hash: string;
  right_release_hash: string;
  changed_components: Array<
    "model" | "prompt" | "tools" | "policy" | "runtime_build"
  >;
  model: AnsichReleaseFieldChange[];
  prompt: AnsichReleaseFieldChange[];
  tools: {
    added: Array<{ source: string; name: string }>;
    removed: Array<{ source: string; name: string }>;
    schema_changed: Array<{
      source: string;
      name: string;
      left: unknown;
      right: unknown;
    }>;
    description_changed: Array<{
      source: string;
      name: string;
      left: unknown;
      right: unknown;
    }>;
    source_changed: Array<{
      name: string;
      left_source: string;
      right_source: string;
    }>;
  };
  policy: AnsichReleaseFieldChange[];
  build: AnsichReleaseFieldChange[];
  quality_status: "unassessed";
}

/**
 * One dimension of a release-to-release quality comparison. `observed_delta` is
 * exactly that — an observed difference, never a significance claim — and it
 * exists only while `comparison_status` is `"comparable"`. `reason` carries the
 * machine-readable refusal (`no_shared_cohort`, `scale_mismatch`,
 * `insufficient_samples`, `observability_loss`) so a caller never parses prose.
 */
export interface AnsichQualityComparison {
  dimension: string;
  cohort_key: string;
  comparison_status: "comparable" | "not_comparable";
  reason: string | null;
  observed_delta: number | null;
  left_sample_count: number;
  right_sample_count: number;
  coverage: Record<string, unknown>;
  resolver: AnsichNamedVersion;
}

export interface AnsichAgentReleaseComparisonResponse {
  comparison: AnsichAgentReleaseComparison;
  /**
   * Optional: an older backend, or one without evaluation storage, omits the
   * block entirely. Consumers must render the structural comparison without it
   * rather than treating absence as "no quality difference".
   */
  quality?: {
    comparisons: AnsichQualityComparison[];
    cohort: string | null;
  };
  projection_status: AnsichHealth;
}

/**
 * The current semantic quality Belief for one dimension of one subject.
 *
 * `unassessed` is a first-class state: such a Belief still carries the complete
 * structure, with an explicit `{"status": "unassessed"}` value, the `unknown`
 * authority/fidelity classes and no evidence. Absence of an evaluation must
 * never be rendered as a verdict.
 */
export interface AnsichQualityBelief {
  dimension: string;
  value: Record<string, unknown>;
  source: AnsichNamedVersion;
  authority_class: AnsichAuthorityClass;
  fidelity_class: AnsichFidelityClass;
  as_of: string | null;
  resolver: AnsichNamedVersion | null;
  conflicting_assertion_count: number;
  evidence_obs_ids: string[];
  unassessed: boolean;
}

/**
 * One row of the evaluation query index. This is a metadata projection:
 * expected/actual/rationale bodies stay in the Observation payload and are read
 * through the audited raw-payload route.
 *
 * `cohort_key` is `null` when the evaluation declared no cohort. The release
 * quality read model instead uses the empty-string sentinel
 * (`AnsichReleaseQualityCohort.cohort_key`); the two spellings are deliberate
 * and must not be normalized into each other.
 */
export interface AnsichEvaluation {
  evaluation_obs_id: string;
  subject_type: string;
  subject_id: string;
  task_id: string;
  evaluation_kind: string;
  dimension: string;
  verdict: string | null;
  score: number | null;
  scale_min: number | null;
  scale_max: number | null;
  scale_higher_is_better: boolean | null;
  assessor_name: string;
  assessor_version: string | null;
  authority_class: AnsichAuthorityClass;
  fidelity_class: AnsichFidelityClass;
  cohort_key: string | null;
  suite_id: string | null;
  suite_version: string | null;
  case_id: string | null;
  occurred_at: string;
}

export interface AnsichTaskEvaluationsResponse {
  task_id: string;
  quality_beliefs: AnsichQualityBelief[];
  evaluations: AnsichEvaluation[];
  projection_status: AnsichHealth;
}

export interface AnsichStepEvaluationsResponse {
  step_id: string;
  evaluations: AnsichEvaluation[];
  projection_status: AnsichHealth;
}

/**
 * One evaluation Observation's full payload, read lazily through the audited
 * `no-store` route. The `evaluation` block carries the bodies the index omits —
 * `expected`, `actual`, `rationale` — and is typed as an open record because
 * the payload is the raw contract envelope, not a projection.
 */
export interface AnsichEvaluationPayloadResponse {
  evaluation_obs_id: string;
  payload: {
    evaluation?: Record<string, unknown>;
    [key: string]: unknown;
  };
}

/**
 * One `(cohort, dimension)` quality cell of one AgentRelease.
 *
 * `cohort_key` is the aggregation sentinel, where `""` means the evaluations
 * declared no cohort. It is a sample list, never a comparison population: the
 * same empty key on two releases says nothing about the two sample sets sharing
 * a suite, version, or case set.
 */
export interface AnsichReleaseQualityCohort {
  dimension: string;
  cohort_key: string;
  assessed_count: number;
  pass_count: number;
  fail_count: number;
  partial_count: number;
  mean_score: number | null;
  scale: Record<string, unknown> | null;
  as_of: string;
}

export interface AnsichReleaseQualityResponse {
  release_id: string;
  cohorts: AnsichReleaseQualityCohort[];
  projection_status: AnsichHealth;
}
