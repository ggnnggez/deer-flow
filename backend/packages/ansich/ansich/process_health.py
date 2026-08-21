"""Process-subject health rules: projection failure and observability loss.

RB3. Both rules judge the *collector process's own* health rather than the
Agent's behaviour, so both subject the host ``Scope`` whose id
:func:`ansich.safety.host_scope_id` computes, and neither may touch the
Task-scoped assessor-job machinery — ``ansich_assessor_jobs.subject_id`` is
FK-bound to ``ansich_tasks`` and a Scope subject has no row there. They
therefore live in the periodic ``assess_operations`` pass beside
``environment-pressure@1`` rather than riding an observation-triggered
assessor job.

Everything here is a pure function over already-read facts: the SQL side owns
the queries, this module owns the verdict, the condition identity, and the
bounds on both.

Two identity bounds are enforced here rather than left to the database. A
Belief ``field_name`` column is ``String(64)`` while a projector name plus its
version, or a producer name plus its instance id, can be longer than that on
their own; a stable condition key column is ``String(256)`` and the producer
pair alone can reach 257. Truncating either would silently merge two distinct
groups into one Alert, so an over-long key degrades to a digest of itself
instead — the readable form is kept whenever it fits, and the group stays
distinguishable when it does not.
"""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256

from ansich.assessment.base import Assessment, EvidenceRef, canonical_config_hash
from ansich.contracts import NamedVersion

#: ``ansich_belief_assertions.field_name`` is ``String(64)``.
_FIELD_NAME_LIMIT = 64
#: ``ansich_alerts.stable_condition_key`` is ``String(256)``.
_CONDITION_KEY_LIMIT = 256

PROJECTION_HEALTH_ASSESSOR = NamedVersion(name="projection-health", version="1")
OBSERVABILITY_LOSS_ASSESSOR = NamedVersion(name="observability-loss", version="1")

#: How many Observation references one process-subject Alert condition carries.
#: Both rules can be backed by an unbounded number of rows — a projector that
#: fails on every Observation it sees, a producer losing a long range — and the
#: Alert's evidence list exists to let an operator start reading, not to be the
#: complete inventory (the failed-job diagnostics route and the immutable
#: ``observability.lost`` stream are). The newest references are kept, because
#: the newest are the ones that describe the condition as it is now.
MAX_PROCESS_ALERT_EVIDENCE = 10


def _bounded(prefix: str, key: str, limit: int) -> str:
    candidate = f"{prefix}:{key}"
    if len(candidate) <= limit:
        return candidate
    return f"{prefix}:#{sha256(key.encode('utf-8')).hexdigest()[:32]}"


def projection_failure_group_key(projector_name: str, projector_version: str) -> str:
    """The raw ``(projector_name, projector_version)`` group identity."""

    return f"{projector_name}@{projector_version}"


def observability_loss_group_key(producer_name: str, producer_instance_id: str) -> str:
    """The raw losing-producer identity, as ``observability.lost`` reports it."""

    return f"{producer_name}@{producer_instance_id}"


def projection_failure_field_name(projector_name: str, projector_version: str) -> str:
    return _bounded(
        "projection_failure",
        projection_failure_group_key(projector_name, projector_version),
        _FIELD_NAME_LIMIT,
    )


def projection_failure_condition_key(projector_name: str, projector_version: str) -> str:
    return _bounded(
        "projector",
        projection_failure_group_key(projector_name, projector_version),
        _CONDITION_KEY_LIMIT,
    )


def observability_loss_field_name(producer_name: str, producer_instance_id: str) -> str:
    return _bounded(
        "observability_degradation",
        observability_loss_group_key(producer_name, producer_instance_id),
        _FIELD_NAME_LIMIT,
    )


def observability_loss_condition_key(producer_name: str, producer_instance_id: str) -> str:
    return _bounded(
        "producer",
        observability_loss_group_key(producer_name, producer_instance_id),
        _CONDITION_KEY_LIMIT,
    )


def assess_projection_failure(
    *,
    scope_id: str,
    projector_name: str,
    projector_version: str,
    failing: bool,
    as_of: datetime,
    now: datetime,
    evidence_obs_ids: tuple[str, ...] = (),
) -> Assessment:
    """Judge one ``(projector_name, projector_version)`` group's health.

    **Scope boundary (RB3②), and it is deliberate.** The evidence chain for
    this Alert is the failed job's own ``obs_id``, and only *projection* jobs
    carry one — ``ansich_projection_jobs.obs_id`` is a real column, while an
    assessor job identifies a subject and an evidence watermark and has no
    Observation of its own. So this rule covers projection jobs and nothing
    else: a durably failed **assessor** job produces no ``projection_failure``
    Alert in this batch. It still reaches an operator through the shared
    failed-job count and through ``GET /operations/failed-jobs``; giving it an
    Alert would mean deriving evidence by reverse-reading its
    ``evidence_watermark``, which is left for when something needs it.

    The verdict is categorical on purpose. How *many* jobs are failing changes
    with every retry and every new Observation the broken projector chokes on,
    and folding that number into the Assertion value would append a Belief
    Assertion per change instead of one per transition. The count lives in the
    failed-job diagnostics, which is where an operator reads it anyway.
    """

    key = projection_failure_group_key(projector_name, projector_version)
    return Assessment(
        subject_id=scope_id,
        field_name=projection_failure_field_name(projector_name, projector_version),
        value={
            "value": "failing" if failing else "ok",
            "condition_key": projection_failure_condition_key(projector_name, projector_version),
            "group_key": key,
            "projector_name": projector_name,
            "projector_version": projector_version,
        },
        as_of=as_of,
        asserted_at=now,
        assessor=PROJECTION_HEALTH_ASSESSOR,
        config_hash=canonical_config_hash({}),
        authority_class="configured_rule",
        fidelity_class="rule",
        evidence=tuple(EvidenceRef(obs_id=obs_id) for obs_id in evidence_obs_ids),
    )


def assess_observability_degradation(
    *,
    scope_id: str,
    producer_name: str,
    producer_instance_id: str,
    degraded: bool,
    window_seconds: int,
    as_of: datetime,
    now: datetime,
    evidence_obs_ids: tuple[str, ...] = (),
) -> Assessment:
    """Judge whether one producer is *currently* losing Observations.

    ``observability.lost`` rows are append-only and never deleted, so "has this
    producer ever lost anything" is a question whose answer only ever becomes
    yes. An Alert built on it could open once and never resolve, which is the
    one thing an episode must be able to do: an operator who fixed the outage
    has to see it close, and a second outage has to open a *second* episode
    rather than silently ride the first one's recurrence number.

    So the condition is deliberately a recency property: this producer is
    degraded while at least one of its lost ranges was recorded within
    ``window_seconds`` of now, and recovered once the window passes with no new
    range. That gives both directions the episode machinery needs — resolve
    after loss stops, ``episode + 1`` when loss returns — without inventing a
    durable "loss cursor" the read side does not have. The window is part of
    the rule's config identity, so changing it is visible in every Assertion it
    produces rather than silently re-judging history.

    The honest cost: a producer that lost data once and never again reads as
    recovered a window later, even though the data is still gone. That is the
    right split of duties — the *loss* is permanent and stays in the immutable
    ``observability.lost`` stream and in the collector's own accounting; the
    *Alert* is about a condition an operator can act on, and "it stopped" is a
    real change of condition.
    """

    if window_seconds < 1:
        raise ValueError("window_seconds must be positive")
    key = observability_loss_group_key(producer_name, producer_instance_id)
    return Assessment(
        subject_id=scope_id,
        field_name=observability_loss_field_name(producer_name, producer_instance_id),
        value={
            "value": "degraded" if degraded else "ok",
            "condition_key": observability_loss_condition_key(producer_name, producer_instance_id),
            "group_key": key,
            "producer_name": producer_name,
            "producer_instance_id": producer_instance_id,
        },
        as_of=as_of,
        asserted_at=now,
        assessor=OBSERVABILITY_LOSS_ASSESSOR,
        config_hash=canonical_config_hash({"window_seconds": window_seconds}),
        authority_class="configured_rule",
        fidelity_class="rule",
        evidence=tuple(EvidenceRef(obs_id=obs_id) for obs_id in evidence_obs_ids),
    )
