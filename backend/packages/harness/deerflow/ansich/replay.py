"""Versioned replay: aim a projector at a slice of history and re-derive it.

Spec §5's centrepiece, and the whole of it is four steps that must happen in
this order and no other:

1. **Refuse what cannot be honoured**, before anything is written
   (``_validate_replay_target``).
2. **Put the target set back in the queue** -- mint jobs for the Observations
   the target has none for, re-pend the ones it does -- in one transaction
   under the maintenance lock, together with the active-Task read-model delete
   that keeps the re-pend from freezing that read model (plan ruling RC3).
3. **Drive the queue to settled** with a bounded loop that reports rather than
   waits (plan ruling RC1). Each round drains the claim queue and then runs one
   assessment pass, the same shape ``_rebuild_projections_locked`` uses -- a
   re-projected Observation enqueues assessor jobs, and nothing but
   ``assess_operations`` settles those.
4. **Digest the result**, but only if step 3 actually reached settled.

Observations and payloads are never written, never deleted, and never replayed
*into*: a replay re-derives the projection zone from the immutable stream
(Global Constraint 3). What it changes is jobs and read models, both of which
are rebuildable by definition.

**What an accepted target does and does not assert.** ``_validate_replay_target``
answers three questions -- registered name, declared version, executable in
this build -- and the third one is checked with a proxy: the dispatch chain's
branch set is derived from ``_PROJECTORS``, i.e. from what live ingest fans out
to, so "has a branch" is being read off "is live-registered". More importantly,
**the dispatch is version-blind**. ``project_pending`` branches on
``projector_name`` alone and never reads ``projector_version``, so the moment a
second version is declared replayable, replaying it executes exactly the same
code as the first unless that branch has been taught the difference. An
accepted target is therefore evidence that this build will *run* something, and
no evidence at all that two versions would produce two different read models.
Anyone comparing v1 and v2 digests has to have made that difference real in the
dispatch first; nothing here can check it for them.

**Why the drive loop is here and not inside the backend.** Each round releases
every lock before the next one starts, which is precisely what lets a
dependency-deferred job become claimable and another worker's in-flight claim
finish. A loop that waited inside one locked call would have neither, and would
stall an operator and a projector loop for an interval it does not control --
the reasoning behind ``AnsichService.rebuild_until_settled``, applied to a
target set instead of the whole store. The lower-bound caveat that method's
docstring carries applies here unchanged: a returned ``unsettled == 0`` is a
count taken at one known point, a strong signal rather than proof, and the
honest way to want proof is another pass.

This module is deliberately harness-side and imports no ``app.*`` (the
harness/app firewall, pinned by ``tests/test_harness_boundary.py``): a replay
is an operator tool over storage, not an HTTP surface, and spec §5 says it is
never a route.
"""

from __future__ import annotations

from ansich import ReplayReport, ReplaySelector

from deerflow.ansich.persistence.sql import (
    _PROJECTOR_OWNED_TABLES,
    SqlAnsichBackend,
    _validate_replay_target,
)

#: How many drain-then-recount rounds a replay spends before reporting what is
#: still owed. Matches ``AnsichService.rebuild_until_settled``'s default so an
#: operator does not have to hold two numbers in their head.
DEFAULT_MAX_ROUNDS = 5
#: Jobs claimed per ``project_pending`` call. The same figure the rebuild's own
#: drain loop uses; it bounds one transaction, not the pass.
DEFAULT_BATCH_LIMIT = 200

__all__ = ["DEFAULT_BATCH_LIMIT", "DEFAULT_MAX_ROUNDS", "execute_replay", "plan_replay"]


async def plan_replay(
    backend: SqlAnsichBackend,
    *,
    projector_name: str,
    projector_version: str,
    selector: ReplaySelector | None = None,
) -> ReplayReport:
    """Answer "what would this replay do" without doing any of it.

    Reads only. No maintenance lock is taken and no write transaction is
    opened: a plan that locked would make asking as expensive as doing, and
    would queue a question that changes nothing behind (or ahead of) an
    operator who is actually working.

    The target is validated first, so a dry run of an impossible target refuses
    exactly as the real one would -- the point of ``--dry-run`` is to find that
    out cheaply.

    ``digest`` is always ``None`` here, and that is not a limitation to be
    lifted later. A digest computed now would describe the store *before* the
    replay, and reporting it in this pass's report would read as this replay's
    result.
    """

    selector = ReplaySelector() if selector is None else selector
    _validate_replay_target(projector_name, projector_version)
    minted, re_pended = await backend.count_replay_targets(
        projector_name=projector_name,
        projector_version=projector_version,
        selector=selector,
    )
    unsettled = await backend.unsettled_job_count()
    errors = ["dry run: nothing was written, so no digest was computed"]
    if unsettled:
        errors.append(f"{unsettled} job(s) unsettled in the store before this replay")
    return ReplayReport(
        projector_name=projector_name,
        projector_version=projector_version,
        targeted=minted + re_pended,
        minted=minted,
        re_pended=re_pended,
        replayed=0,
        unsettled=unsettled,
        errors=tuple(errors),
        watermark=await backend.projection_continuity_mark(),
        digest=None,
        dry_run=True,
    )


async def execute_replay(
    backend: SqlAnsichBackend,
    *,
    projector_name: str,
    projector_version: str,
    selector: ReplaySelector | None = None,
    max_rounds: int = DEFAULT_MAX_ROUNDS,
    batch_limit: int = DEFAULT_BATCH_LIMIT,
) -> ReplayReport:
    """Re-derive a projector's read models over a slice of history.

    The counts it returns mean exactly what
    :class:`~ansich.contracts.ReplayReport` says they mean, and two of them are
    worth restating at the call site:

    ``replayed`` is **store-wide**. The drive loop drains the claim queue, and
    the claim orders by ``ingest_seq`` and knows nothing about this pass's
    filters -- so an Observation another producer ingests mid-pass is projected
    by this loop like any other, and shows up here. That is the honest
    reporting of a store that moved underneath the replay; counting only the
    targeted subset would let the same event pass unremarked.

    ``unsettled`` is the last round's count, not a sum, and exhausting
    ``max_rounds`` is reported rather than raised. An operator command that
    raised on an incomplete pass would turn a true report into a failure, and
    the remedy for both is the same: run it again.

    The loop's exit condition is ``unsettled == 0`` and deliberately not "a
    round replayed nothing" -- a round can replay nothing because every
    remaining job is inside a dependency backoff or held by another worker's
    lease, which is the opposite of done (F10-26).

    ``max_rounds`` below 1 still runs one round, for the same reason
    ``rebuild_until_settled`` does: the report describes a pass, and there is
    no honest one to synthesise without having made it.
    """

    selector = ReplaySelector() if selector is None else selector
    _validate_replay_target(projector_name, projector_version)
    minted, re_pended = await backend.mint_replay_jobs(
        projector_name=projector_name,
        projector_version=projector_version,
        selector=selector,
    )

    replayed = 0
    unsettled = await backend.unsettled_job_count()
    for _ in range(max(max_rounds, 1)):
        while True:
            processed = await backend.project_pending(limit=batch_limit)
            replayed += processed
            if processed == 0:
                break
        # An assessment pass, per round, for the same reason
        # `_rebuild_projections_locked` ends with one: re-projecting an
        # Observation enqueues the assessor jobs that Observation triggers, and
        # `project_pending` does not run them -- `assess_operations` is the
        # only thing that does. Without this a replay would report every store
        # as permanently unsettled and therefore never produce a digest, which
        # would make the §11 determinism check unreachable.
        #
        # It is also what republishes the active-Task read-model rows the mint
        # deleted (RC3). That is the same order a rebuild uses -- delete, then
        # re-derive, then assess -- and it is why a replay leaves that read
        # model rebuilt rather than merely emptied.
        await backend.assess_operations()
        unsettled = await backend.unsettled_job_count()
        if unsettled == 0:
            break

    errors: list[str] = []
    if unsettled:
        errors.append(f"{unsettled} job(s) still unsettled after {max(max_rounds, 1)} round(s); the store still owes work, run the replay again")
    failed = await backend.failed_projection_job_count(projector_name=projector_name, projector_version=projector_version)
    if failed:
        # Durably failed jobs are *settled*, badly, so they never appear in
        # `unsettled` -- a pass can report a clean settle and still have left
        # projections that never landed. Saying so here is the only place an
        # operator driving a replay would see it.
        errors.append(f"{failed} job(s) durably failed for {projector_name}@{projector_version}; see GET /operations/failed-jobs")

    digest: str | None = None
    if unsettled:
        errors.append("no digest: a digest over a store that still owes work describes a state nobody asked for")
    elif not _PROJECTOR_OWNED_TABLES.get(projector_name):
        errors.append(f"no digest: {projector_name} owns no read-model table exclusively, and hashing the empty set would report determinism nobody established")
    else:
        digest = await backend.read_model_digest(projector_name)

    return ReplayReport(
        projector_name=projector_name,
        projector_version=projector_version,
        targeted=minted + re_pended,
        minted=minted,
        re_pended=re_pended,
        replayed=replayed,
        unsettled=unsettled,
        errors=tuple(errors),
        watermark=await backend.projection_continuity_mark(),
        digest=digest,
        dry_run=False,
    )
