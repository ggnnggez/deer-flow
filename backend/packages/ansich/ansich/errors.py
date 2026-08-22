"""Typed errors that cross the ``ansich`` package boundary.

Deliberately dependency-free — no pydantic, no SQLAlchemy, nothing a backend
adapter drags in. That is the whole point: a storage adapter lives outside this
package and is free to import a driver's exception hierarchy, but what it lets
*out* has to be something every caller can name without adopting the adapter's
dependencies.
"""

from __future__ import annotations

from typing import Literal

__all__ = [
    "ActiveVersionError",
    "ActiveVersionRefusal",
    "HardDeleteError",
    "HardDeleteRefusal",
    "PayloadExpiredError",
    "RawReadAuditUnavailableError",
    "ReplayTargetError",
    "ReplayTargetRefusal",
    "StorageUnavailableError",
]


class RawReadAuditUnavailableError(Exception):
    """The §7 access audit for one raw-payload read could not be persisted.

    **This is the batch's one documented inversion of the project-wide
    fail-open rule** (plan Global Constraint 1, spec:114). Everywhere else in
    Ansich a collection failure degrades and the product keeps working, because
    losing evidence about a run is worse than nothing but far better than
    breaking the run. Here the evidence *is* the control: an admin read of a
    raw body whose audit row did not land is an unaccountable disclosure, and
    the only way to keep the promise "every raw read is audited" is to refuse
    the read. Its caller answers **503 and does not read the payload** — and
    the routes that raise it say so in a comment naming this section, so nobody
    later "fixes" the inversion back to fail-open.

    Raised for both halves of "cannot persist": a backend with no audit writer
    at all (a service that cannot record the access must not serve it either),
    and a writer that raised. The two are the same statement to the caller —
    *this read is not audited* — and the route treats them identically.

    It says nothing about the payload, which by construction was never read:
    the requested-audit write happens before the store is asked for the body.
    """


class PayloadExpiredError(Exception):
    """The body a read needed was deleted under the retention policy.

    The third of the three payload states (plan ruling RC6), raised only by the
    reads whose entire purpose is to return bytes — the raw evidence routes. It
    is deliberately **not** how the projection, assessment and trend readers
    learn about a tombstone: those degrade in place, because a raise on their
    paths is a per-tick, Task-wide stall over a deletion somebody configured.
    A route that has been asked for a body and has none has nothing to degrade
    *to*, so there the honest answer is to say what happened and why.

    It is separate from an absent row on purpose, and the difference is the
    whole reason the tombstone exists. "Not found" says the evidence never was,
    or was never recorded; this says it was recorded, it was read back for as
    long as the policy kept it, and the policy expired it on a date this error
    names. The transport maps it to **410 Gone** rather than 404 for exactly
    that reason.

    The lineage half travels with it — the digest, the size, when it went and
    under which rule — because that is all a reader may still truthfully say
    about the bytes, and saying nothing would leave an operator unable to tell a
    retention outcome from a bug.
    """

    def __init__(
        self,
        message: str,
        *,
        payload_id: str,
        policy: str | None = None,
        deleted_at: object | None = None,
        sha256: str | None = None,
        byte_size: int | None = None,
    ) -> None:
        super().__init__(message)
        self.payload_id = payload_id
        self.policy = policy
        self.deleted_at = deleted_at
        self.sha256 = sha256
        self.byte_size = byte_size


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
      No ``EvaluationProjectionStatus`` value is minted for it either.

      **Updated 2026-08-22 (P11-C, plan ruling RC7)**, because that last clause
      used to read "no *fourth* value ... the receipt's vocabulary is
      unchanged" and half of it is now false: the vocabulary did gain a fourth
      value, ``expired``, for a different condition. The reasoning above is not
      weakened by it — it is the reason the two are kept apart. ``expired``
      is a positive statement the store can make from its own durable record
      (the retention horizon says a contiguous prefix of ``ingest_seq`` has
      been deleted under policy), so it reports knowledge as knowledge. *This*
      condition has no such record to appeal to: the read that would have told
      us anything is the read that failed. A value minted here would have to
      mean "unknown", and a receipt whose whole job is to answer a question
      must not answer it with a fifth way of saying it did not.
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
#: * ``filtered_replace_unsupported`` — the request pairs ``--replace`` with a
#:   task, time or ingest filter. ``--replace`` is **whole-table** (plan ruling
#:   RC4): read-model rows carry no provenance back to the Observation that
#:   produced them, so a delete cannot honour a filter the way the re-derive
#:   can. Running it anyway would clear the whole table and re-derive only the
#:   window, silently losing every row outside it. Drop the filter to replace
#:   the table, or drop ``--replace`` to re-derive the window in place.
#: * ``replace_restore_unproven`` — ``--replace`` was asked for a projector
#:   whose owned tables are not known to survive being deleted and re-derived.
#:   Exclusive ownership is necessary for a replace and **not sufficient**: the
#:   projector must also be able to rebuild those rows from the Observation
#:   stream *alone*, and one that consults state a projector-scoped replace
#:   does not clear cannot. ``task-control`` is the worked counterexample — it
#:   owns ``ansich_transitions`` outright, and computes each transition's
#:   ``from_value`` from the current control Belief, which lives in the shared
#:   Belief triple a replace neither owns nor clears — so replacing it rewrites
#:   history into ``running -> running``. The remedy for such a projector is
#:   ``rebuild_projections()``, which clears the shared zone too.
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
    "filtered_replace_unsupported",
    "replace_restore_unproven",
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


#: Why an activation was refused. A sibling of :data:`ReplayTargetRefusal` and
#: written for the same reason: each refusal has a different remedy, and a
#: caller must be able to branch on it without matching prose.
#:
#: * ``unknown_component_kind`` — the kind is not one this build versions.
#:   Exactly two are: ``projector`` and ``resolver``. Fix the request.
#: * ``unknown_component`` — the kind is real and no component of that kind
#:   carries this name in this build (a typo, or a projector that does not
#:   exist yet). Fix the request, or deploy the build that has it.
#: * ``unknown_version`` — the component is real and this build does not know
#:   the version asked for. Deploy the build that does; activating a version
#:   this process cannot execute would leave a row every reader has to
#:   fall back from.
#: * ``invalid_actor`` — the actor is blank or longer than the column that has
#:   to hold it. It is a *typed* refusal rather than a bare ``ValueError``
#:   because both halves otherwise fail late and differently: a blank actor
#:   makes an unattributed switch (which is not an audited one), and an
#:   over-long one is refused only by accident of the column width — silently
#:   truncated on SQLite, where the row's ``activated_by`` and the audit
#:   Observation's producer identity then disagree about who acted, and raised
#:   as a raw driver error on PostgreSQL, which escapes every handler a CLI has
#:   and exits on the code that means "re-run me".
ActiveVersionRefusal = Literal[
    "unknown_component_kind",
    "unknown_component",
    "unknown_version",
    "invalid_actor",
]


class ActiveVersionError(ValueError):
    """The requested activation names something this build does not know.

    Raised *before* anything is written — no row, no audit Observation — so a
    refusal costs the caller nothing but the answer, exactly as
    :class:`ReplayTargetError` does for a replay target. It is a ``ValueError``
    for the same reason: the store is fine, the request names something this
    build cannot honour.

    **Why validation is a refusal rather than a warning.** An active-version
    row is read by processes that are not this one, and the reader's only
    honest response to a version it cannot execute is to fall back to the code
    default — which is to say, to ignore the operator's deliberate action while
    reporting that it took effect. Refusing at the write keeps the row's
    meaning ("some build runs this") true at the moment it is made, and
    :func:`validate_active_versions` re-asks the same question at every later
    start, because a build can be rolled back underneath a row that was legal
    when it was written.
    """

    def __init__(
        self,
        message: str,
        *,
        reason: ActiveVersionRefusal,
        component_kind: str,
        component_name: str,
        version: str,
    ) -> None:
        super().__init__(message)
        self.reason: ActiveVersionRefusal = reason
        self.component_kind = component_kind
        self.component_name = component_name
        self.version = version


#: Why an owner/thread hard delete was refused (spec §6 D6-2). A sibling of
#: :data:`ReplayTargetRefusal` and :data:`ActiveVersionRefusal`, written for the
#: same reason: each refusal has a different remedy and a caller must be able to
#: branch on it without matching prose.
#:
#: * ``unknown_scope`` — no ``Scope`` carries this id. The request names
#:   something that is not there; nothing was deleted.
#: * ``bootstrap_sentinel`` — the id is ``ANSICH_BOOTSTRAP_TASK_ID``, which is
#:   not an entity at all but the value that says *"this Observation has no
#:   Task"*. Rows subjected to it belong to no deletable Scope, so "erase this
#:   owner" is not a question about it.
#: * ``host_scope`` — the process's own anchor Scope. It is this build's
#:   identity rather than one owner's data, and every worker's audit trail
#:   hangs off it, so it is not erasable by an owner-scoped action.
#: * ``shared_scope_kind`` — the Scope is real and its kind is not one owner's
#:   data. ``ScopeKind`` also spans ``workspace``, ``sandbox``, ``authorization``
#:   and ``external_origin``, which are shared *across* owners by construction: a
#:   workspace Scope names a repository path and a sandbox Scope a pooled
#:   runtime, so erasing one would take every Task that ever reported it, from
#:   every owner, with no signal that it had. Only ``owner`` and ``thread`` name
#:   one owner's data, and D6-2 calls this the *owner/thread* hard delete. This
#:   is the same argument ``host_scope`` rests on — "not one owner's data" —
#:   applied to the kinds it also covers.
#: * ``parent_scope`` — the Scope is another Scope's parent. Erasing it would
#:   orphan the child's ancestry (``ansich_scopes.parent_scope_id`` is
#:   ``RESTRICT``, so the database would refuse it anyway); the remedy is to
#:   delete the children first. Answered as a refusal rather than as an
#:   ``IntegrityError`` because a caller cannot branch on a driver error.
#: * ``blocked`` — a row **outside** this Scope's reach still points at a row
#:   inside it, so completing the erasure would either orphan that row or
#:   delete data belonging to somebody else. :attr:`HardDeleteError.blocker`
#:   names the table and column. This is the only refusal that can be raised
#:   *after* work has committed; see :class:`HardDeleteError`.
HardDeleteRefusal = Literal[
    "unknown_scope",
    "bootstrap_sentinel",
    "host_scope",
    "shared_scope_kind",
    "parent_scope",
    "blocked",
]


class HardDeleteError(ValueError):
    """An owner/thread hard delete cannot be completed (spec §6 D6-2).

    A ``ValueError`` for the same reason :class:`ReplayTargetError` is one: with
    the first four reasons the store is fine and the *request* names something
    this operation must not touch. Those four are answered **before anything is
    deleted**, from cheap indexed reads, so a refused request costs the caller
    nothing but the answer.

    ``blocked`` is the exception and the docstring must not hide it. A hard
    delete commits in batches — that is what keeps a large thread's erasure off
    one unbounded transaction — so a blocking referrer discovered part-way
    through is raised *after* the batches that already committed. This is not a
    partial failure to apologise for: the operation is **resumable from the
    store itself** rather than from a cursor (the remaining Tasks are re-derived
    from the Scope's surviving ``within_scope`` relations), so an operator who
    removes the blocker and re-runs the same call finishes the erasure. What a
    caller must not do is treat ``blocked`` as "nothing happened".

    **That resumability is a property of the erasure's transaction boundaries,
    not of this docstring** (review finding F1). The Scope row is the resume
    handle — a resumed run finds its Tasks through it — so the phase that
    deletes it raises from *inside* its own transaction, and a ``blocked``
    erasure therefore leaves the Scope standing. An earlier shape raised after
    that transaction committed, which deleted the handle and left the re-run
    answering ``unknown_scope``: a half-erased owner with no API able to finish
    the job, which is the one failure mode this operation cannot have.

    :attr:`blocker` is ``"table.column"`` for ``blocked`` and ``None``
    otherwise, and it names the **removable** edge rather than the proximate
    one. A protected Entity pinning an Observation refuses on
    ``ansich_entities.discovered_obs_id`` first, which is a column on the
    *surviving* row and names nothing an operator can act on; what they can act
    on is the Scope or the AgentRelease that owns it, so that is what this
    carries. Prose in a message is not something an operator can act on
    mechanically, which is the whole reason this field exists.

    :attr:`report` carries the counts the erasure had already committed when it
    refused, for ``blocked`` only. Typed ``object`` rather than
    ``HardDeleteReport`` to keep this module dependency-free — the same reason
    :class:`PayloadExpiredError` carries an ``object`` timestamp — and ``None``
    for every refusal raised before anything was deleted, which is all of the
    others. Without it a caller told "blocked" has no way to learn that most of
    the owner's data is already gone.
    """

    def __init__(
        self,
        message: str,
        *,
        reason: HardDeleteRefusal,
        scope_id: str,
        blocker: str | None = None,
        report: object | None = None,
    ) -> None:
        super().__init__(message)
        self.reason: HardDeleteRefusal = reason
        self.scope_id = scope_id
        self.blocker = blocker
        self.report = report
