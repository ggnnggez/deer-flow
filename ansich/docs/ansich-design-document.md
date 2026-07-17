# Ansich — DeerFlow Agent Observability System Design (v0.2 Draft)

---

## 0. Purpose, Scope, and Status

This document is the direct basis for the first Ansich implementation inside
DeerFlow. It defines:

1. the decisions and observers Ansich serves;
2. the canonical observations collected from DeerFlow;
3. the entities, beliefs, and relations used to reconstruct the Agent world;
4. the embedded runtime, storage, projection, and query architecture;
5. the acceptance drills required before the design can be considered complete.

Ansich v1 is an **embedded module with a logically independent boundary**. It
runs in the DeerFlow Gateway process and shares DeerFlow's configured database,
but owns its contracts, tables, projection logic, and query API. Its design must
permit a later move to a separate service without changing the world model.

The initial product audience is **developers and operators**. An end-user
progress view is explicitly out of scope for v1: progress for an open-ended
Agent cannot be inferred honestly from Step count or elapsed time and requires a
separate goal/milestone model.

This document supersedes v0.1. The most important v0.2 changes are:

- Observer Lenses are separated from the shared world model.
- Agent becomes an immutable AgentRelease fingerprint.
- ContentBlock and ContextSnapshot become first-class lineage objects.
- logical Agent Steps are separated from physical LLM attempts and internal LLM
  operations.
- Alert is separated from Belief.
- Scope is multi-valued, and action intent, authorization, and observed effects
  are separate streams.
- External occurrences remain Observations unless they acquire persistent
  identity or lifecycle.
- the physical model uses a generic Entity registry plus typed core tables.
- collection is fail-open while existing DeerFlow runtime guards remain
  fail-safe.

Terminology:

- **Behavior model**: the schema of entities, states, relations, and valid
  judgments that Ansich can express.
- **World model**: the runtime projection populated from Observations.
- **Observation**: an append-only record of something a probe observed.
- **Belief Assertion**: one assessor's judgment about an entity at an evidence
  time.
- **Current Belief**: the assertion selected by a named, versioned resolver.
- **Hard evidence**: a direct system measurement or lifecycle signal, such as an
  exit code or counter.
- **Rule evidence**: a deterministic rule's interpretation of observations.
- **Soft evidence**: a fallible assessor's judgment, such as an LLM judge or
  human review.

---

## 1. Global Disciplines

These rules constrain every schema and implementation. Violating one is an
architectural defect.

### 1.1 Every state field is a Belief field

Any field that means "an object is in a state" must carry at least:

```text
Belief {
    value
    as_of              // time of the newest evidence supporting this assertion
    asserted_at        // time the assessor produced the assertion
    source             // named and versioned probe/assessor
    fidelity_class     // hard | rule | soft
    confidence?        // reserved; optional in v1
    selected_by?       // Current Belief only: resolver name/version
}
```

`unknown` is legal for control state when evidence is absent. `unassessed` is
legal for semantic state when no assessor has evaluated it. Bare state enums in
Ansich projections or API responses are forbidden.

### 1.2 Records and inference are separated

Observations, structural projections, Belief Assertions, Current Beliefs, and
relations live in separate structures. A probe may record `tool.returned_raw`; it
must not directly write `Task.behavior = on_track`. Every inferred Belief or
relation must link back to supporting Observation IDs.

### 1.3 One world model, multiple Observer Lenses

Developers and operators do not get separate truths. They read different
projections of the same observations and beliefs:

```text
Observation -> World Model -> Beliefs -> Developer Lens
                                  \----> Operator Lens
```

A Lens may select, aggregate, and explain. It may not silently change state or
certainty.

### 1.4 Security-bounded "record everything"

Ansich records every semantic signal that can affect an Agent decision:

- final structured model inputs;
- model completions returned to DeerFlow;
- Tool requests, raw results, and model-visible results;
- context composition and transformations;
- middleware/system-operation inputs and outputs needed for attribution.

"Everything" does not include platform credentials. Authorization headers,
cookies, request-scoped secrets, database DSNs, encryption keys, and secret
environment values must never enter Ansich. The lossless-reconstruction promise
therefore applies **after platform credential exclusion and known-secret
filtering**.

### 1.5 Collection is fail-open; runtime guards remain fail-safe

An Ansich storage, serialization, or projection failure must not change a
DeerFlow Task's execution result. The failure must instead produce an explicit
degraded signal and a lost sequence range when possible.

Token, loop, wall-time, authorization, and other enforcement required for safe
Agent execution remain in DeerFlow's local runtime path. D1 must not depend on
successful Ansich persistence in v1.

### 1.6 Projections are rebuildable and idempotent

Except for the Observation/Payload zone, all Ansich world, belief, relation, and
read-model tables are projections. Deleting them and replaying the same
Observations with the same projector versions must recreate the same result.

---

## 2. Decision and Observer Catalog

The decision catalog is the paymaster. Future disputes about fields, entities,
or probes are resolved by whether they serve D1-D4.

### D1 Runtime gating and intervention

- **Maker**: DeerFlow runtime guardian plus operator/on-call human.
- **Situation**: Task is executing.
- **Actions**: continue, inspect, interrupt while retaining the current
  checkpoint, or rollback to the pre-Run checkpoint. Durable pause/resume and a
  separate force-terminate API are not available in DeerFlow v1 and must not be
  simulated by relabeling interrupt as pause.
- **Required beliefs**: Task control state, behavior label, last activity,
  state dwell time, local/inclusive usage, budget health, absolute-limit
  breaches, observability health.
- **Timeliness**: minute-level; v1 UI polling every 5-10 seconds is sufficient.

### D2 Post-hoc attribution

- **Maker**: developer.
- **Situation**: Task failed, was interrupted, or received an explicit poor
  quality evaluation.
- **Actions**: fix prompt, tool, model, policy, context management, environment,
  or input classification.
- **Required beliefs and facts**: earliest erroneous Step (when assessed), the
  Step's decision-basis inventory, Tool intent/outcome, context transformations,
  and possible downstream exposure through lineage.

### D3 Capability drift

- **Maker**: developer/owner.
- **Situation**: before/after an AgentRelease change.
- **Actions**: release, roll back, or gather more comparable samples.
- **Required data**: immutable release fingerprints, comparable Task cohorts,
  behavior/usage distributions, and external evaluations.
- **Honesty constraint**: when semantic quality is unassessed, Ansich may report
  operational distribution changes but must not claim capability improvement.

### D4 Safety audit

- **Maker**: operator/owner/auditor.
- **Situation**: periodic or triggered review.
- **Actions**: tighten permissions, Scope, Tool access, or freeze the Agent.
- **Required facts and beliefs**: Step-level action intent, effective
  authorization snapshot, allow/deny decision, potential and observed effects,
  attempted/realized Scope violations, and unknown effect ranges.

### 2.1 Developer Lens

The Developer Lens must answer:

- what happened in a Task and in which logical Step;
- what the model could see at a Step's effective LLM attempt;
- which Tool schemas were exposed;
- where a ContentBlock originated and how it was transformed;
- which later Steps could see a suspect block or a derivative;
- how AgentRelease manifests differ;
- which claims are evidence-backed and which remain unassessed.

### 2.2 Operator Lens

The Operator Lens must answer:

- which Tasks are active and when they last produced evidence;
- current Step/ToolCall state and dwell time;
- local and inclusive resource usage;
- which alerts are open, why, and with what evidence;
- whether Ansich itself is current, lagging, degraded, or failed;
- which interruption actions DeerFlow actually supports.

### 2.3 Evaluation input

Runtime success is not proof of semantic correctness. Quality judgments enter as
Observations:

```text
evaluation.recorded {
    subject_ref
    evaluation_kind    // user_feedback | developer_annotation |
                       // benchmark_assertion | unit_test | llm_judge
    dimension
    verdict_or_score
    expected?
    actual?
    rationale?
    assessor
    assessor_version?
    fidelity_class
}
```

An ongoing review workflow may later become a Review Entity. A single evaluation
remains an Observation.

---

## 3. Abstraction and Projection Pipeline

```text
DeerFlow source event
    -> Canonical Observation
    -> Structural Projector
    -> World Model
    -> Assessor
    -> Belief Assertions
    -> Belief Resolver
    -> Current Belief
    -> Observer Lens
```

### 3.1 Structural Projector

The Structural Projector performs only deterministic consequences, such as:

- `task.created` registers a Task;
- `llm.requested` registers an attempt projection and ContextSnapshot;
- an Agent AIMessage completes the Step decision projection and registers its
  ToolCalls;
- `subagent.started` registers a child Task and `spawned` relation;
- `context.compressed` creates a summary ContentBlock and derivation edges.

It must not judge whether a Step was good or whether a Task is stuck.

### 3.2 Control-state Projector

Direct lifecycle observations produce hard control-state assertions and
Transitions. Missing events remain `unknown`; elapsed time alone does not mutate
hard control state.

### 3.3 Assessors

V1 assessors are deterministic and versioned:

- absolute Step/token/wall-time limit assessor;
- exact Tool/Step action-signature repetition assessor;
- heartbeat/dwell assessor where configured;
- evaluation projector for developer/user/benchmark input.

Generic Tool frequency is an operational signal, not automatically a runaway
judgment.

### 3.4 Resolver

Belief Assertions from different sources are not last-write-wins. The v1
resolver is named and versioned. Initial precedence is:

```text
control state: latest valid hard lifecycle evidence
semantic state: explicit human override > deterministic hard evaluation >
                configured rule > soft automated assessor;
                newest as_of within the same class
```

Changing this policy creates a new resolver version and permits replay.

### 3.5 Late and out-of-order evidence

Projectors must tolerate late observations. A `tool.returned_raw` observation may
temporarily create an incomplete ToolCall projection before `tool.issued`
arrives. Missing attributes remain unknown, historical Transitions are repaired
by evidence time, and Current Beliefs must not regress merely because an older
event committed late.

---

## 4. Entity Catalog and Identity

### 4.1 Core Entity table

| Entity | Identity | Role | Serves |
|---|---|---|---|
| AgentRelease | namespace + agent_name + release_hash | immutable actor configuration | D2-D4 |
| Task | Ansich task_id; source kind/id retained | top-level or child work item | D1-D4 |
| Step | step_id + unique(task_id, step_seq) | atomic Agent accountability unit | D1, D2, D4 |
| ToolCall | Ansich ID + unique(step_id, call_seq) | Step sub-action | D1, D2, D4 |
| ContextWindow | task_id | capacity-bearing Task resource | D1, D2 |
| ContextState | task_id + state_hash | reusable immutable ordered context inventory | D2-D4 |
| ContextSnapshot | snapshot_id; Step + attempt number | actual structured decision input inventory | D2-D4 |
| ContentBlock | block_id; content hash is non-identity | immutable lineage unit | D2-D4 |
| TaskBudget | task_id + dimension + aggregation scope | effective resource constraint | D1 |
| Scope | scope_id + kind | user/thread/workspace/sandbox/auth boundary | D4 |
| Alert | alert key + episode | operator work item | D1, D4 |

LLM attempts, system operations, heartbeats, budget-consumption events, and
one-off external occurrences are Observations or query projections, not core
Entities in v1.

### 4.2 AgentRelease

AgentRelease is an immutable, sanitized canonical manifest. Its identity is:

```text
namespace
+ agent_name
+ model_hash
+ prompt_hash
+ tool_catalog_hash
+ policy_hash
+ runtime_build_id
```

The canonical manifest stores readable components and a SHA-256 release hash.
Secrets and runtime object addresses are excluded. It distinguishes:

- requested and effective configured model names;
- prompt template hash, rendered base prompt hash, SOUL hash, and available
  skill-catalog hash;
- actual loaded Tool names/descriptions/argument schemas/source/deferred state;
- effective middleware order, summarization, guardrail, budget, loop, Tool
  output, subagent, plan, and non-interactive policies;
- DeerFlow package/image/git build revision when available.

Provider-reported model name/revision is not known when the Task-start release
is resolved and therefore does not mutate or participate in AgentRelease
identity. It is recorded on each LLM response Observation and may produce a
configuration-drift Alert when it disagrees with the release manifest.

Only effective behavior values participate in the hash. Requested values may be
retained for diagnosis. Dynamic date, memory, summary text, activated skill body,
and per-Step promoted Tool schemas belong to ContextSnapshots rather than the
release.

Custom-agent self-update during a Task records `external.config_changed`; the
current Task retains its starting AgentRelease, and the next Task resolves a new
release.

### 4.3 Task

For DeerFlow:

- Gateway `run_id` maps to a top-level Ansich Task;
- `thread_id` is a conversation Scope, not a Task;
- a user retry/new message is a new Task linked by `follows_up` when known;
- hidden goal continuations inside the same Run remain the same Task;
- a `task` Tool delegation creates a child Task.

Ansich Task IDs are globally stable. Provider or DeerFlow source IDs are stored
as source attributes, not assumed globally unique.

### 4.4 Step and LLM attempt

One Step is one **logical Agent model decision plus all ToolCalls it emits**.

- multiple provider retries are multiple `llm_attempt` Observations in one Step;
- parallel ToolCalls in one AIMessage belong to the same Step;
- the next Agent model decision after Tool results is the next Step;
- a direct final answer is a valid no-Tool Step;
- title, summarization, memory extraction, and goal-evaluator LLM calls are
  `system_operation` Observations, not Steps;
- subagent decisions are Steps of the child Task.

`step_seq` is monotonic within a Task, never reused, and continued from durable
state after recovery. The final/successful LLM attempt determines the Step's
`effective_context_snapshot_id`.

### 4.5 ToolCall

Ansich never uses provider `tool_call_id` as its primary identity. Real DeerFlow
records demonstrate provider IDs can be reused after compaction. The identity is
`step_id + call_seq`; provider ID is an attribute.

Agent intent (`tool.issued`), authorization, raw execution outcome, and
model-visible outcome are separate observation streams.

### 4.6 ContentBlock

A ContentBlock is an immutable occurrence with provenance. Equal content from
different producers receives different block IDs; `content_hash` supports
comparison and deduplication but is not identity.

V1 kinds include:

```text
user_input | assistant_output | tool_request | tool_result_raw |
tool_result_visible | system_prompt | summary | memory |
skill_instruction | middleware_injection | tool_schema |
image_or_attachment | unknown
```

Raw and visible Tool results are distinct. Sanitization, truncation,
externalization, coalescing, and compression create new blocks with explicit
`derived_from` edges.

### 4.7 ContextWindow, ContextState, and ContextSnapshot

ContextWindow is the Task-level capacity-bearing resource. Each real Agent LLM
attempt captures an attempt-specific ContextSnapshot immediately before the
LangChain model adapter receives the final structured request. The snapshot
references an immutable, reusable ContextState: identical retries may share the
same state while remaining distinct attempts and snapshot facts.

ContextState is stored as either a full ordered checkpoint or
`parent_state_id + ordered delta`. Deltas express append/remove/replace/reorder;
the storage chain is capped and periodically checkpointed so reads never require
unbounded traversal. This is a physical optimization only: query APIs always
materialize the complete strict-order inventory without requiring a live
process-local registry.

The v1 lossless boundary includes:

- ordered structured messages and roles;
- actual visible Tool schemas;
- response format;
- behavior-affecting generation parameters;
- model adapter name/version as provenance.

It does not include raw provider HTTP wire bytes or authorization headers.

Each snapshot item stores ordinal, channel, role, ContentBlock ID, visible bytes,
and estimated tokens. If origin cannot be resolved, the full visible block is
recorded with kind `unknown`. If a referenced parent state or ContentBlock has
not arrived, the ordinal remains present as a typed `missing` item and the
snapshot is `incomplete`; late evidence repairs it to `complete` without
poisoning replay. Compression lineage remains explicit: Phase 4 must record its
source/preserved/removed inventories and summary `derived_from` edges rather
than inferring them from text diffs.

### 4.8 Budget and usage

Usage is measurement; Budget is a constraint. V1 usage dimensions are:

```text
input_tokens | output_tokens | total_tokens | llm_attempts | steps |
tool_calls_issued | tool_calls_executed | wall_time_ms |
child_tasks_spawned
```

TaskBudget stores effective warning/hard limits and whether they apply to local
or inclusive usage. Raw consumption is recorded only on the Task where it
occurred; inclusive usage is projected through `spawned` relations to avoid
double-writing evidence.

DeerFlow's effective runtime policy is the enforcement source of truth. Ansich
may define shadow thresholds only when marked `enforcement = false`.

### 4.9 Scope

A Task participates in multiple Scopes: owner, thread, workspace, sandbox,
authorization, and external origin. A single `scope_ref` is insufficient.

AuthorizationSnapshot records the effective permissions at a ToolCall decision
time. Tool intent, authorization decision, and actual side effects are separate.
V1 effect classes are:

```text
filesystem_read | filesystem_write | filesystem_delete | process_execute |
network_read | external_write | permission_change | child_task_spawn | unknown
```

Effect phase is `potential`, `intended`, or `observed`. Unknown MCP/bash effects
remain unknown; exit code zero is not evidence that no other side effect occurred.

### 4.10 Alert

Alert is an operator workflow Entity, not a Belief. It references a source
Belief/rule and supporting evidence. Stable keys deduplicate repeated
confirmations within one condition episode.

V1 Alert types include budget warning/exceeded, Tool repetition/frequency,
heartbeat missing, long dwell, attempted/realized Scope violation, unverified
effect, observability degradation, and projection failure.

Acknowledge or dismiss changes Alert lifecycle, not the underlying Task Belief.
A human dismissal may separately create a higher-priority human semantic
assertion.

### 4.11 Event-to-Entity promotion rule

A noun is not automatically an Entity. It becomes one when it has stable identity
across observations, lifecycle/state, important relation endpoints, or direct
operator actions. A provider timeout remains an Observation. A multi-event
provider outage may later become an Incident Entity.

---

## 5. State, Belief, Transition, and Alert Semantics

### 5.1 Control state

```text
Task:
  unknown -> created -> running -> {completed | failed | interrupted}

Step:
  unknown -> deciding -> closed
  unknown -> deciding -> acting -> observing -> closed

ToolCall:
  unknown -> issued -> {acting | returned | denied | timed_out |
                        cancelled | failed | unknown_terminal}
  acting -> {returned | timed_out | cancelled | failed | unknown_terminal}
```

Denied Tools do not imply an executed effect. A clarification request may return
`human_input_requested` and close normally. A user interrupt closes incomplete
work as cancelled when causality is known, otherwise unknown terminal.

### 5.2 Semantic labels

```text
Task behavior:  on_track | drifting | stuck | runaway | unassessed
Step quality:   sound | redundant | erroneous | unassessed
Output quality: sound | degraded | invalid | unassessed
Budget health:  within_limit | warning | exceeded | unknown
```

V1 leaves semantic quality unassessed unless a configured deterministic rule or
external evaluation supplies evidence.

### 5.3 Belief Assertions and Current Beliefs

Assertions are append-only. Current Beliefs are resolver projections. Evidence
is represented through a junction table, not an array embedded in the assertion.
Assertions from different assessors may coexist.

### 5.4 Fallback detection

V1 may assert runaway from:

- an absolute configured Step/token/wall-time limit breach;
- exact repetition of a canonical Step action signature across the configured
  window.

Canonical action signature is based on Tool name plus secret-filtered canonical
arguments; a parallel Step uses a sorted multiset of ToolCall signatures.

Generic Tool-frequency warnings, changing search queries, or middleware events
whose detector is not mapped to a specific Ansich assessor produce Alerts or
metrics but do not automatically assert runaway.

### 5.5 Dwell and heartbeat

Dwell is computed from Transition evidence times. Active Task heartbeat is
emitted by an outer Run worker timer, not by model/tool stream activity. Missing
heartbeat is a rule judgment and Alert, not retroactive hard evidence that the
Task stopped.

### 5.6 Alert lifecycle

```text
unknown -> open -> acknowledged -> resolved
                  \-> resolved
open -> resolved
```

Dismissal is retained as an operator Observation and feedback, never a delete.
Absolute-limit facts remain true after Task termination even when the associated
operational Alert is resolved with reason `task_terminal`.

---

## 6. Relation Catalog and Lineage

| Relation | Direction | Physical modeling | Serves |
|---|---|---|---|
| belongs_to | Step/ToolCall -> parent | typed FK | all |
| executed_by | Task -> AgentRelease | typed FK | D2-D4 |
| follows_up | Task -> predecessor Task | generic relation/typed FK | D2, D3 |
| spawned | Step -> child Task | first-class relation | D1, D4 |
| within_scope | Entity -> Scope, role attributed | first-class relation | D4 |
| snapshot_contains | ContextSnapshot -> ContentBlock | ordered typed table | D2-D4 |
| derived_from | ContentBlock -> source ContentBlock | typed graph edge | D2 |
| consumes | Step/Task -> TaskBudget | Observation plus usage projection | D1 |
| evaluated_against | ToolCall -> AuthorizationSnapshot | typed relation | D4 |
| produced_effect | ToolCall -> ToolEffect | typed relation | D4 |

### 6.1 Context lineage

The model records what the model **could see**, not invisible attention or actual
reliance. Backward lineage answers origin; forward lineage answers possible
exposure. API responses must label forward results `possible_exposure`.

Compression creates a summary block derived from every block it compressed and
records preserved and removed block inventories. Tool result transformations
similarly preserve raw-to-visible edges.

### 6.2 Scope and effect conclusions

D4 conclusions distinguish:

```text
policy_denial
attempted_scope_violation
realized_scope_violation
unverified_effect
```

These are claims/beliefs backed by Tool intent, AuthorizationSnapshot, and Effect
Observations. They are not inferred solely from a Tool's final text.

### 6.3 Relation evidence

Every inferred relation stores established/dissolved Beliefs where applicable
and references supporting Observations through a relation-evidence junction.
Typed high-volume relations still obey this evidence requirement.

---

## 7. Observation Protocol

### 7.1 ObservationEnvelope

```text
ObservationEnvelope {
    obs_id
    schema_version
    kind
    occurred_at
    recorded_at
    task_id
    step_id?
    subject_type
    subject_id
    scope_id?
    fidelity_class
    producer {
        name
        version
        instance_id
    }
    source_event_id
    correlation_id?
    causation_obs_id?
    payload
    payload_ref?
}
```

`occurred_at` is evidence time; `recorded_at` measures ingestion delay.

### 7.2 Event kinds

V1 uses specific kinds rather than broad `llm_call` or `tool_io` buckets:

```text
task.created | task.started | task.heartbeat | task.completed |
task.failed | task.interrupted

step.started | step.closed

llm.requested | llm.responded | llm.failed

tool.issued | tool.started | tool.returned_raw | tool.result_visible |
tool.denied | tool.timed_out | tool.cancelled | tool.failed

content.produced | context.state_recorded | context.snapshotted |
context.compressed

budget.configured | budget.consumed

scope.snapshotted | authorization.evaluated |
authorization.allowed | authorization.denied | authorization.unknown |
effect.observed

evaluation.recorded | operator.action_requested |
operator.action_succeeded | operator.action_failed |
operator.alert_acknowledged | operator.alert_dismissed

external.user_submitted | external.user_interrupted |
external.scheduler_triggered | external.webhook_received |
external.config_changed | provider.timed_out | provider.rate_limited |
sandbox.permission_denied | observability.degraded
```

### 7.3 Ordering and causality

Database ingest order is stable replay order, not proof of causal order. Ansich
uses occurred time, explicit causation IDs, stable Entity relationships, and
subject lifecycle rules. Parallel ToolCalls are not forced into a false temporal
ordering.

### 7.4 Idempotency

Collector retries are deduplicated with:

```text
UNIQUE(producer_name, producer_instance_id, source_event_id)
```

Projection uses at-least-once jobs and idempotent upserts/edge creation.

### 7.5 Payload storage and redaction

Small payloads are inline JSON. Large prompts, Tool results, and binary/visual
content use a compressed payload reference with content type, byte size, and
SHA-256 metadata.

Known credential fields are structurally excluded; known secret values are
exact-value redacted. Broad regex scanning may add sensitivity flags but does not
silently mutate arbitrary user content in v1. Every redaction stores a manifest
containing field path and reason, never the original secret.

Raw payload reads are admin-only in v1 and are themselves audited. Thread/user
deletion cascades to observations, payloads, projections, and relations. Raw and
structural retention periods are separately configurable; expired payloads leave
explicit retention tombstones so absence is not confused with collection loss.

---

## 8. Physical Data Model

The conceptual model is generic; the physical model is hybrid.

### 8.1 Observation zone

```text
ansich_observations
ansich_payloads
```

These are the canonical append-only records.

### 8.2 Entity registry and typed details

```text
ansich_entities(entity_id, entity_type, primary_scope_id?, discovered_obs_id)

ansich_agent_releases(entity_id FK, namespace, agent_name, release_hash, ...)
ansich_tasks(entity_id FK, source_kind, source_id, trigger_obs_id, ...)
ansich_steps(entity_id FK, task_id, step_seq, actor_kind, ...)
ansich_tool_calls(entity_id FK, step_id, call_seq, provider_call_id?, ...)
ansich_tool_call_results(tool_call_id FK, result_role, source_obs_id, content_block_id FK, ...)
ansich_context_windows(entity_id FK, task_id, capacity, ...)
ansich_content_blobs(blob_key, content_hash, byte_size, content_type, payload_status, ...)
ansich_content_blocks(entity_id FK, kind, content_hash, blob_key FK, ...)
ansich_content_occurrences(task_id, source_identity, content_hash, kind, block_id FK, ...)
ansich_context_states(state_id FK, task_id, parent_state_id, state_hash, chain_depth, ...)
ansich_context_snapshots(entity_id FK, step_id, attempt_no, state_id FK, ...)
ansich_task_budgets(entity_id FK, task_id, dimension, aggregation_scope, ...)
ansich_scopes(entity_id FK, scope_kind, parent_scope_id?, ...)
ansich_alerts(entity_id FK, alert_key, episode, alert_type, ...)
```

The registry supplies common identity and generic Belief/Relation references.
Typed details provide foreign keys, constraints, and portable indexes. Examples:

```text
UNIQUE(task_id, step_seq)
UNIQUE(step_id, call_seq)
UNIQUE(snapshot_id, ordinal)
```

### 8.3 Belief zone

```text
ansich_belief_assertions
ansich_current_beliefs
ansich_transitions
ansich_belief_evidence
```

Assertions are append-only; current rows are materialized resolver output.

### 8.4 Relation zone

```text
ansich_context_snapshot_items
ansich_context_snapshot_missing_items
ansich_context_state_checkpoint_items
ansich_context_state_deltas
ansich_context_state_missing_blocks
ansich_content_block_derivations
ansich_relations
ansich_relation_evidence
ansich_authorization_snapshots
ansich_tool_effects
```

High-volume ordered/graph relations have typed tables. Low-frequency relations
such as `follows_up`, `spawned`, and `within_scope` may use the generic relation
table with indexed type/from/to columns.

### 8.5 Usage/read projections

```text
ansich_task_usage
ansich_task_summaries
ansich_active_task_read_model
ansich_alert_read_model
```

Usage rows always carry `as_of` and source Observation references even though
they are measurements rather than semantic states.

The embedded Phase 3 slice keeps `tool_calls_issued` and
`tool_calls_executed` on the Task summary read model. `executed` advances only
from `tool.started` or stronger execution evidence; denied and
unknown-terminal observations do not increment it. A later dedicated usage
projection may normalize these counters without changing their evidence rule.

### 8.6 Projection infrastructure

```text
ansich_projection_jobs
ansich_projection_errors
ansich_projector_versions
```

Jobs are mutable infrastructure and are not part of the append-only Observation
zone. Each job is unique by Observation, projector, and projector version.

---

## 9. Embedded Runtime Architecture

### 9.1 Module boundary

```text
DeerFlow runtime
    -> DeerFlow Ansich adapters/probes
    -> in-process Ansich Collector
    -> shared configured database, Ansich-owned tables
    -> async Projectors
    -> Gateway /api/ansich read/action API
```

Ansich core must not import FastAPI, LangGraph, or DeerFlow-specific classes.
Adapters depend on Ansich contracts, not vice versa. Gateway owns lifecycle and
API wiring.

### 9.2 Components

```text
AnsichService
  Collector
  BatchWriter
  ProjectorWorker
  HeartbeatProducer
  HealthReporter
```

Collector `record()` validates and enqueues without waiting for storage.
`flush_task()` places a barrier at Task terminal time and waits, within a bounded
timeout, for earlier queued observations to persist.

### 9.3 Queue and degradation

The queue is bounded. Full queue, serialization failure, storage failure, and
shutdown timeout increment loss counters and mark affected Tasks degraded.
Recovery emits `observability.degraded` with first/last lost producer sequence
when determinable. Absence inside a lost range must never be interpreted as
proof that nothing happened.

### 9.4 Atomic writer transaction

Each batch atomically writes:

```text
payloads + observations + projection_jobs
```

An Observation may not commit without its projection job; when it carries a
payload reference, that reference must also be valid in the same transaction.

### 9.5 Delivery and multi-worker behavior

Collection and projection use at-least-once delivery with deduplication and
idempotency. Each Gateway worker has a unique producer instance and writer.
Projectors claim database jobs with leases; PostgreSQL may use `FOR UPDATE SKIP
LOCKED`, while SQLite remains single-Gateway-worker as required by DeerFlow.

Poison jobs retry up to a configured limit, then become failed projection jobs,
mark the Task degraded, and allow unrelated jobs to proceed.

### 9.6 Shutdown

Shutdown order is: stop new records, stop heartbeat, drain Collector/Writer,
stop claiming projector jobs, finish bounded transactions, then close the
database. Ansich may not indefinitely delay Gateway shutdown.

---

## 10. DeerFlow Probe Placement

### 10.1 Task Control Probe

Installed around Gateway `run_agent()`/RunManager. It captures Task creation,
start, heartbeat, terminal outcome, AgentRelease, effective Budgets, and Scopes.
Task terminal truth comes from the worker/RunManager, not generic nested
LangChain `run.end` callbacks.

### 10.2 Decision probes

Two model probes are required:

- an outer logical Step probe outside retry logic allocates Step identity and
  closes the logical decision;
- an inner attempt probe after request-transform middleware and before the model
  adapter captures each physical request, ContextSnapshot, response, and error.

Caller tags classify lead/subagent decisions versus internal system operations.

### 10.3 Tool probes

- `tool.issued` is derived from the Agent AIMessage, so intent survives later
  denial/short-circuit;
- an inner raw execution probe captures actual start, raw result/exception, and
  duration;
- an outer visible-result probe captures the result after normalization,
  sanitization, output budgeting, and externalization;
- authorization components emit their own structured decision observations;
- Task-end reconciliation closes issued ToolCalls without terminal evidence as
  cancelled or unknown terminal, depending on known causality.

### 10.4 Context transformation probes

Block-producing or transforming code records provenance at the point of change:
user input, Agent output, raw/visible Tool result, summarization, memory, skill
activation/load, durable/dynamic context, vision injection, and system-message
coalescing.

Summarization must explicitly record source, preserved, and removed blocks; an
LLM summary response alone is insufficient.

### 10.5 Subagents

Child execution receives `ansich_task_id`, parent Task, spawning Step,
AgentRelease, Scope relations, and Collector handle. The same Step/attempt/Tool
probes run in the child chain. Child usage is recorded locally and rolled up to
parent inclusive usage by projection.

### 10.6 Coexistence with RunJournal

RunJournal continues serving current `run_events`, chat history, and convenience
usage fields. Ansich writes its own ObservationEnvelope and tables. Shared event
normalization may be extracted later, but v1 must not change `run_events`
semantics to fit Ansich.

---

## 11. Read Models and API

All v1 endpoints are admin-only and live under `/api/ansich`.

### 11.1 Shared Task endpoints

```text
GET /api/ansich/tasks
GET /api/ansich/tasks/{task_id}
GET /api/ansich/tasks/{task_id}/timeline
```

Filters include control/behavior belief, AgentRelease, time range, Alert, and
observability health. Every response includes projection status, lag, failed
jobs, and lost ranges.

### 11.2 Developer endpoints

```text
GET /api/ansich/steps/{step_id}
GET /api/ansich/steps/{step_id}/context
GET /api/ansich/content-blocks/{block_id}/payload
GET /api/ansich/content-blocks/{block_id}/lineage
GET /api/ansich/content-blocks/{block_id}/exposures
GET /api/ansich/observations/{obs_id}
GET /api/ansich/observations/{obs_id}/payload
GET /api/ansich/agent-releases
GET /api/ansich/agent-releases/{release_id}
GET /api/ansich/agent-releases/compare?left=...&right=...
```

Lineage endpoints enforce depth/node limits and return a `truncated` flag.
Forward lineage is labeled possible exposure. Raw payload reads are audited.

### 11.3 Operator endpoints

```text
GET /api/ansich/operations/active-tasks
GET /api/ansich/operations/alerts
GET /api/ansich/operations/alerts/{alert_id}
GET /api/ansich/health
POST /api/ansich/operations/alerts/{alert_id}/acknowledge
POST /api/ansich/operations/alerts/{alert_id}/dismiss
POST /api/ansich/tasks/{task_id}/actions/interrupt
POST /api/ansich/tasks/{task_id}/actions/rollback
```

Action endpoints delegate to DeerFlow RunManager and produce requested/succeeded/
failed audit Observations. Health combines process-local and database state so a
database failure does not make the health endpoint silently disappear.

### 11.4 UI

```text
/workspace/ansich/operations
/workspace/ansich/tasks/{task_id}
```

Task detail tabs: Overview, Timeline, Steps, Context & Lineage, Budgets, Scopes &
Effects, Raw Evidence, and Agent Release. Active pages poll every 5-10 seconds in
v1; no new cross-Task SSE channel is required.

---

## 12. Acceptance and Paper Drills

### 12.1 Paper-drill requirement

Before feature implementation is declared design-complete, narrate two real
records entirely using this vocabulary:

1. an actual infinite-loop/drift failure;
2. a semantically wrong result with an external expected-vs-actual oracle.

Any required vocabulary outside this document is a design gap.

### 12.2 Completed high-frequency Tool warning drill

A permitted local DeerFlow Run from 2026-05-22 was inspected as the drill
record. It:

- completed successfully in about 7m36s;
- used 217,359 tokens;
- contained 14 logical lead-Agent Steps and five summarization system
  operations;
- issued and received 31 `web_search` ToolCalls plus read/write/present calls;
- triggered a Tool-frequency warning at count 30 and then wrote/presented the
  report successfully.

Conclusions:

- `middleware:loop_detection` is evidence, not automatically a runaway Belief;
- Tool frequency with changing arguments produces an Alert/metric, while v1
  runaway fallback requires a mapped absolute breach or exact repetition;
- middleware LLM calls cannot be counted as Agent Steps;
- provider ToolCall IDs were reused and cannot be primary identity;
- existing data did not preserve compression source blocks or complete
  AgentRelease/Budget/Scope snapshots;
- nested chain-end callbacks are not Task-terminal truth.

This is a valid Operator warning drill, not the required runaway failure drill.

### 12.3 Implementation acceptance

1. A normal completed Task can reconstruct every logical Agent Step and physical
   attempt without counting internal system LLM calls as Steps.
2. Every effective model attempt reconstructs the final structured messages,
   visible Tool schemas, response format, and generation settings at the defined
   model-adapter boundary.
3. Raw Tool result, visible Tool result, and all recorded transformations have an
   unbroken ContentBlock lineage.
4. Any Step supports backward decision-basis inventory and forward possible-
   exposure queries with bounded graph traversal.
5. Parallel ToolCalls have stable Ansich IDs even when provider IDs repeat.
6. Artificial exact repetition and absolute-limit breaches produce evidence-
   linked Beliefs and Alerts within configured limits; generic frequency alone
   does not assert runaway.
7. AgentRelease changes in model, rendered prompt, loaded Tool schema, policy, or
   runtime build produce distinct releases and a structured comparison.
8. Every state API field returns value, as_of, asserted_at, source, and fidelity,
   including honest unknown/unassessed values.
9. Child Task local usage and parent inclusive usage are both queryable without
   double-counting raw consumption.
10. Tool intent, authorization decision, and observed effect are independently
    queryable; unknown effects remain unknown.
11. Collector/store/projector failures do not fail the DeerFlow Task and produce
    visible degraded health/lost ranges when possible.
12. Projection replay is deterministic and idempotent across duplicate and late
    Observations.
13. Agent configuration secrets and request-scoped credentials do not appear in
    stored Ansich payloads.

---

## 13. V1 Boundaries, Assumptions, and Known Gaps

1. The required real runaway/drift failure paper drill is still outstanding.
2. The semantic-error paper drill is deliberately deferred until a real Run and
   expected-vs-actual oracle are supplied.
3. Initial fallback thresholds lack calibrated history; use existing DeerFlow
   effective limits and mark any shadow thresholds pending P99 calibration.
4. Ordinary-user progress is not a v1 Observer Lens. It requires a separate
   goal/plan/milestone model rather than Step-count heuristics.
5. Durable pause/resume and a separate force-terminate API are not current
   DeerFlow capabilities. V1 exposes the existing interrupt/rollback actions.
6. Context lineage represents visibility, not actual model reliance. Attribution
   conclusions are an over-approximation until later judge/causal-analysis
   levels.
7. Exact provider model revision may be unavailable; record unknown rather than
   treating a configured alias as a verified revision.
8. Bash and undeclared MCP side effects may remain unknown. V1 does not claim
   comprehensive syscall/network tracing.
9. Fail-open collection cannot guarantee process-crash losslessness without a
   durable local spool/WAL. V1 lossless reconstruction is limited to normal
   operation with healthy storage and successful Task flush.
10. Raw and structural retention defaults remain deployment policy; the schema
    supports separate periods and explicit tombstones.
11. D3 quality comparison remains limited without comparable Task cohorts and
    evaluation observations.
12. Confidence calibration, assessor confusion matrices, and general Claims
    remain Level 6/7 work; v1 preserves their evidence and schema attachment
    points.

---

*v0.2 Draft · DeerFlow embedded Ansich · developer/operator first*
