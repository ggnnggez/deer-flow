"""Compaction destroys the mapping it is observed by.

Summarization replaces N messages with one summary. After the fact, only the
summary survives, so 'which messages became this summary' is not reconstructible
from state — it has to be emitted at the moment of the transform.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from deerflow_extension_api import CompactionEvent, canonical_hash


def test_event_records_both_ends_of_the_transform():
    event = CompactionEvent(
        transform_kind="summarization",
        transform_version="1",
        source_content_hashes=("h1", "h2"),
        output_content_hash="h3",
        compacted_message_count=2,
        kept_message_count=4,
    )
    assert event.source_content_hashes == ("h1", "h2")
    assert event.output_content_hash == "h3"


def test_identity_and_kept_hashes_default_to_absent_for_older_emitters():
    """Additive contract release: an event built with only the 0.2.0 fields still constructs,
    and every field added since reads as "not known" rather than as a value."""
    event = CompactionEvent(
        transform_kind="summarization",
        transform_version="1",
        source_content_hashes=("h1",),
        output_content_hash="h3",
        compacted_message_count=1,
        kept_message_count=1,
    )
    assert event.task_id is None
    assert event.run_id is None
    assert event.thread_id is None
    assert event.kept_content_hashes == ()
    assert event.emitted_at is None


def test_source_hashes_are_a_tuple_so_the_event_cannot_be_mutated_after_emission():
    event = CompactionEvent(
        transform_kind="summarization",
        transform_version="1",
        source_content_hashes=("h1",),
        output_content_hash="h3",
        compacted_message_count=1,
        kept_message_count=1,
    )
    with pytest.raises(AttributeError):
        event.output_content_hash = "other"


_UNOBSERVED = object()


def _observed_extensions(observer=None):
    """A real ``LoadedExtensions`` carrying one compaction observer.

    ``replace`` on the ambient set rather than a hand-built stub: the
    middleware reads other fields off ``_extensions`` too (the system-model
    call path), so a namespace carrying only the observer tuple would pass
    these tests while diverging from what the middleware is handed in
    production.
    """
    from dataclasses import replace

    from deerflow.extensions import get_agent_build_extensions

    return replace(get_agent_build_extensions(), context_compaction_observers=(("test-source", observer or (lambda event, context=None: None)),))


def test_source_hashes_are_computed_on_content_directly_not_a_stringified_copy():
    """Regression: hashing ``str(message.content)`` would defeat canonical_hash's
    key-order normalization for multimodal (``list[dict]``) content, which
    ``view_image_middleware`` and other producers routinely inject. Two
    logically identical messages whose dict content differs only in key
    insertion order must hash the same.
    """
    from langchain_core.messages import HumanMessage

    from deerflow.agents.middlewares.summarization_middleware import DeerFlowSummarizationMiddleware

    a = HumanMessage(content=[{"type": "text", "text": "hi"}, {"b": 1, "a": 2}])
    b = HumanMessage(content=[{"type": "text", "text": "hi"}, {"a": 2, "b": 1}])

    middleware = DeerFlowSummarizationMiddleware(model=MagicMock(), extensions=_observed_extensions())
    hashes = middleware._freeze_compaction_sources([a, b])
    assert hashes[0] == hashes[1]
    assert hashes[0] == canonical_hash(a.content)
    # str() on a dict renders insertion order, so the pre-stringified form
    # this guards against would not have matched.
    assert str(a.content) != str(b.content)


# --- Driving a real compaction --------------------------------------------
#
# Mirrors tests/test_summarization_middleware.py's `_messages` / `_middleware` /
# `_runtime` fixture helpers rather than inventing a second way to drive the
# middleware: a static model, `token_counter=len`, and a runtime carrying a
# plain `context` mapping.


def _messages() -> list:
    from langchain_core.messages import AIMessage, HumanMessage

    return [
        HumanMessage(content="user-1"),
        AIMessage(content="assistant-1"),
        HumanMessage(content="user-2"),
        AIMessage(content="assistant-2"),
    ]


def _runtime(thread_id: str | None = "thread-1", run_id: str | None = "run-1", task_store=None) -> SimpleNamespace:
    context = {}
    if thread_id is not None:
        context["thread_id"] = thread_id
    if run_id is not None:
        context["run_id"] = run_id
    if task_store is not None:
        from deerflow_extension_api import EXTENSION_TASK_STORE_KEY

        context[EXTENSION_TASK_STORE_KEY] = task_store
    return SimpleNamespace(context=context)


def _middleware(*, trigger=("messages", 4), keep=("messages", 2), extensions=_UNOBSERVED):
    from deerflow.agents.middlewares.summarization_middleware import DeerFlowSummarizationMiddleware

    model = MagicMock()
    model.invoke.return_value = SimpleNamespace(text="compressed summary")
    model.ainvoke = AsyncMock(return_value=SimpleNamespace(text="compressed summary"))
    model.with_config.return_value = model
    return DeerFlowSummarizationMiddleware(
        model=model,
        trigger=trigger,
        keep=keep,
        token_counter=len,
        extensions=_observed_extensions() if extensions is _UNOBSERVED else extensions,
    )


class TestSummarizationEmitsTheEvent:
    @pytest.mark.asyncio
    async def test_a_compaction_notifies_observers_once(self, monkeypatch):
        from deerflow.agents.middlewares import summarization_middleware

        events = []
        monkeypatch.setattr(
            summarization_middleware,
            "notify_context_compacted",
            lambda event, extensions=None: events.append(event),
        )
        middleware = _middleware()

        result = await middleware.abefore_model({"messages": _messages()}, _runtime())

        assert result is not None
        assert len(events) == 1
        event = events[0]
        assert event.transform_kind == "summarization"
        assert event.compacted_message_count == 2
        assert event.kept_message_count == 2
        assert event.source_content_hashes == (
            canonical_hash("user-1"),
            canonical_hash("assistant-1"),
        )
        assert event.output_content_hash == canonical_hash("compressed summary")
        # The kept side is captured at the same moment as the removed side: after
        # this turn the preserved tail is all that is left, so "which messages
        # survived this compaction" is only knowable here.
        assert event.kept_content_hashes == (
            canonical_hash("user-2"),
            canonical_hash("assistant-2"),
        )
        assert event.thread_id == "thread-1"
        assert event.run_id == "run-1"
        assert event.task_id is None, "no task store on this runtime: the host must not guess a task id"
        emitted = datetime.fromisoformat(event.emitted_at)
        assert emitted.tzinfo is not None and emitted.utcoffset() == timedelta(0)

    @pytest.mark.asyncio
    async def test_no_event_is_emitted_when_the_trigger_does_not_fire(self, monkeypatch):
        from deerflow.agents.middlewares import summarization_middleware

        events = []
        monkeypatch.setattr(
            summarization_middleware,
            "notify_context_compacted",
            lambda event, extensions=None: events.append(event),
        )
        # A trigger threshold far above the message count never fires, so
        # compaction never runs and the record half is never reached.
        middleware = _middleware(trigger=("messages", 100))

        result = await middleware.abefore_model({"messages": _messages()}, _runtime())

        assert result is None
        assert events == []


class TestTheEventNamesTheTaskItHappenedIn:
    """Observers receive a detached store, so the task identity has to ride in the event.

    The host seeds every task store with the scope's ``TaskInfo`` before any hook
    runs; the compaction seam reads it back through the runtime the middleware
    already holds. Without a seeded store the field stays ``None`` — the host never
    guesses (a subagent's task id is not its run id).
    """

    @pytest.mark.asyncio
    async def test_a_seeded_task_store_yields_the_task_id(self, monkeypatch):
        from deerflow_extension_api import ExtensionData, TaskInfo

        from deerflow.agents.middlewares import summarization_middleware

        events = []
        monkeypatch.setattr(summarization_middleware, "notify_context_compacted", lambda event, extensions=None: events.append(event))
        store = ExtensionData("call-7")
        store.set(TaskInfo(task_id="sub-9", run_id="run-1", thread_id="thread-1", kind="subagent", parent_task_id="run-1"))

        result = await _middleware().abefore_model({"messages": _messages()}, _runtime(task_store=store))

        assert result is not None
        [event] = events
        assert event.task_id == "sub-9"
        assert event.run_id == "run-1"
        assert event.thread_id == "thread-1"

    @pytest.mark.asyncio
    async def test_an_unseeded_store_leaves_the_task_id_absent(self, monkeypatch):
        from deerflow_extension_api import ExtensionData

        from deerflow.agents.middlewares import summarization_middleware

        events = []
        monkeypatch.setattr(summarization_middleware, "notify_context_compacted", lambda event, extensions=None: events.append(event))

        await _middleware().abefore_model({"messages": _messages()}, _runtime(task_store=ExtensionData("run-1")))

        [event] = events
        assert event.task_id is None

    def test_the_sync_path_carries_the_same_identity(self, monkeypatch):
        from deerflow_extension_api import ExtensionData, TaskInfo

        from deerflow.agents.middlewares import summarization_middleware

        events = []
        monkeypatch.setattr(summarization_middleware, "notify_context_compacted", lambda event, extensions=None: events.append(event))
        store = ExtensionData("run-1")
        store.set(TaskInfo(task_id="run-1", run_id="run-1", thread_id="thread-1", kind="lead"))

        result = _middleware().before_model({"messages": _messages()}, _runtime(task_store=store))

        assert result is not None
        [event] = events
        assert event.task_id == "run-1"
        assert event.kept_content_hashes == (canonical_hash("user-2"), canonical_hash("assistant-2"))
        assert event.emitted_at is not None


class TestTheSummaryCarrierJoinsTheEvent:
    """The compaction records the summary's identity next to the summary text, and
    the message that later renders the summary declares that same identity — so a
    consumer joins event to carrier by equality, never by re-hashing a bounded,
    escaped rendering (the trap ``compaction.py`` documents)."""

    @pytest.mark.asyncio
    async def test_the_state_update_records_the_hash_the_event_carries(self, monkeypatch):
        from deerflow.agents.middlewares import summarization_middleware

        events = []
        monkeypatch.setattr(summarization_middleware, "notify_context_compacted", lambda event, extensions=None: events.append(event))

        update = await _middleware().abefore_model({"messages": _messages()}, _runtime())

        [event] = events
        assert update["summary_content_hash"] == event.output_content_hash == canonical_hash("compressed summary")

    @pytest.mark.asyncio
    async def test_the_durable_context_block_declares_that_hash(self, monkeypatch):
        from deerflow_extension_api import read_provenance
        from langchain.agents.middleware.types import ModelRequest

        from deerflow.agents.middlewares import summarization_middleware
        from deerflow.agents.middlewares.durable_context_middleware import DurableContextMiddleware

        events = []
        monkeypatch.setattr(summarization_middleware, "notify_context_compacted", lambda event, extensions=None: events.append(event))
        update = await _middleware().abefore_model({"messages": _messages()}, _runtime())

        request = ModelRequest(
            model=SimpleNamespace(),
            messages=[],
            state={
                "summary_text": update["summary_text"],
                "summary_content_hash": update["summary_content_hash"],
                "delegations": [],
                "skill_context": [],
            },
        )
        carriers = [m for m in DurableContextMiddleware()._inject(request).messages if "durable_context_data" in (m.additional_kwargs or {})]
        assert carriers, "expected the durable-context data block"
        assert read_provenance(carriers[0]).summary_content_hash == events[0].output_content_hash

    def test_the_thread_state_declares_the_channel(self):
        from typing import get_type_hints

        from deerflow.agents.thread_state import ThreadState

        assert "summary_content_hash" in get_type_hints(ThreadState)


class TestAnInstallWithNoObserverPaysNothing:
    """Hashing the sources is an O(context-size) canonical-JSON pass.

    Every install runs this middleware; almost none of them register a
    compaction observer. The check cannot live in ``notify_context_compacted``
    — by the time it is called the hashing has already happened — so the freeze
    site has to make it itself.
    """

    def test_the_sources_are_not_hashed_when_nothing_observes(self):
        from dataclasses import replace

        from deerflow.extensions import get_agent_build_extensions

        unobserved = replace(get_agent_build_extensions(), context_compaction_observers=())
        middleware = _middleware(extensions=unobserved)

        assert middleware._freeze_compaction_sources(_messages()) == ()

    def test_the_sources_are_hashed_when_an_observer_is_registered(self):
        middleware = _middleware(extensions=_observed_extensions())

        assert middleware._freeze_compaction_sources(_messages()) == tuple(canonical_hash(m.content) for m in _messages())

    @pytest.mark.asyncio
    async def test_the_compaction_itself_still_happens_unobserved(self, monkeypatch):
        """The skip must cost the run nothing but the hashes."""
        from dataclasses import replace

        from deerflow.agents.middlewares import summarization_middleware
        from deerflow.extensions import get_agent_build_extensions

        events = []
        monkeypatch.setattr(summarization_middleware, "notify_context_compacted", lambda event, extensions=None: events.append(event))
        unobserved = replace(get_agent_build_extensions(), context_compaction_observers=())

        result = await _middleware(extensions=unobserved).abefore_model({"messages": _messages()}, _runtime())

        assert result is not None, "compaction must still run; only the observation bookkeeping is skipped"
        # The middleware still calls notify (which would itself no-op on the
        # empty observer tuple); what it must not do is compute the hashes.
        assert [e.source_content_hashes for e in events] == [()]
        assert [e.kept_content_hashes for e in events] == [()]
