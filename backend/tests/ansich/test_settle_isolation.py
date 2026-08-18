"""Regression nails for the settle-timing isolation this suite depends on (F10-10).

Both mechanisms are silent when they break: the suite stays green on an idle
machine and starts rotating red only under load, which is exactly the failure
mode F10-10 was opened for. They are therefore pinned here rather than left to
the tests that consume them.
"""

import asyncio
from datetime import UTC, datetime

import pytest
from ansich import AnsichService
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from support.ansich_settle import only_test_driven_assessments

from deerflow.ansich.persistence.sql import SqlAnsichBackend
from deerflow.persistence.base import Base

ASSERTED_AT = datetime(2026, 8, 19, tzinfo=UTC)


class _RecordingService:
    """Duck-typed stand-in: the helper only rebinds ``assess_operations``."""

    def __init__(self) -> None:
        self.calls: list[datetime | None] = []

    async def assess_operations(self, *, now: datetime | None = None) -> int:
        self.calls.append(now)
        return 1


@pytest.mark.anyio
async def test_only_test_driven_assessments_silences_the_projector_loops_own_calls() -> None:
    service = _RecordingService()
    only_test_driven_assessments(service)

    own = await service.assess_operations(now=ASSERTED_AT)
    background = await asyncio.create_task(service.assess_operations())

    assert own == 1
    assert background == 0
    assert service.calls == [ASSERTED_AT]


@pytest.mark.anyio
async def test_the_gate_covers_the_call_a_real_projector_loop_actually_makes(tmp_path, monkeypatch) -> None:
    """The pin above proves task discrimination; this one proves the attachment point.

    The gate rebinds the *public* ``AnsichService.assess_operations`` because
    that is the method ``_projector_loop`` calls — both on its cadence
    (service.py:1227) and in the stop drain (service.py:1247). A refactor that
    let the loop reach ``_assess_operations_unlocked`` directly (tempting: it
    would avoid re-acquiring ``_projection_lock``) would silently turn all 29
    gates in this suite into no-ops with the duck-typed pin still green. So this
    one runs a real service and counts at the backend boundary, the one place
    every assessment path has to pass through.
    """

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'gate-attachment.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    backend = SqlAnsichBackend(session_factory)
    service = AnsichService(
        backend,
        flush_interval_ms=60_000,
        projector_poll_interval_ms=1,
        # One millisecond: every projector-loop iteration is due to assess, so
        # a gate that missed its attachment point cannot stay unnoticed.
        operations_assessment_interval_ms=1,
    )
    assessed_at: list[datetime | None] = []
    iterations = 0
    third_iteration = asyncio.Event()
    original_assess = backend.assess_operations
    original_project = backend.project_pending

    async def counting_assess(**kwargs) -> int:
        assessed_at.append(kwargs.get("now"))
        return await original_assess(**kwargs)

    async def counting_project(**kwargs) -> int:
        nonlocal iterations
        iterations += 1
        if iterations >= 3:
            third_iteration.set()
        return await original_project(**kwargs)

    monkeypatch.setattr(backend, "assess_operations", counting_assess)
    monkeypatch.setattr(backend, "project_pending", counting_project)
    only_test_driven_assessments(service)
    await service.start()
    try:
        # A signal, not a duration: the loop opens every iteration with
        # project_pending, so three of them mean three assessment-due
        # iterations have come and gone.
        async with asyncio.timeout(30):
            await third_iteration.wait()
        loop_initiated = len(assessed_at)
        await service.assess_operations(now=ASSERTED_AT)
        test_driven = len(assessed_at) - loop_initiated
    finally:
        await service.stop()
        await engine.dispose()

    assert loop_initiated == 0
    assert test_driven == 1
    # stop() drains the loop with one last assess_operations; the gate has to
    # cover that path too, so the test's own call stays the only one.
    assert assessed_at == [ASSERTED_AT]


@pytest.mark.anyio
async def test_sqlite_engines_in_this_suite_use_productions_locking_pragmas(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'pragma-parity.db'}")
    try:
        async with engine.connect() as connection:
            journal_mode = await connection.scalar(text("PRAGMA journal_mode"))
            busy_timeout = await connection.scalar(text("PRAGMA busy_timeout"))
    finally:
        await engine.dispose()

    # Bare create_async_engine gives "delete" + 5000; deerflow/persistence/engine.py
    # gives production WAL + 30s, and conftest.py brings this suite in line.
    assert journal_mode == "wal"
    assert busy_timeout == 30_000
