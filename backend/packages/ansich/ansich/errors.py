"""Typed errors that cross the ``ansich`` package boundary.

Deliberately dependency-free — no pydantic, no SQLAlchemy, nothing a backend
adapter drags in. That is the whole point: a storage adapter lives outside this
package and is free to import a driver's exception hierarchy, but what it lets
*out* has to be something every caller can name without adopting the adapter's
dependencies.
"""

from __future__ import annotations

from typing import Literal

__all__ = ["ReplayTargetError", "ReplayTargetRefusal", "StorageUnavailableError"]


class StorageUnavailableError(Exception):
    """Storage could not answer a read the caller needed to reach a verdict.

    Raised by a backend adapter when the store is unreachable — locked,
    disconnected, timed out — on a read whose answer the caller cannot proceed
    without. It says *"I could not read"*, never *"it is gone"*: the row it was
    asking about may be perfectly durable, and this error asserts nothing about
    it either way.

    **What an adapter must translate into it** (controller ruling PB6). The
    boundary is that meaning — "could not answer" — not whichever base class a
    driver library happens to hang its failures from. In the SQLAlchemy adapter
    those are four types that do *not* share one branch: ``OperationalError``
    and ``InterfaceError`` are ``DBAPIError`` subclasses, while pool exhaustion
    (``sqlalchemy.exc.TimeoutError``) and a detected disconnect
    (``DisconnectionError``) descend straight from ``SQLAlchemyError``. A catch
    written against ``DBAPIError`` alone therefore leaks the two most likely
    production outages — an exhausted pool above all — straight through this
    boundary untranslated.

    Equally, a failure where storage *did* answer and said no —
    ``ProgrammingError``, ``IntegrityError``, ``DataError`` — is a **bug**, not
    unavailability, and must not be translated. Typing a malformed statement or
    a violated constraint as "unavailable" tells the caller to retry something
    that can never succeed.

    Its first user is ``AnsichService.record_evaluation``'s replay lookup
    (F10-25), and the way it is *not* handled there is the part worth keeping:

    * The receipt is **not** answered ``failed``. ``failed`` means "I know it
      was lost", while this condition is "I do not know whether this is a
      replay" — reporting ignorance as knowledge is the worse of the two lies.
      No fourth ``EvaluationProjectionStatus`` value is minted for it either;
      the receipt's vocabulary is unchanged.
    * The error is **not** swallowed so the write can proceed anyway. Skipping
      the dedupe would record a second Observation for the same evaluation and
      hand back a receipt pointing at it — a phantom id, and the worst of the
      three options.

    So the condition is named and re-raised, and a transport that already has a
    "storage is unavailable" answer (the Gateway's 503) maps it there. The cost
    to the caller is a retry; the alternative was a wrong answer.
    """


#: Why a replay target was refused. Each refusal has a different remedy, which
#: is the whole reason the caller gets a code rather than a sentence:
#:
#: * ``unknown_projector`` — the name is not registered in this build (a typo,
#:   or a projector that does not exist yet). Fix the request.
#: * ``unknown_version`` — the projector is real but this build cannot execute
#:   the version asked for. Deploy the build that can.
#: * ``not_executable`` — this build *declares* the version replayable and
#:   cannot run it. Fix the deploy, not the command line.
#: * ``time_filter_unsupported`` — the request pairs an ``occurred_at`` window
#:   with a projector that claims **no** Observation kinds, so there is no kind
#:   list to bound the window with and ``ix_ansich_observations_kind_occurred``
#:   cannot serve it. Reaching it takes exactly one target today,
#:   ``task-spawn-reconcile`` (its jobs are enqueued inside another projector's
#:   transaction rather than fanned out by kind), and the remedy is a task or
#:   ingest filter instead — both of which have an index of their own. This is
#:   a refusal rather than a silent full scan because the scan is over a table
#:   with no retention: it gets slower every day and never gets faster.
#:
#: ``not_executable`` covers **two** conditions, deliberately, because they
#: share that one remedy and a caller never needs to tell them apart: the
#: projector has no execution branch at all, or it claims an Observation kind
#: the contract no longer admits (which would replay it over an empty target
#: set and report a clean pass over nothing). Both are half-finished code
#: changes rather than bad requests, and both should be unreachable in a
#: coherent build. The discriminating detail is in the message.
ReplayTargetRefusal = Literal[
    "unknown_projector",
    "unknown_version",
    "not_executable",
    "time_filter_unsupported",
]


class ReplayTargetError(ValueError):
    """The requested ``(projector, version)`` cannot be replayed by this build.

    Raised *before* a replay touches anything — no jobs minted, no read models
    cleared — so a refusal costs the caller nothing but the answer. It is a
    ``ValueError`` because it describes a bad argument: the store is fine, the
    request names something this build cannot do.

    The refusal is carried as :attr:`reason` (a
    :data:`ReplayTargetRefusal` member) rather than left to be parsed out of
    the message, so a CLI can map it to an exit code and a caller can branch on
    it without matching prose. The message stays for a human reading a
    terminal.

    What this error deliberately does **not** assert: that replaying an
    accepted target would produce jobs for historical Observations *of a
    version that never ran*. It would not, on its own. A newly executable
    version has no jobs for anything already ingested — live ingest mints jobs
    only for the versions in the live registry — and minting them is exactly
    what a replay is for. Accepting a target says "this build can run it",
    never "this build already has".
    """

    def __init__(
        self,
        message: str,
        *,
        reason: ReplayTargetRefusal,
        projector_name: str,
        projector_version: str,
    ) -> None:
        super().__init__(message)
        self.reason: ReplayTargetRefusal = reason
        self.projector_name = projector_name
        self.projector_version = projector_version
