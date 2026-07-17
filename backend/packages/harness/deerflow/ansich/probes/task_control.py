from __future__ import annotations

import logging
from datetime import UTC, datetime
from itertools import count
from threading import Lock
from uuid import uuid4

from ansich import AnsichService, ObservationEnvelope, new_id

from deerflow.runtime.user_context import get_effective_user_id

logger = logging.getLogger(__name__)

_PRODUCER_INSTANCE_ID = str(uuid4())
_PRODUCER_SEQUENCE = count(1)
_PRODUCER_SEQUENCE_LOCK = Lock()


def _next_producer_sequence() -> int:
    with _PRODUCER_SEQUENCE_LOCK:
        return next(_PRODUCER_SEQUENCE)


class TaskControlProbe:
    """Fail-open adapter from one DeerFlow Run to one Ansich Task."""

    def __init__(
        self,
        service: AnsichService | None,
        *,
        run_id: str,
        thread_id: str,
        owner_id: str | None = None,
        trigger_kind: str | None = None,
    ) -> None:
        self._service = service
        self.task_id = new_id()
        self._run_id = run_id
        self._thread_id = thread_id
        self._owner_id = owner_id
        self._trigger_kind = trigger_kind

    def created(self) -> None:
        self._record("task.created")

    def started(self) -> None:
        self._record("task.started")

    async def terminal(self, status: str) -> None:
        kind = {
            "success": "task.completed",
            "error": "task.failed",
            "interrupted": "task.interrupted",
        }.get(status)
        if kind is not None:
            self._record(kind)
        if self._service is not None:
            try:
                await self._service.flush_task(self.task_id)
            except Exception:
                logger.warning("Ansich terminal flush failed for run %s", self._run_id, exc_info=True)

    def _record(self, kind: str) -> None:
        if self._service is None:
            return
        try:
            terminal_value = kind.removeprefix("task.")
            source_event_id = f"run:{self._run_id}:task:terminal:{terminal_value}" if terminal_value in {"completed", "failed", "interrupted"} else f"run:{self._run_id}:task:{terminal_value}"
            self._service.record(
                ObservationEnvelope.task_lifecycle(
                    kind=kind,
                    task_id=self.task_id,
                    source_kind="deerflow_run",
                    source_id=self._run_id,
                    occurred_at=datetime.now(UTC),
                    source_event_id=source_event_id,
                    producer_seq=_next_producer_sequence(),
                    thread_id=self._thread_id,
                    owner_id=self._owner_id,
                    trigger_kind=self._trigger_kind,
                    producer_name="deerflow-task-control",
                    producer_version="1",
                    producer_instance_id=_PRODUCER_INSTANCE_ID,
                )
            )
        except Exception:
            logger.warning("Ansich Task observation failed for run %s", self._run_id, exc_info=True)


def create_task_control_probe(
    service: AnsichService | None,
    *,
    run_id: str,
    thread_id: str,
    config: dict,
) -> TaskControlProbe:
    context = config.get("context")
    owner_id = context.get("user_id") if isinstance(context, dict) else None
    if not isinstance(owner_id, str):
        owner_id = get_effective_user_id()
    trigger_kind = "scheduled" if isinstance(context, dict) and context.get("non_interactive") is True else "interactive"
    return TaskControlProbe(
        service,
        run_id=run_id,
        thread_id=thread_id,
        owner_id=owner_id,
        trigger_kind=trigger_kind,
    )
