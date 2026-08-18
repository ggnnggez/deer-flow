# Ansich Phase 10 — Evaluation Inputs & Semantic Beliefs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let external evaluations (developer annotations, benchmark/unit-test results, user feedback, LLM-judge verdicts) enter Ansich as `evaluation.recorded` Observations and produce evidence-backed per-dimension quality Beliefs, separating "run completed" from "semantically correct".

**Architecture:** A new framework-independent evaluation contract + core validator in `backend/packages/ansich/`, a deterministic `evaluation-projector@1` in the harness SQL layer that maps evaluations to `quality.<dimension>` Belief assertions and maintains two replayable query projections (`ansich_evaluation_index`, `ansich_release_quality_stats`), a resolver upgrade to `ansich-default@2.0.0` (new `soft_human` authority class), three input adapters (admin POST API, feedback-router best-effort bridge, benchmark idempotency-key builder), and read-only frontend surfaces (Task detail Evaluations view, Release compare Quality section).

**Tech Stack:** Python 3.12 / Pydantic v2 / SQLAlchemy async + Alembic (SQLite & PostgreSQL) / FastAPI; Next.js + TanStack Query + Vitest + Playwright.

**Spec:** `ansich/docs/plans/10-evaluation-and-semantic-beliefs.md` (binding authority). Related context: `ansich/docs/plans/README.md` (阶段合并规则), `ansich/docs/concepts.md` (concept sync obligation), `ansich/docs/ansich-design-document.md`.

## Global Constraints

Copied from the spec and the repo's 阶段合并规则; every task's requirements implicitly include these.

- **Fail-open:** collection/adapter failures must never change DeerFlow business results. The feedback API must still succeed when the Ansich write fails (loss lands in Ansich health); the reverse — Ansich success masking a feedback primary-write failure — is forbidden.
- **Append-only + replayable:** `evaluation.recorded` Observations are canonical; `ansich_evaluation_index` and `ansich_release_quality_stats` are deletable, rebuildable per `projector_version`. Belief assertions are never overwritten; conflicting pass/fail assertions are all retained.
- **`unknown`/`unassessed` are first-class:** every unevaluated dimension returns a complete Belief structure with `value="unassessed"`, `source={name:"none",version:"1"}`, and NO fabricated evidence. Task `completed` never implies `pass`.
- **`quality` ≠ `behavior`:** a correctness fail supports `quality.correctness=failed` but never promotes runaway/drifting (Phase 6 owns behavior); a runaway Task may still be correct — both Beliefs coexist.
- **No hidden LLM execution:** this phase only receives external LLM-judge results; it never launches judge model calls.
- **No user-facing progress view:** admin-only surfaces; no thumbs-up/down auto-interpreted as full-task correctness.
- **Score needs scale:** a score without `{min,max,higher_is_better}` is rejected by the validator; the projector refuses bare incomparable numbers.
- **Hard fidelity is earned:** `fidelity_class="hard"` is allowed only for `benchmark_assertion`/`unit_test` inputs carrying stable `suite`/`suite_version`/`case_id` and a verifiable oracle; human annotations are `soft` (or explicit human override) and never auto-promote to hard because the caller is an admin.
- **`earliest_erroneous_step`:** subject must be a Task and `actual` must reference a Step belonging to that Task; never guessed via content similarity.
- **Cohort comparability:** release quality deltas only when same suite/version + case set (or explicit cohort key), same dimension + score scale, both sides ≥ configured minimum samples, and no unexplained missing evaluation/lost range; otherwise `comparison_status="not_comparable"` + reason. v1 reports observed delta only — no statistical-significance claims.
- **Migration discipline:** new tables ship as one Alembic revision (`0023_ansich_evaluations`, revises `0022_ansich_assessor_deadline`), executable on empty/existing SQLite and PostgreSQL, reversible, using `safe_add_column`-style idempotent helpers where applicable. All head-revision pins in tests must be bumped in the same task.
- **Observation kind discipline:** `evaluation.recorded` v1 has a schema version, idempotent source-event-ID rules (benchmark key `(suite, suite_version, case_id, run_id, dimension)`), and at least one duplicate/out-of-order test.
- **Payload discipline:** `expected`/`actual`/`rationale` pass the existing secret filter and may externalize to `ansich_payloads`; raw bodies stay behind the logged `Cache-Control: no-store` admin payload route; list/detail APIs return metadata/preview only.
- **Dependency direction:** `backend/packages/ansich/` must not import DeerFlow/LangGraph/FastAPI/SQLAlchemy. Router does auth/validation/DTO only — no projection or rule logic in routes.
- **TDD mandatory:** every task writes its failing test first (backend `backend/tests/ansich/`; frontend unit + Playwright where UI changes). SQLite and PostgreSQL semantics both covered for schema work.
- **Format before finish:** `cd backend && uv run ruff format <changed files>` + `uv run ruff check` (use the project-pinned ruff via `uv run`, NEVER `uvx ruff` / `make format` — the unpinned latest ruff reformats unrelated Markdown code blocks).
- **Known flaky:** `tests/ansich/test_sql_budget.py::test_sql_budget_health_retains_terminal_overshoot_and_evidence` is a suite-level timing flaky (passes in isolation). If it is the only full-suite failure, rerun it alone and report; do not chase it.
- **Docs in the same change set:** `backend/AGENTS.md` (ansich section + migrations list), `ansich/docs/concepts.md` (new kind/tables/resolver v2), `ansich/docs/plans/README.md` (Phase 10 status), and the phase plan doc's implementation-status notes are updated by the dedicated docs task at the end.

## Fixed design rulings (pre-resolved ambiguities — binding for all tasks)

- **R1 (resolver v2):** `AuthorityClass` gains `"soft_human"` between `configured_rule` and `automated`. Priorities in `ansich-default@2.0.0`: `human_override=5 > deterministic=4 > configured_rule=3 > soft_human=2 > automated=1`. The v1 priority table is retained verbatim for replay; `resolve_current_belief` dispatches on the resolver version and rejects unknown versions.
- **R2 (human override marker):** the evaluation schema carries `human_override: bool = False`, valid only for `evaluation_kind="developer_annotation"` (validator rejects it elsewhere). It maps to `authority_class="human_override"`; developer annotations without it and `user_feedback` map to `soft_human`; `llm_judge` maps to `automated`; `benchmark_assertion`/`unit_test` with hard fidelity map to `deterministic` (with rule/soft fidelity → `configured_rule`).
- **R3 (belief identity):** current Beliefs stay keyed by `(subject_id, field_name)` with `field_name="quality.<dimension>"` (e.g. `quality.correctness`); suite/cohort identity lives in assertion `value` payloads and in `ansich_evaluation_index`/`ansich_release_quality_stats`, not in the belief key. Cross-suite disagreement surfaces as retained conflicting assertions + `conflicting_assertion_count`, and per-cohort splits appear in release stats.
- **R4 (compare surface):** release quality comparison is served server-side by extending the existing agent-release compare read with a `quality` block (per-dimension: `comparison_status`, `observed_delta`, `sample_count`s, `coverage`, `reason`, resolver version) driven by a `cohort` query parameter — comparability rules must not be re-implemented client-side.
- **R5 (adapters):** the "internal benchmark adapter" is the deterministic source-event-ID builder + validator path in the core package, exercised by `POST /api/ansich/evaluations` for `benchmark_assertion`/`unit_test` kinds; it is not a separate HTTP surface.
- **R6 (dimension set for unassessed synthesis):** the fixed dimension list rendered/synthesized as `unassessed` when absent is `correctness, completeness, relevance, safety, efficiency` (not `earliest_erroneous_step`/`custom`, which appear only when actually recorded).
- **R7 (service plumbing):** new evaluation reads/writes follow the failed-jobs optional-capability precedent — `AnsichService` duck-types the backend via `getattr` and returns safe empty values; SQL-only implementation; NO changes to the `AnsichBackend` Protocol (`backend.py`) or `InMemoryAnsichBackend` (`memory.py`); `_UnavailableBackend` (`packages/harness/deerflow/ansich/__init__.py:7-42`) gets matching safe stubs only if it would otherwise raise.
- **R8 (POST projection_status):** `POST /evaluations` records the observation, then computes `projection_status` from the observation's projection-job states (new SQL read): all jobs `completed` → `"applied"`; any `failed` → `"failed"`; otherwise `"pending"`; storage unavailable → `"failed"`. It never waits unbounded (one bounded `flush_task` settle attempt max). Idempotent replay: an existing observation with the same `source_event_id` is returned with its current status instead of double-recording.
- **R9 (cohort key):** the evaluation schema carries optional `cohort_key: str | None`; for `benchmark_assertion`/`unit_test` it defaults to `f"{suite}@{suite_version}"` when absent. `ansich_release_quality_stats` aggregates only evaluations whose subject is a **Task** (resolved to that Task's bound release via `executed_by`); step/tool_call/content_block/agent_release-subject evaluations appear in `ansich_evaluation_index` but do not feed release stats in v1.
- **R11 (task detail entry point):** the Evaluations surface is a FIFTH question-oriented entry point (`?view=evaluations`, question: "结果对吗?") added to the UI-1 four-view structure — the phase spec's explicit "Evaluations 标签" requirement postdates and overrides the UI-1 "7→4" consolidation. Extend `TaskView`/`TASK_VIEWS` in the task detail page; do not fold evaluations into Evidence.
- **R10 (invalid references):** projection-time semantic violations (e.g. `earliest_erroneous_step` whose referenced Step exists but belongs to a different Task) raise a plain `ValueError` in the projector — the job retries and lands in the durable failed-jobs diagnostics surface (visible, non-poisoning). A referenced Step/Task/subject Entity that does not exist YET raises `_ProjectionDependencyPending` (graceful wait with the Phase-9 deadline semantics).

---

## Tasks

### Task 1: Core evaluation contract + observation kind registration

**Files:**
- Create: `backend/packages/ansich/ansich/evaluation.py`
- Modify: `backend/packages/ansich/ansich/contracts.py` (ObservationKind union ~line 68-84; `_validate_subject` chain ~line 213-270)
- Modify: `backend/packages/ansich/ansich/__init__.py` (export the new public names alongside existing exports)
- Test: `backend/tests/ansich/test_evaluation_contracts.py` (new)

**Interfaces:**
- Consumes: `ansich.contracts.NamedVersion`, `ObservationEnvelope`, `new_id` (`ansich.ids`), `canonical_json_bytes` (`ansich.assessment.base`).
- Produces (later tasks rely on these exact names):
  - `EvaluationKind = Literal["user_feedback", "developer_annotation", "benchmark_assertion", "unit_test", "llm_judge"]`
  - `EvaluationDimension = Literal["correctness", "completeness", "relevance", "safety", "efficiency", "earliest_erroneous_step", "custom"]`
  - `EvaluationVerdict = Literal["pass", "fail", "partial", "unknown"]`
  - `EvaluationSubjectType = Literal["task", "step", "tool_call", "content_block", "agent_release"]`
  - `class ScoreScale(BaseModel)`: `min: float`, `max: float`, `higher_is_better: bool` (frozen/strict; validator `max > min`)
  - `class EvaluationRecord(BaseModel)` (frozen/strict, `extra="forbid"`): `subject_type: EvaluationSubjectType`, `subject_id: str`, `task_id: str`, `evaluation_kind: EvaluationKind`, `dimension: EvaluationDimension`, `verdict: EvaluationVerdict | None = None`, `score: float | None = None`, `scale: ScoreScale | None = None`, `expected: str | None = None`, `actual: str | None = None`, `rationale: str | None = None`, `assessor: NamedVersion`, `fidelity_class: Literal["hard","rule","soft"]`, `human_override: bool = False`, `cohort_key: str | None = None`, `suite: str | None = None`, `suite_version: str | None = None`, `case_id: str | None = None`, `run_id: str | None = None`, `occurred_at: datetime`
  - `def build_evaluation_observation(record: EvaluationRecord, *, producer: Producer, source_event_id: str | None = None, obs_id: str | None = None) -> ObservationEnvelope`
  - `def benchmark_source_event_id(*, suite: str, suite_version: str, case_id: str, run_id: str, dimension: str) -> str` returning `f"evaluation:benchmark:{suite}:{suite_version}:{case_id}:{run_id}:{dimension}"`
  - `EVALUATION_OBSERVATION_KIND = "evaluation.recorded"`

**Model validators on `EvaluationRecord` (each is a test case):**
1. at least one of `verdict` / `score` present;
2. `score` present ⇒ `scale` present ("projector 拒绝无法比较的裸数字" starts at the validator);
3. `fidelity_class == "hard"` ⇒ `evaluation_kind in {"benchmark_assertion","unit_test"}` AND `suite`/`suite_version`/`case_id` all present;
4. `evaluation_kind in {"benchmark_assertion","unit_test"}` ⇒ `suite`/`suite_version`/`case_id` present (idempotency needs them), and `cohort_key` defaults to `f"{suite}@{suite_version}"` when None (R9);
5. `human_override is True` ⇒ `evaluation_kind == "developer_annotation"` (R2);
6. `dimension == "earliest_erroneous_step"` ⇒ `subject_type == "task"` AND `actual` is a non-empty string (the Step id; ownership is checked at projection time per R10);
7. timestamps timezone-aware (mirror `Assessment._timestamp_is_aware`).

**`build_evaluation_observation`:** payload = `{"evaluation": record.model_dump(mode="json")}`; `kind="evaluation.recorded"`; `subject_type=record.subject_type`; `subject_id=record.subject_id`; `task_id=record.task_id`; `source_event_id` = explicit arg, else `benchmark_source_event_id(...)` for benchmark/unit_test kinds (requires `run_id`; raise `ValueError` when absent), else raise `ValueError("source_event_id is required for non-benchmark evaluations")`. The envelope's existing secret filter applies automatically because expected/actual/rationale ride inside `payload`.

**contracts.py registration:**
- Add `EvaluationObservationKind = Literal["evaluation.recorded"]` next to the other per-domain aliases and include it in the `ObservationKind` union.
- Insert into `_validate_subject` (before the unconditional payload-check tail, after the `effect.` branch):

```python
elif self.kind == "evaluation.recorded":
    if self.subject_type not in {"task", "step", "tool_call", "content_block", "agent_release"}:
        raise ValueError("evaluation.recorded requires a task/step/tool_call/content_block/agent_release subject")
    from ansich.evaluation import EvaluationRecord  # local import, mirrors the scope.snapshotted pattern

    evaluation = EvaluationRecord.model_validate((self.payload or {}).get("evaluation"), strict=False)
    if evaluation.subject_id != self.subject_id or evaluation.subject_type != self.subject_type:
        raise ValueError("evaluation payload subject must match the Observation subject")
    if evaluation.task_id != self.task_id:
        raise ValueError("evaluation payload task must match the Observation task")
```

(The payload cross-check only runs when `self.payload is not None`; externalized payloads skip it, mirroring how `scope.snapshotted` behaves — copy that guard style exactly from contracts.py:241-248.)

- [ ] **Step 1:** Write failing tests in `backend/tests/ansich/test_evaluation_contracts.py` covering: happy-path benchmark record + `build_evaluation_observation` envelope roundtrip (kind/subject/source_event_id); each validator 1-7 rejection; `benchmark_source_event_id` determinism (same tuple → same id, differing dimension → different id); envelope-level subject mismatch rejection; secret field in `expected` payload rejected by the envelope (reuse an `"authorization"`-named key to trip `_find_secret_field`); duplicate `source_event_id` intake absorbed idempotently (record the same benchmark observation twice through a real `create_sql_ansich_service` SQLite service, assert one `ansich_observations` row — follow the service-construction pattern in `tests/ansich/test_sql_safety.py::test_scope_safety_waits_for_subject_entity_then_self_heals`).
- [ ] **Step 2:** Run `uv run pytest tests/ansich/test_evaluation_contracts.py -q` from `backend/`; confirm failures are ImportError/ValidationError-shaped (feature missing), not typos.
- [ ] **Step 3:** Implement `evaluation.py`, the contracts.py union entry, `_validate_subject` branch, and `__init__.py` exports.
- [ ] **Step 4:** Re-run the test file → all pass. Also run `uv run pytest tests/ansich/test_contracts.py -q` (existing kind-validation suite must stay green).
- [ ] **Step 5:** `uv run ruff format` + `uv run ruff check` on changed files; commit `feat(ansich): add evaluation.recorded contract and core validator`.

### Task 2: Resolver v2 with soft_human authority class

**Files:**
- Modify: `backend/packages/ansich/ansich/assessment/base.py` (AuthorityClass Literal, lines 15-20)
- Modify: `backend/packages/ansich/ansich/belief/resolver.py`
- Modify: `backend/packages/harness/deerflow/ansich/persistence/sql.py` (`_resolve_current_assessment`, ~line 2088 — pass the explicit resolver)
- Test: `backend/tests/ansich/test_belief_resolver.py` (extend if it exists, else create)

**Interfaces:**
- Produces:
  - `AuthorityClass` gains `"soft_human"` (full set: human_override, deterministic, configured_rule, soft_human, automated)
  - `DEFAULT_RESOLVER = NamedVersion(name="ansich-default", version="2.0.0")`
  - `RESOLVER_V1 = NamedVersion(name="ansich-default", version="1.0.0")` retained
  - `def resolve_current_belief(assertions: Sequence[BeliefAssertion], *, resolver: NamedVersion = DEFAULT_RESOLVER) -> ResolvedBelief` — dispatches priority table by `resolver.version` (`"1.0.0"` → v1 table where `soft_human` is ABSENT and encountering it raises `ValueError("authority class soft_human is not resolvable under ansich-default@1.0.0")`; `"2.0.0"` → v2 table `{human_override:5, deterministic:4, configured_rule:3, soft_human:2, automated:1}`; any other version → `ValueError`)
  - `ResolvedBelief` gains `conflicting_assertion_count: int` (= `len(assertions) - 1`, counting retained non-selected assertions)
- Consumes: existing `BeliefAssertion`, `ResolvedBelief` shape (extend, don't rename).

**sql.py change:** `_resolve_current_assessment` (sql.py:2041-2106) calls `resolve_current_belief(assertions)` → unchanged call site still works (keyword default is v2), but verify the stored row now records `resolver_version == "2.0.0"` for NEW resolutions. Existing rows with `1.0.0` stay untouched (replay preservation: `rebuild_projections` re-resolves under v2 — that is the documented upgrade semantics; v1 results remain reproducible by calling `resolve_current_belief(..., resolver=RESOLVER_V1)`).

- [ ] **Step 1:** Failing tests: v2 priority ordering across all five classes (build five assertions differing only in authority_class + as_of, assert selection order); tie-break within class by `as_of` then `asserted_at` then `assertion_id` (unchanged from v1); `conflicting_assertion_count` = N-1; v1 dispatch reproduces old behavior for the four legacy classes; v1 + soft_human assertion → ValueError; unknown resolver version → ValueError; SQL integration: persist two assertions for one subject/field (one `automated`, one `soft_human`), assert `AnsichCurrentBeliefRow.resolver_version == "2.0.0"` and the `soft_human` one is selected.
- [ ] **Step 2:** Run → watch fail.
- [ ] **Step 3:** Implement (Literal extension, two priority tables, dispatch, count field). Keep the v1 table verbatim as `_AUTHORITY_PRIORITY_V1`.
- [ ] **Step 4:** Run the new file + `uv run pytest tests/ansich -q -k "resolver or belief"` → green. Then run the FULL `tests/ansich` suite once here — this task touches every assertion-persisting path, so catching fallout early is cheaper than in Task 4.
- [ ] **Step 5:** Format + commit `feat(ansich): upgrade belief resolver to ansich-default@2 with soft_human class`.

### Task 3: Migration 0023 + evaluation row models

**Files:**
- Create: `backend/packages/harness/deerflow/persistence/migrations/versions/0023_ansich_evaluations.py`
- Modify: `backend/packages/harness/deerflow/ansich/persistence/models.py` (add two row classes)
- Modify (head pins, same mechanical bump as commit 55e1a7d7 did for 0022): `backend/tests/test_persistence_bootstrap.py` (HEAD constant + rename `test_head_revision_is_ansich_assessor_deadline_revision` → `test_head_revision_is_ansich_evaluations_revision`), `backend/tests/test_persistence_bootstrap_regression.py` (2 asserts), `backend/tests/test_persistence_bootstrap_concurrency.py` (HEAD), `backend/tests/test_migration_0004_run_ownership_dedupe.py` (1 assert), `backend/tests/ansich/test_sql_task_lifecycle.py` (2 revision asserts in the two `*_migration_upgrades_sqlite` tests), `backend/tests/ansich/test_sql_safety.py`, `backend/tests/ansich/test_sql_alerts.py`, `backend/tests/ansich/test_sql_agent_releases.py`, `backend/tests/ansich/test_sql_active_tasks.py`, `backend/tests/ansich/test_sql_task_tree.py` (1 revision assert each)
- Test: extend `backend/tests/ansich/test_evaluation_contracts.py` with a migration test (or create `test_sql_evaluations.py` and put it there — Task 4 will extend the same file)

**Row classes (models.py), following `AnsichContextSnapshotBlockMembershipRow`'s style:**

```python
class AnsichEvaluationIndexRow(Base):
    __tablename__ = "ansich_evaluation_index"

    evaluation_obs_id: Mapped[str] = mapped_column(String(36), ForeignKey("ansich_observations.obs_id", ondelete="CASCADE"), primary_key=True)
    subject_type: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(36), nullable=False)
    task_id: Mapped[str] = mapped_column(String(36), nullable=False)
    evaluation_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    dimension: Mapped[str] = mapped_column(String(32), nullable=False)
    verdict: Mapped[str | None] = mapped_column(String(16))
    score: Mapped[float | None] = mapped_column(Float)
    scale_min: Mapped[float | None] = mapped_column(Float)
    scale_max: Mapped[float | None] = mapped_column(Float)
    scale_higher_is_better: Mapped[bool | None] = mapped_column(Boolean)
    assessor_name: Mapped[str] = mapped_column(String(64), nullable=False)
    assessor_version: Mapped[str | None] = mapped_column(String(32))
    authority_class: Mapped[str] = mapped_column(String(32), nullable=False)
    fidelity_class: Mapped[str] = mapped_column(String(16), nullable=False)
    cohort_key: Mapped[str | None] = mapped_column(String(128))
    suite_id: Mapped[str | None] = mapped_column(String(128))
    suite_version: Mapped[str | None] = mapped_column(String(64))
    case_id: Mapped[str | None] = mapped_column(String(128))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    projector_version: Mapped[str] = mapped_column(String(32), nullable=False)

    __table_args__ = (
        Index("ix_ansich_evaluation_subject_dimension", "subject_type", "subject_id", "dimension", "occurred_at"),
        Index("ix_ansich_evaluation_suite_case", "suite_id", "suite_version", "case_id"),
        Index("ix_ansich_evaluation_task", "task_id", "occurred_at"),
    )


class AnsichReleaseQualityStatsRow(Base):
    __tablename__ = "ansich_release_quality_stats"

    release_id: Mapped[str] = mapped_column(String(36), ForeignKey("ansich_entities.entity_id", ondelete="CASCADE"), primary_key=True)
    cohort_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    dimension: Mapped[str] = mapped_column(String(32), primary_key=True)
    assessed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pass_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fail_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    partial_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    score_sum: Mapped[float | None] = mapped_column(Float)
    score_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    scale_min: Mapped[float | None] = mapped_column(Float)
    scale_max: Mapped[float | None] = mapped_column(Float)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    projector_version: Mapped[str] = mapped_column(String(32), nullable=False)

    __table_args__ = (Index("ix_ansich_release_quality_cohort", "release_id", "cohort_key", "dimension"),)
```

(`scale_min`/`scale_max` on stats rows record the single scale the cohort cell aggregates — mixed scales must never be summed; the projector keeps them per R4/§7. Evaluations use a NO-cohort sentinel `cohort_key=""` for the "样本列表" case where no cohort key exists.)

**Migration 0023:** `revision = "0023_ansich_evaluations"`, `down_revision = "0022_ansich_assessor_deadline"`. `upgrade()` = `op.create_table` for both tables + the three/one `op.create_index` calls matching the model `__table_args__` exactly (guard with an idempotent `_has_table` check mirroring how `0016_ansich_operations.py` creates its read-model table — copy that file's structure). `downgrade()` = drop indexes + tables in reverse order.

**rebuild_projections registration:** add both row classes to the FK-safe delete tuple in `sql.py` `rebuild_projections` (sql.py:939-993) — evaluation_index references observations (CASCADE) and stats reference entities: place them early in the delete list alongside the other leaf read models (before `AnsichEntityRow`-dependent parents get touched; exact position: next to `AnsichActiveTaskReadModelRow` at sql.py:949).

- [ ] **Step 1:** Failing tests: (a) `test_evaluation_models_compile_with_postgresql_constraints_and_indexes` — CreateTable DDL for both rows compiles on `postgresql.dialect()` and the index names above are present (mirror `test_phase9_safety_models_compile_with_postgresql_constraints_and_indexes` in test_sql_safety.py:44); (b) `test_evaluation_migration_upgrades_sqlite` — alembic upgrade head on a fresh SQLite file creates both tables, revision == `"0023_ansich_evaluations"`, `len(revision) <= 32` (mirror `test_assessor_dependency_deadline_migration_upgrades_sqlite` in test_sql_task_lifecycle.py). Watch (b) fail on the missing migration; head-pin tests across the 10 files will fail after the migration lands — bump them in Step 3.
- [ ] **Step 2:** Run the two new tests → correct RED.
- [ ] **Step 3:** Implement models + migration; bump ALL head pins listed in Files (grep `0022_ansich_assessor_deadline` under `backend/tests/` — every hit outside migration internals gets bumped to `0023_ansich_evaluations`); add the rebuild delete entries.
- [ ] **Step 4:** Run: the new tests, `tests/test_persistence_bootstrap.py`, `tests/test_persistence_bootstrap_regression.py`, `tests/test_persistence_bootstrap_concurrency.py`, `tests/test_migration_0004_run_ownership_dedupe.py`, and the five ansich migration-assert files → all green.
- [ ] **Step 5:** Format + commit `feat(ansich): add evaluation index and release quality stats storage`.

### Task 4: evaluation-projector@1

**Files:**
- Modify: `backend/packages/harness/deerflow/ansich/persistence/sql.py`:
  - `_PROJECTORS` (sql.py:268-276): append `("evaluation-projector", "1")` LAST (evaluations depend on subjects other projectors create — lowest priority is correct)
  - `_PROJECTOR_KINDS` (sql.py:277-285): `"evaluation-projector": frozenset({"evaluation.recorded"})`
  - dispatch chain in `project_pending` (sql.py:824-843): `elif projector_name == "evaluation-projector": await self._project_evaluation(session, observation)`
  - new `async def _project_evaluation(self, session: AsyncSession, observation: ObservationEnvelope) -> None`
- Test: `backend/tests/ansich/test_sql_evaluations.py` (created in Task 3, extended here)

**Interfaces:**
- Consumes: `EvaluationRecord` (Task 1), `_persist_assessment` (sql.py:1957 — already guards subject Entity existence via `_ProjectionDependencyPending`), `Assessment` contract, resolver v2 via `_resolve_current_assessment` (invoked inside `_persist_assessment`).
- Produces: `ansich_evaluation_index` rows, `quality.<dimension>` Belief assertions, `ansich_release_quality_stats` cell recomputes. Assessor identity on assertions: `assessor=record.assessor`, `config_hash=canonical_config_hash({"projector": "evaluation-projector", "version": "1"})`.

**`_project_evaluation` behavior (each bullet is at least one test):**
1. Hydrate `EvaluationRecord` from `payload["evaluation"]` (load via payload ref when externalized — copy the payload-ref hydration used by `_claim_projection_job`'s payload loading at sql.py:1215-1222).
2. Subject Entity must exist (`session.get(AnsichEntityRow, record.subject_id)`), else raise `_ProjectionDependencyPending` — late subjects self-heal.
3. Idempotent index upsert keyed by `evaluation_obs_id` (re-projection of the same observation must not duplicate; conflicting re-projection with different content raises, mirroring `_project_authorization_snapshot`'s conflict stance).
4. Authority mapping (R2): benchmark/unit_test+hard → `deterministic`; benchmark/unit_test+rule/soft → `configured_rule`; developer_annotation+`human_override` → `human_override`; developer_annotation/user_feedback → `soft_human`; llm_judge → `automated`.
5. Assertion for dimensions in {correctness, completeness, relevance, safety, efficiency}: `field_name=f"quality.{record.dimension}"`, `value={"verdict": ..., "score": ..., "scale": {...}, "evaluation_kind": ..., "cohort_key": ..., "suite": ...}` (JSON-safe), `evidence=(EvidenceRef(obs_id=observation.obs_id),)`, `as_of=record.occurred_at`, `asserted_at=datetime.now(UTC)`, persisted through `await self._persist_assessment(session, assessment)`.
6. `dimension == "custom"`: index row only, NO assertion (no semantic claim without a named dimension).
7. `dimension == "earliest_erroneous_step"`: subject is the Task; `record.actual` is the Step id. Load `AnsichStepRow` for it — absent → `_ProjectionDependencyPending`; present but `task_id != record.task_id` → `raise ValueError("earliest erroneous step must belong to the evaluated Task")` (R10). Assertion `field_name="quality.earliest_erroneous_step"`, `value={"step_id": ..., "step_seq": <from the row>, "verdict": ...}`.
8. Release stats (R9): only when `record.subject_type == "task"` and the dimension is in the five quality dimensions. Resolve the Task's release via the `executed_by` relation row (find how `_project_agent_release` records the binding — an `AnsichRelationRow` with `relation_type="executed_by"`; query it by `source_id == record.task_id`); Task without a release binding → skip stats (index + assertion still land). Recompute the affected `(release_id, cohort_key or "", dimension)` cell from scratch: for each Task bound to that release having index rows in the cohort+dimension, take the CURRENT belief's selected assertion (join `ansich_current_beliefs` on `(task_id, f"quality.{dimension}")` → assertion → verdict/score) and aggregate `assessed_count/pass_count/fail_count/partial_count/score_sum/score_count`; refuse to aggregate mixed scales — on scale mismatch within a cell, store counts with `score_sum=None, score_count=0` and the FIRST scale (deterministic: lowest `evaluation_obs_id`); `as_of = max(occurred_at)`; delete the cell row when it aggregates zero evaluations.
9. Behavior/quality separation: a correctness fail writes ONLY `quality.correctness` — assert no `behavior` field assertions are produced by this projector.
10. Replay: after `rebuild_projections()`, index rows, stats cells, and current beliefs are reproduced (now under resolver v2).

- [ ] **Step 1:** Failing tests covering bullets 1-10 plus: duplicate observation re-projection idempotent; out-of-order (evaluation arrives before its subject Step's projection → pending → self-heals after the Step lands — reuse the Task-4 service pattern from `test_scope_safety_waits_for_subject_entity_then_self_heals`); two conflicting pass/fail assertions both retained with `conflicting_assertion_count == 1` on the resolved read (via `get_current_belief` + a direct `ansich_belief_assertions` count).
- [ ] **Step 2:** Run → RED.
- [ ] **Step 3:** Implement `_project_evaluation` + registration + dispatch + rebuild list (if not done in Task 3).
- [ ] **Step 4:** Run `tests/ansich/test_sql_evaluations.py` then the FULL `tests/ansich` suite → green (module count grows; the known budget flaky rule applies).
- [ ] **Step 5:** Format + commit `feat(ansich): project evaluations into quality beliefs, index, and release stats`.

### Task 5: Service surface, cohort comparability core, config

**Files:**
- Create: `backend/packages/ansich/ansich/quality.py` (pure comparability logic + view models)
- Modify: `backend/packages/ansich/ansich/evaluation.py` (add view models)
- Modify: `backend/packages/ansich/ansich/service.py` (new methods)
- Modify: `backend/packages/harness/deerflow/ansich/persistence/sql.py` (backend reads/writes)
- Modify: `backend/packages/harness/deerflow/ansich/__init__.py` (`_UnavailableBackend` stubs if needed per R7; thread new config)
- Modify: `backend/packages/harness/deerflow/config/ansich_config.py` (+ `config.example.yaml` ansich section; bump `config_version` per repo config rules ONLY if that is what sibling ansich fields did — check `git log -p config.example.yaml` for the 0016-era pattern and mirror it)
- Test: `backend/tests/ansich/test_evaluation_service.py` (new), `backend/tests/ansich/test_ansich_config.py` (extend)

**Interfaces (produced — Tasks 6/8 depend on these exact names):**
- Views (frozen/strict, in `evaluation.py`): `EvaluationView` (index-row shape + `evaluation_obs_id`, no bodies), `EvaluationRecordReceipt` (`observation_id: str`, `projection_status: Literal["pending","applied","failed"]`, `idempotent_replay: bool`), `QualityBeliefView` (`dimension: str`, `value: dict`, `source: NamedVersion`, `authority_class: str`, `fidelity_class: str`, `as_of: datetime | None`, `resolver: NamedVersion | None`, `conflicting_assertion_count: int`, `evidence_obs_ids: tuple[str, ...]`, `unassessed: bool`)
- Views (in `quality.py`): `ReleaseQualityDimensionView` (`dimension: str`, `cohort_key: str`, `assessed_count: int`, `pass_count: int`, `fail_count: int`, `partial_count: int`, `mean_score: float | None`, `scale: dict | None`, `as_of: datetime`), `ReleaseQualityView` (`release_id: str`, `cohorts: tuple[ReleaseQualityDimensionView, ...]`), `QualityComparisonView` (`dimension`, `cohort_key`, `comparison_status: Literal["comparable","not_comparable"]`, `reason: str | None`, `observed_delta: float | None`, `left_sample_count: int`, `right_sample_count: int`, `coverage: dict`, `resolver: NamedVersion`)
- Pure function: `def compare_release_quality(left: Sequence[ReleaseQualityDimensionView], right: Sequence[ReleaseQualityDimensionView], *, min_samples: int, unexplained_loss: bool) -> tuple[QualityComparisonView, ...]` implementing spec §7 verbatim: comparable only when same cohort_key (non-empty) + same dimension + same scale + both counts ≥ min_samples + not unexplained_loss; every failure returns `not_comparable` with a specific machine-readable `reason` (`"no_shared_cohort" | "scale_mismatch" | "insufficient_samples" | "observability_loss"`); delta = right mean − left mean for score dimensions, pass-rate delta for verdict-only cells; v1 reports observed delta only.
- Service methods (R7 optional-capability duck-typing):
  - `async def record_evaluation(self, record: EvaluationRecord, *, source_event_id: str | None, producer: Producer) -> EvaluationRecordReceipt` — checks existing observation by source_event_id (new SQL read `find_evaluation_observation(source_event_id)`) → replay; else `build_evaluation_observation` + `self.record(...)`; bounded `flush_task(record.task_id)`; compute `projection_status` per R8 via new SQL read `get_observation_projection_status(obs_id) -> Literal["pending","applied","failed"] | None`.
  - `async def get_evaluation_subject(self, subject_id: str) -> str | None` (returns entity_type; SQL: `session.get(AnsichEntityRow, subject_id)`)
  - `async def list_evaluations(self, *, subject_type: str | None = None, subject_id: str | None = None, task_id: str | None = None, limit: int = 100) -> list[EvaluationView]`
  - `async def get_quality_beliefs(self, subject_id: str) -> list[QualityBeliefView]` — resolved beliefs for the five R6 dimensions with unassessed synthesis (`value={"status":"unassessed"}`, `source=NamedVersion(name="none", version="1")`, `unassessed=True`, empty evidence) plus `earliest_erroneous_step` only when present; conflict counts from an assertion count query.
  - `async def get_release_quality(self, release_id: str, *, cohort_key: str | None = None) -> ReleaseQualityView | None`
- Config: `AnsichConfig` gains `evaluation_min_cohort_samples: int = 5` and `evaluation_max_payload_bytes: int = 262_144`; threaded through `create_sql_ansich_service`/`create_embedded_ansich_service` mirrors of existing fields; `config.example.yaml` ansich block gains the two keys with one-line comments.

- [ ] **Step 1:** Failing tests: `compare_release_quality` matrix (same suite comparable; version differs → no_shared_cohort; scale differs → scale_mismatch; insufficient samples both directions; loss → observability_loss; empty-cohort sentinel `""` never comparable); `record_evaluation` receipt states (applied after settle; pending when projector stalled — use a missing subject to hold the job pending; failed when storage unavailable via a stopped service; idempotent replay returns same obs id + flag); `get_quality_beliefs` unassessed synthesis (completed Task with zero evaluations → five unassessed dimensions, no fabricated evidence) and post-evaluation resolution (soft_human beats automated); `list_evaluations` filters; config defaults asserted in `test_ansich_config.py`.
- [ ] **Step 2:** RED run.
- [ ] **Step 3:** Implement core views + pure comparability + service methods + SQL reads + config threading.
- [ ] **Step 4:** Green run of the two test files, then full `tests/ansich`.
- [ ] **Step 5:** Format + commit `feat(ansich): add evaluation service surface and cohort comparability`.

### Task 6: Gateway API endpoints

**Files:**
- Modify: `backend/app/gateway/routers/ansich.py`
- Test: `backend/tests/ansich/test_ansich_evaluations_router.py` (new; copy harness/fixture style from `backend/tests/ansich/test_ansich_operations_router.py`)

**Interfaces (produced):**
```text
POST /api/ansich/evaluations                                (Idempotency-Key header required)
GET  /api/ansich/tasks/{task_id}/evaluations                (+ quality beliefs block)
GET  /api/ansich/steps/{step_id}/evaluations
GET  /api/ansich/agent-releases/{release_id}/quality?cohort=
GET  /api/ansich/agent-releases/compare                     (existing route gains a `quality` block per R4)
```
- Every route: first line `await require_admin_user(request, detail=_ADMIN_REQUIRED)`, then `_service_or_503` + `_ensure_queryable`, per-query try/except → 503 with `projection_status`, exactly like ansich.py:196-203. Responses are raw dicts with `model_dump(mode="json")` + embedded `"projection_status": _projection_status(service)`.
- POST body schema (pydantic request model in the router module): the EvaluationRecord fields minus task_id (derived: subject task → itself; other subjects → require explicit `task_id` field). Flow: validate → 422 (pydantic/ValueError with message); measure canonical payload size → 413 when > `evaluation_max_payload_bytes`; `get_evaluation_subject` → 404 `"Ansich evaluation subject not found"`; entity_type vs subject_type mismatch → 422; `Idempotency-Key` header via `Header(alias="Idempotency-Key")` (blank/>128 chars → 422, mirroring ansich.py:588-592); `source_event_id = f"evaluation:api:{idempotency_key}"` for non-benchmark kinds, benchmark tuple id otherwise (per Task 1); producer `Producer(name="ansich-evaluation-api", version="1", instance_id="gateway")`. Response: `{"observation_id", "projection_status", "idempotent_replay"}` — 200.
- Task evaluations GET: `{"task_id", "quality_beliefs": [...], "evaluations": [...], "projection_status"}` — beliefs from `get_quality_beliefs`, list from `list_evaluations(task_id=...)`; 404 when the Task summary doesn't exist (reuse the existing task-detail 404 lookup pattern at ansich.py:1007-1008).
- Step evaluations GET: `{"step_id", "evaluations": [...], "projection_status"}`; 404 on unknown step (subject entity lookup).
- Release quality GET: 404 unknown release; `{"release_id", "cohorts": [...], "projection_status"}` filtered by `?cohort=`.
- Compare quality block: the existing compare route gains `quality: {comparisons: [...], cohort: <requested>}` computed via `compare_release_quality` with `min_samples` from config and `unexplained_loss` from `service.get_health().loss_detected`.
- Alert dismiss `semantic_override` (spec §5): the existing alert dismiss route's request body gains an OPTIONAL `semantic_override: {dimension: <one of the five R6 dimensions>, verdict: "pass"|"fail"|"partial", rationale?: str}` field. When present, after the dismiss workflow write succeeds, record a `developer_annotation` evaluation with `human_override=True`, `fidelity_class="soft"`, subject = the alert's owning Task, `assessor=NamedVersion(name="operator-dismissal", version="1.0.0")`, `source_event_id=f"evaluation:dismiss:{alert_id}:{workflow_version}"` — producing the human quality assertion. A plain ack/dismiss (no `semantic_override`) must NOT change quality beliefs (regression test required for both branches).

- [ ] **Step 1:** Failing router tests: admin 403 for non-admin; 503 when service missing/storage unavailable; POST happy path (record lands, 200 receipt); POST idempotent replay; POST 404 unknown subject; POST 413 oversized rationale; POST 422 (missing Idempotency-Key → FastAPI 422; score without scale; human_override on llm_judge); GET task evaluations returns five unassessed beliefs pre-evaluation and resolved beliefs + conflict count post; GET step evaluations 404/200; GET release quality 404/200 + cohort filter; compare quality not_comparable reason surfaces.
- [ ] **Step 2:** RED run.
- [ ] **Step 3:** Implement routes.
- [ ] **Step 4:** Green run + full `tests/ansich`.
- [ ] **Step 5:** Format + commit `feat(ansich): expose evaluation record/read and release quality over HTTP`.

### Task 7: Feedback → evaluation best-effort adapter

**Files:**
- Create: `backend/app/gateway/feedback_evaluation.py` (adapter module — keeps the router thin)
- Modify: `backend/app/gateway/routers/feedback.py` (hook points at feedback.py:83-89 `upsert_feedback` and feedback.py:135-142 `create_feedback`)
- Test: `backend/tests/test_feedback_evaluation_adapter.py` (new; follow the existing feedback router test file's fixture style — find it via `grep -rl "feedback" backend/tests/ --include="*.py" -l`)

**Interfaces:**
- `async def record_feedback_evaluation(app_state, *, thread_id: str, run_id: str, user_id: str | None, rating: int, comment: str | None) -> None` — resolves `ansich_service = getattr(app_state, "ansich_service", None)` (None → return); maps run → Task via `await service.get_task_by_source("deerflow_run", run_id)` (None → return); builds an `EvaluationRecord` with `evaluation_kind="user_feedback"`, `dimension="relevance"` (R: spec mandates relevance/custom only — rating +1 → verdict "pass", −1 → verdict "fail", NO correctness inference), `fidelity_class="soft"`, `assessor=NamedVersion(name="user-feedback", version="1.0.0")`, `subject_type="task"`, `occurred_at=datetime.now(UTC)`, `source_event_id=f"evaluation:feedback:{thread_id}:{run_id}:{user_id or 'anonymous'}"` (stable → re-rating upserts idempotently at the observation layer; a CHANGED rating gets a new source event by appending `:{rating}` — include the rating in the id); `service.record(...)` wrapped in `try/except Exception: logger.warning("ansich feedback evaluation failed", exc_info=True)` — fail-open, mirroring `TaskControlProbe._record` (probes/task_control.py:240-270).
- Router change shape: `record = await feedback_repo.upsert(...)` → `await record_feedback_evaluation(request.app.state, ...)` → `return record`. The adapter call must be OUTSIDE any transaction affecting the feedback write and must never raise.

- [ ] **Step 1:** Failing tests: feedback write success + ansich absent → API still 200, no error; feedback success + ansich raising → API still 200 + warning logged; adapter emits relevance evaluation with verdict mapping and NEVER a correctness dimension; unknown run→Task mapping → no observation, API still 200; feedback primary-write failure → adapter not invoked (Ansich never masks the failure); duplicate rating → idempotent (one observation).
- [ ] **Step 2:** RED.
- [ ] **Step 3:** Implement adapter + router hooks.
- [ ] **Step 4:** Green + run the existing feedback router tests + full `tests/ansich`.
- [ ] **Step 5:** Format + commit `feat(ansich): bridge run feedback into evaluation observations`.

### Task 8: Frontend API client, types, and hooks

**Files:**
- Modify: `frontend/src/core/ansich/types.ts` (new response types)
- Modify: `frontend/src/core/ansich/api.ts` (new fetch functions)
- Modify: `frontend/src/core/ansich/hooks.ts` (new hooks)
- Modify: `frontend/src/core/ansich/presentation.ts` (verdict/score formatting helpers)
- Test: `frontend/tests/unit/core/ansich/api-evaluations.test.ts` (new; copy the `rs.mock("@/core/api/fetcher", () => ({ fetch: rs.fn() }))` harness from `tests/unit/core/ansich/api.test.ts`), extend `tests/unit/core/ansich/presentation.test.ts`

**Interfaces (produced — Tasks 9/10 depend on these exact names):**
- Types (mirror the Task 5/6 backend views; follow existing `Ansich*Response` naming):
  - `AnsichQualityBelief` — `{ dimension: string; value: Record<string, unknown>; source: { name: string; version: string }; authority_class: string; fidelity_class: string; as_of: string | null; resolver: { name: string; version: string } | null; conflicting_assertion_count: number; evidence_obs_ids: string[]; unassessed: boolean }`
  - `AnsichEvaluation` — the index-row shape (`evaluation_obs_id`, `subject_type`, `subject_id`, `task_id`, `evaluation_kind`, `dimension`, `verdict`, `score`, `scale_min`, `scale_max`, `scale_higher_is_better`, `assessor_name`, `assessor_version`, `authority_class`, `fidelity_class`, `cohort_key`, `suite_id`, `suite_version`, `case_id`, `occurred_at`)
  - `AnsichTaskEvaluationsResponse` — `{ task_id: string; quality_beliefs: AnsichQualityBelief[]; evaluations: AnsichEvaluation[]; projection_status: Partial<AnsichHealth> }`
  - `AnsichStepEvaluationsResponse` — `{ step_id: string; evaluations: AnsichEvaluation[]; projection_status: Partial<AnsichHealth> }`
  - `AnsichReleaseQualityCohort` — `{ dimension: string; cohort_key: string; assessed_count: number; pass_count: number; fail_count: number; partial_count: number; mean_score: number | null; scale: Record<string, unknown> | null; as_of: string }`
  - `AnsichReleaseQualityResponse` — `{ release_id: string; cohorts: AnsichReleaseQualityCohort[]; projection_status: Partial<AnsichHealth> }`
  - `AnsichQualityComparison` — `{ dimension: string; cohort_key: string; comparison_status: "comparable" | "not_comparable"; reason: string | null; observed_delta: number | null; left_sample_count: number; right_sample_count: number; coverage: Record<string, unknown>; resolver: { name: string; version: string } }`
  - Extend `AnsichAgentReleaseComparisonResponse` with `quality?: { comparisons: AnsichQualityComparison[]; cohort: string | null }`
- API functions (same error/URL conventions as `executeAnsichTaskAction` — `ansichUrl()`, `throwAnsichApiError` on `!response.ok`):
  - `fetchAnsichTaskEvaluations(taskId: string): Promise<AnsichTaskEvaluationsResponse>` → GET `/tasks/{taskId}/evaluations`
  - `fetchAnsichStepEvaluations(stepId: string): Promise<AnsichStepEvaluationsResponse>` → GET `/steps/{stepId}/evaluations`
  - `fetchAnsichReleaseQuality(releaseId: string, cohort?: string): Promise<AnsichReleaseQualityResponse>` → GET `/agent-releases/{releaseId}/quality?cohort=`
  - `compareAnsichAgentReleases` gains an optional `cohort?: string` argument threaded as a query param (existing function — extend its signature backward-compatibly)
- Hooks (follow `useAnsichTaskSteps`'s `(taskId, isAdmin, polling)` shape with `REFRESH_INTERVAL_MS` polling while the Task runs; no polling for release quality):
  - `useAnsichTaskEvaluations(taskId: string, enabled: boolean, polling: boolean)` — queryKey `["ansich", "task", taskId, "evaluations"]`
  - `useAnsichStepEvaluations(stepId: string | null, enabled: boolean)` — queryKey `["ansich", "step", stepId, "evaluations"]`, `enabled` also gates null
  - `useAnsichReleaseQuality(releaseId: string | null, cohort: string | null, enabled: boolean)` — queryKey `["ansich", "release", releaseId, "quality", cohort]`
- Presentation helpers (pure, in `presentation.ts`):
  - `formatEvaluationVerdict(verdict: string | null, score: number | null, scaleMin: number | null, scaleMax: number | null): string` (verdict wins; score renders `"7 / 10"` style; both absent → `"—"`)
  - `qualityBeliefTone(belief: AnsichQualityBelief): "pass" | "fail" | "partial" | "unassessed" | "unknown"` (unassessed flag first; then value.verdict; never infer pass from absence)

- [ ] **Step 1:** Failing unit tests: each fetch function issues the exact URL/method and returns parsed JSON; non-ok responses throw `AnsichApiError` preserving `projection_status`; `compareAnsichAgentReleases` cohort param appears only when provided; presentation helpers cover verdict-wins/score-format/dash and the unassessed-first tone rules.
- [ ] **Step 2:** `pnpm test -- run tests/unit/core/ansich/api-evaluations.test.ts tests/unit/core/ansich/presentation.test.ts` (from `frontend/`) → RED.
- [ ] **Step 3:** Implement types, api functions, hooks, presentation helpers.
- [ ] **Step 4:** Same command → GREEN; then `pnpm check` (lint + typecheck) must pass.
- [ ] **Step 5:** Commit `feat(ansich-ui): add evaluation and release quality API client`.

### Task 9: Task detail Evaluations entry point

**Files:**
- Create: `frontend/src/components/workspace/ansich/evaluations-panel.tsx`
- Modify: `frontend/src/components/workspace/ansich/index.ts` (export `AnsichEvaluationsPanel`)
- Modify: `frontend/src/app/workspace/ansich/tasks/[task_id]/page.tsx` (5th view per R11: extend `type TaskView` and `TASK_VIEWS` at page.tsx:50-51, add `<TabsTrigger value="evaluations">{t.ansich.viewEvaluations}</TabsTrigger>` and a `<TabsContent value="evaluations">` rendering the panel)
- Modify: `frontend/src/core/i18n/locales/en-US.ts`, `zh-CN.ts`, `types.ts` (ansich namespace at en-US.ts:435: `viewEvaluations`, `evaluationsTitle`, `evaluationsUnassessed`, `evaluationsConflicts`, `evaluationsEvidence`, `evaluationsExpectedActual`, `evaluationsNoRecords`, plus dimension labels `dimensionCorrectness|Completeness|Relevance|Safety|Efficiency|EarliestErroneousStep|Custom`)
- Test: `frontend/tests/unit/core/ansich/evaluations-presentation.test.ts` if new pure logic emerges (otherwise extend presentation tests); extend `frontend/tests/e2e/ansich.spec.ts`

**Panel behavior (each bullet is a test assertion somewhere):**
1. `AnsichEvaluationsPanel({ taskId, polling })` consumes `useAnsichTaskEvaluations(taskId, isAdmin, polling)`.
2. Renders one row per quality belief (five R6 dimensions always present): dimension label, verdict/score via `formatEvaluationVerdict`, authority/fidelity badges (reuse `signal-badge.tsx`/`status-badge.tsx` conventions), `conflicting_assertion_count` chip when > 0, assessor `name@version`, resolver `name@version`.
3. `unassessed` rows render with the neutral unassessed treatment (same visual language the release panel used for its unassessed placeholder) — NEVER green/red, never "pass by default".
4. Evidence obs ids render via `AnsichShortId` inside the existing `TechnicalEvidence` fold (`technical-evidence.tsx`); expected/actual/rationale are NOT fetched with the list — an explicit expand action lazily loads the raw payload through the existing admin content-payload route (`fetchAnsichContentPayload` pattern), matching the raw-body lazy/no-store rule.
5. A separate "Recorded evaluations" list shows index rows (kind, dimension, verdict/score, cohort/suite badges, occurred_at via `formatAnsichTimestamp`); empty state uses `evaluationsNoRecords`.
6. E2E (extend `tests/e2e/ansich.spec.ts`, same `page.route()` interception used by existing task-detail flows): mock `/api/ansich/tasks/*/evaluations` → visiting `?view=evaluations` shows the five dimensions with one resolved `fail` (red), four `unassessed` (neutral), conflict chip visible; asserts the raw payload endpoint is NOT called before the expand click.

- [ ] **Step 1:** Write failing unit + e2e tests.
- [ ] **Step 2:** RED run (`pnpm test -- run <files>`; `pnpm test:e2e -- ansich.spec.ts` — e2e may be run once at the end of the task if the harness is slow, but must be run).
- [ ] **Step 3:** Implement panel + page wiring + i18n keys (en + zh + types).
- [ ] **Step 4:** GREEN run + `pnpm check`.
- [ ] **Step 5:** Commit `feat(ansich-ui): add task detail Evaluations entry point`.

### Task 10: Release compare Quality section

**Files:**
- Modify: `frontend/src/components/workspace/ansich/agent-release-panel.tsx` (Quality section inside the comparison card — comparison renders at ~line 208 `<ReleaseComparison comparison={...} />`; add a sibling `<ReleaseQualitySection quality={data.quality} />` fed by the extended compare response, plus a cohort text input threaded into `useAnsichAgentReleaseComparison`'s new cohort argument)
- Modify: `frontend/src/core/ansich/release-presentation.ts` (pure helpers: `qualityComparisonLabel(item: AnsichQualityComparison, t)` mapping `reason` codes `no_shared_cohort|scale_mismatch|insufficient_samples|observability_loss` to localized copy; delta formatting with sign and higher-is-better direction)
- Modify: i18n locales (`qualityTitle`, `qualityNotComparable`, `qualityObservedDelta`, `qualityUnassessed`, `qualitySamples`, `qualityCohortPlaceholder`, reason strings)
- Test: extend `frontend/tests/unit/core/ansich/release-presentation.test.ts` + `frontend/tests/e2e/ansich.spec.ts`

**Behavior (test assertions):**
1. Three visually DISTINCT states per dimension row: `unassessed` (neutral), `not_comparable` (muted + reason copy — not an error color), `comparable` (observed delta with sign, sample counts both sides) — the spec forbids one green/red icon vocabulary covering all three.
2. Quality section renders in a separate card region from the operational/structural diff (spec §7: semantic quality must be visually partitioned from operational distributions).
3. Cohort input change refetches the comparison with `cohort=` and the section reflects the requested cohort.
4. v1 shows observed delta only — no significance language in copy.
5. E2E: mock compare response with one comparable + one not_comparable(insufficient_samples) + absent quality block (old backend) → section hides gracefully when `quality` is undefined.

- [ ] **Step 1:** Failing unit tests for the presentation helpers + e2e additions.
- [ ] **Step 2:** RED run.
- [ ] **Step 3:** Implement section + helpers + i18n.
- [ ] **Step 4:** GREEN + `pnpm check` + full `pnpm test`.
- [ ] **Step 5:** Commit `feat(ansich-ui): add release compare quality section`.

### Task 11: Docs, status sync, and final verification

**Files:**
- Modify: `backend/AGENTS.md` (ansich router table row + embedded-observability section: evaluation kind, projector, resolver v2, new tables; migrations list gains 0023)
- Modify: `ansich/docs/concepts.md` (register `evaluation.recorded`, quality Beliefs, resolver v2, the two new tables — §8 sync obligation)
- Modify: `ansich/docs/plans/README.md` (Phase 10 implementation-status paragraph mirroring the Phase 1-9 entries: what's implemented, what stays gated on PostgreSQL matrix / perf baseline / paper drill)
- Modify: `ansich/docs/plans/10-evaluation-and-semantic-beliefs.md` (append an implementation-status note listing landed pieces and file anchors, mirroring how `09-scope-authorization-and-effects.md` records its state)
- Modify: `ansich/docs/rfc.md` §6 endpoint count (39 → 43: +4 new; note it is currently untracked — edit in place, do not commit it unless asked)

- [ ] **Step 1:** Write the doc updates (no code).
- [ ] **Step 2:** Run the FULL backend suite `uv run pytest tests/ansich -q` and the frontend checks (`pnpm check`, `pnpm test` filtered to ansich + evaluations) one final time; record counts.
- [ ] **Step 3:** Format check (`uv run ruff format --check` on all Python files changed across the phase — never `uvx`).
- [ ] **Step 4:** Commit `docs(ansich): record phase 10 evaluation implementation status`.

---

## Tasks

(TASK DETAILS APPENDED BELOW — each task carries Files / Interfaces / TDD steps.)
