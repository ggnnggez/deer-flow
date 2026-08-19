"""Process-local lifecycle state derivation for the Ansich collector.

Spec 11 §2 fixes the in-process state machine::

    starting -> healthy -> degraded -> recovering -> healthy
                             \\-> failed
    healthy/degraded -> shutting_down -> stopped

:data:`LEGAL_TRANSITIONS` is that graph enumerated edge for edge, and
:func:`derive_status` answers "which state is this" from the collector's current
facts alone. The derivation is deliberately memoryless: it holds no previous
state, so it cannot drift out of sync with the service it describes, and every
caller reading the same inputs gets the same answer.

This module is framework-independent (pydantic only) like the rest of
``ansich``: no ``deerflow`` or ``app`` imports.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

LEGAL_TRANSITIONS: frozenset[tuple[str, str]] = frozenset(
    {
        ("starting", "healthy"),
        ("healthy", "degraded"),
        ("degraded", "recovering"),
        ("recovering", "healthy"),
        ("degraded", "failed"),
        ("healthy", "shutting_down"),
        ("degraded", "shutting_down"),
        ("shutting_down", "stopped"),
    }
)
"""Spec 11 §2's graph, edge for edge.

Staying in one state is not a transition and is therefore not listed; a
consumer clamping a sequence compares only the pairs where the state changed.
"""


class LifecycleInputs(BaseModel):
    """Everything :func:`derive_status` is allowed to look at.

    No field carries a default: each one is a fact somebody has to measure, and
    a default would let a caller that forgot to wire a signal report a quiet
    collector instead of an unknown one.
    """

    model_config = ConfigDict(frozen=True)

    started: bool
    stopping: bool
    stopped: bool
    unavailable_reason: str | None
    consecutive_write_failures: int
    dropped_count: int
    failed_jobs: int
    queue_depth: int
    batch_size: int
    unreported_loss_pending: bool


def derive_status(inputs: LifecycleInputs) -> str:
    """Return the current lifecycle state, one of the seven spec §2 states.

    The rules are ordered, most decisive first:

    ``stopped``
        Shutdown finished. Nothing else can be true of a stopped collector.
    ``shutting_down``
        Shutdown is running. The drain's own backlog and write failures are
        expected during it and must not be reported as degradation.
    ``starting``
        ``start()`` has not run yet. Nothing has had a chance to fail, so a
        pre-start collector is never ``failed``, ``degraded`` or ``recovering``.
    ``failed``
        Storage is unavailable — the collector cannot persist anything.
    ``degraded``
        An active failure signal: the writer is failing (
        ``consecutive_write_failures``), Observations were dropped
        (``dropped_count``), or projection jobs are failing (``failed_jobs``).
        Note that ``dropped_count`` keeps this answer permanently: loss is a
        fact, not a transient, and a later drain cannot make a lost range
        un-lost. Spec §2's ``recovering`` covers the write-failure recovery
        path only.
    ``recovering``
        No active failure, but the collector is still catching up: the queue
        holds more than one batch, or a known lost range has not been reported
        into the Observation stream yet.
    ``healthy``
        Everything above is quiet.
    """

    if inputs.stopped:
        return "stopped"
    if inputs.stopping:
        return "shutting_down"
    if not inputs.started:
        return "starting"
    if inputs.unavailable_reason is not None:
        return "failed"
    if inputs.consecutive_write_failures > 0 or inputs.dropped_count > 0 or inputs.failed_jobs > 0:
        return "degraded"
    if inputs.queue_depth > inputs.batch_size or inputs.unreported_loss_pending:
        return "recovering"
    return "healthy"
