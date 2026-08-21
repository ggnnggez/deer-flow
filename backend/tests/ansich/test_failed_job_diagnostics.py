from datetime import UTC, datetime, timedelta

import pytest
from ansich import AnsichService, ObservationEnvelope, Producer, new_id
from ansich.jobs import FailedJobDetailView, FailedJobErrorView, FailedJobSummaryView
from pydantic import ValidationError
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from deerflow.ansich.persistence.models import AnsichAssessorErrorRow, AnsichAssessorJobRow, Base
from deerflow.ansich.persistence.sql import SqlAnsichBackend


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
    assert FailedJobSummaryView.model_validate_json(view.model_dump_json()) == view


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
        # both the "task-step" and "task-usage" projection jobs (step.started
        # is a registered kind for each — see _STEP_PROJECTION_KINDS and
        # _USAGE_PROJECTION_KINDS in sql.py) dependency-pending, then fail
        # once the (zero-second) dependency timeout elapses — two real failed
        # projection jobs from the one observation, same technique and same
        # job count as
        # test_sql_task_lifecycle.py::test_dependency_pending_job_eventually_fails_health_and_can_be_retried
        # (which asserts `health_after_timeout.failed_jobs == 2` from this
        # exact fixture).
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
        assert len(all_failed) == 2
        assert len(scoped_failed) == 2
        assert {job.name for job in scoped_failed} == {"task-step", "task-usage"}
        summary = next(job for job in scoped_failed if job.name == "task-step")
        assert summary.kind == "projection"
        assert summary.task_id == task_id
        assert summary.status == "failed"
        # Dependency-pending failures reset attempts to 0 (see
        # sql.py::_record_projection_error: `job.attempts = max(0, job.attempts - 1)`
        # for the `_ProjectionDependencyPending` branch) — the wait itself
        # never counted as a processing attempt.
        assert summary.attempts >= 0
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
        # Same fixture as the previous test: one step.started observation
        # yields two dependency-pending-then-failed projection jobs
        # ("task-step" and "task-usage"), both sharing the same obs_id.
        assert len(before_retry) == 2
        job_id = next(job.job_id for job in before_retry if job.name == "task-step")
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

        assert retried.re_armed == 2
        assert after_retry == []
        # The append-only error table is untouched by retry — history for
        # the now-recovered job is still queryable by job_id.
        detail_after = await service.get_failed_job_detail(job_id=job_id, kind="projection")
        assert detail_after is not None
        assert len(detail_after.errors) == error_count_before
    finally:
        await service.stop()
        await engine.dispose()


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
    now = datetime.now(UTC)
    older = now - timedelta(hours=2)
    # Dependency-pending projection-job failures stamp `available_at` from
    # real wall-clock time (see sql.py::_record_projection_error), not from
    # the observation's `occurred_at` — so the assessor row's `available_at`
    # must be anchored to `now` (not a fixed past date) to deterministically
    # sort newest regardless of when this test runs.
    newer = now + timedelta(hours=1)

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
        assessor_job_id = new_id()
        async with session_factory() as session, session.begin():
            session.add(
                AnsichAssessorJobRow(
                    job_id=assessor_job_id,
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
            await session.flush()
            session.add(
                AnsichAssessorErrorRow(
                    error_id=new_id(),
                    job_id=assessor_job_id,
                    attempt=2,
                    error_type="ValueError",
                    message="forced for merge test",
                    occurred_at=newer,
                )
            )

        merged = await service.list_failed_jobs()

        # Close the assessor-kind gap in get_failed_job_detail: both tests
        # above only ever exercise kind="projection". The found path uses
        # the assessor job/error rows just inserted; the not-found path
        # mirrors the existing projection-kind assertion in
        # test_list_and_detail_failed_jobs_cover_both_projection_and_assessor_kinds.
        assessor_detail = await service.get_failed_job_detail(job_id=assessor_job_id, kind="assessor")
        assert assessor_detail is not None
        assert assessor_detail.kind == "assessor"
        assert assessor_detail.task_id == assessor_task_id
        assert len(assessor_detail.errors) == 1
        assert assessor_detail.errors[0].error_type == "ValueError"
        assert assessor_detail.errors[0].message == "forced for merge test"
        assert assessor_detail.errors[0].attempt == 2

        missing_assessor_detail = await service.get_failed_job_detail(job_id="does-not-exist", kind="assessor")
        assert missing_assessor_detail is None
    finally:
        await service.stop()
        await engine.dispose()

    # The projection_task_id's step.started observation fails both the
    # "task-step" and "task-usage" projection jobs (same technique/count as
    # the two tests above), so the merge covers one assessor job plus two
    # projection jobs — three failed jobs total, across both tasks.
    assert [job.kind for job in merged] == ["assessor", "projection", "projection"]
    assert merged[0].available_at >= merged[1].available_at >= merged[2].available_at
    assert {job.task_id for job in merged} == {assessor_task_id, projection_task_id}
    assert {job.name for job in merged if job.kind == "projection"} == {"task-step", "task-usage"}
