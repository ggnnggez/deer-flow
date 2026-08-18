"""Settle-timing isolation for the Ansich SQL integration tests.

``AnsichService._projector_loop`` calls ``assess_operations()`` on its very
first iteration and then once every ``operations_assessment_interval_ms``.
That is correct for production — periodic assessment is the loop's job — but
it makes the loop a second, invisible writer for any test that drives
assessment itself: those tests pass a *simulated* ``now`` and then assert on
the assessor jobs, watermarks and Belief Assertions that assessment produced.
The background call uses the wall clock, claims the same assessor jobs, and
under suite load lands at an arbitrary point in the test body instead of
harmlessly before the first Observation. The result is an outcome-racing
test: green when the loop is early, red when it slips between two reads.

Phase 7 M2 closed one instance of this by installing the test's hooks before
``start()`` (``e91d9f1c``) and by making the direct SQL factory patient about
projection settling (``4e5eb0fd``). Neither closes the window for a test whose
assertions describe *which* assessment ran, and no timeout can: the wait
target is another writer, not a slow one. Such tests take ownership of
assessment scheduling instead — the projector loop keeps projecting, only its
periodic assessment falls silent.
"""

from __future__ import annotations

import asyncio
from datetime import datetime

from ansich import AnsichService


def only_test_driven_assessments(service: AnsichService) -> None:
    """Silence the projector loop's own ``assess_operations()`` calls.

    Call it from the test's own task, before ``await service.start()`` (the
    ordering discipline of ``e91d9f1c``: install the hook before the loop that
    it gates can run). Afterwards every assessment in the test is one the test
    asked for, so the state it asserts on is a function of its own calls
    rather than of how loaded the machine was.

    ``rebuild_projections()`` is unaffected: it reaches the backend through
    ``_assess_operations_unlocked`` and still re-assesses after a replay.
    """

    test_task = asyncio.current_task()
    if test_task is None:  # pragma: no cover - defensive, tests are async
        raise RuntimeError("only_test_driven_assessments must be called from the test task")
    original = service.assess_operations

    async def assess_operations(*, now: datetime | None = None) -> int:
        if asyncio.current_task() is not test_task:
            return 0
        return await original(now=now)

    service.assess_operations = assess_operations  # type: ignore[method-assign]
