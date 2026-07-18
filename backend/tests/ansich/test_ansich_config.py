from datetime import UTC, datetime

import pytest
from ansich import ObservationEnvelope, new_id

from deerflow.ansich import create_embedded_ansich_service
from deerflow.config.ansich_config import AnsichConfig


def test_ansich_is_disabled_by_default_with_bounded_runtime_settings():
    config = AnsichConfig()

    assert config.enabled is False
    assert config.queue_capacity == 10_000
    assert config.batch_size == 100
    assert config.flush_interval_ms == 100
    assert config.terminal_flush_timeout_ms == 2_000
    assert config.projector_poll_interval_ms == 250
    assert config.projector_lease_seconds == 30
    assert config.projector_max_attempts == 5
    assert config.projector_dependency_timeout_seconds == 300
    assert config.inline_payload_max_bytes == 65_536


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
