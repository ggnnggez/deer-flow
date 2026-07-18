from datetime import UTC, datetime, timedelta

from ansich.heartbeat import TaskHeartbeatView
from ansich.operations import assess_dwell, assess_heartbeat


def _heartbeat(observed_at: datetime) -> TaskHeartbeatView:
    return TaskHeartbeatView(
        task_id="00000000-0000-4000-8000-000000000001",
        heartbeat_obs_id="00000000-0000-4000-8000-000000000002",
        occurred_at=observed_at,
        producer_instance_id="producer-a",
        ownership_epoch="worker-a",
        elapsed_ms=10_000,
    )


def test_heartbeat_becomes_stale_only_after_the_configured_boundary():
    observed_at = datetime(2026, 7, 18, 10, 20, tzinfo=UTC)
    heartbeat = _heartbeat(observed_at)

    at_boundary = assess_heartbeat(
        heartbeat,
        now=observed_at + timedelta(seconds=30),
        stale_after_seconds=30,
    )
    after_boundary = assess_heartbeat(
        heartbeat,
        now=observed_at + timedelta(seconds=30, microseconds=1),
        stale_after_seconds=30,
    )

    assert at_boundary.value == "fresh"
    assert after_boundary.value == "stale"
    assert after_boundary.evidence_obs_ids == (heartbeat.heartbeat_obs_id,)
    assert after_boundary.fidelity_class == "rule"


def test_missing_heartbeat_is_unknown_and_future_clock_skew_does_not_look_stale():
    now = datetime(2026, 7, 18, 10, 20, tzinfo=UTC)

    missing = assess_heartbeat(None, now=now, stale_after_seconds=30)
    future = assess_heartbeat(
        _heartbeat(now + timedelta(seconds=5)),
        now=now,
        stale_after_seconds=30,
    )

    assert missing.value == "unknown"
    assert missing.evidence_obs_ids == ()
    assert future.value == "fresh"
    assert future.age_ms == 0


def test_dwell_assessment_marks_long_only_after_threshold_and_handles_missing():
    now = datetime(2026, 7, 18, 10, 5, tzinfo=UTC)

    boundary = assess_dwell(
        since=now - timedelta(seconds=120),
        evidence_obs_id="obs-step",
        now=now,
        long_dwell_seconds=120,
    )
    long = assess_dwell(
        since=now - timedelta(seconds=121),
        evidence_obs_id="obs-tool",
        now=now,
        long_dwell_seconds=120,
    )
    missing = assess_dwell(
        since=None,
        evidence_obs_id=None,
        now=now,
        long_dwell_seconds=120,
    )

    assert boundary.value == "normal"
    assert boundary.duration_ms == 120_000
    assert long.value == "long"
    assert long.evidence_obs_ids == ("obs-tool",)
    assert missing.value == "unknown"
    assert missing.duration_ms is None
