"""End-to-end environment Alert episodes.

Covers the periodic `_assess_environment` pass: which Scopes it judges, the
Assertions it appends (transition-only), the Alert episodes it opens, resolves
and re-opens, and the `possibly_affected_task_ids` it writes onto the Alert read
model.

Every test drives `assess_operations(now=...)` itself, so every test installs
`only_test_driven_assessments(service)` before `start()` — otherwise the
projector loop's own wall-clock assessment is a second, invisible writer racing
the assertions below (see `tests/support/ansich_settle.py`).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from ansich import AnsichService, ObservationEnvelope, new_id
from ansich.safety import scope_entity_id, scope_reference_hash
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from support.ansich_settle import only_test_driven_assessments

from deerflow.ansich import create_sql_ansich_service
from deerflow.ansich.persistence.models import (
    AnsichAlertReadModelRow,
    AnsichAlertRow,
    AnsichBeliefAssertionRow,
    AnsichCurrentBeliefRow,
)
from deerflow.persistence.base import Base

_STARTED_AT = datetime(2026, 8, 19, 10, tzinfo=UTC)
_SCOPE_KIND = "sandbox"
_SCOPE_REF = "local:thread-env-alerts"
_SCOPE_ID = scope_entity_id(_SCOPE_KIND, scope_reference_hash(_SCOPE_KIND, _SCOPE_REF))
_FD_FIELD = "environment_pressure:fd_open"
_LEAK_FIELD = "environment_leak:fd_open"


@asynccontextmanager
async def _environment_service(
    tmp_path: Path,
    database_name: str,
    **overrides: object,
) -> AsyncIterator[tuple[AnsichService, async_sessionmaker[AsyncSession]]]:
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / database_name}",
        connect_args={"timeout": 30},
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    settings: dict[str, object] = {
        "flush_interval_ms": 60_000,
        "terminal_flush_timeout_ms": 10_000,
        "projector_poll_interval_ms": 5,
        "operations_assessment_interval_ms": 60_000,
        "environment_sample_interval_seconds": 10,
    }
    settings.update(overrides)
    service = create_sql_ansich_service(session_factory, **settings)
    only_test_driven_assessments(service)
    await service.start()
    try:
        yield service, session_factory
    finally:
        await service.stop()
        await engine.dispose()


def _task_created(task_id: str, run_id: str) -> ObservationEnvelope:
    return ObservationEnvelope.task_lifecycle(
        kind="task.created",
        task_id=task_id,
        source_kind="deerflow_run",
        source_id=run_id,
        occurred_at=_STARTED_AT,
        source_event_id=f"run:{run_id}:task:created",
    )


def _task_started(task_id: str, run_id: str) -> ObservationEnvelope:
    return ObservationEnvelope.task_lifecycle(
        kind="task.started",
        task_id=task_id,
        source_kind="deerflow_run",
        source_id=run_id,
        occurred_at=_STARTED_AT,
        source_event_id=f"run:{run_id}:task:started",
    )


def _task_completed(task_id: str, run_id: str, occurred_at: datetime) -> ObservationEnvelope:
    return ObservationEnvelope.task_lifecycle(
        kind="task.completed",
        task_id=task_id,
        source_kind="deerflow_run",
        source_id=run_id,
        occurred_at=occurred_at,
        source_event_id=f"run:{run_id}:task:completed",
    )


def _scope_snapshotted(task_id: str, run_id: str) -> ObservationEnvelope:
    return ObservationEnvelope.scope_snapshotted(
        task_id=task_id,
        run_id=run_id,
        occurred_at=_STARTED_AT,
        scope_kind=_SCOPE_KIND,
        external_ref=_SCOPE_REF,
        relation_role="sandbox_boundary",
        source_event_id=f"run:{run_id}:scope:{_SCOPE_ID}",
    )


def _environment_sampled(
    task_id: str,
    run_id: str,
    *,
    tick: int,
    occurred_at: datetime,
    metrics: dict[str, dict[str, int | None]] | None = None,
    coverage: str = "continuous",
    environment_scope: str = "container",
    sample_count: int = 1,
) -> ObservationEnvelope:
    payload: dict[str, object] = {
        "environment_scope": environment_scope,
        "coverage": coverage,
        "provider": "local",
        "metrics": metrics or {},
        "window": {
            "started_at": _STARTED_AT.isoformat(),
            "ended_at": occurred_at.isoformat(),
            "sample_count": sample_count,
        },
    }
    return ObservationEnvelope.environment_sampled(
        task_id=task_id,
        run_id=run_id,
        occurred_at=occurred_at,
        scope_id=_SCOPE_ID,
        payload=payload,
        source_event_id=f"run:{run_id}:env:{_SCOPE_ID}:{tick}",
        producer_seq=tick,
        producer_name="deerflow-environment-probe",
    )


def _fd(value: int, limit: int | None = 1024) -> dict[str, dict[str, int | None]]:
    return {"fd_open": {"value": value, "limit": limit}}


async def _bootstrap(service: AnsichService, task_id: str, run_id: str) -> None:
    service.record_batch(
        (
            _task_created(task_id, run_id),
            _task_started(task_id, run_id),
            _scope_snapshotted(task_id, run_id),
        )
    )
    await service.flush_task(task_id)


async def _record_sample(
    service: AnsichService,
    task_id: str,
    run_id: str,
    *,
    tick: int,
    occurred_at: datetime,
    metrics: dict[str, dict[str, int | None]] | None = None,
    coverage: str = "continuous",
    environment_scope: str = "container",
    sample_count: int = 1,
) -> None:
    service.record(
        _environment_sampled(
            task_id,
            run_id,
            tick=tick,
            occurred_at=occurred_at,
            metrics=metrics,
            coverage=coverage,
            environment_scope=environment_scope,
            sample_count=sample_count,
        )
    )
    await service.flush_task(task_id)


async def _alerts(session_factory: async_sessionmaker[AsyncSession]) -> list[AnsichAlertRow]:
    async with session_factory() as session:
        return list(
            (
                await session.execute(
                    select(AnsichAlertRow)
                    .where(AnsichAlertRow.subject_id == _SCOPE_ID)
                    .order_by(
                        AnsichAlertRow.alert_type,
                        AnsichAlertRow.episode,
                    )
                )
            ).scalars()
        )


async def _assertion_count(
    session_factory: async_sessionmaker[AsyncSession],
    field_name: str,
) -> int:
    async with session_factory() as session:
        return int(
            await session.scalar(
                select(func.count())
                .select_from(AnsichBeliefAssertionRow)
                .where(
                    AnsichBeliefAssertionRow.subject_id == _SCOPE_ID,
                    AnsichBeliefAssertionRow.field_name == field_name,
                )
            )
            or 0
        )


async def _current_value(
    session_factory: async_sessionmaker[AsyncSession],
    field_name: str,
) -> str | None:
    async with session_factory() as session:
        current = await session.get(AnsichCurrentBeliefRow, (_SCOPE_ID, field_name))
        if current is None:
            return None
        assertion = await session.get(AnsichBeliefAssertionRow, current.assertion_id)
        return None if assertion is None else str(assertion.value_json["value"])


@pytest.mark.anyio
async def test_environment_pressure_episode_opens_resolves_and_recurs(tmp_path) -> None:
    task_id = new_id()
    run_id = "env-pressure"
    async with _environment_service(tmp_path, "ansich-env-pressure.db") as (
        service,
        session_factory,
    ):
        await _bootstrap(service, task_id, run_id)

        await _record_sample(
            service,
            task_id,
            run_id,
            tick=1,
            occurred_at=_STARTED_AT + timedelta(seconds=10),
            metrics=_fd(990),
        )
        await service.assess_operations(now=_STARTED_AT + timedelta(seconds=11))
        opened = await _alerts(session_factory)
        assert [row.alert_type for row in opened] == ["environment_pressure"]
        assert opened[0].severity == "critical"
        assert opened[0].workflow_state == "open"
        assert opened[0].episode == 1
        assert opened[0].stable_condition_key == "env:fd_open"
        assert opened[0].rule_name == "environment-pressure"
        assert await _current_value(session_factory, _FD_FIELD) == "critical"

        # The Alert subject is the Scope, so the Tasks a human should look at
        # ride on the read model instead of inside the Assertion value.
        async with session_factory() as session:
            read_model = await session.get(AnsichAlertReadModelRow, opened[0].entity_id)
        assert read_model is not None
        assert read_model.possibly_affected_task_ids == [task_id]

        await _record_sample(
            service,
            task_id,
            run_id,
            tick=2,
            occurred_at=_STARTED_AT + timedelta(seconds=20),
            metrics=_fd(100),
        )
        await service.assess_operations(now=_STARTED_AT + timedelta(seconds=21))
        resolved = await _alerts(session_factory)
        assert len(resolved) == 1
        assert resolved[0].workflow_state == "resolved"
        assert resolved[0].resolved_at is not None
        assert resolved[0].resolution_reason == "condition_cleared"
        assert await _current_value(session_factory, _FD_FIELD) == "ok"

        await _record_sample(
            service,
            task_id,
            run_id,
            tick=3,
            occurred_at=_STARTED_AT + timedelta(seconds=30),
            metrics=_fd(1000),
        )
        await service.assess_operations(now=_STARTED_AT + timedelta(seconds=31))
        recurred = await _alerts(session_factory)

    assert [row.episode for row in recurred] == [1, 2]
    assert recurred[1].workflow_state == "open"
    assert recurred[1].alert_key == recurred[0].alert_key
    assert recurred[1].severity == "critical"


@pytest.mark.anyio
async def test_sustained_fd_growth_opens_a_leak_suspected_episode(tmp_path) -> None:
    task_id = new_id()
    run_id = "env-leak"
    async with _environment_service(tmp_path, "ansich-env-leak.db") as (
        service,
        session_factory,
    ):
        await _bootstrap(service, task_id, run_id)
        # A baseline sample plus six strictly growing ones: growth count 6,
        # span from the first growing sample 75s, net growth 60 fds. Values stay
        # far below the fd pressure ratio so the leak rule is judged alone.
        for tick, (offset, value) in enumerate(
            (
                (0, 100),
                (15, 110),
                (30, 120),
                (45, 130),
                (60, 145),
                (75, 155),
                (90, 160),
            ),
            start=1,
        ):
            await _record_sample(
                service,
                task_id,
                run_id,
                tick=tick,
                occurred_at=_STARTED_AT + timedelta(seconds=offset),
                metrics=_fd(value),
            )
        await service.assess_operations(now=_STARTED_AT + timedelta(seconds=91))
        alerts = await _alerts(session_factory)
        pressure_value = await _current_value(session_factory, _FD_FIELD)
        leak_value = await _current_value(session_factory, _LEAK_FIELD)

    assert [row.alert_type for row in alerts] == ["environment_leak_suspected"]
    assert alerts[0].severity == "warning"
    assert alerts[0].workflow_state == "open"
    assert alerts[0].stable_condition_key == "env-leak:fd_open"
    assert leak_value == "suspected"
    # Pressure and leak are independent rules on the same metric.
    assert pressure_value == "ok"


@pytest.mark.anyio
async def test_sampling_gap_turns_pressure_unknown_and_resolves_the_episode(tmp_path) -> None:
    task_id = new_id()
    run_id = "env-gap"
    async with _environment_service(tmp_path, "ansich-env-gap.db") as (
        service,
        session_factory,
    ):
        await _bootstrap(service, task_id, run_id)
        await _record_sample(
            service,
            task_id,
            run_id,
            tick=1,
            occurred_at=_STARTED_AT + timedelta(seconds=10),
            metrics=_fd(990),
        )
        await service.assess_operations(now=_STARTED_AT + timedelta(seconds=11))
        assert [row.workflow_state for row in await _alerts(session_factory)] == ["open"]

        # No further samples: past three sampling intervals the reading no
        # longer describes the present, so the state is unknown — never "ok".
        await service.assess_operations(now=_STARTED_AT + timedelta(seconds=41))
        alerts = await _alerts(session_factory)
        value = await _current_value(session_factory, _FD_FIELD)

    assert value == "unknown"
    assert [row.workflow_state for row in alerts] == ["resolved"]


@pytest.mark.anyio
async def test_unchanged_state_appends_no_further_assertions(tmp_path) -> None:
    task_id = new_id()
    run_id = "env-transition"
    async with _environment_service(tmp_path, "ansich-env-transition.db") as (
        service,
        session_factory,
    ):
        await _bootstrap(service, task_id, run_id)
        await _record_sample(
            service,
            task_id,
            run_id,
            tick=1,
            occurred_at=_STARTED_AT + timedelta(seconds=10),
            metrics=_fd(990),
        )
        await service.assess_operations(now=_STARTED_AT + timedelta(seconds=11))
        after_first = (
            await _assertion_count(session_factory, _FD_FIELD),
            await _assertion_count(session_factory, _LEAK_FIELD),
        )

        for offset in (12, 13, 14):
            await service.assess_operations(now=_STARTED_AT + timedelta(seconds=offset))
        after_repeats = (
            await _assertion_count(session_factory, _FD_FIELD),
            await _assertion_count(session_factory, _LEAK_FIELD),
        )

        # A fresh sample carrying the same category advances the evidence
        # Observation and `as_of` but not the state, so it must not append
        # either: the Assertion value is the only thing dedupe looks at.
        await _record_sample(
            service,
            task_id,
            run_id,
            tick=2,
            occurred_at=_STARTED_AT + timedelta(seconds=20),
            metrics=_fd(1000),
        )
        await service.assess_operations(now=_STARTED_AT + timedelta(seconds=21))
        after_new_sample = (
            await _assertion_count(session_factory, _FD_FIELD),
            await _assertion_count(session_factory, _LEAK_FIELD),
        )
        value = await _current_value(session_factory, _FD_FIELD)

    assert after_first == (1, 1)
    assert after_repeats == (1, 1)
    assert after_new_sample == (1, 1)
    assert value == "critical"


@pytest.mark.anyio
async def test_terminal_task_without_open_episode_leaves_the_candidate_set(tmp_path) -> None:
    task_id = new_id()
    run_id = "env-terminal"
    async with _environment_service(tmp_path, "ansich-env-terminal.db") as (
        service,
        session_factory,
    ):
        await _bootstrap(service, task_id, run_id)
        await _record_sample(
            service,
            task_id,
            run_id,
            tick=1,
            occurred_at=_STARTED_AT + timedelta(seconds=10),
            metrics=_fd(990),
        )
        await service.assess_operations(now=_STARTED_AT + timedelta(seconds=11))
        await _record_sample(
            service,
            task_id,
            run_id,
            tick=2,
            occurred_at=_STARTED_AT + timedelta(seconds=20),
            metrics=_fd(100),
        )
        await service.assess_operations(now=_STARTED_AT + timedelta(seconds=21))
        assert [row.workflow_state for row in await _alerts(session_factory)] == ["resolved"]

        service.record(_task_completed(task_id, run_id, _STARTED_AT + timedelta(seconds=25)))
        await service.flush_task(task_id)
        before = (
            await _assertion_count(session_factory, _FD_FIELD),
            await _assertion_count(session_factory, _LEAK_FIELD),
        )

        # Nothing running is attached to the Scope any more and no episode is
        # open, so a fresh breaching sample must not re-enter assessment.
        await _record_sample(
            service,
            task_id,
            run_id,
            tick=3,
            occurred_at=_STARTED_AT + timedelta(seconds=30),
            metrics=_fd(1000),
        )
        await service.assess_operations(now=_STARTED_AT + timedelta(seconds=31))
        after = (
            await _assertion_count(session_factory, _FD_FIELD),
            await _assertion_count(session_factory, _LEAK_FIELD),
        )
        alerts = await _alerts(session_factory)
        value = await _current_value(session_factory, _FD_FIELD)

    assert before == after
    assert [row.workflow_state for row in alerts] == ["resolved"]
    assert value == "ok"


@pytest.mark.anyio
async def test_uninstrumented_declaration_asserts_unknown_without_state_rows(tmp_path) -> None:
    task_id = new_id()
    run_id = "env-uninstrumented"
    async with _environment_service(tmp_path, "ansich-env-uninstrumented.db") as (
        service,
        session_factory,
    ):
        await _bootstrap(service, task_id, run_id)
        await _record_sample(
            service,
            task_id,
            run_id,
            tick=1,
            occurred_at=_STARTED_AT + timedelta(seconds=10),
            metrics=None,
            coverage="uninstrumented",
            sample_count=0,
        )
        await service.assess_operations(now=_STARTED_AT + timedelta(seconds=11))
        value = await _current_value(session_factory, _FD_FIELD)
        leak_value = await _current_value(session_factory, _LEAK_FIELD)
        alerts = await _alerts(session_factory)

    assert value == "unknown"
    # No state row exists, so the leak rule never runs for this Scope.
    assert leak_value is None
    assert alerts == []


@pytest.mark.anyio
async def test_per_command_coverage_never_drives_periodic_assessment(tmp_path) -> None:
    task_id = new_id()
    run_id = "env-per-command"
    async with _environment_service(tmp_path, "ansich-env-per-command.db") as (
        service,
        session_factory,
    ):
        await _bootstrap(service, task_id, run_id)
        service.record(
            ObservationEnvelope.environment_sampled(
                task_id=task_id,
                run_id=run_id,
                occurred_at=_STARTED_AT + timedelta(seconds=10),
                scope_id=_SCOPE_ID,
                payload={
                    "environment_scope": "process_group",
                    "coverage": "per_command",
                    "provider": "local",
                    "tool_call_id": new_id(),
                    "metrics": {"fd_open": {"value": 1020, "limit": 1024}},
                    "window": {
                        "started_at": _STARTED_AT.isoformat(),
                        "ended_at": (_STARTED_AT + timedelta(seconds=10)).isoformat(),
                        "sample_count": 1,
                    },
                },
                source_event_id=f"run:{run_id}:env:{_SCOPE_ID}:1",
                producer_seq=1,
                producer_name="deerflow-environment-probe",
            )
        )
        await service.flush_task(task_id)
        await service.assess_operations(now=_STARTED_AT + timedelta(seconds=11))
        value = await _current_value(session_factory, _FD_FIELD)
        alerts = await _alerts(session_factory)

    assert value is None
    assert alerts == []
