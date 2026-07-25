"""Shared fault-injection harness for the Ansich retro validation matrix.

See ``ansich/docs/plans/retro-validation-matrix.md``. These helpers deliberately
drive the real ``AnsichService`` over SQLite with production foreign-key
semantics; nothing inside Ansich is mocked, because the matrix is testing
whether the read models can answer on their own.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from ansich import AnsichService, ObservationEnvelope, Producer, new_id
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from deerflow.ansich import create_sql_ansich_service
from deerflow.persistence.base import Base

RETRO_PRODUCER = Producer(name="ansich-retro", version="1", instance_id="retro-test")


@asynccontextmanager
async def retro_service(tmp_path, name: str) -> AsyncIterator[AnsichService]:
    """Start a SQLite-backed Ansich service with production foreign-key semantics."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / f'{name}.db'}")

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(session_factory)
    await service.start()
    try:
        yield service
    finally:
        await service.stop()
        await engine.dispose()


async def open_task(
    service: AnsichService,
    source_id: str,
    *,
    source_kind: str = "deerflow_run",
    occurred_at: datetime | None = None,
) -> str:
    """Record task.created exactly as run admission does, then settle projections."""
    task_id = new_id()
    service.record(
        ObservationEnvelope.task_lifecycle(
            kind="task.created",
            task_id=task_id,
            source_kind=source_kind,
            source_id=source_id,
            occurred_at=occurred_at or datetime.now(UTC),
            source_event_id=f"{source_kind}:{source_id}:task:created",
            producer_seq=1,
        )
    )
    await service.flush_task(task_id)
    return task_id


async def close_task(
    service: AnsichService,
    task_id: str,
    *,
    source_id: str,
    kind: str = "task.completed",
    occurred_at: datetime | None = None,
) -> None:
    """Record the terminal signal the run worker emits, then settle projections."""
    service.record(
        ObservationEnvelope.task_lifecycle(
            kind=kind,
            task_id=task_id,
            source_kind="deerflow_run",
            source_id=source_id,
            occurred_at=occurred_at or datetime.now(UTC),
            source_event_id=f"deerflow_run:{source_id}:task:{kind}",
            producer_seq=2,
        )
    )
    await service.flush_task(task_id)


class ErrorFallbackModel(BaseChatModel):
    """Reproduce what LLMErrorHandlingMiddleware emits after retry exhaustion (#3320/#4041)."""

    @property
    def _llm_type(self) -> str:
        return "ansich-retro-error-fallback"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(
            generations=[
                ChatGeneration(
                    message=AIMessage(
                        content="LLM request failed: Error code: 400 - provider unavailable",
                        additional_kwargs={"deerflow_error_fallback": True},
                        response_metadata={"finish_reason": "stop", "model_name": "retro-failing-model"},
                    )
                )
            ]
        )

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


class PlainAnswerModel(BaseChatModel):
    """A normal successful final answer, used as the control arm."""

    provider_model: str = "retro-model"

    @property
    def _llm_type(self) -> str:
        return "ansich-retro-plain"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(
            generations=[
                ChatGeneration(
                    message=AIMessage(
                        content="done",
                        usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                        response_metadata={"finish_reason": "stop", "model_name": self.provider_model},
                    )
                )
            ]
        )

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
