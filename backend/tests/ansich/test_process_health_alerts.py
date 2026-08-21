"""The two process-subject Alert producers (RB3).

``projection_failure`` and ``observability_degradation`` are the first Alerts
whose subject is not a Task. They are produced by the periodic
``assess_operations`` pass against the host ``Scope`` the collector's bootstrap
mints, and everything here drives them through a real service: real failed
projection jobs (an Observation whose dependency never lands, with a zero
dependency timeout), and real ``observability.lost`` rows written through the
normal record path.

The pure half of both rules — the verdict, the bounded identities, the window's
own validation — is tested by function call at the bottom of this file, with no
service and no database, the same split ``test_environment_assessor.py`` uses.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from _router_auth_helpers import make_authed_test_app
from ansich import AnsichService, ObservationEnvelope, Producer, new_id
from ansich.contracts import ANSICH_BOOTSTRAP_TASK_ID
from ansich.process_health import (
    assess_observability_degradation,
    assess_projection_failure,
    observability_loss_condition_key,
    observability_loss_field_name,
    projection_failure_condition_key,
    projection_failure_field_name,
)
from ansich.safety import host_scope_id
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from support.ansich_settle import only_test_driven_assessments

from app.gateway.auth.models import User
from app.gateway.routers import ansich as ansich_router
from deerflow.ansich import create_sql_ansich_service
from deerflow.ansich.persistence.models import (
    AnsichAlertEvidenceRow,
    AnsichAlertRow,
    AnsichAssessorErrorRow,
    AnsichAssessorJobRow,
    AnsichBeliefAssertionRow,
    AnsichCurrentBeliefRow,
    AnsichObservationRow,
    AnsichPayloadRow,
    AnsichProjectionJobRow,
    AnsichScopeRow,
)
from deerflow.ansich.persistence.sql import (
    _OBSERVABILITY_LOSS_SCAN_LIMIT,
    _OBSERVABILITY_LOSS_WINDOW_SECONDS,
    _UNREADABLE_LOSS_PRODUCER,
    SqlAnsichBackend,
)
from deerflow.persistence.base import Base

_HOSTNAME = "ansich-process-health-test-host"
_SCOPE_ID = host_scope_id(_HOSTNAME)
_T0 = datetime(2026, 8, 21, 10, 0, tzinfo=UTC)
#: A projection job's claim predicate is `available_at <= datetime.now(UTC)`, so
#: a test that parks a row out of the projector's reach must do it against the
#: *real* clock, not against `_T0`. `_T0 + 1 day` reads as unreachable today and
#: becomes reachable tomorrow — a fixture that fails on a date rather than on a
#: change. This constant is absolute and far enough out that no wall clock this
#: suite runs under reaches it.
_UNREACHABLE_AVAILABLE_AT = datetime(2099, 1, 1, tzinfo=UTC)


def _admin_user() -> User:
    return User(
        id=uuid4(),
        email="ansich-process-health-admin@example.com",
        password_hash="x",
        system_role="admin",
    )


async def _await_failed_projectors(session_factory, expected: set[str], *, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while True:
        failed = await _failed_projector_names(session_factory)
        if expected <= failed:
            return
        assert time.monotonic() < deadline, f"timed out waiting for {expected} to fail, saw {failed}"
        await asyncio.sleep(0.01)


async def _await_no_failed_projectors(session_factory, *, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while True:
        failed = await _failed_projector_names(session_factory)
        if not failed:
            return
        assert time.monotonic() < deadline, f"timed out waiting for {failed} to clear"
        await asyncio.sleep(0.01)


async def _started_service(tmp_path, filename: str):
    """A started SQL service whose host Scope is a property of this test."""

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / filename}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(
        session_factory,
        hostname=_HOSTNAME,
        # A dependency wait that never resolves becomes a durable failed job
        # immediately, which is how every failing projector below is made real.
        projector_dependency_timeout_seconds=0,
        operations_assessment_interval_ms=60_000,
    )
    only_test_driven_assessments(service)
    await service.start()
    return engine, session_factory, service


def _orphan_budget_consumed(task_id: str, *, occurred_at: datetime, suffix: str) -> ObservationEnvelope:
    """A ``budget.consumed`` for a Task that does not exist.

    ``budget.consumed`` is claimed by exactly one projector (``task-usage`` --
    see ``_PROJECTOR_KINDS``), so an orphaned one produces exactly one failing
    group. That single-projector property is what lets a two-group test recover
    one group without touching the other.
    """

    return ObservationEnvelope.budget_consumed(
        task_id=task_id,
        run_id=f"run-{suffix}",
        occurred_at=occurred_at,
        dimension="output_tokens",
        delta=17,
        source_event_id=f"process-health:{suffix}:budget:consumed",
    )


def _orphan_step_closed(task_id: str, *, occurred_at: datetime, suffix: str) -> ObservationEnvelope:
    """A ``step.closed`` for a Step that does not exist (``task-step`` only)."""

    step_id = new_id()
    return ObservationEnvelope(
        kind="step.closed",
        occurred_at=occurred_at,
        task_id=task_id,
        step_id=step_id,
        subject_type="step",
        subject_id=step_id,
        producer=Producer(name="process-health-test", version="1", instance_id="test"),
        producer_seq=1,
        source_event_id=f"process-health:{suffix}:step:closed",
        correlation_id=task_id,
        payload={
            "result": "acting",
            "effective_attempt_no": None,
            "issued_tools": [],
        },
    )


def _lost_range(
    *,
    occurred_at: datetime,
    first_sequence: int,
    last_sequence: int,
    producer_name: str,
    producer_instance_id: str,
    suffix: str,
) -> ObservationEnvelope:
    return ObservationEnvelope.observability_lost(
        host_scope_id=_SCOPE_ID,
        occurred_at=occurred_at,
        first_sequence=first_sequence,
        last_sequence=last_sequence,
        lost_producer_name=producer_name,
        lost_producer_instance_id=producer_instance_id,
        source_event_id=f"process-health:lost:{suffix}",
    )


async def _alerts(session_factory, alert_type: str) -> list[AnsichAlertRow]:
    async with session_factory() as session:
        return list(
            (
                await session.execute(
                    select(AnsichAlertRow)
                    .where(
                        AnsichAlertRow.subject_id == _SCOPE_ID,
                        AnsichAlertRow.alert_type == alert_type,
                    )
                    .order_by(AnsichAlertRow.stable_condition_key, AnsichAlertRow.episode)
                )
            ).scalars()
        )


async def _failed_projector_names(session_factory) -> set[str]:
    async with session_factory() as session:
        return set(
            (
                await session.execute(
                    select(AnsichProjectionJobRow.projector_name).where(
                        AnsichProjectionJobRow.status == "failed",
                    )
                )
            ).scalars()
        )


@pytest.mark.anyio
async def test_projection_failure_opens_confirms_resolves_and_recurs(tmp_path):
    """One projector group through the whole episode arc.

    Open on the first failing job, confirm without a second row while it stays
    failing, resolve once an operator retry clears it, and open ``episode=2``
    when the same projector breaks again — recurrence numbering rides the
    existing episode machinery untouched.
    """

    engine, session_factory, service = await _started_service(tmp_path, "process-health-lifecycle.db")
    task_id = new_id()
    try:
        service.record(_orphan_budget_consumed(task_id, occurred_at=_T0, suffix="lifecycle-a"))
        await service.flush_task(task_id)
        # The dependency timeout is zero, so the job fails on its first claim;
        # wait for the projector loop to actually get there.
        await _await_failed_projectors(session_factory, {"task-usage"})

        opened_changes = await service.assess_operations(now=_T0 + timedelta(seconds=1))
        opened = await _alerts(session_factory, "projection_failure")

        confirmed_changes = await service.assess_operations(now=_T0 + timedelta(seconds=2))
        confirmed = await _alerts(session_factory, "projection_failure")

        # Recovery: give the Task its entity, then re-arm the failed job.
        service.record_batch(
            (
                ObservationEnvelope.task_lifecycle(
                    kind="task.created",
                    task_id=task_id,
                    source_kind="deerflow_run",
                    source_id="run-lifecycle-a",
                    occurred_at=_T0,
                    source_event_id="process-health:lifecycle-a:task:created",
                ),
            )
        )
        await service.flush_task(task_id)
        await service.retry_failed_projections(task_id=task_id)
        await _await_no_failed_projectors(session_factory)

        await service.assess_operations(now=_T0 + timedelta(seconds=3))
        resolved = await _alerts(session_factory, "projection_failure")

        # Break the same projector again.
        second_task_id = new_id()
        service.record(_orphan_budget_consumed(second_task_id, occurred_at=_T0 + timedelta(seconds=4), suffix="lifecycle-b"))
        await service.flush_task(second_task_id)
        await _await_failed_projectors(session_factory, {"task-usage"})

        await service.assess_operations(now=_T0 + timedelta(seconds=5))
        recurred = await _alerts(session_factory, "projection_failure")
    finally:
        await service.stop()
        await engine.dispose()

    assert opened_changes > 0
    assert len(opened) == 1
    assert opened[0].episode == 1
    assert opened[0].alert_type == "projection_failure"
    assert opened[0].subject_id == _SCOPE_ID
    assert opened[0].severity == "warning"
    assert opened[0].resolved_at is None
    assert opened[0].stable_condition_key == projection_failure_condition_key("task-usage", "1")
    assert opened[0].rule_name == "projection-health"

    # Confirm: the categorical Belief did not transition, so no new Assertion
    # and no second episode row.
    assert confirmed_changes == 0
    assert len(confirmed) == 1
    assert confirmed[0].entity_id == opened[0].entity_id
    assert confirmed[0].episode == 1
    assert confirmed[0].resolved_at is None

    assert len(resolved) == 1
    assert resolved[0].resolved_at is not None
    assert resolved[0].workflow_state == "resolved"
    assert resolved[0].resolution_reason == "condition_cleared"

    assert len(recurred) == 2
    assert [row.episode for row in recurred] == [1, 2]
    assert recurred[1].alert_key == recurred[0].alert_key
    assert recurred[1].resolved_at is None


@pytest.mark.anyio
async def test_one_reconcile_call_carries_every_projector_group(tmp_path):
    """RB3④: exhaustiveness across groups, proved by a partial recovery.

    Two projectors fail. One is repaired; its episode resolves, and — the point
    of the exhaustive contract — the other one's episode does **not**, which is
    exactly what a per-group reconcile call would have got wrong.
    """

    engine, session_factory, service = await _started_service(tmp_path, "process-health-groups.db")
    usage_task_id = new_id()
    step_task_id = new_id()
    try:
        service.record(_orphan_budget_consumed(usage_task_id, occurred_at=_T0, suffix="groups-usage"))
        await service.flush_task(usage_task_id)
        service.record(_orphan_step_closed(step_task_id, occurred_at=_T0, suffix="groups-step"))
        await service.flush_task(step_task_id)

        await _await_failed_projectors(session_factory, {"task-usage", "task-step"})

        await service.assess_operations(now=_T0 + timedelta(seconds=1))
        both_open = await _alerts(session_factory, "projection_failure")

        service.record(
            ObservationEnvelope.task_lifecycle(
                kind="task.created",
                task_id=usage_task_id,
                source_kind="deerflow_run",
                source_id="run-groups-usage",
                occurred_at=_T0,
                source_event_id="process-health:groups-usage:task:created",
            )
        )
        await service.flush_task(usage_task_id)
        await service.retry_failed_projections(task_id=usage_task_id)
        deadline = time.monotonic() + 20.0
        while "task-usage" in await _failed_projector_names(session_factory):
            assert time.monotonic() < deadline, "timed out waiting for the task-usage retry to clear"
            await asyncio.sleep(0.01)

        await service.assess_operations(now=_T0 + timedelta(seconds=2))
        after_partial_recovery = await _alerts(session_factory, "projection_failure")
    finally:
        await service.stop()
        await engine.dispose()

    by_key = {row.stable_condition_key: row for row in both_open}
    assert set(by_key) == {
        projection_failure_condition_key("task-usage", "1"),
        projection_failure_condition_key("task-step", "1"),
    }
    assert all(row.resolved_at is None for row in both_open)

    after = {row.stable_condition_key: row for row in after_partial_recovery}
    assert after[projection_failure_condition_key("task-usage", "1")].resolved_at is not None
    assert after[projection_failure_condition_key("task-step", "1")].resolved_at is None


@pytest.mark.anyio
async def test_retry_status_jobs_are_not_projection_failures(tmp_path):
    """A job in ``retry`` is work in flight, not a failure.

    ``retry`` exists to say "this was re-armed after a spent attempt". Counting
    it would raise an Alert about the very act of retrying.
    """

    engine, session_factory, service = await _started_service(tmp_path, "process-health-retry.db")
    task_id = new_id()
    try:
        service.record(_orphan_budget_consumed(task_id, occurred_at=_T0, suffix="retry"))
        await service.flush_task(task_id)
        await _await_failed_projectors(session_factory, {"task-usage"})

        # Park every failed job in `retry` and stop the projector from picking
        # them back up by leaving the dependency unmet but the row unclaimable.
        async with session_factory() as session, session.begin():
            await session.execute(
                update(AnsichProjectionJobRow)
                .where(AnsichProjectionJobRow.status == "failed")
                .values(
                    status="retry",
                    available_at=_UNREACHABLE_AVAILABLE_AT,
                )
            )

        await service.assess_operations(now=_T0 + timedelta(seconds=1))
        alerts = await _alerts(session_factory, "projection_failure")
    finally:
        await service.stop()
        await engine.dispose()

    assert alerts == []


@pytest.mark.anyio
async def test_a_failed_assessor_job_produces_no_projection_failure(tmp_path):
    """Boundary pin (RB3②): assessor jobs are out of this producer's scope.

    An assessor job carries a subject and an evidence watermark, never an
    ``obs_id``, so there is no Observation evidence chain to build an episode
    on. It still reaches an operator through the shared failed-job count and
    ``GET /operations/failed-jobs``; it must not become an Alert here.
    """

    engine, session_factory, service = await _started_service(tmp_path, "process-health-assessor.db")
    task_id = new_id()
    try:
        service.record(
            ObservationEnvelope.task_lifecycle(
                kind="task.created",
                task_id=task_id,
                source_kind="deerflow_run",
                source_id="run-assessor-boundary",
                occurred_at=_T0,
                source_event_id="process-health:assessor-boundary:task:created",
            )
        )
        await service.flush_task(task_id)
        job_id = new_id()
        async with session_factory() as session, session.begin():
            session.add(
                AnsichAssessorJobRow(
                    job_id=job_id,
                    subject_id=task_id,
                    assessor_name="scope-safety",
                    assessor_version="1",
                    evidence_watermark=1,
                    status="failed",
                    attempts=2,
                    available_at=_T0,
                    last_error="ValueError: forced for the boundary pin",
                )
            )
            await session.flush()
            session.add(
                AnsichAssessorErrorRow(
                    error_id=new_id(),
                    job_id=job_id,
                    attempt=2,
                    error_type="ValueError",
                    message="forced for the boundary pin",
                    occurred_at=_T0,
                )
            )

        failed_jobs = await service.list_failed_jobs()
        await service.assess_operations(now=_T0 + timedelta(seconds=1))
        alerts = await _alerts(session_factory, "projection_failure")
    finally:
        await service.stop()
        await engine.dispose()

    assert [job.kind for job in failed_jobs] == ["assessor"]
    assert alerts == []


@pytest.mark.anyio
async def test_projection_failure_evidence_is_capped_to_the_newest_references(tmp_path):
    """More failing jobs than the cap keeps the newest, in ascending order."""

    engine, session_factory, service = await _started_service(tmp_path, "process-health-evidence.db")
    obs_ids: list[str] = []
    try:
        for index in range(13):
            task_id = new_id()
            observation = _orphan_budget_consumed(
                task_id,
                occurred_at=_T0 + timedelta(seconds=index),
                suffix=f"evidence-{index}",
            )
            obs_ids.append(observation.obs_id)
            service.record(observation)
            await service.flush_task(task_id)

        async def _failed_count() -> int:
            async with session_factory() as session:
                return len(
                    list(
                        (
                            await session.execute(
                                select(AnsichProjectionJobRow.job_id).where(
                                    AnsichProjectionJobRow.status == "failed",
                                )
                            )
                        ).scalars()
                    )
                )

        deadline = time.monotonic() + 20.0
        while await _failed_count() < 13:
            assert time.monotonic() < deadline, "timed out waiting for thirteen failed task-usage jobs"
            await asyncio.sleep(0.01)

        await service.assess_operations(now=_T0 + timedelta(seconds=30))
        alerts = await _alerts(session_factory, "projection_failure")
        async with session_factory() as session:
            evidence = list((await session.execute(select(AnsichAlertEvidenceRow.obs_id).where(AnsichAlertEvidenceRow.alert_id == alerts[0].entity_id).order_by(AnsichAlertEvidenceRow.ordinal))).scalars())
    finally:
        await service.stop()
        await engine.dispose()

    assert len(alerts) == 1
    assert len(evidence) == 10
    assert evidence == obs_ids[-10:]


@pytest.mark.anyio
async def test_process_alerts_skip_when_the_host_scope_entity_is_absent(tmp_path):
    """The handle rule: an addressable Scope id is not an existing entity.

    A second backend on the same database, naming a host nothing ever minted,
    sees the same failing projector and the same lost range and writes nothing —
    it asks the database whether its Scope is there rather than trusting that
    some process's mint succeeded.
    """

    engine, session_factory, service = await _started_service(tmp_path, "process-health-absent.db")
    other_hostname = "ansich-process-health-never-minted"
    other_scope_id = host_scope_id(other_hostname)
    task_id = new_id()
    try:
        service.record(_orphan_budget_consumed(task_id, occurred_at=_T0, suffix="absent"))
        await service.flush_task(task_id)
        service.record(
            _lost_range(
                occurred_at=_T0,
                first_sequence=1,
                last_sequence=4,
                producer_name="absent-probe",
                producer_instance_id="worker-a",
                suffix="absent",
            )
        )
        await service.flush_task(ANSICH_BOOTSTRAP_TASK_ID)
        await _await_failed_projectors(session_factory, {"task-usage"})

        other_backend = SqlAnsichBackend(
            session_factory,
            hostname=other_hostname,
            projector_dependency_timeout_seconds=0,
        )
        other_changed = await other_backend.assess_operations(now=_T0 + timedelta(seconds=1))

        async with session_factory() as session:
            minted = await session.get(AnsichScopeRow, _SCOPE_ID)
            never_minted = await session.get(AnsichScopeRow, other_scope_id)
            alerts_for_other = list(
                (
                    await session.execute(
                        select(AnsichAlertRow).where(
                            AnsichAlertRow.subject_id == other_scope_id,
                        )
                    )
                ).scalars()
            )
            assertions_for_other = list(
                (
                    await session.execute(
                        select(AnsichBeliefAssertionRow).where(
                            AnsichBeliefAssertionRow.subject_id == other_scope_id,
                        )
                    )
                ).scalars()
            )
    finally:
        await service.stop()
        await engine.dispose()

    assert minted is not None
    assert never_minted is None
    assert other_changed == 0
    assert alerts_for_other == []
    assert assertions_for_other == []


@pytest.mark.anyio
async def test_observability_degradation_opens_resolves_after_the_window_and_recurs(tmp_path):
    """Loss rows are forever; the condition is not.

    An episode opens on the first lost range, stays open while the range is
    inside the window, resolves once the window passes with nothing new, and a
    later range opens ``episode=2`` under the same key.
    """

    engine, session_factory, service = await _started_service(tmp_path, "process-health-loss.db")
    try:
        first = _lost_range(
            occurred_at=_T0,
            first_sequence=11,
            last_sequence=14,
            producer_name="loss-probe",
            producer_instance_id="worker-a",
            suffix="first",
        )
        service.record(first)
        await service.flush_task(ANSICH_BOOTSTRAP_TASK_ID)

        opened_changes = await service.assess_operations(now=_T0 + timedelta(seconds=1))
        opened = await _alerts(session_factory, "observability_degradation")

        confirmed_changes = await service.assess_operations(now=_T0 + timedelta(seconds=2))
        confirmed = await _alerts(session_factory, "observability_degradation")

        await service.assess_operations(now=_T0 + timedelta(seconds=_OBSERVABILITY_LOSS_WINDOW_SECONDS + 1))
        resolved = await _alerts(session_factory, "observability_degradation")

        later = _T0 + timedelta(seconds=_OBSERVABILITY_LOSS_WINDOW_SECONDS + 30)
        service.record(
            _lost_range(
                occurred_at=later,
                first_sequence=90,
                last_sequence=92,
                producer_name="loss-probe",
                producer_instance_id="worker-a",
                suffix="second",
            )
        )
        await service.flush_task(ANSICH_BOOTSTRAP_TASK_ID)
        await service.assess_operations(now=later + timedelta(seconds=1))
        recurred = await _alerts(session_factory, "observability_degradation")

        async with session_factory() as session:
            evidence = list((await session.execute(select(AnsichAlertEvidenceRow.obs_id).where(AnsichAlertEvidenceRow.alert_id == opened[0].entity_id).order_by(AnsichAlertEvidenceRow.ordinal))).scalars())
    finally:
        await service.stop()
        await engine.dispose()

    assert opened_changes > 0
    assert len(opened) == 1
    assert opened[0].episode == 1
    assert opened[0].severity == "critical"
    assert opened[0].rule_name == "observability-loss"
    assert opened[0].stable_condition_key == observability_loss_condition_key("loss-probe", "worker-a")
    assert evidence == [first.obs_id]

    assert confirmed_changes == 0
    assert len(confirmed) == 1
    assert confirmed[0].resolved_at is None

    assert len(resolved) == 1
    assert resolved[0].resolved_at is not None

    assert [row.episode for row in recurred] == [1, 2]
    assert recurred[1].alert_key == recurred[0].alert_key
    assert recurred[1].resolved_at is None


@pytest.mark.anyio
async def test_observability_degradation_keys_by_losing_producer(tmp_path):
    """Two losing producers, one quiet again: only its episode resolves."""

    engine, session_factory, service = await _started_service(tmp_path, "process-health-loss-keys.db")
    try:
        service.record_batch(
            (
                _lost_range(
                    occurred_at=_T0,
                    first_sequence=1,
                    last_sequence=2,
                    producer_name="probe-a",
                    producer_instance_id="worker-1",
                    suffix="keys-a",
                ),
                _lost_range(
                    occurred_at=_T0,
                    first_sequence=3,
                    last_sequence=4,
                    producer_name="probe-b",
                    producer_instance_id="worker-2",
                    suffix="keys-b",
                ),
            )
        )
        await service.flush_task(ANSICH_BOOTSTRAP_TASK_ID)
        await service.assess_operations(now=_T0 + timedelta(seconds=1))
        both_open = await _alerts(session_factory, "observability_degradation")

        # `probe-b` keeps losing; `probe-a` has gone quiet. Assess past the
        # window relative to the original pair.
        still_losing_at = _T0 + timedelta(seconds=_OBSERVABILITY_LOSS_WINDOW_SECONDS + 10)
        service.record(
            _lost_range(
                occurred_at=still_losing_at,
                first_sequence=5,
                last_sequence=9,
                producer_name="probe-b",
                producer_instance_id="worker-2",
                suffix="keys-b-again",
            )
        )
        await service.flush_task(ANSICH_BOOTSTRAP_TASK_ID)
        await service.assess_operations(now=still_losing_at + timedelta(seconds=1))
        after = await _alerts(session_factory, "observability_degradation")
    finally:
        await service.stop()
        await engine.dispose()

    assert {row.stable_condition_key for row in both_open} == {
        observability_loss_condition_key("probe-a", "worker-1"),
        observability_loss_condition_key("probe-b", "worker-2"),
    }
    by_key = {row.stable_condition_key: row for row in after}
    assert by_key[observability_loss_condition_key("probe-a", "worker-1")].resolved_at is not None
    assert by_key[observability_loss_condition_key("probe-b", "worker-2")].resolved_at is None
    assert by_key[observability_loss_condition_key("probe-b", "worker-2")].episode == 1


@pytest.mark.anyio
async def test_a_lost_row_with_an_unreadable_payload_keeps_the_loss_visible(tmp_path):
    """An externalized or missing payload groups under the reserved identity.

    ``observability.lost`` carries four small fields, so this is reachable only
    through payload externalization or an ``ansich_payloads`` row that has gone
    missing — but the loss is the one thing that must not disappear because its
    label did. It is charged to a reserved, obviously-not-a-producer name rather
    than dropped (invisible loss) or attributed to the envelope's own producer
    (which is the collector *reporting* the loss, not the one that suffered it).
    """

    engine, session_factory, service = await _started_service(tmp_path, "process-health-unreadable.db")
    try:
        unreadable = _lost_range(
            occurred_at=_T0,
            first_sequence=1,
            last_sequence=2,
            producer_name="a-real-producer",
            producer_instance_id="worker-a",
            suffix="unreadable",
        )
        service.record(unreadable)
        await service.flush_task(ANSICH_BOOTSTRAP_TASK_ID)
        # Simulate the externalized shape the reader sees: `payload_json IS NULL`
        # beside a `payload_ref_id`. The CHECK constraint requires exactly one of
        # the two, so the payload row has to exist for the update to be legal.
        payload_id = new_id()
        async with session_factory() as session, session.begin():
            session.add(
                AnsichPayloadRow(
                    payload_id=payload_id,
                    content_type="application/json",
                    encoding="utf-8",
                    compression="none",
                    byte_size=2,
                    sha256="0" * 64,
                    body=b"{}",
                )
            )
            await session.flush()
            await session.execute(update(AnsichObservationRow).where(AnsichObservationRow.obs_id == unreadable.obs_id).values(payload_json=None, payload_ref_id=payload_id))

        await service.assess_operations(now=_T0 + timedelta(seconds=1))
        alerts = await _alerts(session_factory, "observability_degradation")
    finally:
        await service.stop()
        await engine.dispose()

    assert len(alerts) == 1
    assert alerts[0].stable_condition_key == observability_loss_condition_key(
        _UNREADABLE_LOSS_PRODUCER,
        _UNREADABLE_LOSS_PRODUCER,
    )
    assert alerts[0].resolved_at is None


@pytest.mark.anyio
async def test_a_truncated_loss_scan_says_so_and_can_miss_a_quiet_producer(tmp_path):
    """The scan cap's real cost is a silent never-alert, so it must not be silent.

    One quiet producer with a single in-window loss, then enough noise to fill
    the scan past its cap. The quiet producer is **not merely resolved early —
    it never enters the key set at all**, so no episode ever opens for it and it
    stays invisible on every tick while the noise continues. That is the honest
    statement of what the cap costs, and it is why the pass runs an unbounded
    ``COUNT`` beside the capped scan: the Assertions it writes carry
    ``scan_truncated``, so the gap is at least detectable rather than silent.
    """

    engine, session_factory, service = await _started_service(tmp_path, "process-health-truncated.db")
    noisy_count = _OBSERVABILITY_LOSS_SCAN_LIMIT + 100
    try:
        # Oldest row in the window, and the only one this producer ever loses.
        service.record(
            _lost_range(
                occurred_at=_T0,
                first_sequence=1,
                last_sequence=1,
                producer_name="quiet-probe",
                producer_instance_id="worker-q",
                suffix="quiet",
            )
        )
        for index in range(noisy_count):
            service.record(
                _lost_range(
                    occurred_at=_T0 + timedelta(seconds=1 + index),
                    first_sequence=1 + index,
                    last_sequence=2 + index,
                    producer_name="noisy-probe",
                    producer_instance_id="worker-n",
                    suffix=f"noisy-{index}",
                )
            )
        await service.flush_task(ANSICH_BOOTSTRAP_TASK_ID)

        await service.assess_operations(now=_T0 + timedelta(seconds=noisy_count + 2))
        alerts = await _alerts(session_factory, "observability_degradation")
        async with session_factory() as session:
            assertions = list(
                (
                    await session.execute(
                        select(AnsichBeliefAssertionRow).where(
                            AnsichBeliefAssertionRow.subject_id == _SCOPE_ID,
                            AnsichBeliefAssertionRow.assessor_name == "observability-loss",
                        )
                    )
                ).scalars()
            )
    finally:
        await service.stop()
        await engine.dispose()

    keys = {row.stable_condition_key for row in alerts}
    # The miss, stated as an assertion rather than left implicit.
    assert observability_loss_condition_key("noisy-probe", "worker-n") in keys
    assert observability_loss_condition_key("quiet-probe", "worker-q") not in keys
    # ...and the signal that makes the miss detectable.
    assert assertions
    assert all(row.value_json["scan_truncated"] is True for row in assertions)


@pytest.mark.anyio
async def test_recovery_resolves_an_episode_opened_by_an_earlier_rule_version(tmp_path):
    """A rule-version bump must not strand the episodes the old version opened.

    ``alert_key`` is ``(alert_type, subject, rule.name, stable_condition_key)``
    and carries **no** version, so a v1-era episode and a v2 condition for the
    same group are one episode line. If the recovery query filtered on the
    current version, bumping the rule at an all-healthy moment would leave every
    open v1 episode with nothing left in the system that could ever close it.
    """

    engine, session_factory, service = await _started_service(tmp_path, "process-health-version.db")
    try:
        service.record(
            _lost_range(
                occurred_at=_T0,
                first_sequence=1,
                last_sequence=2,
                producer_name="version-probe",
                producer_instance_id="worker-a",
                suffix="version",
            )
        )
        await service.flush_task(ANSICH_BOOTSTRAP_TASK_ID)
        await service.assess_operations(now=_T0 + timedelta(seconds=1))
        opened = await _alerts(session_factory, "observability_degradation")

        # Rewrite the standing Belief as if an earlier rule version had made it.
        # The episode stays exactly as v1 left it.
        async with session_factory() as session, session.begin():
            await session.execute(
                update(AnsichBeliefAssertionRow)
                .where(
                    AnsichBeliefAssertionRow.subject_id == _SCOPE_ID,
                    AnsichBeliefAssertionRow.assessor_name == "observability-loss",
                )
                .values(assessor_version="0", source_version="0")
            )

        # The loss stops; the current version's pass must still resolve it.
        await service.assess_operations(now=_T0 + timedelta(seconds=_OBSERVABILITY_LOSS_WINDOW_SECONDS + 1))
        resolved = await _alerts(session_factory, "observability_degradation")
    finally:
        await service.stop()
        await engine.dispose()

    assert len(opened) == 1
    assert opened[0].resolved_at is None
    assert len(resolved) == 1
    assert resolved[0].entity_id == opened[0].entity_id
    assert resolved[0].resolved_at is not None


@pytest.mark.anyio
async def test_process_health_beliefs_are_transition_only(tmp_path):
    """The Scope's Belief carries the categorical state, once per transition."""

    engine, session_factory, service = await _started_service(tmp_path, "process-health-belief.db")
    try:
        service.record(
            _lost_range(
                occurred_at=_T0,
                first_sequence=1,
                last_sequence=1,
                producer_name="belief-probe",
                producer_instance_id="worker-a",
                suffix="belief",
            )
        )
        await service.flush_task(ANSICH_BOOTSTRAP_TASK_ID)
        for offset in (1, 2, 3):
            await service.assess_operations(now=_T0 + timedelta(seconds=offset))
        field_name = observability_loss_field_name("belief-probe", "worker-a")
        async with session_factory() as session:
            assertions = list(
                (
                    await session.execute(
                        select(AnsichBeliefAssertionRow).where(
                            AnsichBeliefAssertionRow.subject_id == _SCOPE_ID,
                            AnsichBeliefAssertionRow.field_name == field_name,
                        )
                    )
                ).scalars()
            )
            current = await session.get(AnsichCurrentBeliefRow, (_SCOPE_ID, field_name))
    finally:
        await service.stop()
        await engine.dispose()

    assert len(assertions) == 1
    assert assertions[0].value_json["value"] == "degraded"
    assert assertions[0].assessor_name == "observability-loss"
    assert current is not None
    assert current.assertion_id == assertions[0].assertion_id


@pytest.mark.anyio
async def test_alert_list_filter_admits_both_process_alert_types(tmp_path):
    """The router allowlist admits the two process-subject types."""

    engine, session_factory, service = await _started_service(tmp_path, "process-health-router.db")
    task_id = new_id()
    try:
        service.record(_orphan_budget_consumed(task_id, occurred_at=_T0, suffix="router"))
        await service.flush_task(task_id)
        service.record(
            _lost_range(
                occurred_at=_T0,
                first_sequence=1,
                last_sequence=3,
                producer_name="router-probe",
                producer_instance_id="worker-a",
                suffix="router",
            )
        )
        await service.flush_task(ANSICH_BOOTSTRAP_TASK_ID)
        await _await_failed_projectors(session_factory, {"task-usage"})
        await service.assess_operations(now=_T0 + timedelta(seconds=1))

        app = make_authed_test_app(user_factory=_admin_user)
        app.state.ansich_service = service
        app.include_router(ansich_router.router)
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            projection = await client.get("/api/ansich/operations/alerts?type=projection_failure")
            degradation = await client.get("/api/ansich/operations/alerts?type=observability_degradation")
            unknown = await client.get("/api/ansich/operations/alerts?type=not_a_type")
    finally:
        await service.stop()
        await engine.dispose()

    assert projection.status_code == 200
    assert [item["alert_type"] for item in projection.json()["items"]] == ["projection_failure"]
    assert projection.json()["items"][0]["subject_id"] == _SCOPE_ID

    assert degradation.status_code == 200
    assert [item["alert_type"] for item in degradation.json()["items"]] == ["observability_degradation"]

    assert unknown.status_code == 422


# --- assessment-tick failure reporting --------------------------------------
#
# `_projector_loop` must swallow an `assess_operations` exception, but the blast
# radius makes swallowing it *silently* untenable: one transaction runs
# heartbeat, dwell, budget, environment and both producers above, so a single
# failure discards every family's work for that tick. These pin that a failing
# tick is always reported at DEBUG and is reported at WARNING without flooding.


def _tick_failure_records(caplog: pytest.LogCaptureFixture, level: int) -> list[logging.LogRecord]:
    return [record for record in caplog.records if getattr(record, "event", None) == "ansich.assessment.tick_failed" and record.levelno == level]


@pytest.mark.anyio
async def test_a_failing_assessment_tick_is_never_silent(tmp_path, caplog: pytest.LogCaptureFixture):
    """DEBUG with the traceback every time; WARNING at most once per window."""

    engine, session_factory, service = await _started_service(tmp_path, "process-health-tick-log.db")
    try:
        with caplog.at_level(logging.DEBUG, logger="ansich.service"):
            service._report_assessment_failure(RuntimeError("first failure"))
            service._report_assessment_failure(RuntimeError("second failure"))
            first_debug = _tick_failure_records(caplog, logging.DEBUG)
            first_warnings = _tick_failure_records(caplog, logging.WARNING)

            # Step past the rate-limit window without sleeping through it.
            service._last_assessment_warning_at = time.monotonic() - 3600.0
            service._report_assessment_failure(RuntimeError("third failure"))
            later_warnings = _tick_failure_records(caplog, logging.WARNING)
    finally:
        await service.stop()
        await engine.dispose()

    # Every failure is reported at DEBUG, with the exception itself attached.
    assert len(first_debug) == 2
    assert all(record.exc_info is not None for record in first_debug)
    # The second failure inside the window is counted, not repeated.
    assert len(first_warnings) == 1
    assert first_warnings[0].suppressed_assessment_warning_count == 0
    assert len(later_warnings) == 2
    assert later_warnings[1].suppressed_assessment_warning_count == 1


@pytest.mark.anyio
async def test_the_projector_loop_routes_a_failing_tick_to_the_reporter(tmp_path):
    """The loop still swallows the exception, but no longer swallows the fact."""

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'process-health-tick-loop.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(
        session_factory,
        hostname=_HOSTNAME,
        operations_assessment_interval_ms=20,
    )
    reported: list[BaseException] = []
    service._report_assessment_failure = reported.append  # type: ignore[method-assign]

    async def _always_fails(**_kwargs) -> int:
        raise RuntimeError("assessment tick exploded")

    service.assess_operations = _always_fails  # type: ignore[method-assign]
    await service.start()
    try:
        deadline = time.monotonic() + 20.0
        while len(reported) < 2:
            assert time.monotonic() < deadline, "timed out waiting for two reported assessment failures"
            await asyncio.sleep(0.01)
        # The loop is still alive and still projecting, which is the whole
        # reason the exception is swallowed in the first place.
        assert service._running
    finally:
        await service.stop()
        await engine.dispose()

    assert all(isinstance(error, RuntimeError) for error in reported)


# --- pure rules -------------------------------------------------------------


def test_projection_failure_rule_reports_a_categorical_verdict() -> None:
    failing = assess_projection_failure(
        scope_id=_SCOPE_ID,
        projector_name="task-usage",
        projector_version="1",
        failing=True,
        as_of=_T0,
        now=_T0,
        evidence_obs_ids=("obs-1", "obs-2"),
    )
    recovered = assess_projection_failure(
        scope_id=_SCOPE_ID,
        projector_name="task-usage",
        projector_version="1",
        failing=False,
        as_of=_T0,
        now=_T0,
    )

    assert failing.field_name == "projection_failure:task-usage@1"
    assert failing.value["value"] == "failing"
    assert failing.value["condition_key"] == "projector:task-usage@1"
    assert failing.assessor.name == "projection-health"
    assert failing.authority_class == "configured_rule"
    assert failing.fidelity_class == "rule"
    assert [item.obs_id for item in failing.evidence] == ["obs-1", "obs-2"]

    assert recovered.value["value"] == "ok"
    assert recovered.evidence == ()
    # Same key on both sides: that is what lets the inactive condition resolve
    # the episode the active one opened.
    assert recovered.value["condition_key"] == failing.value["condition_key"]


def test_observability_rule_hashes_the_window_into_its_config_identity() -> None:
    narrow = assess_observability_degradation(
        scope_id=_SCOPE_ID,
        producer_name="probe",
        producer_instance_id="worker-a",
        degraded=True,
        window_seconds=60,
        as_of=_T0,
        now=_T0,
        evidence_obs_ids=("obs-1",),
    )
    wide = assess_observability_degradation(
        scope_id=_SCOPE_ID,
        producer_name="probe",
        producer_instance_id="worker-a",
        degraded=True,
        window_seconds=900,
        as_of=_T0,
        now=_T0,
        evidence_obs_ids=("obs-1",),
    )

    assert narrow.field_name == "observability_degradation:probe@worker-a"
    assert narrow.value["value"] == "degraded"
    assert narrow.config_hash != wide.config_hash

    with pytest.raises(ValueError):
        assess_observability_degradation(
            scope_id=_SCOPE_ID,
            producer_name="probe",
            producer_instance_id="worker-a",
            degraded=False,
            window_seconds=0,
            as_of=_T0,
            now=_T0,
        )


def test_over_long_identities_degrade_to_a_digest_instead_of_truncating() -> None:
    """A long identity must stay distinguishable, not be cut to a shared prefix."""

    long_producer = "p" * 128
    first = observability_loss_field_name(long_producer, "i" * 128)
    second = observability_loss_field_name(long_producer, "i" * 127 + "j")

    assert len(first) <= 64
    assert first.startswith("observability_degradation:#")
    assert first != second

    long_key = observability_loss_condition_key(long_producer, "i" * 128)
    assert len(long_key) <= 256

    # A short identity keeps its readable form on both surfaces.
    assert projection_failure_field_name("task-step", "1") == "projection_failure:task-step@1"
    assert projection_failure_condition_key("task-step", "1") == "projector:task-step@1"


@pytest.mark.anyio
async def test_service_and_backend_agree_on_the_host_scope(tmp_path):
    """The mint and the producers must name the same Scope entity."""

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'process-health-hostname.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    backend = SqlAnsichBackend(session_factory, hostname=_HOSTNAME)
    service = AnsichService(backend, hostname=_HOSTNAME, flush_interval_ms=60_000)
    await service.start()
    try:
        # `host_scope_id` means "this process's mint was written"; the Scope
        # *entity* only exists once the projector has run, which is precisely
        # the gap `_existing_host_scope_id` refuses to paper over.
        assert service.host_scope_id == _SCOPE_ID
        resolved: str | None = None
        deadline = time.monotonic() + 20.0
        while resolved is None:
            assert time.monotonic() < deadline, "timed out waiting for the host Scope projection"
            async with session_factory() as session:
                resolved = await backend._existing_host_scope_id(session)
            if resolved is None:
                await asyncio.sleep(0.01)
        assert resolved == _SCOPE_ID
    finally:
        await service.stop()
        await engine.dispose()
