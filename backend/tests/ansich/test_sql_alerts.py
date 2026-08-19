import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from ansich import AnsichService, ObservationEnvelope, Producer, new_id
from ansich.alerts import AlertWorkflowConflict
from sqlalchemy import create_engine, event, func, inspect, select, text
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateTable
from support.ansich_settle import only_test_driven_assessments

from deerflow.ansich import create_sql_ansich_service
from deerflow.ansich.persistence.models import (
    AnsichAlertEvidenceRow,
    AnsichAlertReadModelRow,
    AnsichAlertRow,
    AnsichAlertWorkflowEventRow,
    AnsichAssessorErrorRow,
    AnsichAssessorJobRow,
    AnsichBeliefAssertionRow,
    AnsichCurrentBeliefRow,
    AnsichObservationRow,
    AnsichOperatorActionRow,
)
from deerflow.ansich.persistence.sql import (
    _STALE_REQUESTED_TAKEOVER_AFTER,
    SqlAnsichBackend,
    _action_repetition_rows_statement,
    _reconciliation_alert_rows_statement,
)
from deerflow.persistence.base import Base


async def _record_action_step(
    service: AnsichService,
    *,
    task_id: str,
    step_seq: int,
    args: dict[str, object],
    observed_at: datetime,
) -> str:
    step_id = new_id()
    tool_call_id = new_id()
    producer = Producer(
        name="phase6-sql-test",
        version="1",
        instance_id="test",
    )
    issued = ObservationEnvelope(
        kind="tool.issued",
        occurred_at=observed_at,
        task_id=task_id,
        step_id=step_id,
        subject_type="tool_call",
        subject_id=tool_call_id,
        producer=producer,
        source_event_id=f"tool:{tool_call_id}:issued",
        correlation_id=task_id,
        payload={
            "call_seq": 1,
            "provider_call_id": f"provider-{step_seq}",
            "tool_name": "web_search",
            "args_hash": f"{step_seq:064x}",
            "args_preview": args,
            "tool_schema_block_id": None,
        },
    )
    service.record_batch(
        (
            ObservationEnvelope(
                kind="step.started",
                occurred_at=observed_at,
                task_id=task_id,
                step_id=step_id,
                subject_type="step",
                subject_id=step_id,
                producer=producer,
                source_event_id=f"step:{step_id}:started",
                correlation_id=task_id,
                payload={"step_seq": step_seq, "actor_kind": "lead_agent"},
            ),
            issued,
            ObservationEnvelope(
                kind="step.closed",
                occurred_at=observed_at + timedelta(milliseconds=1),
                task_id=task_id,
                step_id=step_id,
                subject_type="step",
                subject_id=step_id,
                producer=producer,
                source_event_id=f"step:{step_id}:closed",
                correlation_id=task_id,
                causation_obs_id=issued.obs_id,
                payload={
                    "result": "acting",
                    "effective_attempt_no": None,
                    "issued_tools": [],
                },
            ),
        )
    )
    await service.flush_task(task_id)
    return issued.obs_id


@pytest.mark.anyio
async def test_sql_assessor_job_projects_exact_repetition_belief_and_alert(
    tmp_path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-phase6-repetition.db'}")

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(
        session_factory,
        exact_repetition_window=3,
        operations_assessment_interval_ms=60_000,
    )
    only_test_driven_assessments(service)
    await service.start()
    task_id = new_id()
    started_at = datetime(2026, 7, 18, 16, 30, tzinfo=UTC)
    try:
        service.record_batch(
            (
                ObservationEnvelope.task_lifecycle(
                    kind="task.created",
                    task_id=task_id,
                    source_kind="deerflow_run",
                    source_id="run-phase6-repetition",
                    occurred_at=started_at,
                    source_event_id="run:phase6-repetition:task:created",
                ),
                ObservationEnvelope.task_lifecycle(
                    kind="task.started",
                    task_id=task_id,
                    source_kind="deerflow_run",
                    source_id="run-phase6-repetition",
                    occurred_at=started_at,
                    source_event_id="run:phase6-repetition:task:started",
                ),
            )
        )
        await service.flush_task(task_id)
        issued_obs_ids = tuple(
            [
                await _record_action_step(
                    service,
                    task_id=task_id,
                    step_seq=step_seq,
                    args={"query": "same"},
                    observed_at=started_at + timedelta(seconds=step_seq),
                )
                for step_seq in range(1, 4)
            ]
        )
        changed = await service.assess_operations(now=started_at + timedelta(seconds=5))
        async with session_factory() as session:
            jobs = list(
                (
                    await session.execute(
                        select(AnsichAssessorJobRow).where(
                            AnsichAssessorJobRow.subject_id == task_id,
                            AnsichAssessorJobRow.assessor_name == "action-repetition",
                        )
                    )
                ).scalars()
            )
            current = await session.get(
                AnsichCurrentBeliefRow,
                (task_id, "behavior"),
            )
            assertion = (
                None
                if current is None
                else await session.get(
                    AnsichBeliefAssertionRow,
                    current.assertion_id,
                )
            )
            alerts = list((await session.execute(select(AnsichAlertRow).where(AnsichAlertRow.subject_id == task_id))).scalars())
            evidence = [] if not alerts else list((await session.execute(select(AnsichAlertEvidenceRow).where(AnsichAlertEvidenceRow.alert_id == alerts[0].entity_id).order_by(AnsichAlertEvidenceRow.ordinal))).scalars())
        listed_alerts = await service.list_alerts(
            limit=10,
            alert_type="exact_repetition",
            workflow_state="open",
            task_id=task_id,
        )
        detail = await service.get_alert_detail(alerts[0].entity_id)
        acknowledged = await service.acknowledge_alert(
            alerts[0].entity_id,
            expected_workflow_version=1,
            operator_id="admin-1",
            occurred_at=started_at + timedelta(seconds=6),
        )
        with pytest.raises(AlertWorkflowConflict):
            await service.dismiss_alert(
                alerts[0].entity_id,
                expected_workflow_version=1,
                operator_id="admin-1",
                reason="stale browser state",
                occurred_at=started_at + timedelta(seconds=7),
            )
        dismissed = await service.dismiss_alert(
            alerts[0].entity_id,
            expected_workflow_version=2,
            operator_id="admin-1",
            reason="known maintenance loop",
            occurred_at=started_at + timedelta(seconds=7),
        )
        workflow_detail = await service.get_alert_detail(alerts[0].entity_id)
    finally:
        await service.stop()
        await engine.dispose()

    assert changed > 0
    assert jobs
    assert all(job.status == "completed" for job in jobs)
    assert assertion is not None
    assert assertion.value_json["value"] == "runaway"
    assert assertion.assessor_name == "behavior-aggregate"
    assert len(alerts) == 1
    assert alerts[0].alert_type == "exact_repetition"
    assert alerts[0].workflow_state == "open"
    assert [item.obs_id for item in evidence] == list(issued_obs_ids)
    assert [item.alert_id for item in listed_alerts] == [alerts[0].entity_id]
    assert detail is not None
    assert detail.source_belief.assessor.name == "action-repetition"
    assert [item.obs_id for item in detail.evidence] == list(issued_obs_ids)
    assert detail.available_actions == (
        "acknowledge",
        "dismiss",
        "interrupt",
        "rollback",
    )
    assert acknowledged.workflow_state == "acknowledged"
    assert acknowledged.workflow_version == 2
    assert dismissed.workflow_state == "dismissed"
    assert dismissed.workflow_version == 3
    assert workflow_detail is not None
    assert [item.action for item in workflow_detail.workflow_history] == [
        "acknowledge",
        "dismiss",
    ]


@pytest.mark.anyio
async def test_sql_assessor_jobs_coalesce_to_highest_pending_watermark(
    tmp_path,
    monkeypatch,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-phase6-assessor-coalescing.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    backend = SqlAnsichBackend(
        session_factory,
        exact_repetition_window=3,
    )
    service = AnsichService(
        backend,
        flush_interval_ms=60_000,
        operations_assessment_interval_ms=60_000,
    )
    task_id = new_id()
    started_at = datetime(2026, 7, 18, 16, 45, tzinfo=UTC)
    evaluated_watermarks: list[int] = []
    assessment_statements: list[str] = []
    original = backend._assess_action_repetition_at

    async def count_assessment(*args, evidence_watermark: int, **kwargs):
        evaluated_watermarks.append(evidence_watermark)
        return await original(
            *args,
            evidence_watermark=evidence_watermark,
            **kwargs,
        )

    def capture_assessment_sql(
        _connection,
        _cursor,
        statement,
        _parameters,
        _context,
        _executemany,
    ) -> None:
        assessment_statements.append(" ".join(statement.lower().split()))

    monkeypatch.setattr(
        backend,
        "_assess_action_repetition_at",
        count_assessment,
    )
    event.listen(
        engine.sync_engine,
        "before_cursor_execute",
        capture_assessment_sql,
    )
    # The 60s cadence above only spaces out the projector loop's *periodic*
    # assessments; its first iteration assesses unconditionally, and under
    # suite load that one call can slip past the Observations below and drain
    # the very assessor jobs whose coalescing this test counts.
    only_test_driven_assessments(service)
    await service.start()
    try:
        service.record_batch(
            (
                ObservationEnvelope.task_lifecycle(
                    kind="task.created",
                    task_id=task_id,
                    source_kind="deerflow_run",
                    source_id="run-phase6-assessor-coalescing",
                    occurred_at=started_at,
                    source_event_id="run:phase6-assessor-coalescing:task:created",
                ),
                ObservationEnvelope.task_lifecycle(
                    kind="task.started",
                    task_id=task_id,
                    source_kind="deerflow_run",
                    source_id="run-phase6-assessor-coalescing",
                    occurred_at=started_at,
                    source_event_id="run:phase6-assessor-coalescing:task:started",
                ),
            )
        )
        await service.flush_task(task_id)
        issued_obs_ids = tuple(
            [
                await _record_action_step(
                    service,
                    task_id=task_id,
                    step_seq=step_seq,
                    args={"query": "same"},
                    observed_at=started_at + timedelta(seconds=step_seq),
                )
                for step_seq in range(1, 4)
            ]
        )
        async with session_factory() as session:
            pending_count = int(
                await session.scalar(
                    select(func.count())
                    .select_from(AnsichAssessorJobRow)
                    .where(
                        AnsichAssessorJobRow.subject_id == task_id,
                        AnsichAssessorJobRow.assessor_name == "action-repetition",
                        AnsichAssessorJobRow.status == "pending",
                    )
                )
                or 0
            )
            highest_watermark = await session.scalar(
                select(func.max(AnsichAssessorJobRow.evidence_watermark)).where(
                    AnsichAssessorJobRow.subject_id == task_id,
                    AnsichAssessorJobRow.assessor_name == "action-repetition",
                )
            )
        await service.assess_operations(now=started_at + timedelta(seconds=5))
        signal = await service.get_current_belief(
            task_id,
            "behavior_signal:action-repetition",
        )
        async with session_factory() as session:
            jobs = list(
                (
                    await session.execute(
                        select(AnsichAssessorJobRow).where(
                            AnsichAssessorJobRow.subject_id == task_id,
                            AnsichAssessorJobRow.assessor_name == "action-repetition",
                        )
                    )
                ).scalars()
            )
    finally:
        event.remove(
            engine.sync_engine,
            "before_cursor_execute",
            capture_assessment_sql,
        )
        await service.stop()
        await engine.dispose()

    assert pending_count > 1
    assert highest_watermark is not None
    assert evaluated_watermarks == [highest_watermark]
    assert jobs
    assert all(job.status == "completed" for job in jobs)
    assert sum(job.attempts for job in jobs) == 1
    assert signal is not None
    assert signal.value["value"] == "runaway"
    assert signal.evidence_obs_ids == issued_obs_ids
    step_tool_joins = [statement for statement in assessment_statements if "from ansich_steps" in statement and "join ansich_tool_calls" in statement]
    assert len(step_tool_joins) == 1


@pytest.mark.anyio
async def test_sql_tool_frequency_alert_does_not_mark_behavior_runaway(
    tmp_path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-phase6-frequency.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(
        session_factory,
        exact_repetition_window=3,
        tool_frequency_window_seconds=60,
        tool_frequency_threshold=3,
        operations_assessment_interval_ms=60_000,
    )
    only_test_driven_assessments(service)
    await service.start()
    task_id = new_id()
    started_at = datetime(2026, 7, 18, 16, 45, tzinfo=UTC)
    try:
        service.record_batch(
            (
                ObservationEnvelope.task_lifecycle(
                    kind="task.created",
                    task_id=task_id,
                    source_kind="deerflow_run",
                    source_id="run-phase6-frequency",
                    occurred_at=started_at,
                    source_event_id="run:phase6-frequency:task:created",
                ),
                ObservationEnvelope.task_lifecycle(
                    kind="task.started",
                    task_id=task_id,
                    source_kind="deerflow_run",
                    source_id="run-phase6-frequency",
                    occurred_at=started_at,
                    source_event_id="run:phase6-frequency:task:started",
                ),
            )
        )
        await service.flush_task(task_id)
        for step_seq in range(1, 4):
            await _record_action_step(
                service,
                task_id=task_id,
                step_seq=step_seq,
                args={"query": f"different-{step_seq}"},
                observed_at=started_at + timedelta(seconds=step_seq),
            )
        await service.assess_operations(now=started_at + timedelta(seconds=5))
        async with session_factory() as session:
            current = await session.get(
                AnsichCurrentBeliefRow,
                (task_id, "behavior"),
            )
            assertion = (
                None
                if current is None
                else await session.get(
                    AnsichBeliefAssertionRow,
                    current.assertion_id,
                )
            )
            alerts = list((await session.execute(select(AnsichAlertRow).where(AnsichAlertRow.subject_id == task_id))).scalars())
    finally:
        await service.stop()
        await engine.dispose()

    assert assertion is not None
    assert assertion.value_json["value"] == "unassessed"
    assert [alert.alert_type for alert in alerts] == ["tool_frequency"]


@pytest.mark.anyio
async def test_sql_absolute_budget_breach_marks_runaway_and_opens_alert(
    tmp_path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-phase6-absolute.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(
        session_factory,
        operations_assessment_interval_ms=60_000,
    )
    only_test_driven_assessments(service)
    await service.start()
    task_id = new_id()
    started_at = datetime(2026, 7, 18, 17, tzinfo=UTC)
    configured = ObservationEnvelope.budget_configured(
        task_id=task_id,
        run_id="run-phase6-absolute",
        occurred_at=started_at,
        dimension="total_tokens",
        aggregation_scope="local",
        warning_limit=80,
        hard_limit=100,
        enforcement=True,
        source_kind="release_default",
        requested_value=None,
        effective_value=100,
        source_event_id="run:phase6-absolute:budget:configured",
    )
    usage_observation = ObservationEnvelope(
        kind="llm.responded",
        subject_type="llm_attempt",
        subject_id=new_id(),
        task_id=task_id,
        occurred_at=started_at + timedelta(seconds=1),
        producer=Producer(name="phase6-budget-test", version="1", instance_id="test"),
        source_event_id="run:phase6-absolute:llm:responded",
        correlation_id="run-phase6-absolute",
        payload={"attempt_no": 1, "latency_ms": 10, "usage": {"total_tokens": 101}},
    )
    try:
        service.record_batch(
            (
                ObservationEnvelope.task_lifecycle(
                    kind="task.created",
                    task_id=task_id,
                    source_kind="deerflow_run",
                    source_id="run-phase6-absolute",
                    occurred_at=started_at,
                    source_event_id="run:phase6-absolute:task:created",
                ),
                ObservationEnvelope.task_lifecycle(
                    kind="task.started",
                    task_id=task_id,
                    source_kind="deerflow_run",
                    source_id="run-phase6-absolute",
                    occurred_at=started_at,
                    source_event_id="run:phase6-absolute:task:started",
                ),
                configured,
                usage_observation,
            )
        )
        await service.flush_task(task_id)
        await service.assess_operations(now=started_at + timedelta(seconds=2))
        async with session_factory() as session:
            current = await session.get(
                AnsichCurrentBeliefRow,
                (task_id, "behavior"),
            )
            assertion = (
                None
                if current is None
                else await session.get(
                    AnsichBeliefAssertionRow,
                    current.assertion_id,
                )
            )
            alert = await session.scalar(
                select(AnsichAlertRow).where(
                    AnsichAlertRow.subject_id == task_id,
                    AnsichAlertRow.alert_type == "budget_exceeded",
                )
            )
            evidence = [] if alert is None else list((await session.execute(select(AnsichAlertEvidenceRow).where(AnsichAlertEvidenceRow.alert_id == alert.entity_id).order_by(AnsichAlertEvidenceRow.ordinal))).scalars())
        service.record(
            ObservationEnvelope.task_lifecycle(
                kind="task.completed",
                task_id=task_id,
                source_kind="deerflow_run",
                source_id="run-phase6-absolute",
                occurred_at=started_at + timedelta(seconds=3),
                source_event_id="run:phase6-absolute:task:completed",
            )
        )
        await service.flush_task(task_id)
        await service.assess_operations(now=started_at + timedelta(seconds=4))
        async with session_factory() as session:
            terminal_alert = await session.get(
                AnsichAlertRow,
                None if alert is None else alert.entity_id,
            )
    finally:
        await service.stop()
        await engine.dispose()

    assert assertion is not None
    assert assertion.value_json["value"] == "runaway"
    assert alert is not None
    assert alert.workflow_state == "open"
    assert [item.obs_id for item in evidence] == [
        configured.obs_id,
        usage_observation.obs_id,
    ]
    assert terminal_alert is not None
    assert terminal_alert.workflow_state == "resolved"
    assert terminal_alert.resolution_reason == "task_terminal"


@pytest.mark.anyio
async def test_sql_terminal_wall_time_breach_keeps_final_interval_after_last_heartbeat(
    tmp_path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-phase6-terminal-wall-time.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(
        session_factory,
        operations_assessment_interval_ms=60_000,
    )
    only_test_driven_assessments(service)
    await service.start()
    task_id = new_id()
    started_at = datetime(2026, 7, 18, 17, 30, tzinfo=UTC)
    configured = ObservationEnvelope.budget_configured(
        task_id=task_id,
        run_id="run-phase6-terminal-wall-time",
        occurred_at=started_at,
        dimension="wall_time_ms",
        aggregation_scope="local",
        warning_limit=8_000,
        hard_limit=9_500,
        enforcement=True,
        source_kind="release_default",
        requested_value=None,
        effective_value=9_500,
        source_event_id="run:phase6-terminal-wall-time:budget:configured",
    )
    heartbeat = ObservationEnvelope.task_heartbeat(
        task_id=task_id,
        run_id="run-phase6-terminal-wall-time",
        occurred_at=started_at + timedelta(seconds=9),
        producer_instance_id="phase6-test",
        worker_id="worker-phase6-test",
        ownership_epoch="epoch-1",
        elapsed_ms=9_000,
        source_event_id="run:phase6-terminal-wall-time:heartbeat:last",
    )
    terminal_wall_time = ObservationEnvelope.budget_consumed(
        task_id=task_id,
        run_id="run-phase6-terminal-wall-time",
        occurred_at=started_at + timedelta(seconds=10),
        dimension="wall_time_ms",
        delta=10_000,
        source_event_id="run:phase6-terminal-wall-time:budget:terminal",
    )

    try:
        service.record_batch(
            (
                ObservationEnvelope.task_lifecycle(
                    kind="task.created",
                    task_id=task_id,
                    source_kind="deerflow_run",
                    source_id="run-phase6-terminal-wall-time",
                    occurred_at=started_at,
                    source_event_id="run:phase6-terminal-wall-time:task:created",
                ),
                ObservationEnvelope.task_lifecycle(
                    kind="task.started",
                    task_id=task_id,
                    source_kind="deerflow_run",
                    source_id="run-phase6-terminal-wall-time",
                    occurred_at=started_at,
                    source_event_id="run:phase6-terminal-wall-time:task:started",
                ),
                configured,
                heartbeat,
                terminal_wall_time,
                ObservationEnvelope.task_lifecycle(
                    kind="task.completed",
                    task_id=task_id,
                    source_kind="deerflow_run",
                    source_id="run-phase6-terminal-wall-time",
                    occurred_at=started_at + timedelta(seconds=10),
                    source_event_id="run:phase6-terminal-wall-time:task:completed",
                ),
            )
        )
        await service.flush_task(task_id)
        await service.assess_operations(now=datetime.now(UTC) + timedelta(seconds=1))
        health = await service.get_task_budget_health(task_id)
        absolute_signal = await service.get_current_belief(
            task_id,
            "behavior_signal:absolute-limit",
        )
    finally:
        await service.stop()
        await engine.dispose()

    assert len(health) == 1
    assert health[0].value == "exceeded"
    assert health[0].usage_value == 10_000
    assert health[0].overshoot == 500
    assert absolute_signal is not None
    assert absolute_signal.value["value"] == "runaway"
    assert health[0].evidence_obs_ids == (
        configured.obs_id,
        terminal_wall_time.obs_id,
        heartbeat.obs_id,
    )


@pytest.mark.anyio
async def test_sql_wall_clock_assessment_opens_and_resolves_liveness_alerts(
    tmp_path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-phase6-liveness.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(
        session_factory,
        heartbeat_stale_after_seconds=5,
        long_dwell_seconds=5,
        operations_assessment_interval_ms=60_000,
    )
    only_test_driven_assessments(service)
    await service.start()
    task_id = new_id()
    step_id = new_id()
    started_at = datetime(2026, 7, 18, 17, 30, tzinfo=UTC)
    producer = Producer(
        name="phase6-liveness-test",
        version="1",
        instance_id="test",
    )
    try:
        service.record_batch(
            (
                ObservationEnvelope.task_lifecycle(
                    kind="task.created",
                    task_id=task_id,
                    source_kind="deerflow_run",
                    source_id="run-phase6-liveness",
                    occurred_at=started_at,
                    source_event_id="run:phase6-liveness:task:created",
                ),
                ObservationEnvelope.task_lifecycle(
                    kind="task.started",
                    task_id=task_id,
                    source_kind="deerflow_run",
                    source_id="run-phase6-liveness",
                    occurred_at=started_at,
                    source_event_id="run:phase6-liveness:task:started",
                ),
                ObservationEnvelope.task_heartbeat(
                    task_id=task_id,
                    run_id="run-phase6-liveness",
                    occurred_at=started_at,
                    elapsed_ms=0,
                    worker_id="worker-phase6",
                    ownership_epoch="epoch-1",
                    source_event_id="run:phase6-liveness:heartbeat:1",
                ),
                ObservationEnvelope(
                    kind="step.started",
                    occurred_at=started_at,
                    task_id=task_id,
                    step_id=step_id,
                    subject_type="step",
                    subject_id=step_id,
                    producer=producer,
                    source_event_id="run:phase6-liveness:step:started",
                    correlation_id=task_id,
                    payload={"step_seq": 1, "actor_kind": "lead_agent"},
                ),
            )
        )
        await service.flush_task(task_id)
        await service.assess_operations(now=started_at + timedelta(seconds=10))
        async with session_factory() as session:
            opened = list((await session.execute(select(AnsichAlertRow).where(AnsichAlertRow.subject_id == task_id).order_by(AnsichAlertRow.alert_type))).scalars())

        service.record_batch(
            (
                ObservationEnvelope.task_heartbeat(
                    task_id=task_id,
                    run_id="run-phase6-liveness",
                    occurred_at=started_at + timedelta(seconds=11),
                    elapsed_ms=11_000,
                    worker_id="worker-phase6",
                    ownership_epoch="epoch-1",
                    source_event_id="run:phase6-liveness:heartbeat:2",
                ),
                ObservationEnvelope(
                    kind="step.closed",
                    occurred_at=started_at + timedelta(seconds=11),
                    task_id=task_id,
                    step_id=step_id,
                    subject_type="step",
                    subject_id=step_id,
                    producer=producer,
                    source_event_id="run:phase6-liveness:step:closed",
                    correlation_id=task_id,
                    payload={
                        "result": "responded",
                        "effective_attempt_no": None,
                        "issued_tools": [],
                    },
                ),
            )
        )
        await service.flush_task(task_id)
        await service.assess_operations(now=started_at + timedelta(seconds=12))
        async with session_factory() as session:
            resolved = list((await session.execute(select(AnsichAlertRow).where(AnsichAlertRow.subject_id == task_id).order_by(AnsichAlertRow.alert_type))).scalars())
    finally:
        await service.stop()
        await engine.dispose()

    assert [alert.alert_type for alert in opened] == [
        "heartbeat_missing",
        "long_dwell",
    ]
    assert all(alert.workflow_state == "open" for alert in opened)
    assert [alert.alert_type for alert in resolved] == [
        "heartbeat_missing",
        "long_dwell",
    ]
    assert all(alert.workflow_state == "resolved" for alert in resolved)


@pytest.mark.anyio
async def test_periodic_alert_reconciliation_skips_historical_episode_evidence(
    tmp_path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-phase6-alert-reconciliation.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(
        session_factory,
        heartbeat_stale_after_seconds=2,
        operations_assessment_interval_ms=60_000,
    )
    only_test_driven_assessments(service)
    await service.start()
    task_id = new_id()
    started_at = datetime(2026, 7, 18, 17, 45, tzinfo=UTC)
    reconciliation_statements: list[str] = []

    def capture_reconciliation_sql(
        _connection,
        _cursor,
        statement,
        _parameters,
        _context,
        _executemany,
    ) -> None:
        reconciliation_statements.append(" ".join(statement.lower().split()))

    try:
        service.record_batch(
            (
                ObservationEnvelope.task_lifecycle(
                    kind="task.created",
                    task_id=task_id,
                    source_kind="deerflow_run",
                    source_id="run-phase6-alert-reconciliation",
                    occurred_at=started_at,
                    source_event_id="run:phase6-alert-reconciliation:task:created",
                ),
                ObservationEnvelope.task_lifecycle(
                    kind="task.started",
                    task_id=task_id,
                    source_kind="deerflow_run",
                    source_id="run-phase6-alert-reconciliation",
                    occurred_at=started_at,
                    source_event_id="run:phase6-alert-reconciliation:task:started",
                ),
            )
        )
        await service.flush_task(task_id)
        await service.assess_operations(now=started_at + timedelta(seconds=1))

        for heartbeat_index, elapsed_seconds in enumerate(
            (2, 6, 10),
            start=1,
        ):
            service.record(
                ObservationEnvelope.task_heartbeat(
                    task_id=task_id,
                    run_id="run-phase6-alert-reconciliation",
                    occurred_at=started_at + timedelta(seconds=elapsed_seconds),
                    elapsed_ms=elapsed_seconds * 1_000,
                    worker_id="worker-phase6",
                    ownership_epoch="epoch-1",
                    producer_seq=heartbeat_index,
                    source_event_id=(f"run:phase6-alert-reconciliation:heartbeat:{heartbeat_index}"),
                )
            )
            await service.flush_task(task_id)
            await service.assess_operations(
                now=started_at + timedelta(seconds=elapsed_seconds),
            )
            if heartbeat_index < 3:
                await service.assess_operations(
                    now=started_at + timedelta(seconds=elapsed_seconds + 3),
                )

        async with session_factory() as session:
            historical_episodes = list(
                (
                    await session.execute(
                        select(AnsichAlertRow)
                        .where(
                            AnsichAlertRow.subject_id == task_id,
                            AnsichAlertRow.alert_type == "heartbeat_missing",
                        )
                        .order_by(AnsichAlertRow.episode)
                    )
                ).scalars()
            )

        event.listen(
            engine.sync_engine,
            "before_cursor_execute",
            capture_reconciliation_sql,
        )
        try:
            stable_changes = await service.assess_operations(
                now=started_at + timedelta(seconds=11),
            )
        finally:
            event.remove(
                engine.sync_engine,
                "before_cursor_execute",
                capture_reconciliation_sql,
            )
    finally:
        await service.stop()
        await engine.dispose()

    assert [episode.episode for episode in historical_episodes] == [1, 2]
    assert all(episode.workflow_state == "resolved" for episode in historical_episodes)
    assert stable_changes == 0
    alert_episode_queries = [statement for statement in reconciliation_statements if "from ansich_alerts" in statement]
    alert_evidence_queries = [statement for statement in reconciliation_statements if "from ansich_alert_evidence" in statement]
    reconciliation_queries = [statement for statement in alert_episode_queries if "max(ansich_alerts.episode)" in statement]
    # Environment assessment adds exactly one bounded candidate lookup per
    # tick — the still-unresolved environment episodes, which is what keeps an
    # environment Scope in the candidate set after its Tasks end. It reads no
    # historical episode and does not scale with them, so it does not weaken
    # what this test protects.
    environment_candidate_queries = [statement for statement in alert_episode_queries if "resolved_at is null" in statement]
    assert len(reconciliation_queries) == 1
    assert len(environment_candidate_queries) == 1
    assert len(alert_episode_queries) == 2
    assert alert_evidence_queries == []


@pytest.mark.anyio
async def test_failed_assessor_jobs_degrade_health_and_can_be_retried(
    tmp_path,
    monkeypatch,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-phase6-assessor-error.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    backend = SqlAnsichBackend(
        session_factory,
        projector_max_attempts=1,
    )
    service = AnsichService(
        backend,
        flush_interval_ms=60_000,
        operations_assessment_interval_ms=60_000,
    )
    only_test_driven_assessments(service)
    await service.start()
    task_id = new_id()
    started_at = datetime(2026, 7, 18, 18, tzinfo=UTC)
    original = backend._assess_action_repetition_at

    async def fail_assessor(*args, **kwargs):
        raise RuntimeError("poison assessor input")

    try:
        service.record_batch(
            (
                ObservationEnvelope.task_lifecycle(
                    kind="task.created",
                    task_id=task_id,
                    source_kind="deerflow_run",
                    source_id="run-phase6-assessor-error",
                    occurred_at=started_at,
                    source_event_id="run:phase6-assessor-error:task:created",
                ),
                ObservationEnvelope.task_lifecycle(
                    kind="task.started",
                    task_id=task_id,
                    source_kind="deerflow_run",
                    source_id="run-phase6-assessor-error",
                    occurred_at=started_at,
                    source_event_id="run:phase6-assessor-error:task:started",
                ),
            )
        )
        await service.flush_task(task_id)
        await _record_action_step(
            service,
            task_id=task_id,
            step_seq=1,
            args={"query": "poison"},
            observed_at=started_at + timedelta(seconds=1),
        )
        monkeypatch.setattr(
            backend,
            "_assess_action_repetition_at",
            fail_assessor,
        )
        await service.assess_operations(now=started_at + timedelta(seconds=2))
        failed_health = service.get_health()
        async with session_factory() as session:
            failed_jobs = list(
                (
                    await session.execute(
                        select(AnsichAssessorJobRow).where(
                            AnsichAssessorJobRow.assessor_name == "action-repetition",
                            AnsichAssessorJobRow.status == "failed",
                        )
                    )
                ).scalars()
            )
            error_count = len(list((await session.execute(select(AnsichAssessorErrorRow))).scalars()))

        monkeypatch.setattr(
            backend,
            "_assess_action_repetition_at",
            original,
        )
        retried = await service.retry_failed_projections(task_id=task_id)
        recovered_health = service.get_health()
        async with session_factory() as session:
            recovered_statuses = list((await session.execute(select(AnsichAssessorJobRow.status).where(AnsichAssessorJobRow.assessor_name == "action-repetition"))).scalars())
    finally:
        await service.stop()
        await engine.dispose()

    assert failed_jobs
    assert error_count == len(failed_jobs)
    assert failed_health.status == "degraded"
    assert failed_health.failed_jobs == len(failed_jobs)
    assert retried == len(failed_jobs)
    assert recovered_statuses
    assert all(status == "completed" for status in recovered_statuses)
    assert recovered_health.failed_jobs == 0


@pytest.mark.anyio
async def test_operator_action_idempotency_is_atomic_under_concurrency(
    tmp_path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-action-idempotency.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(
        session_factory,
        operations_assessment_interval_ms=60_000,
    )
    await service.start()
    task_id = new_id()
    now = datetime.now(UTC)
    service.record_batch(
        (
            ObservationEnvelope.task_lifecycle(
                kind="task.created",
                task_id=task_id,
                source_kind="deerflow_run",
                source_id="run-action-idempotency",
                occurred_at=now,
                source_event_id="run:action-idempotency:created",
            ),
            ObservationEnvelope.task_lifecycle(
                kind="task.started",
                task_id=task_id,
                source_kind="deerflow_run",
                source_id="run-action-idempotency",
                occurred_at=now,
                source_event_id="run:action-idempotency:started",
            ),
        )
    )
    await service.flush_task(task_id)
    try:
        results = await asyncio.gather(
            *(
                service.begin_operator_action(
                    task_id=task_id,
                    action_type="interrupt",
                    idempotency_key="same-network-request",
                    operator_id=f"admin-{index}",
                    occurred_at=now,
                )
                for index in range(2)
            )
        )
        async with session_factory() as session:
            actions = list((await session.execute(select(AnsichOperatorActionRow))).scalars())
            requested = list((await session.execute(select(AnsichObservationRow).where(AnsichObservationRow.kind == "operator.action_requested"))).scalars())
    finally:
        await service.stop()
        await engine.dispose()

    assert sorted(started for _, started in results) == [False, True]
    assert results[0][0].action_id == results[1][0].action_id
    assert len(actions) == 1
    assert len(requested) == 1


@pytest.mark.anyio
async def test_stale_requested_operator_action_takeover_elects_one_winner(
    tmp_path,
) -> None:
    """Two concurrent retries against one orphaned row must elect one takeover.

    The takeover reuses the same conflict-election transaction as ordinary
    idempotency: the loser observes the winner's re-armed row and reports an
    in-progress conflict instead of executing the runtime action twice.
    """

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-action-takeover.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(
        session_factory,
        operations_assessment_interval_ms=60_000,
    )
    await service.start()
    task_id = new_id()
    now = datetime.now(UTC)
    service.record_batch(
        (
            ObservationEnvelope.task_lifecycle(
                kind="task.created",
                task_id=task_id,
                source_kind="deerflow_run",
                source_id="run-action-takeover",
                occurred_at=now,
                source_event_id="run:action-takeover:created",
            ),
            ObservationEnvelope.task_lifecycle(
                kind="task.started",
                task_id=task_id,
                source_kind="deerflow_run",
                source_id="run-action-takeover",
                occurred_at=now,
                source_event_id="run:action-takeover:started",
            ),
        )
    )
    await service.flush_task(task_id)
    try:
        orphan, _ = await service.begin_operator_action(
            task_id=task_id,
            action_type="interrupt",
            idempotency_key="crashed-before-finish",
            operator_id="operator-that-crashed",
            occurred_at=now - _STALE_REQUESTED_TAKEOVER_AFTER - timedelta(seconds=1),
        )
        results = await asyncio.gather(
            *(
                service.begin_operator_action(
                    task_id=task_id,
                    action_type="interrupt",
                    idempotency_key="crashed-before-finish",
                    operator_id=f"admin-{index}",
                    occurred_at=now,
                )
                for index in range(2)
            )
        )
        async with session_factory() as session:
            actions = list((await session.execute(select(AnsichOperatorActionRow))).scalars())
            requested = list((await session.execute(select(AnsichObservationRow).where(AnsichObservationRow.kind == "operator.action_requested"))).scalars())
            failed = list((await session.execute(select(AnsichObservationRow).where(AnsichObservationRow.kind == "operator.action_failed"))).scalars())
    finally:
        await service.stop()
        await engine.dispose()

    assert sorted(started for _, started in results) == [False, True]
    assert results[0][0].action_id == results[1][0].action_id
    assert results[0][0].action_id != orphan.action_id
    # One ledger row per Idempotency-Key, now armed for the winning attempt.
    assert len(actions) == 1
    assert actions[0].status == "requested"
    assert actions[0].action_id == results[0][0].action_id
    # Exactly one takeover: the orphan is terminalized once, one new attempt opened.
    assert len(failed) == 1
    assert failed[0].payload_json["action_id"] == orphan.action_id
    assert failed[0].payload_json["result"]["outcome"] == "stale_requested_takeover"
    assert sorted(row.payload_json["action_id"] for row in requested) == sorted((orphan.action_id, actions[0].action_id))


def test_phase6_alert_models_compile_with_postgresql_semantics() -> None:
    dialect = postgresql.dialect()
    statements = {
        model.__tablename__: str(CreateTable(model.__table__).compile(dialect=dialect))
        for model in (
            AnsichAssessorJobRow,
            AnsichAssessorErrorRow,
            AnsichAlertRow,
            AnsichAlertEvidenceRow,
            AnsichAlertWorkflowEventRow,
            AnsichAlertReadModelRow,
            AnsichOperatorActionRow,
        )
    }

    assert "TIMESTAMP WITH TIME ZONE" in statements["ansich_assessor_jobs"]
    assert "UNIQUE (subject_id, assessor_name, assessor_version, evidence_watermark)" in statements["ansich_assessor_jobs"]
    assert "BOOLEAN NOT NULL" in statements["ansich_alerts"]
    assert "JSON NOT NULL" in statements["ansich_alert_read_model"]
    assert "UNIQUE (task_id, action_type, idempotency_key)" in statements["ansich_operator_actions"]
    assertion_columns = AnsichBeliefAssertionRow.__table__.c
    assert str(assertion_columns.config_hash.type) == "VARCHAR(64)"
    assert str(assertion_columns.authority_class.type) == "VARCHAR(32)"


def test_assessment_channel_batch_queries_compile_portably() -> None:
    for dialect in (sqlite.dialect(), postgresql.dialect()):
        action_sql = " ".join(
            str(
                _action_repetition_rows_statement(
                    task_id="task-portable",
                    evidence_watermark=42,
                ).compile(dialect=dialect)
            )
            .upper()
            .split()
        )
        alert_sql = " ".join(
            str(
                _reconciliation_alert_rows_statement(
                    task_id="task-portable",
                ).compile(dialect=dialect)
            )
            .upper()
            .split()
        )

        assert "FROM ANSICH_STEPS" in action_sql
        assert "LEFT OUTER JOIN ANSICH_TOOL_CALLS" in action_sql
        assert "LEFT OUTER JOIN ANSICH_OBSERVATIONS AS ISSUED_OBSERVATION" in action_sql
        assert "MAX(ANSICH_ALERTS.EPISODE)" in alert_sql
        assert "GROUP BY ANSICH_ALERTS.ALERT_KEY" in alert_sql
        assert "ANSICH_ALERTS.WORKFLOW_STATE !=" in alert_sql


def test_phase6_alert_migration_upgrades_sqlite_and_backfills_assertions(
    tmp_path,
) -> None:
    backend_root = Path(__file__).resolve().parents[2]
    config = AlembicConfig(str(backend_root / "packages" / "harness" / "deerflow" / "persistence" / "migrations" / "alembic.ini"))
    database_path = tmp_path / "ansich-phase6-migration.db"
    config.set_main_option(
        "sqlalchemy.url",
        f"sqlite+aiosqlite:///{database_path}",
    )
    config.config_file_name = None

    alembic_command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{database_path}")
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        assertion_columns = {column["name"] for column in inspector.get_columns("ansich_belief_assertions")}
        with engine.connect() as connection:
            revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
    finally:
        engine.dispose()

    assert {
        "ansich_assessor_jobs",
        "ansich_assessor_errors",
        "ansich_alerts",
        "ansich_alert_evidence",
        "ansich_alert_workflow_events",
        "ansich_alert_read_model",
        "ansich_operator_actions",
    } <= tables
    assert {
        "assessor_name",
        "assessor_version",
        "config_hash",
        "authority_class",
        "confidence",
    } <= assertion_columns
    assert revision == "0026_ansich_environment"
    assert len(revision) <= 32
