from __future__ import annotations

import logging

import pytest
from ansich import AnsichService
from ansich.release import AgentRuntimeDescriptor

from deerflow.ansich.probes import TaskControlProbe


@pytest.mark.asyncio
async def test_agent_release_resolution_follows_task_created_and_binds_starting_actor():
    service = AnsichService.in_memory()
    await service.start()
    probe = TaskControlProbe(
        service,
        run_id="run-release-probe",
        thread_id="thread-release-probe",
    )
    descriptor = AgentRuntimeDescriptor(
        namespace="deerflow",
        agent_name="lead-agent",
        effective_model="provider/model-v1",
        prompt_template_id="lead-v1",
        rendered_base_prompt="You are DeerFlow.",
    )

    try:
        probe.created()
        probe.agent_release_resolved(descriptor)
        await service.flush_task(probe.task_id)
        observations = await service.list_observations(probe.task_id)
        binding = await service.get_task_agent_release(probe.task_id)
    finally:
        await service.stop()

    assert [item.kind for item in observations[:2]] == [
        "task.created",
        "agent_release.resolved",
    ]
    assert binding is not None
    assert binding.release.manifest.model.effective == "provider/model-v1"


@pytest.mark.asyncio
async def test_agent_release_resolution_failure_is_fail_open_and_does_not_log_descriptor_secrets(
    caplog,
):
    service = AnsichService.in_memory()
    await service.start()
    probe = TaskControlProbe(
        service,
        run_id="run-invalid-release-probe",
        thread_id="thread-invalid-release-probe",
    )
    secret = "release-descriptor-secret"

    try:
        probe.created()
        with caplog.at_level(
            logging.WARNING,
            logger="deerflow.ansich.probes.task_control",
        ):
            probe.agent_release_resolved({"api_key": secret})
        await service.flush_task(probe.task_id)
        observations = await service.list_observations(probe.task_id)
    finally:
        await service.stop()

    assert secret not in caplog.text
    assert any(
        item.kind == "observability.degraded"
        and item.payload
        == {
            "component": "agent_release",
            "reason": "resolution_failed",
        }
        for item in observations
    )


@pytest.mark.asyncio
async def test_agent_release_resolution_filters_request_scoped_secret_values() -> None:
    service = AnsichService.in_memory()
    await service.start()
    probe = TaskControlProbe(
        service,
        run_id="run-secret-release-probe",
        thread_id="thread-secret-release-probe",
    )
    secret = "request-scoped-release-secret"
    descriptor = AgentRuntimeDescriptor(
        namespace="deerflow",
        agent_name="lead-agent",
        effective_model="provider/model-v1",
        prompt_template_id="lead-v1",
        rendered_base_prompt=f"Prompt accidentally includes {secret}",
    )

    try:
        probe.created()
        probe.agent_release_resolved(descriptor, known_secrets=(secret,))
        await service.flush_task(probe.task_id)
        binding = await service.get_task_agent_release(probe.task_id)
    finally:
        await service.stop()

    assert binding is not None
    assert secret not in binding.release.manifest.model_dump_json()


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


@pytest.mark.asyncio
async def test_terminal_wall_time_uses_monotonic_duration_and_never_goes_negative():
    service = AnsichService.in_memory()
    await service.start()
    monotonic_values = iter((100.0, 99.0))
    probe = TaskControlProbe(
        service,
        run_id="run-monotonic-wall-time",
        thread_id="thread-monotonic-wall-time",
        monotonic=lambda: next(monotonic_values),
    )

    try:
        probe.created()
        probe.started()
        await probe.terminal("success")
        observations = await service.list_observations(probe.task_id)
        usage = await service.get_task_usage(probe.task_id)
    finally:
        await service.stop()

    assert [(item.dimension, item.value) for item in usage.local] == [
        ("wall_time_ms", 0),
    ]
    kinds = [item.kind for item in observations]
    assert kinds.index("budget.consumed") < kinds.index("task.completed")
