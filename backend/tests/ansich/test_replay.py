"""Versioned replay: the projector registry split and the replay-target check.

Two registries, two different questions, and keeping them apart is the whole
point of this module (plan ruling RC2).

``_PROJECTORS`` is the **live** set: the registrations live ingest fans an
Observation out to, in registration order, which is also the per-Observation
execution priority. ``_REPLAYABLE_VERSIONS`` is the **replayable** set: every
version the code can execute, whether or not live ingest mints jobs for it.
Today the two coincide, because there is exactly one version of everything.

They must be able to diverge without live ingest noticing. A second version of
a projector exists so an operator can replay history through it and compare;
if merely *knowing* about it made every new Observation mint a v2 job, the
comparison would have changed the thing being compared, and every Task
admitted after the registration would carry projections nobody asked for. So
the structural pin here monkeypatches a hypothetical ``task-structural@2``
into the replayable registry and asserts a fresh Observation still mints
exactly the live set.

The rest is ``_validate_replay_target``: the check T4's replay command runs
before it touches anything, and the reason vocabulary it refuses with.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, get_args, get_origin

import pytest
from ansich import ObservationEnvelope, ReplayReport, ReplaySelector, new_id
from ansich.contracts import ObservationKind
from ansich.errors import ReplayTargetError
from pydantic import ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.dialects import sqlite
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from deerflow.ansich import replay_cli
from deerflow.ansich.persistence.models import (
    AnsichActiveTaskReadModelRow,
    AnsichObservationRow,
    AnsichProjectionJobRow,
    AnsichProjectorVersionRow,
    AnsichTaskHeartbeatRow,
)
from deerflow.ansich.persistence.sql import (
    _NON_PROJECTOR_REBUILT_TABLES,
    _PROJECTOR_KINDS,
    _PROJECTOR_OWNED_TABLES,
    _PROJECTORS,
    _REBUILD_DELETE_ORDER,
    _REPLAYABLE_VERSIONS,
    _SHARED_REBUILT_TABLES,
    SqlAnsichBackend,
    _projectors_for_kind,
    _replay_observation_condition,
    _validate_replay_target,
)
from deerflow.ansich.replay import execute_replay, plan_replay
from deerflow.persistence.base import Base

_OCCURRED_AT = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
async def backend(tmp_path: Path) -> AsyncIterator[tuple[SqlAnsichBackend, async_sessionmaker]]:
    """One worker over one SQLite file — no concurrency under test here."""

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-replay.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield SqlAnsichBackend(sessions), sessions
    finally:
        await engine.dispose()


def _heartbeat(task_id: str, *, run_id: str, offset_seconds: int, ordinal: int) -> ObservationEnvelope:
    return ObservationEnvelope.task_heartbeat(
        task_id=task_id,
        run_id=run_id,
        occurred_at=_OCCURRED_AT + timedelta(seconds=offset_seconds),
        elapsed_ms=1000 * (offset_seconds + 1),
        worker_id="worker-replay",
        ownership_epoch="epoch-1",
        source_event_id=f"run:{run_id}:heartbeat:{ordinal}",
        producer_seq=ordinal,
    )


async def _settle(sql_backend: SqlAnsichBackend, *, rounds: int = 5) -> int:
    """Drain the claim queue in bounded rounds, the T1 loop's shape.

    Never "one round claimed nothing means done" (F10-26): a dependency-waiting
    job is invisible inside its backoff, so completeness is re-read from a
    fresh round rather than inferred from a replay count.
    """

    replayed = 0
    for _ in range(max(rounds, 1)):
        while True:
            processed = await sql_backend.project_pending(limit=200)
            replayed += processed
            if processed == 0:
                break
        if await sql_backend.unsettled_job_count() == 0:
            break
    return replayed


async def _row_counts(sessions: async_sessionmaker) -> dict[str, int]:
    """Row counts for every ``ansich_*`` table — the dry-run write detector."""

    counts: dict[str, int] = {}
    async with sessions() as session:
        for name, table in Base.metadata.tables.items():
            if not name.startswith("ansich_"):
                continue
            counts[name] = int(await session.scalar(select(func.count()).select_from(table)) or 0)
    return counts


@pytest.fixture
async def populated(backend: tuple[SqlAnsichBackend, async_sessionmaker]) -> dict[str, object]:
    """Two Tasks, three of the projector families, and a settled store.

    Built through the real ingest path rather than by inserting rows, because
    what the filters are aimed at is what live ingest produces: an
    ``ingest_seq`` order that is not the ``occurred_at`` order, and a kind mix
    where every projector claims a different subset.
    """

    sql_backend, sessions = backend
    task_a = new_id()
    task_b = new_id()
    envelopes = [
        ObservationEnvelope.task_lifecycle(
            kind="task.created",
            task_id=task_a,
            source_kind="deerflow_run",
            source_id="run-a",
            occurred_at=_OCCURRED_AT,
            source_event_id="run-a:task:created",
        ),
        ObservationEnvelope.task_lifecycle(
            kind="task.started",
            task_id=task_a,
            source_kind="deerflow_run",
            source_id="run-a",
            occurred_at=_OCCURRED_AT,
            source_event_id="run-a:task:started",
            producer_seq=2,
        ),
        _heartbeat(task_a, run_id="run-a", offset_seconds=0, ordinal=1),
        _heartbeat(task_a, run_id="run-a", offset_seconds=1, ordinal=2),
        _heartbeat(task_a, run_id="run-a", offset_seconds=5, ordinal=3),
        ObservationEnvelope.task_lifecycle(
            kind="task.created",
            task_id=task_b,
            source_kind="deerflow_run",
            source_id="run-b",
            occurred_at=_OCCURRED_AT,
            source_event_id="run-b:task:created",
        ),
        _heartbeat(task_b, run_id="run-b", offset_seconds=0, ordinal=1),
        _heartbeat(task_b, run_id="run-b", offset_seconds=5, ordinal=2),
    ]
    assert await sql_backend.persist_and_project(envelopes) == len(envelopes)
    await _settle(sql_backend)

    async with sessions() as session:
        rows = (await session.execute(select(AnsichObservationRow.ingest_seq, AnsichObservationRow.obs_id, AnsichObservationRow.kind, AnsichObservationRow.task_id, AnsichObservationRow.occurred_at))).all()

    return {
        "task_a": task_a,
        "task_b": task_b,
        "by_ingest_seq": {int(seq): obs_id for seq, obs_id, _, _, _ in rows},
        "kind_by_obs": {obs_id: kind for _, obs_id, kind, _, _ in rows},
        "heartbeats_a": {obs_id for _, obs_id, kind, task_id, _ in rows if kind == "task.heartbeat" and task_id == task_a},
        "all_heartbeats": {obs_id for _, obs_id, kind, _, _ in rows if kind == "task.heartbeat"},
        "early_heartbeats": {obs_id for _, obs_id, kind, _, occurred_at in rows if kind == "task.heartbeat" and (occurred_at.replace(tzinfo=UTC) if occurred_at.tzinfo is None else occurred_at) <= _OCCURRED_AT + timedelta(seconds=1)},
    }


def _task_created(task_id: str, *, source_id: str) -> ObservationEnvelope:
    return ObservationEnvelope.task_lifecycle(
        kind="task.created",
        task_id=task_id,
        source_kind="deerflow_run",
        source_id=source_id,
        occurred_at=_OCCURRED_AT,
        source_event_id=f"run:{source_id}:task:created",
    )


def _known_observation_kinds() -> frozenset[str]:
    """Flatten ``ObservationKind``'s union-of-Literals into its member strings."""

    def _flatten(annotation: object) -> frozenset[str]:
        if get_origin(annotation) is Literal:
            return frozenset(str(value) for value in get_args(annotation))
        return frozenset().union(*(_flatten(member) for member in get_args(annotation)))

    return _flatten(ObservationKind)


class TestLiveIngestIsUnchangedByReplayableVersions:
    """RC2: knowing a replayable version must not change live-ingest fan-out."""

    @pytest.mark.anyio
    async def test_fresh_observation_mints_exactly_the_live_projector_set(
        self,
        backend: tuple[SqlAnsichBackend, async_sessionmaker],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A hypothetical ``task-structural@2`` is known and still mints nothing.

        The v2 entry is injected the way a future code change would add it — a
        second version listed beside the first in ``_REPLAYABLE_VERSIONS``,
        with ``_PROJECTORS`` untouched — and the assertion is on the *rows*, not
        on the helper: what matters is what the database ends up holding for a
        Task admitted while the registration exists.
        """

        sql_backend, sessions = backend
        monkeypatch.setitem(_REPLAYABLE_VERSIONS, "task-structural", ("1", "2"))

        task_id = new_id()
        assert await sql_backend.persist_and_project([_task_created(task_id, source_id="rc2")]) == 1

        async with sessions() as session:
            minted = {(row.projector_name, row.projector_version) for row in (await session.execute(select(AnsichProjectionJobRow))).scalars()}
            registered = {(row.projector_name, row.projector_version) for row in (await session.execute(select(AnsichProjectorVersionRow))).scalars()}

        expected = set(_projectors_for_kind("task.created"))
        assert expected <= set(_PROJECTORS)
        assert minted == expected
        assert registered == expected
        assert not any(version != "1" for _, version in minted)

    def test_projectors_for_kind_reads_the_live_set_only(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The fan-out helper itself never consults the replayable registry."""

        before = _projectors_for_kind("task.created")
        monkeypatch.setitem(_REPLAYABLE_VERSIONS, "task-control", ("1", "2", "3"))
        assert _projectors_for_kind("task.created") == before


class TestValidateReplayTarget:
    @pytest.mark.parametrize(("projector_name", "projector_version"), _PROJECTORS)
    def test_every_live_registration_is_a_valid_replay_target(self, projector_name: str, projector_version: str) -> None:
        assert _validate_replay_target(projector_name, projector_version) is None

    def test_every_live_registration_is_declared_replayable(self) -> None:
        """The live set is a subset of the replayable set, by construction.

        A registration live ingest mints jobs for that the code could not
        replay would make an ordinary rebuild impossible to reproduce.
        """

        for projector_name, projector_version in _PROJECTORS:
            assert projector_version in _REPLAYABLE_VERSIONS[projector_name]

    def test_unknown_projector_name_is_refused(self) -> None:
        with pytest.raises(ReplayTargetError) as caught:
            _validate_replay_target("task-imaginary", "1")
        assert caught.value.reason == "unknown_projector"

    def test_unknown_version_of_a_known_projector_is_refused(self) -> None:
        with pytest.raises(ReplayTargetError) as caught:
            _validate_replay_target("task-structural", "2")
        assert caught.value.reason == "unknown_version"

    def test_declared_version_without_an_executor_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``not_executable`` is unreachable today and this is why it exists.

        It takes a projector the replayable registry names but the projection
        dispatch has no branch for — a shape only a partial code change
        produces. Simulated here rather than left untested, because the whole
        value of the reason is that it separates "this build never heard of it"
        from "this build declares it and cannot run it".
        """

        monkeypatch.setitem(_REPLAYABLE_VERSIONS, "task-unwired", ("1",))
        with pytest.raises(ReplayTargetError) as caught:
            _validate_replay_target("task-unwired", "1")
        assert caught.value.reason == "not_executable"

    def test_a_claimed_kind_the_contract_no_longer_knows_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The second ``not_executable`` trigger, and equally unreachable today.

        A projector whose ``_PROJECTOR_KINDS`` entry names a kind
        ``ObservationKind`` does not admit would be replayed over an empty
        target set and report a clean pass over nothing — the worst answer
        available, because it looks like success. Two triggers share one reason
        because they are the same *class* of fault: a half-finished code change,
        not a bad request.
        """

        monkeypatch.setitem(_PROJECTOR_KINDS, "task-heartbeat", frozenset({"task.heartbeat", "task.imagined"}))
        with pytest.raises(ReplayTargetError) as caught:
            _validate_replay_target("task-heartbeat", "1")
        assert caught.value.reason == "not_executable"
        assert "task.imagined" in str(caught.value)

    def test_error_is_a_value_error_carrying_a_readable_message(self) -> None:
        """The message is pinned whole, not by substring.

        ``"2" in message`` would pass on any text containing a digit — and the
        message is the only part of the refusal a human ever reads, so it is
        worth an exact assertion rather than a probe that a rewrite could gut
        without going red.
        """

        with pytest.raises(ReplayTargetError) as caught:
            _validate_replay_target("task-structural", "2")
        error = caught.value
        assert isinstance(error, ValueError)
        assert error.projector_name == "task-structural"
        assert error.projector_version == "2"
        assert str(error) == "Ansich projector 'task-structural' cannot replay version '2'; this build executes: 1"

    def test_unknown_projector_message_names_the_projector_and_the_build(self) -> None:
        with pytest.raises(ReplayTargetError) as caught:
            _validate_replay_target("task-imaginary", "1")
        assert str(caught.value) == "unknown Ansich projector 'task-imaginary': not registered in this build"


class TestClaimedKindsAreKnown:
    """D5-2's third clause, pinned where it is actually decided.

    ``_validate_replay_target`` re-checks this at call time, but the invariant
    it checks is a property of two module constants written side by side, so
    this test is what catches a typo the moment it is committed rather than the
    first time somebody replays that projector.
    """

    def test_every_claimed_kind_is_a_known_observation_kind(self) -> None:
        known = _known_observation_kinds()
        for projector_name, kinds in _PROJECTOR_KINDS.items():
            assert set(kinds) <= known, projector_name

    def test_every_kind_claiming_projector_is_registered_live(self) -> None:
        live_names = {name for name, _ in _PROJECTORS}
        assert set(_PROJECTOR_KINDS) <= live_names

    def test_exactly_one_live_projector_claims_no_kinds(self) -> None:
        """The complement, which the two pins above do not cover.

        ``_validate_replay_target`` reads "every kind it *does* claim is
        known", so a projector with **no** ``_PROJECTOR_KINDS`` entry validates
        green — correct for ``task-spawn-reconcile``, which is enqueued by
        ``_project_task_spawn`` rather than fanned out by kind and therefore
        claims nothing by design, and silently wrong for anything else. A
        projector that *lost* its entry would be replayed over an empty target
        set and report a clean pass over nothing.

        Absence cannot be distinguished from deliberate kind-lessness at call
        time, so it is pinned here instead: exactly one live registration is
        allowed to be missing, and it is named.
        """

        live_names = {name for name, _ in _PROJECTORS}
        assert live_names - set(_PROJECTOR_KINDS) == {"task-spawn-reconcile"}


class TestProjectorOwnedTables:
    """The rebuild delete list, partitioned into three named classes.

    ``--replace`` (T5) and this task's digest both need one question answered:
    *which read-model tables belong to this projector alone?* The answer cannot
    be derived at runtime — read-model rows carry no projector column — so it is
    a declared map, and what a test can pin is that the declaration covers the
    rebuild delete list exactly once each.

    Three classes rather than one, because "every table has exactly one owning
    projector" is simply false and pretending otherwise would put another
    projector's rows inside a ``--replace``: assessor and Alert tables have no
    projector at all, and ``ansich_entities`` has nine.
    """

    def test_the_rebuild_delete_list_is_partitioned_exactly_once(self) -> None:
        owned = [model for models in _PROJECTOR_OWNED_TABLES.values() for model in models]
        classified = [*owned, *_SHARED_REBUILT_TABLES, *_NON_PROJECTOR_REBUILT_TABLES]
        assert len(classified) == len(set(classified)), "a table is classified twice"
        assert set(classified) == set(_REBUILD_DELETE_ORDER)

    def test_the_rebuild_actually_deletes_the_pinned_list(self) -> None:
        """The partition is pinned against the constant the rebuild iterates.

        A list restated beside the rebuild rather than shared with it would
        drift the first time a table is added, and the drift would be silent:
        ``--replace`` would keep deleting the old set while the rebuild deleted
        the new one.
        """

        assert "_REBUILD_DELETE_ORDER" in SqlAnsichBackend._rebuild_projections_locked.__code__.co_names

    def test_every_owning_projector_is_a_replayable_target(self) -> None:
        assert set(_PROJECTOR_OWNED_TABLES) <= set(_REPLAYABLE_VERSIONS)

    def test_every_replayable_projector_has_an_entry(self) -> None:
        """Including the ones that own nothing, which must say so explicitly.

        An absent key and an empty tuple would read the same to
        ``dict.get(name, ())`` and mean different things: "nobody wrote this
        down" versus "this projector shares every table it writes". The digest
        refuses to hash the empty set either way, so the distinction is only
        visible here.
        """

        assert set(_PROJECTOR_OWNED_TABLES) == set(_REPLAYABLE_VERSIONS)


class TestReplayTargetSelection:
    @pytest.mark.anyio
    async def test_task_filter_selects_only_that_tasks_claimed_observations(
        self,
        backend: tuple[SqlAnsichBackend, async_sessionmaker],
        populated: dict[str, object],
    ) -> None:
        sql_backend, sessions = backend
        condition = _replay_observation_condition("task-heartbeat", ReplaySelector(task_id=populated["task_a"]))
        async with sessions() as session:
            selected = {row for row in (await session.execute(select(AnsichObservationRow.obs_id).where(condition))).scalars()}
        assert selected == populated["heartbeats_a"]

    @pytest.mark.anyio
    async def test_ingest_filter_selects_the_primary_key_range(
        self,
        backend: tuple[SqlAnsichBackend, async_sessionmaker],
        populated: dict[str, object],
    ) -> None:
        sql_backend, sessions = backend
        by_seq: dict[int, str] = populated["by_ingest_seq"]
        condition = _replay_observation_condition("task-control", ReplaySelector(ingest_from=1, ingest_to=2))
        async with sessions() as session:
            selected = {row for row in (await session.execute(select(AnsichObservationRow.obs_id).where(condition))).scalars()}
        control_kinds = _PROJECTOR_KINDS["task-control"]
        expected = {obs_id for seq, obs_id in by_seq.items() if seq <= 2 and populated["kind_by_obs"][obs_id] in control_kinds}
        assert selected == expected
        assert expected

    @pytest.mark.anyio
    async def test_time_filter_selects_the_window_within_the_claimed_kinds(
        self,
        backend: tuple[SqlAnsichBackend, async_sessionmaker],
        populated: dict[str, object],
    ) -> None:
        sql_backend, sessions = backend
        condition = _replay_observation_condition(
            "task-heartbeat",
            ReplaySelector(occurred_from=_OCCURRED_AT, occurred_to=_OCCURRED_AT + timedelta(seconds=1)),
        )
        async with sessions() as session:
            selected = {row for row in (await session.execute(select(AnsichObservationRow.obs_id).where(condition))).scalars()}
        assert selected == populated["early_heartbeats"]

    def test_the_time_filter_is_bounded_by_kind_and_never_reads_recorded_at(self) -> None:
        """The index this filter depends on is ``(kind, occurred_at)``.

        Without the kind bound the same window is served by nothing, and the
        obvious "fix" -- filtering on ``recorded_at``, the column that actually
        records when the row landed -- is worse: it carries no index at all, so
        it is a full scan of a table with no retention. Pinned on the compiled
        SQL because that is the only place the choice is observable.
        """

        condition = _replay_observation_condition(
            "task-heartbeat",
            ReplaySelector(occurred_from=_OCCURRED_AT, occurred_to=_OCCURRED_AT + timedelta(hours=1)),
        )
        compiled = str(select(AnsichObservationRow.obs_id).where(condition).compile(dialect=sqlite.dialect(), compile_kwargs={"literal_binds": True}))
        assert "occurred_at" in compiled
        assert "recorded_at" not in compiled
        assert "kind IN" in compiled

    def test_a_time_filtered_replay_of_a_kindless_projector_is_refused(self) -> None:
        """``task-spawn-reconcile`` has no kind list to bound the window with.

        Its jobs are enqueued inside ``_project_task_spawn``'s own transaction
        rather than fanned out by kind, so ``_PROJECTOR_KINDS`` has no entry for
        it -- and an ``occurred_at`` window with no kind bound is exactly the
        unindexed full scan the filter design exists to avoid. Refused with a
        typed reason rather than served slowly, because the scan gets worse
        every day the store grows.
        """

        with pytest.raises(ReplayTargetError) as caught:
            _replay_observation_condition(
                "task-spawn-reconcile",
                ReplaySelector(occurred_from=_OCCURRED_AT, occurred_to=_OCCURRED_AT + timedelta(hours=1)),
            )
        assert caught.value.reason == "time_filter_unsupported"

    def test_a_kindless_projector_still_accepts_a_task_or_ingest_filter(self) -> None:
        assert _replay_observation_condition("task-spawn-reconcile", ReplaySelector(task_id=new_id())) is not None
        assert _replay_observation_condition("task-spawn-reconcile", ReplaySelector(ingest_from=1, ingest_to=5)) is not None


class TestReplaySelectorContract:
    @pytest.mark.parametrize(
        "kwargs",
        [
            {"occurred_from": _OCCURRED_AT},
            {"occurred_to": _OCCURRED_AT},
            {"ingest_from": 3},
            {"ingest_to": 3},
        ],
    )
    def test_one_sided_ranges_are_refused(self, kwargs: dict[str, object]) -> None:
        """The open side is where an operator does not want a surprise."""

        with pytest.raises(ValidationError):
            ReplaySelector(**kwargs)

    def test_reversed_ranges_are_refused(self) -> None:
        with pytest.raises(ValidationError):
            ReplaySelector(occurred_from=_OCCURRED_AT + timedelta(hours=1), occurred_to=_OCCURRED_AT)
        with pytest.raises(ValidationError):
            ReplaySelector(ingest_from=9, ingest_to=2)

    def test_an_empty_selector_reports_itself_unfiltered(self) -> None:
        assert ReplaySelector().is_unfiltered is True
        assert ReplaySelector(task_id="x").is_unfiltered is False


class TestReplayJobMintAndRePend:
    @pytest.mark.anyio
    async def test_absent_jobs_are_minted_and_existing_ones_re_pended(
        self,
        backend: tuple[SqlAnsichBackend, async_sessionmaker],
        populated: dict[str, object],
    ) -> None:
        """The two halves of a replay's write, told apart by what was there.

        ``task-heartbeat@1`` already has a job per heartbeat Observation, so a
        replay of it re-pends. A version that never ran has none, so the same
        request against it mints -- which is the whole reason a replay can
        introduce a new version at all.
        """

        sql_backend, sessions = backend
        async with sessions() as session:
            await session.execute(update(AnsichProjectionJobRow).values(status="completed", attempts=1))
            await session.commit()
            before = {
                obs_id: generation
                for obs_id, generation in (
                    await session.execute(
                        select(AnsichProjectionJobRow.obs_id, AnsichProjectionJobRow.lease_generation).where(
                            AnsichProjectionJobRow.projector_name == "task-heartbeat",
                        )
                    )
                ).all()
            }

        minted, re_pended = await sql_backend.mint_replay_jobs(
            projector_name="task-heartbeat",
            projector_version="1",
            selector=ReplaySelector(task_id=populated["task_a"]),
        )
        assert (minted, re_pended) == (0, len(populated["heartbeats_a"]))

        async with sessions() as session:
            rows = list(
                (
                    await session.execute(
                        select(AnsichProjectionJobRow).where(
                            AnsichProjectionJobRow.projector_name == "task-heartbeat",
                            AnsichProjectionJobRow.obs_id.in_(populated["heartbeats_a"]),
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert {row.obs_id for row in rows} == populated["heartbeats_a"]
        for row in rows:
            assert row.status == "pending"
            # Constraint 7, store-wide: pending <=> attempts == 0.
            assert row.attempts == 0
            assert row.lease_owner is None
            assert row.last_error is None
            # Global Constraint 6: monotonic, raised by exactly one so a claim
            # taken before the replay cannot complete over it. Never reset --
            # the counter's whole value is that an older claim's number can
            # never match again, so the assertion is relative to what the row
            # already carried (these jobs were claimed once when the fixture
            # settled the store).
            assert row.lease_generation == before[row.obs_id] + 1

    @pytest.mark.anyio
    async def test_a_version_that_never_ran_is_minted_for_every_targeted_observation(
        self,
        backend: tuple[SqlAnsichBackend, async_sessionmaker],
        populated: dict[str, object],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        sql_backend, sessions = backend
        monkeypatch.setitem(_REPLAYABLE_VERSIONS, "task-heartbeat", ("1", "2"))

        minted, re_pended = await sql_backend.mint_replay_jobs(
            projector_name="task-heartbeat",
            projector_version="2",
            selector=ReplaySelector(),
        )
        assert re_pended == 0
        assert minted == len(populated["all_heartbeats"])

        async with sessions() as session:
            rows = list((await session.execute(select(AnsichProjectionJobRow).where(AnsichProjectionJobRow.projector_version == "2"))).scalars().all())
            registered = await session.get(AnsichProjectorVersionRow, ("task-heartbeat", "2"))
        assert {row.obs_id for row in rows} == populated["all_heartbeats"]
        assert all(row.status == "pending" and row.attempts == 0 and row.lease_generation == 0 for row in rows)
        # A minted job's projector version has to be registered in the same
        # breath, or health cannot name the row set it now owes work for.
        assert registered is not None

    @pytest.mark.anyio
    async def test_a_kindless_projector_re_pends_and_never_mints(
        self,
        backend: tuple[SqlAnsichBackend, async_sessionmaker],
        populated: dict[str, object],
    ) -> None:
        """The complement of the kind bound, and the reason it is not optional.

        ``task-spawn-reconcile`` claims no kinds, so "every Observation this
        projector claims" is the empty set. Minting by filter alone would give
        every Observation in the store a spawn-reconcile job -- jobs whose
        projector expects a spawn edge that does not exist. A replay of it can
        therefore only re-pend the jobs ``_project_task_spawn`` actually
        enqueued.
        """

        sql_backend, sessions = backend
        minted, re_pended = await sql_backend.mint_replay_jobs(
            projector_name="task-spawn-reconcile",
            projector_version="1",
            selector=ReplaySelector(),
        )
        assert (minted, re_pended) == (0, 0)
        async with sessions() as session:
            count = await session.scalar(select(func.count()).select_from(AnsichProjectionJobRow).where(AnsichProjectionJobRow.projector_name == "task-spawn-reconcile"))
        assert count == 0

    @pytest.mark.anyio
    async def test_counting_the_target_set_writes_nothing(
        self,
        backend: tuple[SqlAnsichBackend, async_sessionmaker],
        populated: dict[str, object],
    ) -> None:
        sql_backend, sessions = backend
        before = await _row_counts(sessions)
        minted, re_pended = await sql_backend.count_replay_targets(
            projector_name="task-heartbeat",
            projector_version="1",
            selector=ReplaySelector(),
        )
        assert (minted, re_pended) == (0, len(populated["all_heartbeats"]))
        assert await _row_counts(sessions) == before


class TestReadModelDigest:
    @pytest.mark.anyio
    async def test_a_projector_that_owns_no_table_has_no_digest(
        self,
        backend: tuple[SqlAnsichBackend, async_sessionmaker],
        populated: dict[str, object],
    ) -> None:
        """Hashing the empty set would make such a replay trivially reproducible.

        ``task-structural`` writes nothing ``task-control`` does not also write
        (``_project_control`` calls ``_project_structural`` first), so it owns
        no table exclusively -- and a digest over zero tables would compare
        equal to any other digest over zero tables, reporting determinism
        nobody established.
        """

        sql_backend, _ = backend
        assert _PROJECTOR_OWNED_TABLES["task-structural"] == ()
        assert await sql_backend.read_model_digest("task-structural") is None

    @pytest.mark.anyio
    async def test_the_digest_covers_the_owned_rows_and_moves_when_they_do(
        self,
        backend: tuple[SqlAnsichBackend, async_sessionmaker],
        populated: dict[str, object],
    ) -> None:
        sql_backend, sessions = backend
        first = await sql_backend.read_model_digest("task-heartbeat")
        assert first is not None
        assert await sql_backend.read_model_digest("task-heartbeat") == first

        async with sessions() as session, session.begin():
            row = await session.scalar(select(AnsichTaskHeartbeatRow).limit(1))
            row.elapsed_ms = row.elapsed_ms + 1
        assert await sql_backend.read_model_digest("task-heartbeat") != first

    @pytest.mark.anyio
    async def test_the_digest_ignores_row_insertion_order(
        self,
        backend: tuple[SqlAnsichBackend, async_sessionmaker],
        populated: dict[str, object],
    ) -> None:
        """Ordered by primary key, so two stores holding the same rows agree.

        A digest that read rows in physical order would answer differently for
        the same history replayed in a different interleaving -- which is
        precisely the comparison §11 wants it to be able to make.
        """

        sql_backend, sessions = backend
        before = await sql_backend.read_model_digest("task-heartbeat")
        async with sessions() as session, session.begin():
            rows = list((await session.execute(select(AnsichTaskHeartbeatRow))).scalars().all())
            for row in rows:
                await session.delete(row)
            await session.flush()
            for row in reversed(rows):
                session.add(
                    AnsichTaskHeartbeatRow(
                        **{column.name: getattr(row, column.name) for column in AnsichTaskHeartbeatRow.__table__.columns},
                    )
                )
        assert await sql_backend.read_model_digest("task-heartbeat") == before


class TestPlanReplay:
    @pytest.mark.anyio
    async def test_a_dry_run_writes_nothing_anywhere(
        self,
        backend: tuple[SqlAnsichBackend, async_sessionmaker],
        populated: dict[str, object],
    ) -> None:
        """Row counts across **every** ``ansich_*`` table, not just the jobs.

        The narrow assertion (no new jobs) would pass a plan that quietly
        assessed, stamped a read model or minted a projector-version row on the
        way past. What ``--dry-run`` promises an operator is that asking costs
        nothing, so the check is the whole schema.
        """

        sql_backend, sessions = backend
        before = await _row_counts(sessions)
        report = await plan_replay(
            sql_backend,
            projector_name="task-heartbeat",
            projector_version="1",
            selector=ReplaySelector(),
        )
        assert await _row_counts(sessions) == before
        assert report.dry_run is True
        assert report.targeted == len(populated["all_heartbeats"])
        assert report.targeted == report.minted + report.re_pended
        assert report.replayed == 0
        assert report.digest is None

    @pytest.mark.anyio
    async def test_a_plan_refuses_an_impossible_target_before_reading(
        self,
        backend: tuple[SqlAnsichBackend, async_sessionmaker],
        populated: dict[str, object],
    ) -> None:
        sql_backend, _ = backend
        with pytest.raises(ReplayTargetError) as caught:
            await plan_replay(
                sql_backend,
                projector_name="task-heartbeat",
                projector_version="7",
                selector=ReplaySelector(),
            )
        assert caught.value.reason == "unknown_version"


class TestExecuteReplay:
    @pytest.mark.anyio
    async def test_two_replays_of_one_observation_set_agree(
        self,
        backend: tuple[SqlAnsichBackend, async_sessionmaker],
        populated: dict[str, object],
    ) -> None:
        """Spec §11's determinism acceptance, and both halves of it matter.

        The digests must be equal *and* both passes must have reached
        ``unsettled == 0`` through the bounded loop. Equality alone would be
        satisfiable by two identically-incomplete runs, which is the F10-26
        mistake wearing the digest's clothes -- so the completeness half is
        asserted first.
        """

        sql_backend, _ = backend
        first = await execute_replay(sql_backend, projector_name="task-heartbeat", projector_version="1", selector=ReplaySelector())
        second = await execute_replay(sql_backend, projector_name="task-heartbeat", projector_version="1", selector=ReplaySelector())

        assert first.unsettled == 0
        assert second.unsettled == 0
        assert first.digest is not None
        assert first.digest == second.digest
        assert first.errors == ()
        assert first.re_pended == len(populated["all_heartbeats"])
        assert first.replayed >= first.targeted

    @pytest.mark.anyio
    async def test_a_digest_is_refused_while_anything_is_still_owed(
        self,
        backend: tuple[SqlAnsichBackend, async_sessionmaker],
        populated: dict[str, object],
    ) -> None:
        """A digest over an unsettled store would be a lie with a checksum.

        The unsettled job here is one a live lease holds, which is the ordinary
        shape: another worker claimed it and this pass has no business either
        waiting for it or hashing around it.
        """

        sql_backend, sessions = backend
        async with sessions() as session, session.begin():
            await session.execute(
                update(AnsichProjectionJobRow)
                .where(AnsichProjectionJobRow.projector_name == "task-heartbeat")
                .values(
                    status="processing",
                    attempts=1,
                    lease_owner="another-worker",
                    lease_expires_at=datetime.now(UTC) + timedelta(hours=1),
                )
            )

        report = await execute_replay(
            sql_backend,
            projector_name="task-control",
            projector_version="1",
            selector=ReplaySelector(),
            max_rounds=2,
        )
        assert report.unsettled > 0
        assert report.digest is None
        assert any("unsettled" in error for error in report.errors)

    @pytest.mark.anyio
    async def test_an_observation_ingested_mid_pass_is_reported_not_absorbed(
        self,
        backend: tuple[SqlAnsichBackend, async_sessionmaker],
        populated: dict[str, object],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The drive loop drains the queue; the queue does not know the filters.

        A replay bounded by an ingest range cannot target a row that does not
        exist yet, but its drive loop will still claim that row's jobs -- the
        claim orders by ``ingest_seq`` and has never heard of this pass. Two
        things therefore have to be true at once, and both are asserted: the
        late Observation is **outside** ``targeted``, and it is **visible** in
        ``replayed``, which is exactly the store-wide count that makes the
        difference legible instead of silent.
        """

        sql_backend, sessions = backend
        highest = max(populated["by_ingest_seq"])
        late = _heartbeat(populated["task_a"], run_id="run-a", offset_seconds=9, ordinal=99)
        original = sql_backend.project_pending
        calls = {"count": 0}

        async def instrumented(*, limit: int = 200) -> int:
            calls["count"] += 1
            if calls["count"] == 1:
                await sql_backend.persist_and_project([late])
            return await original(limit=limit)

        monkeypatch.setattr(sql_backend, "project_pending", instrumented)

        report = await execute_replay(
            sql_backend,
            projector_name="task-heartbeat",
            projector_version="1",
            selector=ReplaySelector(ingest_from=1, ingest_to=highest),
        )

        assert report.targeted == len(populated["all_heartbeats"])
        assert report.replayed > report.targeted
        async with sessions() as session:
            late_job = await session.scalar(
                select(AnsichProjectionJobRow).where(
                    AnsichProjectionJobRow.obs_id == late.obs_id,
                    AnsichProjectionJobRow.projector_name == "task-heartbeat",
                )
            )
        assert late_job is not None
        assert late_job.status == "completed"


class TestActiveTaskReadModelIsNotFrozen:
    """Global Constraint 4 / ruling RC3 -- the batch's most dangerous interaction.

    ``_is_staler_publish``'s docstring names "a partial replay backfilled at a
    low ``ingest_seq``" as one of three ways to freeze the active-Task read
    model for good. These two tests are that named hazard, driven and then
    driven again with the fix disarmed, because a regression test for a freeze
    is only worth anything if the freeze can be shown to happen without it.
    """

    @pytest.mark.anyio
    async def test_a_low_ingest_replay_clears_the_rows_and_the_next_tick_republishes(
        self,
        backend: tuple[SqlAnsichBackend, async_sessionmaker],
        populated: dict[str, object],
    ) -> None:
        sql_backend, sessions = backend
        await sql_backend.assess_operations(now=datetime.now(UTC))
        async with sessions() as session:
            published = await session.scalar(select(AnsichActiveTaskReadModelRow).where(AnsichActiveTaskReadModelRow.task_id == populated["task_a"]))
        assert published is not None
        assert published.projection_watermark == max(populated["by_ingest_seq"])

        # The delete rides in the mint's own transaction (RC3), so it is
        # observable before anything has been re-projected.
        await sql_backend.mint_replay_jobs(
            projector_name="task-control",
            projector_version="1",
            selector=ReplaySelector(ingest_from=1, ingest_to=1),
        )
        async with sessions() as session:
            during = await session.scalar(select(AnsichActiveTaskReadModelRow).where(AnsichActiveTaskReadModelRow.task_id == populated["task_a"]))
        assert during is None, "the re-pend must clear the basis it just invalidated"

        report = await execute_replay(
            sql_backend,
            projector_name="task-control",
            projector_version="1",
            selector=ReplaySelector(ingest_from=1, ingest_to=1),
        )
        assert report.unsettled == 0
        async with sessions() as session:
            republished = await session.scalar(select(AnsichActiveTaskReadModelRow).where(AnsichActiveTaskReadModelRow.task_id == populated["task_a"]))
        assert republished is not None
        assert republished.projection_watermark == max(populated["by_ingest_seq"])

        # And the read model keeps moving: a later tick publishes over the
        # republished row instead of being skipped as staler, which is the
        # freeze the counterfactual below demonstrates.
        await sql_backend.assess_operations(now=datetime.now(UTC) + timedelta(minutes=5))
        async with sessions() as session:
            later = await session.scalar(select(AnsichActiveTaskReadModelRow).where(AnsichActiveTaskReadModelRow.task_id == populated["task_a"]))
        assert later.updated_at > republished.updated_at

    @pytest.mark.anyio
    async def test_without_the_delete_the_read_model_freezes(
        self,
        backend: tuple[SqlAnsichBackend, async_sessionmaker],
        populated: dict[str, object],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The counterfactual, so the fix above is not a test of nothing.

        With the in-transaction delete disarmed, the row keeps a basis the
        store can no longer reach while the re-pended job is outstanding, and
        every later tick reads as staler and skips it. The visible symptom is
        the one that matters operationally: a stale row that stops updating
        rather than an error anyone would notice.
        """

        sql_backend, sessions = backend
        await sql_backend.assess_operations(now=datetime.now(UTC))

        async def disarmed(*args: object, **kwargs: object) -> int:
            return 0

        monkeypatch.setattr(sql_backend, "_clear_frozen_active_task_rows", disarmed)
        await sql_backend.mint_replay_jobs(
            projector_name="task-control",
            projector_version="1",
            selector=ReplaySelector(ingest_from=1, ingest_to=1),
        )
        async with sessions() as session:
            before = await session.scalar(select(AnsichActiveTaskReadModelRow).where(AnsichActiveTaskReadModelRow.task_id == populated["task_a"]))
        stale_updated_at = before.updated_at

        await sql_backend.assess_operations(now=datetime.now(UTC) + timedelta(minutes=5))
        async with sessions() as session:
            frozen = await session.scalar(select(AnsichActiveTaskReadModelRow).where(AnsichActiveTaskReadModelRow.task_id == populated["task_a"]))
        assert frozen is not None
        assert frozen.updated_at == stale_updated_at, "the tick should have been skipped by the publish guard"


class TestReplayCli:
    def test_the_documented_flags_parse_into_a_selector(self) -> None:
        args = replay_cli.build_parser().parse_args(
            [
                "--projector",
                "task-heartbeat",
                "--version",
                "1",
                "--task-id",
                "task-7",
                "--ingest-from",
                "3",
                "--ingest-to",
                "9",
                "--dry-run",
            ]
        )
        selector = replay_cli.selector_from_args(args)
        assert args.projector == "task-heartbeat"
        assert args.version == "1"
        assert args.dry_run is True
        assert selector == ReplaySelector(task_id="task-7", ingest_from=3, ingest_to=9)

    def test_iso_time_bounds_become_an_aware_window(self) -> None:
        args = replay_cli.build_parser().parse_args(
            [
                "--projector",
                "task-heartbeat",
                "--version",
                "1",
                "--occurred-from",
                "2026-07-01T12:00:00+00:00",
                "--occurred-to",
                "2026-07-01T13:00:00+00:00",
            ]
        )
        selector = replay_cli.selector_from_args(args)
        assert selector.occurred_from == _OCCURRED_AT
        assert selector.occurred_to == _OCCURRED_AT + timedelta(hours=1)

    def test_a_naive_time_bound_is_read_as_utc(self) -> None:
        """An operator typing a bare timestamp means UTC, and is told so.

        The alternative -- letting a naive value through -- compares a naive
        bound against a timezone-aware column, which on PostgreSQL raises and
        on SQLite silently compares strings. Neither is an answer.
        """

        args = replay_cli.build_parser().parse_args(
            [
                "--projector",
                "task-heartbeat",
                "--version",
                "1",
                "--occurred-from",
                "2026-07-01T12:00:00",
                "--occurred-to",
                "2026-07-01T13:00:00",
            ]
        )
        assert replay_cli.selector_from_args(args).occurred_from == _OCCURRED_AT

    def test_exit_codes_separate_refusal_from_an_incomplete_pass(self) -> None:
        """Three outcomes, three codes, because a script has to tell them apart.

        A refused target is the operator's to fix; an incomplete pass is the
        store's, and re-running is the remedy; a clean pass is neither.
        """

        clean = ReplayReport(projector_name="task-heartbeat", projector_version="1", targeted=3, minted=0, re_pended=3, replayed=3, unsettled=0, dry_run=False, digest="abc")
        incomplete = clean.model_copy(update={"unsettled": 2, "errors": ("2 job(s) still unsettled",), "digest": None})
        assert replay_cli.exit_code(clean) == 0
        assert replay_cli.exit_code(incomplete) == 1

    def test_a_one_sided_window_is_refused_by_the_selector(self) -> None:
        args = replay_cli.build_parser().parse_args(
            [
                "--projector",
                "task-heartbeat",
                "--version",
                "1",
                "--occurred-from",
                "2026-07-01T12:00:00+00:00",
            ]
        )
        with pytest.raises(ValidationError):
            replay_cli.selector_from_args(args)
