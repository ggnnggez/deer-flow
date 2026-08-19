# Ansich Pre-Phase-11 Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clear every followup item registered as "Phase 11 前" across phases 6–10, close the retro matrix's #3645 weak pass, stand up the opt-in PostgreSQL integration tier, and execute the migration upgrade matrix that has been deferred since Phase 1 — leaving `ansich-dev` ready for Phase 11's multi-worker work.

**Architecture:** Nine focused fixes on existing subsystems (no new features): a contract guard, wall_time single-writer + max-type channel rework (with migration 0024), incremental scope-safety assessment, effect-taxonomy additions, orphan operator-action recovery, a by-model usage read, settle-flake isolation, and a `DEER_FLOW_TEST_POSTGRES_URL`-gated PG test tier mirroring the repo's redis-tier precedent. Docs task last.

**Tech Stack:** Python 3.12 / Pydantic v2 / SQLAlchemy async + Alembic / FastAPI / pytest; PostgreSQL via asyncpg for the new tier.

**Spec:** The binding specs are the registered followup sections themselves — each task names its section. Sources: `ansich/docs/plans/phase-8-review-followups.md` (M1, M2), `phase-9-review-followups.md` (M1, M2), `phase-6-review-followups.md` (L2), `phase-10-review-followups.md` (F10-8, F10-10), `retro-validation-matrix.md` (case F / #3645), `human-followups.md` (D1/D2 status refresh). Repo conventions: `ansich/docs/plans/README.md` 阶段合并规则.

## Global Constraints

- **TDD mandatory:** failing test first with recorded RED, then implement, then GREEN, then the full `uv run pytest tests/ansich -q` once per task (from `backend/`).
- **Known flaky (until Task 8 lands):** `test_sql_budget.py::test_sql_budget_health_retains_terminal_overshoot_and_evidence` plus a rotating load-induced settle-timing family — if the only full-suite failure is one of these, rerun it alone and report both results.
- **Fail-open, append-only, replayable:** no fix may make collection raise into the runtime; projections stay deletable/rebuildable per version; `rebuild_projections()` must reproduce state after every change (extend replay tests where a task touches projection outputs).
- **Followup bookkeeping convention:** each fix task updates ITS OWN followup entry (状态总览 row + 状态 line) in the owning followups file within the same commit, using `✅ 已修复(2026-08-18,本次变更待提交)` style — commits are pushed later, so "本次变更待提交" or the short SHA once known; follow the file's existing precedent.
- **Formatting:** `uv run ruff format` / `uv run ruff check` on changed files from `backend/` — NEVER `uvx ruff` or `make format` (unpinned ruff reformats unrelated Markdown code blocks).
- **Commits on `ansich-dev` directly; never push.**
- **Migration discipline:** any new revision chains from head `0023_ansich_evaluations`, is reversible, idempotent-guarded per the `0016`/`0023` precedent, executable on empty/existing SQLite and (via Task 9's tier) PostgreSQL; bump every head pin under `backend/tests/` (the `55e1a7d7` precedent — grep the old head, zero remaining hits, rename the head test function).
- **No cross-cutting doc edits until Task 10** (except each task's own followup entry per the bookkeeping convention above).

## Fixed design rulings

- **HR1 (phase-8 M2 scope):** implement direction ① ONLY — wall_time becomes a max-type high-water-mark channel (one row per `(aggregate_task, source_task)` for the wall_time dimension, updated by max, never appended per tick); direction ② (general incremental refresh for sum dimensions) is deferred to Phase 11 proper. Migration `0024` collapses historical per-tick wall_time contribution rows into per-source high-water rows (max per source), mirroring how `0019` converted historical usage.
- **HR2 (phase-9 M1 scope):** classify only what is reliably identifiable — built-in file-deletion paths (if any built-in tool deletes) and bash argv patterns `rm`/`unlink`/`rmdir` → `filesystem_delete`, `chmod`/`chown`/`chgrp` → `permission_change`; anything not reliably identifiable stays `unknown` (never over-assert). MCP/external-write metadata remains Phase 11 (registered elsewhere).
- **HR3 (phase-6 L2 shape):** conservative expiry (5 minutes, constant next to the projector lease constants) after which a NEW request with the same Idempotency-Key marks the stale `requested` row `failed` with result `stale_requested_takeover` and proceeds to execute fresh; startup-time sweeping is NOT added (v1 keeps recovery request-driven).
- **HR4 (#3645 scope):** by-model breakdown is LOCAL scope only, computed from the Task's own LLM attempts (provider model identity + per-attempt usage columns from migration 0012); exposed as an additive `by_model` block on the existing `GET /tasks/{task_id}/usage` response when `?by=model` is passed; inclusive-scope by-model is explicitly out of scope (documented).
- **HR5 (PG tier shape):** opt-in via `DEER_FLOW_TEST_POSTGRES_URL` + `@pytest.mark.integration` + self-skip without the env var — the exact contract `tests/test_sandbox_ownership_store.py` uses for `DEER_FLOW_TEST_REDIS_URL`. CI provisions no PG; the tier runs locally/on-demand via a documented make target + docker one-liner. Scope: migration matrix + bootstrap branches + one end-to-end service smoke on PG. Porting the full ansich suite to PG is Phase 11 material.
- **HR6 (settle-flake method):** follow the Phase 7 M2 precedent commits `e91d9f1c`/`4e5eb0fd` (read them first) — make the wait conditions deterministic/isolated rather than raising timeouts. Acceptance: three consecutive full `tests/ansich` runs green on the developer machine.

---

## Tasks

### Task 1: F10-8 — payload-None guard on the three sibling `_validate_subject` branches

**Binding spec:** `ansich/docs/plans/phase-10-review-followups.md` §F10-8.

**Files:**
- Modify: `backend/packages/ansich/ansich/contracts.py` (the `scope.snapshotted` / `authorization.*` / `effect.*` branches at ~contracts.py:243-271)
- Test: extend `backend/tests/ansich/test_sql_safety.py` (its fixtures already build scope/authorization/effect observations)
- Update: F10-8 entry in `phase-10-review-followups.md`

**Interfaces:** none new — the `evaluation.recorded` branch (contracts.py:273-283) is the reference pattern: wrap each branch's payload cross-validation in `if self.payload is not None:` while keeping the subject-type check unconditional. Validation strength with payload in hand must NOT change (existing rejection tests stay green).

- [ ] **Step 1:** Failing test: record one observation of each of the three kinds with a payload large enough to externalize (> `inline_payload_max_bytes`; construct e.g. a scope with a huge `display_label` or pad via a legit large field — if the domain models cap field sizes, drive externalization by constructing the service with a small `inline_payload_max_bytes` like Task-1-of-Phase-10's harness allows via `create_sql_ansich_service(...)` kwargs), flush, then read the observation back through a path that re-validates (`_observation_from_row` — e.g. the timeline read); assert the roundtrip returns the observation instead of raising. Watch it fail with the current unguarded branches.
- [ ] **Step 2:** RED run recorded.
- [ ] **Step 3:** Apply the guard to all three branches (subject-type checks stay unconditional; only payload cross-checks move under the guard).
- [ ] **Step 4:** GREEN: the new test + `uv run pytest tests/ansich/test_contracts.py tests/ansich/test_sql_safety.py -q`, then full `tests/ansich`.
- [ ] **Step 5:** Update the F10-8 entry; format; commit `fix(ansich): guard externalized payload revalidation for scope, authorization, and effect kinds`.

### Task 2: phase-8 M1 — wall_time single writer

**Binding spec:** `ansich/docs/plans/phase-8-review-followups.md` §M1.

**Files:**
- Modify: `backend/packages/harness/deerflow/ansich/persistence/sql.py::_project_heartbeat` (delete its direct `AnsichTaskUsageRow(task_id, "wall_time_ms", "local")` update branch; the heartbeat projector keeps ONLY the `ansich_task_heartbeats` write)
- Test: extend the heartbeat/usage SQL tests (find via `grep -rln "wall_time" backend/tests/ansich/`)
- Update: M1 entry in `phase-8-review-followups.md`

**Interfaces:** after this task `_refresh_usage_summary` (task-usage projector) is the ONLY writer of the wall_time summary row. Behavior must be value-identical on the single-worker path (the followup documents why: usage projector runs at higher priority and computes max-per-source-then-sum).

- [ ] **Step 1:** Failing tests: (a) after heartbeats project, the wall_time summary value equals the usage-projector computation and is NOT touched when only the heartbeat projector runs (drive by processing the heartbeat job while asserting the summary row's value/updated state comes from the usage path — e.g. assert `_project_heartbeat` no longer writes the row by checking the row is absent when the usage projector's kinds are filtered out, or by instrumenting per the existing test style); (b) existing end-to-end wall_time tests stay green.
- [ ] **Step 2:** RED recorded.
- [ ] **Step 3:** Delete the redundant branch.
- [ ] **Step 4:** GREEN + full `tests/ansich`.
- [ ] **Step 5:** Update M1 entry; format; commit `fix(ansich): make usage projector the single wall_time summary writer`.

### Task 3: phase-8 M2 — wall_time as a max-type high-water channel (ruling HR1) + migration 0024

**Binding spec:** `ansich/docs/plans/phase-8-review-followups.md` §M2, direction ① only per HR1.

**Files:**
- Modify: `backend/packages/ansich/ansich/usage.py::usage_contributions_for_observation` (heartbeat no longer emits per-tick wall_time contributions)
- Modify: `backend/packages/harness/deerflow/ansich/persistence/sql.py` (`_project_usage` + `_refresh_usage_summary`: wall_time maintained as one high-water row per `(aggregate_task_id, source_task_id)` updated by max — including ancestry fan-out; summary for wall_time = sum over sources of their high-water values; sum-type dimensions unchanged)
- Create: `backend/packages/harness/deerflow/persistence/migrations/versions/0024_ansich_wall_time_watermarks.py` (collapse historical per-tick wall_time contribution rows to per-source max rows; reversible per the 0019 precedent — read `0019_ansich_task_tree_usage.py` for the historical-conversion style; head pins bumped repo-wide per the Global Constraint)
- Test: extend usage/heartbeat SQL tests + a performance guardrail test (per the P5-M1 SQL statement-listener precedent — find it via `grep -rln "statement" backend/tests/ansich/ | head` or the phase-5 followups' cited test) asserting: N heartbeat ticks produce O(1) wall_time rows per (aggregate, source) and the refresh work per tick does not rescan all historical ticks
- Update: M2 entry in `phase-8-review-followups.md`

**Interfaces:**
- Replay invariant: `rebuild_projections()` reproduces identical wall_time summaries (max is commutative/idempotent — assert with an out-of-order heartbeat test).
- Inclusive semantics preserved: parent inclusive wall_time = Σ over source Tasks of that source's max elapsed (matches the Phase-8 documented semantics "maximum elapsed evidence per source, then summed across sources").
- Terminal wall_time (from the Task monotonic clock at terminal projection) must still land and still win over stale heartbeat values where it did before — locate the terminal-side writer before changing anything and keep its semantics (the absolute-limit assessor reads "max of accumulated terminal contribution and latest heartbeat elapsed"; do not regress `test_sql_budget` semantics).

- [ ] **Step 1:** Failing tests first (row-count guardrail; out-of-order max; replay identity; inclusive sum-of-maxes; terminal-vs-heartbeat precedence unchanged).
- [ ] **Step 2:** RED recorded.
- [ ] **Step 3:** Implement channel rework + migration 0024 + head-pin bumps.
- [ ] **Step 4:** GREEN: usage/heartbeat/budget test files, migration/bootstrap pin files, then full `tests/ansich`.
- [ ] **Step 5:** Update M2 entry; format; commit `fix(ansich): store wall_time as per-source high-water marks instead of per-tick rows`.

### Task 4: phase-9 M2 — incremental scope-safety assessment

**Binding spec:** `ansich/docs/plans/phase-9-review-followups.md` §M2.

**Files:**
- Modify: `backend/packages/harness/deerflow/ansich/persistence/sql.py::_assess_scope_safety_at` (~sql.py:1430-1475 pre-Phase-10 numbering — re-locate): derive the affected `tool_call_id` set from observations in the NEW watermark window (previous assessed watermark → current), re-assess only those; untouched historical tool_calls keep their conclusions with no rewrite
- Test: extend `backend/tests/ansich/test_scope_safety_assessment.py` / the SQL scope-safety tests + a perf guardrail (statement-listener style per the same precedent as Task 3) asserting assessment work does not grow linearly with historical tool_call count when one new evidence observation arrives
- Update: M2 entry in `phase-9-review-followups.md`

**Interfaces:** the assessor's domain function `assess_scope_safety` is per-tool_call already — only the SQL driver's candidate selection changes. The previous watermark must come from durable state (the assessor job's own watermark lineage / last completed job for the subject — read `_claim_assessor_job`'s coalescing to find what "previous watermark" is available; if none is durably available, compute the window from the max `evaluated_obs_id`/ingest_seq already recorded in `ansich_scope_conclusions` rows for the task — pick whichever is durable and deterministic, and say which in the report). Conclusions for re-assessed tool_calls with unchanged results must not append duplicate assertions (`_persist_assessment` dedupe covers this — assert it).

- [ ] **Step 1:** Failing tests (guardrail + incremental correctness: late evidence for tool_call B re-assesses B only; A's conclusion rows/assertions unchanged by count).
- [ ] **Step 2:** RED recorded.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** GREEN + full `tests/ansich`.
- [ ] **Step 5:** Update M2 entry; format; commit `fix(ansich): assess scope safety incrementally per new-evidence tool calls`.

### Task 5: phase-9 M1 — effect taxonomy: filesystem_delete and permission_change (ruling HR2)

**Binding spec:** `ansich/docs/plans/phase-9-review-followups.md` §M1.

**Files:**
- Modify: `backend/packages/harness/deerflow/ansich/tool_middleware.py::_effect_class` (~:259-271)
- Test: extend the tool-effect tests (find via `grep -rln "_effect_class\|effect_class" backend/tests/ansich/`)
- Update: M1 entry in `phase-9-review-followups.md`

**Interfaces:** bash argv-pattern recognition must parse only the LEADING command tokens conservatively (`rm`, `unlink`, `rmdir` → `filesystem_delete`; `chmod`, `chown`, `chgrp` → `permission_change`; pipes/subshells/`&&` chains beyond the first command stay `process_execute`+`unknown` — never over-assert). Check whether any built-in file tool deletes (grep the sandbox tools); if none, bash patterns are the whole surface (say so). The domain Literal for effect classes lives in `ansich.safety` — extend it and check both DB CheckConstraints (models.py `ck_ansich_tool_effect_class`) and the migration that declared it: if the constraint enumerates classes, a migration amendment is needed → then head-pin discipline applies; if it is loose, no migration. Report which.

- [ ] **Step 1:** Failing tests: `rm`/`chmod` bash intents classify; chained/piped commands do NOT; effect rows carry the new classes end-to-end (record→project→read).
- [ ] **Step 2:** RED recorded.
- [ ] **Step 3:** Implement (+ constraint/migration if required).
- [ ] **Step 4:** GREEN + full `tests/ansich`.
- [ ] **Step 5:** Update M1 entry; format; commit `feat(ansich): classify filesystem deletes and permission changes`.

### Task 6: phase-6 L2 — orphan `requested` operator action recovery (ruling HR3)

**Binding spec:** `ansich/docs/plans/phase-6-review-followups.md` §L2.

**Files:**
- Modify: `backend/packages/harness/deerflow/ansich/persistence/sql.py::begin_operator_action` (stale-`requested` takeover per HR3) — the router's 409 path stays for fresh in-progress rows
- Test: extend `backend/tests/ansich/test_ansich_operations_router.py` or the operator-action SQL tests (locate the existing begin/finish tests)
- Update: L2 entry in `phase-6-review-followups.md`

- [ ] **Step 1:** Failing test: simulate crash-after-begin (begin an action, never finish), age the row past the 5-minute window (write its timestamp back directly in the test), retry the SAME Idempotency-Key → the stale row flips to `failed` with result `stale_requested_takeover`, the retry executes, audit trail carries a terminal for both; a FRESH `requested` row (not aged) still 409s.
- [ ] **Step 2:** RED recorded.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** GREEN + full `tests/ansich`.
- [ ] **Step 5:** Update L2 entry; format; commit `fix(ansich): recover orphaned requested operator actions after expiry`.

### Task 7: #3645 — by-model usage breakdown (ruling HR4)

**Binding spec:** `ansich/docs/plans/retro-validation-matrix.md` case F conclusion (弱通过:证据齐全、缺 by-model 聚合).

**Files:**
- Modify: `backend/packages/harness/deerflow/ansich/persistence/sql.py` (new read: per-task token usage grouped by attempt `provider_model` from `AnsichLlmAttemptRow`'s usage/metadata columns — locate the exact columns from migration `0012_ansich_attempt_metadata`)
- Modify: `backend/packages/ansich/ansich/usage.py` or the fitting views module (frozen view `TaskUsageByModelView`: `provider_model: str | None` (None bucket for attempts without provider identity — labeled, never dropped), token dimension sums, `attempt_count`)
- Modify: `backend/packages/ansich/ansich/service.py` (optional-capability read `get_task_usage_by_model(task_id)`)
- Modify: `backend/app/gateway/routers/ansich.py` (`GET /tasks/{task_id}/usage` gains `?by=model` → response gains additive `by_model` block; absent param → response unchanged byte-for-byte)
- Test: extend the usage router/SQL tests
- Update: retro matrix case-F 备注 (one line: 已补,commit ref) — this is the one cross-doc edit allowed outside Task 10 because the retro doc's own text mandates it "随下一次 API 改动顺带补上"
- Note in the phase-10 followups file if convenient, else Task 10 records it

- [ ] **Step 1:** Failing tests: two attempts on model A + one on model B (+ one with no provider identity) → grouped sums with the unknown bucket explicit; `?by=model` additive; without the param the response is unchanged; inclusive scope + `by=model` combination → 422 or documented local-only behavior (pick 422 with a clear message; HR4 says inclusive is out of scope).
- [ ] **Step 2:** RED recorded.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** GREEN + full `tests/ansich`.
- [ ] **Step 5:** Update retro note; format; commit `feat(ansich): expose per-model usage breakdown on task usage`.

### Task 8: F10-10 — settle-flake isolation (ruling HR6)

**Binding spec:** `ansich/docs/plans/phase-10-review-followups.md` §F10-10 + the Phase 7 M2 precedent (`git show e91d9f1c`, `git show 4e5eb0fd` — read both first).

**Files:**
- Modify: the affected test files — start from `backend/tests/ansich/test_sql_budget.py::test_sql_budget_health_retains_terminal_overshoot_and_evidence` (diagnosed this session: the periodic assessment's `absolute-limit` assertion overtakes `budget-health` between the test's two reads — the wait/assert must pin WHICH assessor's assertion it awaits rather than racing the loop) and whatever the precedent's isolation mechanism generalizes to (settle helpers, poll intervals, dedicated waits)
- Possibly modify: shared test support under `backend/tests/support/` or fixture defaults — follow where the precedent commits put their isolation
- Update: F10-10 entry in `phase-10-review-followups.md`

- [ ] **Step 1:** Reproduce first: run the full suite up to three times, record which tests rotate red (if none reproduce, rely on the session-recorded instances: the budget test + Task-9's rotating pair) — this task's RED is the flake evidence itself.
- [ ] **Step 2:** Apply the precedent's isolation to the affected waits (never just raise timeouts).
- [ ] **Step 3:** Acceptance: THREE consecutive full `uv run pytest tests/ansich -q` runs, all green, outputs recorded.
- [ ] **Step 4:** Update F10-10 entry (and drop the "known flaky" caveat lines from `backend/AGENTS.md`? — NO: leave AGENTS.md to Task 10; note it for Task 10 in your report); format; commit `test(ansich): isolate settle-timing waits from suite load`.

### Task 9: PostgreSQL integration tier + migration matrix (ruling HR5)

**Binding spec:** the ten-phase deferred gate "真实 PostgreSQL 升级矩阵" (plans/README 阶段合并规则) + HR5's scope.

**Files:**
- Create: `backend/tests/integration/test_postgres_migration_matrix.py` (or the repo's fitting location — check how `tests/test_sandbox_ownership_store.py` structures its redis tier: marker, skip condition, env var read; mirror it exactly with `DEER_FLOW_TEST_POSTGRES_URL`)
- Create/modify: `backend/Makefile` target `test-postgres` (runs the integration marker with the env var) + a documented docker one-liner (e.g. `docker run --rm -d -p 5433:5432 -e POSTGRES_PASSWORD=... postgres:16` — put the exact command in the Makefile comment or a short `backend/docs/` note; keep it one screen)
- Verify: asyncpg/psycopg driver availability in backend deps (the persistence layer already supports `database.backend: postgres` — confirm the driver is a main dependency; if it is optional, add to the dev group only)
- Update: nothing else (Task 10 records gate progress)

**Test content (each its own test function):**
1. Empty PG: `alembic upgrade head` succeeds; `alembic_version` equals the repo's CURRENT head — assert via `_get_head_revision()` (import from `deerflow.persistence.bootstrap`), never a hardcoded revision string (Task 5 may add a migration before this task runs); all `ansich_*` tables present.
2. Reversibility: `downgrade` to `0004` (pre-ansich), re-`upgrade head` — both succeed (walks every ansich migration's downgrade AND upgrade twice).
3. Idempotent re-upgrade: second `upgrade head` on the migrated DB is a no-op.
4. Bootstrap branches on PG: empty-DB branch (create_all + stamp) and versioned branch (upgrade) via `bootstrap_schema(engine, backend="postgres")` — check `tests/test_persistence_bootstrap.py` for the branch-driving pattern; the legacy branch may be skipped if its seeding is SQLite-specific (say so).
5. Service smoke on PG: `create_sql_ansich_service` against the PG engine — record a task + step + evaluation flow, flush, assert a projection row, a current belief, and `rebuild_projections()` succeeds. One test, end-to-end.
- Each test creates and drops its own uniquely-named database (connect to the server URL, `CREATE DATABASE`, run, `DROP DATABASE`) so the tier is re-runnable — check whether the redis precedent has an isolation idiom to mirror.

- [ ] **Step 1:** Write the tier skeleton + first test; verify the self-skip fires without the env var (run without it → skipped, not failed).
- [ ] **Step 2:** Spin up dockerized PG locally, export the env var, run the tier — fix what real PG surfaces (THIS is the point: 24 migrations have never executed on PG; expect surprises — JSON vs JSONB, index quirks, `safe_add_column` behavior. Genuine migration bugs found here are IN SCOPE to fix, with their own minimal commits, each noted in the report).
- [ ] **Step 3:** All five tests green against real PG; record the verbatim run output in the report.
- [ ] **Step 4:** Confirm the default (no env var) full `tests/ansich` suite is unaffected.
- [ ] **Step 5:** Format; commit `test(ansich): add opt-in postgres migration matrix and service smoke tier` (+ any migration-fix commits separately, `fix(persistence): ...`).

### Task 10: Documentation and status sync

**Files:**
- `ansich/docs/plans/human-followups.md`: D1 → ✅ (concepts.md landed `152f44c2`, extended through Phase 10); D2 → ① 内联 tooltip ✅ (`3425a7a1` System-details drawer help triggers) / ② 正式运维文档仍归 Phase 12 §9 — split the entry's status accordingly; refresh the 施工时机汇总 section (U1 现已到期 — Phase 10 后; U2/A1 归 Phase 11)
- `ansich/docs/plans/README.md`: add a pre-Phase-11 hardening paragraph (what this batch closed: phase-8 M1/M2, phase-9 M1/M2, phase-6 L2, F10-8/F10-10, #3645 by-model, PG matrix executed with driver/details); update the Phase-9/8/6 followup lines' item statuses; state the PostgreSQL gate's honest progress (migration matrix + bootstrap + service smoke executed on real PG; full-suite PG parity and multi-worker semantics remain for Phase 11/12)
- `backend/AGENTS.md`: ansich section — wall_time high-water channel (0024), incremental scope-safety, new effect classes, by-model usage read, stale-`requested` recovery; migrations list gains 0024; remove/adjust the known-flaky caveat per Task 8's outcome; add the `test-postgres` target to the commands section
- `ansich/docs/plans/retro-validation-matrix.md`: only if Task 7 did not already annotate case F
- `ansich/docs/rfc.md` (UNTRACKED — edit in place, do not git-add): §7 对 main 的入侵 refresh — recompute the file/line counts against the SAME baseline the section names (`git diff --stat <baseline>..HEAD` filtered to the categories the section describes; if the named baseline commit is no longer resolvable, restate against the current `git merge-base` with upstream main and say so in the text); migration range 0005–0024
- Final verification: full `uv run pytest tests/ansich -q` (should now be flake-free per Task 8 — three runs if time allows) + `cd frontend && pnpm check` (no frontend changes expected — confirm) + `uv run ruff format --check` on all Python files this plan changed

- [ ] **Step 1:** Write all doc updates (accuracy over volume — verify each claim against the merged code).
- [ ] **Step 2:** Run the final verification; record counts verbatim.
- [ ] **Step 3:** Format check; commit `docs(ansich): record pre-phase-11 hardening and postgres matrix status`.
