from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from ansich import AnsichService, ObservationEnvelope, Producer, new_id
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from deerflow.ansich import create_sql_ansich_service
from deerflow.ansich.probes import create_task_control_probe
from deerflow.persistence.base import Base


@pytest.mark.anyio
async def test_sql_budget_projection_preserves_effective_policy_across_rebuild(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-budget.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service: AnsichService = create_sql_ansich_service(session_factory)
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
        run_id="run-sql-budget",
        thread_id="thread-sql-budget",
        config={
            "configurable": {
                "subagent_enabled": True,
                "max_total_subagents": 80,
            }
        },
        app_config=app_config,
    )

    try:
        probe.created()
        await service.flush_task(probe.task_id)
        budgets = await service.get_task_budgets(probe.task_id)
        await service.rebuild_projections()
        rebuilt = await service.get_task_budgets(probe.task_id)
    finally:
        await service.stop()
        await engine.dispose()

    assert budgets == rebuilt
    assert [budget.dimension for budget in budgets.budgets] == [
        "total_tokens",
        "child_tasks_spawned",
    ]
    token_budget, child_budget = budgets.budgets
    assert token_budget.aggregation_scope == "local"
    assert token_budget.warning_limit == 80_000
    assert token_budget.hard_limit == 100_000
    assert token_budget.enforcement is True
    assert token_budget.source_kind == "release_default"
    assert token_budget.requested_value is None
    assert token_budget.effective_value == 100_000
    assert token_budget.configured_obs_id
    assert child_budget.source_kind == "runtime_override"
    assert child_budget.requested_value == 80
    assert child_budget.effective_value == 50


@pytest.mark.anyio
async def test_sql_budget_health_retains_terminal_overshoot_and_evidence(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-budget-health.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(session_factory)
    await service.start()
    task_id = new_id()
    observed_at = datetime(2026, 7, 18, 13, tzinfo=UTC)
    configured = ObservationEnvelope.budget_configured(
        task_id=task_id,
        run_id="run-budget-health",
        occurred_at=observed_at,
        dimension="total_tokens",
        aggregation_scope="local",
        warning_limit=80,
        hard_limit=100,
        enforcement=True,
        source_kind="release_default",
        requested_value=None,
        effective_value=100,
        source_event_id="run:run-budget-health:budget:total_tokens",
    )
    consumed = ObservationEnvelope.budget_consumed(
        task_id=task_id,
        run_id="run-budget-health",
        occurred_at=observed_at + timedelta(seconds=1),
        dimension="total_tokens",
        delta=107,
        source_event_id="run:run-budget-health:usage:total_tokens",
    )

    try:
        service.record_batch(
            (
                ObservationEnvelope.task_lifecycle(
                    kind="task.created",
                    task_id=task_id,
                    source_kind="deerflow_run",
                    source_id="run-budget-health",
                    occurred_at=observed_at,
                    source_event_id="run:run-budget-health:task:created",
                ),
                ObservationEnvelope.task_lifecycle(
                    kind="task.started",
                    task_id=task_id,
                    source_kind="deerflow_run",
                    source_id="run-budget-health",
                    occurred_at=observed_at,
                    source_event_id="run:run-budget-health:task:started",
                ),
                configured,
                consumed,
                ObservationEnvelope.task_lifecycle(
                    kind="task.completed",
                    task_id=task_id,
                    source_kind="deerflow_run",
                    source_id="run-budget-health",
                    occurred_at=observed_at + timedelta(seconds=2),
                    source_event_id="run:run-budget-health:task:completed",
                ),
            )
        )
        await service.flush_task(task_id)
        await service.assess_operations(now=observed_at + timedelta(seconds=3))
        health = await service.get_task_budget_health(task_id)
    finally:
        await service.stop()
        await engine.dispose()

    assert len(health) == 1
    belief = health[0]
    assert belief.value == "exceeded"
    assert belief.usage_value == 107
    assert belief.overshoot == 7
    assert belief.evidence_obs_ids == (configured.obs_id, consumed.obs_id)


@pytest.mark.anyio
async def test_task_scoped_collector_loss_makes_budget_health_unknown(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-budget-loss.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(session_factory, queue_capacity=1)
    await service.start()
    task_id = new_id()
    step_id = new_id()
    observed_at = datetime(2026, 7, 18, 13, 30, tzinfo=UTC)

    try:
        for observation in (
            ObservationEnvelope.task_lifecycle(
                kind="task.created",
                task_id=task_id,
                source_kind="deerflow_run",
                source_id="run-budget-loss",
                occurred_at=observed_at,
                source_event_id="run:run-budget-loss:task:created",
            ),
            ObservationEnvelope.budget_configured(
                task_id=task_id,
                run_id="run-budget-loss",
                occurred_at=observed_at,
                dimension="steps",
                aggregation_scope="local",
                warning_limit=8,
                hard_limit=10,
                enforcement=False,
                source_kind="shadow",
                requested_value=None,
                effective_value=10,
                source_event_id="run:run-budget-loss:budget:steps",
            ),
            ObservationEnvelope(
                kind="step.started",
                occurred_at=observed_at,
                task_id=task_id,
                step_id=step_id,
                subject_type="step",
                subject_id=step_id,
                producer=Producer(
                    name="budget-loss-test",
                    version="1",
                    instance_id="test",
                ),
                source_event_id="run:run-budget-loss:step:1",
                correlation_id="run-budget-loss",
                payload={"step_seq": 1, "actor_kind": "lead_agent"},
            ),
        ):
            assert service.record(observation).accepted
            await service.flush_task(task_id)
        dropped = service.record_batch(
            (
                ObservationEnvelope.task_heartbeat(
                    task_id=task_id,
                    run_id="run-budget-loss",
                    occurred_at=observed_at,
                    elapsed_ms=1,
                    worker_id="worker-a",
                    ownership_epoch="worker-a",
                    source_event_id="run:run-budget-loss:heartbeat:1",
                ),
                ObservationEnvelope.task_heartbeat(
                    task_id=task_id,
                    run_id="run-budget-loss",
                    occurred_at=observed_at,
                    elapsed_ms=2,
                    worker_id="worker-a",
                    ownership_epoch="worker-a",
                    source_event_id="run:run-budget-loss:heartbeat:2",
                    producer_seq=2,
                ),
            )
        )
        assert all(not receipt.accepted for receipt in dropped)
        await service.assess_operations(now=observed_at + timedelta(seconds=1))
        health = await service.get_task_budget_health(task_id)
    finally:
        await service.stop()
        await engine.dispose()

    assert len(health) == 1
    assert health[0].value == "unknown"
    assert health[0].usage_value == 1
