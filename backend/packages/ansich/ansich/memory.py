from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from ansich.contracts import ControlBelief, ControlValue, NamedVersion, ObservationEnvelope, TaskView
from ansich.control import should_select_control_candidate
from ansich.step import ContentBlockPayloadView, ContextSnapshotItemView, ContextSnapshotView, LlmAttemptView, StepView

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

    async def list_timeline(
        self,
        task_id: str,
        *,
        limit: int,
        cursor: tuple[datetime, int] | None = None,
    ) -> list[tuple[int, ObservationEnvelope]]:
        items = [(ingest_seq, observation) for ingest_seq, observation in enumerate(self._observations, start=1) if observation.task_id == task_id]
        items.sort(key=lambda item: (item[1].occurred_at, item[0]))
        if cursor is not None:
            items = [item for item in items if (item[1].occurred_at, item[0]) > cursor]
        return items[:limit]

    async def get_max_step_seq(self, task_id: str) -> int:
        return max(
            (
                int(observation.payload["step_seq"])
                for observation in self._observations
                if observation.task_id == task_id and observation.kind == "step.started" and observation.payload is not None and isinstance(observation.payload.get("step_seq"), int)
            ),
            default=0,
        )

    async def list_steps(self, task_id: str) -> list[StepView]:
        started = [observation for observation in self._observations if observation.task_id == task_id and observation.kind == "step.started"]
        views = [self._step_view(observation) for observation in started]
        return sorted(views, key=lambda step: step.step_seq)

    async def list_system_operations(self, task_id: str) -> list[LlmAttemptView]:
        attempts: list[LlmAttemptView] = []
        for request in self._observations:
            if request.task_id != task_id or request.kind != "llm.requested" or request.step_id is not None or request.payload is None:
                continue
            response = next(
                (observation for observation in self._observations if observation.subject_id == request.subject_id and observation.kind in {"llm.responded", "llm.failed"}),
                None,
            )
            snapshot = next(
                (observation for observation in self._observations if observation.kind == "context.snapshotted" and observation.payload is not None and observation.payload.get("attempt_id") == request.subject_id),
                None,
            )
            response_payload = {} if response is None or response.payload is None else response.payload
            attempts.append(
                LlmAttemptView(
                    attempt_id=request.subject_id,
                    task_id=request.task_id,
                    step_id=None,
                    actor_kind="system_operation",
                    operation_id=request.payload.get("operation_id") if isinstance(request.payload.get("operation_id"), str) else None,
                    operation_kind=request.payload.get("operation_kind") if isinstance(request.payload.get("operation_kind"), str) else "other",
                    attempt_no=int(request.payload["attempt_no"]),
                    status="requested" if response is None else "success" if response.kind == "llm.responded" else "failed",
                    request_obs_id=request.obs_id,
                    response_obs_id=response.obs_id if response is not None and response.kind == "llm.responded" else None,
                    failure_obs_id=response.obs_id if response is not None and response.kind == "llm.failed" else None,
                    provider_model=request.payload.get("configured_model") if isinstance(request.payload.get("configured_model"), str) else None,
                    usage=dict(response_payload.get("usage", {})),
                    response_metadata=dict(response_payload.get("response_metadata", {})),
                    latency_ms=int(response_payload["latency_ms"]) if isinstance(response_payload.get("latency_ms"), int) else None,
                    context_snapshot_id=None if snapshot is None else snapshot.subject_id,
                )
            )
        return attempts

    async def get_step(self, step_id: str) -> StepView | None:
        started = next(
            (observation for observation in self._observations if observation.kind == "step.started" and observation.step_id == step_id),
            None,
        )
        return None if started is None else self._step_view(started)

    async def get_step_context(self, step_id: str) -> ContextSnapshotView | None:
        step = await self.get_step(step_id)
        if step is None or step.effective_context_snapshot_id is None:
            return None
        snapshot = next(
            (observation for observation in self._observations if observation.kind == "context.snapshotted" and observation.subject_id == step.effective_context_snapshot_id),
            None,
        )
        if snapshot is None or snapshot.payload is None:
            return None
        payload = snapshot.payload
        blocks = {observation.subject_id: observation.payload for observation in self._observations if observation.kind == "content.produced" and observation.payload is not None}
        items: list[ContextSnapshotItemView] = []
        for item in payload.get("items", []):
            if not isinstance(item, dict):
                continue
            block_id = str(item["block_id"])
            block = blocks.get(block_id)
            if block is None:
                continue
            items.append(
                ContextSnapshotItemView(
                    ordinal=int(item["ordinal"]),
                    channel=str(item["channel"]),
                    role=item.get("role") if isinstance(item.get("role"), str) else None,
                    name=item.get("name") if isinstance(item.get("name"), str) else None,
                    block_id=block_id,
                    kind=str(block["kind"]),
                    content_hash=str(block["content_hash"]),
                    visible_bytes=int(item["visible_bytes"]),
                    estimated_tokens=int(item["estimated_tokens"]),
                    metadata=dict(item.get("metadata", {})),
                    sensitivity_flags=tuple(block.get("sensitivity_flags", [])),
                    payload_available="body" in block,
                )
            )
        return ContextSnapshotView(
            snapshot_id=snapshot.subject_id,
            task_id=snapshot.task_id,
            step_id=snapshot.step_id,
            operation_id=payload.get("operation_id") if isinstance(payload.get("operation_id"), str) else None,
            attempt_no=int(payload["attempt_no"]),
            request_obs_id=snapshot.causation_obs_id or "",
            message_count=int(payload["message_count"]),
            tool_schema_count=int(payload["tool_schema_count"]),
            visible_bytes=int(payload["visible_bytes"]),
            estimated_tokens=int(payload["estimated_tokens"]),
            estimator_name=str(payload["estimator_name"]),
            estimator_version=str(payload["estimator_version"]),
            adapter_name=str(payload["adapter_name"]),
            adapter_version=str(payload["adapter_version"]),
            configured_model=payload.get("configured_model") if isinstance(payload.get("configured_model"), str) else None,
            response_format=payload.get("response_format"),
            generation_settings=dict(payload.get("generation_settings", {})),
            redactions=tuple(payload.get("redactions", [])),
            warnings=tuple(payload.get("warnings", [])),
            items=tuple(sorted(items, key=lambda item: item.ordinal)),
        )

    async def get_content_block_payload(self, block_id: str) -> ContentBlockPayloadView | None:
        observation = next(
            (observation for observation in self._observations if observation.kind == "content.produced" and observation.subject_id == block_id),
            None,
        )
        if observation is None or observation.payload is None or "body" not in observation.payload:
            return None
        return ContentBlockPayloadView(block_id=block_id, body=observation.payload["body"])

    def _step_view(self, started: ObservationEnvelope) -> StepView:
        if started.payload is None or started.step_id is None:
            raise ValueError("invalid in-memory step.started observation")
        closed = next(
            (observation for observation in self._observations if observation.kind == "step.closed" and observation.step_id == started.step_id),
            None,
        )
        closed_payload = {} if closed is None or closed.payload is None else closed.payload
        effective_no = closed_payload.get("effective_attempt_no")
        attempts: list[LlmAttemptView] = []
        for request in self._observations:
            if request.kind != "llm.requested" or request.step_id != started.step_id or request.payload is None:
                continue
            response = next(
                (observation for observation in self._observations if observation.subject_id == request.subject_id and observation.kind in {"llm.responded", "llm.failed"}),
                None,
            )
            snapshot = next(
                (observation for observation in self._observations if observation.kind == "context.snapshotted" and observation.payload is not None and observation.payload.get("attempt_id") == request.subject_id),
                None,
            )
            attempt_no = int(request.payload["attempt_no"])
            response_payload = {} if response is None or response.payload is None else response.payload
            status = "requested" if response is None else "success" if response.kind == "llm.responded" else "failed"
            attempts.append(
                LlmAttemptView(
                    attempt_id=request.subject_id,
                    task_id=request.task_id,
                    step_id=request.step_id,
                    actor_kind=str(request.payload.get("actor_kind", "lead_agent")),
                    operation_id=request.payload.get("operation_id") if isinstance(request.payload.get("operation_id"), str) else None,
                    operation_kind=request.payload.get("operation_kind") if isinstance(request.payload.get("operation_kind"), str) else None,
                    attempt_no=attempt_no,
                    status=status,
                    request_obs_id=request.obs_id,
                    response_obs_id=response.obs_id if response is not None and response.kind == "llm.responded" else None,
                    failure_obs_id=response.obs_id if response is not None and response.kind == "llm.failed" else None,
                    provider_model=request.payload.get("configured_model") if isinstance(request.payload.get("configured_model"), str) else None,
                    usage=dict(response_payload.get("usage", {})),
                    response_metadata=dict(response_payload.get("response_metadata", {})),
                    latency_ms=int(response_payload["latency_ms"]) if isinstance(response_payload.get("latency_ms"), int) else None,
                    context_snapshot_id=None if snapshot is None else snapshot.subject_id,
                    effective=attempt_no == effective_no and status == "success",
                )
            )
        attempts.sort(key=lambda attempt: attempt.attempt_no)
        effective_attempt = next((attempt for attempt in attempts if attempt.effective), None)
        result = closed_payload.get("result") if isinstance(closed_payload.get("result"), str) else None
        return StepView(
            step_id=started.step_id,
            task_id=started.task_id,
            step_seq=int(started.payload["step_seq"]),
            actor_kind=str(started.payload["actor_kind"]),
            status=("deciding" if closed is None else "model_failed" if result == "model_failed" else "acting" if result == "acting" else "closed"),
            result=result,
            started_obs_id=started.obs_id,
            closed_obs_id=None if closed is None else closed.obs_id,
            effective_attempt_no=effective_no if isinstance(effective_no, int) else None,
            effective_context_snapshot_id=None if effective_attempt is None else effective_attempt.context_snapshot_id,
            issued_tools=tuple(closed_payload.get("issued_tools", [])),
            attempts=tuple(attempts),
        )

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
