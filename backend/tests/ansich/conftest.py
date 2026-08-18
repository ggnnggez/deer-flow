"""SQLite engine parity for the Ansich SQL integration tests.

Every SQL test in this directory builds its own engine with a bare
``create_async_engine("sqlite+aiosqlite:///...")``, which leaves the file in
rollback-journal mode (``PRAGMA journal_mode=delete``) with the sqlite3
driver's default 5s ``busy_timeout``. Production never runs that way:
``deerflow/persistence/engine.py`` puts every SQLite connection in WAL with a
30s ``busy_timeout``.

The difference only shows up under load, and then it shows up as a spurious
failure rather than a slow one. A started ``AnsichService`` holds several
pooled connections at once — the writer loop, the projector loop and the
test's own sessions — and in rollback-journal mode a connection that has to
upgrade its read transaction to a write one while another connection holds
RESERVED gets SQLITE_BUSY *immediately*: SQLite deliberately skips the busy
handler for that case because retrying it would deadlock. The test then dies
with "database is locked" instead of waiting the timeout out. WAL removes the
upgrade path altogether (readers never block the writer), and the widened
``busy_timeout`` covers the writer-writer contention that remains.

``foreign_keys`` is deliberately *not* set here: it changes what a write is
allowed to do rather than how long it waits, and the tests that want
production FK semantics (``_scope_safety_service``, ``support.ansich_retro``)
already opt in per engine.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import event
from sqlalchemy.engine import Engine


@pytest.fixture(autouse=True)
def production_sqlite_concurrency_pragmas() -> Iterator[None]:
    """Apply production's SQLite locking pragmas to every engine in this suite."""

    def _apply(dbapi_connection: object, _connection_record: object) -> None:
        if "sqlite" not in (type(dbapi_connection).__module__ or ""):
            return
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=30000")
        finally:
            cursor.close()

    event.listen(Engine, "connect", _apply)
    try:
        yield
    finally:
        event.remove(Engine, "connect", _apply)
