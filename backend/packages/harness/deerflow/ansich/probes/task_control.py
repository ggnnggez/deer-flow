from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from itertools import count
from threading import Lock
from uuid import uuid4

from ansich import AnsichService, ObservationEnvelope, Producer, new_id
from ansich.budget import ResolvedBudget
from ansich.release import AgentRuntimeDescriptor, build_agent_release

from deerflow.ansich.budgets import resolve_deerflow_task_budgets
from deerflow.runtime.user_context import get_effective_user_id

logger = logging.getLogger(__name__)

_PRODUCER_INSTANCE_ID = str(uuid4())
_PRODUCER_SEQUENCE = count(1)
_PRODUCER_SEQUENCE_LOCK = Lock()

#: Every terminal RunStatus must map to a terminal Task control kind; a run
#: that times out is a failure from the observability perspective.
_TERMINAL_KIND_BY_STATUS = {
    "success": "task.completed",
    "error": "task.failed",
    "timeout": "task.failed",
    "interrupted": "task.interrupted",
}


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
        monotonic: Callable[[], float] = time.monotonic,
        budgets: tuple[ResolvedBudget, ...] = (),
    ) -> None:
        self._service = service
        self.task_id = new_id()
        self._run_id = run_id
        self._thread_id = thread_id
        self._owner_id = owner_id
        self._trigger_kind = trigger_kind
        self._monotonic = monotonic
        self._started_monotonic: float | None = None
        self._budgets = budgets

    def created(self) -> None:
        self._record("task.created")
        for budget in self._budgets:
            self._record_budget(budget)

    def started(self) -> None:
        try:
            self._started_monotonic = self._monotonic()
        except Exception:
            self._started_monotonic = None
            logger.warning(
                "Ansich Task monotonic start capture failed for run %s",
                self._run_id,
                exc_info=True,
            )
        self._record("task.started")

    def agent_release_resolved(
        self,
        descriptor: AgentRuntimeDescriptor | object,
        *,
        known_secrets: Sequence[str] = (),
    ) -> None:
        """Resolve and record the immutable starting actor without gating the Run."""

        if self._service is None:
            return
        try:
            release = build_agent_release(
                AgentRuntimeDescriptor.model_validate(descriptor),
                known_secrets=known_secrets,
            )
            self._service.record(
                ObservationEnvelope.agent_release_resolved(
                    task_id=self.task_id,
                    run_id=self._run_id,
                    occurred_at=datetime.now(UTC),
                    release=release,
                    source_event_id=f"run:{self._run_id}:agent-release:resolved",
                    producer_seq=_next_producer_sequence(),
                    producer_name="deerflow-agent-release",
                    producer_version="1",
                    producer_instance_id=_PRODUCER_INSTANCE_ID,
                )
            )
        except Exception:
            logger.warning(
                "Ansich AgentRelease resolution failed for run %s",
                self._run_id,
            )
            try:
                self._service.record(
                    ObservationEnvelope(
                        kind="observability.degraded",
                        occurred_at=datetime.now(UTC),
                        task_id=self.task_id,
                        subject_id=self.task_id,
                        producer=Producer(
                            name="deerflow-agent-release",
                            version="1",
                            instance_id=_PRODUCER_INSTANCE_ID,
                        ),
                        producer_seq=_next_producer_sequence(),
                        source_event_id=(f"run:{self._run_id}:agent-release:resolution-failed"),
                        correlation_id=self._run_id,
                        payload={
                            "component": "agent_release",
                            "reason": "resolution_failed",
                        },
                    )
                )
            except Exception:
                logger.warning(
                    "Ansich AgentRelease degradation observation failed for run %s",
                    self._run_id,
                )

    async def terminal(self, status: str) -> None:
        kind = _TERMINAL_KIND_BY_STATUS.get(status)
        self._record_wall_time()
        if kind is not None:
            self._record(kind)
        else:
            logger.warning(
                "Ansich has no terminal control mapping for run %s status %r; Task control stays non-terminal",
                self._run_id,
                status,
            )
        if self._service is not None:
            try:
                await self._service.flush_task(self.task_id)
            except Exception:
                logger.warning("Ansich terminal flush failed for run %s", self._run_id, exc_info=True)

    def _record_wall_time(self) -> None:
        if self._service is None or self._started_monotonic is None:
            return
        try:
            elapsed_ms = max(
                0,
                int((self._monotonic() - self._started_monotonic) * 1000),
            )
            self._service.record(
                ObservationEnvelope.budget_consumed(
                    task_id=self.task_id,
                    run_id=self._run_id,
                    occurred_at=datetime.now(UTC),
                    dimension="wall_time_ms",
                    delta=elapsed_ms,
                    source_event_id=f"run:{self._run_id}:budget:wall_time_ms:terminal",
                    producer_seq=_next_producer_sequence(),
                    producer_name="deerflow-task-control",
                    producer_version="1",
                    producer_instance_id=_PRODUCER_INSTANCE_ID,
                )
            )
        except Exception:
            logger.warning(
                "Ansich wall-time observation failed for run %s",
                self._run_id,
                exc_info=True,
            )

    def _record_budget(self, budget: ResolvedBudget) -> None:
        if self._service is None:
            return
        try:
            self._service.record(
                ObservationEnvelope.budget_configured(
                    task_id=self.task_id,
                    run_id=self._run_id,
                    occurred_at=datetime.now(UTC),
                    dimension=budget.dimension,
                    aggregation_scope=budget.aggregation_scope,
                    warning_limit=budget.warning_limit,
                    hard_limit=budget.hard_limit,
                    enforcement=budget.enforcement,
                    source_kind=budget.source_kind,
                    requested_value=budget.requested_value,
                    effective_value=budget.effective_value,
                    source_event_id=(f"run:{self._run_id}:budget:{budget.dimension}:{budget.aggregation_scope}:configured"),
                    producer_seq=_next_producer_sequence(),
                    producer_name="deerflow-budget-configuration",
                    producer_version="1",
                    producer_instance_id=_PRODUCER_INSTANCE_ID,
                )
            )
        except Exception:
            logger.warning(
                "Ansich budget observation failed for run %s dimension %s",
                self._run_id,
                budget.dimension,
                exc_info=True,
            )

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
    app_config: object | None = None,
) -> TaskControlProbe:
    context = config.get("context")
    owner_id = context.get("user_id") if isinstance(context, dict) else None
    if not isinstance(owner_id, str):
        owner_id = get_effective_user_id()
    trigger_kind = "scheduled" if isinstance(context, dict) and context.get("non_interactive") is True else "interactive"
    budgets = resolve_deerflow_task_budgets(app_config, config) if app_config is not None else ()
    return TaskControlProbe(
        service,
        run_id=run_id,
        thread_id=thread_id,
        owner_id=owner_id,
        trigger_kind=trigger_kind,
        budgets=budgets,
    )
