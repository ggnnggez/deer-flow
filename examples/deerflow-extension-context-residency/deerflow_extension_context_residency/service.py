"""Gateway-lifetime writer: drains the recorder buffer into the extension's tables."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy import insert, update

from .inventory import ESTIMATOR_NAME, ESTIMATOR_VERSION
from .options import Options
from .recorder import (
    AttemptFinished,
    AttemptRequested,
    CompactionObserved,
    Event,
    RecorderHandle,
    StepClosed,
    TaskStarted,
    TaskStopped,
)
from .store import attempts, compactions, members, metadata, tasks

logger = logging.getLogger(__name__)


class ResidencyService:
    """Creates the tables at start and flushes buffered events every interval.

    Hooks never touch the database: they append to the buffer and return. The
    writer runs on the Gateway loop, so the session factory is only ever used on
    the loop that owns it. A failed write drops that batch and counts it; the
    next flush carries on with whatever arrived since.
    """

    def __init__(self, handle: RecorderHandle, options: Options) -> None:
        self.handle = handle
        self.options = options
        self.session_factory: Any | None = None
        self._writer_task: asyncio.Task[None] | None = None
        self._stopping = False
        self.flushed = 0
        self.write_failures = 0

    @property
    def running(self) -> bool:
        return self.session_factory is not None

    async def start(self, deps: Any) -> None:
        session_factory = getattr(deps, "session_factory", None)
        if session_factory is None:
            logger.warning("context-residency: the host has no database session factory (database.backend is memory); capture is off and reads answer 503")
            return
        self.session_factory = session_factory
        await self.ensure_schema()
        self._stopping = False
        self._writer_task = asyncio.create_task(self._writer(), name="context-residency-writer")

    async def ensure_schema(self) -> None:
        assert self.session_factory is not None
        async with self.session_factory() as session:
            connection = await session.connection()
            await connection.run_sync(lambda sync_connection: metadata.create_all(sync_connection))
            await session.commit()

    async def stop(self) -> None:
        self._stopping = True
        if self._writer_task is not None:
            self._writer_task.cancel()
            try:
                await self._writer_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001 - a dying writer must not block shutdown
                pass
            self._writer_task = None
        try:
            await self.flush()
        finally:
            self.session_factory = None

    async def _writer(self) -> None:
        interval = self.options.flush_interval_ms / 1000
        while not self._stopping:
            await asyncio.sleep(interval)
            try:
                await self.flush()
            except Exception:  # noqa: BLE001 - logged; the loop must survive one bad batch
                logger.exception("context-residency: flush failed")

    async def flush(self) -> int:
        """Write everything buffered so far; returns how many events were written."""
        if self.session_factory is None:
            return 0
        events = self.handle.drain()
        if not events:
            return 0
        try:
            async with self.session_factory() as session:
                async with session.begin():
                    for event in events:
                        await self._apply(session, event)
        except Exception:  # noqa: BLE001 - counted, never re-raised into the loop
            self.write_failures += len(events)
            logger.exception("context-residency: dropped %d event(s) after a failed write", len(events))
            return 0
        self.flushed += len(events)
        return len(events)

    async def _apply(self, session: Any, event: Event) -> None:
        if isinstance(event, TaskStarted):
            values = {
                "run_id": event.run_id,
                "thread_id": event.thread_id,
                "kind": event.kind,
                "parent_task_id": event.parent_task_id,
                "agent_name": event.agent_name,
                "started_at": event.started_at,
            }
            result = await session.execute(update(tasks).where(tasks.c.task_id == event.task_id).values(**values))
            if result.rowcount == 0:
                await session.execute(insert(tasks).values(task_id=event.task_id, **values))
        elif isinstance(event, TaskStopped):
            await session.execute(update(tasks).where(tasks.c.task_id == event.task_id).values(outcome=event.outcome, stopped_at=event.stopped_at))
        elif isinstance(event, AttemptRequested):
            message_members = [member for member in event.members if member.channel == "message"]
            await session.execute(
                insert(attempts).values(
                    attempt_id=event.attempt_id,
                    task_id=event.task_id,
                    step_id=event.step_id,
                    step_seq=event.step_seq,
                    attempt_no=event.attempt_no,
                    effective=False,
                    status=event.status,
                    outcome=None,
                    occurred_at=event.occurred_at,
                    finished_at=None,
                    model_name=event.model_name,
                    message_count=len(message_members),
                    tool_schema_count=len(event.members) - len(message_members),
                    visible_bytes=sum(member.visible_bytes for member in event.members),
                    estimated_tokens=sum(member.estimated_tokens for member in event.members),
                    estimator_name=ESTIMATOR_NAME,
                    estimator_version=ESTIMATOR_VERSION,
                )
            )
            if event.members:
                await session.execute(
                    insert(members),
                    [
                        {
                            "attempt_id": event.attempt_id,
                            "ordinal": member.ordinal,
                            "block_id": member.block_id,
                            "channel": member.channel,
                            "role": member.role,
                            "kind": member.kind,
                            "name": member.name,
                            "content_hash": member.content_hash,
                            "source_identity": member.source_identity,
                            "summary_content_hash": member.summary_content_hash,
                            "visible_bytes": member.visible_bytes,
                            "estimated_tokens": member.estimated_tokens,
                        }
                        for member in event.members
                    ],
                )
        elif isinstance(event, AttemptFinished):
            await session.execute(update(attempts).where(attempts.c.attempt_id == event.attempt_id).values(outcome=event.outcome, finished_at=event.finished_at))
        elif isinstance(event, StepClosed):
            if event.effective_attempt_id is not None:
                await session.execute(update(attempts).where(attempts.c.attempt_id == event.effective_attempt_id).values(effective=True))
        elif isinstance(event, CompactionObserved):
            await session.execute(
                insert(compactions).values(
                    compaction_id=event.compaction_id,
                    task_id=event.task_id,
                    run_id=event.run_id,
                    thread_id=event.thread_id,
                    transform_kind=event.transform_kind,
                    transform_version=event.transform_version,
                    output_hash=event.output_hash,
                    source_hashes=list(event.source_hashes),
                    kept_hashes=list(event.kept_hashes),
                    compacted_count=event.compacted_count,
                    kept_count=event.kept_count,
                    emitted_at=event.emitted_at,
                    observed_at=event.observed_at,
                )
            )

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.options.enabled,
            "running": self.running,
            "queue_depth": self.handle.depth,
            "accepted": self.handle.accepted,
            "dropped": self.handle.dropped,
            "flushed": self.flushed,
            "write_failures": self.write_failures,
            "estimator": f"{ESTIMATOR_NAME}@{ESTIMATOR_VERSION}",
            "max_attempts": self.options.max_attempts,
        }
