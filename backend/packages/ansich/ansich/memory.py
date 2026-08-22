from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, cast

from ansich.budget import BudgetSourceKind, TaskBudgetsView, TaskBudgetView
from ansich.compression import (
    CompressionDisposition,
    ContextCompressionItemView,
    ContextCompressionSummaryView,
    ContextCompressionView,
)
from ansich.context_state import ContextStateDelta, ContextStateItem, ContextStateView, materialize_context_state
from ansich.contracts import ANSICH_BOOTSTRAP_TASK_ID, ControlBelief, ControlValue, NamedVersion, ObservationEnvelope, TaskLifecycleScope, TaskView, control_values_for_lifecycle_scope
from ansich.control import should_select_control_candidate
from ansich.environment import (
    EnvironmentHistoryView,
    TaskEnvironmentView,
    TaskToolEnvSamplesView,
    ToolEnvironmentSampleView,
)
from ansich.heartbeat import TaskHeartbeatView
from ansich.lineage import ContentBlockView, ContentProducerView, LineageDirection, PossibleExposureItemView
from ansich.release import (
    AgentRelease,
    AgentReleaseDetailView,
    AgentReleaseSummaryView,
    TaskAgentReleaseView,
    validate_agent_release,
)
from ansich.safety import (
    AuthorizationSnapshot,
    ScopeDescriptor,
    TaskScopesView,
    TaskScopeView,
    ToolAuthorizationView,
    ToolEffect,
    ToolEffectsView,
    scope_display_label,
    scope_entity_id,
    scope_reference_hash,
)
from ansich.step import ContentBlockPayloadView, ContentOccurrenceView, ContextSnapshotItemView, ContextSnapshotView, LlmAttemptView, StepView
from ansich.task_tree import TaskSpawnView, TaskTreeDirection
from ansich.tool import (
    ContentDerivationSourceRole,
    ContentDerivationView,
    ToolBelief,
    ToolCallView,
    ToolResultView,
    ToolTransformKind,
)
from ansich.usage import (
    AggregationScope,
    TaskUsageBreakdownView,
    TaskUsageSourceView,
    TaskUsageValue,
    TaskUsageView,
    child_task_contribution_for_tool_started,
    usage_contributions_for_observation,
)

_CONTROL_BY_KIND = {
    "task.created": "created",
    "task.started": "running",
    "task.completed": "completed",
    "task.failed": "failed",
    "task.interrupted": "interrupted",
}
_TOOL_TERMINAL_PRECEDENCE = {
    "tool.unknown_terminal": 0,
    "tool.denied": 1,
    "tool.cancelled": 2,
    "tool.timed_out": 3,
    "tool.failed": 4,
    "tool.returned_raw": 5,
}


class InMemoryAnsichBackend:
    def __init__(self) -> None:
        self._seen: set[tuple[str, str, str]] = set()
        self._tasks: dict[str, TaskView] = {}
        self._observations: list[ObservationEnvelope] = []
        self._agent_releases: dict[str, tuple[AgentRelease, datetime]] = {}
        self._task_agent_releases: dict[str, tuple[str, str]] = {}

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

    async def record_raw_read_audit(
        self,
        *,
        status: Literal["requested", "succeeded", "failed"],
        read_id: str,
        actor: str,
        target_kind: str,
        target_id: str,
        purpose: str | None = None,
        request_correlation_id: str | None = None,
        outcome: str | None = None,
        http_status: int | None = None,
        served_byte_size: int | None = None,
    ) -> str:
        """The §7 audit row, written straight into this backend's store.

        It exists here for the same reason every other read does: a caller that
        holds this backend must be able to exercise the whole path. What it is
        **not** is durability — this store is a list in a process, so "the audit
        landed" means exactly as much here as every other write to it does, and
        a deployment that wants the §7 guarantee runs a SQL backend
        (``database.backend: memory`` already surfaces ``status=failed``).

        The subject follows RC8's rule as far as this backend can honour it:
        the Task that emitted an Observation about the target when there is
        one, else the bootstrap sentinel. There is deliberately no Scope arm —
        this backend projects no Scope entities, so a host-Scope subject would
        name something that does not exist here.
        """

        owning_task_id: str | None = None
        if target_kind != "agent_release":
            for observation in reversed(self._observations):
                if observation.subject_id == target_id or observation.obs_id == target_id:
                    if observation.task_id != ANSICH_BOOTSTRAP_TASK_ID:
                        owning_task_id = observation.task_id
                    break
        audit = ObservationEnvelope.raw_payload_read(
            status=status,
            read_id=read_id,
            actor=actor,
            target_kind=target_kind,
            target_id=target_id,
            occurred_at=datetime.now(UTC),
            task_id=owning_task_id if owning_task_id is not None else ANSICH_BOOTSTRAP_TASK_ID,
            subject_type="task",
            subject_id=owning_task_id if owning_task_id is not None else ANSICH_BOOTSTRAP_TASK_ID,
            purpose=purpose,
            request_correlation_id=request_correlation_id,
            outcome=outcome,
            http_status=http_status,
            served_byte_size=served_byte_size,
        )
        self._observations.append(audit)
        return audit.obs_id

    async def get_task(self, task_id: str) -> TaskView | None:
        task = self._tasks.get(task_id)
        if task is None:
            return None
        issued_ids = {observation.subject_id for observation in self._observations if observation.task_id == task_id and observation.kind == "tool.issued"}
        executed_ids = {
            observation.subject_id
            for observation in self._observations
            if observation.task_id == task_id
            and observation.kind
            in {
                "tool.started",
                "tool.returned_raw",
                "tool.timed_out",
                "tool.cancelled",
                "tool.failed",
            }
        }
        terminal_kinds_by_call = {
            tool_call_id: {
                observation.kind
                for observation in self._observations
                if observation.task_id == task_id
                and observation.subject_id == tool_call_id
                and observation.kind
                in {
                    "tool.returned_raw",
                    "tool.denied",
                    "tool.timed_out",
                    "tool.cancelled",
                    "tool.failed",
                    "tool.unknown_terminal",
                }
            }
            for tool_call_id in issued_ids
        }
        return task.model_copy(
            update={
                "observability_status": ("degraded" if any(len(terminal_kinds) > 1 for terminal_kinds in terminal_kinds_by_call.values()) else "healthy"),
                "tool_calls_issued": len(issued_ids),
                "tool_calls_executed": len(executed_ids),
            }
        )

    def _agent_release_detail(self, release_id: str) -> AgentReleaseDetailView | None:
        stored = self._agent_releases.get(release_id)
        if stored is None:
            return None
        release, created_at = stored
        fingerprint = release.fingerprint
        manifest = release.manifest
        task_count = sum(bound_release_id == release_id for bound_release_id, _ in self._task_agent_releases.values())
        return AgentReleaseDetailView(
            summary=AgentReleaseSummaryView(
                release_id=release_id,
                namespace=manifest.namespace,
                agent_name=manifest.agent_name,
                release_hash=fingerprint.release_hash,
                schema_version=manifest.schema_version,
                model_hash=fingerprint.model_hash,
                prompt_hash=fingerprint.prompt_hash,
                tool_catalog_hash=fingerprint.tool_catalog_hash,
                policy_hash=fingerprint.policy_hash,
                runtime_build_id=fingerprint.runtime_build_id,
                created_at=created_at,
                task_count=task_count,
            ),
            manifest=manifest,
        )

    async def get_task_agent_release(
        self,
        task_id: str,
    ) -> TaskAgentReleaseView | None:
        binding = self._task_agent_releases.get(task_id)
        if binding is None:
            return None
        release_id, established_obs_id = binding
        detail = self._agent_release_detail(release_id)
        if detail is None:
            return None
        return TaskAgentReleaseView(
            task_id=task_id,
            relation_role="executed_by",
            established_obs_id=established_obs_id,
            release=detail,
        )

    async def get_agent_release(
        self,
        release_id: str,
    ) -> AgentReleaseDetailView | None:
        return self._agent_release_detail(release_id)

    async def list_agent_releases(
        self,
        *,
        limit: int = 100,
        agent_name: str | None = None,
        component_hash: str | None = None,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
    ) -> list[AgentReleaseSummaryView]:
        details = [detail for release_id in self._agent_releases if (detail := self._agent_release_detail(release_id)) is not None]
        if agent_name is not None:
            details = [item for item in details if item.summary.agent_name == agent_name]
        if component_hash is not None:
            details = [
                item
                for item in details
                if component_hash
                in {
                    item.summary.model_hash,
                    item.summary.prompt_hash,
                    item.summary.tool_catalog_hash,
                    item.summary.policy_hash,
                    item.summary.runtime_build_id,
                }
            ]
        if from_time is not None:
            details = [item for item in details if item.summary.created_at >= from_time]
        if to_time is not None:
            details = [item for item in details if item.summary.created_at <= to_time]
        details.sort(key=lambda item: (item.summary.created_at, item.summary.release_id), reverse=True)
        return [item.summary for item in details[:limit]]

    async def get_task_by_source(self, source_kind: str, source_id: str) -> TaskView | None:
        task = next(
            (task for task in self._tasks.values() if task.source_kind == source_kind and task.source_id == source_id),
            None,
        )
        return None if task is None else await self.get_task(task.task_id)

    async def list_tasks(
        self,
        *,
        limit: int = 100,
        control: ControlValue | None = None,
        lifecycle_scope: TaskLifecycleScope = "all",
        from_time: datetime | None = None,
        to_time: datetime | None = None,
        cursor: tuple[datetime, str] | None = None,
        root_only: bool = False,
    ) -> list[TaskView]:
        tasks = [task for task_id in self._tasks if (task := await self.get_task(task_id)) is not None]
        if root_only:
            child_ids = {
                observation.task_id
                for observation in self._observations
                if observation.kind == "task.created" and observation.payload is not None and observation.payload.get("source_kind") == "deerflow_subagent" and isinstance(observation.payload.get("parent_task_id"), str)
            }
            tasks = [task for task in tasks if task.task_id not in child_ids]
        if control is not None:
            tasks = [task for task in tasks if task.control.value == control]
        lifecycle_controls = control_values_for_lifecycle_scope(lifecycle_scope)
        if lifecycle_controls is not None:
            tasks = [task for task in tasks if task.control.value in lifecycle_controls]
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

    async def list_task_children(self, task_id: str) -> list[TaskSpawnView]:
        children: list[TaskSpawnView] = []
        for observation in self._observations:
            payload = observation.payload
            if observation.kind != "task.created" or payload is None or payload.get("source_kind") != "deerflow_subagent" or payload.get("parent_task_id") != task_id:
                continue
            step_id = payload.get("spawning_step_id")
            tool_call_id = payload.get("spawning_tool_call_id")
            if not isinstance(step_id, str) or not isinstance(tool_call_id, str):
                continue
            children.append(
                TaskSpawnView(
                    parent_task_id=task_id,
                    spawning_step_id=step_id,
                    spawning_tool_call_id=tool_call_id,
                    child_task_id=observation.task_id,
                    established_obs_id=observation.obs_id,
                    subagent_name=(str(payload["subagent_name"]) if isinstance(payload.get("subagent_name"), str) else None),
                )
            )
        return children

    async def list_task_tree_spawns(
        self,
        task_id: str,
        *,
        direction: TaskTreeDirection,
        depth: int,
    ) -> tuple[list[TaskSpawnView], bool]:
        all_edges: list[TaskSpawnView] = []
        parent_ids: set[str] = set()
        for observation in self._observations:
            payload = observation.payload
            if observation.kind != "task.created" or payload is None or payload.get("source_kind") != "deerflow_subagent":
                continue
            parent_id = payload.get("parent_task_id")
            step_id = payload.get("spawning_step_id")
            tool_call_id = payload.get("spawning_tool_call_id")
            if not all(isinstance(value, str) for value in (parent_id, step_id, tool_call_id)):
                continue
            if observation.task_id in parent_ids:
                continue
            parent_ids.add(observation.task_id)
            all_edges.append(
                TaskSpawnView(
                    parent_task_id=parent_id,
                    spawning_step_id=step_id,
                    spawning_tool_call_id=tool_call_id,
                    child_task_id=observation.task_id,
                    established_obs_id=observation.obs_id,
                    subagent_name=(str(payload["subagent_name"]) if isinstance(payload.get("subagent_name"), str) else None),
                )
            )
        by_parent: dict[str, list[TaskSpawnView]] = {}
        by_child: dict[str, TaskSpawnView] = {}
        for edge in all_edges:
            by_parent.setdefault(edge.parent_task_id, []).append(edge)
            by_child[edge.child_task_id] = edge

        selected: dict[str, TaskSpawnView] = {}
        truncated = False

        if direction in {"descendants", "both"}:
            frontier = [(task_id, 0)]
            visited = {task_id}
            while frontier:
                current, current_depth = frontier.pop(0)
                for edge in by_parent.get(current, ()):
                    if current_depth >= depth:
                        truncated = True
                        continue
                    selected[edge.child_task_id] = edge
                    if edge.child_task_id not in visited:
                        visited.add(edge.child_task_id)
                        frontier.append((edge.child_task_id, current_depth + 1))

        if direction in {"ancestors", "both"}:
            current = task_id
            current_depth = 0
            visited = {task_id}
            while (parent_edge := by_child.get(current)) is not None:
                if current_depth >= depth:
                    truncated = True
                    break
                selected[parent_edge.child_task_id] = parent_edge
                current = parent_edge.parent_task_id
                current_depth += 1
                if current in visited:
                    truncated = True
                    break
                visited.add(current)
        edges = list(selected.values())
        edges.sort(key=lambda edge: (edge.parent_task_id, edge.child_task_id))
        return edges, truncated

    async def get_task_usage(self, task_id: str) -> TaskUsageView:
        order = {
            "input_tokens": 0,
            "output_tokens": 1,
            "total_tokens": 2,
            "llm_attempts": 3,
            "steps": 4,
            "tool_calls_issued": 5,
            "tool_calls_executed": 6,
            "wall_time_ms": 7,
            "child_tasks_spawned": 8,
        }

        def local_values(source_task_id: str) -> dict[str, tuple[int, datetime, int]]:
            values: dict[str, int] = {}
            as_of: dict[str, datetime] = {}
            complete_through: dict[str, int] = {}
            seen: set[tuple[str, str]] = set()
            executed_tool_ids: set[str] = set()
            for ingest_seq, observation in enumerate(self._observations, start=1):
                if observation.task_id != source_task_id:
                    continue
                if observation.kind == "task.heartbeat" and observation.payload is not None:
                    elapsed_ms = observation.payload.get("elapsed_ms")
                    if isinstance(elapsed_ms, int) and not isinstance(elapsed_ms, bool):
                        values["wall_time_ms"] = max(
                            values.get("wall_time_ms", 0),
                            max(0, elapsed_ms),
                        )
                        as_of["wall_time_ms"] = max(
                            as_of.get("wall_time_ms", observation.occurred_at),
                            observation.occurred_at,
                        )
                        complete_through["wall_time_ms"] = ingest_seq
                contributions = list(usage_contributions_for_observation(observation))
                if observation.kind == "tool.started":
                    issued = next(
                        (item for item in self._observations if item.task_id == source_task_id and item.subject_id == observation.subject_id and item.kind == "tool.issued" and item.payload is not None),
                        None,
                    )
                    tool_name = None if issued is None else issued.payload.get("tool_name")
                    if isinstance(tool_name, str):
                        child = child_task_contribution_for_tool_started(
                            observation,
                            tool_name=tool_name,
                        )
                        if child is not None:
                            contributions.append(child)
                for contribution in contributions:
                    key = (contribution.source_obs_id, contribution.dimension)
                    if key in seen:
                        continue
                    if contribution.dimension == "tool_calls_executed":
                        if observation.subject_id in executed_tool_ids:
                            continue
                        executed_tool_ids.add(observation.subject_id)
                    seen.add(key)
                    if contribution.dimension == "wall_time_ms":
                        values[contribution.dimension] = max(
                            values.get(contribution.dimension, 0),
                            contribution.delta,
                        )
                    else:
                        values[contribution.dimension] = values.get(contribution.dimension, 0) + contribution.delta
                    as_of[contribution.dimension] = max(
                        as_of.get(contribution.dimension, contribution.as_of),
                        contribution.as_of,
                    )
                    complete_through[contribution.dimension] = max(
                        complete_through.get(contribution.dimension, ingest_seq),
                        ingest_seq,
                    )
            return {
                dimension: (
                    value,
                    as_of[dimension],
                    complete_through[dimension],
                )
                for dimension, value in values.items()
            }

        direct_children: dict[str, set[str]] = {}
        for observation in self._observations:
            payload = observation.payload
            if observation.kind == "task.created" and payload is not None and payload.get("source_kind") == "deerflow_subagent" and isinstance(payload.get("parent_task_id"), str):
                direct_children.setdefault(str(payload["parent_task_id"]), set()).add(observation.task_id)
        descendants = {task_id}
        frontier = [task_id]
        while frontier:
            current = frontier.pop()
            for child_id in direct_children.get(current, ()):
                if child_id not in descendants:
                    descendants.add(child_id)
                    frontier.append(child_id)

        local_map = local_values(task_id)
        inclusive_map: dict[str, tuple[int, datetime, int]] = {}
        for source_task_id in descendants:
            for dimension, (value, item_as_of, watermark) in local_values(source_task_id).items():
                previous = inclusive_map.get(dimension)
                inclusive_map[dimension] = (
                    value + (0 if previous is None else previous[0]),
                    item_as_of if previous is None else max(item_as_of, previous[1]),
                    watermark if previous is None else max(watermark, previous[2]),
                )

        def usage_values(
            values: dict[str, tuple[int, datetime, int]],
            scope: AggregationScope,
        ) -> tuple[TaskUsageValue, ...]:
            return tuple(
                TaskUsageValue(
                    dimension=dimension,
                    aggregation_scope=scope,
                    value=value,
                    as_of=item_as_of,
                    complete_through_ingest_seq=watermark,
                )
                for dimension, (value, item_as_of, watermark) in sorted(values.items(), key=lambda item: order[item[0]])
            )

        return TaskUsageView(
            task_id=task_id,
            local=usage_values(local_map, "local"),
            inclusive=usage_values(inclusive_map, "inclusive"),
        )

    async def get_task_usage_breakdown(
        self,
        task_id: str,
        *,
        scope: AggregationScope,
    ) -> TaskUsageBreakdownView:
        source_task_ids = {task_id}
        if scope == "inclusive":
            direct_children: dict[str, set[str]] = {}
            for observation in self._observations:
                payload = observation.payload
                if observation.kind == "task.created" and payload is not None and payload.get("source_kind") == "deerflow_subagent" and isinstance(payload.get("parent_task_id"), str):
                    direct_children.setdefault(str(payload["parent_task_id"]), set()).add(observation.task_id)
            frontier = [task_id]
            while frontier:
                current = frontier.pop()
                for child_id in direct_children.get(current, ()):
                    if child_id not in source_task_ids:
                        source_task_ids.add(child_id)
                        frontier.append(child_id)
        sources: list[TaskUsageSourceView] = []
        for source_task_id in sorted(source_task_ids):
            usage = await self.get_task_usage(source_task_id)
            if usage.local:
                sources.append(
                    TaskUsageSourceView(
                        source_task_id=source_task_id,
                        values=tuple(item.model_copy(update={"aggregation_scope": scope}) for item in usage.local),
                    )
                )
        return TaskUsageBreakdownView(
            task_id=task_id,
            scope=scope,
            sources=tuple(sources),
        )

    async def get_task_budgets(self, task_id: str) -> TaskBudgetsView:
        budgets: list[TaskBudgetView] = []
        for observation in self._observations:
            if observation.task_id != task_id or observation.kind != "budget.configured" or observation.payload is None:
                continue
            payload = observation.payload
            budgets.append(
                TaskBudgetView(
                    entity_id=observation.obs_id,
                    task_id=task_id,
                    dimension=payload["dimension"],
                    aggregation_scope=payload["aggregation_scope"],
                    warning_limit=payload.get("warning_limit"),
                    hard_limit=payload.get("hard_limit"),
                    enforcement=payload["enforcement"],
                    source_kind=cast(BudgetSourceKind, payload["source_kind"]),
                    requested_value=payload.get("requested_value"),
                    effective_value=payload["effective_value"],
                    configured_obs_id=observation.obs_id,
                )
            )
        order = {
            "input_tokens": 0,
            "output_tokens": 1,
            "total_tokens": 2,
            "llm_attempts": 3,
            "steps": 4,
            "tool_calls_issued": 5,
            "tool_calls_executed": 6,
            "wall_time_ms": 7,
            "child_tasks_spawned": 8,
        }
        budgets.sort(key=lambda item: (order[item.dimension], item.aggregation_scope))
        return TaskBudgetsView(task_id=task_id, budgets=tuple(budgets))

    async def get_task_environment(self, task_id: str) -> TaskEnvironmentView:
        # Minimal implementation: the in-memory backend backs pure-projection
        # unit tests, not the environment-projector's coverage/state/belief
        # tables, so it always reports "nothing observed" rather than raising.
        return TaskEnvironmentView(task_id=task_id, scopes=())

    async def get_environment_history(
        self,
        scope_id: str,
        *,
        environment_scope: str,
        metric: str,
        window_minutes: int,
        max_points: int,
    ) -> EnvironmentHistoryView:
        # Minimal implementation, same reason as ``get_task_environment``: the
        # trend read replays projected environment Observations, which this
        # backend does not retain. An empty window is "nothing observed", not
        # an error.
        return EnvironmentHistoryView(
            scope_id=scope_id,
            environment_scope=environment_scope,
            metric=metric,
            window_minutes=window_minutes,
            truncated=False,
            points=(),
        )

    async def get_task_tool_env_samples(self, task_id: str) -> TaskToolEnvSamplesView:
        # Minimal implementation: ``ansich_tool_env_samples`` is a SQL
        # projection this backend does not materialize.
        return TaskToolEnvSamplesView(task_id=task_id, truncated=False, samples=())

    async def get_task_heartbeat(self, task_id: str) -> TaskHeartbeatView | None:
        observation = max(
            (item for item in self._observations if item.task_id == task_id and item.kind == "task.heartbeat" and item.payload is not None),
            key=lambda item: item.occurred_at,
            default=None,
        )
        if observation is None or observation.payload is None:
            return None
        return TaskHeartbeatView(
            task_id=task_id,
            heartbeat_obs_id=observation.obs_id,
            occurred_at=observation.occurred_at,
            producer_instance_id=observation.producer.instance_id,
            ownership_epoch=str(observation.payload["ownership_epoch"]),
            elapsed_ms=int(observation.payload["elapsed_ms"]),
        )

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

    async def list_content_occurrences(self, task_id: str) -> list[ContentOccurrenceView]:
        occurrences: dict[tuple[str, str, str], ContentOccurrenceView] = {}
        for observation in self._observations:
            if observation.task_id != task_id or observation.kind != "content.produced" or observation.payload is None:
                continue
            source_identity = observation.payload.get("source_identity")
            content_hash = observation.payload.get("content_hash")
            kind = observation.payload.get("kind")
            if not all(isinstance(value, str) and value for value in (source_identity, content_hash, kind)):
                continue
            key = (source_identity, content_hash, kind)
            occurrences.setdefault(
                key,
                ContentOccurrenceView(
                    task_id=task_id,
                    source_identity=source_identity,
                    content_hash=content_hash,
                    kind=kind,
                    block_id=observation.subject_id,
                    producer_obs_id=observation.obs_id,
                ),
            )
        return list(occurrences.values())

    async def get_latest_context_state(self, task_id: str) -> ContextStateView | None:
        observation = next(
            (observation for observation in reversed(self._observations) if observation.task_id == task_id and observation.kind == "context.state_recorded"),
            None,
        )
        return None if observation is None else self._context_state_view(observation.subject_id)

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

    async def get_tool_call(self, tool_call_id: str) -> ToolCallView | None:
        issued = next(
            (observation for observation in self._observations if observation.kind == "tool.issued" and observation.subject_id == tool_call_id),
            None,
        )
        return None if issued is None else self._tool_call_view(issued)

    async def get_tool_environment_sample(self, tool_call_id: str) -> ToolEnvironmentSampleView | None:
        # Minimal implementation: per-command environment samples are a SQL
        # projection (``ansich_tool_env_samples``) the in-memory backend does
        # not materialize.
        return None

    async def get_task_scopes(self, task_id: str) -> TaskScopesView:
        scopes: dict[str, TaskScopeView] = {}
        created = next(
            (item for item in self._observations if item.task_id == task_id and item.kind == "task.created"),
            None,
        )
        if created is not None and created.payload is not None:
            for scope_kind, relation_role, field_name in (
                ("owner", "owner", "owner_id"),
                ("thread", "conversation", "thread_id"),
                ("workspace", "execution_workspace", "workspace_ref"),
                ("sandbox", "sandbox_boundary", "sandbox_ref"),
                ("authorization", "auth_context", "authorization_ref"),
                ("external_origin", "trigger_origin", "external_origin_ref"),
            ):
                raw_ref = created.payload.get(field_name)
                if not isinstance(raw_ref, str) or not raw_ref:
                    continue
                ref_hash = scope_reference_hash(scope_kind, raw_ref)
                scope_id = scope_entity_id(scope_kind, ref_hash)
                scopes[scope_id] = TaskScopeView(
                    scope_id=scope_id,
                    scope_kind=scope_kind,
                    external_ref_hash=ref_hash,
                    display_label=scope_display_label(scope_kind, raw_ref),
                    parent_scope_id=None,
                    created_obs_id=created.obs_id,
                    relation_role=relation_role,
                    relation_obs_id=created.obs_id,
                    inherited_from_task_id=None,
                )
        for item in self._observations:
            if item.kind != "scope.snapshotted" or item.payload is None:
                continue
            subject_id = item.payload.get("within_scope_subject_id", item.task_id)
            if subject_id != task_id:
                continue
            scope = ScopeDescriptor.model_validate(item.payload.get("scope"), strict=False)
            relation_role = item.payload.get("relation_role")
            if not isinstance(relation_role, str):
                continue
            inherited_from = item.payload.get("inherited_from_task_id")
            scopes[scope.scope_id] = TaskScopeView(
                **scope.model_dump(mode="python"),
                relation_role=relation_role,
                relation_obs_id=item.obs_id,
                inherited_from_task_id=(inherited_from if isinstance(inherited_from, str) else None),
            )
        return TaskScopesView(
            task_id=task_id,
            scopes=tuple(
                sorted(
                    scopes.values(),
                    key=lambda item: (
                        item.scope_kind,
                        item.display_label,
                        item.scope_id,
                    ),
                )
            ),
        )

    async def get_tool_authorization(
        self,
        tool_call_id: str,
    ) -> ToolAuthorizationView | None:
        if await self.get_tool_call(tool_call_id) is None:
            return None
        by_snapshot: dict[str, AuthorizationSnapshot] = {}
        for item in self._observations:
            if not item.kind.startswith("authorization.") or item.payload is None:
                continue
            snapshot = AuthorizationSnapshot.model_validate(item.payload.get("snapshot"), strict=False)
            if snapshot.tool_call_id == tool_call_id:
                by_snapshot[snapshot.snapshot_id] = snapshot
        snapshots = tuple(
            sorted(
                by_snapshot.values(),
                key=lambda item: (item.evaluated_at, item.snapshot_id),
            )
        )
        return ToolAuthorizationView(
            tool_call_id=tool_call_id,
            snapshots=snapshots,
            current_decision=(snapshots[-1].decision if snapshots else "unknown"),
        )

    async def get_tool_effects(self, tool_call_id: str) -> ToolEffectsView | None:
        if await self.get_tool_call(tool_call_id) is None:
            return None
        effects = tuple(
            ToolEffect.model_validate(item.payload.get("effect"), strict=False)
            for item in self._observations
            if item.kind.startswith("effect.") and item.payload is not None and isinstance(item.payload.get("effect"), dict) and item.payload["effect"].get("tool_call_id") == tool_call_id
        )
        if any(item.result_metadata.get("coverage") == "complete" for item in effects):
            coverage = "complete"
        elif effects:
            coverage = "partial"
        else:
            coverage = "unknown"
        return ToolEffectsView(
            tool_call_id=tool_call_id,
            effects=effects,
            coverage=coverage,
        )

    async def get_step_context(self, step_id: str) -> ContextSnapshotView | None:
        step = await self.get_step(step_id)
        if step is None or step.effective_context_snapshot_id is None:
            return None
        return await self.get_context_snapshot(step.effective_context_snapshot_id)

    async def get_context_snapshot(
        self,
        snapshot_id: str,
    ) -> ContextSnapshotView | None:
        snapshot = next(
            (observation for observation in self._observations if observation.kind == "context.snapshotted" and observation.subject_id == snapshot_id),
            None,
        )
        if snapshot is None or snapshot.payload is None:
            return None
        payload = snapshot.payload
        blocks = {observation.subject_id: observation.payload for observation in self._observations if observation.kind == "content.produced" and observation.payload is not None}
        state_id = payload.get("state_id")
        state = self._context_state_view(state_id) if isinstance(state_id, str) else None
        if state is not None:
            raw_items = [item.model_dump(mode="json") for item in state.items]
        else:
            raw_items = payload.get("items", [])
        items: list[ContextSnapshotItemView] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            block_id = str(item["block_id"])
            block = blocks.get(block_id)
            items.append(
                ContextSnapshotItemView(
                    ordinal=int(item["ordinal"]),
                    channel=str(item["channel"]),
                    role=item.get("role") if isinstance(item.get("role"), str) else None,
                    name=item.get("name") if isinstance(item.get("name"), str) else None,
                    message_id=item.get("message_id") if isinstance(item.get("message_id"), str) else None,
                    source_identity=item.get("source_identity") if isinstance(item.get("source_identity"), str) else None,
                    block_id=block_id,
                    kind=str(block["kind"]) if block is not None else None,
                    content_hash=str(block["content_hash"]) if block is not None else None,
                    visible_bytes=int(item["visible_bytes"]),
                    estimated_tokens=int(item["estimated_tokens"]),
                    metadata=dict(item.get("metadata", {})),
                    sensitivity_flags=tuple(block.get("sensitivity_flags", [])) if block is not None else (),
                    payload_available=block is not None and "body" in block,
                    resolution_status="available" if block is not None else "missing",
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
            status=("complete" if not isinstance(state_id, str) or (state is not None and state.status == "complete") else "incomplete"),
        )

    def _context_state_view(
        self,
        state_id: str,
        visited: frozenset[str] = frozenset(),
    ) -> ContextStateView | None:
        if state_id in visited:
            raise ValueError("ContextState parent cycle detected")
        observation = next(
            (observation for observation in self._observations if observation.kind == "context.state_recorded" and observation.subject_id == state_id),
            None,
        )
        if observation is None or observation.payload is None:
            return None
        payload = observation.payload
        is_checkpoint = bool(payload["is_checkpoint"])
        parent_state_id = payload.get("parent_state_id") if isinstance(payload.get("parent_state_id"), str) else None
        if is_checkpoint:
            items = tuple(ContextStateItem.model_validate(item) for item in payload.get("checkpoint_items", []))
            parent_complete = True
        else:
            parent = self._context_state_view(parent_state_id, visited | {state_id}) if parent_state_id is not None else None
            if parent is None:
                items = ()
                parent_complete = False
            else:
                delta = tuple(ContextStateDelta.model_validate(operation) for operation in payload.get("delta", []))
                items = materialize_context_state(parent.items, delta, item_count=int(payload["item_count"]))
                parent_complete = parent.status == "complete"
        available_blocks = {item.subject_id for item in self._observations if item.kind == "content.produced" and item.task_id == observation.task_id}
        status = "complete" if parent_complete and all(item.block_id in available_blocks for item in items) else "incomplete"
        return ContextStateView(
            state_id=state_id,
            task_id=observation.task_id,
            state_hash=str(payload["state_hash"]),
            parent_state_id=parent_state_id,
            chain_depth=int(payload["chain_depth"]),
            is_checkpoint=is_checkpoint,
            status=status,
            items=items,
        )

    async def get_content_block_payload(self, block_id: str) -> ContentBlockPayloadView | None:
        observation = next(
            (observation for observation in self._observations if observation.kind == "content.produced" and observation.subject_id == block_id),
            None,
        )
        if observation is None or observation.payload is None or "body" not in observation.payload:
            return None
        return ContentBlockPayloadView(block_id=block_id, body=observation.payload["body"])

    async def get_context_compression(
        self,
        compression_id: str,
    ) -> ContextCompressionView | None:
        observation = next(
            (item for item in self._observations if item.kind == "context.compressed" and item.subject_id == compression_id),
            None,
        )
        if observation is None or observation.payload is None:
            return None
        payload = observation.payload
        raw_items = [item for item in payload.get("items", []) if isinstance(item, dict)]
        summary_block_id = payload.get("summary_block_id")
        if not isinstance(summary_block_id, str):
            return None
        block_ids = tuple(
            dict.fromkeys(
                [
                    summary_block_id,
                    *[str(item["block_id"]) for item in raw_items if isinstance(item.get("block_id"), str)],
                ]
            )
        )
        blocks = {block.block_id: block for block in await self.get_content_blocks(block_ids)}
        summary_block = blocks.get(summary_block_id)
        if summary_block is None:
            return None
        items = tuple(
            ContextCompressionItemView(
                disposition=cast(CompressionDisposition, item["disposition"]),
                ordinal=int(item["ordinal"]),
                block=blocks[str(item["block_id"])],
            )
            for item in raw_items
            if isinstance(item.get("block_id"), str) and str(item["block_id"]) in blocks
        )
        return ContextCompressionView(
            compression_id=compression_id,
            task_id=observation.task_id,
            summary_operation_id=(payload.get("summary_operation_id") if isinstance(payload.get("summary_operation_id"), str) else None),
            summary_block=summary_block,
            before_tokens=int(payload["before_tokens"]),
            after_tokens=int(payload["after_tokens"]),
            before_visible_bytes=int(payload.get("before_visible_bytes", 0)),
            after_visible_bytes=int(payload.get("after_visible_bytes", 0)),
            algorithm=str(payload["algorithm"]),
            algorithm_version=str(payload["algorithm_version"]),
            source_obs_id=observation.obs_id,
            status=("complete" if payload.get("status", "complete") == "complete" and len(items) == len(raw_items) else "incomplete"),
            items=items,
        )

    async def list_context_compressions(
        self,
        task_id: str,
        *,
        limit: int = 100,
        cursor: tuple[datetime, str] | None = None,
    ) -> list[ContextCompressionSummaryView]:
        observations = [observation for observation in self._observations if observation.task_id == task_id and observation.kind == "context.compressed" and observation.payload is not None]
        observations.sort(key=lambda observation: observation.obs_id)
        observations.sort(
            key=lambda observation: observation.occurred_at,
            reverse=True,
        )
        if cursor is not None:
            cursor_time, cursor_obs_id = cursor
            observations = [observation for observation in observations if observation.occurred_at < cursor_time or (observation.occurred_at == cursor_time and observation.obs_id > cursor_obs_id)]
        summaries: list[ContextCompressionSummaryView] = []
        for observation in observations[:limit]:
            payload = observation.payload
            assert payload is not None
            summaries.append(
                ContextCompressionSummaryView(
                    compression_id=observation.subject_id,
                    task_id=task_id,
                    summary_operation_id=(payload.get("summary_operation_id") if isinstance(payload.get("summary_operation_id"), str) else None),
                    summary_block_id=str(payload["summary_block_id"]),
                    before_tokens=int(payload["before_tokens"]),
                    after_tokens=int(payload["after_tokens"]),
                    before_visible_bytes=int(payload.get("before_visible_bytes", 0)),
                    after_visible_bytes=int(payload.get("after_visible_bytes", 0)),
                    algorithm=str(payload["algorithm"]),
                    algorithm_version=str(payload["algorithm_version"]),
                    source_obs_id=observation.obs_id,
                    occurred_at=observation.occurred_at,
                    status=cast(
                        Literal["complete", "incomplete"],
                        payload.get("status", "complete"),
                    ),
                )
            )
        return summaries

    async def get_content_blocks(
        self,
        block_ids: tuple[str, ...],
    ) -> list[ContentBlockView]:
        requested = set(block_ids)
        blocks: dict[str, ContentBlockView] = {}
        for observation in self._observations:
            if observation.kind != "content.produced" or observation.subject_id not in requested or observation.payload is None:
                continue
            payload = observation.payload
            blocks.setdefault(
                observation.subject_id,
                ContentBlockView(
                    block_id=observation.subject_id,
                    kind=str(payload["kind"]),
                    content_hash=str(payload["content_hash"]),
                    byte_size=int(payload["visible_bytes"]),
                    token_estimate=int(payload["estimated_tokens"]),
                    sensitivity_flags=tuple(payload.get("sensitivity_flags", [])),
                    payload_status=("available" if "body" in payload else "missing"),
                    producer=ContentProducerView(
                        producer_kind=str(payload.get("producer_kind") or observation.producer.name),
                        producer_entity_id=(payload.get("producer_entity_id") if isinstance(payload.get("producer_entity_id"), str) else None),
                        producer_obs_id=observation.obs_id,
                    ),
                ),
            )
        return [blocks[block_id] for block_id in block_ids if block_id in blocks]

    async def list_content_derivations(
        self,
        block_ids: tuple[str, ...],
        direction: LineageDirection,
    ) -> list[ContentDerivationView]:
        requested = set(block_ids)
        derivations: dict[tuple[str, str, str], ContentDerivationView] = {}
        for observation in self._observations:
            if observation.payload is None:
                continue
            payload = observation.payload
            candidates: list[tuple[str, str, str, str, int | None]] = []
            if observation.kind == "content.produced":
                candidates.extend(
                    (
                        observation.subject_id,
                        str(item["source_block_id"]),
                        str(item.get("transform_kind", "unknown")),
                        str(item.get("source_role", "source")),
                        (int(item["ordinal"]) if isinstance(item.get("ordinal"), int) else None),
                    )
                    for item in payload.get("derivation_sources", [])
                    if isinstance(item, dict) and isinstance(item.get("source_block_id"), str)
                )
                source_block_id = payload.get("source_block_id")
                if isinstance(source_block_id, str):
                    candidates.append(
                        (
                            observation.subject_id,
                            source_block_id,
                            str(payload.get("transform_kind", "unknown")),
                            str(payload.get("source_role", "source")),
                            (int(payload["source_ordinal"]) if isinstance(payload.get("source_ordinal"), int) else None),
                        )
                    )
            elif observation.kind == "tool.result_visible":
                derived_block_id = payload.get("result_block_id")
                source_block_id = payload.get("source_block_id")
                if isinstance(derived_block_id, str) and isinstance(source_block_id, str):
                    candidates.append(
                        (
                            derived_block_id,
                            source_block_id,
                            str(payload.get("transform_kind", "unknown")),
                            "source",
                            None,
                        )
                    )
            elif observation.kind == "context.compressed":
                derived_block_id = payload.get("summary_block_id")
                if isinstance(derived_block_id, str):
                    candidates.extend(
                        (
                            derived_block_id,
                            str(item["block_id"]),
                            "compressed",
                            "source",
                            int(item["ordinal"]),
                        )
                        for item in payload.get("items", [])
                        if isinstance(item, dict) and item.get("disposition") == "source" and isinstance(item.get("block_id"), str)
                    )
            for derived_block_id, source_block_id, transform_kind, source_role, ordinal in candidates:
                if derived_block_id == source_block_id:
                    continue
                endpoint = derived_block_id if direction == "backward" else source_block_id
                if endpoint not in requested:
                    continue
                key = (derived_block_id, source_block_id, transform_kind)
                derivations.setdefault(
                    key,
                    ContentDerivationView(
                        derived_block_id=derived_block_id,
                        source_block_id=source_block_id,
                        transform_kind=cast(ToolTransformKind, transform_kind),
                        transform_version=str(payload.get("transform_version", "1")),
                        established_obs_id=observation.obs_id,
                        source_role=cast(ContentDerivationSourceRole, source_role),
                        ordinal=ordinal,
                    ),
                )
        return list(derivations.values())

    async def list_snapshot_exposures(
        self,
        root_block_id: str,
        descendant_block_ids: tuple[str, ...],
    ) -> list[PossibleExposureItemView]:
        requested = set(descendant_block_ids)
        root_observation = next(
            (observation for observation in self._observations if observation.kind == "content.produced" and observation.subject_id == root_block_id),
            None,
        )
        if root_observation is None:
            return []
        exposures: list[PossibleExposureItemView] = []
        for snapshot in self._observations:
            if snapshot.kind != "context.snapshotted" or snapshot.step_id is None or snapshot.payload is None:
                continue
            state_id = snapshot.payload.get("state_id")
            if not isinstance(state_id, str):
                continue
            state = self._context_state_view(state_id)
            if state is None:
                continue
            started = next(
                (observation for observation in self._observations if observation.kind == "step.started" and observation.step_id == snapshot.step_id and observation.payload is not None),
                None,
            )
            if started is None or started.payload is None:
                continue
            request = next(
                (observation for observation in self._observations if observation.obs_id == snapshot.causation_obs_id),
                None,
            )
            ordering = "later" if request is not None and request.occurred_at > root_observation.occurred_at else "unknown"
            exposures.extend(
                PossibleExposureItemView(
                    task_id=snapshot.task_id,
                    step_id=snapshot.step_id,
                    step_seq=int(started.payload["step_seq"]),
                    snapshot_id=snapshot.subject_id,
                    snapshot_ordinal=item.ordinal,
                    descendant_block_id=item.block_id,
                    ordering=ordering,
                )
                for item in state.items
                if item.block_id in requested
            )
        exposures.sort(
            key=lambda item: (
                item.step_seq,
                item.snapshot_id,
                item.snapshot_ordinal,
                item.descendant_block_id,
            )
        )
        return exposures

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
        tool_calls = tuple(self._tool_call_view(observation) for observation in self._observations if observation.kind == "tool.issued" and observation.step_id == started.step_id)
        result = closed_payload.get("result") if isinstance(closed_payload.get("result"), str) else None
        status = "deciding" if closed is None else "model_failed" if result == "model_failed" else "acting" if result == "acting" else "closed"
        if status == "acting" and tool_calls:
            terminal_values = {
                "returned",
                "denied",
                "timed_out",
                "cancelled",
                "failed",
                "unknown_terminal",
            }
            all_terminal = all(tool_call.execution.value in terminal_values for tool_call in tool_calls)
            current_step_seq = int(started.payload["step_seq"])
            followup_observed = any(
                observation.kind == "step.started" and observation.task_id == started.task_id and observation.payload is not None and int(observation.payload["step_seq"]) > current_step_seq for observation in self._observations
            ) or any(observation.task_id == started.task_id and observation.kind in {"task.completed", "task.failed", "task.interrupted"} for observation in self._observations)
            if all_terminal and followup_observed:
                status = "closed"
        return StepView(
            step_id=started.step_id,
            task_id=started.task_id,
            step_seq=int(started.payload["step_seq"]),
            actor_kind=str(started.payload["actor_kind"]),
            status=status,
            result=result,
            started_obs_id=started.obs_id,
            closed_obs_id=None if closed is None else closed.obs_id,
            effective_attempt_no=effective_no if isinstance(effective_no, int) else None,
            effective_context_snapshot_id=None if effective_attempt is None else effective_attempt.context_snapshot_id,
            issued_tools=tuple(closed_payload.get("issued_tools", [])),
            attempts=tuple(attempts),
            tool_calls=tuple(sorted(tool_calls, key=lambda item: item.call_seq)),
        )

    def _tool_call_view(self, issued: ObservationEnvelope) -> ToolCallView:
        if issued.payload is None or issued.step_id is None:
            raise ValueError("invalid in-memory tool.issued observation")
        related = [observation for observation in self._observations if observation.subject_id == issued.subject_id and observation.kind.startswith("tool.")]
        started = next(
            (observation for observation in related if observation.kind == "tool.started"),
            None,
        )
        terminals = [observation for observation in related if observation.kind in _TOOL_TERMINAL_PRECEDENCE]
        terminal = (
            None
            if not terminals
            else max(
                terminals,
                key=lambda observation: _TOOL_TERMINAL_PRECEDENCE[observation.kind],
            )
        )
        visible = next(
            (observation for observation in reversed(related) if observation.kind == "tool.result_visible"),
            None,
        )
        blocks = {observation.subject_id: observation.payload for observation in self._observations if observation.kind == "content.produced" and observation.payload is not None}

        def result_view(
            observation: ObservationEnvelope | None,
            role: str,
        ) -> ToolResultView | None:
            payload = None if observation is None else observation.payload
            block_id = None if payload is None else payload.get("result_block_id")
            if observation is None or not isinstance(block_id, str):
                return None
            block = blocks.get(block_id)
            metadata = {key: value for key, value in payload.items() if key not in {"result_block_id", "call_seq", "source_block_id"}}
            return ToolResultView(
                result_role=cast(str, role),
                content_block_id=block_id,
                source_obs_id=observation.obs_id,
                content_hash=(str(block["content_hash"]) if block is not None and "content_hash" in block else None),
                byte_size=(int(block["visible_bytes"]) if block is not None and isinstance(block.get("visible_bytes"), int) else None),
                payload_available=block is not None and "body" in block,
                metadata=metadata,
            )

        raw_result = result_view(terminal, "raw")
        visible_result = result_view(visible, "visible")
        execution_status = {
            "tool.returned_raw": "returned",
            "tool.denied": "denied",
            "tool.timed_out": "timed_out",
            "tool.cancelled": "cancelled",
            "tool.failed": "failed",
            "tool.unknown_terminal": "unknown_terminal",
        }.get(None if terminal is None else terminal.kind)
        if execution_status is None:
            execution_status = "acting" if started is not None else "issued"

        def belief(
            value: str,
            evidence: ObservationEnvelope | None,
            resolver: str,
        ) -> ToolBelief:
            return ToolBelief(
                value=value,
                as_of=None if evidence is None else evidence.occurred_at,
                asserted_at=(issued.recorded_at if evidence is None else evidence.recorded_at),
                source=NamedVersion(
                    name=("tool-accountability" if evidence is None else evidence.producer.name),
                    version=("1" if evidence is None else evidence.producer.version),
                ),
                selected_by=NamedVersion(name=resolver, version="1"),
                evidence_obs_ids=() if evidence is None else (evidence.obs_id,),
            )

        derivations: tuple[ContentDerivationView, ...] = ()
        if visible is not None and visible.payload is not None:
            derived_block_id = visible.payload.get("result_block_id")
            source_block_id = visible.payload.get("source_block_id")
            if isinstance(derived_block_id, str) and isinstance(source_block_id, str):
                derivations = (
                    ContentDerivationView(
                        derived_block_id=derived_block_id,
                        source_block_id=source_block_id,
                        transform_kind=str(visible.payload.get("transform_kind", "unknown")),
                        transform_version=str(visible.payload.get("transform_version", "1")),
                        established_obs_id=visible.obs_id,
                    ),
                )
        return ToolCallView(
            tool_call_id=issued.subject_id,
            task_id=issued.task_id,
            step_id=issued.step_id,
            step_seq=next(
                (int(observation.payload["step_seq"]) for observation in self._observations if observation.kind == "step.started" and observation.step_id == issued.step_id and observation.payload is not None),
                0,
            ),
            call_seq=int(issued.payload["call_seq"]),
            provider_call_id=(issued.payload.get("provider_call_id") if isinstance(issued.payload.get("provider_call_id"), str) else None),
            tool_name=str(issued.payload["tool_name"]),
            args_hash=str(issued.payload["args_hash"]),
            args_preview=issued.payload.get("args_preview", {}),
            tool_schema_block_id=(issued.payload.get("tool_schema_block_id") if isinstance(issued.payload.get("tool_schema_block_id"), str) else None),
            issued_obs_id=issued.obs_id,
            started_obs_id=None if started is None else started.obs_id,
            raw_terminal_obs_id=None if terminal is None else terminal.obs_id,
            visible_result_obs_id=None if visible is None else visible.obs_id,
            duration_ms=(int(terminal.payload["duration_ms"]) if terminal is not None and terminal.payload is not None and isinstance(terminal.payload.get("duration_ms"), int) else None),
            authorization=belief(
                "denied" if terminal is not None and terminal.kind == "tool.denied" else "unknown",
                terminal if terminal is not None and terminal.kind == "tool.denied" else None,
                "tool-authorization-state",
            ),
            execution=belief(
                execution_status,
                terminal or started or issued,
                ("tool-terminal-precedence" if terminal is not None else "tool-execution-state"),
            ),
            visible_result=belief(
                "available" if visible is not None else "unknown",
                visible,
                "tool-visible-result-state",
            ),
            raw_results=() if raw_result is None else (raw_result,),
            visible_results=() if visible_result is None else (visible_result,),
            derivations=derivations,
        )

    def _project(self, observation: ObservationEnvelope) -> None:
        if observation.kind == "agent_release.resolved":
            if observation.payload is None:
                return
            release = AgentRelease.model_validate(observation.payload.get("release"))
            validate_agent_release(release)
            release_id = observation.subject_id
            self._agent_releases.setdefault(
                release_id,
                (release, observation.occurred_at),
            )
            binding = self._task_agent_releases.get(observation.task_id)
            if binding is not None and binding[0] != release_id:
                raise ValueError("Task starting AgentRelease is immutable")
            self._task_agent_releases.setdefault(
                observation.task_id,
                (release_id, observation.obs_id),
            )
            return
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
