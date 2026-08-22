from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from ansich import AnsichService, ObservationEnvelope, Producer, new_id
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from support.ansich_settle import only_test_driven_assessments

from deerflow.ansich import create_sql_ansich_service
from deerflow.ansich.persistence.sql import _periodic_budget_rows_statement
from deerflow.ansich.probes import create_task_control_probe
from deerflow.persistence.base import Base


def test_periodic_budget_assessment_filters_running_tasks_for_all_dialects():
    statement = _periodic_budget_rows_statement()

    for dialect in (sqlite.dialect(), postgresql.dialect()):
        compiled = " ".join(str(statement.compile(dialect=dialect)).upper().split())
        assert "JOIN ANSICH_TASK_SUMMARIES" in compiled
        assert "ANSICH_TASK_SUMMARIES.CONTROL_VALUE =" in compiled


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
        await service.rebuild_until_settled()
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
    # Which assertion this Task's budget_health Belief resolves to is exactly
    # what the reads below compare, and two assessors write it: the terminal
    # control projection (budget-health@1) and the absolute-limit assessor job
    # that `assess_operations` drains. The projector loop assesses on its own
    # cadence with a wall-clock `now`, which outranks the simulated `now` this
    # test asserts with - so a background assessment landing between the two
    # reads flips the selected source from budget-health@1 to
    # absolute-limit@1.0.0 and fails the comparison. The test drives every
    # assessment itself instead.
    only_test_driven_assessments(service)
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
    usage_observation = ObservationEnvelope(
        kind="llm.responded",
        subject_type="llm_attempt",
        subject_id=new_id(),
        task_id=task_id,
        occurred_at=observed_at + timedelta(seconds=1),
        producer=Producer(name="budget-health-test", version="1", instance_id="test"),
        source_event_id="run:run-budget-health:llm:responded",
        correlation_id="run-budget-health",
        payload={"attempt_no": 1, "latency_ms": 10, "usage": {"total_tokens": 107}},
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
                usage_observation,
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
        terminal_health = await service.get_task_budget_health(task_id)
        periodic_changes = await service.assess_operations(now=observed_at + timedelta(seconds=3))
        health_after_periodic_assessment = await service.get_task_budget_health(task_id)
        await service.rebuild_until_settled()
        rebuilt_terminal_health = await service.get_task_budget_health(task_id)
    finally:
        await service.stop()
        await engine.dispose()

    assert periodic_changes == 0
    assert len(terminal_health) == 1
    assert len(health_after_periodic_assessment) == 1
    assert len(rebuilt_terminal_health) == 1
    # Pinned, not incidental: the terminal control projection's own assertion is
    # the one both reads must see, so a future writer that overtakes it fails
    # here with a source name instead of flaking on the comparison below.
    assert terminal_health[0].source.name == "budget-health"
    assert health_after_periodic_assessment[0].source.name == "budget-health"
    assert health_after_periodic_assessment[0].model_dump(exclude={"selected_by"}) == terminal_health[0].model_dump(exclude={"selected_by"})
    assert health_after_periodic_assessment[0].selected_by.name == "ansich-default"
    belief = terminal_health[0]
    assert belief.value == "exceeded"
    assert belief.usage_value == 107
    assert belief.overshoot == 7
    assert belief.evidence_obs_ids == (configured.obs_id, usage_observation.obs_id)
    rebuilt = rebuilt_terminal_health[0]
    assert rebuilt.value == belief.value
    assert rebuilt.usage_value == belief.usage_value
    assert rebuilt.hard_limit == belief.hard_limit
    assert rebuilt.overshoot == belief.overshoot
    assert rebuilt.as_of == belief.as_of
    assert rebuilt.evidence_obs_ids == belief.evidence_obs_ids
    assert rebuilt.source.name == "absolute-limit"


@pytest.mark.anyio
async def test_task_scoped_collector_loss_makes_budget_health_unknown(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-budget-loss.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(session_factory, queue_capacity=1)
    only_test_driven_assessments(service)
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
            ObservationEnvelope.task_lifecycle(
                kind="task.started",
                task_id=task_id,
                source_kind="deerflow_run",
                source_id="run-budget-loss",
                occurred_at=observed_at,
                source_event_id="run:run-budget-loss:task:started",
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
