"""Task 6: per-command environment-sample emission from the tool probe chain.

Covers the ``environment.sampled`` emission wired into
``AnsichRawToolMiddleware.wrap_tool_call`` / ``awrap_tool_call`` right after
the raw ``tool.returned_raw`` terminal is recorded, plus the async
``asyncio.to_thread`` context-hand-back fix in
``deerflow.sandbox.tools._run_sync_tool_after_async_sandbox_init`` that makes
the emission actually observable on the real (async, Gateway) execution path.

Fixture conventions (execution context, ``_register_call``-equivalent
registration, ``SimpleNamespace`` request, ``_record_batch`` monkeypatch) are
lifted from ``tests/ansich/test_execution_context.py``.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from ansich import new_id
from langchain_core.messages import ToolMessage

from deerflow.ansich import tool_middleware as tool_observer
from deerflow.ansich.execution import ANSICH_EXECUTION_CONTEXT_KEY, AnsichExecutionContext
from deerflow.ansich.tool_middleware import AnsichRawToolMiddleware
from deerflow.sandbox import telemetry
from deerflow.sandbox.telemetry import CommandResourceSample

THREAD_ID = "thread-env-sample"


def _register_call(execution, provider_call_id, tool_name):
    return execution.register_tool_call(
        tool_call_id=new_id(),
        step_id=new_id(),
        step_seq=1,
        call_seq=1,
        provider_call_id=provider_call_id,
        tool_name=tool_name,
        args_hash="a" * 64,
        issued_obs_id=new_id(),
    )


def _make_execution_and_request(tool_name: str, provider_call_id: str, *, thread_id: str | None = THREAD_ID):
    execution = AnsichExecutionContext(task_id=new_id(), service=MagicMock())
    registration = _register_call(execution, provider_call_id, tool_name)
    context: dict[str, object] = {ANSICH_EXECUTION_CONTEXT_KEY: execution}
    if thread_id is not None:
        context["thread_id"] = thread_id
    request = SimpleNamespace(
        runtime=SimpleNamespace(context=context),
        tool_call={"id": provider_call_id, "name": tool_name, "args": {}},
    )
    return execution, registration, request


def _sample(**overrides) -> CommandResourceSample:
    base = {
        "started_at": datetime(2026, 8, 19, 12, 0, 0, tzinfo=UTC),
        "ended_at": datetime(2026, 8, 19, 12, 0, 1, tzinfo=UTC),
        "sample_count": 3,
        "io_read_bytes": 4096,
        "io_write_bytes": 8192,
        "fd_peak": 12,
    }
    base.update(overrides)
    return CommandResourceSample(**base)


def _env_sampled_calls(service: MagicMock):
    return [call for call in service.record.call_args_list if call.args[0].kind == "environment.sampled"]


@pytest.fixture(autouse=True)
def _clean_command_sample_contextvar():
    # Defensive: an earlier failing test in the same process must not leak a
    # stale sample into this one via the module-level ContextVar.
    telemetry.consume_command_sample()
    yield
    telemetry.consume_command_sample()


def test_bash_success_emits_environment_sampled_with_expected_shape(monkeypatch) -> None:
    execution, registration, request = _make_execution_and_request("bash", "prov-bash-1")
    monkeypatch.setattr(tool_observer, "_record_batch", lambda e, b, *, batch_kind: True)
    telemetry.publish_command_sample(_sample())

    with execution.activate_tool_invocation(registration):
        result = AnsichRawToolMiddleware().wrap_tool_call(
            request,
            lambda r: ToolMessage(content="ok", tool_call_id="prov-bash-1", name="bash"),
        )

    assert isinstance(result, ToolMessage)
    calls = _env_sampled_calls(execution.service)
    assert len(calls) == 1
    envelope = calls[0].args[0]
    assert envelope.subject_type == "scope"
    payload = envelope.payload
    assert payload["environment_scope"] == "process_group"
    assert payload["coverage"] == "per_command"
    assert payload["provider"] == "local"
    assert payload["tool_call_id"] == registration.tool_call_id
    assert payload["window"] == {
        "started_at": _sample().started_at,
        "ended_at": _sample().ended_at,
        "sample_count": 3,
    }
    assert payload["metrics"] == {
        "fd_open": {"value": 12, "limit": None},
        "io_read_bytes": {"value": 4096, "limit": None},
        "io_write_bytes": {"value": 8192, "limit": None},
    }
    assert envelope.source_event_id == f"tool:{registration.tool_call_id}:env"


def test_metrics_include_only_non_none_dimensions(monkeypatch) -> None:
    execution, registration, request = _make_execution_and_request("bash", "prov-bash-2")
    monkeypatch.setattr(tool_observer, "_record_batch", lambda e, b, *, batch_kind: True)
    telemetry.publish_command_sample(_sample(io_read_bytes=None, io_write_bytes=None))

    with execution.activate_tool_invocation(registration):
        AnsichRawToolMiddleware().wrap_tool_call(
            request,
            lambda r: ToolMessage(content="ok", tool_call_id="prov-bash-2", name="bash"),
        )

    calls = _env_sampled_calls(execution.service)
    assert len(calls) == 1
    assert calls[0].args[0].payload["metrics"] == {"fd_open": {"value": 12, "limit": None}}


def test_non_bash_tool_does_not_emit_and_leaves_sample_untouched(monkeypatch) -> None:
    execution, registration, request = _make_execution_and_request("write_file", "prov-nonbash")
    monkeypatch.setattr(tool_observer, "_record_batch", lambda e, b, *, batch_kind: True)
    sample = _sample()
    telemetry.publish_command_sample(sample)

    with execution.activate_tool_invocation(registration):
        AnsichRawToolMiddleware().wrap_tool_call(
            request,
            lambda r: ToolMessage(content="ok", tool_call_id="prov-nonbash", name="write_file"),
        )

    assert _env_sampled_calls(execution.service) == []
    # Non-bash tools must not consume a sample that belongs to a (possibly
    # concurrent) bash context — ContextVar isolation across contexts makes
    # cross-tool-call interference impossible in production, but within one
    # context the helper's own tool_name gate must not eagerly drain it either.
    assert telemetry.consume_command_sample() is sample


def test_empty_context_var_does_not_emit(monkeypatch) -> None:
    execution, registration, request = _make_execution_and_request("bash", "prov-empty")
    monkeypatch.setattr(tool_observer, "_record_batch", lambda e, b, *, batch_kind: True)
    assert telemetry.consume_command_sample() is None  # sanity: nothing published

    with execution.activate_tool_invocation(registration):
        AnsichRawToolMiddleware().wrap_tool_call(
            request,
            lambda r: ToolMessage(content="ok", tool_call_id="prov-empty", name="bash"),
        )

    assert _env_sampled_calls(execution.service) == []


def test_missing_thread_id_does_not_emit(monkeypatch) -> None:
    execution, registration, request = _make_execution_and_request("bash", "prov-nothread", thread_id=None)
    monkeypatch.setattr(tool_observer, "_record_batch", lambda e, b, *, batch_kind: True)
    telemetry.publish_command_sample(_sample())

    with execution.activate_tool_invocation(registration):
        AnsichRawToolMiddleware().wrap_tool_call(
            request,
            lambda r: ToolMessage(content="ok", tool_call_id="prov-nothread", name="bash"),
        )

    assert _env_sampled_calls(execution.service) == []


def test_emission_failure_is_fail_open_and_tool_message_unaffected(monkeypatch) -> None:
    execution, registration, request = _make_execution_and_request("bash", "prov-failopen")
    monkeypatch.setattr(tool_observer, "_record_batch", lambda e, b, *, batch_kind: True)
    telemetry.publish_command_sample(_sample())
    execution.service.record.side_effect = RuntimeError("boom")

    with execution.activate_tool_invocation(registration):
        result = AnsichRawToolMiddleware().wrap_tool_call(
            request,
            lambda r: ToolMessage(content="still ok", tool_call_id="prov-failopen", name="bash"),
        )

    assert isinstance(result, ToolMessage)
    assert result.content == "still ok"


def test_async_bash_success_emits_environment_sampled(monkeypatch) -> None:
    async def scenario() -> None:
        execution, registration, request = _make_execution_and_request("bash", "prov-async-1")
        monkeypatch.setattr(tool_observer, "_record_batch", lambda e, b, *, batch_kind: True)
        telemetry.publish_command_sample(_sample())

        async def handler(r):
            return ToolMessage(content="ok", tool_call_id="prov-async-1", name="bash")

        with execution.activate_tool_invocation(registration):
            result = await AnsichRawToolMiddleware().awrap_tool_call(request, handler)

        assert isinstance(result, ToolMessage)
        calls = _env_sampled_calls(execution.service)
        assert len(calls) == 1
        assert calls[0].args[0].payload["tool_call_id"] == registration.tool_call_id

    asyncio.run(scenario())


def test_async_emission_failure_is_fail_open(monkeypatch) -> None:
    async def scenario() -> None:
        execution, registration, request = _make_execution_and_request("bash", "prov-async-failopen")
        monkeypatch.setattr(tool_observer, "_record_batch", lambda e, b, *, batch_kind: True)
        telemetry.publish_command_sample(_sample())
        execution.service.record.side_effect = RuntimeError("boom")

        async def handler(r):
            return ToolMessage(content="still ok", tool_call_id="prov-async-failopen", name="bash")

        with execution.activate_tool_invocation(registration):
            result = await AnsichRawToolMiddleware().awrap_tool_call(request, handler)

        assert isinstance(result, ToolMessage)
        assert result.content == "still ok"

    asyncio.run(scenario())


def test_asyncio_to_thread_offload_hands_the_sample_back_to_the_caller_context(monkeypatch) -> None:
    """The real Task 3/6 boundary defect and its fix, isolated from Ansich.

    Before the transport fix in ``_run_sync_tool_after_async_sandbox_init``,
    ``asyncio.to_thread(func, ...)`` copied the caller's context and ran
    ``func`` inside that copy; any ``ContextVar.set()`` performed by ``func``
    (i.e. ``telemetry.publish_command_sample`` inside a real
    ``execute_command``) was therefore invisible to the awaiting coroutine's
    own context once the ``await`` returned, and
    ``telemetry.consume_command_sample()`` called back in the tool-middleware
    chain would always read ``None``. This test drives the actual offload
    helper end to end and would have failed (asserted ``None`` instead of the
    sample) against the pre-fix ``return await asyncio.to_thread(func, ...)``
    body.
    """
    import deerflow.sandbox.tools as sandbox_tools

    async def fake_ensure_sandbox_initialized_async(_runtime):
        return None

    monkeypatch.setattr(
        sandbox_tools,
        "ensure_sandbox_initialized_async",
        fake_ensure_sandbox_initialized_async,
    )

    def sync_body(_runtime, *_args) -> str:
        telemetry.publish_command_sample(_sample())
        return "command output"

    async def scenario() -> None:
        runtime = SimpleNamespace(context={}, state={"sandbox": {"sandbox_id": "local:test"}}, config={})
        result = await sandbox_tools._run_sync_tool_after_async_sandbox_init(sync_body, runtime)
        assert result == "command output"
        handed_back = telemetry.consume_command_sample()
        assert handed_back is not None
        assert handed_back.fd_peak == 12

    asyncio.run(scenario())
