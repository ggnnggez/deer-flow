"""The host-Scope bootstrap mint and the process-wide loss it makes reportable.

RB1 + RB2. Two facts this collector could not previously write down get a
subject here, and both of them are about the *process* rather than about any
Task: the environment it runs in, and the loss it charged for something that
never was an Observation.

**Why a Scope and not a Task.** ``ObservationEnvelope`` requires a ``task_id``,
so a process-level row has to carry something there. It carries
``ANSICH_BOOTSTRAP_TASK_ID`` — a fixed, documented sentinel that means "no Task
exists for this" — and its *subject* is the host ``Scope``, which is a real
entity a reader can resolve. The sentinel is legal only because
``ansich_observations.task_id`` has no foreign key; every Task-scoped machine
that does have one (the assessor job and watermark tables) must therefore be
kept away from these rows, which is what
``sql.py::_assessors_for_observation`` does and what
``test_a_bootstrap_row_enqueues_no_task_scoped_assessor`` pins with
``PRAGMA foreign_keys=ON``.

**Two backends, deliberately.** The mint's durability, its convergence with the
environment probe's own `host` declaration, and its replay are properties of a
real database, so they run against SQLite through ``create_sql_ansich_service``.
The drain's *decisions* — what it refuses to write, what it leaves in the
bucket, what it does when a report is refused — are properties of the service,
and a fake backend that can refuse one kind on demand is the only way to stand
the collector in those states without also arguing about SQLite.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime

import pytest
from ansich import AnsichService, ObservationEnvelope, new_id
from ansich.contracts import ANSICH_BOOTSTRAP_TASK_ID
from ansich.safety import host_scope_id
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from support.ansich_settle import only_test_driven_assessments

from deerflow.ansich import create_sql_ansich_service
from deerflow.ansich.persistence.models import (
    AnsichAssessorJobRow,
    AnsichEntityRow,
    AnsichObservationRow,
    AnsichRelationRow,
    AnsichScopeRow,
    AnsichTaskRow,
)
from deerflow.persistence.base import Base

_HOSTNAME = "ansich-bootstrap-test-host"
_OCCURRED_AT = datetime(2026, 8, 20, 9, 0, tzinfo=UTC)


def _lifecycle(task_id: str) -> ObservationEnvelope:
    return ObservationEnvelope.task_lifecycle(
        kind="task.created",
        task_id=task_id,
        source_kind="deerflow_run",
        source_id=task_id,
        occurred_at=_OCCURRED_AT,
        source_event_id=f"run:{task_id}:task:created",
        producer_name="bootstrap-test-probe",
        producer_version="1",
        producer_instance_id="worker-a",
    )


async def _wait_for(description: str, predicate: Callable[[], bool], *, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, f"timed out after {timeout}s waiting for {description}"
        await asyncio.sleep(0.005)


def _engine(tmp_path, name: str):
    """A SQLite engine with production's foreign-key enforcement turned on.

    Opted in per engine (the suite conftest deliberately sets only the locking
    pragmas), and needed here rather than convenient: the whole hazard this file
    guards against is a Task-scoped row minted for a Task that does not exist,
    and without FK enforcement SQLite would accept it silently.
    """

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / name}.db")

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record):  # pragma: no cover - driver callback
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


@contextlib.asynccontextmanager
async def _sql_service(engine, **overrides) -> AsyncIterator[AnsichService]:
    settings: dict[str, object] = {
        "flush_interval_ms": 20,
        "terminal_flush_timeout_ms": 10_000,
        "projector_poll_interval_ms": 5,
        "operations_assessment_interval_ms": 60_000,
        "hostname": _HOSTNAME,
    }
    settings.update(overrides)
    service = create_sql_ansich_service(async_sessionmaker(engine, expire_on_commit=False), **settings)  # type: ignore[arg-type]
    only_test_driven_assessments(service)
    await service.start()
    try:
        yield service
    finally:
        await service.stop()


async def _mint_rows(session_factory) -> list[AnsichObservationRow]:
    async with session_factory() as session:
        rows = await session.scalars(select(AnsichObservationRow).where(AnsichObservationRow.kind == "scope.snapshotted").order_by(AnsichObservationRow.ingest_seq))
        return list(rows)


class _ScopeAwareBackend:
    """A backend that projects nothing but declares Scopes real, and can refuse.

    Its whole job is to make one decision observable at a time: which kinds it
    accepts. ``refuse_kinds`` fails a write the way storage refuses one — the
    call raises and nothing lands — so a test can drive "the mint could not be
    written", "the report could not be written", and the heal that follows
    either of them, without a database in the way.
    """

    projects_scope_entities = True

    def __init__(self) -> None:
        self.written: list[ObservationEnvelope] = []
        self.refuse_kinds: set[str] = set()

    async def persist_and_project(self, observations: list[ObservationEnvelope]) -> int:
        if any(observation.kind in self.refuse_kinds for observation in observations):
            raise RuntimeError("storage refused this batch")
        self.written.extend(observations)
        return len(observations)

    def kinds(self) -> list[str]:
        return [observation.kind for observation in self.written]

    def lost_rows(self) -> list[ObservationEnvelope]:
        return [observation for observation in self.written if observation.kind == "observability.lost"]


async def _charge_one_global_range(service: AnsichService) -> None:
    """Charge a range that has no Task, the way the collector really charges one.

    A non-``ObservationEnvelope`` item is rejected at intake and charged
    process-wide, because there is no envelope to read a Task or a producer off
    (``_record_batch_loss``). That is the shape ``observability.degraded``
    cannot report and this batch exists for.
    """

    receipts = service.record_batch((object(),))  # type: ignore[arg-type]
    assert receipts[0].accepted is False
    assert receipts[0].reason == "validation_failed"


@pytest.mark.anyio
async def test_start_mints_a_task_free_host_scope(tmp_path) -> None:
    """RB1①③. The mint lands, projects into a Scope entity, and owes no Task.

    Four separate claims, because three of them are the ones a later change
    could quietly break: the Observation is durable, the *entity* exists (so a
    row subjected to it is resolvable), it carries no ``within_scope`` relation
    (a Task-free Scope is reachable only because ``_project_scope_snapshot``
    returns before the relation when ``relation_role`` is absent), and the
    sentinel did not become a Task.
    """

    engine = _engine(tmp_path, "mint")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    expected_scope_id = host_scope_id(_HOSTNAME)

    try:
        async with _sql_service(engine) as service:
            assert service.host_scope_id == expected_scope_id
            # Settled by replay rather than by waiting on the projector loop:
            # the loop would get there, but only this makes *when* deterministic.
            await service.rebuild_until_settled()

            async with session_factory() as session:
                mint = await session.scalar(select(AnsichObservationRow).where(AnsichObservationRow.kind == "scope.snapshotted"))
                assert mint is not None
                assert mint.task_id == ANSICH_BOOTSTRAP_TASK_ID
                assert mint.subject_type == "scope"
                assert mint.subject_id == expected_scope_id
                assert mint.source_event_id == f"ansich:host-scope:{_HOSTNAME}"
                assert mint.correlation_id == expected_scope_id

                entity = await session.get(AnsichEntityRow, expected_scope_id)
                assert entity is not None and entity.entity_type == "scope"
                scope = await session.get(AnsichScopeRow, expected_scope_id)
                assert scope is not None
                assert (scope.scope_kind, scope.parent_scope_id) == ("host", None)

                # Task-free: no relation was asserted for it, and the sentinel
                # is not a Task.
                relations = await session.scalar(select(func.count()).select_from(AnsichRelationRow).where(AnsichRelationRow.object_id == expected_scope_id))
                assert relations == 0
                assert await session.get(AnsichTaskRow, ANSICH_BOOTSTRAP_TASK_ID) is None

            assert service.get_health().failed_jobs == 0
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_a_bootstrap_row_enqueues_no_task_scoped_assessor(tmp_path) -> None:
    """RB1②/RB3①. The mint must not touch the Task-bound assessor machine.

    ``task-safety`` normally enqueues the scope-safety assessor after every
    Scope projection, and ``ansich_assessor_jobs.subject_id`` is FK-bound to
    ``ansich_tasks``. For a bootstrap row that Task does not exist, so the
    insert would fail — taking the projection down with it and leaving the mint
    a durably failed job rather than a Scope. This is the teeth for the guard:
    with foreign keys enforced, an unguarded enqueue makes ``failed_jobs``
    non-zero and the Scope row absent.
    """

    engine = _engine(tmp_path, "no-assessor")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with _sql_service(engine) as service:
            await service.rebuild_until_settled()
            health = service.get_health()

            async with session_factory() as session:
                assessor_jobs = await session.scalar(select(func.count()).select_from(AnsichAssessorJobRow))
                assert assessor_jobs == 0
                assert await session.get(AnsichScopeRow, host_scope_id(_HOSTNAME)) is not None

            assert health.failed_jobs == 0
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_the_mint_is_absorbed_on_restart_and_by_a_second_collector(tmp_path) -> None:
    """RB1①. Deterministic ``source_event_id`` plus a fixed producer identity.

    Both halves are needed and both are exercised: the same service started
    twice (restart) and a second service over the same database (the second
    Gateway worker) each write nothing new. A per-process producer instance id
    would pass neither.
    """

    engine = _engine(tmp_path, "idempotent")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with _sql_service(engine) as service:
            assert len(await _mint_rows(session_factory)) == 1
            await service.stop()
            await service.start()
            assert len(await _mint_rows(session_factory)) == 1
            assert service.host_scope_id == host_scope_id(_HOSTNAME)

        async with _sql_service(engine) as second:
            assert second.host_scope_id == host_scope_id(_HOSTNAME)
            assert len(await _mint_rows(session_factory)) == 1
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_the_mint_converges_with_the_environment_probe_host_scope(tmp_path) -> None:
    """RB1③. One host, one Scope entity — no coordination between the two writers.

    The environment probe declares the same `host` Scope from inside a real
    Task, with a ``relation_role``. Convergence is not "both wrote a Scope": it
    is that ``_project_scope_snapshot``'s identity check passed, so the probe's
    row *related a Task to the entity the bootstrap minted* instead of raising
    ``Scope identity conflicts`` or minting a second one. ``created_obs_id``
    still naming the mint is what says which of the two established it.
    """

    engine = _engine(tmp_path, "convergence")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    task_id = new_id()
    scope_id = host_scope_id(_HOSTNAME)

    try:
        async with _sql_service(engine) as service:
            mint = await _mint_rows(session_factory)
            assert len(mint) == 1

            service.record(_lifecycle(task_id))
            service.record(
                ObservationEnvelope.scope_snapshotted(
                    task_id=task_id,
                    run_id=task_id,
                    occurred_at=_OCCURRED_AT,
                    scope_kind="host",
                    external_ref=_HOSTNAME,
                    relation_role="host_environment",
                    source_event_id=f"run:{task_id}:scope:host",
                    producer_name="deerflow-environment-probe",
                    producer_version="1",
                    producer_instance_id="worker-a",
                )
            )
            await service.flush_task(task_id)
            await service.rebuild_until_settled()

            async with session_factory() as session:
                scopes = await session.scalars(select(AnsichScopeRow))
                host_scopes = [row for row in scopes if row.scope_kind == "host"]
                assert [row.entity_id for row in host_scopes] == [scope_id]
                assert host_scopes[0].created_obs_id == mint[0].obs_id

                relation = await session.scalar(select(AnsichRelationRow).where(AnsichRelationRow.object_id == scope_id))
                assert relation is not None
                assert (relation.subject_id, relation.relation_role) == (task_id, "host_environment")

            assert service.get_health().failed_jobs == 0
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_rebuild_recreates_the_host_scope_from_the_durable_mint(tmp_path) -> None:
    """RB1⑤. Replay safety: the Observation is the record, the Scope is derived.

    The Scope row is deleted out from under the service — which is what a
    rebuild does to every projection before replaying it — and the rebuild puts
    it back without anything minting a second Observation.
    """

    engine = _engine(tmp_path, "rebuild")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    scope_id = host_scope_id(_HOSTNAME)

    try:
        async with _sql_service(engine) as service:
            await service.rebuild_until_settled()
            async with session_factory() as session:
                assert await session.get(AnsichScopeRow, scope_id) is not None

            async with session_factory() as session, session.begin():
                scope = await session.get(AnsichScopeRow, scope_id)
                await session.delete(scope)
                entity = await session.get(AnsichEntityRow, scope_id)
                await session.delete(entity)
            async with session_factory() as session:
                assert await session.get(AnsichScopeRow, scope_id) is None

            # A bounded completeness loop, not one round: ``rebuild_projections()``
            # reports rather than waits (F10-26), so under load a single pass can
            # legitimately return with dependency-deferred jobs still unsettled.
            outcome = await service.rebuild_until_settled()

            assert outcome.unsettled == 0
            async with session_factory() as session:
                assert await session.get(AnsichScopeRow, scope_id) is not None
            assert len(await _mint_rows(session_factory)) == 1
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_process_wide_loss_lands_as_observability_lost_against_the_host_scope(tmp_path) -> None:
    """RB2③, end to end. The bucket empties only into a durable row.

    The charge itself is unchanged by the report — ``dropped_count`` and
    ``lost_ranges`` still say the rows were lost, because reporting loss is not
    un-charging it. What changes is ``unreported_global_lost_range_count``,
    which is the count of loss *nothing has written down*, and the row that
    makes it drop is readable back under the sentinel.
    """

    engine = _engine(tmp_path, "drain")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    task_id = new_id()

    try:
        async with _sql_service(engine) as service:
            await _charge_one_global_range(service)
            charged = service.get_health()
            assert charged.unreported_global_lost_range_count == 1
            assert charged.dropped_count == 1

            # Any successful Observation write runs the reporting seam; this is
            # the ordinary path a recovered collector takes.
            service.record(_lifecycle(task_id))
            await _wait_for(
                "the collector to report the process-wide range",
                lambda: service.get_health().unreported_global_lost_range_count == 0,
            )

            reported = service.get_health()
            bootstrap_rows = await service.list_observations(ANSICH_BOOTSTRAP_TASK_ID)

        lost_rows = [row for row in bootstrap_rows if row.kind == "observability.lost"]
        assert len(lost_rows) == 1
        assert lost_rows[0].subject_type == "scope"
        assert lost_rows[0].subject_id == host_scope_id(_HOSTNAME)
        assert lost_rows[0].payload == {
            "first_sequence": charged.lost_ranges[0].first_sequence,
            "last_sequence": charged.lost_ranges[0].last_sequence,
            # A non-envelope item has no producer identity to charge, and the
            # report says so rather than guessing one.
            "producer_name": "unknown",
            "producer_instance_id": "unknown",
        }

        # Reported, not forgotten: the loss is still charged and still visible.
        assert reported.dropped_count == 1
        assert reported.lost_ranges == charged.lost_ranges
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_a_refused_report_leaves_the_range_in_the_bucket() -> None:
    """The honesty rule, in both directions, on one collector.

    Nothing is marked reported unless something wrote it: while the report is
    refused the count stays at one and no ``observability.lost`` row exists.
    When storage takes it, the same range leaves the bucket — so the refusal
    parked the work rather than losing it.
    """

    backend = _ScopeAwareBackend()
    service = AnsichService(backend, flush_interval_ms=10, hostname=_HOSTNAME)
    await service.start()
    task_id = new_id()

    try:
        assert service.host_scope_id == host_scope_id(_HOSTNAME)
        await _charge_one_global_range(service)

        backend.refuse_kinds = {"observability.lost"}
        service.record(_lifecycle(task_id))
        await _wait_for("the lifecycle row to be placed", lambda: "task.created" in backend.kinds())
        # The seam runs inside that same successful write, so by the time the
        # row is placed the refused report has already happened.
        assert service.get_health().unreported_global_lost_range_count == 1
        assert backend.lost_rows() == []

        backend.refuse_kinds = set()
        service.record(_lifecycle(new_id()))
        await _wait_for(
            "the healed collector to report the range",
            lambda: service.get_health().unreported_global_lost_range_count == 0,
        )

        assert len(backend.lost_rows()) == 1
        assert backend.lost_rows()[0].subject_id == host_scope_id(_HOSTNAME)
    finally:
        await service.stop()


@pytest.mark.anyio
async def test_a_mint_that_could_not_be_written_leaves_the_bucket_alone() -> None:
    """RB1⑤ fail-open, and what it costs: the bucket stays, honestly counted.

    A failed mint must not fail ``start()`` — collection is fail-open — and it
    must not leave the drain writing rows against a Scope that was never
    established. ``host_scope_id`` staying ``None`` is the whole mechanism.
    """

    backend = _ScopeAwareBackend()
    backend.refuse_kinds = {"scope.snapshotted"}
    service = AnsichService(backend, flush_interval_ms=10, hostname=_HOSTNAME)
    await service.start()
    task_id = new_id()

    try:
        assert service.get_health().status == "healthy"
        assert service.host_scope_id is None

        await _charge_one_global_range(service)
        service.record(_lifecycle(task_id))
        await _wait_for("the lifecycle row to be placed", lambda: "task.created" in backend.kinds())

        assert service.get_health().unreported_global_lost_range_count == 1
        assert backend.lost_rows() == []
    finally:
        await service.stop()


@pytest.mark.anyio
async def test_a_backend_that_does_not_project_scopes_never_mints() -> None:
    """The in-memory case, stated as the property it actually turns on.

    A backend that keeps Observations but builds no Scope entity cannot give a
    process-wide row a resolvable subject, so nothing is minted and the bucket
    stays. The count is the honest report of that gap, not a bug in it.
    """

    backend = _ScopeAwareBackend()
    backend.projects_scope_entities = False  # type: ignore[misc]
    service = AnsichService(backend, flush_interval_ms=10, hostname=_HOSTNAME)
    await service.start()

    try:
        assert service.host_scope_id is None
        assert backend.written == []

        await _charge_one_global_range(service)
        service.record(_lifecycle(new_id()))
        await _wait_for("the lifecycle row to be placed", lambda: "task.created" in backend.kinds())

        assert service.get_health().unreported_global_lost_range_count == 1
        assert backend.lost_rows() == []
    finally:
        await service.stop()


@pytest.mark.anyio
async def test_a_range_that_can_still_grow_is_left_for_the_next_pass() -> None:
    """The coalescing boundary, one level below the report cursor.

    ``_record_loss`` extends the newest range in place until the reporting pass
    walks past it. A drain that wrote it *before* that point would report
    ``[first, last]`` now and ``[first, last + n]`` later — the same loss
    counted twice, which is exactly what the cursor rule prevents for
    Task-scoped ranges. So the drain is called directly here, while the range is
    still growable, and asserted to write nothing; the ordinary seam, which
    freezes the range first, then writes it.
    """

    backend = _ScopeAwareBackend()
    service = AnsichService(backend, flush_interval_ms=10, hostname=_HOSTNAME)
    await service.start()

    try:
        await _charge_one_global_range(service)
        # Still the newest range and still above the report cursor: it can be
        # extended by the next non-envelope item, so it is not final.
        await service._drain_unreported_global_ranges()
        assert backend.lost_rows() == []
        assert service.get_health().unreported_global_lost_range_count == 1

        service.record(_lifecycle(new_id()))
        await _wait_for(
            "the seam to freeze the range and then report it",
            lambda: service.get_health().unreported_global_lost_range_count == 0,
        )
        assert len(backend.lost_rows()) == 1
    finally:
        await service.stop()
