from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from threading import Lock
from typing import Literal

from ansich import AnsichService, new_id

ActorKind = Literal["lead_agent", "subagent", "system_operation"]
OperationKind = Literal["title", "summarization", "memory", "goal", "other"]

ANSICH_EXECUTION_CONTEXT_KEY = "__ansich_execution_context"


@dataclass
class ExecutionCall:
    actor_kind: ActorKind
    step_id: str | None
    step_seq: int | None
    operation_id: str | None
    operation_kind: OperationKind | None
    attempt_no: int = 0
    started_obs_id: str | None = None
    last_response_obs_id: str | None = None
    effective_attempt_no: int | None = None


class AnsichExecutionContext:
    """Run-scoped Step allocator and call carrier.

    A context instance belongs to one Ansich Task. Its current logical call is
    carried by an instance-local ContextVar, so async tasks and copied sync
    contexts do not share a module-global "current Step".
    """

    def __init__(
        self,
        *,
        task_id: str,
        service: AnsichService | None = None,
        next_step_seq: int = 1,
    ) -> None:
        if next_step_seq < 1:
            raise ValueError("next_step_seq must be positive")
        self.task_id = task_id
        self.service = service
        self._next_step_seq = next_step_seq
        self._producer_seq = 0
        self._lock = Lock()
        self._current_call: ContextVar[ExecutionCall | None] = ContextVar(
            f"ansich-execution-call-{task_id}",
            default=None,
        )

    @property
    def next_step_seq(self) -> int:
        with self._lock:
            return self._next_step_seq

    def begin_call(
        self,
        *,
        actor_kind: ActorKind,
        operation_kind: OperationKind | None = None,
    ) -> ExecutionCall:
        if actor_kind == "system_operation":
            return ExecutionCall(
                actor_kind=actor_kind,
                step_id=None,
                step_seq=None,
                operation_id=new_id(),
                operation_kind=operation_kind or "other",
            )
        with self._lock:
            step_seq = self._next_step_seq
            self._next_step_seq += 1
        return ExecutionCall(
            actor_kind=actor_kind,
            step_id=new_id(),
            step_seq=step_seq,
            operation_id=None,
            operation_kind=None,
        )

    @contextmanager
    def activate(self, call: ExecutionCall):
        token = self._current_call.set(call)
        try:
            yield call
        finally:
            self._current_call.reset(token)

    def current_call(self) -> ExecutionCall | None:
        return self._current_call.get()

    def next_attempt(self, call: ExecutionCall) -> int:
        with self._lock:
            call.attempt_no += 1
            return call.attempt_no

    def next_producer_seq(self) -> int:
        with self._lock:
            self._producer_seq += 1
            return self._producer_seq
