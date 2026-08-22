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

import ast
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, get_args, get_origin

import pytest
from ansich import ObservationEnvelope, ReplayReport, ReplaySelector, new_id
from ansich.contracts import ObservationKind
from ansich.errors import ReplayTargetError
from pydantic import ValidationError
from sqlalchemy import UniqueConstraint, func, select, update
from sqlalchemy.dialects import sqlite
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from deerflow.ansich import replay_cli
from deerflow.ansich.persistence import models as models_module
from deerflow.ansich.persistence import sql as sql_module
from deerflow.ansich.persistence.models import (
    AnsichActiveTaskReadModelRow,
    AnsichObservationRow,
    AnsichProjectionJobRow,
    AnsichProjectorVersionRow,
    AnsichStepRow,
    AnsichTaskBudgetRow,
    AnsichTaskHeartbeatRow,
    AnsichTransitionRow,
)
from deerflow.ansich.persistence.sql import (
    _DIGEST_EXCLUDED_COLUMNS,
    _DIGEST_RANDOM_KEY_COLUMNS,
    _DIGEST_SURROGATE_ORDER,
    _NON_PROJECTOR_REBUILT_TABLES,
    _PROJECTOR_KINDS,
    _PROJECTOR_OWNED_TABLES,
    _PROJECTORS,
    _REBUILD_DELETE_ORDER,
    _REPLACE_PROVEN_PROJECTORS,
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


#: Which ``project_pending`` dispatch branch each projector name enters at.
#: Declared rather than parsed out of the dispatch chain, and pinned against
#: ``_PROJECTOR_OWNED_TABLES``'s key set below so a new projector cannot be
#: added without deciding what it writes.
_DISPATCH_ENTRY = {
    "task-structural": "_project_structural",
    "task-control": "_project_control",
    "task-step": "_project_step",
    "task-usage": "_project_usage",
    "task-budget": "_project_budget",
    "task-heartbeat": "_project_heartbeat",
    "task-safety": "_project_safety",
    "environment-projector": "_project_environment",
    "evaluation-projector": "_project_evaluation",
    "task-spawn-reconcile": "_reconcile_spawn_usage",
}
_MODEL_WRITE_CALLS = frozenset({"delete", "update", "postgresql_insert", "sqlite_insert"})


def _is_row_class(name: str) -> bool:
    return name.startswith("Ansich") and name.endswith("Row")


def _mentioned_models(node: ast.AST) -> set[str]:
    return {child.id for child in ast.walk(node) if isinstance(child, ast.Name) and _is_row_class(child.id)}


def _function_facts(function: ast.AST) -> tuple[set[str], set[str]]:
    """``(models this body writes, functions it calls)`` for one function.

    Writes are detected in four forms, and the set is a deliberate **lower
    bound** -- see the test that consumes it for why that is the useful
    direction here.
    """

    writes: set[str] = set()
    calls: set[str] = set()
    bound: dict[str, str] = {}

    # Two passes so `rows = select(X)...` then `for row in rows:` resolves
    # regardless of which the walk reaches first.
    for _ in range(2):
        for node in ast.walk(function):
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                models = _mentioned_models(node.value) | {bound[child.id] for child in ast.walk(node.value) if isinstance(child, ast.Name) and child.id in bound}
                if len(models) == 1:
                    bound[node.targets[0].id] = next(iter(models))
            elif isinstance(node, ast.For) and isinstance(node.target, ast.Name):
                models = _mentioned_models(node.iter) | {bound[child.id] for child in ast.walk(node.iter) if isinstance(child, ast.Name) and child.id in bound}
                if len(models) == 1:
                    bound[node.target.id] = next(iter(models))

    for node in ast.walk(function):
        if isinstance(node, ast.Call):
            callee = node.func
            if isinstance(callee, ast.Name):
                if _is_row_class(callee.id):
                    writes.add(callee.id)
                elif callee.id in _MODEL_WRITE_CALLS or "insert" in callee.id or "upsert" in callee.id:
                    writes |= {argument.id for argument in node.args if isinstance(argument, ast.Name) and _is_row_class(argument.id)}
                calls.add(callee.id)
            elif isinstance(callee, ast.Attribute):
                calls.add(callee.attr)
                if "insert" in callee.attr or "upsert" in callee.attr:
                    writes |= {argument.id for argument in node.args if isinstance(argument, ast.Name) and _is_row_class(argument.id)}
                if callee.attr in {"add", "delete", "merge"}:
                    for argument in node.args:
                        if isinstance(argument, ast.Call) and isinstance(argument.func, ast.Name) and _is_row_class(argument.func.id):
                            writes.add(argument.func.id)
                        elif isinstance(argument, ast.Name) and argument.id in bound:
                            writes.add(bound[argument.id])
        elif isinstance(node, ast.Assign | ast.AugAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id in bound:
                    writes.add(bound[target.value.id])
    return writes, calls


def _dispatch_branch_writers() -> dict[str, set[str]]:
    """``table name -> the projector branches whose code writes it``."""

    source = Path(sql_module.__file__).read_text(encoding="utf-8")
    functions: dict[str, ast.AST] = {}
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            functions[node.name] = node
    facts = {name: _function_facts(function) for name, function in functions.items()}

    def reachable_writes(name: str, seen: set[str]) -> set[str]:
        if name in seen or name not in facts:
            return set()
        seen.add(name)
        writes, calls = facts[name]
        return set(writes).union(*(reachable_writes(callee, seen) for callee in calls)) if calls else set(writes)

    writers: dict[str, set[str]] = {}
    for projector_name, entry in _DISPATCH_ENTRY.items():
        for model_name in reachable_writes(entry, set()):
            model = getattr(models_module, model_name, None)
            if model is None:
                continue
            writers.setdefault(model.__table__.name, set()).add(projector_name)
    return writers


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
        condition = _replay_observation_condition("task-heartbeat", "1", ReplaySelector(task_id=populated["task_a"]))
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
        condition = _replay_observation_condition("task-control", "1", ReplaySelector(ingest_from=1, ingest_to=2))
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
            "1",
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
            "1",
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
                "1",
                ReplaySelector(occurred_from=_OCCURRED_AT, occurred_to=_OCCURRED_AT + timedelta(hours=1)),
            )
        assert caught.value.reason == "time_filter_unsupported"

    def test_a_kindless_projector_still_accepts_a_task_or_ingest_filter(self) -> None:
        assert _replay_observation_condition("task-spawn-reconcile", "1", ReplaySelector(task_id=new_id())) is not None
        assert _replay_observation_condition("task-spawn-reconcile", "1", ReplaySelector(ingest_from=1, ingest_to=5)) is not None


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


class TestOwnershipIsConservativeInFact:
    """The map states a rule; these pin that the entries obey it.

    Review finding F1: ``ansich_steps`` sat in ``task-step``'s owned tuple while
    ``task-control``'s branch writes ``status`` on it through
    ``_close_settled_acting_steps``. The partition test could not see that --
    it proves disjointness and coverage, which a wrong *assignment* satisfies
    perfectly. So the rule itself is checked here.
    """

    def test_steps_are_shared_because_task_control_closes_them(self) -> None:
        """The concrete regression, named so the reason survives the fix.

        On a terminal Task Observation ``_project_control`` calls
        ``_close_settled_acting_steps``, which flips ``ansich_steps.status`` to
        ``closed``. If ``task-step`` owned the table, T5's
        ``--replace --projector task-step`` would delete every Step and
        re-derive from ``task-step``'s Observations alone: every Step
        ``task-control`` had closed comes back ``acting`` and stays that way,
        because nothing re-pends the ``task-control`` job that closed it.
        """

        owned = {model for models in _PROJECTOR_OWNED_TABLES.values() for model in models}
        assert AnsichStepRow not in owned
        assert AnsichStepRow in _SHARED_REBUILT_TABLES

    def test_no_owned_table_is_written_from_a_second_dispatch_branch(self) -> None:
        """The rule, mechanised: one writing branch per owned table.

        A static walk from each ``project_pending`` dispatch entry through the
        helpers it calls, collecting the tables each one writes. It is a
        deliberate **lower bound** on writes -- it sees constructor calls, bulk
        ``delete``/``update``/upsert statements, and attribute assignment on a
        local bound from a ``select``/``get`` of one model, which is the shape
        ``_close_settled_acting_steps`` uses -- so a table it clears is not
        thereby proven exclusive. What it does catch is exactly the class of
        mistake F1 was, and catching that class is the point: the alternative
        is re-deriving this by hand every time a projector gains a helper.
        """

        writers = _dispatch_branch_writers()
        for projector_name, models in _PROJECTOR_OWNED_TABLES.items():
            for model in models:
                branches = writers.get(model.__table__.name, set())
                assert branches <= {projector_name}, f"{model.__table__.name} is claimed by {projector_name} but written from {sorted(branches)}"


class TestDigestExcludesWallClockColumns:
    """Review finding F5: a digest must not hash "when the projection ran".

    Two columns default to ``_utc_now`` inside a projector's owned set
    (``ansich_content_occurrences.created_at``,
    ``ansich_context_states.created_at``). Today a double replay agrees anyway,
    because those rows are inserted only if absent and a replay never deletes
    them -- so the wall clock is never re-stamped. T5's ``--replace`` deletes
    them and re-derives, and the §11 digests would then differ **by
    construction** with nothing going red, because the §11 test drives
    ``task-heartbeat``, whose one owned table has no such column.
    """

    def test_the_excluded_set_is_exactly_the_wall_clock_defaults(self) -> None:
        expected = {
            ("ansich_content_occurrences", "created_at"),
            ("ansich_context_states", "created_at"),
            ("ansich_environment_coverage", "updated_at"),
            ("ansich_environment_state", "updated_at"),
        }
        assert _DIGEST_EXCLUDED_COLUMNS == expected

    @pytest.mark.anyio
    async def test_an_excluded_column_cannot_move_the_digest(
        self,
        backend: tuple[SqlAnsichBackend, async_sessionmaker],
        populated: dict[str, object],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The mechanism, driven on a table the fixture actually populates.

        The four real exclusions live on tables this fixture has no rows for
        (they need step/tool/environment Observations), so the exclusion is
        exercised by pointing it at a heartbeat column instead. What is under
        test is that an excluded column is genuinely dropped from the payload,
        not which columns are on the list -- that is the structural pin above.
        """

        sql_backend, sessions = backend
        monkeypatch.setattr(
            "deerflow.ansich.persistence.sql._DIGEST_EXCLUDED_COLUMNS",
            {("ansich_task_heartbeats", "elapsed_ms")},
        )
        before = await sql_backend.read_model_digest("task-heartbeat")
        async with sessions() as session, session.begin():
            row = await session.scalar(select(AnsichTaskHeartbeatRow).limit(1))
            row.elapsed_ms = row.elapsed_ms + 4242
        assert await sql_backend.read_model_digest("task-heartbeat") == before


class TestDurableFailuresAreNotSilent:
    @pytest.mark.anyio
    async def test_a_durably_failed_job_in_the_target_blocks_the_digest(
        self,
        backend: tuple[SqlAnsichBackend, async_sessionmaker],
        populated: dict[str, object],
    ) -> None:
        """Review finding F3. ``failed`` is settled, badly -- and not `unsettled`.

        ``unsettled_job_count`` counts pending/retry/processing only, so a
        durably failed job is the one state in which owned rows are *known*
        never to have been written and the old gate did not fire. A digest over
        that store is the precise thing the gate exists to refuse.
        """

        sql_backend, sessions = backend
        other_task_heartbeat = sorted(populated["all_heartbeats"] - populated["heartbeats_a"])[0]
        async with sessions() as session, session.begin():
            await session.execute(
                update(AnsichProjectionJobRow)
                .where(
                    AnsichProjectionJobRow.projector_name == "task-heartbeat",
                    AnsichProjectionJobRow.obs_id == other_task_heartbeat,
                )
                .values(status="failed", attempts=5, last_error="poisoned")
            )

        report = await execute_replay(
            sql_backend,
            projector_name="task-heartbeat",
            projector_version="1",
            # Deliberately not the failed row's Task: a replay that re-pended it
            # would have repaired the very state under test.
            selector=ReplaySelector(task_id=populated["task_a"]),
        )
        assert report.unsettled == 0
        assert report.failed == 1
        assert report.digest is None
        assert any("durably failed" in error for error in report.errors)

    @pytest.mark.anyio
    async def test_a_replay_refreshes_the_process_failed_job_count(
        self,
        backend: tuple[SqlAnsichBackend, async_sessionmaker],
        populated: dict[str, object],
    ) -> None:
        """Review finding F4: an operator's own remedy left the service degraded.

        The re-pend clears ``failed`` rows in the database, but
        ``SqlAnsichBackend._failed_jobs`` -- what the process-local health block
        reports, and what ``lifecycle.derive_status`` keys ``degraded`` on -- is
        only recomputed at start, rebuild, retry and the assessor-error path.
        Without a refresh here, a successful replay leaves the service reporting
        ``degraded`` for the rest of the process's life beside a database block
        that says ``failed_jobs: 0``.
        """

        sql_backend, sessions = backend
        async with sessions() as session, session.begin():
            await session.execute(update(AnsichProjectionJobRow).where(AnsichProjectionJobRow.projector_name == "task-heartbeat").values(status="failed", attempts=5, last_error="poisoned"))
        sql_backend._failed_jobs = 5

        report = await execute_replay(sql_backend, projector_name="task-heartbeat", projector_version="1", selector=ReplaySelector())
        assert report.failed == 0
        assert sql_backend.get_projection_metrics()["failed_jobs"] == 0

    @pytest.mark.anyio
    async def test_the_drive_loop_cannot_spin_forever_inside_one_round(
        self,
        backend: tuple[SqlAnsichBackend, async_sessionmaker],
        populated: dict[str, object],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Review finding F8: only the outer round count was bounded.

        A store ingesting faster than the loop drains would keep
        ``project_pending`` returning non-zero, and the inner ``while`` exits
        only on a zero. The rebuild has the same shape but holds both locks
        while it does it; the replay's drive loop deliberately holds neither, so
        it is the more exposed of the two. Simulated with a claim that never
        runs dry.
        """

        sql_backend, _ = backend
        calls = {"count": 0}

        async def never_dry(*, limit: int = 200) -> int:
            calls["count"] += 1
            return 1

        monkeypatch.setattr(sql_backend, "project_pending", never_dry)
        report = await execute_replay(
            sql_backend,
            projector_name="task-heartbeat",
            projector_version="1",
            selector=ReplaySelector(),
            max_rounds=2,
            max_drain_batches=3,
        )
        assert calls["count"] == 6
        assert report.replayed == 6


class TestRefusalCarriesTheVersion:
    def test_a_time_filter_refusal_names_the_version_that_was_asked_for(self) -> None:
        """Review finding F6. Every other refusal in the taxonomy carries it."""

        with pytest.raises(ReplayTargetError) as caught:
            _replay_observation_condition(
                "task-spawn-reconcile",
                "1",
                ReplaySelector(occurred_from=_OCCURRED_AT, occurred_to=_OCCURRED_AT + timedelta(hours=1)),
            )
        assert caught.value.reason == "time_filter_unsupported"
        assert caught.value.projector_version == "1"


class TestExitCodesAreHonest:
    """Review finding F2: the exit code was the only machine-readable half."""

    def _report(self, **overrides: object) -> ReplayReport:
        base = {
            "projector_name": "task-heartbeat",
            "projector_version": "1",
            "targeted": 3,
            "minted": 0,
            "re_pended": 3,
            "replayed": 3,
            "unsettled": 0,
            "failed": 0,
            "digest": "abc",
            "dry_run": False,
        }
        return ReplayReport(**{**base, **overrides})

    def test_durably_failed_jobs_page(self) -> None:
        """``unsettled`` excludes ``failed``, so this used to exit ``0``.

        A cron wrapper that pages on non-zero accepted a replay that left N
        projections permanently unlanded, with the fact visible only in prose
        the CLI's own docstring says a script will get wrong.
        """

        assert replay_cli.exit_code(self._report(failed=2, digest=None, errors=("2 job(s) durably failed",))) == 1

    def test_a_projector_owning_no_table_still_exits_clean(self) -> None:
        """The false alarm the obvious fix would introduce.

        ``digest is None`` is not by itself an incomplete pass: three
        projectors own no table exclusively and honestly have no digest, and
        paging on that would train an operator to ignore the exit code.
        """

        assert replay_cli.exit_code(self._report(projector_name="task-structural", digest=None)) == 0

    def test_unsettled_work_pages_and_a_clean_pass_does_not(self) -> None:
        assert replay_cli.exit_code(self._report(unsettled=2, digest=None)) == 1
        assert replay_cli.exit_code(self._report()) == 0
        assert replay_cli.exit_code(self._report(dry_run=True, digest=None)) == 0


# ---------------------------------------------------------------------------
# T5: `--replace`
# ---------------------------------------------------------------------------


def _new_id_bound_names(function: ast.AST) -> set[str]:
    """Names this function binds to a ``new_id()`` call.

    One level, deliberately: ``window_id = new_id()`` is the shape the audit
    below has to see through, and chasing further would trade a fact for an
    inference.
    """

    bound: set[str] = set()
    for node in ast.walk(function):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) and node.value.func.id == "new_id":
            bound.add(node.targets[0].id)
    return bound


def _minted_primary_key_columns() -> set[tuple[str, str]]:
    """``(table, column)`` for every owned-table primary key set from ``new_id()``.

    Walks ``sql.py`` for the two forms a projector writes a row in: the ORM
    constructor (``AnsichXRow(pk=...)``) and the dict handed to
    ``_insert_ignoring_conflict``. A primary-key value that is ``new_id()`` --
    directly, or through a local the same function bound to it -- is a key that
    is *minted*, not derived from the Observation, which is the property
    ``--replace`` cannot survive.
    """

    owned = {model.__name__: model for models in _PROJECTOR_OWNED_TABLES.values() for model in models}
    source = Path(sql_module.__file__).read_text(encoding="utf-8")
    minted: set[tuple[str, str]] = set()

    def _is_minted(value: ast.AST, bound: set[str]) -> bool:
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id == "new_id":
            return True
        return isinstance(value, ast.Name) and value.id in bound

    for function in ast.walk(ast.parse(source)):
        if not isinstance(function, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        bound = _new_id_bound_names(function)
        for node in ast.walk(function):
            if not isinstance(node, ast.Call):
                continue
            # Form 1: the ORM constructor.
            if isinstance(node.func, ast.Name) and node.func.id in owned:
                table = owned[node.func.id].__table__
                keys = {column.name for column in table.primary_key.columns}
                minted |= {(table.name, keyword.arg) for keyword in node.keywords if keyword.arg in keys and _is_minted(keyword.value, bound)}
            # Form 2: `_insert_ignoring_conflict(session, Model, {...})`.
            model_arguments = [argument for argument in node.args if isinstance(argument, ast.Name) and argument.id in owned]
            dict_arguments = [argument for argument in node.args if isinstance(argument, ast.Dict)]
            for model_argument in model_arguments:
                table = owned[model_argument.id].__table__
                keys = {column.name for column in table.primary_key.columns}
                for mapping in dict_arguments:
                    for key, value in zip(mapping.keys, mapping.values, strict=True):
                        if isinstance(key, ast.Constant) and key.value in keys and _is_minted(value, bound):
                            minted.add((table.name, str(key.value)))
    return minted


@pytest.fixture
async def enriched(
    backend: tuple[SqlAnsichBackend, async_sessionmaker],
    populated: dict[str, object],
) -> dict[str, object]:
    """``populated`` plus rows for every projector ``--replace`` is proven for.

    The determinism-through-replace check below is parametrized over
    ``_REPLACE_PROVEN_PROJECTORS`` and asserts a **non-empty** owned row set
    before it compares anything, so this fixture is what stops that check from
    passing vacuously: an empty table hashes equal to an empty table, which is
    the F10-26 mistake in the digest's clothes.
    """

    sql_backend, sessions = backend
    task_a = str(populated["task_a"])
    scope = ObservationEnvelope.scope_snapshotted(
        task_id=task_a,
        run_id="run-a",
        occurred_at=_OCCURRED_AT,
        scope_kind="sandbox",
        external_ref="replace-sandbox",
        relation_role="sandbox_boundary",
        source_event_id="run-a:scope:sandbox",
        producer_seq=1,
    )
    scope_id = scope.subject_id
    envelopes = [
        scope,
        ObservationEnvelope.budget_configured(
            task_id=task_a,
            run_id="run-a",
            occurred_at=_OCCURRED_AT,
            dimension="total_tokens",
            aggregation_scope="local",
            warning_limit=800,
            hard_limit=1000,
            enforcement=True,
            source_kind="release_default",
            requested_value=None,
            effective_value=1000,
            source_event_id="run-a:budget:total_tokens",
        ),
    ]
    for tick in range(1, 4):
        envelopes.append(
            ObservationEnvelope.environment_sampled(
                task_id=task_a,
                run_id="run-a",
                occurred_at=_OCCURRED_AT + timedelta(seconds=tick),
                scope_id=scope_id,
                payload={
                    "environment_scope": "container",
                    "coverage": "continuous",
                    "provider": "local",
                    "metrics": {"fd_open": {"value": 10 + tick, "limit": 1024}},
                    "window": {
                        "started_at": _OCCURRED_AT.isoformat(),
                        "ended_at": (_OCCURRED_AT + timedelta(seconds=tick)).isoformat(),
                        "sample_count": 1,
                    },
                },
                source_event_id=f"run-a:env:{scope_id}:{tick}",
                producer_seq=tick,
            )
        )
    assert await sql_backend.persist_and_project(envelopes) == len(envelopes)
    await _settle(sql_backend)
    await sql_backend.assess_operations()
    await _settle(sql_backend)
    return {**populated, "scope_id": scope_id}


async def _owned_row_count(sessions: async_sessionmaker, projector_name: str) -> int:
    total = 0
    async with sessions() as session:
        for model in _PROJECTOR_OWNED_TABLES[projector_name]:
            total += int(await session.scalar(select(func.count()).select_from(model)) or 0)
    return total


class TestOwnedPrimaryKeysAreDerived:
    """The other half of review finding F5, and the reason it had to be checked.

    Dropping wall-clock columns makes a re-derived row hash the same only if the
    row can be *found* in the same place twice. A primary key minted with
    ``new_id()`` breaks that twice over: the key itself is a fresh value in the
    hashed payload, and it is what the digest orders by -- so two replaces of
    one history would disagree on both the contents and the order, with nothing
    going red, because ``task-heartbeat`` (the §11 driver) has neither.
    """

    def test_the_minted_key_set_is_exactly_what_the_projectors_actually_mint(self) -> None:
        """Audited from the source, not from memory.

        The declared set has to be the AST's answer: an entry that stops being
        minted should stop being excluded, and a table that starts minting one
        must not be able to slip past by nobody re-reading ``sql.py``.
        """

        assert _minted_primary_key_columns() == _DIGEST_RANDOM_KEY_COLUMNS

    def test_the_two_known_minted_keys_are_named(self) -> None:
        """The audit's finding, written down so the reason outlives the fix."""

        assert _DIGEST_RANDOM_KEY_COLUMNS == {
            ("ansich_transitions", "transition_id"),
            ("ansich_context_windows", "entity_id"),
        }

    def test_every_minted_key_table_orders_by_a_unique_derived_key(self) -> None:
        """Excluding the column is not enough -- the *order* has to survive too.

        A surrogate order that is not unique is not an order at all: two rows
        sharing its value would come back in whatever order the storage engine
        felt like, and the digest would report a difference that is not one. So
        each surrogate is checked against a real uniqueness constraint on the
        table, and against not being minted itself.
        """

        assert set(_DIGEST_SURROGATE_ORDER) == {table for table, _ in _DIGEST_RANDOM_KEY_COLUMNS}
        for table_name, order in _DIGEST_SURROGATE_ORDER.items():
            table = Base.metadata.tables[table_name]
            assert order, f"{table_name} declares an empty surrogate order"
            unique_columns = {(column.name,) for column in table.columns if column.unique} | {tuple(constraint.columns.keys()) for constraint in table.constraints if isinstance(constraint, UniqueConstraint)}
            assert tuple(order) in unique_columns, f"{table_name} orders by {order}, which nothing makes unique"
            assert all((table_name, column) not in _DIGEST_RANDOM_KEY_COLUMNS for column in order)

    @pytest.mark.anyio
    async def test_a_minted_key_cannot_move_the_digest(
        self,
        backend: tuple[SqlAnsichBackend, async_sessionmaker],
        populated: dict[str, object],
    ) -> None:
        """The mechanism, driven: rewrite the key, keep the facts, same digest.

        ``ansich_transitions`` is the table the audit found, and this rewrites
        every ``transition_id`` in place. Nothing an Observation said has
        changed, so the digest must not move -- which is exactly what a replace
        that re-derives these rows would do to them.
        """

        sql_backend, sessions = backend
        before = await sql_backend.read_model_digest("task-control")
        assert before is not None
        async with sessions() as session, session.begin():
            rows = list((await session.execute(select(AnsichTransitionRow))).scalars().all())
            assert rows, "the fixture must produce transitions for this to mean anything"
            for row in rows:
                await session.delete(row)
            await session.flush()
            for row in rows:
                session.add(
                    AnsichTransitionRow(
                        **{
                            **{column.name: getattr(row, column.name) for column in AnsichTransitionRow.__table__.columns},
                            "transition_id": new_id(),
                        }
                    )
                )
        assert await sql_backend.read_model_digest("task-control") == before


class TestReplaceIsRefusedWhereItCannotBeHonoured:
    """RC4's narrowing, and the one this task had to add on top of it."""

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "selector",
        [
            ReplaySelector(task_id="task-7"),
            ReplaySelector(ingest_from=1, ingest_to=2),
            ReplaySelector(occurred_from=_OCCURRED_AT, occurred_to=_OCCURRED_AT + timedelta(hours=1)),
        ],
        ids=["task", "ingest", "time"],
    )
    async def test_a_filtered_replace_is_refused(
        self,
        backend: tuple[SqlAnsichBackend, async_sessionmaker],
        populated: dict[str, object],
        selector: ReplaySelector,
    ) -> None:
        """Ruling RC4: replace is whole-table, so a filter is a contradiction.

        The delete cannot honour the filter -- read models carry no row-level
        provenance back to the Observation that produced them -- so a filtered
        replace would delete far more than it re-derives and silently lose every
        row outside the window. Refusing costs the operator one message; the
        alternative costs them the table.
        """

        sql_backend, sessions = backend
        before = await _row_counts(sessions)
        with pytest.raises(ReplayTargetError) as caught:
            await execute_replay(
                sql_backend,
                projector_name="task-heartbeat",
                projector_version="1",
                selector=selector,
                replace=True,
            )
        assert caught.value.reason == "filtered_replace_unsupported"
        assert caught.value.projector_version == "1"
        assert await _row_counts(sessions) == before

    @pytest.mark.anyio
    async def test_a_projector_whose_restore_is_unproven_is_refused(
        self,
        backend: tuple[SqlAnsichBackend, async_sessionmaker],
        populated: dict[str, object],
    ) -> None:
        """Exclusive ownership is necessary for replace and **not sufficient**.

        ``task-control`` owns ``ansich_transitions`` outright -- no other
        dispatch branch writes it -- and a replace of it still cannot restore
        what it deletes: ``_project_control`` computes ``from_value`` from the
        *current control Belief*, which lives in the shared Belief triple that a
        projector-scoped replace neither owns nor clears. Re-deriving after the
        delete therefore reads a Belief that already carries the destination
        value and writes ``running -> running`` where history had
        ``unknown -> created`` and ``created -> running``.
        """

        sql_backend, sessions = backend
        before = await _row_counts(sessions)
        with pytest.raises(ReplayTargetError) as caught:
            await execute_replay(
                sql_backend,
                projector_name="task-control",
                projector_version="1",
                selector=ReplaySelector(),
                replace=True,
            )
        assert caught.value.reason == "replace_restore_unproven"
        assert "task-control" in str(caught.value)
        assert await _row_counts(sessions) == before

    @pytest.mark.anyio
    async def test_a_dry_run_refuses_the_same_requests(
        self,
        backend: tuple[SqlAnsichBackend, async_sessionmaker],
        populated: dict[str, object],
    ) -> None:
        """``--dry-run`` exists to find this out cheaply, so it must find it out."""

        sql_backend, _ = backend
        with pytest.raises(ReplayTargetError):
            await plan_replay(
                sql_backend,
                projector_name="task-heartbeat",
                projector_version="1",
                selector=ReplaySelector(task_id="task-7"),
                replace=True,
            )
        with pytest.raises(ReplayTargetError):
            await plan_replay(
                sql_backend,
                projector_name="task-control",
                projector_version="1",
                selector=ReplaySelector(),
                replace=True,
            )

    def test_every_proven_projector_owns_something_to_replace(self) -> None:
        """A proven projector that owns nothing would be a no-op wearing a flag."""

        assert _REPLACE_PROVEN_PROJECTORS
        for projector_name in _REPLACE_PROVEN_PROJECTORS:
            assert _PROJECTOR_OWNED_TABLES[projector_name], f"{projector_name} is declared replaceable but owns no table"


class TestReplaceIsProjectorScoped:
    @pytest.mark.anyio
    async def test_replace_deletes_the_owned_tables_and_nothing_else(
        self,
        backend: tuple[SqlAnsichBackend, async_sessionmaker],
        enriched: dict[str, object],
    ) -> None:
        """The F1 lesson, driven on rows rather than on the map.

        Three assertions, and the first is the one that gives the other two
        teeth: a row nothing in the Observation stream produces is planted in
        the target's own table and must be **gone** afterwards, which is how a
        genuine whole-table delete is told apart from a replay that merely
        overwrote what it found. The sibling projectors' rows -- ``task-control``'s
        transitions and ``task-budget``'s budget row -- must be untouched, and
        the target's real rows must be back.
        """

        sql_backend, sessions = backend
        async with sessions() as session, session.begin():
            session.add(
                AnsichTaskHeartbeatRow(
                    heartbeat_obs_id=new_id(),
                    task_id=str(enriched["task_a"]),
                    occurred_at=_OCCURRED_AT,
                    producer_instance_id="planted-by-nothing",
                    ownership_epoch="planted",
                    elapsed_ms=999_999,
                )
            )
        planted = await _owned_row_count(sessions, "task-heartbeat")
        async with sessions() as session:
            transitions_before = sorted((await session.execute(select(AnsichTransitionRow.transition_id))).scalars().all())
            budgets_before = sorted((await session.execute(select(AnsichTaskBudgetRow.entity_id))).scalars().all())
        assert transitions_before
        assert budgets_before

        report = await execute_replay(
            sql_backend,
            projector_name="task-heartbeat",
            projector_version="1",
            selector=ReplaySelector(),
            replace=True,
        )

        assert report.unsettled == 0
        assert report.failed == 0
        assert await _owned_row_count(sessions, "task-heartbeat") == planted - 1
        async with sessions() as session:
            assert sorted((await session.execute(select(AnsichTransitionRow.transition_id))).scalars().all()) == transitions_before
            assert sorted((await session.execute(select(AnsichTaskBudgetRow.entity_id))).scalars().all()) == budgets_before

    @pytest.mark.anyio
    async def test_the_frozen_read_model_delete_still_fires_on_the_replace_path(
        self,
        backend: tuple[SqlAnsichBackend, async_sessionmaker],
        populated: dict[str, object],
    ) -> None:
        """PB7 is not suspended because the operator asked for a replace.

        The replace-delete joins ``mint_replay_jobs``' transaction; the
        active-Task read-model clear is the *last* step of that same
        transaction, and it has nothing to do with ownership -- it exists
        because the re-pend lowers ``min(unsettled ingest_seq)`` and would
        otherwise freeze the publish guard shut (ruling RC3).
        """

        sql_backend, sessions = backend
        await sql_backend.assess_operations()
        async with sessions() as session:
            before = int(await session.scalar(select(func.count()).select_from(AnsichActiveTaskReadModelRow)) or 0)
        assert before > 0

        cleared: list[int] = []
        original = sql_backend._clear_frozen_active_task_rows

        async def instrumented(session, **kwargs):
            deleted = await original(session, **kwargs)
            cleared.append(deleted)
            return deleted

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(sql_backend, "_clear_frozen_active_task_rows", instrumented)
            await execute_replay(
                sql_backend,
                projector_name="task-heartbeat",
                projector_version="1",
                selector=ReplaySelector(),
                replace=True,
            )
        assert cleared == [before]

    @pytest.mark.anyio
    async def test_a_dry_run_replace_writes_nothing(
        self,
        backend: tuple[SqlAnsichBackend, async_sessionmaker],
        populated: dict[str, object],
    ) -> None:
        """Asking what a replace would delete must not delete it."""

        sql_backend, sessions = backend
        before = await _row_counts(sessions)
        report = await plan_replay(
            sql_backend,
            projector_name="task-heartbeat",
            projector_version="1",
            selector=ReplaySelector(),
            replace=True,
        )
        assert await _row_counts(sessions) == before
        assert report.dry_run is True
        assert any("replace" in note for note in report.errors)


class TestReplaceIsDeterministic:
    """Spec §11's determinism acceptance, taken **through** ``--replace``.

    This is what ``_REPLACE_PROVEN_PROJECTORS`` means. A projector is listed
    there because this test passes for it, not because someone read its code
    and believed it: the parametrization is over the set itself, so adding a
    member whose owned tables cannot be re-derived from the Observation stream
    alone turns this red rather than shipping a silent data loss.
    """

    @pytest.mark.anyio
    @pytest.mark.parametrize("projector_name", sorted(_REPLACE_PROVEN_PROJECTORS))
    async def test_replace_reproduces_the_pre_replace_digest(
        self,
        backend: tuple[SqlAnsichBackend, async_sessionmaker],
        enriched: dict[str, object],
        projector_name: str,
    ) -> None:
        sql_backend, sessions = backend
        assert await _owned_row_count(sessions, projector_name) > 0, f"{projector_name} owns no rows here, so the comparison below would be vacuous"

        first = await execute_replay(sql_backend, projector_name=projector_name, projector_version="1", selector=ReplaySelector())
        assert first.unsettled == 0
        assert first.failed == 0
        assert first.digest is not None

        second = await execute_replay(sql_backend, projector_name=projector_name, projector_version="1", selector=ReplaySelector(), replace=True)
        assert second.unsettled == 0
        assert second.failed == 0
        assert second.digest == first.digest
        assert await _owned_row_count(sessions, projector_name) > 0


class TestReplaceCli:
    def test_the_replace_flag_reaches_the_module(self) -> None:
        args = replay_cli.build_parser().parse_args(["--projector", "task-heartbeat", "--version", "1", "--replace"])
        assert args.replace is True
        assert replay_cli.build_parser().parse_args(["--projector", "task-heartbeat", "--version", "1"]).replace is False
