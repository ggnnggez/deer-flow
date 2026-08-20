"""The four read-modify-write rollups lock their target before reading inputs.

F10-6 and F10-20 are one hazard wearing four hats: ``_refresh_behavior_belief``
(a rollup over sibling assessments), ``_refresh_active_task_read_model``,
``_project_budget`` and ``_refresh_usage_summary`` each read a set of rows,
reduce it, and write one aggregate row -- while sibling jobs that separate
leased workers claim concurrently (``skip_locked``) do the same thing to the
same aggregate. ``_recompute_release_quality_stats`` is the reference
implementation and its comment already says why *reading first and locking
second* leaves exactly the same window open.

What this module can and cannot prove, stated up front:

* The **order** of statements -- lock before read -- is a structural property
  of the code and is pinned here by recording the ORM statement stream. That
  works on SQLite because a ``SELECT ... FOR UPDATE`` carries its
  ``_for_update_arg`` in the statement object regardless of the dialect that
  renders it (SQLite renders nothing; it has one writer anyway).
* The **lost update** the order prevents needs two workers genuinely
  interleaving under READ COMMITTED. That is a real PostgreSQL server's
  property and lives in the opt-in two-worker tier
  (``tests/integration/test_postgres_multiworker.py``, T9), which is where the
  pre-fix shape is proven red.
* The **first-writer race** likewise cannot happen for real on SQLite -- one
  writer at a time means two inserts are never both in flight -- so the window
  is *injected*, the same discipline ``tests/ansich/test_lease_cas.py`` uses
  when it injects lease expiry as a past-dated timestamp rather than waiting
  for a clock.

The behavioural regression at the top is a clamp, not a discovery: the whole
point of this change is that single-worker output is unchanged, so it is green
on arrival. Its teeth come from running it against a deliberately broken
variant.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from ansich import AnsichService, ObservationEnvelope, Producer, new_id
from sqlalchemy import event, select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session
from support.ansich_settle import only_test_driven_assessments

from deerflow.ansich import create_sql_ansich_service
from deerflow.ansich.persistence import sql as ansich_sql
from deerflow.ansich.persistence.models import (
    AnsichActiveTaskReadModelRow,
    AnsichBeliefAssertionRow,
    AnsichCurrentBeliefRow,
    AnsichEntityRow,
    AnsichTaskAncestryRow,
    AnsichTaskBudgetRow,
    AnsichTaskUsageRow,
)
from deerflow.persistence.base import Base

# Past-dated on purpose, same clock discipline as test_lease_cas.py: nothing
# here may be settled between a fixture timestamp and the real clock.
_OCCURRED_AT = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
_ASSESSED_AT = _OCCURRED_AT + timedelta(seconds=30)
_PRODUCER = Producer(name="rollup-serialization-test", version="1", instance_id="test")


# --------------------------------------------------------------------------
# Statement recorder (shared by every shape pin below)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class _Statement:
    """One ORM execution: its SQLite text plus whether it asked for a lock."""

    sql: str
    for_update: bool

    def touches(self, table: str) -> bool:
        return table in self.sql


@contextlib.contextmanager
def _record_statements() -> Iterator[list[_Statement]]:
    """Record every ORM statement in execution order.

    ``do_orm_execute`` is the one hook that sees all three entry points the
    backend uses -- ``session.execute``, ``session.get`` and ``session.scalar``
    (the latter two do not route through ``AsyncSession.execute``) -- and it
    hands over the statement *object*, which is what carries ``FOR UPDATE`` on
    a dialect that does not render it.
    """

    recorded: list[_Statement] = []

    def _capture(state: object) -> None:
        statement = state.statement  # type: ignore[attr-defined]
        try:
            text = " ".join(str(statement.compile(dialect=sqlite.dialect())).split()).lower()
        except Exception:  # pragma: no cover - defensive, a statement we cannot render
            text = repr(statement).lower()
        recorded.append(
            _Statement(
                sql=text,
                for_update=getattr(statement, "_for_update_arg", None) is not None,
            )
        )

    event.listen(Session, "do_orm_execute", _capture)
    try:
        yield recorded
    finally:
        event.remove(Session, "do_orm_execute", _capture)


def _index_of_lock(recorded: list[_Statement], table: str) -> int:
    for index, statement in enumerate(recorded):
        if statement.for_update and statement.touches(table):
            return index
    raise AssertionError(f"no FOR UPDATE statement against {table} in {[item.sql for item in recorded]}")


def _index_of_read(recorded: list[_Statement], table: str) -> int:
    for index, statement in enumerate(recorded):
        if statement.touches(table) and not statement.for_update:
            return index
    raise AssertionError(f"no unlocked read of {table} in {[item.sql for item in recorded]}")


def _index_of_first_touch(recorded: list[_Statement], table: str) -> int:
    for index, statement in enumerate(recorded):
        if statement.touches(table):
            return index
    raise AssertionError(f"nothing touched {table} in {[item.sql for item in recorded]}")


def _lock_missing_once(monkeypatch: pytest.MonkeyPatch, table: str) -> dict[str, int]:
    """Make the target-row lock miss once, as a not-yet-existing row does.

    This is the injected half of the first-writer race. SQLite serializes
    writers, so "two workers both found no row and both reached the insert" is
    not a state its engine can be driven into; what the production code has to
    survive is exactly the state this leaves behind -- the lock found nothing,
    and by the time the insert runs a peer's row is committed. Injecting it is
    the same move ``test_lease_cas.py`` makes for lease expiry.
    """

    original = ansich_sql._lock_rollup_targets
    state = {"remaining": 1, "calls": 0, "missed": 0}

    async def _patched(session: object, statement: object) -> list:
        state["calls"] += 1
        text = str(statement.compile(dialect=sqlite.dialect())).lower()  # type: ignore[attr-defined]
        if state["remaining"] and table in text:
            state["remaining"] -= 1
            state["missed"] += 1
            return []
        return await original(session, statement)  # type: ignore[arg-type]

    monkeypatch.setattr(ansich_sql, "_lock_rollup_targets", _patched)
    return state


# --------------------------------------------------------------------------
# Representative fixture: one running Task that reaches all four rollups
# --------------------------------------------------------------------------


def _budget_observation(task_id: str) -> ObservationEnvelope:
    return ObservationEnvelope.budget_configured(
        task_id=task_id,
        run_id="run-rollup-serialization",
        occurred_at=_OCCURRED_AT,
        dimension="total_tokens",
        aggregation_scope="local",
        warning_limit=80,
        hard_limit=100,
        enforcement=True,
        source_kind="release_default",
        requested_value=None,
        effective_value=100,
        source_event_id="run:run-rollup-serialization:budget:total_tokens",
    )


@contextlib.asynccontextmanager
async def _representative_state(tmp_path, name: str) -> AsyncIterator[tuple[AnsichService, str, ObservationEnvelope]]:
    """A running Task carrying a budget, usage contributions and assessments.

    One fixture reaches all four rollups: ``_project_budget`` on the budget
    Observation, ``_refresh_usage_summary`` through the usage projector, and
    then ``_refresh_behavior_belief`` plus ``_refresh_active_task_read_model``
    through the operations assessment the test drives itself.
    """

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / f'{name}.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(
        session_factory,
        operations_assessment_interval_ms=60_000,
    )
    # Which assessment ran is exactly what the behavior Belief below asserts
    # on, and the projector loop assesses on a wall clock (F10-10).
    only_test_driven_assessments(service)
    await service.start()
    task_id = new_id()
    attempt_id = new_id()
    budget = _budget_observation(task_id)
    try:
        service.record_batch(
            (
                ObservationEnvelope.task_lifecycle(
                    kind="task.created",
                    task_id=task_id,
                    source_kind="deerflow_run",
                    source_id="run-rollup-serialization",
                    occurred_at=_OCCURRED_AT,
                    source_event_id="run:run-rollup-serialization:task:created",
                ),
                ObservationEnvelope.task_lifecycle(
                    kind="task.started",
                    task_id=task_id,
                    source_kind="deerflow_run",
                    source_id="run-rollup-serialization",
                    occurred_at=_OCCURRED_AT,
                    source_event_id="run:run-rollup-serialization:task:started",
                ),
                budget,
                ObservationEnvelope(
                    kind="llm.requested",
                    occurred_at=_OCCURRED_AT + timedelta(seconds=1),
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
                    occurred_at=_OCCURRED_AT + timedelta(seconds=2),
                    task_id=task_id,
                    subject_type="llm_attempt",
                    subject_id=attempt_id,
                    producer=_PRODUCER,
                    source_event_id=f"attempt:{attempt_id}:responded",
                    correlation_id=task_id,
                    payload={
                        "attempt_no": 1,
                        "latency_ms": 20,
                        "usage": {"total_tokens": 41},
                    },
                ),
            )
        )
        await service.flush_task(task_id)
        await service.assess_operations(now=_ASSESSED_AT)
        yield service, task_id, budget
    finally:
        with contextlib.suppress(Exception):
            await service.stop()
        await engine.dispose()


# --------------------------------------------------------------------------
# (a) Behavioural regression: the locking discipline changes no row
# --------------------------------------------------------------------------


@pytest.mark.anyio
async def test_the_four_rollups_write_the_same_rows_they_wrote_before_locking(tmp_path):
    """A clamp on the four rollups' output, driven through the public paths.

    This is green on arrival by construction -- the change is a locking and
    upsert discipline, not a semantic one -- so it earns its place by failing
    if any of the four rewrites drifts. Deliberately excluded:
    ``projection_lag_ms`` (derived from the wall clock) and
    ``projection_watermark``, both of which T10/RB8 replaces with DB-derived
    numbers.
    """

    async with _representative_state(tmp_path, "rollup-regression") as (service, task_id, budget):
        session_factory = service._backend._session_factory
        async with session_factory() as session:
            budgets = list((await session.execute(select(AnsichTaskBudgetRow).where(AnsichTaskBudgetRow.task_id == task_id))).scalars())
            usage_rows = list((await session.execute(select(AnsichTaskUsageRow).where(AnsichTaskUsageRow.task_id == task_id).order_by(AnsichTaskUsageRow.dimension, AnsichTaskUsageRow.aggregation_scope))).scalars())
            behavior = await session.scalar(
                select(AnsichBeliefAssertionRow)
                .join(
                    AnsichCurrentBeliefRow,
                    AnsichCurrentBeliefRow.assertion_id == AnsichBeliefAssertionRow.assertion_id,
                )
                .where(
                    AnsichCurrentBeliefRow.subject_id == task_id,
                    AnsichCurrentBeliefRow.field_name == "behavior",
                )
            )
            read_model = await session.get(AnsichActiveTaskReadModelRow, task_id)

    # _project_budget
    assert [(row.dimension, row.aggregation_scope, row.warning_limit, row.hard_limit, row.enforcement, row.source_kind, row.requested_value, row.effective_value) for row in budgets] == [
        ("total_tokens", "local", 80, 100, True, "release_default", None, 100),
    ]

    # _refresh_usage_summary
    assert [(row.dimension, row.aggregation_scope, row.value) for row in usage_rows] == [
        ("llm_attempts", "inclusive", 1),
        ("llm_attempts", "local", 1),
        ("total_tokens", "inclusive", 41),
        ("total_tokens", "local", 41),
    ]
    total_local = next(row for row in usage_rows if row.dimension == "total_tokens" and row.aggregation_scope == "local")
    assert total_local.as_of.replace(tzinfo=UTC) == _OCCURRED_AT + timedelta(seconds=2)
    assert total_local.complete_through_ingest_seq > 0

    # _refresh_behavior_belief
    assert behavior is not None
    assert behavior.assessor_name == "behavior-aggregate"
    assert behavior.value_json["value"] == "unassessed"
    assert behavior.value_json["reason"] == "no_runaway_signal"
    assert behavior.value_json["signals"] == []
    assert behavior.value_json["shadow"] is False

    # _refresh_active_task_read_model
    assert read_model is not None
    assert read_model.run_id == "run-rollup-serialization"
    assert read_model.source_kind == "deerflow_run"
    assert read_model.control_value == "running"
    assert read_model.budget_status == "within"
    assert read_model.observability_status == "healthy"
    assert read_model.duration_ms == 30_000
    assert read_model.updated_at.replace(tzinfo=UTC) == _ASSESSED_AT
    assert read_model.last_evidence_at.replace(tzinfo=UTC) == _OCCURRED_AT + timedelta(seconds=2)
    assert [(item["dimension"], item["value"]) for item in read_model.usage_json["local"]] == [
        ("total_tokens", 41),
        ("llm_attempts", 1),
    ]
    assert isinstance(read_model.projection_lag_ms, int) and read_model.projection_lag_ms >= 0


# --------------------------------------------------------------------------
# (b) Shape pins: the FOR UPDATE lands before the inputs are read
# --------------------------------------------------------------------------


@pytest.mark.anyio
async def test_behavior_belief_locks_the_aggregate_before_reading_its_signals(tmp_path):
    async with _representative_state(tmp_path, "rollup-shape-behavior") as (service, task_id, budget):
        backend = service._backend
        await service.stop()  # silence the projector loop's own statements
        with _record_statements() as recorded:
            async with backend._session_factory() as session, session.begin():
                await backend._refresh_behavior_belief(session, task_id=task_id, now=_ASSESSED_AT)

    lock_index = _index_of_lock(recorded, "ansich_current_beliefs")
    assert lock_index == 0, [item.sql for item in recorded]
    # The inputs are the sibling `behavior_signal:*` Beliefs, read through a
    # join onto their assertions -- which is what makes the join the input read
    # and the bare locked select the target.
    assert lock_index < _index_of_first_touch(recorded, "ansich_belief_assertions")


@pytest.mark.anyio
async def test_active_task_read_model_locks_its_rows_before_the_write_transaction_reads_them(tmp_path):
    async with _representative_state(tmp_path, "rollup-shape-read-model") as (service, task_id, budget):
        backend = service._backend
        await service.stop()
        with _record_statements() as recorded:
            await backend._refresh_active_task_read_model(now=_ASSESSED_AT, lost_ranges=())

    assert task_id  # the fixture's Task is what puts a row in the batch
    read_model_statements = [item for item in recorded if item.touches("ansich_active_task_read_model")]
    assert read_model_statements, [item.sql for item in recorded]
    # Nothing in the write transaction may touch the target table before its
    # lock: not the stale-row DELETE, not the per-view compare.
    assert read_model_statements[0].for_update is True, [item.sql for item in read_model_statements]
    assert read_model_statements[0].sql.startswith("select")
    assert any(item.sql.startswith("delete from ansich_active_task_read_model") for item in read_model_statements)


@pytest.mark.anyio
async def test_budget_projection_locks_the_target_row_before_reading_its_dependencies(tmp_path):
    async with _representative_state(tmp_path, "rollup-shape-budget") as (service, task_id, budget):
        backend = service._backend
        await service.stop()
        fresh = ObservationEnvelope.budget_configured(
            task_id=task_id,
            run_id="run-rollup-serialization",
            occurred_at=_OCCURRED_AT,
            dimension="child_tasks_spawned",
            aggregation_scope="local",
            warning_limit=None,
            hard_limit=8,
            enforcement=False,
            source_kind="runtime_override",
            requested_value=8,
            effective_value=8,
            source_event_id="run:run-rollup-serialization:budget:child_tasks_spawned",
        )
        with _record_statements() as recorded:
            async with backend._session_factory() as session, session.begin():
                await backend._project_budget(session, fresh)

    lock_index = _index_of_lock(recorded, "ansich_task_budgets")
    assert lock_index == 0, [item.sql for item in recorded]
    assert lock_index < _index_of_first_touch(recorded, "ansich_tasks")
    assert lock_index < _index_of_first_touch(recorded, "ansich_entities")
    # First write goes through ON CONFLICT DO NOTHING, not a bare insert.
    inserts = [item for item in recorded if item.sql.startswith("insert into ansich_task_budgets")]
    assert inserts and all("do nothing" in item.sql for item in inserts), [item.sql for item in inserts]


@pytest.mark.anyio
async def test_usage_summary_locks_the_summary_before_rescanning_contributions(tmp_path):
    async with _representative_state(tmp_path, "rollup-shape-usage") as (service, task_id, budget):
        backend = service._backend
        await service.stop()
        with _record_statements() as recorded:
            async with backend._session_factory() as session, session.begin():
                await backend._refresh_usage_summary(
                    session,
                    task_id=task_id,
                    dimension="total_tokens",
                    aggregation_scope="local",
                    updated_at=_ASSESSED_AT,
                )

    lock_index = _index_of_lock(recorded, "ansich_task_usage")
    assert lock_index == 0, [item.sql for item in recorded]
    assert lock_index < _index_of_read(recorded, "ansich_usage_contributions")


# --------------------------------------------------------------------------
# (b2) Lock ORDER: the usage fan-out must be worker-independent
# --------------------------------------------------------------------------


def _record_summary_refreshes(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, str]]:
    """Record the order the fan-out reaches each usage summary.

    ``_refresh_usage_summary``'s very first statement is that summary row's
    ``SELECT … FOR UPDATE`` (pinned by the shape test above), so the order of
    these calls *is* the lock acquisition order -- which is the thing two
    workers have to agree on.
    """

    recorded: list[tuple[str, str, str]] = []
    original = ansich_sql.SqlAnsichBackend._refresh_usage_summary

    async def _patched(session, *, task_id, dimension, aggregation_scope, updated_at):
        recorded.append((task_id, dimension, aggregation_scope))
        return await original(
            session,
            task_id=task_id,
            dimension=dimension,
            aggregation_scope=aggregation_scope,
            updated_at=updated_at,
        )

    monkeypatch.setattr(ansich_sql.SqlAnsichBackend, "_refresh_usage_summary", staticmethod(_patched))
    return recorded


async def _add_unsorted_ancestors(session_factory, descendant_task_id: str) -> tuple[str, ...]:
    """Give one Task three ancestors, stored in deliberately unsorted order.

    Insertion order is what an unordered SQLite select returns, so a fan-out
    that walks the ancestry read as it arrives produces ``z, a, m`` here. No
    matching ``ansich_tasks`` rows are created: this suite's engines run without
    ``PRAGMA foreign_keys``, and the fan-out reads only the ancestry table.
    """

    ancestors = ("zzz-ancestor", "aaa-ancestor", "mmm-ancestor")
    async with session_factory() as session, session.begin():
        for depth, ancestor_task_id in enumerate(ancestors, start=1):
            session.add(
                AnsichTaskAncestryRow(
                    ancestor_task_id=ancestor_task_id,
                    descendant_task_id=descendant_task_id,
                    depth=depth,
                    established_obs_id=new_id(),
                )
            )
    return ancestors


@pytest.mark.anyio
async def test_usage_fan_out_locks_its_targets_in_a_worker_independent_order(tmp_path, monkeypatch):
    """Ancestry order must not decide lock order (PG deadlock window).

    Before the summary lock was explicit its row lock came from the flush,
    where SQLAlchemy's unit of work orders writes by mapper and primary key --
    worker-independent for free. An explicit ``FOR UPDATE`` takes it in
    traversal order instead, so two workers fanning out over overlapping
    ancestor sets could take the same rows in opposite orders and deadlock.
    """

    async with _representative_state(tmp_path, "rollup-fanout-order") as (service, task_id, budget):
        session_factory = service._backend._session_factory
        await _add_unsorted_ancestors(session_factory, task_id)
        recorded = _record_summary_refreshes(monkeypatch)
        attempt_id = new_id()
        with _record_statements() as statements:
            service.record_batch(
                (
                    ObservationEnvelope(
                        kind="llm.requested",
                        occurred_at=_OCCURRED_AT + timedelta(seconds=3),
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
                        occurred_at=_OCCURRED_AT + timedelta(seconds=4),
                        task_id=task_id,
                        subject_type="llm_attempt",
                        subject_id=attempt_id,
                        producer=_PRODUCER,
                        source_event_id=f"attempt:{attempt_id}:responded",
                        correlation_id=task_id,
                        payload={"attempt_no": 1, "latency_ms": 20, "usage": {"total_tokens": 7}},
                    ),
                )
            )
            await service.flush_task(task_id)

    first_touch: list[str] = []
    for target_task_id, _dimension, _scope in recorded:
        if target_task_id not in first_touch:
            first_touch.append(target_task_id)
    assert len(first_touch) == 4, recorded
    assert first_touch == sorted(first_touch), recorded
    # The ancestry read itself is ordered, so the traversal it feeds is a
    # function of the ids rather than of storage order.
    ancestry_reads = [item for item in statements if item.touches("ansich_task_ancestry")]
    assert ancestry_reads, [item.sql for item in statements]
    assert any("order by ansich_task_ancestry.ancestor_task_id" in item.sql for item in ancestry_reads), [item.sql for item in ancestry_reads]


@pytest.mark.anyio
async def test_spawn_backfill_refreshes_summaries_in_a_worker_independent_order(tmp_path, monkeypatch):
    """A `set` iterates in hash order, which differs between processes.

    Hash order is stable within one process but not across them (string hashing
    is seeded per interpreter), so the pre-fix iteration satisfied the sorted
    assertion below only by coincidence -- a different coincidence per run.
    """

    async with _representative_state(tmp_path, "rollup-backfill-order") as (service, task_id, budget):
        backend = service._backend
        await service.stop()
        ancestors = ("zzz-ancestor", "aaa-ancestor", "mmm-ancestor")
        recorded = _record_summary_refreshes(monkeypatch)
        async with backend._session_factory() as session, session.begin():
            await backend._backfill_spawn_usage(
                session,
                ancestor_task_ids=ancestors,
                descendant_task_ids=(task_id,),
                updated_at=_ASSESSED_AT,
            )

    assert len(recorded) >= 4, recorded
    assert all(scope == "inclusive" for _task, _dimension, scope in recorded), recorded
    pairs = [(target, dimension) for target, dimension, _scope in recorded]
    assert pairs == sorted(pairs), pairs


# --------------------------------------------------------------------------
# (c) First-writer race: ON CONFLICT DO NOTHING, then re-read
# --------------------------------------------------------------------------


@pytest.mark.anyio
async def test_usage_summary_first_write_race_converges_instead_of_crashing(tmp_path, monkeypatch):
    """The loser of a first-write race re-reads under the lock and re-reduces.

    Overwriting with the value it computed *before* the winner committed would
    be the very lost update the lock exists to prevent, so the losing pass must
    take the now-lockable row and reduce again -- which the doubled
    contribution rescan below is the structural evidence for.
    """

    async with _representative_state(tmp_path, "rollup-conflict-usage") as (service, task_id, budget):
        backend = service._backend
        await service.stop()
        state = _lock_missing_once(monkeypatch, "ansich_task_usage")
        with _record_statements() as recorded:
            async with backend._session_factory() as session, session.begin():
                await backend._refresh_usage_summary(
                    session,
                    task_id=task_id,
                    dimension="total_tokens",
                    aggregation_scope="local",
                    updated_at=_ASSESSED_AT + timedelta(seconds=5),
                )
        async with backend._session_factory() as session:
            rows = list((await session.execute(select(AnsichTaskUsageRow).where(AnsichTaskUsageRow.task_id == task_id, AnsichTaskUsageRow.dimension == "total_tokens", AnsichTaskUsageRow.aggregation_scope == "local"))).scalars())

    assert state["missed"] == 1
    assert state["calls"] == 2, "the losing writer must take the lock a second time"
    assert len([item for item in recorded if item.touches("ansich_usage_contributions") and not item.for_update]) == 2, "the losing writer must re-reduce, not reuse its pre-conflict value"
    assert len(rows) == 1
    assert rows[0].value == 41
    assert rows[0].updated_at.replace(tzinfo=UTC) == _ASSESSED_AT + timedelta(seconds=5)


@pytest.mark.anyio
async def test_budget_projection_first_write_race_is_a_no_op_not_a_primary_key_crash(tmp_path, monkeypatch):
    async with _representative_state(tmp_path, "rollup-conflict-budget") as (service, task_id, budget):
        backend = service._backend
        await service.stop()
        state = _lock_missing_once(monkeypatch, "ansich_task_budgets")
        async with backend._session_factory() as session, session.begin():
            # Re-projecting the same Observation with the lock forced to miss
            # is the shape a lease takeover produces: two workers doing the
            # same projection, both convinced the row is absent.
            await backend._project_budget(session, budget)
        async with backend._session_factory() as session:
            rows = list((await session.execute(select(AnsichTaskBudgetRow).where(AnsichTaskBudgetRow.task_id == task_id))).scalars())

    assert state["missed"] == 1
    assert len(rows) == 1
    assert rows[0].entity_id == budget.obs_id
    assert rows[0].effective_value == 100


@pytest.mark.anyio
async def test_active_task_read_model_first_write_race_is_a_no_op_not_a_primary_key_crash(tmp_path, monkeypatch):
    async with _representative_state(tmp_path, "rollup-conflict-read-model") as (service, task_id, budget):
        backend = service._backend
        await service.stop()
        async with backend._session_factory() as session:
            before = await session.get(AnsichActiveTaskReadModelRow, task_id)
            before_updated_at = before.updated_at
        state = _lock_missing_once(monkeypatch, "ansich_active_task_read_model")
        await backend._refresh_active_task_read_model(now=_ASSESSED_AT, lost_ranges=())
        async with backend._session_factory() as session:
            rows = list((await session.execute(select(AnsichActiveTaskReadModelRow))).scalars())

    assert state["missed"] == 1
    assert len(rows) == 1
    # Re-read under the lock, then the ordinary unchanged-content compare: the
    # loser must not bump `updated_at` for a write it did not make.
    assert rows[0].updated_at == before_updated_at


@pytest.mark.anyio
async def test_the_pre_fix_bare_insert_is_what_a_first_write_race_crashes_on(tmp_path, monkeypatch):
    """Evidence that the ON CONFLICT above is load-bearing, not decoration.

    Same injected window, but the helper degraded to the plain ORM insert the
    code used before this change. It raises, which is the failure the three
    tests above assert does not happen.
    """

    async with _representative_state(tmp_path, "rollup-conflict-control") as (service, task_id, budget):
        backend = service._backend
        await service.stop()
        _lock_missing_once(monkeypatch, "ansich_task_budgets")

        async def _bare_insert(session, model, values, *, index_elements, returning):
            session.add(model(**values))
            await session.flush()
            return True

        monkeypatch.setattr(ansich_sql, "_insert_ignoring_conflict", _bare_insert)
        with pytest.raises(IntegrityError):
            async with backend._session_factory() as session, session.begin():
                await backend._project_budget(session, budget)


# --------------------------------------------------------------------------
# Dialect parity: the PostgreSQL half of the upsert never runs on SQLite
# --------------------------------------------------------------------------


class _RecordingBind:
    def __init__(self, dialect_name: str) -> None:
        self.dialect = type("_Dialect", (), {"name": dialect_name})()


class _RecordingSession:
    """Just enough session for the dialect dispatch, no database behind it."""

    def __init__(self, dialect_name: str) -> None:
        self.bind = _RecordingBind(dialect_name)
        self.statements: list[object] = []

    async def execute(self, statement: object) -> object:
        self.statements.append(statement)
        return type("_Result", (), {"scalar_one_or_none": staticmethod(lambda: "inserted")})()


#: Every ``_insert_ignoring_conflict`` call site in ``sql.py``, as
#: ``(model, values, index_elements, returning column)``. Kept as data so the
#: PostgreSQL rendering of each is compiled rather than hand-verified.
_FIRST_WRITE_UPSERTS = (
    (
        AnsichTaskUsageRow,
        {
            "task_id": "task",
            "dimension": "total_tokens",
            "aggregation_scope": "local",
            "value": 1,
            "as_of": _OCCURRED_AT,
            "complete_through_ingest_seq": 1,
            "updated_at": _OCCURRED_AT,
        },
        ["task_id", "dimension", "aggregation_scope"],
        AnsichTaskUsageRow.task_id,
    ),
    (
        AnsichActiveTaskReadModelRow,
        {"task_id": "task", "run_id": "run", "source_kind": "deerflow_run"},
        ["task_id"],
        AnsichActiveTaskReadModelRow.task_id,
    ),
    (
        AnsichEntityRow,
        {"entity_id": "obs", "entity_type": "task_budget", "discovered_obs_id": "obs"},
        ["entity_id"],
        AnsichEntityRow.entity_id,
    ),
    (
        AnsichTaskBudgetRow,
        {"entity_id": "obs", "task_id": "task", "dimension": "total_tokens"},
        ["entity_id"],
        AnsichTaskBudgetRow.entity_id,
    ),
)


@pytest.mark.anyio
@pytest.mark.parametrize(("model", "values", "index_elements", "returning"), _FIRST_WRITE_UPSERTS, ids=lambda item: getattr(item, "__tablename__", ""))
async def test_first_write_upsert_renders_on_conflict_on_postgresql_as_well(model, values, index_elements, returning):
    """The branch every other test here cannot reach.

    The whole suite runs on SQLite, so the ``postgresql_insert`` half of
    ``_insert_ignoring_conflict`` is never executed by it -- and PostgreSQL is
    the only dialect where the race it closes is real. Every call site is
    compiled here rather than one representative, so a conflict target that is
    wrong for a particular table cannot hide behind a sibling that is right.
    """

    session = _RecordingSession("postgresql")
    won = await ansich_sql._insert_ignoring_conflict(
        session,
        model,
        values,
        index_elements=index_elements,
        returning=returning,
    )

    assert won is True
    compiled = " ".join(str(session.statements[0].compile(dialect=postgresql.dialect())).split()).lower()
    assert compiled.startswith(f"insert into {model.__tablename__}")
    assert f"on conflict ({', '.join(index_elements)}) do nothing" in compiled
    assert compiled.endswith(f"returning {model.__tablename__}.{returning.key}")


@pytest.mark.anyio
async def test_first_write_upsert_refuses_a_dialect_it_cannot_render():
    """No silent degradation to a bare insert on an unknown backend."""

    with pytest.raises(ValueError, match="unsupported Ansich SQL dialect"):
        await ansich_sql._insert_ignoring_conflict(
            _RecordingSession("mysql"),
            AnsichTaskUsageRow,
            {"task_id": "task"},
            index_elements=["task_id"],
            returning=AnsichTaskUsageRow.task_id,
        )
