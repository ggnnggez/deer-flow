# Ansich P11-C — Replay, Retention, Raw-Read Audit, Shutdown Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver spec §5–§8 of `ansich/docs/plans/11-resilience-replay-and-retention.md` — versioned replay, tiered retention with tombstones, fail-closed raw-payload read audit, and a bounded shutdown/startup-recovery sequence — plus the inherited debts routed to this batch (F10-29, F10-31, F10-32, F10-33, and the ruling-only items F10-21/F10-22/jsonb/U2).

**Architecture:** All storage work lands in `backend/packages/harness/deerflow/ansich/persistence/` (sql.py, models.py, migration 0028); service-level orchestration in `backend/packages/ansich/ansich/` (service.py, lifecycle.py, contracts.py); the replay entrypoint is a harness CLI module `deerflow.ansich.replay` (never a route); §7 touches the gateway router and the frontend client layer; §8 touches `AnsichService.stop()/start()` and the Gateway lifespan.

**Tech Stack:** Python 3.12 / SQLAlchemy 2 async / Alembic / FastAPI / pytest; Next.js + TanStack Query on the frontend; the opt-in PostgreSQL tier (`DEER_FLOW_TEST_POSTGRES_URL`) for dialect-real proofs.

**Spec:** `ansich/docs/plans/11-resilience-replay-and-retention.md` (§5 spec:67-85, §6 spec:87-108, §7 spec:110-118, §8 spec:120-133, §9 spec:135-141, §10 spec:143-153, §11 spec:155-162). **Recon dossier** (anchors valid at `dbfc9c8a`): `/home/nan/.claude/jobs/80128e0c/tmp/p11c-recon-dossier.md` — implementers should trust its anchors over memory, and re-locate by symbol if lines have drifted.

## Global Constraints

These carry P11-A/P11-B's binding lessons plus this batch's spec-wide rules. Every task's requirements implicitly include this section.

1. **Fail-open for collection; the ONE documented inversion is §7.** Nothing added in this batch may raise into a Run path or the ops tick. Raw-read audit is the single fail-closed site (spec:114) and every fail-closed line must carry a comment naming the inversion so nobody "fixes" it back.
2. **None-never-0, unknown-first-class.** `retention last run` is `None` when never run; `active versions` absent ≠ empty; no health/read-model field ever fabricates a number.
3. **Observations are append-only; idempotency key is `(producer_name, producer_instance_id, source_event_id)` (`models.py:75`).** Replay and retention never write Observations (retention deletes per policy; replay touches jobs + read models only). Audit Observations (§7) key `source_event_id` on a per-read unique id, never on `(actor, payload)`.
4. **PB7 monotonic-basis precondition (spec:108, `sql.py:865-879`).** Any operation that creates or re-pends a job below the current `complete_through` mark MUST delete the affected `ansich_active_task_read_model` rows in the same transaction. This binds replay (T5/T6), retention (T9/T10), and any operator tool this batch adds.
5. **Receipt coupling (spec:106, FC-3).** Retention must not let RA6 rung-3/4 receipts flip a once-live row's answer to `failed`. The chosen device is the retention horizon (ruling RC7).
6. **Generation monotonicity (`models.py:94-111`).** No path resets `lease_generation`. Replay re-pends increment it (the rebuild precedent, `sql.py:1915`); retry-style re-arms leave it alone.
7. **`pending ⟺ attempts == 0` holds store-wide** (P11-B batch-final F2). Any new writer of job status obeys it: re-arm with attempts>0 ⇒ `retry`, never `pending`.
8. **Lock ordering: every multi-row lock traversal is sorted; the serializing-prefix argument must be stated at the site** (`backend/AGENTS.md:1445-1470`). `descendant_task_ids` is deterministic but NOT sorted at its two producers — the first task that walks it taking locks (T10's subtree delete) must sort it at both producers first.
9. **Ruling discipline:** every ruling states invariant + domain + cost-if-wrong. Deviations from spec letter are recorded with rationale in the same change set (AGENTS + the spec's section notes), following the P11-B four-deviation precedent.
10. **Process rules (binding, from the P11-B ledger):** pinned `uv run ruff format` / `uv run ruff check` only (never uvx/make format); no output-truncating pipes on failure-bearing runs; timeout-wrap long runs; snapshot-restore for mutation verification (never `git checkout` on a dirty tree); reviewers are read-only; one implementer holds the git index at a time; probe → committed-test; red-first for every testable behavior; assert on DB rows where `project_pending` swallows exceptions; fixture clocks are past-dated.
11. **F10-30 narrow merge gate (nine named members, `phase-10-review-followups.md:436-477`).** Unnamed reds block until triaged. A red of shape "`unsettled == 0` treated as completion" routes to F10-26, not F10-30 — and because this batch writes replay tests, every completeness assertion in new tests uses the bounded settle loop (T1's helper) from the start so it never enters that triage.
12. **PG tier honesty:** `test_postgres_multiworker.py` has **14** tests (+5 migration-matrix = the 19 of `make test-postgres`). The tier runs on a developer machine, never CI; tasks touching leases/claims/locks/retention batching must run it locally and record the result.
13. **Harness/app firewall:** `deerflow.*` never imports `app.*`; the replay CLI lives harness-side. Frontend exhaustive-switch rule: a new alert type or health field goes through all six pinned places at once.
14. **Config:** all new keys are startup-only, mirrored into `config.example.yaml` with `config_version` bumped once per batch (35→36 at the first task that adds a key; later tasks do NOT bump again).

## Rulings

**RC1 — Completeness is a bounded caller loop, not a wait.**
Invariant: no caller may treat one `rebuild_projections()`/`retry_failed_projections()` round as completion; completeness = observed `unsettled == 0` from a fresh round, reached via a bounded loop.
Domain: every completeness-wanting caller — the replay CLI, §10 replay/retention tests, the retry HTTP route's consumers.
Cost if wrong: a wait inside the lock stalls a worker (`sql.py:1279-1283`); an unbounded loop hangs shutdown paths. Bound: `max_rounds` with honest "still unsettled" report on exhaustion.

**RC2 — Multi-version registration must not leak into live ingest.**
Invariant: registering a projector version for replay purposes never causes live ingest to mint jobs for it; `_projectors_for_kind` fan-out stays exactly the live `_PROJECTORS` set.
Domain: T3's registry split (live set vs replayable set).
Cost if wrong: every new Observation silently doubles its job fan-out (the `contracts.py:92-102` one-way door in reverse).

**RC3 — Replay reuses the rebuild posture: maintenance lock + read-model delete in the same transaction + generation increment.**
Invariant: Global Constraint 4 (PB7). Replay's job mint/re-pend at low `ingest_seq` deletes affected `ansich_active_task_read_model` rows in the same transaction — exactly what `_rebuild_projections_locked` already does wholesale.
Domain: T5's executor; any future operator re-enqueue tool.
Cost if wrong: the active-task read model freezes permanently (the `sql.py:865-879` docstring's named shape).

**RC4 — v1 `--replace` is projector-scoped whole-table, filtered replace is rejected.**
Invariant: `--replace` deletes exactly the read-model tables owned by the target projector (a new explicit projector→tables ownership map, partitioned from the rebuild delete list), under the maintenance lock; a `--replace` combined with a task/time/ingest filter is refused with an explanatory error.
Domain: T5. Rationale: read models carry no version/row-level ownership discriminator (50 tables, none version-keyed); inventing one is a cross-cutting migration this batch does not need — same-version replay + whole-table replace covers §5's determinism acceptance. Recorded as a spec-letter narrowing ("该 version 管理的 projection rows" ⇒ "该 projector 拥有的 read-model 表").
Cost if wrong (too coarse): a replace rebuilds more rows than the filter targeted — wasted work, never wrong data (projections are rebuildable by definition).

**RC5 — Active version selection is a DB row mutated only by the CLI, not config.**
Invariant: `ansich_active_versions` (new table, migration 0028) maps `component_kind` (`projector`/`resolver`) + `component_name` → `active_version`; absent row ⇒ code default; the ONLY writer is the replay CLI's `activate` subcommand, which persists an audit Observation in the same flow; readers cache per-process and `start()` validates every active row against the code registry (D8-5).
Domain: belief resolver selection (`resolver.py:64` default param) and replay's "which version is current" answer.
Cost if wrong: a config field would be startup-only (contradicting "显式管理动作并审计") or silently reinterpret history on deploy — exactly what spec:79 forbids.

**RC6 — Payload tombstones replace the raise with an explicit degraded state (the H6-A three-way decision, decided).**
Invariant: after retention deletes a payload body, every reader distinguishes three states: present / tombstoned (`evidence_expired`) / missing (still a loud `RuntimeError` — a tombstone-less missing row remains a corruption signal, not a policy outcome).
Domain: all seven hydrator sites (`sql.py:2958, :2178, :4119, :4309, :8049, :8317, :9031`) plus the scope-safety readers behind them; the F10-29 fixes (T2) land first so environment readers inherit it.
Cost if wrong: either a Task-wide poison stall every tick (keep the raise) or fabricated verdicts from empty payloads (silent `{}`) — both worse than an explicit expired state.

**RC7 — The retention horizon prevents the receipt flip.**
Invariant: retention maintains a durable horizon row (max `ingest_seq` at-or-below which observation-tier deletion has completed); RA6's rung-3/4 receipt inference consults it and answers the expired-evidence status (not `failed`) for sequences at or below the horizon.
Domain: `service.py:966-1037`'s ladder; the `EvaluationProjectionStatus` literal set — the implementer reads `errors.py:47-48`'s no-fourth-value record and either mints the fourth value honestly (updating that record in the same commit) or maps to the existing unknown-shaped value with a written reason.
Cost if wrong: once-accepted writes read as `failed` after retention — a false integrity alarm that erodes trust in receipts (FC-3's named harm).

**RC8 — §7 reuses `operator.action_*` by widening `action_type`; the subject is the host Scope for non-Task payloads. (Recorded spec deviations: the field is `action_type`, not `action_kind`; subject rule widened.)**
Invariant: raw-read audits are `operator.action_requested/succeeded/failed` Observations with `action_type="raw_payload_read"`; subject = the owning Task when the payload is Task-scoped, else the host `Scope` (the `contracts.py:307-308` validator gains a scope-subject arm for exactly this action_type); `source_event_id` keys on a fresh per-read `action_id` (H7-D).
Domain: the four raw endpoints; the audit rows also become §6's eighth delete family.
Cost if wrong: a new kind trio would fork the operator-audit pipeline; a Task-only subject would leave ContentBlock/manifest reads unauditable.

**RC9 — Raw-read audit writes are synchronous backend writes, never `record()`.**
Invariant: the requested-audit row is durably committed before the payload is read (audit-then-read); persistence failure ⇒ 503 with no read attempted; denied requests audit without reading. The fail-open collector queue is structurally incapable of confirming persistence, so the audit path calls the backend directly.
Domain: T12's route flow only. Cost if wrong: an "audited" read whose audit evaporates with the queue is a security control in name only.

**RC10 — F10-33 is built in this batch as the episode lock-then-read conversion, which also un-blocks the shutdown's final assessment.**
Invariant: episode opening uses `_insert_ignoring_conflict` + winner re-read (the T5-family posture) so a `uq_ansich_alert_episode` collision costs one row re-read, not the whole `assess_operations` transaction.
Domain: `sql.py::_reconcile_alerts_for_assessments`; consumed by T13 (the shutdown's final tick has no "next tick to self-heal").
Cost if wrong: the terminal assessment of every shutdown silently discards heartbeat/dwell/budget/environment conclusions whenever two workers race — at exactly the moment no retry follows.

**RC11 — F10-32 takes route (b): a one-statement data step in migration 0028.**
Invariant: `DELETE FROM ansich_active_task_read_model` in 0028 (pure read model; the next ops tick rebuilds it — the rebuild precedent). This kills the expiring "no deployed population" premise permanently instead of re-adjudicating it at deploy time.
Domain: the migration + the F10-32 registry flip. Cost if wrong: one-to-two seconds of empty Running lens on first startup after upgrade — recorded in the migration docstring.

**RC12 — Startup lease sweep implements D8-2 literally, honoring the attempt-count rule.**
Invariant: `start()` sweeps `processing` rows with expired leases into their honest bucket (`attempts > 0 ⇒ retry`, else `pending`), touching neither attempts nor generation; bounded, logged with counts.
Domain: T13 startup. The lazy claim-path re-claim remains the correctness backstop; the sweep adds legibility (health counts stop showing phantom `processing`).
Cost if wrong: none beyond one indexed scan at startup; skipping it entirely would be a recorded deviation for no gain.

**RC13 — D8-4 restores nothing and says so.**
Invariant: producer health has no durable source; `start()` fabricates neither producer state nor lost ranges (spec:128's own words). The deliverable is the honest docstring + AGENTS sentence, not a mechanism.
Domain: T13. Cost if wrong: fabricated lost ranges — the exact thing spec:7 forbids readers to misread.

**RC14 — Ruling-only debts get written adjudications, not builds.**
- **F10-21**: this batch takes the cheap honest half — UI/docs state that `attempted_/realized_scope_violation` are structurally unreachable in production (zero hits ≠ health); the Scope-binding design stays open with its entry updated. Domain: docs + one UI label. Cost: none.
- **F10-22**: NOT this batch — P11-C never touches `_effect_class`; the entry's own 归属 keys it to that next touch. Recorded with reason.
- **jsonb**: adjudicated DEFERRED with reason — this batch's retention/replay queries filter on timestamps, sequences, and typed columns, never JSON content; the migration trigger remains "the first content-filter consumer", and the registry entry gains this batch's confirmation that no such consumer was added.
- **U2**: unblocked by T12 but NOT built here (frontend content-browsing is its own batch; building it before §7 settles would have meant building twice — that reason expires with this batch, so U2's entry flips to "unblocked, schedulable").

**RC15 — Spec/document corrections ride the first task that touches each document.**
The dangling `task-3-report.md §6` pointer at spec:83 (T1 replaces it with the real wrapper's location); spec:85's stale "没有 docstring" clause (T1); every "19 tests" claim about the multiworker file corrected to 14 (+5) where quoted (T15 sweep).

---

### Task 1: Completeness loop — `rebuild_until_settled` + `RetryOutcome`

**Files:**
- Modify: `backend/packages/ansich/ansich/contracts.py` (add `RetryOutcome`; extend `RebuildOutcome` docs)
- Modify: `backend/packages/ansich/ansich/service.py` (`rebuild_until_settled`, `retry_failed_projections` return type)
- Modify: `backend/packages/harness/deerflow/ansich/persistence/sql.py` (`retry_failed_projections` counts unsettled)
- Modify: `backend/app/gateway/routers/ansich.py` (`POST /operations/failed-jobs/retry` response gains `unsettled`)
- Modify: `frontend/src/core/ansich/api.ts` + `types.ts` + `failed-jobs-dialog.tsx` (surface `unsettled` honestly)
- Modify: `ansich/docs/plans/11-resilience-replay-and-retention.md` (spec:83 pointer, spec:85 stale clause — RC15)
- Test: `backend/tests/ansich/test_lease_cas.py` (extend), `backend/tests/ansich/test_ansich_router.py` (route shape)

**Interfaces:**
- Produces: `RetryOutcome(re_armed: int, unsettled: int)` (frozen pydantic model beside `RebuildOutcome`, `contracts.py:764`); `async AnsichService.rebuild_until_settled(*, max_rounds: int = 5) -> RebuildOutcome` — loops `rebuild_projections()` while `unsettled > 0` and rounds remain, returns the LAST round's outcome (callers check `.unsettled == 0` themselves; exhaustion is reported, not raised). `retry_failed_projections() -> RetryOutcome`.
- Consumes: `RebuildOutcome` (`contracts.py:764-792`), `_unsettled_job_count` (`sql.py:1819-1831`).

- [ ] Red-first: a test where one dependency-deferred job leaves round 1 with `unsettled > 0` and `rebuild_until_settled` converges by round ≤ 5; a test that `retry_failed_projections` returns `RetryOutcome` with a genuine `unsettled` count (re-read after the re-arm, same lower-bound honesty as `RebuildOutcome` — document it); route test pins the JSON shape.
- [ ] Implement; `_as_rebuild_outcome`-style normalization for bare-int backends stays.
- [ ] Frontend: the retry dialog shows "re-armed N, still unsettled M" (both locales); no new switch sites.
- [ ] Spec text corrections (RC15). Gates: full `tests/ansich`, `pnpm check && pnpm test`, ruff. Commit.

### Task 2: F10-29 — close the externalized-payload reader class (three instances)

**Files:**
- Modify: `backend/packages/ansich/ansich/contracts.py:318-322` (guard the `environment.sampled` branch, F10-8 style)
- Modify: `backend/packages/harness/deerflow/ansich/persistence/sql.py` (`_claim_projection_job` hydrates BEFORE `_observation_from_row` envelope validation, `sql.py:2174-2182`; `get_environment_history` hydrates instead of guard-and-skip, `sql.py:5778-5792`)
- Test: `backend/tests/ansich/test_contracts_environment.py`, `test_environment_projector.py`, `test_lease_cas.py` (claim-path regression with an externalized environment sample)

**Interfaces:**
- Consumes: `_hydrated_observation_payload` (`sql.py:2933-2963`), `inline_payload_max_bytes` (65536).
- Produces: nothing new — three regressions, one per instance, each red-first (a >65536-byte `environment.sampled` payload: validates on read-back, claims and projects, appears in history).

- [ ] One red-first regression per instance; fix; the retraction comments at the history reader are updated to describe the hydrate. Registry flip text drafted for T15 (do not edit the registry here). Gates + commit.

### Task 3: Multi-version projector registry + schema-compat check

**Files:**
- Modify: `backend/packages/harness/deerflow/ansich/persistence/sql.py` (`_PROJECTORS` stays the LIVE set; new `_REPLAYABLE_VERSIONS: dict[str, tuple[str, ...]]` naming every version the code can execute per projector — today `{name: ("1",)}` for all ten; new `_validate_replay_target(projector_name, version)` returning a typed refusal reason or None)
- Test: `backend/tests/ansich/test_replay.py` (NEW)

**Interfaces:**
- Produces: `_validate_replay_target` (registered? version executable? kinds known?) — consumed by T4. `ReplayTargetError(ValueError)` in `errors.py` with a `reason` literal (`unknown_projector` / `unknown_version` / `not_executable`).
- Consumes: `_PROJECTORS` (`sql.py:333-353`), `_PROJECTOR_KINDS` (`sql.py:360-370`), `AnsichProjectorVersionRow`.

- [ ] Red-first: registering/knowing a replayable version does NOT change `_projectors_for_kind` fan-out (structural pin: live-ingest job mint for a fresh Observation names exactly the live set — RC2); `_validate_replay_target` refuses unknown name/version with typed reasons.
- [ ] Implement. Gates + commit.

### Task 4: Replay module `deerflow.ansich.replay` + CLI (dry-run, filters, digest)

**Files:**
- Create: `backend/packages/harness/deerflow/ansich/replay.py` (module: `plan_replay`, `execute_replay`), `backend/packages/harness/deerflow/ansich/replay_cli.py` or `__main__`-style entry following `skills/review/cli.py` precedent
- Modify: `backend/packages/harness/deerflow/ansich/persistence/sql.py` (target-set query; job mint/re-pend under maintenance lock; canonical read-model digest)
- Test: `backend/tests/ansich/test_replay.py`

**Interfaces:**
- Produces: `ReplayReport(projector_name, projector_version, targeted: int, minted: int, re_pended: int, replayed: int, unsettled: int, errors: tuple[str, ...], watermark: int | None, digest: str | None, dry_run: bool)` (frozen model, `contracts.py`); CLI args: `--projector NAME --version V [--task-id ID] [--occurred-from ISO --occurred-to ISO] [--ingest-from N --ingest-to N] [--dry-run] [--replace] [--max-rounds N]`.
- Consumes: T1's `rebuild_until_settled` loop shape (the drive loop calls `project_pending` rounds and reports `unsettled` the same way); T3's `_validate_replay_target`; `sha256_canonical` (`release/canonical.py:8-11`); the maintenance lock (`sql.py:1267-1385`).

Binding mechanics:
- Target set: task filter via `ix_ansich_observations_task_ingest`; time filter via `occurred_at` bounded WITH a kind list from `_PROJECTOR_KINDS[projector]` so `ix_ansich_observations_kind_occurred` serves it (NEVER `recorded_at` — no index); ingest filter via PK range.
- Mint absent `(obs_id, projector, version)` rows / re-pend existing ones with `lease_generation + 1` (Global Constraint 6), **deleting affected `ansich_active_task_read_model` rows in the same transaction (RC3)** — affected = the task_ids of targeted Observations (plus all when the target is unfiltered).
- Digest: canonical serialization of the target projector's owned read-model rows (ownership map from T5; ordered by each table's PK), `sha256_canonical` over the concatenation; `None` when `unsettled > 0` (a digest over an unsettled state is a lie).
- Dry-run: plan only — counts, no writes, no lock beyond the reads.

- [ ] Red-first: target-filter tests (task/time/ingest each select exactly the expected job set); dry-run writes nothing (row-count snapshot equality); digest determinism — replay twice over the same Observation set, digests equal AND `unsettled == 0` via the bounded loop (§11 acceptance, spec:159); late-Observation test (an Observation ingested after round 1 is NOT silently absorbed — either outside the target range or reported in a fresh count); PB7 regression — replay over a low-ingest range with an active task read-model row present: row deleted in-txn, next ops tick republishes (no freeze; assert on rows).
- [ ] Implement module then CLI (CLI is a thin arg-parse over the module; no `app.*` imports). Gates + commit. PG tier: add one two-worker replay test (replay while a live worker projects) — run locally, record.

### Task 5: `--replace` + per-version read-model ownership map

**Files:**
- Modify: `backend/packages/harness/deerflow/ansich/persistence/sql.py` (`_PROJECTOR_OWNED_TABLES: dict[str, tuple[type[Base], ...]]` — partition of the `_rebuild_projections_locked` delete list (`sql.py:1835-1901`) by owning projector, with a structural test pinning "every table in the rebuild delete list is owned by exactly one projector"; `--replace` path deletes the target projector's tables under the maintenance lock before re-pend)
- Test: `backend/tests/ansich/test_replay.py`

**Interfaces:**
- Produces: `_PROJECTOR_OWNED_TABLES` (consumed by T4's digest); replace semantics per RC4 (whole-table, filter+replace refused with `ReplayTargetError(reason="filtered_replace_unsupported")`).
- Consumes: T4's executor.

- [ ] Red-first: partition pin (exactly-one-owner over the rebuild list); replace deletes only the owned tables (sibling projector rows survive — assert on rows); filter+replace refused; replace + full replay reproduces the pre-replace digest (determinism across replace).
- [ ] Implement. Record the RC4 spec-letter narrowing in the spec §5 note + AGENTS. Gates + commit.

### Task 6: Active versions — DB row, audited CLI switch, health field, startup validation

**Files:**
- Modify: `backend/packages/harness/deerflow/ansich/persistence/models.py` + migration 0028 (T8 owns the migration file; this task defines `AnsichActiveVersionRow(component_kind, component_name, active_version, activated_at, activated_by, audit_obs_id)` — coordinate: T6 lands AFTER T8's migration exists, or mints the table in 0028 via T8's interface block)
- Modify: `backend/packages/harness/deerflow/ansich/persistence/sql.py` (read/write + cache), `backend/packages/ansich/ansich/service.py`, `replay_cli.py` (`activate` subcommand), `contracts.py` (`DatabaseHealth.active_versions: tuple[ActiveVersion, ...] | None`)
- Modify: `backend/app/gateway/routers/ansich.py` (health passthrough), `frontend/src/core/ansich/types.ts` + `observability-health-panel.tsx` + both locales
- Test: `backend/tests/ansich/test_replay.py`, `test_database_health.py`, frontend unit

**Interfaces:**
- Produces: `activate(component_kind, component_name, version, actor)` — validates against T3's registry / `resolver.py` versions, writes the row AND an `operator.action_*`-family audit Observation (RC8's discriminator machinery from T12 is NOT required: use `action_type="raw_payload_read"`'s sibling value `"activate_version"` added in the same Literal widening — coordinate with T12's widening; whichever task lands first widens the Literal for both values and the other consumes it); resolver reads consult the row (absent ⇒ `DEFAULT_RESOLVER`).
- Consumes: T3 registry; T8 migration; D8-5 consumed by T13.

- [ ] Red-first: absent row ⇒ code default (structural + behavioral); activate writes row + audit observation atomically; activating an unknown version refused; health block carries active versions (`None` when unreadable — Constraint 2); startup validation helper `validate_active_versions()` returns typed mismatches (consumed by T13). Frontend renders the list; six-place rule if any new alert/health enum appears.
- [ ] Implement. Gates (backend + frontend) + commit.

### Task 7: (folded into Task 8 — F10-32 route (b) is a data step in migration 0028; the ruling record is RC11. No standalone task.)

### Task 8: Retention config + migration 0028

**Files:**
- Modify: `backend/packages/harness/deerflow/config/ansich_config.py` (`AnsichRetentionConfig(raw_payload_days=7, observation_days=30, structural_days=90, cleanup_batch_size=500)` nested field `retention:`, `AnsichAssessorConfig` precedent at :6-30; cross-field validator: `raw_payload_days <= observation_days <= structural_days`)
- Modify: `config.example.yaml` (`ansich.retention:` block; `config_version` 35→36 — the batch's single bump)
- Modify: `backend/packages/harness/deerflow/ansich/persistence/models.py` (`AnsichPayloadRow.body` → nullable + `deleted_at` + `policy` columns — `sha256`/`byte_size` already exist :37-38, with `ck_ansich_payload_tombstone_one_of` check (body XOR deleted_at); `AnsichRetentionStateRow` — durable cursor + horizon + last-run: `(id=1, payload_cursor, observation_cursor, structural_cursor, observation_horizon_ingest_seq, last_run_started_at, last_run_finished_at, last_run_policy)`; `AnsichActiveVersionRow` per T6's interface)
- Create: migration `0028_ansich_retention` (via `make migrate-rev`, then `_helpers.py`-ify; includes RC11's `DELETE FROM ansich_active_task_read_model` data step with docstring)
- Test: `backend/tests/ansich/test_retention.py` (NEW — config + schema), `backend/tests/integration/test_postgres_migration_matrix.py` self-extends (head moves to 0028)

**Interfaces:**
- Produces: the config model; the three new/changed tables; `retention_last_run` raw material (consumed by T9's health work); tombstone columns (consumed by T9/T2-adjacent hydrators).
- Consumes: config version discipline (Constraint 14).

- [ ] Red-first: config parse + validator + reload-boundary pin (startup-only inheritance); migration up on both dialects (matrix tests stay green with head 0028); tombstone check constraint enforced.
- [ ] Implement. Gates + commit. PG matrix run locally, record.

### Task 9: Time-tiered retention executor + horizon + hydrator degrade states

**Files:**
- Modify: `backend/packages/harness/deerflow/ansich/persistence/sql.py` (`run_retention(policy, *, now) -> RetentionReport`; three tiers; own advisory lock KEY distinct from maintenance (`_PG_RETENTION_LOCK_KEY`), small batches of `cleanup_batch_size`, cursor persisted per batch — resumable mid-tier; tombstone hydrator states per RC6 at all seven sites; receipt horizon per RC7 in `service.py:966-1037`)
- Modify: `backend/packages/ansich/ansich/service.py` (async passthrough; `errors.py` fourth-status adjudication per RC7), `contracts.py` (`RetentionReport(payload_tombstoned, observations_deleted, structural_deleted, batches, resumed_from_cursor, finished, started_at, finished_at)`; `DatabaseHealth.retention_last_run: RetentionLastRun | None`)
- Modify: `backend/app/gateway/routers/ansich.py` (health passthrough), frontend health panel + locales
- Test: `backend/tests/ansich/test_retention.py`; PG tier: one retention-vs-projector concurrency test

**Interfaces:**
- Produces: `run_retention`, `RetentionReport`, the horizon consumed by receipts, `retention_last_run` in health (None when never run — Constraint 2).
- Consumes: T8's schema; T2's hydrate honesty; RC6/RC7.

Binding mechanics:
- Tier 1 (payload): `deleted_at IS NULL AND` age > `raw_payload_days` (age from the owning observation's `occurred_at` via the RESTRICT referrer — enumerate referrers; payloads referenced by `content_blobs`/`agent_releases`/`authorization_snapshots` are aged by their own referrer rows' evidence; a payload with ANY referrer younger than policy is skipped) — body→NULL + `deleted_at` + `policy`; sha256/byte_size retained (they are the tombstone's lineage half).
- Tier 2 (observation): age > `observation_days` AND `ingest_seq` contiguous from the current horizon (the horizon only advances over fully-deleted prefixes — that is what makes RC7's "at or below horizon" answerable); dependent projections deleted or marked expired per RC6; the RESTRICT wall means tier 2 deletes referrers-first inside one batch txn per FK order (the dossier's Part 2.2.2 list is the order authority); jobs go via the Observation CASCADE (`models.py:85`) — which is exactly why the horizon must be committed BEFORE the delete batch (receipt readers must never see deleted-but-below-horizon as failed; write horizon, then delete, in that order — an aborted batch leaves the horizon honestly high? NO — the horizon claims deletion happened. Order is: delete batch commits, THEN advance horizon in the same transaction's final statement — same txn = atomic, no window).
- Tier 3 (structural): Entity/Relation last, only for Tasks whose entire observation range is below the horizon.
- PB7: retention NEVER re-creates jobs (Constraint 4 trivially held — assert structurally: no `INSERT` into job tables anywhere in the retention module).
- Every lock traversal sorted (Constraint 8).

- [ ] Red-first per §10 (spec:150): payload tombstone (delete → tombstone visible, hydrators return expired state, scope-safety degrade not raise, lineage intact); observation expiry (dependent projection deleted/marked; Current Belief never left evidence-less — the belief whose only assertion evidence expired reads as expired, assert on rows); batch resume (kill mid-tier via injected failure, re-run resumes from cursor, no double-count); receipt horizon (an accepted receipt for a deleted observation answers expired/unknown, never `failed` — the FC-3 regression); FK no-orphan sweep (after a full pass, a referential integrity walk over the dossier's RESTRICT list finds zero danglers, both dialects).
- [ ] Implement. Gates + commit. PG tier run recorded.

### Task 10: Owner/thread hard delete (D6-2)

**Files:**
- Modify: `backend/packages/harness/deerflow/ansich/persistence/sql.py` (`hard_delete_scope(scope_id) -> HardDeleteReport`; Scope→Tasks via `ix_ansich_relations_object_predicate`; subtree via task_spawns/ancestry — SORT `descendant_task_ids` at both producers first, Constraint 8; deletes the eight families in FK order incl. §7 audit rows; bootstrap sentinel refused)
- Modify: `backend/packages/ansich/ansich/service.py` + router (admin route `POST /retention/hard-delete` — this one IS a route: it is owner-initiated, not arbitrary projector execution) + contracts (`HardDeleteReport`)
- Test: `backend/tests/ansich/test_retention.py`; PG tier concurrency case

**Interfaces:**
- Consumes: T9's machinery (batching, lock key); T12's audit rows (delete family #8) — T10 lands after T12.
- Produces: `HardDeleteReport(tasks, observations, payloads, projections, relations, read_models, audit_refs, batches)`.

- [ ] Red-first: full-subtree delete leaves zero orphans (the walk); observations belonging to the deleted Tasks go too (no FK exists — explicit delete by `task_id` index; the RESTRICT wall order from the dossier); precedence over time retention (a hard-deleted range never resurfaces via tier cursors); `ANSICH_BOOTSTRAP_TASK_ID`/host-Scope refused with typed error; PB7 (read-model rows for deleted Tasks removed in-txn).
- [ ] Implement. Gates + commit + PG record.

### Task 11: F10-31 + F10-33 — the two remaining first-writer races (lock-then-read family)

**Files:**
- Modify: `backend/packages/harness/deerflow/ansich/persistence/sql.py` (attempt projector site ~:9499-9516 → fifth conversion: `_insert_ignoring_conflict` + `FOR UPDATE` re-read + loser-field merge — two obs pointers compose (request_obs_id from whichever side carries it, likewise response), status transition takes the max of the lattice `incomplete < requested < success`; episode site `_reconcile_alerts_for_assessments` → sixth conversion per RC10)
- Modify: `backend/tests/integration/test_postgres_multiworker.py` (REMOVE the `ansich_llm_attempts_pkey` typed tolerance — with the fix it must not fire; the F10-33 provocation test at :1567 asserts no whole-tick loss)
- Test: `backend/tests/ansich/test_rollup_serialization.py`, `test_process_health_alerts.py`

**Interfaces:**
- Consumes: `_lock_rollup_targets` (`sql.py:887`), `_insert_ignoring_conflict` (`sql.py:926`), the four-site precedent.
- Produces: collision-free attempt projection + episode opening; consumed by T13's final assessment.

- [ ] PRE-AUTHORIZED SPLIT (like PB3): if the two conversions prove independently large, 11a=F10-31, 11b=F10-33, each with its own review.
- [ ] Red-first (SQLite behavioral + structural pins); PG tier is the real proof — both races were provoked there; run locally and record. Remove the tolerance in the same commit as the F10-31 fix. Gates + commit.

### Task 12: §7 raw-read audit — fail-closed

**Files:**
- Modify: `backend/packages/ansich/ansich/operator.py:14` (widen `action_type` Literal per RC8 — coordinate with T6), `contracts.py:307-308` (scope-subject arm for the widened types), `backend/packages/harness/deerflow/ansich/persistence/sql.py:5207-5247` (payload fields: actor user id, payload id, purpose, request correlation, timestamp — never the body)
- Modify: `backend/app/gateway/routers/ansich.py` (all four raw endpoints: admin → subject validation → synchronous requested-audit persist (RC9) → read → succeeded/failed audit; denied ⇒ audit-without-read; audit-persist failure ⇒ 503 with the inversion comment; size limit via new config `ansich.raw_read_max_bytes` default 1 MiB startup-only (NO version bump — Constraint 14); `Content-Disposition: attachment` on non-JSON bodies per the artifacts-router precedent)
- Modify: `frontend/src/core/ansich/api.ts:647-652` (`{cache:"no-store"}` on `fetchAnsichContentPayload`)
- Test: `backend/tests/ansich/test_raw_read_audit.py` (NEW); frontend unit for the api change

**Interfaces:**
- Produces: the audit rows (delete family for T10); the widened Literal (shared with T6's `activate_version`).
- Consumes: RC8/RC9; `require_admin_user` (`deps.py:597-616`); trace correlation from the Request Trace Context.

- [ ] Red-first per §10 (spec:151): admin vs non-admin (denied audited, payload never read — instrument the read path to prove no touch); audit-DB-failure ⇒ 503 AND no read (injected failure); metadata routes still readable during the same failure; `no-store` on all four responses; oversized payload refused with audited denial; second read by same actor of same payload produces a SECOND audit row (H7-D); the strict actor idiom (`str(user.id)`) — unify the two router idioms while there.
- [ ] Implement. Gates + commit.

### Task 13: §8 bounded shutdown + startup recovery

**Files:**
- Modify: `backend/packages/ansich/ansich/service.py` (`stop()` → seven-step sequence per spec:122, each step budgeted from a new `ansich.shutdown_budget_ms` (default 25000, startup-only) apportioned per-step, each step's outcome recorded into a `ShutdownReport`; bound the projector join AND the post-loop drain (`service.py:2388-2393` gets a deadline + bounded final assessment — safe after RC10); FC-5: the unreported-loss drain step calls `_drain_unreported_global_ranges` under its step budget — first real caller of the `live` guard; `start()`: RC12 lease sweep, T6 active-version validation, RC13 honesty, orphan-correlation hook)
- Modify: `backend/packages/ansich/ansich/contracts.py` (`ShutdownReport(steps: tuple[ShutdownStep, ...], total_ms, budget_ms, completed)`; `ShutdownStep(name, ok, timed_out, duration_ms, detail)`), `lifecycle.py` untouched (H8-A — the 17-edge closure is a merge gate; shutdown phases live in the report, not the status vocabulary)
- Modify: `backend/app/gateway/deps.py:412-429` (lifespan consumes the report, logs per-step), `backend/app/gateway/routers/ansich.py` + frontend if health carries last-shutdown info (optional — only if cheap and honest)
- Test: `backend/tests/ansich/test_bounded_stop.py` (extend), `test_gateway_lifecycle.py`, `test_lifecycle.py` stays green untouched

**Interfaces:**
- Consumes: T1 (bounded rounds), T6 (`validate_active_versions`), RC10 (safe final assessment), RC12/RC13, FC-5's `live` guard.
- Produces: `ShutdownReport` consumed by the lifespan logs; startup sweep counts logged.

- [ ] Red-first per §10 (spec:152): shutdown with active Task + writer backlog completes within budget with per-step results (freeze one step via injected hang → that step times out, later steps still run, report says so); the unreported-loss bucket drains at stop (a loss range recorded just before stop() appears as an `observability.lost` row — the FC-5 regression) and a still-growing range is honestly left (the `live` guard's first real test); startup lease sweep (expired `processing` rows land in retry/pending per attempts — Constraint 7); orphan correlation writes `unknown` evidence, never `completed` (assert on assertion rows); active-version mismatch at startup surfaces as a typed startup log + health degradation, not a crash (fail-open — Constraint 1); no lost-range fabrication on crash recovery (RC13's docstring + a test that start() after simulated crash writes zero loss rows).
- [ ] Implement. Gates + commit. PG tier shutdown-vs-worker case run locally, recorded.

### Task 14: Frontend — Observability panel: retention last run + active versions (+ F10-21 honest label)

**Files:**
- Modify: `frontend/src/core/ansich/types.ts`, `api.ts`, `hooks.ts`, `observability-health-panel.tsx`, both locales; the scope-effects view gains F10-21's "structurally unreachable in production" honest annotation (RC14)
- Test: frontend unit (`observability-health.test.ts`) + `tests/e2e/ansich.spec.ts`

**Interfaces:** Consumes T6 + T9 health fields (may already be partially landed by those tasks' passthroughs — this task owns the panel rendering + e2e).

- [ ] Red-first: null-never-0 rendering for `retention_last_run` (never run ⇒ "—"/未运行, epoch-zero forbidden); active versions listed with code-default marking; e2e stub faithful to real wire shapes (the T11-P11B lesson: derive from backend source, not invention). `pnpm check && pnpm test` + e2e out-of-band. Commit.

### Task 15: Docs & status closure

**Files:** `backend/AGENTS.md` (§5-8 paragraphs: replay posture incl. RC4 narrowing, retention tiers + horizon, the §7 fail-closed inversion, the shutdown report; migration list 0028); registry flips F10-29/31/32/33 with hashes; RC14's four written adjudications (F10-21 half, F10-22 not-this-batch, jsonb deferred-with-reason, U2 unblocked); F10-26 observation note updated (tests now use the bounded loop); `ansich/docs/plans/README.md` P11-C entry; spec §5-8 implementation-status notes (deviations: RC4, RC8's action_type/subject, RC5's DB-row-not-config); the 14-vs-19 sweep (RC15); `config.example.yaml` final check; commit this plan file; full dual-side gate run.

- [ ] Commit `docs(ansich): record P11-C replay, retention, audit, and shutdown`。

## Self-Review 记录

- Spec coverage: §5 → T1/T3/T4/T5/T6(D5-1..9 各有归属;D5-7 由 RC5 落为 DB 行);§6 → T8/T9/T10(D6-1..7 + FC-3/FC-4);§7 → T12(D7-1..5;RC8/RC9 记偏离);§8 → T13(D8-1..7 + FC-5;RC12/RC13);§9 欠账(retention last run、active versions、CLI replay)→ T6/T9/T14;§10 各条测试形状在对应任务的 red-first 清单里逐条点名;§11 完成条件:多 worker 不重复投影(P11-B 已证,T11 补两处竞态)、digest 双跑一致(T4)、无悬空引用+tombstone(T9/T10)、审计不可用即拒(T12)、无 spool 诚实(T13/RC13)。
- 继承债:F10-29→T2;F10-31/33→T11;F10-32→RC11(0028 数据步);F10-21/22/jsonb/U2→RC14(T15 落档);F10-26 留观→Constraint 11 + T1。
- Type consistency: `RetryOutcome`/`ReplayReport`/`RetentionReport`/`HardDeleteReport`/`ShutdownReport`/`ShutdownStep`/`AnsichActiveVersionRow`/`AnsichRetentionStateRow` 的名字在产出任务定义、消费任务逐字引用;T6/T12 共享的 Literal 扩宽有先落者负责的协调条款。
- 依赖顺序:T1→T4;T3→T4→T5;T6 依赖 T8 的迁移与 T3;T12 先于 T10(审计行是删除族之八);T11 先于 T13(RC10);T14 收 T6/T9 的字段;T15 收尾。0028 一次迁移承载 T6/T8/RC11 全部 schema 变更——T8 是唯一的迁移作者,T6 通过接口块提供表定义。
- 无占位符;每任务锚点来自侦察档案(HEAD dbfc9c8a 核实)。
