from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import ClassVar

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from deerflow.agents.middlewares.llm_error_handling_middleware import LLMErrorHandlingMiddleware
from deerflow.config.app_config import AppConfig
from deerflow.config.sandbox_config import SandboxConfig


class _OrderedMiddleware(AgentMiddleware):
    def __init__(self, name: str, events: list[str]) -> None:
        super().__init__()
        self._name = name
        self._events = events

    @property
    def name(self) -> str:
        return self._name

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        self._events.append(f"{self._name}.enter")
        try:
            return handler(request)
        finally:
            self._events.append(f"{self._name}.exit")

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        self._events.append(f"{self._name}.enter")
        try:
            return await handler(request)
        finally:
            self._events.append(f"{self._name}.exit")


class _OrderedModel(BaseChatModel):
    events: ClassVar[list[str]] = []

    @property
    def _llm_type(self) -> str:
        return "ansich-order-characterization"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.events.append("adapter")
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="done"))])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


class _TransientAdapterError(Exception):
    status_code = 503


class _RetryOnceModel(_OrderedModel):
    call_count: int = 0

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.call_count += 1
        self.events.append(f"adapter.{self.call_count}")
        if self.call_count == 1:
            raise _TransientAdapterError("retry me")
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="done"))])


def _retry_middleware() -> LLMErrorHandlingMiddleware:
    middleware = LLMErrorHandlingMiddleware(app_config=AppConfig(sandbox=SandboxConfig(use="test")))
    middleware.retry_max_attempts = 2
    middleware.retry_base_delay_ms = 0
    middleware.retry_cap_delay_ms = 0
    return middleware


def test_sync_model_middleware_list_wraps_first_to_last() -> None:
    events: list[str] = []
    _OrderedModel.events = events
    agent = create_agent(
        model=_OrderedModel(),
        tools=[],
        middleware=[
            _OrderedMiddleware("first", events),
            _OrderedMiddleware("second", events),
            _OrderedMiddleware("third", events),
        ],
    )

    agent.invoke({"messages": [HumanMessage(content="hello")]})

    assert events == [
        "first.enter",
        "second.enter",
        "third.enter",
        "adapter",
        "third.exit",
        "second.exit",
        "first.exit",
    ]


def test_async_model_middleware_list_wraps_first_to_last() -> None:
    events: list[str] = []
    _OrderedModel.events = events
    agent = create_agent(
        model=_OrderedModel(),
        tools=[],
        middleware=[
            _OrderedMiddleware("first", events),
            _OrderedMiddleware("second", events),
            _OrderedMiddleware("third", events),
        ],
    )

    asyncio.run(agent.ainvoke({"messages": [HumanMessage(content="hello")]}))

    assert events == [
        "first.enter",
        "second.enter",
        "third.enter",
        "adapter",
        "third.exit",
        "second.exit",
        "first.exit",
    ]


def test_sync_graph_stream_preserves_model_middleware_boundary() -> None:
    events: list[str] = []
    _OrderedModel.events = events
    agent = create_agent(
        model=_OrderedModel(),
        tools=[],
        middleware=[
            _OrderedMiddleware("decision", events),
            _OrderedMiddleware("attempt", events),
        ],
    )

    list(agent.stream({"messages": [HumanMessage(content="hello")]}, stream_mode="updates"))

    assert events == [
        "decision.enter",
        "attempt.enter",
        "adapter",
        "attempt.exit",
        "decision.exit",
    ]


def test_async_graph_stream_preserves_model_middleware_boundary() -> None:
    async def scenario() -> list[str]:
        events: list[str] = []
        _OrderedModel.events = events
        agent = create_agent(
            model=_OrderedModel(),
            tools=[],
            middleware=[
                _OrderedMiddleware("decision", events),
                _OrderedMiddleware("attempt", events),
            ],
        )

        async for _ in agent.astream(
            {"messages": [HumanMessage(content="hello")]},
            stream_mode="updates",
        ):
            pass
        return events

    assert asyncio.run(scenario()) == [
        "decision.enter",
        "attempt.enter",
        "adapter",
        "attempt.exit",
        "decision.exit",
    ]


def test_retry_reenters_only_middlewares_inside_retry_boundary() -> None:
    events: list[str] = []
    _RetryOnceModel.events = events
    agent = create_agent(
        model=_RetryOnceModel(),
        tools=[],
        middleware=[
            _OrderedMiddleware("decision", events),
            _retry_middleware(),
            _OrderedMiddleware("attempt", events),
        ],
    )

    agent.invoke({"messages": [HumanMessage(content="hello")]})

    assert events == [
        "decision.enter",
        "attempt.enter",
        "adapter.1",
        "attempt.exit",
        "attempt.enter",
        "adapter.2",
        "attempt.exit",
        "decision.exit",
    ]


def test_async_retry_uses_the_same_decision_and_attempt_boundaries() -> None:
    events: list[str] = []
    _RetryOnceModel.events = events
    agent = create_agent(
        model=_RetryOnceModel(),
        tools=[],
        middleware=[
            _OrderedMiddleware("decision", events),
            _retry_middleware(),
            _OrderedMiddleware("attempt", events),
        ],
    )

    asyncio.run(agent.ainvoke({"messages": [HumanMessage(content="hello")]}))

    assert events == [
        "decision.enter",
        "attempt.enter",
        "adapter.1",
        "attempt.exit",
        "attempt.enter",
        "adapter.2",
        "attempt.exit",
        "decision.exit",
    ]
