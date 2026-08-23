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
   ``assess_operations`` settles those. Both the round count *and* the drain
   inside each round are capped, so the whole pass is bounded even against a
   store that keeps minting.
4. **Digest the result**, but only if step 3 actually reached settled.

Observations and payloads are never written, never deleted, and never replayed
*into*: a replay re-derives the projection zone from the immutable stream
(Global Constraint 3). What it changes is jobs and read models, both of which
are rebuildable by definition.

**``replace`` adds a step 0 and two refusals** (plan ruling RC4). It deletes
the target projector's exclusively-owned read-model tables whole, in the mint's
own transaction, before the re-pend -- which is what turns a replay from "write
the rows again" into "these rows are exactly what this history produces".
Because the delete cannot be narrowed the way the re-derive can, a replace
combined with any filter is refused; and because owning a table does not by
itself mean the projector can put its rows back from the Observation stream
alone, a replace of a projector that has not been shown to do so is refused
too. Both live in ``_validate_replace_request``, with the reasoning at
``_REPLACE_PROVEN_PROJECTORS``.

**Retention is the other half of what a report has to say** (batch-final
findings B2 and B4). Two of this module's numbers were blind to a store that had
run a retention pass, and both blindnesses were silent. A replayed Observation
whose payload tier 1 tombstoned settles ``completed`` having derived nothing, so
``ReplayReport.expired_evidence`` counts them and the digest is refused when it
is non-zero -- otherwise spec §11's determinism condition reports a policy
outcome as a violation, with nothing in either report to tell them apart. And a
range retention (or an owner erasure) removed matched nothing at all, which read
identically to a mistyped ``--task-id``; the report now names which, from the
same two deletion marks the receipt ladder consults. ``--replace`` over expired
evidence is refused outright rather than reported, because there the tables are
emptied first and the loss is not recoverable.

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
    _validate_replace_request,
    _validate_replay_target,
)

#: How many drain-then-recount rounds a replay spends before reporting what is
#: still owed. Matches ``AnsichService.rebuild_until_settled``'s default so an
#: operator does not have to hold two numbers in their head.
DEFAULT_MAX_ROUNDS = 5
#: Jobs claimed per ``project_pending`` call. The same figure the rebuild's own
#: drain loop uses; it bounds one transaction, not the pass.
DEFAULT_BATCH_LIMIT = 200
#: How many ``project_pending`` calls one round makes before it stops draining
#: and re-reads the backlog, whatever the last call returned.
#:
#: Without it the inner drain exits only on a call that claims nothing, so a
#: store ingesting faster than the loop drains never finishes a round and the
#: outer ``max_rounds`` bound never gets to apply (review finding F8). The
#: rebuild's drain has the same shape, but it runs holding both the maintenance
#: lock and the caller's projector lock, whereas this loop deliberately holds
#: neither -- so the replay is the more exposed of the two. Hitting the cap
#: ends the round early and is not an error: the recount that follows reports
#: what is still owed, exactly as a naturally-drained round would.
DEFAULT_MAX_DRAIN_BATCHES = 500

__all__ = ["DEFAULT_BATCH_LIMIT", "DEFAULT_MAX_DRAIN_BATCHES", "DEFAULT_MAX_ROUNDS", "execute_replay", "plan_replay"]


def _replace_notes(projector_name: str, *, replace: bool) -> list[str]:
    """Say in words that a whole table was (or would be) cleared.

    A replace that succeeded looks exactly like a replay that did not in every
    number ``ReplayReport`` carries -- same targets, same counts, and, when it
    works, the same digest. The one thing an operator cannot recover from the
    report is *which tables were emptied and re-derived*, and that is the part
    they would want to read back after the fact. So it is said here, in the
    free-text channel, rather than by adding a count nobody would compare.
    """

    if not replace:
        return []
    tables = _PROJECTOR_OWNED_TABLES.get(projector_name, ())
    names = ", ".join(sorted(model.__table__.name for model in tables))
    return [f"replace: {len(tables)} read-model table(s) owned by {projector_name} cleared and re-derived ({names})"]


async def _empty_target_note(backend: SqlAnsichBackend, selector: ReplaySelector) -> str:
    """Why nothing matched: a deletion, or a filter that missed (finding B4).

    The two are indistinguishable in every number a report carries -- ``targeted``
    is ``0`` and ``errors`` was empty -- and they call for opposite next moves:
    check the ``--task-id``, or accept that the evidence is gone. The store can
    answer it, and already does one rung over: the receipt ladder reads the same
    two marks as one question (*has a deliberate deletion happened here*), the
    horizon for retention's contiguous prefix and ``observation_cursor`` for an
    owner erasure, which cannot raise the horizon when a survivor sits below the
    range it removed.

    The consult is deliberately weak in one direction and says so: a selector
    that starts at or below the mark *may* have lost rows to a deletion, and this
    note claims no more than that. A selector whose range begins above the mark
    cannot have, so that case gets the plain answer.
    """

    horizon, cursor = await backend.observation_deletion_marks()
    mark = max(horizon, cursor)
    if mark > 0 and (selector.ingest_from is None or selector.ingest_from <= mark):
        return (
            f"no Observation matched, and this store has deleted evidence at or below ingest_seq {mark} "
            f"(retention horizon {horizon}, erasure cursor {cursor}) -- a target set inside that range is "
            "empty because the rows were removed, not because the filter missed"
        )
    return "no Observation matched this target set, and nothing has been deleted at or below it -- the filter, not retention, is why it is empty"


async def plan_replay(
    backend: SqlAnsichBackend,
    *,
    projector_name: str,
    projector_version: str,
    selector: ReplaySelector | None = None,
    replace: bool = False,
) -> ReplayReport:
    """Answer "what would this replay do" without doing any of it.

    Reads only. No maintenance lock is taken and no write transaction is
    opened: a plan that locked would make asking as expensive as doing, and
    would queue a question that changes nothing behind (or ahead of) an
    operator who is actually working.

    The target is validated first, so a dry run of an impossible target refuses
    exactly as the real one would -- the point of ``--dry-run`` is to find that
    out cheaply. That includes ``replace``: a filtered replace and a projector
    whose restore is unproven are refused here on exactly the terms the real
    pass would refuse them.

    ``digest`` is always ``None`` here, and that is not a limitation to be
    lifted later. A digest computed now would describe the store *before* the
    replay, and reporting it in this pass's report would read as this replay's
    result.
    """

    selector = ReplaySelector() if selector is None else selector
    _validate_replay_target(projector_name, projector_version)
    _validate_replace_request(projector_name, projector_version, selector, replace=replace)
    minted, re_pended = await backend.count_replay_targets(
        projector_name=projector_name,
        projector_version=projector_version,
        selector=selector,
    )
    unsettled = await backend.unsettled_job_count()
    failed = await backend.failed_projection_job_count(projector_name=projector_name, projector_version=projector_version)
    expired_evidence = await backend.count_expired_evidence_targets(
        projector_name=projector_name,
        projector_version=projector_version,
        selector=selector,
    )
    errors = ["dry run: nothing was written, so no digest was computed"]
    errors.extend(_replace_notes(projector_name, replace=replace))
    if unsettled:
        errors.append(f"{unsettled} job(s) unsettled in the store before this replay")
    if failed:
        errors.append(f"{failed} job(s) durably failed for {projector_name}@{projector_version} before this replay")
    if expired_evidence:
        # The dry run is where an operator finds this out for a `--replace`,
        # because the real pass refuses it (`replace_over_expired_evidence`)
        # rather than reporting it.
        errors.append(f"{expired_evidence} targeted Observation(s) carry retention-tombstoned payloads; a replay settles those jobs without deriving any rows{', and --replace over them is refused' if replace else ''}")
    if minted + re_pended == 0:
        errors.append(await _empty_target_note(backend, selector))
    return ReplayReport(
        projector_name=projector_name,
        projector_version=projector_version,
        targeted=minted + re_pended,
        minted=minted,
        re_pended=re_pended,
        replayed=0,
        unsettled=unsettled,
        failed=failed,
        expired_evidence=expired_evidence,
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
    replace: bool = False,
    max_rounds: int = DEFAULT_MAX_ROUNDS,
    batch_limit: int = DEFAULT_BATCH_LIMIT,
    max_drain_batches: int = DEFAULT_MAX_DRAIN_BATCHES,
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
    _validate_replace_request(projector_name, projector_version, selector, replace=replace)
    minted, re_pended = await backend.mint_replay_jobs(
        projector_name=projector_name,
        projector_version=projector_version,
        selector=selector,
        replace=replace,
    )

    replayed = 0
    unsettled = await backend.unsettled_job_count()
    for _ in range(max(max_rounds, 1)):
        for _ in range(max(max_drain_batches, 1)):
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

    errors: list[str] = _replace_notes(projector_name, replace=replace)
    if unsettled:
        errors.append(f"{unsettled} job(s) still unsettled after {max(max_rounds, 1)} round(s); the store still owes work, run the replay again or raise --max-rounds")
    # Durably failed jobs are *settled*, badly, so they never appear in
    # `unsettled` -- a pass can report a clean settle and still have left
    # projections that never landed. It is scoped to the target
    # `(projector, version)` because that is what the digest below hashes: a
    # failure in another projector cannot leave a row missing from *this*
    # projector's exclusively-owned tables. It is **not** scoped to the
    # selector, so a filtered replay reports failures elsewhere in the same
    # projector too -- deliberate (a durable failure anywhere in it is worth
    # saying), but it means the number is not always this pass's own doing.
    failed = await backend.failed_projection_job_count(projector_name=projector_name, projector_version=projector_version)
    if failed:
        errors.append(f"{failed} job(s) durably failed for {projector_name}@{projector_version}; see GET /operations/failed-jobs")

    # Read **after** the drive loop, not before the mint. A tombstone is
    # permanent, so a payload tier 1 expires mid-pass is caught here and would
    # have been missed by a count taken up front -- and that concurrent shape is
    # the reachable one, since retention holds its own advisory key and never
    # queues behind this pass's maintenance lock (finding B9).
    expired_evidence = await backend.count_expired_evidence_targets(
        projector_name=projector_name,
        projector_version=projector_version,
        selector=selector,
    )
    if expired_evidence:
        errors.append(f"{expired_evidence} targeted Observation(s) carry retention-tombstoned payloads; their jobs settled without deriving any rows, so this pass re-derived less than its target set")
    if minted + re_pended == 0:
        errors.append(await _empty_target_note(backend, selector))

    digest: str | None = None
    if unsettled:
        errors.append("no digest: a digest over a store that still owes work describes a state nobody asked for")
    elif failed:
        # The same gate, for the one state in which owned rows are *known*
        # never to have been written. `unsettled` cannot see it -- a durably
        # failed job is settled -- so without this clause the digest describes a
        # read model with holes in it and compares unequal against the same
        # history replayed successfully, with nothing but prose to say why.
        errors.append("no digest: durably failed jobs mean rows this projector owns were never written")
    elif expired_evidence:
        # The fourth clause, and the one that makes spec §11's determinism
        # condition true as stated instead of true-until-retention-runs
        # (finding B2). The rows this pass *did* write are correct; what is
        # false is the comparison the digest exists for, because the same
        # Observation set replayed before the sweep produced rows this one
        # cannot. `unsettled` and `failed` are both blind to it -- an expired
        # settle is `completed` -- so without this clause the digest is
        # computed, `errors` is empty and the CLI exits 0 over evidence that is
        # gone.
        errors.append(f"no digest: {expired_evidence} targeted Observation(s) have expired evidence, so this read model is not comparable with one derived before the retention pass")
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
        failed=failed,
        expired_evidence=expired_evidence,
        errors=tuple(errors),
        watermark=await backend.projection_continuity_mark(),
        digest=digest,
        dry_run=False,
    )
