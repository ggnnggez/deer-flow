"""Best-effort bridge from run feedback into Ansich evaluation Observations.

A thumbs rating is the user's own judgement of a run, and Ansich models exactly
that as a ``user_feedback`` evaluation of the Task that run produced. The bridge
is deliberately one-directional and fail-open: by the time it runs the feedback
row is already written, so nothing here may raise into the route, change its
response, or block the request on Ansich storage. Ansich succeeding must never
mask a feedback write that failed, which is why the caller invokes this only
after its own write returned.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from ansich.contracts import NamedVersion, Producer
from ansich.evaluation import EvaluationRecord, EvaluationVerdict, build_evaluation_observation

logger = logging.getLogger(__name__)

#: Identity of the Observations this bridge produces. Combined with the
#: source-event id it is also the replay key storage deduplicates on.
_PRODUCER = Producer(name="ansich-feedback-adapter", version="1", instance_id="gateway")
#: A thumb is an unverified human judgement, so it stays ``soft`` and carries
#: its own assessor identity rather than borrowing an operator's authority.
_ASSESSOR = NamedVersion(name="user-feedback", version="1.0.0")
#: A thumb says the answer did or did not serve the request. It never says the
#: answer was factually right, so the mapping is confined to ``relevance`` and
#: must never infer ``correctness``.
_DIMENSION = "relevance"
_VERDICT_BY_RATING: dict[int, EvaluationVerdict] = {1: "pass", -1: "fail"}


def _source_event_id(*, thread_id: str, run_id: str, user_id: str | None, rating: int) -> str:
    """Return the replay identity of one user's rating of one run.

    The rating is part of the identity on purpose. Re-submitting the same
    rating replays the same source event and is absorbed as a duplicate, while
    changing the rating produces a genuinely new Observation. Both assertions
    then coexist and the resolver picks by ``as_of`` within the soft-human
    class — a changed mind is new evidence, not a retraction of the old one.
    """

    return f"evaluation:feedback:{thread_id}:{run_id}:{user_id or 'anonymous'}:{rating}"


async def record_feedback_evaluation(
    app_state: Any,
    *,
    thread_id: str,
    run_id: str,
    user_id: str | None,
    rating: int,
    comment: str | None,
) -> None:
    """Record one run rating as an Ansich evaluation, best-effort.

    ``app_state`` is the Gateway's ``app.state``; the service is looked up on
    it by name, so a deployment without Ansich simply has no attribute to find.
    Returns silently — never raising — when Ansich is not configured, when the
    run was never observed (no Task to attach the judgement to), or when any
    part of the recording fails.

    ``comment`` is accepted and deliberately dropped: it is the user's own
    free text about their own request, and the evaluation index carries no
    bodies, so putting it in ``rationale`` would ride the Observation payload
    into a store that never needs it. The rating is the whole assertion.
    """

    verdict = _VERDICT_BY_RATING.get(rating)
    if verdict is None:
        return
    service = getattr(app_state, "ansich_service", None)
    if service is None:
        return
    try:
        task = await service.get_task_by_source("deerflow_run", run_id)
        if task is None:
            # Ansich was not observing this run, so there is no Task to carry
            # the judgement. Recording against a synthesised subject would
            # create an evaluation no Belief read can ever resolve.
            return
        observation = build_evaluation_observation(
            EvaluationRecord(
                subject_type="task",
                subject_id=task.task_id,
                # A Task-subject evaluation always owns itself; the contract
                # requires the two to agree.
                task_id=task.task_id,
                evaluation_kind="user_feedback",
                dimension=_DIMENSION,
                verdict=verdict,
                rationale=None,
                assessor=_ASSESSOR,
                fidelity_class="soft",
                # The run that produced the rated Task, so this Observation
                # correlates with the rest of that run's evidence.
                run_id=run_id,
                occurred_at=datetime.now(UTC),
            ),
            producer=_PRODUCER,
            source_event_id=_source_event_id(thread_id=thread_id, run_id=run_id, user_id=user_id, rating=rating),
        )
        # Fire-and-forget intake: the queue write is non-blocking and a
        # rejected record is already accounted as an Ansich loss, so there is
        # no receipt worth waiting for on a best-effort path.
        service.record(observation)
    except Exception:
        logger.warning("ansich feedback evaluation failed", exc_info=True)
