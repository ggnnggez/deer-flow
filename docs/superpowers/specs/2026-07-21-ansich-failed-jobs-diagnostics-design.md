# U3: Failed-job drill-down diagnostics for Ansich projection/assessor health

- **Date**: 2026-07-21
- **Source**: `ansich/docs/plans/human-followups.md` item **U3**
- **Branch**: `ansich-dev`
- **Status**: design approved, ready for plan

## Problem

`AnsichService.get_health()` exposes a single `failed_jobs` counter (sum of
`AnsichProjectionJobRow`/`AnsichAssessorJobRow` rows with `status == "failed"`,
process-global — not scoped to a Task). `AnsichProjectionHealth`
(`frontend/src/components/workspace/ansich/projection-health.tsx`) renders it as a
plain, non-interactive metric on both the Task detail page and the Operations page.
When the count is non-zero, an operator has no way to see *which* job failed, on
which Task, with what error, or how many times — they have to query the database
directly. `AnsichService.retry_failed_projections(task_id=None)` already exists as a
non-destructive recovery action but has no HTTP route, so it cannot be triggered from
the UI at all today.

The data needed for drill-down already exists and is not destroyed by retry:

- `AnsichProjectionJobRow` / `AnsichAssessorJobRow` — current `status`, `attempts`,
  `last_error` (cleared on retry), plus job identity (`projector_name`/`assessor_name`
  + version) and linkage back to a Task (`obs_id → ansich_observations.task_id` for
  projection jobs; `subject_id` directly for assessor jobs, since assessor jobs are
  Task-scoped).
- `AnsichProjectionErrorRow` / `AnsichAssessorErrorRow` — one row per failed attempt
  (`attempt`, `error_type`, `message`, `occurred_at`), append-only, **not** cleared by
  retry. This is the only place a job's full failure history survives.

## Design decisions (approved)

1. **Two entry points, different scope.** The Operations page drill-down is global
   (optionally filterable by `task_id`); the Task detail page drill-down is
   pre-filtered to that Task. Both render the same dialog component parameterized by
   an optional `taskId` prop — one API, one frontend component, two call sites.
2. **Retry stays Task-batch granularity.** No new single-job retry method. The retry
   action in the UI calls the existing `retry_failed_projections(task_id=...)` (now
   finally exposed over HTTP) and its label makes clear it retries *all* currently
   failed jobs for that Task, not just the row the operator clicked.
3. **List + separate detail endpoint.** The list endpoint returns lightweight rows
   (identity, status, attempts, `last_error`, Task linkage). A separate per-job detail
   endpoint returns the full ordered attempt-error history from
   `AnsichProjectionErrorRow`/`AnsichAssessorErrorRow`, fetched lazily when an operator
   expands a row.

## DTO field naming — align with Phase 11

`ansich/docs/plans/11-resilience-replay-and-retention.md` already commits to writing
poison-job failures into `ansich_projection_errors` and raising a `projection_failure`
Alert from the same data. This feature's DTOs reuse the existing row column names
(`error_type`, `message`, `occurred_at`, `attempt`) verbatim rather than inventing new
ones, so Phase 11 can build its Alert producer and any richer diagnostics view on top
of the same query/DTO shape without a schema or contract rename.

## Components & data flow

### Backend read/mutate methods — `AnsichService` (delegates to backend, same pattern
as `list_alerts` / `retry_failed_projections`)

```text
async def list_failed_jobs(self, *, task_id: str | None = None, limit: int = 100) -> list[FailedJobSummary]
async def get_failed_job_detail(self, *, job_id: str, kind: Literal["projection", "assessor"]) -> FailedJobDetail | None
# retry_failed_projections already exists — reused as-is, only newly routed over HTTP
```

`FailedJobSummary` fields: `job_id`, `kind` (`"projection"|"assessor"`), `name`
(`projector_name` or `assessor_name`), `version`, `task_id`, `status`, `attempts`,
`last_error`, `available_at`. `task_id` is always resolvable: `AnsichObservationRow.
task_id` is `nullable=False` and `AnsichProjectionJobRow.obs_id` is a `CASCADE` FK
into it, so an inner join is sufficient (no left-join / `None`-handling needed); for
assessor jobs `task_id == subject_id` directly.

`FailedJobDetail` = `FailedJobSummary` fields + `errors: list[{attempt, error_type,
message, occurred_at}]` ordered by `occurred_at` ascending.

### SQL backend — `backend/packages/harness/deerflow/ansich/persistence/sql.py`

Added next to `retry_failed_projections` (sql.py:1016):

- `list_failed_jobs`: two `SELECT ... WHERE status == "failed"` queries mirroring the
  `job_ids`/`assessor_job_ids` lookups already in `retry_failed_projections` (same
  `task_id` join pattern), merged and sorted by `available_at DESC`. Reuses the
  existing `ix_ansich_projection_jobs_claim` / `ix_ansich_assessor_jobs_claim`
  indexes (both lead with `status`) — no new index.
- `get_failed_job_detail`: single job lookup by `job_id` (+ `kind` to pick the right
  table pair), then its ordered `AnsichProjectionErrorRow`/`AnsichAssessorErrorRow`
  rows by `job_id`.

### API — `backend/app/gateway/routers/ansich.py` (admin-only via `require_admin_user`,
same 503-when-unavailable handling as neighboring routes)

- `GET /operations/failed-jobs?task=&limit=` → `{"items": [FailedJobSummary...]}`
- `GET /operations/failed-jobs/{job_id}?kind=projection|assessor` → `FailedJobDetail`
  dict, 404 if not found
- `POST /operations/failed-jobs/retry?task=` → `{"retried": <int>}` (first HTTP
  exposure of `retry_failed_projections`; no `task` retries globally)

Response shape follows the existing convention in this router (plain `dict`, not a
declared Pydantic response model — matches `list_alerts`/`list_safety_events`).

### Frontend

- `core/ansich/types.ts` — `AnsichFailedJob`, `AnsichFailedJobDetail`,
  `AnsichFailedJobsResponse`.
- `core/ansich/api.ts` — `getAnsichFailedJobs`, `getAnsichFailedJobDetail`,
  `retryAnsichFailedJobs`.
- `core/ansich/hooks.ts` — `useAnsichFailedJobs(taskId?, limit?, enabled?)`,
  `useAnsichFailedJobDetail(jobId, kind, enabled?)`,
  `useAnsichRetryFailedJobs()` (mutation; invalidates the failed-jobs list query and
  the health query on success).
- **New** `components/workspace/ansich/failed-jobs-dialog.tsx` —
  `AnsichFailedJobsDialog({ taskId }: { taskId?: string })`. Row = identity + status +
  attempts + last_error preview; expand row → lazy-fetches detail, shows ordered
  error history; retry button (per Task, grouped) calls the mutation.
- `components/workspace/ansich/projection-health.tsx` — `failed_jobs` `HealthMetric`
  becomes a `Button`/`Badge` trigger when `health.failed_jobs > 0`, opening the dialog.
  `AnsichProjectionHealth` gains an optional `taskId` prop threaded through to the
  dialog (undefined on the Operations page → global; set on the Task detail page →
  scoped). No prop change needed at either of the two existing call sites beyond
  passing `taskId` where already in scope.
- `components/workspace/ansich/index.ts` — export the new dialog.
- `core/i18n/locales/{en-US,zh-CN,types}.ts` — new strings (dialog title, column
  headers, retry button/confirmation, empty state, error-history section).

## Scope / non-goals (v1)

- No single-job retry — Task-batch only (decision #2 above).
- No multi-worker lease visualization or poison-job auto-isolation — Phase 11.
- No new Alert type (`projection_failure`/`observability_degradation`) — Phase 11.
- No pagination cursor for the list — a bounded `limit` (default 100, matching the
  existing `list_safety_events` convention) is enough for a diagnostics view of
  *currently* failing jobs; this is not a historical log.

## Testing (TDD, `backend/tests/`, `frontend/tests/`)

Backend (new file `backend/tests/ansich/test_failed_job_diagnostics.py` covering both
the SQL/service layer and, alongside existing router test conventions, additions to
`backend/tests/ansich/test_ansich_router.py`):

1. Projection-job failure surfaces in `list_failed_jobs` with correct `task_id`
   resolved via its observation; assessor-job failure surfaces with `task_id ==
   subject_id`.
2. Mixed list (both kinds) sorted by `available_at desc`.
3. `task_id` filter narrows to that Task only; non-existent `task_id` → empty list.
4. `get_failed_job_detail` returns full ordered attempt history and is **not**
   affected by a prior partial retry of a different job.
5. `POST retry` resets targeted job(s) to `pending`/`attempts=0`, list no longer shows
   them as failed, and their prior `AnsichProjectionErrorRow`/`AnsichAssessorErrorRow`
   history is preserved (not deleted) for later detail lookups.
6. Router: admin-only 401/403 on all three new endpoints; 404 on unknown `job_id` for
   the detail endpoint; 503 when storage unavailable (matches `_service_or_503`
   convention).

Frontend (`frontend/tests/unit/core/ansich/`): `api.ts`/`hooks.ts` request-shape and
query-key tests, matching the existing coverage style for this directory (component-
level behavior for workspace panels is not unit-tested elsewhere in this codebase —
`scope-effects-panel.tsx` has none either — so `failed-jobs-dialog.tsx` follows the
same convention and is not required to add one for this feature).

## Files touched

- `backend/packages/harness/deerflow/ansich/persistence/sql.py` — `list_failed_jobs`,
  `get_failed_job_detail`
- `backend/packages/ansich/ansich/service.py` — matching delegating methods
- `backend/app/gateway/routers/ansich.py` — 3 new routes
- **new** `backend/tests/ansich/test_failed_job_diagnostics.py`
- `backend/tests/ansich/test_ansich_router.py` — router-level additions
- `frontend/src/core/ansich/{types,api,hooks}.ts`
- **new** `frontend/src/components/workspace/ansich/failed-jobs-dialog.tsx`
- `frontend/src/components/workspace/ansich/projection-health.tsx`
- `frontend/src/components/workspace/ansich/index.ts`
- `frontend/src/app/workspace/ansich/tasks/[task_id]/page.tsx` — pass `taskId`
- `frontend/src/app/workspace/ansich/operations/page.tsx` — no `taskId` (global)
- `frontend/src/core/i18n/locales/{en-US,zh-CN,types}.ts`
- `frontend/tests/unit/core/ansich/` — new coverage for the above
- `ansich/docs/plans/human-followups.md` — mark U3 ✅ 已修复 (overview table + U3
  status line)
- `backend/AGENTS.md` / `frontend/AGENTS.md` — one line each noting the new
  admin-only failed-job diagnostics endpoints / dialog, if the existing Ansich
  summary paragraphs are updated for Phase 9-adjacent work; otherwise skip (this is a
  small enough surface that it may not warrant a standalone AGENTS.md line beyond
  what the router/component docstrings already say — judgment call at implementation
  time based on how much the surrounding paragraph already covers).
