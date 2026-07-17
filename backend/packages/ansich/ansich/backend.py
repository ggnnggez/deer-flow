from __future__ import annotations

from datetime import datetime
from typing import Protocol

from ansich.contracts import ControlValue, ObservationEnvelope, TaskView


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
