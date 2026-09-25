"""Task rows from the lifecycle hooks; compaction rows from the compaction observer."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from .options import Options
from .recorder import CompactionObserved, RecorderHandle, TaskStarted, TaskStopped, now_iso


class ResidencyLifecycle:
    def __init__(self, handle: RecorderHandle, options: Options) -> None:
        self._handle = handle
        self._options = options

    async def on_task_start(self, app_store: Any, task_store: Any, info: Any) -> None:
        if not self._options.enabled:
            return
        self._handle.put(
            TaskStarted(
                task_id=info.task_id,
                run_id=info.run_id,
                thread_id=info.thread_id,
                kind=str(info.kind),
                parent_task_id=info.parent_task_id,
                agent_name=info.agent_name,
                started_at=now_iso(),
            )
        )

    async def on_task_stop(self, app_store: Any, task_store: Any, info: Any, outcome: Any) -> None:
        if not self._options.enabled:
            return
        self._handle.put(TaskStopped(task_id=info.task_id, outcome=str(getattr(outcome, "value", outcome)), stopped_at=now_iso()))


class ResidencyCompactionObserver:
    """Records the event exactly as emitted; positioning happens at read time."""

    def __init__(self, handle: RecorderHandle, options: Options) -> None:
        self._handle = handle
        self._options = options

    async def on_context_compacted(self, app_store: Any, task_store: Any, event: Any) -> None:
        if not self._options.enabled:
            return
        observed_at = now_iso()
        self._handle.put(
            CompactionObserved(
                compaction_id=uuid4().hex,
                task_id=getattr(event, "task_id", None),
                run_id=getattr(event, "run_id", None),
                thread_id=getattr(event, "thread_id", None),
                transform_kind=event.transform_kind,
                transform_version=event.transform_version,
                output_hash=event.output_content_hash,
                source_hashes=tuple(event.source_content_hashes),
                kept_hashes=tuple(getattr(event, "kept_content_hashes", ()) or ()),
                compacted_count=event.compacted_message_count,
                kept_count=event.kept_message_count,
                emitted_at=getattr(event, "emitted_at", None) or observed_at,
                observed_at=observed_at,
            )
        )
