"""Events the hooks emit and the buffer that carries them to the writer."""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime

from .inventory import Member


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class TaskStarted:
    task_id: str
    run_id: str
    thread_id: str
    kind: str
    parent_task_id: str | None
    agent_name: str | None
    started_at: str


@dataclass(frozen=True)
class TaskStopped:
    task_id: str
    outcome: str
    stopped_at: str


@dataclass(frozen=True)
class AttemptRequested:
    attempt_id: str
    task_id: str
    step_id: str
    step_seq: int
    attempt_no: int
    occurred_at: str
    model_name: str | None
    #: ``complete`` when every member serialized; ``incomplete`` when a member
    #: could not be — an absence in an incomplete inventory is unknown, not a removal.
    status: str
    members: tuple[Member, ...]


@dataclass(frozen=True)
class AttemptFinished:
    attempt_id: str
    #: ``responded`` or ``failed`` — the provider call's outcome, separate from
    #: the inventory's completeness.
    outcome: str
    finished_at: str


@dataclass(frozen=True)
class StepClosed:
    task_id: str
    step_id: str
    #: The attempt whose response this decision returned; ``None`` when every
    #: attempt failed.
    effective_attempt_id: str | None
    closed_at: str


@dataclass(frozen=True)
class CompactionObserved:
    compaction_id: str
    task_id: str | None
    run_id: str | None
    thread_id: str | None
    transform_kind: str
    transform_version: str
    output_hash: str
    source_hashes: tuple[str, ...]
    kept_hashes: tuple[str, ...]
    compacted_count: int
    kept_count: int
    emitted_at: str
    observed_at: str


Event = TaskStarted | TaskStopped | AttemptRequested | AttemptFinished | StepClosed | CompactionObserved


class RecorderHandle:
    """What every hook writes to and the service drains.

    Thread-safe and loop-agnostic on purpose: model-call hooks run inside the
    agent graph (on a worker thread for synchronous execution, on a subagent's
    own loop for delegated work) while the writer runs on the Gateway loop. A
    full buffer drops the event and counts it — a hook must never block the
    model turn on storage, and a silent drop would be worse than a counted one.
    """

    def __init__(self, capacity: int) -> None:
        self._capacity = capacity
        self._events: deque[Event] = deque()
        self._lock = threading.Lock()
        self.accepted = 0
        self.dropped = 0

    def put(self, event: Event) -> bool:
        with self._lock:
            if len(self._events) >= self._capacity:
                self.dropped += 1
                return False
            self._events.append(event)
            self.accepted += 1
            return True

    def drain(self, limit: int | None = None) -> list[Event]:
        with self._lock:
            if limit is None or limit >= len(self._events):
                events = list(self._events)
                self._events.clear()
                return events
            return [self._events.popleft() for _ in range(limit)]

    @property
    def depth(self) -> int:
        with self._lock:
            return len(self._events)
