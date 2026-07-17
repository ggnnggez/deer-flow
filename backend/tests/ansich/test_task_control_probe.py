from __future__ import annotations

import logging

import pytest
from ansich import AnsichService

from deerflow.ansich.probes import TaskControlProbe


@pytest.mark.asyncio
async def test_timeout_run_status_is_mapped_to_terminal_failed_control():
    service = AnsichService.in_memory()
    await service.start()
    probe = TaskControlProbe(service, run_id="run-timeout-status", thread_id="thread-timeout")

    try:
        probe.created()
        probe.started()
        await probe.terminal("timeout")
        task = await service.get_task(probe.task_id)
    finally:
        await service.stop()

    assert task is not None
    assert task.control.value == "failed"


@pytest.mark.asyncio
async def test_unknown_terminal_status_logs_warning_instead_of_leaving_task_silently_non_terminal(caplog):
    service = AnsichService.in_memory()
    await service.start()
    probe = TaskControlProbe(service, run_id="run-unknown-status", thread_id="thread-unknown")

    try:
        probe.created()
        probe.started()
        with caplog.at_level(logging.WARNING, logger="deerflow.ansich.probes.task_control"):
            await probe.terminal("some-future-status")
        task = await service.get_task(probe.task_id)
    finally:
        await service.stop()

    assert task is not None
    assert task.control.value == "running"
    assert any("some-future-status" in record.getMessage() and "run-unknown-status" in record.getMessage() for record in caplog.records)
