from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from ansich import ObservationEnvelope, new_id
from pydantic import ValidationError

from deerflow.ansich import create_embedded_ansich_service, create_sql_ansich_service
from deerflow.config.ansich_config import AnsichConfig


def test_ansich_is_disabled_by_default_with_bounded_runtime_settings():
    config = AnsichConfig()

    assert config.enabled is False
    assert config.queue_capacity == 10_000
    assert config.queue_byte_capacity == 64 * 1024 * 1024
    assert config.batch_size == 100
    assert config.flush_interval_ms == 100
    assert config.terminal_flush_timeout_ms == 2_000
    assert config.projector_poll_interval_ms == 250
    assert config.projector_lease_seconds == 30
    assert config.projector_max_attempts == 5
    assert config.projector_dependency_timeout_seconds == 300
    assert config.inline_payload_max_bytes == 65_536
    assert config.heartbeat_interval_seconds == 10
    assert config.heartbeat_stale_after_seconds == 30
    assert config.long_dwell_seconds == 120
    assert config.evaluation_min_cohort_samples == 5
    assert config.evaluation_max_payload_bytes == 262_144
    assert config.assessors.exact_repetition_window == 5
    assert config.assessors.tool_frequency_window_seconds == 300
    assert config.assessors.tool_frequency_threshold == 30


def test_writer_resilience_defaults_are_bounded():
    config = AnsichConfig()

    assert config.writer_retry_max_attempts == 5
    assert config.writer_backoff_initial_ms == 100
    assert config.writer_backoff_max_ms == 5_000
    assert config.writer_item_max_attempts == 2
    assert config.stop_drain_timeout_ms == 10_000
    for field in (
        "writer_retry_max_attempts",
        "writer_backoff_initial_ms",
        "writer_backoff_max_ms",
        "writer_item_max_attempts",
        "stop_drain_timeout_ms",
    ):
        # Every one of these is a count or a duration: zero would mean "never
        # retry"/"no budget" spelled as a bound rather than as a switch.
        with pytest.raises(ValidationError):
            AnsichConfig.model_validate({field: 0})
        assert AnsichConfig.model_fields[field].description.startswith("startup-only:")


def test_writer_resilience_settings_reach_the_service_on_both_assembly_paths():
    configured = AnsichConfig(
        enabled=True,
        writer_retry_max_attempts=3,
        writer_backoff_initial_ms=25,
        writer_backoff_max_ms=250,
        writer_item_max_attempts=4,
        stop_drain_timeout_ms=7_500,
    )

    sql_backed = create_embedded_ansich_service(configured, MagicMock())
    # The no-storage service still writes nothing, but it must not be assembled
    # with a different writer policy than the one the operator configured.
    without_storage = create_embedded_ansich_service(configured, None)

    for service in (sql_backed, without_storage):
        assert service is not None
        assert service._writer_retry_max_attempts == 3
        assert service._writer_backoff_initial_ms == 25
        assert service._writer_backoff_max_ms == 250
        assert service._writer_item_max_attempts == 4
        assert service._stop_drain_timeout_seconds == 7.5


def test_evaluation_thresholds_are_overridable_and_bounded():
    config = AnsichConfig.model_validate(
        {
            "evaluation_min_cohort_samples": 20,
            "evaluation_max_payload_bytes": 1024,
        }
    )

    assert config.evaluation_min_cohort_samples == 20
    assert config.evaluation_max_payload_bytes == 1024
    with pytest.raises(ValidationError):
        AnsichConfig.model_validate({"evaluation_min_cohort_samples": 0})
    with pytest.raises(ValidationError):
        AnsichConfig.model_validate({"evaluation_max_payload_bytes": 0})


def test_ansich_assessor_thresholds_are_nested_and_validated():
    config = AnsichConfig.model_validate(
        {
            "assessors": {
                "exact_repetition_window": 7,
                "tool_frequency_window_seconds": 120,
                "tool_frequency_threshold": 20,
            }
        }
    )

    assert config.assessors.exact_repetition_window == 7
    assert config.assessors.tool_frequency_window_seconds == 120
    assert config.assessors.tool_frequency_threshold == 20
    with pytest.raises(ValidationError):
        AnsichConfig.model_validate({"assessors": {"exact_repetition_window": 1}})


def test_heartbeat_staleness_requires_at_least_two_intervals():
    with pytest.raises(ValidationError, match="at least twice"):
        AnsichConfig(
            heartbeat_interval_seconds=10,
            heartbeat_stale_after_seconds=19,
        )


def test_direct_sql_factory_waits_longer_without_changing_embedded_timeout() -> None:
    direct = create_sql_ansich_service(MagicMock())
    embedded = create_embedded_ansich_service(
        AnsichConfig(enabled=True, terminal_flush_timeout_ms=2345),
        MagicMock(),
    )

    assert direct._terminal_flush_timeout_seconds == 10
    assert embedded is not None
    assert embedded._terminal_flush_timeout_seconds == 2.345


@pytest.mark.anyio
async def test_enabled_ansich_without_sql_storage_reports_failed_and_rejects_records():
    service = create_embedded_ansich_service(AnsichConfig(enabled=True), None)
    assert service is not None
    await service.start()

    try:
        receipt = service.record(
            ObservationEnvelope.task_lifecycle(
                kind="task.created",
                task_id=new_id(),
                source_kind="deerflow_run",
                source_id="run-without-sql",
                occurred_at=datetime(2026, 7, 17, 13, 0, tzinfo=UTC),
                source_event_id="run:run-without-sql:task:created",
            )
        )
        health = service.get_health()
    finally:
        await service.stop()

    assert receipt.accepted is False
    assert receipt.reason == "storage_unavailable"
    assert health.status == "failed"


def test_environment_defaults():
    config = AnsichConfig()
    assert config.environment_probe_enabled is True
    assert config.environment_sample_interval_seconds is None
    assert config.effective_environment_sample_interval_seconds == config.heartbeat_interval_seconds
    assert config.environment_per_command_sampling is True
    assert config.assessors.environment_leak_min_samples == 6


def test_environment_interval_override_and_bounds():
    config = AnsichConfig(environment_sample_interval_seconds=5)
    assert config.effective_environment_sample_interval_seconds == 5
    with pytest.raises(ValidationError):
        AnsichConfig(environment_sample_interval_seconds=0)


def test_environment_threshold_ordering():
    with pytest.raises(ValidationError):
        AnsichConfig(assessors={"environment_fd_warn_ratio": 0.96, "environment_fd_critical_ratio": 0.95})
