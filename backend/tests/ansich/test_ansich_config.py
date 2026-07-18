from datetime import UTC, datetime

import pytest
from ansich import ObservationEnvelope, new_id
from pydantic import ValidationError

from deerflow.ansich import create_embedded_ansich_service
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
    assert config.assessors.exact_repetition_window == 5
    assert config.assessors.tool_frequency_window_seconds == 300
    assert config.assessors.tool_frequency_threshold == 30


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
