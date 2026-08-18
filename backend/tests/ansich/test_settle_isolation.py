"""Regression nails for the settle-timing isolation this suite depends on (F10-10).

Both mechanisms are silent when they break: the suite stays green on an idle
machine and starts rotating red only under load, which is exactly the failure
mode F10-10 was opened for. They are therefore pinned here rather than left to
the tests that consume them.
"""

import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from support.ansich_settle import only_test_driven_assessments


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
    asserted_at = datetime(2026, 8, 19, tzinfo=UTC)

    own = await service.assess_operations(now=asserted_at)
    background = await asyncio.create_task(service.assess_operations())

    assert own == 1
    assert background == 0
    assert service.calls == [asserted_at]


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
