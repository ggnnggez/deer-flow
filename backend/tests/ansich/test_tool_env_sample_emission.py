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
import json
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


def _make_execution_and_request(
    tool_name: str,
    provider_call_id: str,
    *,
    thread_id: str | None = THREAD_ID,
    run_id: str | None = None,
):
    execution = AnsichExecutionContext(task_id=new_id(), service=MagicMock())
    registration = _register_call(execution, provider_call_id, tool_name)
    context: dict[str, object] = {ANSICH_EXECUTION_CONTEXT_KEY: execution}
    if thread_id is not None:
        context["thread_id"] = thread_id
    if run_id is not None:
        context["run_id"] = run_id
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
        "started_at": _sample().started_at.isoformat(),
        "ended_at": _sample().ended_at.isoformat(),
        "sample_count": 3,
    }
    assert payload["metrics"] == {
        "fd_open": {"value": 12, "limit": None},
        "io_read_bytes": {"value": 4096, "limit": None},
        "io_write_bytes": {"value": 8192, "limit": None},
    }
    assert envelope.source_event_id == f"tool:{registration.tool_call_id}:env"
    # Regression: the payload must be plain-JSON-serializable exactly as the
    # persistence writer serializes it (ansich/persistence/sql.py does a bare
    # json.dumps with no default= converter) — a raw datetime in `window`
    # (rather than an ISO string) would TypeError there and lose the whole
    # flush batch with reason="storage_failure" while still passing here if
    # this assertion were absent.
    assert json.dumps(payload)


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


def test_run_id_from_runtime_context_lands_in_correlation_id(monkeypatch) -> None:
    execution, registration, request = _make_execution_and_request("bash", "prov-runid", run_id="run-context-42")
    monkeypatch.setattr(tool_observer, "_record_batch", lambda e, b, *, batch_kind: True)
    telemetry.publish_command_sample(_sample())

    with execution.activate_tool_invocation(registration):
        AnsichRawToolMiddleware().wrap_tool_call(
            request,
            lambda r: ToolMessage(content="ok", tool_call_id="prov-runid", name="bash"),
        )

    calls = _env_sampled_calls(execution.service)
    assert len(calls) == 1
    envelope = calls[0].args[0]
    # environment.sampled's correlation_id IS the run_id (see
    # ObservationEnvelope.environment_sampled), unlike every other Observation
    # this file emits (those use task_id) — so a context-provided run_id must
    # land there distinctly from execution.task_id.
    assert envelope.correlation_id == "run-context-42"
    assert envelope.correlation_id != execution.task_id


def test_run_id_falls_back_to_task_id_when_context_has_none(monkeypatch) -> None:
    execution, registration, request = _make_execution_and_request("bash", "prov-norunid")
    monkeypatch.setattr(tool_observer, "_record_batch", lambda e, b, *, batch_kind: True)
    telemetry.publish_command_sample(_sample())

    with execution.activate_tool_invocation(registration):
        AnsichRawToolMiddleware().wrap_tool_call(
            request,
            lambda r: ToolMessage(content="ok", tool_call_id="prov-norunid", name="bash"),
        )

    calls = _env_sampled_calls(execution.service)
    assert len(calls) == 1
    assert calls[0].args[0].correlation_id == execution.task_id


def test_bash_error_does_not_leave_a_stray_sample_for_the_next_call(monkeypatch) -> None:
    execution, registration, request = _make_execution_and_request("bash", "prov-raises")
    monkeypatch.setattr(tool_observer, "_record_batch", lambda e, b, *, batch_kind: True)
    telemetry.publish_command_sample(_sample())

    def raising_handler(r):
        raise RuntimeError("command blew up")

    with execution.activate_tool_invocation(registration):
        with pytest.raises(RuntimeError):
            AnsichRawToolMiddleware().wrap_tool_call(request, raising_handler)

    # The failed call must not emit (raised before the success path), and —
    # the actual point of this test — must not leave the sample sitting in
    # the ContextVar where a later, unrelated bash call in this same context
    # would pick it up and misattribute it to its own tool_call_id.
    assert _env_sampled_calls(execution.service) == []
    assert telemetry.consume_command_sample() is None


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
