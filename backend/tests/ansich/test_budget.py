from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from ansich import AnsichService
from ansich.budget import TaskBudgetView, assess_budget_health, resolve_budget_limit
from ansich.usage import TaskUsageValue

from deerflow.ansich.budgets import resolve_deerflow_task_budgets
from deerflow.ansich.probes import create_task_control_probe


def test_budget_resolution_uses_release_default_when_no_override_exists():
    budget = resolve_budget_limit(
        dimension="total_tokens",
        release_default=100_000,
        warning_fraction=0.8,
        hard_fraction=1.0,
        enforcement=True,
    )

    assert budget is not None
    assert budget.source_kind == "release_default"
    assert budget.requested_value is None
    assert budget.effective_value == 100_000
    assert budget.warning_limit == 80_000
    assert budget.hard_limit == 100_000
    assert budget.enforcement is True
    assert budget.aggregation_scope == "local"


def test_budget_resolution_preserves_requested_value_when_runtime_override_is_clamped():
    budget = resolve_budget_limit(
        dimension="child_tasks_spawned",
        release_default=6,
        runtime_override=80,
        minimum=1,
        maximum=50,
        hard_fraction=1.0,
        enforcement=True,
    )

    assert budget is not None
    assert budget.source_kind == "runtime_override"
    assert budget.requested_value == 80
    assert budget.effective_value == 50
    assert budget.warning_limit is None
    assert budget.hard_limit == 50


def test_budget_resolution_returns_none_when_dimension_is_not_configured():
    assert (
        resolve_budget_limit(
            dimension="wall_time_ms",
            release_default=None,
            enforcement=False,
        )
        is None
    )


def test_deerflow_budget_resolution_only_marks_live_runtime_policies_as_enforced():
    app_config = SimpleNamespace(
        token_budget=SimpleNamespace(
            enabled=True,
            max_tokens=100_000,
            max_input_tokens=60_000,
            max_output_tokens=None,
            warn_threshold=0.8,
            hard_stop_threshold=1.0,
        ),
        subagents=SimpleNamespace(max_total_per_run=6),
    )
    run_config = {
        "configurable": {
            "subagent_enabled": True,
            "max_total_subagents": 80,
        }
    }

    budgets = resolve_deerflow_task_budgets(app_config, run_config)

    assert [budget.dimension for budget in budgets] == [
        "input_tokens",
        "total_tokens",
        "child_tasks_spawned",
    ]
    assert all(budget.enforcement for budget in budgets)
    assert budgets[0].hard_limit == 60_000
    assert budgets[1].warning_limit == 80_000
    assert budgets[2].source_kind == "runtime_override"
    assert budgets[2].requested_value == 80
    assert budgets[2].effective_value == 50


@pytest.mark.asyncio
async def test_task_admission_records_each_effective_budget_after_task_creation():
    service = AnsichService.in_memory()
    await service.start()
    app_config = SimpleNamespace(
        token_budget=SimpleNamespace(
            enabled=True,
            max_tokens=100_000,
            max_input_tokens=None,
            max_output_tokens=None,
            warn_threshold=0.8,
            hard_stop_threshold=1.0,
        ),
        subagents=SimpleNamespace(max_total_per_run=6),
    )
    probe = create_task_control_probe(
        service,
        run_id="run-budget-admission",
        thread_id="thread-budget-admission",
        config={"configurable": {"subagent_enabled": False}},
        app_config=app_config,
    )

    try:
        probe.created()
        await service.flush_task(probe.task_id)
        observations = await service.list_observations(probe.task_id)
    finally:
        await service.stop()

    assert [item.kind for item in observations] == [
        "task.created",
        "budget.configured",
    ]
    assert observations[1].payload == {
        "dimension": "total_tokens",
        "aggregation_scope": "local",
        "warning_limit": 80_000,
        "hard_limit": 100_000,
        "enforcement": True,
        "source_kind": "release_default",
        "requested_value": None,
        "effective_value": 100_000,
    }


def test_budget_health_uses_effective_thresholds_and_reports_overshoot():
    budget = TaskBudgetView(
        entity_id="budget-1",
        task_id="task-1",
        dimension="total_tokens",
        aggregation_scope="local",
        warning_limit=80,
        hard_limit=100,
        enforcement=True,
        source_kind="runtime_override",
        requested_value=150,
        effective_value=100,
        configured_obs_id="obs-budget",
    )
    at = datetime(2026, 7, 18, 12, tzinfo=UTC)

    within = assess_budget_health(
        budget,
        TaskUsageValue(
            dimension="total_tokens",
            aggregation_scope="local",
            value=79,
            as_of=at,
            complete_through_ingest_seq=9,
        ),
        now=at,
    )
    warning = assess_budget_health(
        budget,
        TaskUsageValue(
            dimension="total_tokens",
            aggregation_scope="local",
            value=100,
            as_of=at,
            complete_through_ingest_seq=10,
        ),
        now=at,
    )
    exceeded = assess_budget_health(
        budget,
        TaskUsageValue(
            dimension="total_tokens",
            aggregation_scope="local",
            value=107,
            as_of=at,
            complete_through_ingest_seq=11,
        ),
        now=at,
    )

    assert within.value == "within"
    assert warning.value == "warning"
    assert warning.overshoot == 0
    assert exceeded.value == "exceeded"
    assert exceeded.overshoot == 7
    assert exceeded.evidence_obs_ids == ("obs-budget",)


def test_budget_health_is_unknown_when_usage_is_missing_or_incomplete():
    budget = TaskBudgetView(
        entity_id="budget-2",
        task_id="task-1",
        dimension="steps",
        aggregation_scope="local",
        warning_limit=None,
        hard_limit=20,
        enforcement=False,
        source_kind="shadow",
        requested_value=None,
        effective_value=20,
        configured_obs_id="obs-budget-2",
    )
    at = datetime(2026, 7, 18, 12, tzinfo=UTC)
    usage = TaskUsageValue(
        dimension="steps",
        aggregation_scope="local",
        value=4,
        as_of=at,
        complete_through_ingest_seq=3,
    )

    missing = assess_budget_health(budget, None, now=at)
    incomplete = assess_budget_health(
        budget,
        usage,
        now=at,
        usage_complete=False,
    )

    assert missing.value == "unknown"
    assert missing.usage_value is None
    assert incomplete.value == "unknown"
    assert incomplete.usage_value == 4
