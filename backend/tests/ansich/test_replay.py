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
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, get_args, get_origin

import pytest
from ansich import ObservationEnvelope, new_id
from ansich.contracts import ObservationKind
from ansich.errors import ReplayTargetError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from deerflow.ansich.persistence.models import (
    AnsichProjectionJobRow,
    AnsichProjectorVersionRow,
)
from deerflow.ansich.persistence.sql import (
    _PROJECTOR_KINDS,
    _PROJECTORS,
    _REPLAYABLE_VERSIONS,
    SqlAnsichBackend,
    _projectors_for_kind,
    _validate_replay_target,
)
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
        with pytest.raises(ReplayTargetError) as caught:
            _validate_replay_target("task-structural", "2")
        error = caught.value
        assert isinstance(error, ValueError)
        assert error.projector_name == "task-structural"
        assert error.projector_version == "2"
        message = str(error)
        assert "task-structural" in message
        assert "2" in message


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
