"""F10-19: a spawned Task's contributions reach its ancestors even when the
backfill's read missed them.

``_backfill_spawn_usage`` reads a descendant's own contributions and writes
ancestor rows; ``_project_usage`` fans a new contribution out over whatever
ancestry is visible when *it* runs. Nothing orders the two. A contribution
whose fan-out ran before the spawn edge was visible, and which commits after
the backfill has already read, reaches no ancestor at all -- and for the
sum-type dimensions (``steps``, ``total_tokens``, ``llm_attempts``,
``tool_calls_*``) nothing ever repairs it, because no later write recomputes a
sum from the descendant's history. ``wall_time_ms`` escapes only because it is
max-type: every heartbeat re-fans the whole mark.

**How the window is staged, and what that staging is worth.** SQLite has one
writer, so the real interleaving -- an open ``_project_usage`` transaction
spanning the spawn transaction's read -- cannot be run here: the spawn
transaction would simply block. What the window *is*, though, is one
transaction whose reads cannot see rows that are not committed yet, so it is
staged as exactly that: every ``_backfill_spawn_usage`` call made **from the
spawn's own session** gets an empty descendant set, so its read matches no row
while the rows are sitting right there, and any call from a later transaction
sees everything. Keying on the session rather than on a call counter is what
lets "just re-read at the end of the same transaction" be tested as the
non-fix it is (see ``task-6-evidence/mutation-reconciliation-trigger.txt``:
that variant is exactly as red as no reconciliation at all). The tests assert
how many rows were hidden, so a fixture that stopped producing contributions
could not pass silently. Everything else -- the edge, the reconciliation job,
the claim, the re-fan -- is the production path unmodified. The lost-update
half that genuinely needs two workers under READ COMMITTED belongs to the
opt-in Postgres tier, same boundary as ``test_rollup_serialization.py``.

Production windows are usually a subset of the descendant's rows rather than
all of them; the repair is the same code either way, and the subset case is
covered by the no-double-count tests below, where every row is already
delivered and the pass must change nothing.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from ansich import AnsichService, ObservationEnvelope, Producer, new_id
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from support.ansich_settle import only_test_driven_assessments

from deerflow.ansich import create_sql_ansich_service
from deerflow.ansich.persistence import sql as ansich_sql
from deerflow.ansich.persistence.models import (
    AnsichObservationRow,
    AnsichProjectionErrorRow,
    AnsichProjectionJobRow,
    AnsichTaskAncestryRow,
    AnsichTaskSpawnRow,
    AnsichTaskUsageRow,
    AnsichUsageContributionRow,
)
from deerflow.persistence.base import Base

_OCCURRED_AT = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)
_PRODUCER = Producer(name="spawn-reconcile-test", version="1", instance_id="test")
_RECONCILE_PROJECTOR = ansich_sql._SPAWN_RECONCILE_PROJECTOR[0]


def _as_utc(value: datetime) -> datetime:
    """SQLite hands timestamps back naive; every comparison here is in UTC."""

    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class _SpawnFixture:
    """One root Task, one Task about to become its child, and their ids."""

    def __init__(self, service: AnsichService, session_factory, ids: dict[str, str]) -> None:
        self.service = service
        self.session_factory = session_factory
        self.root_id = ids["root_id"]
        self.child_id = ids["child_id"]
        self.root_step = ids["root_step"]
        self.root_tool = ids["root_tool"]
        self.child_step = ids["child_step"]
        self.spawn_observation: ObservationEnvelope | None = None

    @property
    def backend(self):
        return self.service._backend

    def spawn_envelope(self) -> ObservationEnvelope:
        return ObservationEnvelope.task_lifecycle(
            kind="task.created",
            task_id=self.child_id,
            source_kind="deerflow_subagent",
            source_id="provider-task-call",
            occurred_at=_OCCURRED_AT + timedelta(seconds=5),
            source_event_id=f"deerflow_subagent:{self.child_id}:task:created",
            attributes={
                "parent_task_id": self.root_id,
                "spawning_step_id": self.root_step,
                "spawning_tool_call_id": self.root_tool,
                "subagent_name": "researcher",
            },
        )

    async def record_spawn(self) -> ObservationEnvelope:
        envelope = self.spawn_envelope()
        self.spawn_observation = envelope
        self.service.record(envelope)
        await self.service.flush_task(self.child_id)
        return envelope

    async def usage_rows(self) -> list[tuple]:
        async with self.session_factory() as session:
            rows = list(
                (
                    await session.execute(
                        select(AnsichTaskUsageRow).order_by(
                            AnsichTaskUsageRow.task_id,
                            AnsichTaskUsageRow.dimension,
                            AnsichTaskUsageRow.aggregation_scope,
                        )
                    )
                ).scalars()
            )
        return [
            (
                row.task_id,
                row.dimension,
                row.aggregation_scope,
                row.value,
                row.as_of.replace(tzinfo=UTC),
                row.complete_through_ingest_seq,
                row.updated_at.replace(tzinfo=UTC),
            )
            for row in rows
        ]

    async def contribution_rows(self) -> list[tuple]:
        async with self.session_factory() as session:
            rows = list(
                (
                    await session.execute(
                        select(AnsichUsageContributionRow).order_by(
                            AnsichUsageContributionRow.aggregate_task_id,
                            AnsichUsageContributionRow.source_task_id,
                            AnsichUsageContributionRow.dimension,
                            AnsichUsageContributionRow.source_obs_id,
                        )
                    )
                ).scalars()
            )
        return [
            (
                row.aggregate_task_id,
                row.source_task_id,
                row.dimension,
                row.source_obs_id,
                row.delta,
            )
            for row in rows
        ]


def _step_started(task_id: str, step_id: str, step_seq: int, occurred_at: datetime) -> ObservationEnvelope:
    return ObservationEnvelope(
        kind="step.started",
        occurred_at=occurred_at,
        task_id=task_id,
        step_id=step_id,
        subject_type="step",
        subject_id=step_id,
        producer=_PRODUCER,
        source_event_id=f"step:{step_id}:started",
        correlation_id=task_id,
        payload={"step_seq": step_seq, "actor_kind": "lead_agent"},
    )


def _tool_issued(task_id: str, step_id: str, tool_call_id: str, occurred_at: datetime) -> ObservationEnvelope:
    return ObservationEnvelope(
        kind="tool.issued",
        occurred_at=occurred_at,
        task_id=task_id,
        step_id=step_id,
        subject_type="tool_call",
        subject_id=tool_call_id,
        producer=_PRODUCER,
        source_event_id=f"tool:{tool_call_id}:issued",
        correlation_id=task_id,
        payload={
            "call_seq": 1,
            "provider_call_id": "provider-task-call",
            "tool_name": "task",
            "args_hash": "a" * 64,
            "args_preview": {},
            "tool_schema_block_id": None,
        },
    )


def _attempt(task_id: str, attempt_id: str, occurred_at: datetime, total_tokens: int) -> tuple[ObservationEnvelope, ...]:
    return (
        ObservationEnvelope(
            kind="llm.requested",
            occurred_at=occurred_at,
            task_id=task_id,
            subject_type="llm_attempt",
            subject_id=attempt_id,
            producer=_PRODUCER,
            source_event_id=f"attempt:{attempt_id}:requested",
            correlation_id=task_id,
            payload={
                "attempt_no": 1,
                "actor_kind": "system_operation",
                "operation_id": new_id(),
                "operation_kind": "other",
            },
        ),
        ObservationEnvelope(
            kind="llm.responded",
            occurred_at=occurred_at + timedelta(seconds=1),
            task_id=task_id,
            subject_type="llm_attempt",
            subject_id=attempt_id,
            producer=_PRODUCER,
            source_event_id=f"attempt:{attempt_id}:responded",
            correlation_id=task_id,
            payload={"attempt_no": 1, "latency_ms": 20, "usage": {"total_tokens": total_tokens}},
        ),
    )


@contextlib.asynccontextmanager
async def _spawn_fixture(tmp_path, name: str) -> AsyncIterator[_SpawnFixture]:
    """A root Task with a ``task`` ToolCall, plus a Task that already has usage.

    The child's own contributions -- one step, one attempt with tokens, one
    heartbeat mark -- are all durable *before* any spawn edge exists, which is
    the state F10-19's window operates on.
    """

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / f'{name}.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(session_factory)
    only_test_driven_assessments(service)
    await service.start()
    ids = {
        "root_id": new_id(),
        "child_id": new_id(),
        "root_step": new_id(),
        "root_tool": new_id(),
        "child_step": new_id(),
    }
    fixture = _SpawnFixture(service, session_factory, ids)
    try:
        service.record_batch(
            (
                ObservationEnvelope.task_lifecycle(
                    kind="task.created",
                    task_id=fixture.root_id,
                    source_kind="deerflow_run",
                    source_id="root-run",
                    occurred_at=_OCCURRED_AT,
                    source_event_id="run:root-run:task:created",
                ),
                _step_started(fixture.root_id, fixture.root_step, 1, _OCCURRED_AT),
                _tool_issued(fixture.root_id, fixture.root_step, fixture.root_tool, _OCCURRED_AT),
                ObservationEnvelope.task_lifecycle(
                    kind="task.created",
                    task_id=fixture.child_id,
                    source_kind="deerflow_run",
                    source_id="child-before-edge",
                    occurred_at=_OCCURRED_AT,
                    source_event_id="run:child-before-edge:task:created",
                ),
                _step_started(fixture.child_id, fixture.child_step, 1, _OCCURRED_AT + timedelta(seconds=1)),
                *_attempt(fixture.child_id, new_id(), _OCCURRED_AT + timedelta(seconds=2), 41),
                ObservationEnvelope.task_heartbeat(
                    task_id=fixture.child_id,
                    run_id="child-run",
                    occurred_at=_OCCURRED_AT + timedelta(seconds=4),
                    elapsed_ms=4_000,
                    worker_id="worker-spawn-reconcile",
                    ownership_epoch="epoch-spawn-reconcile",
                    source_event_id="run:child-run:task:heartbeat:1",
                ),
            )
        )
        await service.flush_task(fixture.root_id)
        await service.flush_task(fixture.child_id)
        yield fixture
    finally:
        await service.stop()
        await engine.dispose()


def _hide_the_descendants_from_the_spawn_transaction(monkeypatch) -> dict[str, int]:
    """Make the spawn transaction's fan-out read match nothing (F10-19's window).

    The empty descendant set is the read's own ``IN (...)`` predicate going
    empty, so the rest of the function -- the sorted ancestor traversal, the
    ``changed`` fan-out -- still runs exactly as it does in production; only the
    rows it copies are the ones a concurrent, not-yet-committed
    ``_project_usage`` would have withheld.

    The blinding is keyed on the **session**, not on a call count, because that
    is what the window actually is: a transaction whose reads cannot see rows
    that are not committed yet. Every call inside the spawn's own transaction is
    blinded and every call from a later one sees everything -- which is what
    makes "just re-read at the end of the same transaction" testable as the
    non-fix it is, instead of being rescued by a counter.

    ``skipped`` records how many rows were really there at that moment, so this
    staging cannot silently degrade into "there was nothing to lose".
    """

    original = ansich_sql.SqlAnsichBackend._backfill_spawn_usage
    state: dict[str, int] = {"calls": 0, "skipped": 0}
    blinded_session: list[object] = []

    async def blinded(self, session, *, ancestor_task_ids, descendant_task_ids, updated_at):
        if not blinded_session or blinded_session[0] is session:
            if not blinded_session:
                blinded_session.append(session)
                state["skipped"] = len(
                    list(
                        (
                            await session.execute(
                                select(AnsichUsageContributionRow.source_obs_id).where(
                                    AnsichUsageContributionRow.aggregate_task_id == AnsichUsageContributionRow.source_task_id,
                                    AnsichUsageContributionRow.source_task_id.in_(descendant_task_ids),
                                )
                            )
                        ).scalars()
                    )
                )
            state["calls"] += 1
            descendant_task_ids = ()
        return await original(
            self,
            session,
            ancestor_task_ids=ancestor_task_ids,
            descendant_task_ids=descendant_task_ids,
            updated_at=updated_at,
        )

    monkeypatch.setattr(ansich_sql.SqlAnsichBackend, "_backfill_spawn_usage", blinded)
    return state


# --------------------------------------------------------------------------
# (a) The window itself
# --------------------------------------------------------------------------


@pytest.mark.anyio
async def test_a_contribution_the_spawn_backfill_read_missed_still_reaches_its_ancestors(tmp_path, monkeypatch):
    """The permanent-loss window, closed by the follow-up reconciliation.

    Before the reconciliation existed this was terminal for the sum types: the
    root's inclusive ``steps``/``total_tokens``/``llm_attempts`` never learned
    about the child at all, and no later Observation would have taught them.
    """

    async with _spawn_fixture(tmp_path, "spawn-window") as fixture:
        hidden = _hide_the_descendants_from_the_spawn_transaction(monkeypatch)
        await fixture.record_spawn()

        root_usage = await fixture.service.get_task_usage(fixture.root_id)
        child_usage = await fixture.service.get_task_usage(fixture.child_id)
        async with fixture.session_factory() as session:
            reconcile_jobs = list(
                (
                    await session.execute(
                        select(
                            AnsichProjectionJobRow.projector_name,
                            AnsichProjectionJobRow.status,
                        ).where(AnsichProjectionJobRow.projector_name == _RECONCILE_PROJECTOR)
                    )
                ).all()
            )

    # The staging really did hide live rows rather than an empty table. This
    # comes first so a fixture that stopped producing usage reports itself
    # rather than passing the assertions below by vacuity.
    assert hidden["calls"] >= 1
    assert hidden["skipped"] >= 4, hidden

    root_inclusive = {item.dimension: item.value for item in root_usage.inclusive}
    child_local = {item.dimension: item.value for item in child_usage.local}
    assert child_local == {
        "total_tokens": 41,
        "llm_attempts": 1,
        "steps": 1,
        "wall_time_ms": 4_000,
    }
    # The load-bearing assertion, and the one a missing reconciliation makes
    # red: without it the root's inclusive read never learns about the child at
    # all, and no later Observation would have taught it.
    assert root_inclusive == {
        "steps": 2,
        "tool_calls_issued": 1,
        "total_tokens": 41,
        "llm_attempts": 1,
        "wall_time_ms": 4_000,
    }
    assert {item.dimension: item.value for item in root_usage.local} == {
        "steps": 1,
        "tool_calls_issued": 1,
    }
    # Exactly one reconciliation job, and it settled.
    assert reconcile_jobs == [(_RECONCILE_PROJECTOR, "completed")]


@pytest.mark.anyio
async def test_usage_recorded_after_the_reconciled_edge_still_fans_out_normally(tmp_path, monkeypatch):
    """The repair must not consume the ordinary path that follows it."""

    async with _spawn_fixture(tmp_path, "spawn-window-then-normal") as fixture:
        _hide_the_descendants_from_the_spawn_transaction(monkeypatch)
        await fixture.record_spawn()
        fixture.service.record(
            _step_started(
                fixture.child_id,
                new_id(),
                2,
                _OCCURRED_AT + timedelta(seconds=8),
            )
        )
        await fixture.service.flush_task(fixture.child_id)
        root_usage = await fixture.service.get_task_usage(fixture.root_id)

    root_inclusive = {item.dimension: item.value for item in root_usage.inclusive}
    # One root step, the child's reconciled step, and the child's later step.
    assert root_inclusive["steps"] == 3
    assert root_inclusive["total_tokens"] == 41


# --------------------------------------------------------------------------
# (b) No double count
# --------------------------------------------------------------------------


@pytest.mark.anyio
async def test_reconciling_an_already_delivered_spawn_changes_nothing(tmp_path):
    """An ordinary spawn, reconciled again, is byte-identical.

    The second pass is handed a *later* ``recorded_at`` on purpose: every
    summary row this pass touched would take that timestamp into
    ``updated_at``, so "changed nothing" is checked against a value that would
    move if a single contribution had been counted twice, rather than against a
    write that happens to be idempotent in its value.
    """

    async with _spawn_fixture(tmp_path, "spawn-idempotent") as fixture:
        spawn = await fixture.record_spawn()
        before_usage = await fixture.usage_rows()
        before_contributions = await fixture.contribution_rows()

        replay = spawn.model_copy(update={"recorded_at": spawn.recorded_at + timedelta(hours=1)})
        async with fixture.session_factory() as session, session.begin():
            await fixture.backend._reconcile_spawn_usage(session, replay)

        after_usage = await fixture.usage_rows()
        after_contributions = await fixture.contribution_rows()

    # The ordinary path already delivered everything, so the fixture is a real
    # subject rather than an empty one.
    assert any(row[0] == fixture.root_id and row[2] == "inclusive" and row[1] == "total_tokens" for row in before_usage), before_usage
    assert before_contributions == after_contributions
    assert before_usage == after_usage


@pytest.mark.anyio
async def test_a_second_reconciliation_after_a_repair_changes_nothing(tmp_path, monkeypatch):
    """The repaired state is a fixed point too, not only the ordinary one."""

    async with _spawn_fixture(tmp_path, "spawn-repair-fixed-point") as fixture:
        _hide_the_descendants_from_the_spawn_transaction(monkeypatch)
        spawn = await fixture.record_spawn()
        before_usage = await fixture.usage_rows()
        before_contributions = await fixture.contribution_rows()

        replay = spawn.model_copy(update={"recorded_at": spawn.recorded_at + timedelta(hours=1)})
        async with fixture.session_factory() as session, session.begin():
            await fixture.backend._reconcile_spawn_usage(session, replay)

        after_usage = await fixture.usage_rows()
        after_contributions = await fixture.contribution_rows()

    assert before_contributions == after_contributions
    assert before_usage == after_usage


# --------------------------------------------------------------------------
# (c) wall_time stays one high-water row per (aggregate, source)
# --------------------------------------------------------------------------


@pytest.mark.anyio
async def test_reconciliation_keeps_one_high_water_wall_time_row_per_source(tmp_path, monkeypatch):
    """``wall_time_ms`` is max-type and must not gain a row per re-fan.

    It is the one dimension that could already self-heal (the next heartbeat
    re-fans the whole mark), so the risk this pass adds is the opposite one:
    a second durable row per source, which would make the summary's
    ``sum(max per source)`` count the same elapsed time twice.
    """

    async with _spawn_fixture(tmp_path, "spawn-wall-time") as fixture:
        _hide_the_descendants_from_the_spawn_transaction(monkeypatch)
        spawn = await fixture.record_spawn()

        # A later tick raises the mark; the reconciliation must replace rather
        # than append, exactly as the ordinary fan-out does.
        fixture.service.record(
            ObservationEnvelope.task_heartbeat(
                task_id=fixture.child_id,
                run_id="child-run",
                occurred_at=_OCCURRED_AT + timedelta(seconds=9),
                elapsed_ms=9_000,
                worker_id="worker-spawn-reconcile",
                ownership_epoch="epoch-spawn-reconcile",
                source_event_id="run:child-run:task:heartbeat:2",
            )
        )
        await fixture.service.flush_task(fixture.child_id)

        replay = spawn.model_copy(update={"recorded_at": spawn.recorded_at + timedelta(hours=1)})
        async with fixture.session_factory() as session, session.begin():
            await fixture.backend._reconcile_spawn_usage(session, replay)

        wall_time = [row for row in await fixture.contribution_rows() if row[2] == "wall_time_ms"]
        root_usage = await fixture.service.get_task_usage(fixture.root_id)

    # Exactly two rows -- one per (aggregate, source) -- both at the raised
    # mark. A re-fan that appended instead of replacing would show three.
    assert sorted((aggregate, source, delta) for aggregate, source, _dimension, _obs, delta in wall_time) == sorted(
        [
            (fixture.child_id, fixture.child_id, 9_000),
            (fixture.root_id, fixture.child_id, 9_000),
        ]
    )
    assert {item.dimension: item.value for item in root_usage.inclusive}["wall_time_ms"] == 9_000


# --------------------------------------------------------------------------
# (d) The traversal handed down stays worker-independent
# --------------------------------------------------------------------------


@pytest.mark.anyio
async def test_reconciliation_hands_the_backfill_a_sorted_ancestor_traversal(tmp_path, monkeypatch):
    """The re-fan reuses T5's ordering discipline instead of a new order.

    ``_backfill_spawn_usage`` sorts internally, so this pins the input rather
    than the lock order it already owns: the ancestry read the reconciliation
    adds must not reintroduce storage order as an input to anything. The
    ancestors below are inserted deliberately unsorted, which is what an
    unordered SQLite select returns.
    """

    async with _spawn_fixture(tmp_path, "spawn-reconcile-order") as fixture:
        spawn = await fixture.record_spawn()
        # No matching ``ansich_tasks`` rows: this suite's engines run without
        # ``PRAGMA foreign_keys`` and the traversal reads only the closure.
        async with fixture.session_factory() as session, session.begin():
            for depth, ancestor_task_id in enumerate(("zzz-ancestor", "aaa-ancestor", "mmm-ancestor"), start=2):
                session.add(
                    AnsichTaskAncestryRow(
                        ancestor_task_id=ancestor_task_id,
                        descendant_task_id=fixture.child_id,
                        depth=depth,
                        established_obs_id=new_id(),
                    )
                )

        received: list[tuple[str, ...]] = []
        original = ansich_sql.SqlAnsichBackend._backfill_spawn_usage

        async def recording(self, session, *, ancestor_task_ids, descendant_task_ids, updated_at):
            received.append(tuple(ancestor_task_ids))
            return await original(
                self,
                session,
                ancestor_task_ids=ancestor_task_ids,
                descendant_task_ids=descendant_task_ids,
                updated_at=updated_at,
            )

        monkeypatch.setattr(ansich_sql.SqlAnsichBackend, "_backfill_spawn_usage", recording)
        async with fixture.session_factory() as session, session.begin():
            await fixture.backend._reconcile_spawn_usage(session, spawn)

    assert len(received) == 1
    assert len(received[0]) == 4, received
    assert list(received[0]) == sorted(received[0]), received


# --------------------------------------------------------------------------
# (e) Replay / rebuild parity
# --------------------------------------------------------------------------


@pytest.mark.anyio
async def test_rebuild_re_derives_the_same_read_model_the_reconciliation_repaired(tmp_path, monkeypatch):
    """A rebuild re-derives everything, so it is the independent answer.

    It also exercises the reconciliation job's own replay: ``rebuild`` re-pends
    every job including this one, ``_project_task_spawn`` runs again and must
    not enqueue a second, and the pass itself must stay a no-op over the
    already-complete closure.
    """

    async with _spawn_fixture(tmp_path, "spawn-rebuild") as fixture:
        _hide_the_descendants_from_the_spawn_transaction(monkeypatch)
        await fixture.record_spawn()
        repaired = await fixture.service.get_task_usage(fixture.root_id)
        repaired_contributions = await fixture.contribution_rows()

        outcome = await fixture.service.rebuild_projections()
        rebuilt = await fixture.service.get_task_usage(fixture.root_id)
        rebuilt_contributions = await fixture.contribution_rows()
        async with fixture.session_factory() as session:
            reconcile_jobs = list((await session.execute(select(AnsichProjectionJobRow.status).where(AnsichProjectionJobRow.projector_name == _RECONCILE_PROJECTOR))).scalars())

    assert outcome.unsettled == 0
    assert reconcile_jobs == ["completed"]
    assert repaired_contributions == rebuilt_contributions
    assert {item.dimension: item.value for item in rebuilt.inclusive} == {item.dimension: item.value for item in repaired.inclusive}
    assert {item.dimension: item.value for item in rebuilt.inclusive}["steps"] == 2


@pytest.mark.anyio
async def test_a_root_task_creation_leaves_no_reconciliation_job(tmp_path):
    """The job is per established spawn edge, not per ``task.created``."""

    async with _spawn_fixture(tmp_path, "spawn-root-only") as fixture:
        async with fixture.session_factory() as session:
            before = await session.scalar(select(AnsichProjectionJobRow.job_id).where(AnsichProjectionJobRow.projector_name == _RECONCILE_PROJECTOR).limit(1))
        await fixture.record_spawn()
        async with fixture.session_factory() as session:
            after = list((await session.execute(select(AnsichProjectionJobRow.obs_id).where(AnsichProjectionJobRow.projector_name == _RECONCILE_PROJECTOR))).scalars())

    assert before is None
    assert after == [fixture.spawn_observation.obs_id]


@pytest.mark.anyio
async def test_rebuild_mints_a_reconciliation_for_an_edge_that_has_none(tmp_path):
    """The pre-fix-edge recovery path, and the precondition it rests on.

    An ``ansich_task_spawns`` row written before F10-19's fix existed carries no
    reconciliation job, and ``_project_task_spawn``'s early return would not
    mint one for it either. The claim that ``rebuild_projections()`` recovers
    those edges is true for a reason worth pinning: rebuild DELETES the spawn
    and ancestry tables before replaying, so the replayed projection finds no
    existing edge and takes the full path. Narrowing that delete list would make
    the early return reachable on replay and leave such an edge
    reconciliation-less forever, with nothing else to notice.

    The job row is deleted here rather than a database being aged, which is the
    same state: an edge whose reconciliation does not exist.
    """

    async with _spawn_fixture(tmp_path, "spawn-rebuild-mint") as fixture:
        spawn = await fixture.record_spawn()
        async with fixture.session_factory() as session, session.begin():
            await session.execute(delete(AnsichProjectionJobRow).where(AnsichProjectionJobRow.projector_name == _RECONCILE_PROJECTOR))
        async with fixture.session_factory() as session:
            before = list((await session.execute(select(AnsichProjectionJobRow.obs_id).where(AnsichProjectionJobRow.projector_name == _RECONCILE_PROJECTOR))).scalars())
            # The precondition, read as state rather than asserted about code.
            spawn_rows_before_rebuild = await session.scalar(select(func.count()).select_from(AnsichTaskSpawnRow))

        outcome = await fixture.service.rebuild_projections()

        async with fixture.session_factory() as session:
            after = list((await session.execute(select(AnsichProjectionJobRow.obs_id, AnsichProjectionJobRow.status).where(AnsichProjectionJobRow.projector_name == _RECONCILE_PROJECTOR))).scalars())
            minted = list(
                (
                    await session.execute(
                        select(
                            AnsichProjectionJobRow.obs_id,
                            AnsichProjectionJobRow.status,
                        ).where(AnsichProjectionJobRow.projector_name == _RECONCILE_PROJECTOR)
                    )
                ).all()
            )
        root_usage = await fixture.service.get_task_usage(fixture.root_id)

    assert spawn_rows_before_rebuild == 1
    assert before == []
    assert outcome.unsettled == 0
    assert minted == [(spawn.obs_id, "completed")], after
    assert {item.dimension: item.value for item in root_usage.inclusive}["steps"] == 2


# --------------------------------------------------------------------------
# The in-flight gate, and the claim invariant it rests on
# --------------------------------------------------------------------------


async def _dress_a_usage_job_as_processing(fixture: _SpawnFixture, *, lease_expires_at: datetime) -> str:
    """Give one of the child's real ``task-usage`` jobs a ``processing`` claim.

    Nothing on SQLite can hold a second worker's transaction open across this
    one, so the *state that worker's claim leaves behind* is what gets staged:
    a committed ``processing`` row with a lease. That is exactly what the gate
    reads, and it is a real job for a real usage Observation of a real
    descendant, not a synthetic row.
    """

    async with fixture.session_factory() as session, session.begin():
        job_id = await session.scalar(
            select(AnsichProjectionJobRow.job_id)
            .join(
                AnsichObservationRow,
                AnsichObservationRow.obs_id == AnsichProjectionJobRow.obs_id,
            )
            .where(
                AnsichProjectionJobRow.projector_name == "task-usage",
                AnsichObservationRow.task_id == fixture.child_id,
            )
            .limit(1)
        )
        assert job_id is not None, "the fixture must give the child real usage jobs"
        await session.execute(update(AnsichProjectionJobRow).where(AnsichProjectionJobRow.job_id == job_id).values(status="processing", lease_owner="peer-worker", lease_expires_at=lease_expires_at))
    return job_id


async def _re_arm_the_reconciliation(fixture: _SpawnFixture) -> str:
    """Put the (already completed) reconciliation job back on the queue.

    ``attempts`` is reset to zero so "the attempt came back" is readable as a
    value rather than as a delta, and ``lease_generation`` is deliberately left
    alone — it is monotonic for the row's lifetime, exactly as an operator retry
    leaves it.
    """

    async with fixture.session_factory() as session, session.begin():
        job_id = await session.scalar(select(AnsichProjectionJobRow.job_id).where(AnsichProjectionJobRow.projector_name == _RECONCILE_PROJECTOR).limit(1))
        assert job_id is not None, "the spawn must have left a reconciliation job"
        await session.execute(
            update(AnsichProjectionJobRow)
            .where(AnsichProjectionJobRow.job_id == job_id)
            .values(
                status="pending",
                attempts=0,
                available_at=datetime.now(UTC) - timedelta(seconds=1),
                dependency_pending_since=None,
                lease_owner=None,
                lease_expires_at=None,
                last_error=None,
            )
        )
    return job_id


@pytest.mark.anyio
async def test_a_live_usage_claim_defers_the_reconciliation_without_charging_it(tmp_path):
    """The gate's wait branch: deferred, attempt returned, no error row.

    A live-leased ``task-usage`` claim is a fan-out that already read the
    pre-edge ancestry and has not committed, so re-fanning now would read past
    it exactly as the backfill did. The wait is a replay-safe dependency, which
    is a specific contract and not merely "it raises": the attempt goes back,
    the status stays ``pending`` (never ``retry``, which would claim an attempt
    was spent), and no durable error row is written.
    """

    async with _spawn_fixture(tmp_path, "spawn-gate-live") as fixture:
        await fixture.record_spawn()
        backend = fixture.backend
        # The service's own projector loop would keep re-claiming the re-armed
        # job behind the assertions; this test owns the claim schedule.
        await fixture.service.stop()
        await _dress_a_usage_job_as_processing(fixture, lease_expires_at=datetime.now(UTC) + timedelta(seconds=60))
        reconcile_job_id = await _re_arm_the_reconciliation(fixture)

        await backend.project_pending()

        async with fixture.session_factory() as session:
            job = await session.get(AnsichProjectionJobRow, reconcile_job_id)
            state = (job.status, job.attempts, job.dependency_pending_since is not None, job.lease_owner)
            available_at = _as_utc(job.available_at)
            last_error = job.last_error
            error_rows = list((await session.execute(select(AnsichProjectionErrorRow.error_id).where(AnsichProjectionErrorRow.job_id == reconcile_job_id))).scalars())

    assert state == ("pending", 0, True, None), "a dependency wait returns its attempt and keeps `pending`"
    assert available_at > datetime.now(UTC) - timedelta(seconds=1)
    assert "waiting for an in-flight usage projection" in (last_error or "")
    assert error_rows == [], "a replay-safe wait is not a durable failure"


@pytest.mark.anyio
async def test_an_expired_usage_claim_does_not_defer_the_reconciliation(tmp_path, monkeypatch):
    """The gate's other branch, and the honest edge of its domain.

    Waiting on an expired lease would be an unbounded wait on a worker that may
    be gone, and would not close the window anyway — see the DOMAIN note in
    ``_reconcile_spawn_usage``. So the pass proceeds, and the repair it owes the
    ancestor lands. Called directly rather than through ``project_pending``
    because an expired ``processing`` row is itself claimable: the loop would
    re-run that usage projection first and repair the ancestor by that route,
    which would prove nothing about this branch.
    """

    async with _spawn_fixture(tmp_path, "spawn-gate-expired") as fixture:
        _hide_the_descendants_from_the_spawn_transaction(monkeypatch)
        spawn = await fixture.record_spawn()
        backend = fixture.backend
        await fixture.service.stop()
        await _dress_a_usage_job_as_processing(fixture, lease_expires_at=datetime.now(UTC) - timedelta(seconds=60))

        async with fixture.session_factory() as session, session.begin():
            await backend._reconcile_spawn_usage(session, spawn)

        root_usage = await fixture.service.get_task_usage(fixture.root_id)

    assert {item.dimension: item.value for item in root_usage.inclusive}["steps"] == 2
    assert {item.dimension: item.value for item in root_usage.inclusive}["total_tokens"] == 41


@pytest.mark.anyio
async def test_a_claim_is_committed_before_its_projection_work_begins(tmp_path, monkeypatch):
    """The invariant the whole gate rests on, pinned where it can be seen.

    ``_reconcile_spawn_usage`` reads job rows to decide whether a peer's usage
    fan-out is in flight. That is only informative because the claim commits
    ``processing`` in its **own** transaction before the work starts, and the
    completion commits with the projection — so "no live claim" really does mean
    "every such contribution is already durable". Merge the claim into the work
    transaction and the gate still runs, still finds nothing, and silently stops
    covering anything.

    A **separate session** is what makes this observable: it can only see
    committed rows, so reading ``processing`` with a live lease from inside the
    work is the claim's durability, not its intent.
    """

    async with _spawn_fixture(tmp_path, "spawn-claim-invariant") as fixture:
        observed: list[tuple[str, bool]] = []
        original = ansich_sql.SqlAnsichBackend._project_usage

        async def observing(self, session, observation, *, ingest_seq):
            if not observed:
                async with self._session_factory() as probe:
                    row = (
                        await probe.execute(
                            select(
                                AnsichProjectionJobRow.status,
                                AnsichProjectionJobRow.lease_expires_at,
                            ).where(
                                AnsichProjectionJobRow.obs_id == observation.obs_id,
                                AnsichProjectionJobRow.projector_name == "task-usage",
                            )
                        )
                    ).first()
                observed.append((row.status, _as_utc(row.lease_expires_at) > datetime.now(UTC)))
            return await original(self, session, observation, ingest_seq=ingest_seq)

        monkeypatch.setattr(ansich_sql.SqlAnsichBackend, "_project_usage", observing)
        fixture.service.record(_step_started(fixture.child_id, new_id(), 9, _OCCURRED_AT + timedelta(seconds=20)))
        await fixture.service.flush_task(fixture.child_id)

    assert observed == [("processing", True)], "a projection's own claim must already be durable when its work starts"
