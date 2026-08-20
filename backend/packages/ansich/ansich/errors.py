"""Typed errors that cross the ``ansich`` package boundary.

Deliberately dependency-free — no pydantic, no SQLAlchemy, nothing a backend
adapter drags in. That is the whole point: a storage adapter lives outside this
package and is free to import a driver's exception hierarchy, but what it lets
*out* has to be something every caller can name without adopting the adapter's
dependencies.
"""

from __future__ import annotations

__all__ = ["StorageUnavailableError"]


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
