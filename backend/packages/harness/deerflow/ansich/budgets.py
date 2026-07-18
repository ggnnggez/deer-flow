from __future__ import annotations

from typing import Any

from ansich.budget import ResolvedBudget, resolve_budget_limit

from deerflow.config.subagents_config import (
    MAX_TOTAL_SUBAGENTS_PER_RUN,
    MIN_TOTAL_SUBAGENTS_PER_RUN,
)


def _runtime_config(config: dict[str, Any]) -> dict[str, Any]:
    resolved = dict(config.get("configurable", {}) or {})
    context = config.get("context", {}) or {}
    if isinstance(context, dict):
        resolved.update(context)
    return resolved


def resolve_deerflow_task_budgets(
    app_config: object,
    config: dict[str, Any],
) -> tuple[ResolvedBudget, ...]:
    """Resolve only policies that the lead-agent runtime actually enforces."""
    budgets: list[ResolvedBudget] = []
    token_budget = getattr(app_config, "token_budget", None)
    if token_budget is not None and getattr(token_budget, "enabled", False) is True:
        for dimension, configured_limit in (
            ("input_tokens", getattr(token_budget, "max_input_tokens", None)),
            ("output_tokens", getattr(token_budget, "max_output_tokens", None)),
            ("total_tokens", getattr(token_budget, "max_tokens", None)),
        ):
            budget = resolve_budget_limit(
                dimension=dimension,
                release_default=configured_limit,
                warning_fraction=float(token_budget.warn_threshold),
                hard_fraction=float(token_budget.hard_stop_threshold),
                enforcement=True,
            )
            if budget is not None:
                budgets.append(budget)

    runtime = _runtime_config(config)
    if runtime.get("subagent_enabled") is True:
        subagents = getattr(app_config, "subagents", None)
        default_limit = getattr(subagents, "max_total_per_run", None)
        requested_limit = runtime.get("max_total_subagents")
        if not isinstance(requested_limit, int) or isinstance(requested_limit, bool):
            requested_limit = None
        budget = resolve_budget_limit(
            dimension="child_tasks_spawned",
            release_default=default_limit,
            runtime_override=requested_limit,
            minimum=MIN_TOTAL_SUBAGENTS_PER_RUN,
            maximum=MAX_TOTAL_SUBAGENTS_PER_RUN,
            hard_fraction=1.0,
            enforcement=True,
        )
        if budget is not None:
            budgets.append(budget)

    return tuple(budgets)
