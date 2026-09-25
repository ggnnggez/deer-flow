"""Context residency, recorded by an out-of-tree extension.

The extension answers, per task, which content blocks each model request
carried: it inventories every physical provider call at ``MODEL_PHYSICAL``,
groups calls into logical decisions at ``MODEL_LOGICAL``, records each
compaction with the hashes the host declared, and serves a metadata-only
projection to administrators. These tests drive it through the real host
seams — the extension loader, the placement anchors, the task store the host
seeds, the compaction event — and through its own writer and reader on SQLite.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from deerflow_extension_api import (
    EXTENSION_PRINCIPAL_RESOLVER_KEY,
    EXTENSION_TASK_STORE_KEY,
    AgentBuildContext,
    AgentScope,
    CompactionEvent,
    ContentKind,
    ExtensionData,
    ExtensionPrincipal,
    ExtensionRuntimeDeps,
    TaskInfo,
    TaskOutcome,
    canonical_hash,
    provenance_kwargs,
)
from fastapi import FastAPI
from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import PrivateAttr
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from deerflow.agents.middlewares.llm_error_handling_middleware import LLMErrorHandlingMiddleware
from deerflow.agents.thread_state import ThreadState
from deerflow.config.app_config import AppConfig
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.extensions.loader import ExtensionSpec, load_extensions
from deerflow.extensions.stack import compose_with_extensions

EXAMPLE = Path(__file__).resolve().parents[2] / "examples/deerflow-extension-context-residency"


@pytest.fixture
def ctxres(monkeypatch):
    monkeypatch.syspath_prepend(str(EXAMPLE))
    import deerflow_extension_context_residency as package
    import deerflow_extension_context_residency.inventory as inventory
    import deerflow_extension_context_residency.probes as probes
    import deerflow_extension_context_residency.read as read
    import deerflow_extension_context_residency.recorder as recorder
    import deerflow_extension_context_residency.service as service

    return SimpleNamespace(package=package, inventory=inventory, probes=probes, read=read, recorder=recorder, service=service)


def _stamped(content: str, content_kind: str, producer: str, **extra) -> HumanMessage:
    return HumanMessage(content=content, additional_kwargs=provenance_kwargs(content_kind, producer, **extra))


# --- The inventory is the request, in order, hashed the way the host hashes -----


class TestInventory:
    def test_members_follow_request_order_and_hash_content_the_way_the_host_does(self, ctxres):
        @tool
        def search(query: str) -> str:
            """Search the web."""
            return query

        system = SystemMessage(content="You are helpful.")
        human = HumanMessage(content="find it", id="user-1")
        request = AIMessage(content="", tool_calls=[{"id": "call-1", "name": "search", "args": {"query": "x"}}], id="ai-1")
        result = ToolMessage(content="found", tool_call_id="call-1", id="tool-1")

        members = ctxres.inventory.inventory("task-1", [human, request, result], system, [search])

        assert [m.ordinal for m in members] == [0, 1, 2, 3, 4]
        assert [m.kind for m in members] == ["system_prompt", "user_input", "tool_request", "tool_result_visible", "tool_schema"]
        assert [m.channel for m in members] == ["message"] * 4 + ["tool_schema"]
        assert members[1].content_hash == canonical_hash("find it")
        assert members[1].source_identity == "message:user-1"
        assert members[4].name == "search" and members[4].source_identity == "tool-schema:search"
        assert all(m.estimated_tokens > 0 and m.visible_bytes > 0 for m in members)

    def test_stamped_injections_take_their_kind_from_the_stamp(self, ctxres):
        messages = [
            _stamped("recalled", ContentKind.MEMORY, "dynamic_context_memory"),
            _stamped("SKILL.md body", ContentKind.SKILL_BODY, "skill_activation"),
            _stamped("date reminder", ContentKind.MIDDLEWARE_INJECTION, "dynamic_context"),
            _stamped("<durable_context_data>…</durable_context_data>", ContentKind.DURABLE_CONTEXT, "durable_context_data", summary_content_hash="h-summary"),
            SystemMessage(content="merged", additional_kwargs=provenance_kwargs(ContentKind.MIDDLEWARE_INJECTION, "system_coalescing")),
            _stamped("from a newer host", "hologram", "future_middleware"),
        ]

        kinds = [(m.kind, m.summary_content_hash) for m in ctxres.inventory.inventory("task-1", messages, None, [])]

        assert kinds == [
            ("memory", None),
            ("skill_instruction", None),
            ("middleware_injection", None),
            ("summary", "h-summary"),
            ("system_prompt", None),
            ("hologram", None),
        ]

    def test_identity_uses_the_message_id_when_present_and_the_occurrence_otherwise(self, ctxres):
        inventory = ctxres.inventory.inventory
        reminder = _stamped("Today is Monday.", ContentKind.MIDDLEWARE_INJECTION, "dynamic_context")
        stateful = HumanMessage(content="hi", id="user-1")

        first = inventory("task-1", [reminder, stateful], None, [])
        again = inventory("task-1", [stateful, reminder, reminder], None, [])
        elsewhere = inventory("task-2", [reminder], None, [])

        # An id-less injection with the same text is the same block across requests…
        assert first[0].block_id == again[1].block_id
        # …but two identical copies inside one request are told apart by occurrence.
        assert again[1].block_id != again[2].block_id
        # A stateful message keeps its identity wherever it sits.
        assert first[1].block_id == again[0].block_id
        # Identity is task-scoped.
        assert first[0].block_id != elsewhere[0].block_id


# --- The probes through the real host stack --------------------------------------


class RecordingModel(BaseChatModel):
    _seen: list = PrivateAttr(default_factory=list)
    _fail_first: bool = PrivateAttr(default=False)

    @property
    def _llm_type(self):
        return "residency-test"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self._seen.append(messages)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="done"))])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        return self._generate(messages, stop, run_manager, **kwargs)


def _load(enabled: bool = True, **config):
    loaded, diagnostics = load_extensions([ExtensionSpec(use="deerflow_extension_context_residency:install", config={"enabled": enabled, **config})])
    assert not diagnostics, diagnostics
    ((_, service),) = loaded.services
    return loaded, service


def _graph(loaded):
    app_config = AppConfig(sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"))
    stack = compose_with_extensions([LLMErrorHandlingMiddleware(app_config=app_config)], AgentScope.LEAD, AgentBuildContext(scope=AgentScope.LEAD), loaded)
    model = RecordingModel()
    return create_agent(model, tools=[], middleware=stack, state_schema=ThreadState, checkpointer=InMemorySaver()), model


def _seeded_store(task_id: str = "run-1") -> ExtensionData:
    store = ExtensionData(task_id)
    store.set(TaskInfo(task_id=task_id, run_id="run-1", thread_id="thread-1", kind="lead"))
    return store


def _context(store: ExtensionData) -> dict:
    return {"thread_id": "thread-1", "run_id": "run-1", EXTENSION_TASK_STORE_KEY: store}


class TestProbesThroughTheHost:
    @pytest.mark.parametrize("asynchronous", [False, True])
    def test_one_turn_is_one_step_with_one_effective_attempt(self, ctxres, asynchronous):
        loaded, service = _load()
        graph, model = _graph(loaded)
        store = _seeded_store()
        config = {"configurable": {"thread_id": "thread-1"}}

        if asynchronous:
            asyncio.run(graph.ainvoke({"messages": [HumanMessage(content="hello", id="user-1")]}, config, context=_context(store)))
        else:
            graph.invoke({"messages": [HumanMessage(content="hello", id="user-1")]}, config, context=_context(store))

        events = service.handle.drain()
        kinds = [type(e).__name__ for e in events]
        assert kinds == ["AttemptRequested", "AttemptFinished", "StepClosed"]
        requested, finished, closed = events
        assert requested.task_id == "run-1" and requested.step_seq == 1 and requested.attempt_no == 1
        assert requested.status == "complete"
        assert [m.kind for m in requested.members] == ["user_input"]
        assert requested.members[0].content_hash == canonical_hash("hello")
        assert finished.outcome == "responded" and finished.attempt_id == requested.attempt_id
        assert closed.effective_attempt_id == requested.attempt_id and closed.step_id == requested.step_id
        # The probes are read-only: the model saw exactly the state message.
        assert [m.content for m in model._seen[0]] == ["hello"]

    def test_the_second_turn_is_the_second_step(self, ctxres):
        loaded, service = _load()
        graph, _ = _graph(loaded)
        store = _seeded_store()
        config = {"configurable": {"thread_id": "thread-1"}}

        graph.invoke({"messages": [HumanMessage(content="one", id="user-1")]}, config, context=_context(store))
        graph.invoke({"messages": [HumanMessage(content="two", id="user-2")]}, config, context=_context(store))

        requested = [e for e in service.handle.drain() if isinstance(e, ctxres.recorder.AttemptRequested)]
        assert [(e.step_seq, e.attempt_no) for e in requested] == [(1, 1), (2, 1)]
        # The second request carried both turns; the first user block keeps its identity.
        assert requested[0].members[0].block_id == requested[1].members[0].block_id

    def test_without_a_task_store_the_probes_pass_through(self, ctxres):
        loaded, service = _load()
        graph, model = _graph(loaded)

        graph.invoke({"messages": [HumanMessage(content="hello")]}, {"configurable": {"thread_id": "thread-1"}})

        assert service.handle.drain() == []
        assert len(model._seen) == 1

    def test_disabled_contributes_nothing(self, ctxres):
        loaded, _ = _load(enabled=False)
        ((_, contributor),) = loaded.middleware_contributors
        assert contributor.contribute_middlewares(None, AgentBuildContext(scope=AgentScope.LEAD)) == ()
        assert contributor.contribute_middlewares(None, AgentBuildContext(scope=AgentScope.SUBAGENT)) == ()

    def test_the_page_is_registered_as_packaged_assets(self, ctxres):
        from deerflow_extension_api import BrowserAssets

        loaded, _ = _load()
        ((_, plugin),) = loaded.plugins
        assert plugin.namespace == "community.context-residency"
        assert isinstance(plugin.frontend, BrowserAssets)
        assert plugin.frontend.module == "context-residency.v1"
        manifest = Path(plugin.frontend.root) / "ui_manifest.json"
        assert manifest.is_file()
        for relative in ("static/dist/index.mjs", "static/dist/styles.css"):
            assert (Path(plugin.frontend.root) / relative).is_file(), relative

    def test_enabled_contributes_both_probes_to_lead_and_subagent(self, ctxres):
        loaded, _ = _load()
        ((_, contributor),) = loaded.middleware_contributors
        for scope in (AgentScope.LEAD, AgentScope.SUBAGENT):
            placements = contributor.contribute_middlewares(None, AgentBuildContext(scope=scope))
            assert [p.placement.value for p in placements] == ["model_logical", "model_physical"]
            assert all(p.scope == AgentScope.BOTH for p in placements)


class TestProbeSemanticsDirectly:
    """A retry re-enters the physical probe, never the logical one."""

    def _request(self, store):
        return SimpleNamespace(
            runtime=SimpleNamespace(context={EXTENSION_TASK_STORE_KEY: store}),
            messages=[HumanMessage(content="hi", id="user-1")],
            system_message=None,
            tools=[],
            model=SimpleNamespace(model_name="fake-model"),
        )

    def test_two_physical_calls_inside_one_decision_are_two_attempts_of_one_step(self, ctxres):
        handle = ctxres.recorder.RecorderHandle(100)
        decision, attempt = ctxres.probes.DecisionProbe(handle), ctxres.probes.AttemptProbe(handle)
        request = self._request(_seeded_store())
        calls = {"n": 0}

        def provider(_request):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("transient")
            return "ok"

        def retrying_host(inner_request):
            try:
                return attempt.wrap_model_call(inner_request, provider)
            except RuntimeError:
                return attempt.wrap_model_call(inner_request, provider)

        assert decision.wrap_model_call(request, retrying_host) == "ok"

        events = handle.drain()
        requested = [e for e in events if isinstance(e, ctxres.recorder.AttemptRequested)]
        finished = [e for e in events if isinstance(e, ctxres.recorder.AttemptFinished)]
        [closed] = [e for e in events if isinstance(e, ctxres.recorder.StepClosed)]
        assert [(e.step_seq, e.attempt_no) for e in requested] == [(1, 1), (1, 2)]
        assert [e.outcome for e in finished] == ["failed", "responded"]
        assert closed.effective_attempt_id == requested[1].attempt_id
        assert requested[0].model_name == "fake-model"

    def test_a_failed_decision_closes_its_step_without_an_effective_attempt(self, ctxres):
        handle = ctxres.recorder.RecorderHandle(100)
        decision, attempt = ctxres.probes.DecisionProbe(handle), ctxres.probes.AttemptProbe(handle)
        request = self._request(_seeded_store())

        def provider(_request):
            raise RuntimeError("down")

        with pytest.raises(RuntimeError):
            decision.wrap_model_call(request, lambda r: attempt.wrap_model_call(r, provider))

        [closed] = [e for e in handle.drain() if isinstance(e, ctxres.recorder.StepClosed)]
        assert closed.effective_attempt_id is None

    def test_a_physical_call_outside_any_decision_is_its_own_step(self, ctxres):
        handle = ctxres.recorder.RecorderHandle(100)
        attempt = ctxres.probes.AttemptProbe(handle)
        request = self._request(_seeded_store())

        assert attempt.wrap_model_call(request, lambda r: "ok") == "ok"

        events = handle.drain()
        assert [type(e).__name__ for e in events] == ["AttemptRequested", "AttemptFinished", "StepClosed"]
        assert events[2].effective_attempt_id == events[0].attempt_id

    def test_a_full_buffer_drops_and_counts(self, ctxres):
        handle = ctxres.recorder.RecorderHandle(2)
        assert handle.put(ctxres.recorder.TaskStopped("t", "completed", "now")) is True
        assert handle.put(ctxres.recorder.TaskStopped("t", "completed", "now")) is True
        assert handle.put(ctxres.recorder.TaskStopped("t", "completed", "now")) is False
        assert handle.dropped == 1 and handle.accepted == 2 and handle.depth == 2


# --- Lifecycle and compaction hooks ---------------------------------------------------


class TestHooks:
    @pytest.mark.asyncio
    async def test_lifecycle_and_compaction_events_are_recorded_verbatim(self, ctxres):
        loaded, service = _load()
        ((_, lifecycle),) = loaded.task_lifecycle
        ((_, observer),) = loaded.context_compaction_observers
        info = TaskInfo(task_id="sub-1", run_id="run-1", thread_id="thread-1", kind="subagent", parent_task_id="run-1", agent_name="researcher")
        store = ExtensionData("call-1")

        await lifecycle.on_task_start(loaded.app_store, store, info)
        await observer.on_context_compacted(
            loaded.app_store,
            ExtensionData("detached"),
            CompactionEvent(
                transform_kind="summarization",
                transform_version="1",
                source_content_hashes=("h1",),
                output_content_hash="h-sum",
                compacted_message_count=1,
                kept_message_count=2,
                kept_content_hashes=("h2", "h3"),
                task_id="sub-1",
                run_id="run-1",
                thread_id="thread-1",
                emitted_at="2026-09-25T00:00:00+00:00",
            ),
        )
        await lifecycle.on_task_stop(loaded.app_store, store, info, TaskOutcome.COMPLETED)

        started, compacted, stopped = service.handle.drain()
        assert (started.task_id, started.kind, started.parent_task_id, started.agent_name) == ("sub-1", "subagent", "run-1", "researcher")
        assert (compacted.task_id, compacted.output_hash, compacted.source_hashes, compacted.kept_hashes, compacted.emitted_at) == ("sub-1", "h-sum", ("h1",), ("h2", "h3"), "2026-09-25T00:00:00+00:00")
        assert (stopped.task_id, stopped.outcome) == ("sub-1", "completed")


# --- Writer and reader on SQLite ----------------------------------------------------------


def _sqlite_factory(tmp_path: Path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ctxres.db'}")
    return async_sessionmaker(engine, expire_on_commit=False)


async def _record_a_task(ctxres, service, *, member_text=("system", "user", "tool result")):
    """Two steps; a compaction between them that removes the tool result and produces a summary."""
    R = ctxres.recorder
    inventory = ctxres.inventory.inventory
    system = SystemMessage(content=member_text[0])
    user = HumanMessage(content=member_text[1], id="user-1")
    result = ToolMessage(content=member_text[2], tool_call_id="call-1", id="tool-1")
    first = inventory("task-1", [user, result], system, [])
    summary_carrier = _stamped("<durable_context_data>…</durable_context_data>", ContentKind.DURABLE_CONTEXT, "durable_context_data", summary_content_hash=canonical_hash("the summary"))
    second = inventory("task-1", [user, summary_carrier], system, [])

    handle = service.handle
    handle.put(R.TaskStarted("task-1", "run-1", "thread-1", "lead", None, None, "2026-09-25T00:00:00+00:00"))
    handle.put(R.AttemptRequested("a1", "task-1", "s1", 1, 1, "2026-09-25T00:00:01+00:00", "m", "complete", first))
    handle.put(R.AttemptFinished("a1", "responded", "2026-09-25T00:00:02+00:00"))
    handle.put(R.StepClosed("task-1", "s1", "a1", "2026-09-25T00:00:02+00:00"))
    handle.put(
        R.CompactionObserved(
            "c1", "task-1", "run-1", "thread-1", "summarization", "1", canonical_hash("the summary"), (canonical_hash(member_text[2]),), (canonical_hash(member_text[1]),), 1, 1, "2026-09-25T00:00:03+00:00", "2026-09-25T00:00:03+00:00"
        )
    )
    handle.put(R.AttemptRequested("a2", "task-1", "s2", 2, 1, "2026-09-25T00:00:04+00:00", "m", "complete", second))
    handle.put(R.AttemptFinished("a2", "responded", "2026-09-25T00:00:05+00:00"))
    handle.put(R.StepClosed("task-1", "s2", "a2", "2026-09-25T00:00:05+00:00"))
    handle.put(R.TaskStopped("task-1", "completed", "2026-09-25T00:00:06+00:00"))
    written = await service.flush()
    assert written == 9
    return first, second


class TestWriterAndReader:
    @pytest.mark.asyncio
    async def test_the_projection_answers_attempts_blocks_and_positioned_compactions(self, ctxres, tmp_path):
        _, service = _load()
        await service.start(ExtensionRuntimeDeps(session_factory=_sqlite_factory(tmp_path)))
        try:
            first, second = await _record_a_task(ctxres, service)
            data = await ctxres.read.task_residency(service.session_factory, "task-1", 500)
        finally:
            await service.stop()

        assert data is not None and data["task_id"] == "task-1"
        assert data["task"]["outcome"] == "completed"
        assert [(a["step_seq"], a["attempt_no"], a["effective"], a["status"]) for a in data["attempts"]] == [(1, 1, True, "complete"), (2, 1, True, "complete")]
        assert [m["block_id"] for m in data["attempts"][0]["members"]] == [m.block_id for m in first]
        assert data["attempts"][0]["message_count"] == 3 and data["attempts"][0]["tool_schema_count"] == 0
        assert set(data["blocks"]) == {m.block_id for m in first} | {m.block_id for m in second}
        assert data["blocks"][first[2].block_id]["kind"] == "tool_result_visible"
        assert data["attempts_truncated"] is False

        [compaction] = data["compressions"]
        assert compaction["status"] == "positioned"
        assert compaction["positioned_before_attempt_id"] == "a2"
        assert compaction["removed_block_ids"] == [first[2].block_id]
        assert compaction["preserved_block_ids"] == [first[1].block_id]
        assert compaction["summary_block_id"] == second[2].block_id
        assert data["blocks"][second[2].block_id]["kind"] == "summary"
        assert compaction["before_tokens"] == data["attempts"][0]["estimated_tokens"]
        assert compaction["after_tokens"] == data["attempts"][1]["estimated_tokens"]

    @pytest.mark.asyncio
    async def test_the_read_cap_keeps_the_earliest_attempts_and_says_so(self, ctxres, tmp_path):
        _, service = _load()
        await service.start(ExtensionRuntimeDeps(session_factory=_sqlite_factory(tmp_path)))
        try:
            await _record_a_task(ctxres, service)
            data = await ctxres.read.task_residency(service.session_factory, "task-1", 1)
            missing = await ctxres.read.task_residency(service.session_factory, "nope", 1)
            listed = await ctxres.read.thread_tasks(service.session_factory, "thread-1")
        finally:
            await service.stop()

        assert data["attempts_truncated"] is True
        assert [a["attempt_id"] for a in data["attempts"]] == ["a1"]
        # The compaction's positioned attempt lies beyond the window: it is listed, not guessed onto the stream.
        assert data["compressions"][0]["status"] == "unanchored"
        assert data["compressions"][0]["positioned_before_attempt_id"] is None
        assert missing is None
        assert [t["task_id"] for t in listed] == ["task-1"]

    @pytest.mark.asyncio
    async def test_without_a_session_factory_the_service_stays_off(self, ctxres):
        _, service = _load()
        await service.start(ExtensionRuntimeDeps(session_factory=None))
        assert service.running is False
        assert await service.flush() == 0
        assert service.status()["running"] is False
        await service.stop()


# --- The admin routes ------------------------------------------------------------------


def _app(service, *, admin: bool) -> FastAPI:
    from deerflow_extension_context_residency.router import build_router

    app = FastAPI()
    setattr(app.state, EXTENSION_PRINCIPAL_RESOLVER_KEY, lambda request: ExtensionPrincipal("user-1", is_admin=admin))
    app.include_router(build_router(service))
    return app


class TestRoutes:
    @pytest.mark.asyncio
    async def test_reads_require_an_admin_and_a_running_service(self, ctxres, tmp_path):
        _, service = _load()

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_app(service, admin=False)), base_url="http://test") as http:
            assert (await http.get("/api/context-residency/tasks/task-1")).status_code == 403
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_app(service, admin=True)), base_url="http://test") as http:
            assert (await http.get("/api/context-residency/tasks/task-1")).status_code == 503

        await service.start(ExtensionRuntimeDeps(session_factory=_sqlite_factory(tmp_path)))
        try:
            await _record_a_task(ctxres, service)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_app(service, admin=True)), base_url="http://test") as http:
                assert (await http.get("/api/context-residency/tasks/unknown")).status_code == 404
                response = await http.get("/api/context-residency/tasks/task-1")
                listing = await http.get("/api/context-residency/threads/thread-1/tasks")
        finally:
            await service.stop()

        assert response.status_code == 200
        body = response.json()
        assert set(body) == {"task_id", "task", "attempts", "blocks", "compressions", "attempts_truncated", "projection_status"}
        assert body["projection_status"]["running"] is True and body["projection_status"]["dropped"] == 0
        assert listing.status_code == 200 and [t["task_id"] for t in listing.json()["tasks"]] == ["task-1"]
