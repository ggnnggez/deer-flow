from __future__ import annotations

from datetime import datetime
from typing import Protocol

from ansich.contracts import ControlValue, ObservationEnvelope, TaskView
from ansich.step import ContentBlockPayloadView, ContextSnapshotView, LlmAttemptView, StepView


class AnsichBackend(Protocol):
    async def persist_and_project(self, observations: list[ObservationEnvelope]) -> int: ...

    async def get_task(self, task_id: str) -> TaskView | None: ...

    async def get_task_by_source(self, source_kind: str, source_id: str) -> TaskView | None: ...

    async def list_tasks(
        self,
        *,
        limit: int = 100,
        control: ControlValue | None = None,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
        cursor: tuple[datetime, str] | None = None,
    ) -> list[TaskView]: ...

    async def list_observations(self, task_id: str) -> list[ObservationEnvelope]: ...

    async def list_timeline(
        self,
        task_id: str,
        *,
        limit: int,
        cursor: tuple[datetime, int] | None = None,
    ) -> list[tuple[int, ObservationEnvelope]]: ...

    async def get_max_step_seq(self, task_id: str) -> int: ...

    async def list_steps(self, task_id: str) -> list[StepView]: ...

    async def list_system_operations(self, task_id: str) -> list[LlmAttemptView]: ...

    async def get_step(self, step_id: str) -> StepView | None: ...

    async def get_step_context(self, step_id: str) -> ContextSnapshotView | None: ...

    async def get_content_block_payload(self, block_id: str) -> ContentBlockPayloadView | None: ...
