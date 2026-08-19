"""Process-local lifecycle state derivation for the Ansich collector.

Spec 11 §2 fixes the in-process state machine::

    starting -> healthy -> degraded -> recovering -> healthy
                             \\-> failed
    healthy/degraded -> shutting_down -> stopped

That sketch is the *nominal story* — one clean run from start to stop. It is
not the closure of what a collector can do, and :data:`LEGAL_TRANSITIONS` is
therefore wider than it: real operation also takes operator-recovery shortcuts
(a retried projection job clears outright), boundary failures (the first
post-start read already sees a loaded failure), and restart. Treating the
sketch as exhaustive would make a clamp that fails on ordinary operation, so
this widening is a deliberate, recorded deviation from the spec text rather
than a re-reading of it.

:func:`derive_status` answers "which state is this" from the collector's
current facts alone. The derivation is deliberately memoryless: it holds no
previous state, so it cannot drift out of sync with the service it describes,
and every caller reading the same inputs gets the same answer.

This module is framework-independent (pydantic only) like the rest of
``ansich``: no ``deerflow`` or ``app`` imports.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

LEGAL_TRANSITIONS: frozenset[tuple[str, str]] = frozenset(
    {
        # -- spec §2's nominal arc, edge for edge ------------------------------
        ("starting", "healthy"),
        ("healthy", "degraded"),
        ("degraded", "recovering"),
        ("recovering", "healthy"),
        ("degraded", "failed"),
        ("healthy", "shutting_down"),
        ("degraded", "shutting_down"),
        ("shutting_down", "stopped"),
        # -- operator recovery -------------------------------------------------
        # A retried projection job clears `failed_jobs` outright, leaving no
        # residue to catch up on, so degradation can end without `recovering`.
        ("degraded", "healthy"),
        # A fresh failure arrives while the previous one is still catching up.
        ("recovering", "degraded"),
        # -- shutdown does not wait for the arc to finish ----------------------
        # `stop()` may be called in any running state, including mid-recovery
        # and on a service whose storage was never available.
        ("recovering", "shutting_down"),
        ("failed", "shutting_down"),
        # -- boundary: the first read after start ------------------------------
        # `initialize_metrics` can load `failed_jobs > 0` before the service is
        # marked started, so the first post-start read is already degraded.
        ("starting", "degraded"),
        # `unavailable_reason` is fixed at construction, so an unavailable
        # service is failed from its very first post-start read.
        ("starting", "failed"),
        # A restarted instance inherits the previous run's residue in process.
        ("starting", "recovering"),
        # A `start()` that raises leaves the service as stopped as it was.
        ("starting", "stopped"),
        # -- restart -----------------------------------------------------------
        # `start()` re-arms its flags before the first await, so a stopped
        # service is seen starting again rather than jumping back into service.
        ("stopped", "starting"),
    }
)
"""Every status change a live collector can take.

Contains spec §2's arc plus the reachable edges enumerated above. Staying in
one state is not a transition and is therefore not listed; a consumer clamping a
sequence compares only the pairs where the state changed.

The closure is computed for the *post-PA6* derivation, where ``recovering``
comes from the recovery residue (``unreported_loss_pending``, and from Task 4
the writer's retry backlog) rather than from a bare queue backlog. Task 4
removes that backlog clause and re-verifies this set against the real writer
state.
"""


class LifecycleInputs(BaseModel):
    """Everything :func:`derive_status` is allowed to look at.

    No field carries a default: each one is a fact somebody has to measure, and
    a default would let a caller that forgot to wire a signal report a quiet
    collector instead of an unknown one. ``extra="forbid"`` closes the other
    half of that mis-wire: a misspelled signal is an error, not a value the
    derivation silently ignores.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

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
