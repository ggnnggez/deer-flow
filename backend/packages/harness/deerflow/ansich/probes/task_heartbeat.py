from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime
from itertools import count
from threading import Lock
from uuid import uuid4

from ansich import AnsichService, ObservationEnvelope

logger = logging.getLogger(__name__)

_PRODUCER_INSTANCE_ID = str(uuid4())
_PRODUCER_SEQUENCE = count(1)
_PRODUCER_SEQUENCE_LOCK = Lock()


def _next_producer_sequence() -> int:
    with _PRODUCER_SEQUENCE_LOCK:
        return next(_PRODUCER_SEQUENCE)


class AnsichTaskHeartbeat:
    """Emit liveness evidence outside the Agent graph stream.

    The loop is deliberately fail-open: observation construction or collector
    rejection cannot affect the DeerFlow Run. Ownership is checked on every
    tick so a worker stops producing active evidence after losing the Run.
    """

    def __init__(
        self,
        service: AnsichService,
        *,
        task_id: str,
        run_id: str,
        interval_seconds: float,
        worker_id: str,
        ownership_epoch: str,
        is_owner: Callable[[], bool],
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        self._service = service
        self._task_id = task_id
        self._run_id = run_id
        self._interval_seconds = interval_seconds
        self._worker_id = worker_id
        self._ownership_epoch = ownership_epoch
        self._is_owner = is_owner
        self._started_at = time.monotonic()
        self._tick = 0
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(
            self._run(),
            name=f"ansich-task-heartbeat:{self._run_id}",
        )

    async def stop(self) -> None:
        self._stop_event.set()
        task = self._task
        if task is None:
            return
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.warning(
                "Ansich heartbeat shutdown failed for run %s",
                self._run_id,
                exc_info=True,
            )
        finally:
            self._task = None

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self._interval_seconds,
                )
                return
            except TimeoutError:
                pass

            if not self._is_owner():
                logger.info(
                    "Run %s no longer belongs to worker %s; stopping Ansich heartbeat",
                    self._run_id,
                    self._worker_id,
                )
                return
            self._record_tick()

    def _record_tick(self) -> None:
        try:
            self._tick += 1
            elapsed_ms = max(0, int((time.monotonic() - self._started_at) * 1000))
            self._service.record(
                ObservationEnvelope.task_heartbeat(
                    task_id=self._task_id,
                    run_id=self._run_id,
                    occurred_at=datetime.now(UTC),
                    elapsed_ms=elapsed_ms,
                    worker_id=self._worker_id,
                    ownership_epoch=self._ownership_epoch,
                    source_event_id=f"run:{self._run_id}:task:heartbeat:{self._tick}",
                    producer_seq=_next_producer_sequence(),
                    producer_name="deerflow-task-heartbeat",
                    producer_version="1",
                    producer_instance_id=_PRODUCER_INSTANCE_ID,
                )
            )
        except Exception:
            logger.warning(
                "Ansich heartbeat observation failed for run %s",
                self._run_id,
                exc_info=True,
            )
