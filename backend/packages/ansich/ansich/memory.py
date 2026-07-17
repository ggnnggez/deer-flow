from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from ansich.contracts import ControlBelief, ControlValue, NamedVersion, ObservationEnvelope, TaskView
from ansich.control import should_select_control_candidate

_CONTROL_BY_KIND = {
    "task.created": "created",
    "task.started": "running",
    "task.completed": "completed",
    "task.failed": "failed",
    "task.interrupted": "interrupted",
}


class InMemoryAnsichBackend:
    def __init__(self) -> None:
        self._seen: set[tuple[str, str, str]] = set()
        self._tasks: dict[str, TaskView] = {}
        self._observations: list[ObservationEnvelope] = []

    async def persist_and_project(self, observations: list[ObservationEnvelope]) -> int:
        processed = 0
        for observation in observations:
            dedupe_key = (
                observation.producer.name,
                observation.producer.instance_id,
                observation.source_event_id,
            )
            if dedupe_key in self._seen:
                continue
            self._seen.add(dedupe_key)
            self._observations.append(observation)
            self._project(observation)
            processed += 1
        return processed

    async def get_task(self, task_id: str) -> TaskView | None:
        return self._tasks.get(task_id)

    async def get_task_by_source(self, source_kind: str, source_id: str) -> TaskView | None:
        return next(
            (task for task in self._tasks.values() if task.source_kind == source_kind and task.source_id == source_id),
            None,
        )

    async def list_tasks(
        self,
        *,
        limit: int = 100,
        control: ControlValue | None = None,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
        cursor: tuple[datetime, str] | None = None,
    ) -> list[TaskView]:
        tasks = list(self._tasks.values())
        if control is not None:
            tasks = [task for task in tasks if task.control.value == control]
        if from_time is not None:
            tasks = [task for task in tasks if task.control.as_of is not None and task.control.as_of >= from_time]
        if to_time is not None:
            tasks = [task for task in tasks if task.control.as_of is not None and task.control.as_of <= to_time]
        if cursor is not None:
            cursor_time, cursor_task_id = cursor
            tasks = [task for task in tasks if task.control.as_of is not None and (task.control.as_of < cursor_time or (task.control.as_of == cursor_time and task.task_id > cursor_task_id))]
        tasks.sort(key=lambda task: task.task_id)
        tasks.sort(
            key=lambda task: task.control.as_of or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )
        return tasks[:limit]

    async def list_observations(self, task_id: str) -> list[ObservationEnvelope]:
        return [observation for observation in self._observations if observation.task_id == task_id]

    def _project(self, observation: ObservationEnvelope) -> None:
        if observation.kind not in _CONTROL_BY_KIND or observation.payload is None:
            return
        existing = self._tasks.get(observation.task_id)
        candidate = cast(ControlValue, _CONTROL_BY_KIND[observation.kind])
        if not should_select_control_candidate(
            current_value=None if existing is None else existing.control.value,
            current_as_of=None if existing is None else existing.control.as_of,
            candidate_value=candidate,
            candidate_as_of=observation.occurred_at,
        ):
            return

        control = ControlBelief(
            value=candidate,
            as_of=observation.occurred_at,
            asserted_at=datetime.now(UTC),
            source=NamedVersion(name="task-control", version="1"),
            fidelity_class="hard",
            selected_by=NamedVersion(name="control-state", version="1"),
            evidence_obs_ids=(observation.obs_id,),
        )
        self._tasks[observation.task_id] = TaskView(
            task_id=observation.task_id,
            source_kind=str(observation.payload["source_kind"]),
            source_id=str(observation.payload["source_id"]),
            control=control,
        )
