from datetime import UTC, datetime

import pytest
from ansich.jobs import FailedJobDetailView, FailedJobErrorView, FailedJobSummaryView
from pydantic import ValidationError


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
