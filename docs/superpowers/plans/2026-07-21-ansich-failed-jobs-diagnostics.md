# Ansich Failed-Job Diagnostics (U3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an admin see *which* Ansich projection/assessor jobs are currently failing (identity, attempts, last error, owning Task, full attempt-error history) and retry them from the UI, instead of only seeing a bare `failed_jobs` count.

**Architecture:** Two new read-only `AnsichService` methods (`list_failed_jobs`, `get_failed_job_detail`) that query the existing `AnsichProjectionJobRow`/`AnsichAssessorJobRow`/`AnsichProjectionErrorRow`/`AnsichAssessorErrorRow` tables (no new tables, no new indexes — reuses the existing `status`-leading indexes). Three new admin-only routes in `backend/app/gateway/routers/ansich.py`, the third being the first-ever HTTP exposure of the already-existing `AnsichService.retry_failed_projections`. A new `AnsichFailedJobsDialog` frontend component, opened from the existing `failed_jobs` metric in `AnsichProjectionHealth` on both the Task detail page (Task-scoped) and the Operations page (global).

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy async / Pydantic v2 (backend), Next.js / TypeScript / TanStack Query / shadcn Dialog (frontend).

## Global Constraints

- Backend TDD is mandatory: write the failing test before the implementation (`backend/AGENTS.md`).
- No new tables, no new indexes — reuse `ix_ansich_projection_jobs_claim` / `ix_ansich_assessor_jobs_claim` (both lead with `status`).
- Retry stays Task-batch granularity — no single-job retry method (design decision, see spec §"Design decisions").
- New DTO field names reuse the existing row column names verbatim (`error_type`, `message`, `occurred_at`, `attempt`) so Phase 11's poison-job work can reuse this shape (see spec §"DTO field naming").
- `AnsichService.list_failed_jobs` / `get_failed_job_detail` follow the same **optional** `getattr(self._backend, "...", None)` delegation pattern as `retry_failed_projections` (sql.py:1016) — **not** added to the `AnsichBackend` Protocol in `backend/packages/ansich/ansich/backend.py`, matching that method's existing precedent (`InMemoryAnsichBackend` does not implement it either).
- Router responses are plain `dict` (not declared Pydantic `response_model` classes), matching every existing endpoint in `backend/app/gateway/routers/ansich.py`.
- Frontend: component-level unit tests are not required for this feature — no existing `components/workspace/ansich/*.tsx` panel has one (e.g. `scope-effects-panel.tsx`); only `core/ansich/{api,hooks}.ts` get unit tests, matching existing coverage in `frontend/tests/unit/core/ansich/`.
- Spec: `docs/superpowers/specs/2026-07-21-ansich-failed-jobs-diagnostics-design.md`.

---

### Task 1: `FailedJob*View` Pydantic contracts in the `ansich` core package

**Files:**
- Create: `backend/packages/ansich/ansich/jobs.py`
- Test: `backend/tests/ansich/test_failed_job_diagnostics.py` (new file — also used by Tasks 2 and 3)

**Interfaces:**
- Produces: `FailedJobKind = Literal["projection", "assessor"]`, `FailedJobSummaryView(BaseModel)` (fields: `job_id: str`, `kind: FailedJobKind`, `name: str`, `version: str`, `task_id: str`, `status: str`, `attempts: int`, `last_error: str | None`, `available_at: datetime`), `FailedJobErrorView(BaseModel)` (fields: `attempt: int`, `error_type: str`, `message: str`, `occurred_at: datetime`), `FailedJobDetailView(FailedJobSummaryView)` (adds `errors: tuple[FailedJobErrorView, ...]`). All `model_config = ConfigDict(extra="forbid", frozen=True, strict=True)`, matching `backend/packages/ansich/ansich/operator.py`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/ansich/test_failed_job_diagnostics.py`:

```python
from datetime import UTC, datetime

from ansich.jobs import FailedJobDetailView, FailedJobErrorView, FailedJobSummaryView
from pydantic import ValidationError
import pytest


def test_failed_job_summary_view_round_trips_through_json():
    view = FailedJobSummaryView(
        job_id="job-1",
        kind="projection",
        name="task-safety",
        version="1",
        task_id="task-1",
        status="failed",
        attempts=3,
        last_error="IntegrityError: x",
        available_at=datetime(2026, 7, 21, 9, 0, tzinfo=UTC),
    )
    dumped = view.model_dump(mode="json")
    assert dumped["kind"] == "projection"
    assert FailedJobSummaryView.model_validate(dumped) == view


def test_failed_job_summary_view_rejects_unknown_kind():
    with pytest.raises(ValidationError):
        FailedJobSummaryView(
            job_id="job-1",
            kind="not-a-real-kind",
            name="task-safety",
            version="1",
            task_id="task-1",
            status="failed",
            attempts=0,
            last_error=None,
            available_at=datetime(2026, 7, 21, 9, 0, tzinfo=UTC),
        )


def test_failed_job_detail_view_extends_summary_with_ordered_errors():
    detail = FailedJobDetailView(
        job_id="job-1",
        kind="assessor",
        name="scope-safety",
        version="1",
        task_id="task-1",
        status="failed",
        attempts=2,
        last_error="ValueError: y",
        available_at=datetime(2026, 7, 21, 9, 0, tzinfo=UTC),
        errors=(
            FailedJobErrorView(
                attempt=1,
                error_type="ValueError",
                message="first failure",
                occurred_at=datetime(2026, 7, 21, 8, 0, tzinfo=UTC),
            ),
            FailedJobErrorView(
                attempt=2,
                error_type="ValueError",
                message="second failure",
                occurred_at=datetime(2026, 7, 21, 8, 30, tzinfo=UTC),
            ),
        ),
    )
    assert [error.attempt for error in detail.errors] == [1, 2]
    assert detail.model_dump(mode="json")["errors"][0]["message"] == "first failure"
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `backend/`): `PYTHONPATH=. uv run pytest tests/ansich/test_failed_job_diagnostics.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ansich.jobs'`

- [ ] **Step 3: Write minimal implementation**

Create `backend/packages/ansich/ansich/jobs.py`:

```python
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

FailedJobKind = Literal["projection", "assessor"]


class FailedJobSummaryView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    job_id: str
    kind: FailedJobKind
    name: str
    version: str
    task_id: str
    status: str
    attempts: int
    last_error: str | None = None
    available_at: datetime


class FailedJobErrorView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    attempt: int
    error_type: str
    message: str
    occurred_at: datetime


class FailedJobDetailView(FailedJobSummaryView):
    errors: tuple[FailedJobErrorView, ...]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. uv run pytest tests/ansich/test_failed_job_diagnostics.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/packages/ansich/ansich/jobs.py backend/tests/ansich/test_failed_job_diagnostics.py
git commit -m "feat(ansich): add FailedJob view contracts"
```

---

### Task 2: `list_failed_jobs` / `get_failed_job_detail` — SQL backend + `AnsichService` delegation

**Files:**
- Modify: `backend/packages/harness/deerflow/ansich/persistence/sql.py` (add two methods on `SqlAnsichBackend`, right after `retry_failed_projections`, sql.py:1016-1066)
- Modify: `backend/packages/ansich/ansich/service.py` (add two delegating methods on `AnsichService`, right after `retry_failed_projections`)
- Test: `backend/tests/ansich/test_failed_job_diagnostics.py` (append to the file from Task 1)

**Interfaces:**
- Consumes: `FailedJobKind`, `FailedJobSummaryView`, `FailedJobErrorView`, `FailedJobDetailView` from Task 1 (`ansich.jobs`).
- Produces: `SqlAnsichBackend.list_failed_jobs(*, task_id: str | None = None, limit: int = 100) -> list[FailedJobSummaryView]`, `SqlAnsichBackend.get_failed_job_detail(*, job_id: str, kind: FailedJobKind) -> FailedJobDetailView | None`; `AnsichService.list_failed_jobs(*, task_id: str | None = None, limit: int = 100) -> list[FailedJobSummaryView]`, `AnsichService.get_failed_job_detail(*, job_id: str, kind: FailedJobKind) -> FailedJobDetailView | None` — later tasks (router) call these two `AnsichService` methods.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/ansich/test_failed_job_diagnostics.py` (add these imports at the top of the file, alongside the existing ones):

```python
from ansich import AnsichService, ObservationEnvelope, Producer, new_id
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from deerflow.ansich.persistence.models import AnsichAssessorJobRow, Base
from deerflow.ansich.persistence.sql import SqlAnsichBackend
```

Then add:

```python
@pytest.mark.anyio
async def test_list_and_detail_failed_jobs_cover_both_projection_and_assessor_kinds(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-failed-jobs.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    backend = SqlAnsichBackend(session_factory, projector_dependency_timeout_seconds=0)
    service = AnsichService(backend, flush_interval_ms=60_000)
    await service.start()
    task_id = new_id()
    step_id = new_id()
    producer = Producer(name="failed-job-diagnostics-test", version="1", instance_id="test")
    observed_at = datetime.now(UTC)

    try:
        # A step.started observation for a Task that does not exist yet makes
        # the "task-step" projection job dependency-pending, then fail once
        # the (zero-second) dependency timeout elapses — a real failed
        # projection job, same technique as
        # test_sql_task_lifecycle.py::test_dependency_pending_job_eventually_fails_health_and_can_be_retried.
        service.record(
            ObservationEnvelope(
                kind="step.started",
                occurred_at=observed_at,
                task_id=task_id,
                step_id=step_id,
                subject_type="step",
                subject_id=step_id,
                producer=producer,
                producer_seq=1,
                source_event_id="failed-job-diagnostics:step:started",
                correlation_id=task_id,
                payload={"step_seq": 1, "actor_kind": "lead_agent"},
            )
        )
        await service.flush_task(task_id)

        empty_for_other_task = await service.list_failed_jobs(task_id="does-not-exist")
        all_failed = await service.list_failed_jobs()
        scoped_failed = await service.list_failed_jobs(task_id=task_id)

        assert empty_for_other_task == []
        assert len(all_failed) == 1
        assert len(scoped_failed) == 1
        summary = scoped_failed[0]
        assert summary.kind == "projection"
        assert summary.name == "task-step"
        assert summary.task_id == task_id
        assert summary.status == "failed"
        assert summary.attempts >= 1
        assert summary.last_error is not None

        detail = await service.get_failed_job_detail(job_id=summary.job_id, kind="projection")
        assert detail is not None
        assert detail.task_id == task_id
        assert len(detail.errors) >= 1
        assert detail.errors[0].message == summary.last_error or detail.errors[-1].message == summary.last_error

        missing_detail = await service.get_failed_job_detail(job_id="does-not-exist", kind="projection")
        assert missing_detail is None
    finally:
        await service.stop()
        await engine.dispose()


@pytest.mark.anyio
async def test_failed_job_detail_history_survives_retry_and_matches_error_table(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-failed-jobs-retry.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    backend = SqlAnsichBackend(session_factory, projector_dependency_timeout_seconds=0)
    service = AnsichService(backend, flush_interval_ms=60_000)
    await service.start()
    task_id = new_id()
    step_id = new_id()
    producer = Producer(name="failed-job-retry-test", version="1", instance_id="test")
    observed_at = datetime.now(UTC)

    try:
        service.record(
            ObservationEnvelope(
                kind="step.started",
                occurred_at=observed_at,
                task_id=task_id,
                step_id=step_id,
                subject_type="step",
                subject_id=step_id,
                producer=producer,
                producer_seq=1,
                source_event_id="failed-job-retry:step:started",
                correlation_id=task_id,
                payload={"step_seq": 1, "actor_kind": "lead_agent"},
            )
        )
        await service.flush_task(task_id)
        before_retry = await service.list_failed_jobs(task_id=task_id)
        assert len(before_retry) == 1
        job_id = before_retry[0].job_id
        detail_before = await service.get_failed_job_detail(job_id=job_id, kind="projection")
        assert detail_before is not None
        error_count_before = len(detail_before.errors)

        service.record(
            ObservationEnvelope.task_lifecycle(
                kind="task.created",
                task_id=task_id,
                source_kind="deerflow_run",
                source_id="run-failed-job-retry",
                occurred_at=observed_at,
                source_event_id="failed-job-retry:task:created",
            )
        )
        await service.flush_task(task_id)
        retried = await service.retry_failed_projections(task_id=task_id)
        after_retry = await service.list_failed_jobs(task_id=task_id)

        assert retried == 1
        assert after_retry == []
        # The append-only error table is untouched by retry — history for
        # the now-recovered job is still queryable by job_id.
        detail_after = await service.get_failed_job_detail(job_id=job_id, kind="projection")
        assert detail_after is not None
        assert len(detail_after.errors) == error_count_before
    finally:
        await service.stop()
        await engine.dispose()
```

Also add a third test that checks the merge/sort behavior across **both** kinds. This test targets the `list_failed_jobs` query layer only (not the assessor execution/failure-injection pipeline, which already has its own coverage in `test_sql_alerts.py`), so it produces the projection-job failure the same way as above and inserts a failed `AnsichAssessorJobRow` directly against a real (projected) Task:

```python
@pytest.mark.anyio
async def test_list_failed_jobs_merges_and_sorts_both_kinds_across_tasks(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-failed-jobs-merge.db'}")

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    backend = SqlAnsichBackend(session_factory, projector_dependency_timeout_seconds=0)
    service = AnsichService(backend, flush_interval_ms=60_000)
    await service.start()
    projection_task_id = new_id()
    assessor_task_id = new_id()
    step_id = new_id()
    producer = Producer(name="failed-job-merge-test", version="1", instance_id="test")
    older = datetime(2026, 7, 21, 8, 0, tzinfo=UTC)
    newer = datetime(2026, 7, 21, 9, 0, tzinfo=UTC)

    try:
        service.record(
            ObservationEnvelope(
                kind="step.started",
                occurred_at=older,
                task_id=projection_task_id,
                step_id=step_id,
                subject_type="step",
                subject_id=step_id,
                producer=producer,
                producer_seq=1,
                source_event_id="failed-job-merge:step:started",
                correlation_id=projection_task_id,
                payload={"step_seq": 1, "actor_kind": "lead_agent"},
            )
        )
        await service.flush_task(projection_task_id)

        service.record(
            ObservationEnvelope.task_lifecycle(
                kind="task.created",
                task_id=assessor_task_id,
                source_kind="deerflow_run",
                source_id="run-failed-job-merge",
                occurred_at=newer,
                source_event_id="failed-job-merge:task:created",
            )
        )
        await service.flush_task(assessor_task_id)
        async with session_factory() as session, session.begin():
            session.add(
                AnsichAssessorJobRow(
                    job_id=new_id(),
                    subject_id=assessor_task_id,
                    assessor_name="scope-safety",
                    assessor_version="1",
                    evidence_watermark=1,
                    status="failed",
                    attempts=2,
                    available_at=newer,
                    last_error="ValueError: forced for merge test",
                )
            )

        merged = await service.list_failed_jobs()
    finally:
        await service.stop()
        await engine.dispose()

    assert [job.kind for job in merged] == ["assessor", "projection"]
    assert merged[0].available_at >= merged[1].available_at
    assert {job.task_id for job in merged} == {assessor_task_id, projection_task_id}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. uv run pytest tests/ansich/test_failed_job_diagnostics.py -v`
Expected: FAIL with `AttributeError: 'AnsichService' object has no attribute 'list_failed_jobs'`

- [ ] **Step 3: Write minimal implementation**

In `backend/packages/harness/deerflow/ansich/persistence/sql.py`, add `AnsichAssessorErrorRow` import if not already present (it is — confirm `AnsichAssessorErrorRow` and `AnsichProjectionErrorRow` are both already in the `from deerflow.ansich.persistence.models import (...)` block at sql.py:146). Add `from ansich.jobs import FailedJobDetailView, FailedJobErrorView, FailedJobKind, FailedJobSummaryView` to the `from ansich import (...)` import block at the top of sql.py (alongside the other `ansich`-package imports).

Insert immediately after `retry_failed_projections` (right after the `return len(job_ids) + len(assessor_job_ids)` line, sql.py:1066):

```python
    async def list_failed_jobs(
        self,
        *,
        task_id: str | None = None,
        limit: int = 100,
    ) -> list[FailedJobSummaryView]:
        async with self._session_factory() as session:
            projection_stmt = (
                select(
                    AnsichProjectionJobRow.job_id,
                    AnsichProjectionJobRow.projector_name,
                    AnsichProjectionJobRow.projector_version,
                    AnsichProjectionJobRow.status,
                    AnsichProjectionJobRow.attempts,
                    AnsichProjectionJobRow.last_error,
                    AnsichProjectionJobRow.available_at,
                    AnsichObservationRow.task_id,
                )
                .join(AnsichObservationRow, AnsichObservationRow.obs_id == AnsichProjectionJobRow.obs_id)
                .where(AnsichProjectionJobRow.status == "failed")
            )
            if task_id is not None:
                projection_stmt = projection_stmt.where(AnsichObservationRow.task_id == task_id)
            projection_rows = (await session.execute(projection_stmt)).all()

            assessor_stmt = select(
                AnsichAssessorJobRow.job_id,
                AnsichAssessorJobRow.assessor_name,
                AnsichAssessorJobRow.assessor_version,
                AnsichAssessorJobRow.status,
                AnsichAssessorJobRow.attempts,
                AnsichAssessorJobRow.last_error,
                AnsichAssessorJobRow.available_at,
                AnsichAssessorJobRow.subject_id,
            ).where(AnsichAssessorJobRow.status == "failed")
            if task_id is not None:
                assessor_stmt = assessor_stmt.where(AnsichAssessorJobRow.subject_id == task_id)
            assessor_rows = (await session.execute(assessor_stmt)).all()

        summaries = [
            FailedJobSummaryView(
                job_id=row.job_id,
                kind="projection",
                name=row.projector_name,
                version=row.projector_version,
                task_id=row.task_id,
                status=row.status,
                attempts=row.attempts,
                last_error=row.last_error,
                available_at=row.available_at,
            )
            for row in projection_rows
        ] + [
            FailedJobSummaryView(
                job_id=row.job_id,
                kind="assessor",
                name=row.assessor_name,
                version=row.assessor_version,
                task_id=row.subject_id,
                status=row.status,
                attempts=row.attempts,
                last_error=row.last_error,
                available_at=row.available_at,
            )
            for row in assessor_rows
        ]
        summaries.sort(key=lambda item: (item.available_at, item.job_id), reverse=True)
        return summaries[:limit]

    async def get_failed_job_detail(
        self,
        *,
        job_id: str,
        kind: FailedJobKind,
    ) -> FailedJobDetailView | None:
        async with self._session_factory() as session:
            if kind == "projection":
                job = await session.get(AnsichProjectionJobRow, job_id)
                if job is None:
                    return None
                job_task_id = await session.scalar(
                    select(AnsichObservationRow.task_id).where(AnsichObservationRow.obs_id == job.obs_id)
                )
                name, version = job.projector_name, job.projector_version
                error_rows = (
                    await session.execute(
                        select(AnsichProjectionErrorRow)
                        .where(AnsichProjectionErrorRow.job_id == job_id)
                        .order_by(AnsichProjectionErrorRow.occurred_at)
                    )
                ).scalars()
            else:
                job = await session.get(AnsichAssessorJobRow, job_id)
                if job is None:
                    return None
                job_task_id = job.subject_id
                name, version = job.assessor_name, job.assessor_version
                error_rows = (
                    await session.execute(
                        select(AnsichAssessorErrorRow)
                        .where(AnsichAssessorErrorRow.job_id == job_id)
                        .order_by(AnsichAssessorErrorRow.occurred_at)
                    )
                ).scalars()
            return FailedJobDetailView(
                job_id=job.job_id,
                kind=kind,
                name=name,
                version=version,
                task_id=job_task_id,
                status=job.status,
                attempts=job.attempts,
                last_error=job.last_error,
                available_at=job.available_at,
                errors=tuple(
                    FailedJobErrorView(
                        attempt=error.attempt,
                        error_type=error.error_type,
                        message=error.message,
                        occurred_at=error.occurred_at,
                    )
                    for error in error_rows
                ),
            )
```

In `backend/packages/ansich/ansich/service.py`:
1. Add `from typing import Literal` to the top-level imports (this file currently has none — needed for the `kind` parameter type).
2. Add `from ansich.jobs import FailedJobDetailView, FailedJobKind, FailedJobSummaryView` next to the other `from ansich.* import ...` lines.
3. Insert immediately after `retry_failed_projections` (the method that delegates via `getattr(self._backend, "retry_failed_projections", None)`):

```python
    async def list_failed_jobs(
        self,
        *,
        task_id: str | None = None,
        limit: int = 100,
    ) -> list[FailedJobSummaryView]:
        list_failed = getattr(self._backend, "list_failed_jobs", None)
        if not callable(list_failed):
            return []
        return list(await list_failed(task_id=task_id, limit=limit))

    async def get_failed_job_detail(
        self,
        *,
        job_id: str,
        kind: FailedJobKind,
    ) -> FailedJobDetailView | None:
        get_detail = getattr(self._backend, "get_failed_job_detail", None)
        if not callable(get_detail):
            return None
        return await get_detail(job_id=job_id, kind=kind)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. uv run pytest tests/ansich/test_failed_job_diagnostics.py -v`
Expected: PASS (all tests from Task 1 and Task 2 — 3 + 3 = 6 passed)

- [ ] **Step 5: Run the full Ansich backend suite to check for regressions**

Run: `PYTHONPATH=. uv run pytest tests/ansich/ -v`
Expected: PASS (no pre-existing test broken by the new imports/methods)

- [ ] **Step 6: Commit**

```bash
git add backend/packages/harness/deerflow/ansich/persistence/sql.py backend/packages/ansich/ansich/service.py backend/tests/ansich/test_failed_job_diagnostics.py
git commit -m "feat(ansich): add failed-job list/detail queries to SQL backend and service"
```

---

### Task 3: Admin API routes — list, detail, retry

**Files:**
- Modify: `backend/app/gateway/routers/ansich.py` (add three routes right after `list_safety_events`, ansich.py:1280-1319)
- Modify: `backend/tests/ansich/test_ansich_router.py`

**Interfaces:**
- Consumes: `AnsichService.list_failed_jobs`, `AnsichService.get_failed_job_detail`, `AnsichService.retry_failed_projections` (existing) from Task 2.
- Produces: `GET /api/ansich/operations/failed-jobs`, `GET /api/ansich/operations/failed-jobs/{job_id}`, `POST /api/ansich/operations/failed-jobs/retry` — consumed by the frontend `api.ts` functions in Task 5.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/ansich/test_ansich_router.py`. First add these two imports at the top of the file (next to the existing ones):

```python
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from deerflow.ansich.persistence.models import Base
from deerflow.ansich.persistence.sql import SqlAnsichBackend
```

Then add:

```python
@pytest.mark.anyio
async def test_failed_jobs_endpoints_require_admin():
    service = AnsichService.in_memory()
    await service.start()
    app = make_authed_test_app(user_factory=regular_user)
    app.state.ansich_service = service
    app.include_router(ansich_router.router)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            list_response = await client.get("/api/ansich/operations/failed-jobs")
            detail_response = await client.get(
                f"/api/ansich/operations/failed-jobs/{new_id()}?kind=projection"
            )
            retry_response = await client.post("/api/ansich/operations/failed-jobs/retry")
    finally:
        await service.stop()

    assert list_response.status_code == 403
    assert detail_response.status_code == 403
    assert retry_response.status_code == 403


@pytest.mark.anyio
async def test_failed_job_detail_404_for_unknown_job():
    service = AnsichService.in_memory()
    await service.start()
    app = make_authed_test_app(user_factory=admin_user)
    app.state.ansich_service = service
    app.include_router(ansich_router.router)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(
                f"/api/ansich/operations/failed-jobs/{new_id()}?kind=projection"
            )
            list_response = await client.get("/api/ansich/operations/failed-jobs")
    finally:
        await service.stop()

    assert response.status_code == 404
    assert list_response.status_code == 200
    assert list_response.json()["items"] == []


@pytest.mark.anyio
async def test_failed_jobs_list_detail_and_retry_over_http(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-router-failed-jobs.db'}")

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    backend = SqlAnsichBackend(session_factory, projector_dependency_timeout_seconds=0)
    service = AnsichService(backend, flush_interval_ms=60_000)
    await service.start()
    task_id = new_id()
    step_id = new_id()
    producer = Producer(name="router-failed-job-test", version="1", instance_id="test")
    observed_at = datetime.now(UTC)
    app = make_authed_test_app(user_factory=admin_user)
    app.state.ansich_service = service
    app.include_router(ansich_router.router)

    try:
        service.record(
            ObservationEnvelope(
                kind="step.started",
                occurred_at=observed_at,
                task_id=task_id,
                step_id=step_id,
                subject_type="step",
                subject_id=step_id,
                producer=producer,
                producer_seq=1,
                source_event_id="router-failed-job:step:started",
                correlation_id=task_id,
                payload={"step_seq": 1, "actor_kind": "lead_agent"},
            )
        )
        await service.flush_task(task_id)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            list_response = await client.get(f"/api/ansich/operations/failed-jobs?task={task_id}")
            assert list_response.status_code == 200
            items = list_response.json()["items"]
            assert len(items) == 1
            job = items[0]
            assert job["kind"] == "projection"
            assert job["task_id"] == task_id

            detail_response = await client.get(
                f"/api/ansich/operations/failed-jobs/{job['job_id']}?kind=projection"
            )
            assert detail_response.status_code == 200
            assert detail_response.json()["job"]["errors"]

            service.record(
                ObservationEnvelope.task_lifecycle(
                    kind="task.created",
                    task_id=task_id,
                    source_kind="deerflow_run",
                    source_id="run-router-failed-job",
                    occurred_at=observed_at,
                    source_event_id="router-failed-job:task:created",
                )
            )
            await service.flush_task(task_id)
            retry_response = await client.post(f"/api/ansich/operations/failed-jobs/retry?task={task_id}")
            assert retry_response.status_code == 200
            assert retry_response.json()["retried"] == 1

            after_response = await client.get(f"/api/ansich/operations/failed-jobs?task={task_id}")
            assert after_response.json()["items"] == []
    finally:
        await service.stop()
        await engine.dispose()


@pytest.mark.anyio
async def test_failed_jobs_endpoints_503_when_storage_unavailable():
    service = create_embedded_ansich_service(AnsichConfig(enabled=True), None)
    assert service is not None
    await service.start()
    app = make_authed_test_app(user_factory=admin_user)
    app.state.ansich_service = service
    app.include_router(ansich_router.router)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            list_response = await client.get("/api/ansich/operations/failed-jobs")
            retry_response = await client.post("/api/ansich/operations/failed-jobs/retry")
    finally:
        await service.stop()

    assert list_response.status_code == 503
    assert retry_response.status_code == 503
```

`create_embedded_ansich_service` and `AnsichConfig` are already imported at the top of this file — no new imports needed for this test.

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. uv run pytest tests/ansich/test_ansich_router.py -k failed_job -v`
Expected: FAIL with 404 (no such route) on all new tests

- [ ] **Step 3: Write minimal implementation**

In `backend/app/gateway/routers/ansich.py`, insert immediately after the end of `list_safety_events` (right after its closing, ansich.py:1280-1319 — the function ends by returning the merged `pages`; find the exact return block and add these three routes right after it):

```python
@router.get("/operations/failed-jobs")
async def list_failed_jobs(
    request: Request,
    task_id: str | None = Query(default=None, alias="task"),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict:
    await require_admin_user(request, detail=_ADMIN_REQUIRED)
    service = _service_or_503(request)
    _ensure_queryable(service)
    try:
        jobs = await service.list_failed_jobs(task_id=task_id, limit=limit)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Ansich failed-job query failed",
                "projection_status": _projection_status(service),
            },
        ) from exc
    return {
        "items": [item.model_dump(mode="json") for item in jobs],
        "projection_status": _projection_status(service),
    }


@router.get("/operations/failed-jobs/{job_id}")
async def get_failed_job_detail(
    job_id: str,
    request: Request,
    kind: Literal["projection", "assessor"] = Query(...),
) -> dict:
    await require_admin_user(request, detail=_ADMIN_REQUIRED)
    service = _service_or_503(request)
    _ensure_queryable(service)
    try:
        detail = await service.get_failed_job_detail(job_id=job_id, kind=kind)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Ansich failed-job detail query failed",
                "projection_status": _projection_status(service),
            },
        ) from exc
    if detail is None:
        raise HTTPException(status_code=404, detail="Ansich failed job not found")
    return {
        "job": detail.model_dump(mode="json"),
        "projection_status": _projection_status(service),
    }


@router.post("/operations/failed-jobs/retry")
async def retry_failed_jobs(
    request: Request,
    task_id: str | None = Query(default=None, alias="task"),
) -> dict:
    await require_admin_user(request, detail=_ADMIN_REQUIRED)
    service = _service_or_503(request)
    _ensure_queryable(service)
    try:
        retried = await service.retry_failed_projections(task_id=task_id)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Ansich failed-job retry failed",
                "projection_status": _projection_status(service),
            },
        ) from exc
    return {
        "retried": retried,
        "projection_status": _projection_status(service),
    }
```

Note: this file already imports `Query`, `HTTPException`, `Request`, `Literal`, `require_admin_user` — no new imports needed.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. uv run pytest tests/ansich/test_ansich_router.py -k failed_job -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Run the full router test file to check for regressions**

Run: `PYTHONPATH=. uv run pytest tests/ansich/test_ansich_router.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/gateway/routers/ansich.py backend/tests/ansich/test_ansich_router.py
git commit -m "feat(ansich): expose failed-job list/detail/retry over HTTP"
```

---

### Task 4: Frontend types

**Files:**
- Modify: `frontend/src/core/ansich/types.ts` (insert after the `AnsichHealth` interface, types.ts:114-139)

**Interfaces:**
- Produces: `AnsichFailedJobKind`, `AnsichFailedJob`, `AnsichFailedJobError`, `AnsichFailedJobDetail`, `AnsichFailedJobsResponse`, `AnsichFailedJobDetailResponse`, `AnsichFailedJobsRetryResponse` — consumed by Tasks 5, 6, 8.

This task has no automated test (pure type declarations); it is verified by `pnpm typecheck` succeeding once Task 5 references these types. No commit yet — bundle with Task 5's commit since an unused type-only file addition on its own has nothing to verify.

- [ ] **Step 1: Add the types**

Insert immediately after the closing `}` of `AnsichHealth` (types.ts:139) and before `export interface AnsichTaskListResponse {` (types.ts:141):

```typescript
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
  retried: number;
  projection_status: AnsichHealth;
}

```

- [ ] **Step 2: Verify no syntax errors**

Run (from `frontend/`): `pnpm typecheck`
Expected: PASS (these new types are unused so far, which is fine — `noUnusedLocals` does not flag unused exported types)

(No commit — proceed directly to Task 5, which uses these types and commits both files together.)

---

### Task 5: Frontend `api.ts` functions + unit tests

**Files:**
- Modify: `frontend/src/core/ansich/api.ts` (add three functions after `dismissAnsichAlert`, api.ts:253-259)
- Test: Create `frontend/tests/unit/core/ansich/api-failed-jobs.test.ts`

**Interfaces:**
- Consumes: `AnsichFailedJobKind`, `AnsichFailedJobsResponse`, `AnsichFailedJobDetailResponse`, `AnsichFailedJobsRetryResponse` (Task 4).
- Produces: `fetchAnsichFailedJobs(taskId?: string, limit?: number): Promise<AnsichFailedJobsResponse>`, `fetchAnsichFailedJobDetail(jobId: string, kind: AnsichFailedJobKind): Promise<AnsichFailedJobDetailResponse>`, `retryAnsichFailedJobs(taskId?: string): Promise<AnsichFailedJobsRetryResponse>` — consumed by Task 6.

First, check how existing tests in this directory mock `fetch` and `getBackendBaseURL` (read `frontend/tests/unit/core/ansich/presentation.test.ts` and any existing `api*.test.ts` in that directory, if one exists, for the exact mocking pattern before writing Step 1 — if no `api.ts`-level test file exists yet in `tests/unit/core/ansich/`, mirror the mocking style used by another `core/*/api.test.ts` file elsewhere in the repo that mocks `@/core/api/fetcher`).

- [ ] **Step 1: Write the failing test**

Create `frontend/tests/unit/core/ansich/api-failed-jobs.test.ts`:

```typescript
import { describe, expect, it, vi, beforeEach } from "vitest";

vi.mock("@/core/config", () => ({
  getBackendBaseURL: () => "http://backend.test",
}));

const fetchMock = vi.fn();
vi.mock("@/core/api/fetcher", () => ({
  fetch: (...args: unknown[]) => fetchMock(...args),
}));

import {
  fetchAnsichFailedJobDetail,
  fetchAnsichFailedJobs,
  retryAnsichFailedJobs,
} from "@/core/ansich/api";

describe("ansich failed-job api", () => {
  beforeEach(() => {
    fetchMock.mockReset();
  });

  it("fetchAnsichFailedJobs omits the task filter when taskId is not given", async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({ items: [], projection_status: {} }),
    });
    await fetchAnsichFailedJobs();
    const [url] = fetchMock.mock.calls[0] as [string];
    expect(url).toBe(
      "http://backend.test/api/ansich/operations/failed-jobs?limit=100",
    );
  });

  it("fetchAnsichFailedJobs includes the task filter when taskId is given", async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({ items: [], projection_status: {} }),
    });
    await fetchAnsichFailedJobs("task-1", 50);
    const [url] = fetchMock.mock.calls[0] as [string];
    expect(url).toBe(
      "http://backend.test/api/ansich/operations/failed-jobs?limit=50&task=task-1",
    );
  });

  it("fetchAnsichFailedJobDetail requests the given job id and kind", async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({ job: {}, projection_status: {} }),
    });
    await fetchAnsichFailedJobDetail("job-1", "assessor");
    const [url] = fetchMock.mock.calls[0] as [string];
    expect(url).toBe(
      "http://backend.test/api/ansich/operations/failed-jobs/job-1?kind=assessor",
    );
  });

  it("retryAnsichFailedJobs POSTs without a query string when global", async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({ retried: 0, projection_status: {} }),
    });
    await retryAnsichFailedJobs();
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://backend.test/api/ansich/operations/failed-jobs/retry");
    expect(init.method).toBe("POST");
  });

  it("retryAnsichFailedJobs POSTs with the task filter when scoped", async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({ retried: 1, projection_status: {} }),
    });
    await retryAnsichFailedJobs("task-1");
    const [url] = fetchMock.mock.calls[0] as [string];
    expect(url).toBe(
      "http://backend.test/api/ansich/operations/failed-jobs/retry?task=task-1",
    );
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `frontend/`): `pnpm test tests/unit/core/ansich/api-failed-jobs.test.ts`
Expected: FAIL — `fetchAnsichFailedJobs` etc. are not exported from `@/core/ansich/api`

- [ ] **Step 3: Write minimal implementation**

In `frontend/src/core/ansich/api.ts`, add `AnsichFailedJobDetailResponse`, `AnsichFailedJobKind`, `AnsichFailedJobsResponse`, `AnsichFailedJobsRetryResponse` to the existing `import type { ... } from "./types";` block. Then insert these three functions right after `dismissAnsichAlert` (api.ts:253-259):

```typescript
export async function fetchAnsichFailedJobs(
  taskId?: string,
  limit = 100,
): Promise<AnsichFailedJobsResponse> {
  const query = new URLSearchParams({ limit: String(limit) });
  if (taskId) query.set("task", taskId);
  const response = await fetch(
    ansichUrl(`/operations/failed-jobs?${query.toString()}`),
  );
  if (!response.ok) {
    await throwAnsichApiError(
      response,
      `Failed to load Ansich failed jobs: ${response.statusText}`,
    );
  }
  return response.json();
}

export async function fetchAnsichFailedJobDetail(
  jobId: string,
  kind: AnsichFailedJobKind,
): Promise<AnsichFailedJobDetailResponse> {
  const query = new URLSearchParams({ kind });
  const response = await fetch(
    ansichUrl(
      `/operations/failed-jobs/${encodeURIComponent(jobId)}?${query.toString()}`,
    ),
  );
  if (!response.ok) {
    await throwAnsichApiError(
      response,
      `Failed to load Ansich failed job detail: ${response.statusText}`,
    );
  }
  return response.json();
}

export async function retryAnsichFailedJobs(
  taskId?: string,
): Promise<AnsichFailedJobsRetryResponse> {
  const query = new URLSearchParams();
  if (taskId) query.set("task", taskId);
  const suffix = query.toString() ? `?${query.toString()}` : "";
  const response = await fetch(ansichUrl(`/operations/failed-jobs/retry${suffix}`), {
    method: "POST",
  });
  if (!response.ok) {
    await throwAnsichApiError(
      response,
      `Failed to retry Ansich failed jobs: ${response.statusText}`,
    );
  }
  return response.json();
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pnpm test tests/unit/core/ansich/api-failed-jobs.test.ts`
Expected: PASS (5 passed)

- [ ] **Step 5: Typecheck**

Run: `pnpm typecheck`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add frontend/src/core/ansich/types.ts frontend/src/core/ansich/api.ts frontend/tests/unit/core/ansich/api-failed-jobs.test.ts
git commit -m "feat(ansich): add failed-job frontend API client"
```

---

### Task 6: Frontend TanStack Query hooks

**Files:**
- Modify: `frontend/src/core/ansich/hooks.ts` (add three hooks after `useAnsichAlertWorkflow`, hooks.ts:125-152)

**Interfaces:**
- Consumes: `fetchAnsichFailedJobs`, `fetchAnsichFailedJobDetail`, `retryAnsichFailedJobs` (Task 5).
- Produces: `useAnsichFailedJobs(taskId: string | undefined, limit?: number, enabled?: boolean)`, `useAnsichFailedJobDetail(jobId: string, kind: AnsichFailedJobKind, enabled?: boolean)`, `useAnsichRetryFailedJobs()` — consumed by Task 8's `AnsichFailedJobsDialog`.

**No dedicated hook-level test for this task** (plan correction made during execution, 2026-07-21): this repo has no `@testing-library/react` dependency and no existing hook in `hooks.ts` has a dedicated unit test — every hook is a thin `useQuery`/`useMutation` wrapper around an already-unit-tested `api.ts` function, verified indirectly through `pnpm typecheck` (hooks compile against the real function signatures and TanStack Query generics) and later through Task 8's manual UI verification. Treat this task like Task 4 (types-only, typecheck-verified, no test file) rather than writing a new hook-testing harness for one feature.

- [ ] **Step 1: Write the implementation**

In `frontend/src/core/ansich/hooks.ts`:
1. Add `fetchAnsichFailedJobDetail`, `fetchAnsichFailedJobs`, `retryAnsichFailedJobs` to the `import { ... } from "./api";` block.
2. Add `AnsichFailedJobKind` to the `import type { ... } from "./types";` block.
3. Insert right after `useAnsichAlertWorkflow` (hooks.ts:125-152):

```typescript
export function useAnsichFailedJobs(
  taskId: string | undefined,
  limit = 100,
  enabled = true,
) {
  return useQuery({
    queryKey: [
      "ansich",
      "operations",
      "failed-jobs",
      taskId ?? null,
      { limit },
    ],
    queryFn: () => fetchAnsichFailedJobs(taskId, limit),
    enabled,
    retry: false,
  });
}

export function useAnsichFailedJobDetail(
  jobId: string,
  kind: AnsichFailedJobKind,
  enabled = true,
) {
  return useQuery({
    queryKey: ["ansich", "operations", "failed-jobs", jobId, kind],
    queryFn: () => fetchAnsichFailedJobDetail(jobId, kind),
    enabled: enabled && Boolean(jobId),
    retry: false,
  });
}

export function useAnsichRetryFailedJobs() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { taskId?: string }) =>
      retryAnsichFailedJobs(input.taskId),
    onSettled: async () => {
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["ansich", "operations", "failed-jobs"],
        }),
        queryClient.invalidateQueries({
          queryKey: ["ansich", "operations", "active-tasks"],
        }),
        queryClient.invalidateQueries({ queryKey: ["ansich", "tasks"] }),
      ]);
    },
  });
}
```

- [ ] **Step 2: Typecheck**

Run: `pnpm typecheck`
Expected: PASS

- [ ] **Step 3: Lint**

Run: `pnpm lint`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add frontend/src/core/ansich/hooks.ts
git commit -m "feat(ansich): add failed-job TanStack Query hooks"
```

---

### Task 7: i18n strings (en-US, zh-CN, types)

**Files:**
- Modify: `frontend/src/core/i18n/locales/types.ts` (insert after `failedJobs: string;`, types.ts:362)
- Modify: `frontend/src/core/i18n/locales/en-US.ts` (insert after `failedJobs: "Failed jobs",`, en-US.ts:449)
- Modify: `frontend/src/core/i18n/locales/zh-CN.ts` (insert after `failedJobs: "失败任务",`, zh-CN.ts:434)

**Interfaces:**
- Produces: `t.ansich.failedJobsDialogTitle`, `t.ansich.failedJobsDialogDescriptionGlobal`, `t.ansich.failedJobsDialogDescriptionTask`, `t.ansich.failedJobsEmpty`, `t.ansich.failedJobKindLabel.{projection,assessor}`, `t.ansich.failedJobAttempts`, `t.ansich.failedJobRetryTask` — consumed by Task 8.

No dedicated test — i18n key-shape consistency across all three locale files is enforced by `pnpm typecheck` (a locale object missing a key declared in `types.ts` fails to satisfy the `Locale` type).

- [ ] **Step 1: Add the type declarations**

In `frontend/src/core/i18n/locales/types.ts`, insert right after `failedJobs: string;` (line 362):

```typescript
    failedJobsDialogTitle: string;
    failedJobsDialogDescriptionGlobal: string;
    failedJobsDialogDescriptionTask: string;
    failedJobsEmpty: string;
    failedJobKindLabel: Record<"projection" | "assessor", string>;
    failedJobAttempts: string;
    failedJobRetryTask: string;
```

- [ ] **Step 2: Add the English strings**

In `frontend/src/core/i18n/locales/en-US.ts`, insert right after `failedJobs: "Failed jobs",` (line 449):

```typescript
    failedJobsDialogTitle: "Failed jobs",
    failedJobsDialogDescriptionGlobal:
      "Projection and assessor jobs that are currently failing across all Tasks.",
    failedJobsDialogDescriptionTask:
      "Projection and assessor jobs that are currently failing for this Task.",
    failedJobsEmpty: "No failed jobs.",
    failedJobKindLabel: {
      projection: "Projection job",
      assessor: "Assessor job",
    },
    failedJobAttempts: "Attempts",
    failedJobRetryTask: "Retry all failed jobs for this Task",
```

- [ ] **Step 3: Add the Chinese strings**

In `frontend/src/core/i18n/locales/zh-CN.ts`, insert right after `failedJobs: "失败任务",` (line 434):

```typescript
    failedJobsDialogTitle: "失败 Job",
    failedJobsDialogDescriptionGlobal: "当前所有 Task 中正在失败的投影与评估 Job。",
    failedJobsDialogDescriptionTask: "当前这个 Task 正在失败的投影与评估 Job。",
    failedJobsEmpty: "没有失败的 Job。",
    failedJobKindLabel: {
      projection: "投影 Job",
      assessor: "评估 Job",
    },
    failedJobAttempts: "尝试次数",
    failedJobRetryTask: "重试该 Task 全部失败 Job",
```

- [ ] **Step 4: Verify all three locale files still type-check against each other**

Run: `pnpm typecheck`
Expected: PASS (would fail with a type error naming the missing key in whichever locale file forgot it)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/core/i18n/locales/types.ts frontend/src/core/i18n/locales/en-US.ts frontend/src/core/i18n/locales/zh-CN.ts
git commit -m "feat(ansich): add i18n strings for failed-job diagnostics"
```

---

### Task 8: `AnsichFailedJobsDialog` component + wiring into `AnsichProjectionHealth` and both pages

**Files:**
- Create: `frontend/src/components/workspace/ansich/failed-jobs-dialog.tsx`
- Modify: `frontend/src/components/workspace/ansich/projection-health.tsx` (whole file — add state, make the `failedJobs` metric clickable, render the dialog)
- Modify: `frontend/src/components/workspace/ansich/index.ts` (export the new component)
- Modify: `frontend/src/app/workspace/ansich/tasks/[task_id]/page.tsx:120` (pass `taskId`)

**Interfaces:**
- Consumes: `useAnsichFailedJobs`, `useAnsichFailedJobDetail`, `useAnsichRetryFailedJobs` (Task 6); `AnsichFailedJob` (Task 4); `t.ansich.failedJobs*` / `t.ansich.failedJobKindLabel` / `t.ansich.failedJobAttempts` / `t.ansich.failedJobRetryTask` (Task 7); `formatAnsichTimestamp` from `@/core/ansich/presentation` (existing, used by `alert-panel.tsx`).
- Produces: `AnsichFailedJobsDialog({ open, onOpenChange, taskId }: { open: boolean; onOpenChange: (open: boolean) => void; taskId?: string })`, exported from `components/workspace/ansich/index.ts`.

No new automated test for this task (component-level tests are out of scope for this feature per the Global Constraints); verified manually per Step 4 below.

- [ ] **Step 1: Create the dialog component**

Create `frontend/src/components/workspace/ansich/failed-jobs-dialog.tsx`:

```tsx
"use client";

import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import {
  useAnsichFailedJobDetail,
  useAnsichFailedJobs,
  useAnsichRetryFailedJobs,
} from "@/core/ansich/hooks";
import { formatAnsichTimestamp } from "@/core/ansich/presentation";
import type { AnsichFailedJob } from "@/core/ansich/types";
import { useI18n } from "@/core/i18n/hooks";

export function AnsichFailedJobsDialog({
  open,
  onOpenChange,
  taskId,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  taskId?: string;
}) {
  const { t } = useI18n();
  const jobsQuery = useAnsichFailedJobs(taskId, 100, open);
  const retryMutation = useAnsichRetryFailedJobs();
  const [expandedJobId, setExpandedJobId] = useState<string | null>(null);
  const jobs = jobsQuery.data?.items ?? [];
  const failingTaskIds = Array.from(new Set(jobs.map((job) => job.task_id)));

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[80vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t.ansich.failedJobsDialogTitle}</DialogTitle>
          <DialogDescription>
            {taskId
              ? t.ansich.failedJobsDialogDescriptionTask
              : t.ansich.failedJobsDialogDescriptionGlobal}
          </DialogDescription>
        </DialogHeader>
        {jobsQuery.isPending ? (
          <Skeleton className="h-32 w-full" />
        ) : jobs.length === 0 ? (
          <p className="text-muted-foreground text-sm">
            {t.ansich.failedJobsEmpty}
          </p>
        ) : (
          <div className="space-y-2">
            {taskId ? (
              <Button
                size="sm"
                variant="outline"
                disabled={retryMutation.isPending}
                onClick={() => retryMutation.mutate({ taskId })}
              >
                {t.ansich.failedJobRetryTask}
              </Button>
            ) : (
              <div className="flex flex-wrap gap-2">
                {failingTaskIds.map((id) => (
                  <Button
                    key={id}
                    size="sm"
                    variant="outline"
                    disabled={retryMutation.isPending}
                    onClick={() => retryMutation.mutate({ taskId: id })}
                  >
                    {t.ansich.failedJobRetryTask} · {id.slice(0, 8)}
                  </Button>
                ))}
              </div>
            )}
            {jobs.map((job) => (
              <FailedJobRow
                key={job.job_id}
                job={job}
                expanded={expandedJobId === job.job_id}
                onToggle={() =>
                  setExpandedJobId((current) =>
                    current === job.job_id ? null : job.job_id,
                  )
                }
              />
            ))}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

function FailedJobRow({
  job,
  expanded,
  onToggle,
}: {
  job: AnsichFailedJob;
  expanded: boolean;
  onToggle: () => void;
}) {
  const { t } = useI18n();
  const detailQuery = useAnsichFailedJobDetail(job.job_id, job.kind, expanded);
  return (
    <div className="rounded-lg border p-3">
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center justify-between gap-3 text-left"
      >
        <span className="min-w-0">
          <span className="block truncate text-sm font-medium">
            {job.name}@{job.version}
          </span>
          <span className="text-muted-foreground mt-1 block text-xs">
            {t.ansich.failedJobKindLabel[job.kind]} · {t.ansich.task}{" "}
            {job.task_id.slice(0, 8)} · {t.ansich.failedJobAttempts}:{" "}
            {job.attempts}
          </span>
        </span>
        <Badge variant="outline">
          {formatAnsichTimestamp(job.available_at)}
        </Badge>
      </button>
      {job.last_error ? (
        <p className="text-destructive mt-2 truncate text-xs">
          {job.last_error}
        </p>
      ) : null}
      {expanded ? (
        <div className="mt-2 space-y-1 border-t pt-2">
          {detailQuery.isPending ? (
            <Skeleton className="h-16 w-full" />
          ) : (
            (detailQuery.data?.job.errors ?? []).map((error, index) => (
              <div key={index} className="text-xs">
                <span className="font-medium">
                  {t.ansich.failedJobAttempts} #{error.attempt} ·{" "}
                  {formatAnsichTimestamp(error.occurred_at)}
                </span>
                <p className="text-muted-foreground">
                  {error.error_type}: {error.message}
                </p>
              </div>
            ))
          )}
        </div>
      ) : null}
    </div>
  );
}
```

- [ ] **Step 2: Wire the dialog into `AnsichProjectionHealth`**

In `frontend/src/components/workspace/ansich/projection-health.tsx`:

Add `import { useState } from "react";` at the very top, and `import { AnsichFailedJobsDialog } from "./failed-jobs-dialog";` after the existing imports.

Change the function signature and add the open-state:

```tsx
export function AnsichProjectionHealth({
  health,
  taskId,
}: {
  health: AnsichHealth;
  taskId?: string;
}) {
  const { t } = useI18n();
  const lostCount = countLostObservations(health.lost_ranges);
  const unhealthy = health.status !== "healthy";
  const [failedJobsOpen, setFailedJobsOpen] = useState(false);
```

Replace the existing failed-jobs metric:

```tsx
        <HealthMetric
          label={t.ansich.failedJobs}
          value={String(health.failed_jobs)}
        />
```

with:

```tsx
        <button
          type="button"
          onClick={() => setFailedJobsOpen(true)}
          disabled={health.failed_jobs === 0}
          className="flex items-baseline gap-2 text-sm disabled:cursor-default"
        >
          <span className="text-muted-foreground">{t.ansich.failedJobs}</span>
          <span
            className={
              health.failed_jobs > 0
                ? "text-destructive font-mono font-medium tabular-nums underline"
                : "font-mono font-medium tabular-nums"
            }
          >
            {health.failed_jobs}
          </span>
        </button>
```

Add the dialog right after the closing `</Card>` (before the function's closing brace):

```tsx
      <AnsichFailedJobsDialog
        open={failedJobsOpen}
        onOpenChange={setFailedJobsOpen}
        taskId={taskId}
      />
```

- [ ] **Step 3: Export the new component and wire the Task detail page**

In `frontend/src/components/workspace/ansich/index.ts`, add:

```typescript
export { AnsichFailedJobsDialog } from "./failed-jobs-dialog";
```

In `frontend/src/app/workspace/ansich/tasks/[task_id]/page.tsx`, change line 120 from:

```tsx
              {health && <AnsichProjectionHealth health={health} />}
```

to:

```tsx
              {health && <AnsichProjectionHealth health={health} taskId={taskId} />}
```

(`frontend/src/app/workspace/ansich/operations/page.tsx:101` is left unchanged — no `taskId` prop, so the dialog opens in its global, unscoped mode there, matching the approved design.)

- [ ] **Step 4: Manual verification**

Run `pnpm dev` (or use the repo's `run` skill if available), sign in as an admin, navigate to a Task detail page and to `/workspace/ansich/operations`. Confirm:
- The "Failed jobs" metric renders as a disabled, non-underlined `0` when there are no failed jobs.
- With at least one failed job present (can be produced by the backend test technique — pointing a `step.started` observation at a nonexistent Task with `projector_dependency_timeout_seconds=0` — or by waiting for a real failure in a dev environment), the metric becomes clickable and underlined, and clicking it opens the dialog with the job listed, expandable to show its error history, with a working retry button that closes out the row once retried.
- The Task detail page's dialog only shows jobs for that Task; the Operations page's dialog shows jobs across Tasks with one retry button per Task.

- [ ] **Step 5: Typecheck and lint**

Run: `pnpm typecheck && pnpm lint`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/workspace/ansich/failed-jobs-dialog.tsx frontend/src/components/workspace/ansich/projection-health.tsx frontend/src/components/workspace/ansich/index.ts frontend/src/app/workspace/ansich/tasks/\[task_id\]/page.tsx
git commit -m "feat(ansich): add failed-job drill-down dialog to projection health"
```

---

### Task 9: Docs — close out U3, update AGENTS.md

**Files:**
- Modify: `ansich/docs/plans/human-followups.md` (status table row + U3 section)
- Modify: `backend/AGENTS.md` (Ansich router table row)
- Modify: `frontend/AGENTS.md` (Ansich UI paragraph)

**Interfaces:** None (documentation only).

- [ ] **Step 1: Mark U3 fixed in the status table**

In `ansich/docs/plans/human-followups.md`, change the U3 row (line 13) from:

```
| U3 | 投影 Degraded 无 failed jobs 细节，无法下钻排查 | ⬜ 未修复 | 可提前，建议随 Phase 9 顺带或独立小迭代 | — | — |
```

to (leave the "施工时机归属" column text as-is, add 修复时间/Commit — use today's date and the actual commit hash from Task 8's commit once known):

```
| U3 | 投影 Degraded 无 failed jobs 细节，无法下钻排查 | ✅ 已修复 | 可提前，建议随 Phase 9 顺带或独立小迭代 | 2026-07-21 | 见 U3 小节 |
```

- [ ] **Step 2: Update the U3 section body**

In `ansich/docs/plans/human-followups.md`, change the U3 section's 状态 line (line 39, `- 状态：⬜ 未修复。`) to:

```
- 状态：✅ 已修复（2026-07-21）。新增 `AnsichService.list_failed_jobs`/`get_failed_job_detail`（`backend/packages/harness/deerflow/ansich/persistence/sql.py`、`backend/packages/ansich/ansich/service.py`）与三个 admin-only 路由 `GET /operations/failed-jobs`、`GET /operations/failed-jobs/{job_id}`、`POST /operations/failed-jobs/retry`（后者首次把已存在的 `retry_failed_projections` 暴露到 HTTP）；`ProjectionHealth` 的 `failed_jobs` 指标在非零时可点击，打开 `AnsichFailedJobsDialog`——Task 详情页按 taskId 过滤，Operations 页显示全局列表且按 Task 分组重试。详情展开显示 `AnsichProjectionErrorRow`/`AnsichAssessorErrorRow` 的完整 attempt 错误历史（不受重试清除影响）。重试保持按 Task 批量粒度，未做单 job 精确重试。设计文档：`docs/superpowers/specs/2026-07-21-ansich-failed-jobs-diagnostics-design.md`。
```

- [ ] **Step 3: Update `backend/AGENTS.md`**

In `backend/AGENTS.md`'s Routers table, find the **Ansich** row and append one clause before its closing `|`, right after the existing "Alert list/detail plus interrupt/rollback proxy actions" language — add: `Failed-job diagnostics (\`GET/POST /operations/failed-jobs*\`) list and detail currently-failing projection/assessor jobs with their full attempt-error history and support Task-batch retry (first HTTP exposure of the existing non-destructive \`retry_failed_projections\`).` Insert it as an additional sentence within that cell, keeping the row as a single table line (no literal newline inside the Markdown table cell).

- [ ] **Step 4: Update `frontend/AGENTS.md`**

In `frontend/AGENTS.md`'s Ansich section (the long paragraph beginning "Ansich is deliberately separate from chat state..."), add one sentence after the existing "Projection health also renders queue count/byte capacity and both high-watermarks, plus snapshot request/item/incomplete/missing counters." line: `When \`failed_jobs\` is non-zero the metric is clickable and opens \`AnsichFailedJobsDialog\`, which lists currently-failing projection/assessor jobs (Task-scoped on the Task detail page, global with per-Task retry grouping on the Operations page) and lazily fetches each job's full attempt-error history on expand.`

- [ ] **Step 5: Commit**

```bash
git add ansich/docs/plans/human-followups.md backend/AGENTS.md frontend/AGENTS.md
git commit -m "docs(ansich): close U3 failed-job diagnostics follow-up"
```

---

### Task 10: Final verification

**Files:** None (verification only).

- [ ] **Step 1: Full backend Ansich suite**

Run (from `backend/`): `PYTHONPATH=. uv run pytest tests/ansich/ tests/test_task_tool_core_logic.py -v`
Expected: PASS, no regressions

- [ ] **Step 2: Full backend lint**

Run: `cd backend && make lint`
Expected: PASS (ruff clean)

- [ ] **Step 3: Full backend test suite (optional but recommended given cross-cutting router/service changes)**

Run: `cd backend && make test`
Expected: PASS

- [ ] **Step 4: Frontend unit tests**

Run: `cd frontend && pnpm test`
Expected: PASS, no regressions

- [ ] **Step 5: Frontend lint + typecheck**

Run: `cd frontend && pnpm check`
Expected: PASS

- [ ] **Step 6: Report back to the user**

Summarize: all 9 implementation tasks done, U3 closed, list of files touched, and confirmation that `make test` / `pnpm check` both pass. Do not create a PR or push unless the user asks.
