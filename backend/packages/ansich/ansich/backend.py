from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol

from ansich.alerts.views import AlertDetailView, AlertSummaryView, BeliefAssertionView
from ansich.budget import BudgetHealthBelief, TaskBudgetsView
from ansich.compression import ContextCompressionSummaryView, ContextCompressionView
from ansich.context_state import ContextStateView
from ansich.contracts import ControlValue, LostRange, ObservationEnvelope, TaskLifecycleScope, TaskView
from ansich.heartbeat import TaskHeartbeatView
from ansich.lineage import ContentBlockView, LineageDirection, PossibleExposureItemView
from ansich.operations import ActiveTaskView, HeartbeatBelief
from ansich.operator import OperatorActionView, TaskActionTarget
from ansich.release import AgentReleaseDetailView, AgentReleaseSummaryView, TaskAgentReleaseView
from ansich.step import ContentBlockPayloadView, ContentOccurrenceView, ContextSnapshotView, LlmAttemptView, StepView
from ansich.tool import ContentDerivationView, ToolCallView
from ansich.usage import TaskUsageView


class AnsichBackend(Protocol):
    async def persist_and_project(self, observations: list[ObservationEnvelope]) -> int: ...

    async def get_task(self, task_id: str) -> TaskView | None: ...

    async def get_task_agent_release(
        self,
        task_id: str,
    ) -> TaskAgentReleaseView | None: ...

    async def get_agent_release(
        self,
        release_id: str,
    ) -> AgentReleaseDetailView | None: ...

    async def list_agent_releases(
        self,
        *,
        limit: int = 100,
        agent_name: str | None = None,
        component_hash: str | None = None,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
    ) -> list[AgentReleaseSummaryView]: ...

    async def get_current_belief(
        self,
        subject_id: str,
        field_name: str,
    ) -> BeliefAssertionView | None: ...

    async def get_task_by_source(self, source_kind: str, source_id: str) -> TaskView | None: ...

    async def list_tasks(
        self,
        *,
        limit: int = 100,
        control: ControlValue | None = None,
        lifecycle_scope: TaskLifecycleScope = "all",
        from_time: datetime | None = None,
        to_time: datetime | None = None,
        cursor: tuple[datetime, str] | None = None,
    ) -> list[TaskView]: ...

    async def list_observations(self, task_id: str) -> list[ObservationEnvelope]: ...

    async def list_alerts(
        self,
        *,
        limit: int,
        alert_type: str | None = None,
        workflow_state: str | None = None,
        task_id: str | None = None,
        severity: str | None = None,
        shadow: bool | None = None,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
        cursor: tuple[datetime, str] | None = None,
    ) -> list[AlertSummaryView]: ...

    async def get_alert_detail(
        self,
        alert_id: str,
    ) -> AlertDetailView | None: ...

    async def change_alert_workflow(
        self,
        alert_id: str,
        *,
        action: Literal["acknowledge", "dismiss"],
        expected_workflow_version: int,
        operator_id: str,
        reason: str | None,
        occurred_at: datetime,
    ) -> AlertSummaryView | None: ...

    async def get_task_action_target(
        self,
        task_id: str,
    ) -> TaskActionTarget | None: ...

    async def get_operator_action(
        self,
        *,
        task_id: str,
        action_type: Literal["interrupt", "rollback"],
        idempotency_key: str,
    ) -> OperatorActionView | None: ...

    async def begin_operator_action(
        self,
        *,
        task_id: str,
        action_type: Literal["interrupt", "rollback"],
        idempotency_key: str,
        operator_id: str,
        occurred_at: datetime,
    ) -> tuple[OperatorActionView, bool]: ...

    async def finish_operator_action(
        self,
        action_id: str,
        *,
        succeeded: bool,
        operator_id: str,
        result: dict[str, object],
        occurred_at: datetime,
    ) -> OperatorActionView | None: ...

    async def get_task_usage(self, task_id: str) -> TaskUsageView: ...

    async def get_task_budgets(self, task_id: str) -> TaskBudgetsView: ...

    async def get_task_budget_health(
        self,
        task_id: str,
    ) -> tuple[BudgetHealthBelief, ...]: ...

    async def get_task_heartbeat(self, task_id: str) -> TaskHeartbeatView | None: ...

    async def assess_operations(
        self,
        *,
        now: datetime | None = None,
        incomplete_task_ids: tuple[str, ...] = (),
        global_loss: bool = False,
        lost_ranges: tuple[LostRange, ...] = (),
    ) -> int: ...

    async def get_task_heartbeat_belief(
        self,
        task_id: str,
    ) -> HeartbeatBelief | None: ...

    async def list_active_tasks(
        self,
        *,
        limit: int = 100,
        owner_id: str | None = None,
        agent_id: str | None = None,
        control: ControlValue | None = None,
        heartbeat_status: str | None = None,
        budget_status: str | None = None,
        min_duration_ms: int | None = None,
        max_duration_ms: int | None = None,
        observability_status: str | None = None,
        cursor: tuple[datetime, str] | None = None,
    ) -> list[ActiveTaskView]: ...

    async def list_timeline(
        self,
        task_id: str,
        *,
        limit: int,
        cursor: tuple[datetime, int] | None = None,
    ) -> list[tuple[int, ObservationEnvelope]]: ...

    async def get_max_step_seq(self, task_id: str) -> int: ...

    async def list_content_occurrences(self, task_id: str) -> list[ContentOccurrenceView]: ...

    async def get_latest_context_state(self, task_id: str) -> ContextStateView | None: ...

    async def list_steps(self, task_id: str) -> list[StepView]: ...

    async def list_system_operations(self, task_id: str) -> list[LlmAttemptView]: ...

    async def get_step(self, step_id: str) -> StepView | None: ...

    async def get_tool_call(self, tool_call_id: str) -> ToolCallView | None: ...

    async def get_step_context(self, step_id: str) -> ContextSnapshotView | None: ...

    async def get_context_snapshot(
        self,
        snapshot_id: str,
    ) -> ContextSnapshotView | None: ...

    async def get_content_block_payload(self, block_id: str) -> ContentBlockPayloadView | None: ...

    async def get_context_compression(
        self,
        compression_id: str,
    ) -> ContextCompressionView | None: ...

    async def list_context_compressions(
        self,
        task_id: str,
        *,
        limit: int = 100,
        cursor: tuple[datetime, str] | None = None,
    ) -> list[ContextCompressionSummaryView]: ...

    async def get_content_blocks(
        self,
        block_ids: tuple[str, ...],
    ) -> list[ContentBlockView]: ...

    async def list_content_derivations(
        self,
        block_ids: tuple[str, ...],
        direction: LineageDirection,
    ) -> list[ContentDerivationView]: ...

    async def list_snapshot_exposures(
        self,
        root_block_id: str,
        descendant_block_ids: tuple[str, ...],
    ) -> list[PossibleExposureItemView]: ...
