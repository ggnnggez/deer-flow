import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from ansich import ObservationEnvelope, Producer, new_id
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from deerflow.ansich import create_sql_ansich_service
from deerflow.ansich.persistence.models import (
    AnsichBeliefAssertionRow,
    AnsichObservationRow,
    AnsichUsageContributionRow,
)
from deerflow.persistence.base import Base

WALL_TIME_WATERMARK_REVISION = "0024_ansich_wall_time_watermarks"
PREVIOUS_REVISION = "0023_ansich_evaluations"


def _alembic_config(database_path: Path) -> AlembicConfig:
    backend_root = Path(__file__).resolve().parents[2]
    config = AlembicConfig(str(backend_root / "packages" / "harness" / "deerflow" / "persistence" / "migrations" / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database_path}")
    # The Alembic env only applies process-wide logging.fileConfig when this
    # remains set; the integration test must not disable loggers used later.
    config.config_file_name = None
    return config


def _heartbeat(
    task_id: str,
    run_id: str,
    base: datetime,
    *,
    tick: int,
    elapsed_ms: int,
) -> ObservationEnvelope:
    return ObservationEnvelope.task_heartbeat(
        task_id=task_id,
        run_id=run_id,
        occurred_at=base + timedelta(milliseconds=elapsed_ms),
        elapsed_ms=elapsed_ms,
        worker_id=f"{run_id}-worker",
        ownership_epoch=f"{run_id}-epoch",
        source_event_id=f"{run_id}:heartbeat:{tick}",
        producer_seq=tick,
    )


def _task_created(
    task_id: str,
    source_id: str,
    observed_at: datetime,
    *,
    source_kind: str = "deerflow_run",
    attributes: dict[str, object] | None = None,
) -> ObservationEnvelope:
    return ObservationEnvelope.task_lifecycle(
        kind="task.created",
        task_id=task_id,
        source_kind=source_kind,
        source_id=source_id,
        occurred_at=observed_at,
        source_event_id=f"{source_kind}:{source_id}:task:created",
        attributes=attributes,
    )


def _step_started(task_id: str, step_id: str, observed_at: datetime) -> ObservationEnvelope:
    return ObservationEnvelope(
        kind="step.started",
        occurred_at=observed_at,
        task_id=task_id,
        step_id=step_id,
        subject_type="step",
        subject_id=step_id,
        producer=Producer(name="heartbeat-test", version="1", instance_id="test"),
        source_event_id=f"step:{step_id}:started",
        correlation_id=task_id,
        payload={"step_seq": 1, "actor_kind": "lead_agent"},
    )


def _tool_issued(
    task_id: str,
    step_id: str,
    tool_call_id: str,
    observed_at: datetime,
) -> ObservationEnvelope:
    return ObservationEnvelope(
        kind="tool.issued",
        occurred_at=observed_at,
        task_id=task_id,
        step_id=step_id,
        subject_type="tool_call",
        subject_id=tool_call_id,
        producer=Producer(name="heartbeat-test", version="1", instance_id="test"),
        source_event_id=f"tool:{tool_call_id}:issued",
        correlation_id=task_id,
        payload={
            "call_seq": 1,
            "provider_call_id": f"provider-{tool_call_id}",
            "tool_name": "task",
            "args_hash": "a" * 64,
            "args_preview": {},
            "tool_schema_block_id": None,
        },
    )


async def _wall_time_rows_by_pair(session_factory) -> dict[tuple[str, str], list[AnsichUsageContributionRow]]:
    async with session_factory() as session:
        rows = list(
            (
                await session.execute(
                    select(AnsichUsageContributionRow).where(
                        AnsichUsageContributionRow.dimension == "wall_time_ms",
                    )
                )
            ).scalars()
        )
    grouped: dict[tuple[str, str], list[AnsichUsageContributionRow]] = {}
    for row in rows:
        grouped.setdefault((row.aggregate_task_id, row.source_task_id), []).append(row)
    return grouped


@pytest.mark.anyio
async def test_sql_heartbeat_projection_returns_latest_evidence_after_rebuild(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-heartbeat.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(session_factory)
    await service.start()
    task_id = new_id()
    observed_at = datetime(2026, 7, 18, 10, 10, tzinfo=UTC)
    first = ObservationEnvelope.task_heartbeat(
        task_id=task_id,
        run_id="run-sql-heartbeat",
        occurred_at=observed_at + timedelta(seconds=10),
        elapsed_ms=10_000,
        worker_id="worker-a",
        ownership_epoch="worker-a",
        source_event_id="run:run-sql-heartbeat:task:heartbeat:1",
    )
    second = ObservationEnvelope.task_heartbeat(
        task_id=task_id,
        run_id="run-sql-heartbeat",
        occurred_at=observed_at + timedelta(seconds=20),
        elapsed_ms=20_000,
        worker_id="worker-a",
        ownership_epoch="worker-a",
        source_event_id="run:run-sql-heartbeat:task:heartbeat:2",
        producer_seq=2,
    )

    try:
        service.record(
            ObservationEnvelope.task_lifecycle(
                kind="task.created",
                task_id=task_id,
                source_kind="deerflow_run",
                source_id="run-sql-heartbeat",
                occurred_at=observed_at,
                source_event_id="run:run-sql-heartbeat:task:created",
            )
        )
        service.record(first)
        service.record(second)
        await service.flush_task(task_id)
        heartbeat = await service.get_task_heartbeat(task_id)
        usage = await service.get_task_usage(task_id)
        await service.rebuild_projections()
        rebuilt = await service.get_task_heartbeat(task_id)
        rebuilt_usage = await service.get_task_usage(task_id)
    finally:
        await service.stop()
        await engine.dispose()

    assert heartbeat == rebuilt
    assert usage == rebuilt_usage
    assert heartbeat is not None
    assert heartbeat.heartbeat_obs_id == second.obs_id
    assert heartbeat.occurred_at == second.occurred_at
    assert heartbeat.producer_instance_id == second.producer.instance_id
    assert heartbeat.ownership_epoch == "worker-a"
    assert heartbeat.elapsed_ms == 20_000
    assert [(item.dimension, item.value) for item in usage.local] == [("wall_time_ms", 20_000)]


@pytest.mark.anyio
async def test_heartbeat_projector_alone_does_not_maintain_wall_time_summary(tmp_path, monkeypatch):
    """M1: the heartbeat projector must not own a second wall_time summary writer.

    Closing the usage projector for ``task.heartbeat`` leaves ``_project_heartbeat``
    as the only projector that consumes the observation. It must still record the
    heartbeat evidence row, but it must no longer create or update the
    ``(task_id, wall_time_ms, local)`` summary: ``_refresh_usage_summary`` is the
    single writer of that projection row.
    """

    from deerflow.ansich.persistence import sql as sql_module

    monkeypatch.setattr(
        sql_module,
        "_PROJECTOR_KINDS",
        {
            **sql_module._PROJECTOR_KINDS,
            "task-usage": sql_module._PROJECTOR_KINDS["task-usage"] - {"task.heartbeat"},
        },
    )

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-heartbeat-single-writer.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(session_factory)
    await service.start()
    task_id = new_id()
    observed_at = datetime(2026, 7, 18, 10, 10, tzinfo=UTC)
    second = ObservationEnvelope.task_heartbeat(
        task_id=task_id,
        run_id="run-sql-heartbeat-single-writer",
        occurred_at=observed_at + timedelta(seconds=20),
        elapsed_ms=20_000,
        worker_id="worker-a",
        ownership_epoch="worker-a",
        source_event_id="run:run-sql-heartbeat-single-writer:task:heartbeat:2",
        producer_seq=2,
    )

    try:
        service.record_batch(
            (
                ObservationEnvelope.task_lifecycle(
                    kind="task.created",
                    task_id=task_id,
                    source_kind="deerflow_run",
                    source_id="run-sql-heartbeat-single-writer",
                    occurred_at=observed_at,
                    source_event_id="run:run-sql-heartbeat-single-writer:task:created",
                ),
                ObservationEnvelope.task_heartbeat(
                    task_id=task_id,
                    run_id="run-sql-heartbeat-single-writer",
                    occurred_at=observed_at + timedelta(seconds=10),
                    elapsed_ms=10_000,
                    worker_id="worker-a",
                    ownership_epoch="worker-a",
                    source_event_id="run:run-sql-heartbeat-single-writer:task:heartbeat:1",
                ),
                second,
            )
        )
        await service.flush_task(task_id)
        heartbeat = await service.get_task_heartbeat(task_id)
        usage = await service.get_task_usage(task_id)
        async with session_factory() as session:
            contributions = list((await session.execute(select(AnsichUsageContributionRow))).scalars())
    finally:
        await service.stop()
        await engine.dispose()

    # The heartbeat evidence row keeps its full behavior.
    assert heartbeat is not None
    assert heartbeat.heartbeat_obs_id == second.obs_id
    assert heartbeat.elapsed_ms == 20_000
    # The usage projector really was closed for heartbeats.
    assert contributions == []
    # No summary row is maintained by the heartbeat projector.
    assert usage.local == ()
    assert usage.inclusive == ()


@pytest.mark.anyio
async def test_wall_time_summary_is_written_only_from_usage_contributions(tmp_path):
    """M1: the wall_time summary row is exactly the contribution-model result.

    A terminal ``budget.consumed`` wall_time contribution that occurred after the
    final heartbeat makes the two former writers observably different: the
    contribution model (max-per-source-then-sum) carries the latest contribution's
    ``as_of``, while the deleted heartbeat branch rewound it to the heartbeat's own
    ``occurred_at`` whenever its elapsed value matched the summary.
    """

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-heartbeat-contribution-model.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(session_factory)
    await service.start()
    task_id = new_id()
    observed_at = datetime(2026, 7, 18, 10, 10, tzinfo=UTC)

    try:
        service.record_batch(
            (
                ObservationEnvelope.task_lifecycle(
                    kind="task.created",
                    task_id=task_id,
                    source_kind="deerflow_run",
                    source_id="run-sql-heartbeat-contribution",
                    occurred_at=observed_at,
                    source_event_id="run:run-sql-heartbeat-contribution:task:created",
                ),
                ObservationEnvelope.task_heartbeat(
                    task_id=task_id,
                    run_id="run-sql-heartbeat-contribution",
                    occurred_at=observed_at + timedelta(seconds=10),
                    elapsed_ms=10_000,
                    worker_id="worker-a",
                    ownership_epoch="worker-a",
                    source_event_id="run:run-sql-heartbeat-contribution:task:heartbeat:1",
                ),
                ObservationEnvelope.budget_consumed(
                    task_id=task_id,
                    run_id="run-sql-heartbeat-contribution",
                    occurred_at=observed_at + timedelta(seconds=30),
                    dimension="wall_time_ms",
                    delta=5_000,
                    source_event_id="run:run-sql-heartbeat-contribution:budget:wall_time_ms",
                ),
                ObservationEnvelope.task_heartbeat(
                    task_id=task_id,
                    run_id="run-sql-heartbeat-contribution",
                    occurred_at=observed_at + timedelta(seconds=20),
                    elapsed_ms=20_000,
                    worker_id="worker-a",
                    ownership_epoch="worker-a",
                    source_event_id="run:run-sql-heartbeat-contribution:task:heartbeat:2",
                    producer_seq=2,
                ),
            )
        )
        await service.flush_task(task_id)
        usage = await service.get_task_usage(task_id)
        async with session_factory() as session:
            contributions = list(
                (
                    await session.execute(
                        select(AnsichUsageContributionRow, AnsichObservationRow.ingest_seq)
                        .join(
                            AnsichObservationRow,
                            AnsichObservationRow.obs_id == AnsichUsageContributionRow.source_obs_id,
                        )
                        .where(
                            AnsichUsageContributionRow.aggregate_task_id == task_id,
                            AnsichUsageContributionRow.source_task_id == task_id,
                            AnsichUsageContributionRow.dimension == "wall_time_ms",
                        )
                    )
                ).all()
            )
    finally:
        await service.stop()
        await engine.dispose()

    # Two rows, not three: P8-M2 collapses the heartbeat channel into one
    # high-water row per (aggregate, source) while the terminal
    # ``budget.consumed`` contribution keeps its own row.
    assert len(contributions) == 2
    # max-per-source-then-sum over a single source Task.
    expected_value = max(contribution.delta for contribution, _ in contributions)
    expected_as_of = max(contribution.as_of.replace(tzinfo=UTC) for contribution, _ in contributions)
    expected_watermark = max(ingest_seq for _, ingest_seq in contributions)

    local_wall_time = next(item for item in usage.local if item.dimension == "wall_time_ms")
    assert local_wall_time.value == expected_value == 20_000
    assert local_wall_time.as_of == expected_as_of == observed_at + timedelta(seconds=30)
    assert local_wall_time.complete_through_ingest_seq == expected_watermark


@pytest.mark.anyio
async def test_heartbeat_assessor_persists_stale_and_recovery_without_changing_control(
    tmp_path,
):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-heartbeat-assessment.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(
        session_factory,
        heartbeat_stale_after_seconds=30,
        operations_assessment_interval_ms=60_000,
    )
    await service.start()
    task_id = new_id()
    started_at = datetime(2026, 7, 18, 11, tzinfo=UTC)

    try:
        service.record_batch(
            (
                ObservationEnvelope.task_lifecycle(
                    kind="task.created",
                    task_id=task_id,
                    source_kind="deerflow_run",
                    source_id="run-heartbeat-assessment",
                    occurred_at=started_at,
                    source_event_id="run:run-heartbeat-assessment:task:created",
                ),
                ObservationEnvelope.task_lifecycle(
                    kind="task.started",
                    task_id=task_id,
                    source_kind="deerflow_run",
                    source_id="run-heartbeat-assessment",
                    occurred_at=started_at,
                    source_event_id="run:run-heartbeat-assessment:task:started",
                ),
                ObservationEnvelope.task_heartbeat(
                    task_id=task_id,
                    run_id="run-heartbeat-assessment",
                    occurred_at=started_at + timedelta(seconds=10),
                    elapsed_ms=10_000,
                    worker_id="worker-a",
                    ownership_epoch="worker-a",
                    source_event_id="run:run-heartbeat-assessment:task:heartbeat:1",
                ),
            )
        )
        await service.flush_task(task_id)

        fresh_changes = await service.assess_operations(now=started_at + timedelta(seconds=39))
        repeated_fresh_changes = await service.assess_operations(now=started_at + timedelta(seconds=40))
        active_while_fresh = await service.list_active_tasks()
        async with session_factory() as session:
            fresh_assertions = list(
                (
                    await session.execute(
                        select(AnsichBeliefAssertionRow).where(
                            AnsichBeliefAssertionRow.subject_id == task_id,
                            AnsichBeliefAssertionRow.field_name == "heartbeat",
                        )
                    )
                ).scalars()
            )
        stale_changes = await service.assess_operations(now=started_at + timedelta(seconds=41))
        stale = await service.get_task_heartbeat_belief(task_id)
        async with session_factory() as session:
            stale_assertions = list(
                (
                    await session.execute(
                        select(AnsichBeliefAssertionRow).where(
                            AnsichBeliefAssertionRow.subject_id == task_id,
                            AnsichBeliefAssertionRow.field_name == "heartbeat",
                        )
                    )
                ).scalars()
            )

        recovery = ObservationEnvelope.task_heartbeat(
            task_id=task_id,
            run_id="run-heartbeat-assessment",
            occurred_at=started_at + timedelta(seconds=45),
            elapsed_ms=45_000,
            worker_id="worker-a",
            ownership_epoch="worker-a",
            source_event_id="run:run-heartbeat-assessment:task:heartbeat:2",
            producer_seq=2,
        )
        service.record(recovery)
        await service.flush_task(task_id)
        recovery_changes = await service.assess_operations(now=started_at + timedelta(seconds=46))
        recovered = await service.get_task_heartbeat_belief(task_id)
        task = await service.get_task(task_id)
    finally:
        await service.stop()
        await engine.dispose()

    assert fresh_changes == 1
    assert repeated_fresh_changes == 0
    assert len(fresh_assertions) == 1
    assert fresh_assertions[0].value_json == {"value": "fresh"}
    assert active_while_fresh[0].heartbeat.age_ms == 30_000
    assert stale_changes == 1
    assert len(stale_assertions) == 2
    assert [assertion.value_json for assertion in stale_assertions] == [
        {"value": "fresh"},
        {"value": "stale"},
    ]
    assert stale is not None
    assert stale.value == "stale"
    assert stale.age_ms == 31_000
    assert recovery_changes == 1
    assert recovered is not None
    assert recovered.value == "fresh"
    assert recovered.evidence_obs_ids == (recovery.obs_id,)
    assert recovered.selected_by.version == stale.selected_by.version
    assert task is not None
    assert task.control.value == "running"


@pytest.mark.anyio
async def test_background_assessor_materializes_running_task_heartbeat_belief(
    tmp_path,
):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-heartbeat-background.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(
        session_factory,
        projector_poll_interval_ms=10,
        operations_assessment_interval_ms=10,
    )
    await service.start()
    task_id = new_id()
    now = datetime.now(UTC)

    try:
        service.record_batch(
            (
                ObservationEnvelope.task_lifecycle(
                    kind="task.created",
                    task_id=task_id,
                    source_kind="deerflow_run",
                    source_id="run-heartbeat-background",
                    occurred_at=now,
                    source_event_id="run:run-heartbeat-background:task:created",
                ),
                ObservationEnvelope.task_lifecycle(
                    kind="task.started",
                    task_id=task_id,
                    source_kind="deerflow_run",
                    source_id="run-heartbeat-background",
                    occurred_at=now,
                    source_event_id="run:run-heartbeat-background:task:started",
                ),
            )
        )
        await service.flush_task(task_id)
        async with asyncio.timeout(1):
            while (await service.get_task_heartbeat_belief(task_id)) is None:
                await asyncio.sleep(0.01)
        belief = await service.get_task_heartbeat_belief(task_id)
    finally:
        await service.stop()
        await engine.dispose()

    assert belief is not None
    assert belief.value == "unknown"


@pytest.mark.anyio
async def test_heartbeat_ticks_keep_one_wall_time_high_water_row_per_source(tmp_path):
    """P8-M2/HR1: wall_time is a max-type channel, not a per-tick append log.

    N heartbeat ticks on a parent and its child must leave exactly ONE
    ``wall_time_ms`` contribution row per ``(aggregate_task_id, source_task_id)``
    — including the ancestry fan-out row — while the local/inclusive summaries
    keep the Phase-8 semantics (maximum elapsed evidence per source, then summed
    across sources).
    """

    ticks = 12
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-wall-time-high-water.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(
        session_factory,
        operations_assessment_interval_ms=60_000,
    )
    await service.start()
    root_id, child_id = new_id(), new_id()
    root_step, root_tool = new_id(), new_id()
    observed_at = datetime(2026, 8, 19, 9, 0, tzinfo=UTC)

    try:
        service.record_batch(
            (
                _task_created(root_id, "root-high-water", observed_at),
                ObservationEnvelope.task_lifecycle(
                    kind="task.started",
                    task_id=root_id,
                    source_kind="deerflow_run",
                    source_id="root-high-water",
                    occurred_at=observed_at,
                    source_event_id="root-high-water:task:started",
                ),
                _step_started(root_id, root_step, observed_at),
                _tool_issued(root_id, root_step, root_tool, observed_at),
            )
        )
        await service.flush_task(root_id)
        service.record(
            _task_created(
                child_id,
                "child-high-water",
                observed_at,
                source_kind="deerflow_subagent",
                attributes={
                    "parent_task_id": root_id,
                    "spawning_step_id": root_step,
                    "spawning_tool_call_id": root_tool,
                },
            )
        )
        await service.flush_task(child_id)
        for tick in range(1, ticks + 1):
            service.record(
                _heartbeat(
                    root_id,
                    "root-high-water",
                    observed_at,
                    tick=tick,
                    elapsed_ms=tick * 1_000,
                )
            )
            service.record(
                _heartbeat(
                    child_id,
                    "child-high-water",
                    observed_at,
                    tick=tick,
                    elapsed_ms=tick * 500,
                )
            )
            await service.flush_task(root_id)
            await service.flush_task(child_id)

        grouped = await _wall_time_rows_by_pair(session_factory)
        root_usage = await service.get_task_usage(root_id)
        child_usage = await service.get_task_usage(child_id)
        breakdown = await service.get_task_usage_breakdown(root_id, scope="inclusive")
    finally:
        await service.stop()
        await engine.dispose()

    assert {pair: len(rows) for pair, rows in grouped.items()} == {
        (root_id, root_id): 1,
        (root_id, child_id): 1,
        (child_id, child_id): 1,
    }
    assert grouped[(root_id, root_id)][0].delta == ticks * 1_000
    assert grouped[(root_id, child_id)][0].delta == ticks * 500
    assert grouped[(child_id, child_id)][0].delta == ticks * 500
    assert {item.dimension: item.value for item in root_usage.local}["wall_time_ms"] == ticks * 1_000
    assert {item.dimension: item.value for item in root_usage.inclusive}["wall_time_ms"] == ticks * 1_500
    assert {item.dimension: item.value for item in child_usage.local}["wall_time_ms"] == ticks * 500
    assert {item.dimension: item.value for item in child_usage.inclusive}["wall_time_ms"] == ticks * 500
    wall_time_by_source = {source.source_task_id: {item.dimension: item.value for item in source.values} for source in breakdown.sources}
    assert wall_time_by_source[root_id]["wall_time_ms"] == ticks * 1_000
    assert wall_time_by_source[child_id]["wall_time_ms"] == ticks * 500


@pytest.mark.anyio
async def test_wall_time_refresh_work_per_tick_does_not_grow_with_tick_count(tmp_path):
    """P8-M2: the summary refresh must not rescan every historical tick.

    ``_refresh_usage_summary`` recomputes from the contribution rows of one
    ``(aggregate_task_id, dimension)``, so its per-tick cost is
    (statements issued) x (rows in that scan set). The SQL listener pins the
    first factor constant; the scan-set size pins the second at O(1), which
    makes the cumulative refresh work linear in the tick count instead of
    quadratic.
    """

    ticks = 10
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-wall-time-refresh-cost.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(
        session_factory,
        flush_interval_ms=60_000,
        projector_poll_interval_ms=60_000,
        operations_assessment_interval_ms=60_000,
    )
    await service.start()
    task_id = new_id()
    observed_at = datetime(2026, 8, 19, 9, 30, tzinfo=UTC)
    contribution_statements = {"count": 0}

    def capture_contribution_sql(
        _connection,
        _cursor,
        statement,
        _parameters,
        _context,
        _executemany,
    ) -> None:
        if "ansich_usage_contributions" in " ".join(statement.lower().split()):
            contribution_statements["count"] += 1

    scan_set_sizes: list[int] = []
    statements_per_tick: list[int] = []
    try:
        service.record_batch(
            (
                _task_created(task_id, "refresh-cost", observed_at),
                ObservationEnvelope.task_lifecycle(
                    kind="task.started",
                    task_id=task_id,
                    source_kind="deerflow_run",
                    source_id="refresh-cost",
                    occurred_at=observed_at,
                    source_event_id="refresh-cost:task:started",
                ),
            )
        )
        await service.flush_task(task_id)
        event.listen(
            engine.sync_engine,
            "before_cursor_execute",
            capture_contribution_sql,
        )
        try:
            for tick in range(1, ticks + 1):
                contribution_statements["count"] = 0
                service.record(
                    _heartbeat(
                        task_id,
                        "refresh-cost",
                        observed_at,
                        tick=tick,
                        elapsed_ms=tick * 1_000,
                    )
                )
                await service.flush_task(task_id)
                statements_per_tick.append(contribution_statements["count"])
                async with session_factory() as session:
                    scan_set_sizes.append(
                        await session.scalar(
                            select(func.count())
                            .select_from(AnsichUsageContributionRow)
                            .where(
                                AnsichUsageContributionRow.aggregate_task_id == task_id,
                                AnsichUsageContributionRow.dimension == "wall_time_ms",
                            )
                        )
                    )
        finally:
            event.remove(
                engine.sync_engine,
                "before_cursor_execute",
                capture_contribution_sql,
            )
    finally:
        await service.stop()
        await engine.dispose()

    # The refresh's scan set stays O(1) no matter how many ticks arrived, so
    # the cumulative refresh work is linear rather than quadratic.
    assert scan_set_sizes == [1] * ticks
    assert sum(scan_set_sizes) == ticks
    # And no per-row statement fan-out crept in to replace the wide scan.
    assert max(statements_per_tick[2:]) == min(statements_per_tick[2:])


@pytest.mark.anyio
async def test_out_of_order_heartbeats_converge_on_the_wall_time_high_water_mark(tmp_path):
    """P8-M2: max is commutative and idempotent, so replay reproduces it.

    Ingesting the highest tick first must leave the same single high-water row
    (value, provenance and ``as_of``) as any other order, and
    ``rebuild_projections()`` must reproduce it byte-for-byte.
    """

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-wall-time-out-of-order.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(
        session_factory,
        operations_assessment_interval_ms=60_000,
    )
    await service.start()
    task_id = new_id()
    observed_at = datetime(2026, 8, 19, 10, 0, tzinfo=UTC)
    highest = _heartbeat(task_id, "out-of-order", observed_at, tick=3, elapsed_ms=30_000)

    try:
        service.record_batch(
            (
                _task_created(task_id, "out-of-order", observed_at),
                highest,
                _heartbeat(task_id, "out-of-order", observed_at, tick=1, elapsed_ms=10_000),
                _heartbeat(task_id, "out-of-order", observed_at, tick=2, elapsed_ms=20_000),
            )
        )
        await service.flush_task(task_id)
        grouped = await _wall_time_rows_by_pair(session_factory)
        usage = await service.get_task_usage(task_id)
        await service.rebuild_projections()
        rebuilt_grouped = await _wall_time_rows_by_pair(session_factory)
        rebuilt_usage = await service.get_task_usage(task_id)
    finally:
        await service.stop()
        await engine.dispose()

    assert [len(rows) for rows in grouped.values()] == [1]
    row = grouped[(task_id, task_id)][0]
    assert row.delta == 30_000
    assert row.source_obs_id == highest.obs_id
    assert row.as_of.replace(tzinfo=UTC) == highest.occurred_at
    local_wall_time = next(item for item in usage.local if item.dimension == "wall_time_ms")
    assert local_wall_time.value == 30_000
    assert local_wall_time.as_of == highest.occurred_at
    # Replay identity: the same evidence in ingest order rebuilds the same row.
    assert {pair: [(item.source_obs_id, item.delta, item.as_of) for item in rows] for pair, rows in rebuilt_grouped.items()} == {pair: [(item.source_obs_id, item.delta, item.as_of) for item in rows] for pair, rows in grouped.items()}
    assert rebuilt_usage == usage


@pytest.mark.anyio
async def test_terminal_wall_time_keeps_its_own_row_beside_the_heartbeat_high_water_mark(
    tmp_path,
):
    """P8-M2: collapsing the heartbeat channel must not touch terminal wall_time.

    The terminal ``budget.consumed`` wall_time arrives once per Task (from the
    Task monotonic clock), so it stays an ordinary contribution row. The
    absolute-limit assessor must keep taking the maximum of the terminal
    contribution and the latest heartbeat elapsed, and keep retaining BOTH
    evidence paths.
    """

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-wall-time-terminal.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(
        session_factory,
        operations_assessment_interval_ms=60_000,
    )
    await service.start()
    task_id = new_id()
    observed_at = datetime(2026, 8, 19, 10, 30, tzinfo=UTC)
    configured = ObservationEnvelope.budget_configured(
        task_id=task_id,
        run_id="terminal-wall-time",
        occurred_at=observed_at,
        dimension="wall_time_ms",
        aggregation_scope="local",
        warning_limit=20_000,
        hard_limit=25_000,
        enforcement=True,
        source_kind="release_default",
        requested_value=None,
        effective_value=25_000,
        source_event_id="terminal-wall-time:budget:configured",
    )
    last_heartbeat = _heartbeat(task_id, "terminal-wall-time", observed_at, tick=2, elapsed_ms=20_000)
    terminal = ObservationEnvelope.budget_consumed(
        task_id=task_id,
        run_id="terminal-wall-time",
        occurred_at=observed_at + timedelta(seconds=30),
        dimension="wall_time_ms",
        delta=30_000,
        source_event_id="terminal-wall-time:budget:terminal",
    )

    try:
        service.record_batch(
            (
                _task_created(task_id, "terminal-wall-time", observed_at),
                ObservationEnvelope.task_lifecycle(
                    kind="task.started",
                    task_id=task_id,
                    source_kind="deerflow_run",
                    source_id="terminal-wall-time",
                    occurred_at=observed_at,
                    source_event_id="terminal-wall-time:task:started",
                ),
                configured,
                _heartbeat(task_id, "terminal-wall-time", observed_at, tick=1, elapsed_ms=10_000),
                last_heartbeat,
                terminal,
                ObservationEnvelope.task_lifecycle(
                    kind="task.completed",
                    task_id=task_id,
                    source_kind="deerflow_run",
                    source_id="terminal-wall-time",
                    occurred_at=observed_at + timedelta(seconds=30),
                    source_event_id="terminal-wall-time:task:completed",
                ),
            )
        )
        await service.flush_task(task_id)
        await service.assess_operations(now=observed_at + timedelta(seconds=31))
        grouped = await _wall_time_rows_by_pair(session_factory)
        usage = await service.get_task_usage(task_id)
        health = await service.get_task_budget_health(task_id)
    finally:
        await service.stop()
        await engine.dispose()

    rows = grouped[(task_id, task_id)]
    assert {(row.source_obs_id, row.delta) for row in rows} == {
        (last_heartbeat.obs_id, 20_000),
        (terminal.obs_id, 30_000),
    }
    local_wall_time = next(item for item in usage.local if item.dimension == "wall_time_ms")
    assert local_wall_time.value == 30_000
    assert local_wall_time.as_of == terminal.occurred_at
    assert len(health) == 1
    assert health[0].value == "exceeded"
    assert health[0].usage_value == 30_000
    assert health[0].evidence_obs_ids == (
        configured.obs_id,
        terminal.obs_id,
        last_heartbeat.obs_id,
    )


def _seed_legacy_wall_time_rows(
    database_path: Path,
    *,
    task_id: str,
    parent_task_id: str,
    ticks: int,
) -> dict[str, str]:
    """Write the pre-0024 shape: one wall_time contribution per heartbeat tick."""

    observed_at = datetime(2026, 8, 19, 11, tzinfo=UTC)
    obs_ids: dict[str, str] = {}
    engine = create_engine(f"sqlite:///{database_path}")
    try:
        with engine.begin() as connection:
            for tick in range(1, ticks + 1):
                obs_id = new_id()
                obs_ids[f"heartbeat-{tick}"] = obs_id
                connection.execute(
                    text(
                        """
                        INSERT INTO ansich_observations (
                            obs_id, schema_version, kind, occurred_at, recorded_at,
                            task_id, subject_type, subject_id, fidelity_class,
                            producer_name, producer_version, producer_instance_id,
                            producer_seq, source_event_id, correlation_id, payload_json
                        ) VALUES (
                            :obs_id, 1, 'task.heartbeat', :occurred_at, :occurred_at,
                            :task_id, 'task', :task_id, 'hard',
                            'legacy-probe', '1', 'test',
                            :tick, :source_event_id, 'legacy-run', '{}'
                        )
                        """
                    ),
                    {
                        "obs_id": obs_id,
                        "occurred_at": observed_at + timedelta(seconds=tick),
                        "task_id": task_id,
                        "tick": tick,
                        "source_event_id": f"legacy:heartbeat:{tick}",
                    },
                )
                for aggregate_task_id in (task_id, parent_task_id):
                    connection.execute(
                        text(
                            """
                            INSERT INTO ansich_usage_contributions (
                                aggregate_task_id, source_task_id, dimension,
                                source_obs_id, delta, as_of
                            ) VALUES (
                                :aggregate_task_id, :task_id, 'wall_time_ms',
                                :obs_id, :delta, :as_of
                            )
                            """
                        ),
                        {
                            "aggregate_task_id": aggregate_task_id,
                            "task_id": task_id,
                            "obs_id": obs_id,
                            "delta": tick * 1_000,
                            "as_of": observed_at + timedelta(seconds=tick),
                        },
                    )
            terminal_obs_id = new_id()
            obs_ids["terminal"] = terminal_obs_id
            connection.execute(
                text(
                    """
                    INSERT INTO ansich_observations (
                        obs_id, schema_version, kind, occurred_at, recorded_at,
                        task_id, subject_type, subject_id, fidelity_class,
                        producer_name, producer_version, producer_instance_id,
                        producer_seq, source_event_id, correlation_id, payload_json
                    ) VALUES (
                        :obs_id, 1, 'budget.consumed', :occurred_at, :occurred_at,
                        :task_id, 'task', :task_id, 'hard',
                        'legacy-probe', '1', 'test',
                        999, 'legacy:budget:terminal', 'legacy-run', '{}'
                    )
                    """
                ),
                {
                    "obs_id": terminal_obs_id,
                    "occurred_at": observed_at + timedelta(seconds=ticks + 1),
                    "task_id": task_id,
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO ansich_usage_contributions (
                        aggregate_task_id, source_task_id, dimension,
                        source_obs_id, delta, as_of
                    ) VALUES (
                        :task_id, :task_id, 'wall_time_ms', :obs_id, :delta, :as_of
                    )
                    """
                ),
                {
                    "task_id": task_id,
                    "obs_id": terminal_obs_id,
                    "delta": 500,
                    "as_of": observed_at + timedelta(seconds=ticks + 1),
                },
            )
            # A sum-type dimension sharing one of the heartbeat observations
            # must survive untouched.
            connection.execute(
                text(
                    """
                    INSERT INTO ansich_usage_contributions (
                        aggregate_task_id, source_task_id, dimension,
                        source_obs_id, delta, as_of
                    ) VALUES (
                        :task_id, :task_id, 'steps', :obs_id, 1, :as_of
                    )
                    """
                ),
                {
                    "task_id": task_id,
                    "obs_id": obs_ids["heartbeat-1"],
                    "as_of": observed_at + timedelta(seconds=1),
                },
            )
    finally:
        engine.dispose()
    return obs_ids


def _wall_time_contribution_rows(database_path: Path) -> list[tuple[str, str, str, str, int]]:
    engine = create_engine(f"sqlite:///{database_path}")
    try:
        with engine.connect() as connection:
            return [
                tuple(row)
                for row in connection.execute(
                    text(
                        """
                        SELECT aggregate_task_id, source_task_id, dimension, source_obs_id, delta
                        FROM ansich_usage_contributions
                        ORDER BY aggregate_task_id, source_task_id, dimension, delta
                        """
                    )
                )
            ]
    finally:
        engine.dispose()


def _alembic_revision(database_path: Path) -> str:
    engine = create_engine(f"sqlite:///{database_path}")
    try:
        with engine.connect() as connection:
            return connection.scalar(text("SELECT version_num FROM alembic_version"))
    finally:
        engine.dispose()


def test_wall_time_watermark_migration_upgrades_sqlite(tmp_path) -> None:
    database_path = tmp_path / "ansich-wall-time-watermark-migration.db"
    config = _alembic_config(database_path)

    alembic_command.upgrade(config, "head")

    revision = _alembic_revision(database_path)
    assert revision == WALL_TIME_WATERMARK_REVISION
    assert len(revision) <= 32


def test_wall_time_watermark_migration_collapses_historical_per_tick_rows(tmp_path) -> None:
    """P8-M2: an existing database keeps only the per-source high-water rows.

    Terminal ``budget.consumed`` wall_time rows and every sum-type dimension
    stay untouched, and re-running the collapse is a no-op.
    """

    ticks = 6
    database_path = tmp_path / "ansich-wall-time-watermark-collapse.db"
    config = _alembic_config(database_path)
    alembic_command.upgrade(config, PREVIOUS_REVISION)
    task_id, parent_task_id = new_id(), new_id()
    obs_ids = _seed_legacy_wall_time_rows(
        database_path,
        task_id=task_id,
        parent_task_id=parent_task_id,
        ticks=ticks,
    )
    before = _wall_time_contribution_rows(database_path)

    alembic_command.upgrade(config, "head")
    after = _wall_time_contribution_rows(database_path)
    # Idempotent: stamping back and re-running the same collapse changes nothing.
    alembic_command.stamp(config, PREVIOUS_REVISION)
    alembic_command.upgrade(config, "head")
    twice = _wall_time_contribution_rows(database_path)

    assert len([row for row in before if row[2] == "wall_time_ms"]) == ticks * 2 + 1
    assert sorted(after) == sorted(
        [
            (parent_task_id, task_id, "wall_time_ms", obs_ids[f"heartbeat-{ticks}"], ticks * 1_000),
            (task_id, task_id, "steps", obs_ids["heartbeat-1"], 1),
            (task_id, task_id, "wall_time_ms", obs_ids["terminal"], 500),
            (task_id, task_id, "wall_time_ms", obs_ids[f"heartbeat-{ticks}"], ticks * 1_000),
        ]
    )
    assert twice == after
    assert _alembic_revision(database_path) == WALL_TIME_WATERMARK_REVISION


def test_wall_time_watermark_migration_downgrade_returns_to_previous_revision(tmp_path) -> None:
    database_path = tmp_path / "ansich-wall-time-watermark-downgrade.db"
    config = _alembic_config(database_path)
    alembic_command.upgrade(config, "head")

    alembic_command.downgrade(config, PREVIOUS_REVISION)

    assert _alembic_revision(database_path) == PREVIOUS_REVISION


@pytest.mark.anyio
async def test_late_spawn_backfill_carries_the_wall_time_high_water_mark(tmp_path):
    """P8-M2: a late ancestry edge must not reintroduce per-tick wall_time rows.

    The child accumulates heartbeat ticks before its typed spawn evidence
    arrives, so ``_backfill_spawn_usage`` fans its already-durable usage out to
    the new ancestor. It must carry the child's mark as a *mark* — one row per
    ``(ancestor, child)`` — and later ticks must keep replacing that same row.
    """

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-wall-time-late-spawn.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(
        session_factory,
        operations_assessment_interval_ms=60_000,
    )
    await service.start()
    root_id, child_id = new_id(), new_id()
    root_step, root_tool = new_id(), new_id()
    observed_at = datetime(2026, 8, 19, 12, tzinfo=UTC)

    try:
        service.record_batch(
            (
                _task_created(root_id, "root-late-spawn", observed_at),
                _step_started(root_id, root_step, observed_at),
                _tool_issued(root_id, root_step, root_tool, observed_at),
                _task_created(child_id, "child-before-relation", observed_at),
            )
        )
        await service.flush_task(root_id)
        await service.flush_task(child_id)
        for tick in (1, 2, 3):
            service.record(
                _heartbeat(
                    child_id,
                    "child-late-spawn",
                    observed_at,
                    tick=tick,
                    elapsed_ms=tick * 1_000,
                )
            )
        await service.flush_task(child_id)
        # The typed spawn evidence lands only now.
        service.record(
            _task_created(
                child_id,
                "child-executor",
                observed_at,
                source_kind="deerflow_subagent",
                attributes={
                    "parent_task_id": root_id,
                    "spawning_step_id": root_step,
                    "spawning_tool_call_id": root_tool,
                },
            )
        )
        await service.flush_task(child_id)
        backfilled = await _wall_time_rows_by_pair(session_factory)
        backfilled_usage = await service.get_task_usage(root_id)
        # Ticks that arrive after the edge keep replacing the same ancestor row.
        for tick in (4, 5):
            service.record(
                _heartbeat(
                    child_id,
                    "child-late-spawn",
                    observed_at,
                    tick=tick,
                    elapsed_ms=tick * 1_000,
                )
            )
        await service.flush_task(child_id)
        grouped = await _wall_time_rows_by_pair(session_factory)
        usage = await service.get_task_usage(root_id)
        await service.rebuild_projections()
        rebuilt_usage = await service.get_task_usage(root_id)
    finally:
        await service.stop()
        await engine.dispose()

    assert {pair: len(rows) for pair, rows in backfilled.items()} == {
        (root_id, child_id): 1,
        (child_id, child_id): 1,
    }
    assert {item.dimension: item.value for item in backfilled_usage.inclusive}["wall_time_ms"] == 3_000
    assert {pair: len(rows) for pair, rows in grouped.items()} == {
        (root_id, child_id): 1,
        (child_id, child_id): 1,
    }
    assert grouped[(root_id, child_id)][0].delta == 5_000
    assert {item.dimension: item.value for item in usage.inclusive}["wall_time_ms"] == 5_000
    assert rebuilt_usage == usage
