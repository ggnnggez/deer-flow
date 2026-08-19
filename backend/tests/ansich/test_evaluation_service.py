"""Service-surface and cohort-comparability tests for the Phase 10 evaluations."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from ansich import (
    AnsichService,
    EvaluationRecord,
    NamedVersion,
    ObservationEnvelope,
    Producer,
    ScoreScale,
    build_evaluation_observation,
    new_id,
)
from ansich.evaluation import (
    QUALITY_DIMENSIONS,
    UNASSESSED_SOURCE,
    EvaluationRecordReceipt,
    EvaluationView,
    QualityBeliefView,
)
from ansich.quality import (
    QualityComparisonView,
    ReleaseQualityDimensionView,
    ReleaseQualityView,
    compare_release_quality,
)
from ansich.release import AgentRuntimeDescriptor, RuntimeBuildDescriptor, build_agent_release
from pydantic import ValidationError
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from deerflow.ansich import create_embedded_ansich_service, create_sql_ansich_service
from deerflow.ansich.persistence.models import (
    AnsichEvaluationIndexRow,
    AnsichObservationRow,
    AnsichProjectionJobRow,
    AnsichTaskAgentReleaseRow,
)
from deerflow.config.ansich_config import AnsichConfig
from deerflow.persistence.base import Base

_OCCURRED_AT = datetime(2026, 8, 18, 9, tzinfo=UTC)
_BENCHMARK_ASSESSOR = NamedVersion(name="ansich-benchmark-runner", version="1.0.0")
_JUDGE_ASSESSOR = NamedVersion(name="ansich-llm-judge", version="1.0.0")
_OPERATOR_ASSESSOR = NamedVersion(name="deerflow-operator", version="1.0.0")
_UNIT_SCALE = ScoreScale(min=0.0, max=1.0, higher_is_better=True)
_RESOLVER = NamedVersion(name="ansich-default", version="2.0.0")


# ---------------------------------------------------------------------------
# Pure cohort comparability (spec section 7)
# ---------------------------------------------------------------------------


def _cell(
    *,
    dimension: str = "correctness",
    cohort_key: str = "ansich-regression@2026.08.1",
    assessed_count: int = 10,
    pass_count: int = 5,
    fail_count: int = 5,
    partial_count: int = 0,
    mean_score: float | None = None,
    scale: dict[str, object] | None = None,
    as_of: datetime = _OCCURRED_AT,
) -> ReleaseQualityDimensionView:
    return ReleaseQualityDimensionView(
        dimension=dimension,
        cohort_key=cohort_key,
        assessed_count=assessed_count,
        pass_count=pass_count,
        fail_count=fail_count,
        partial_count=partial_count,
        mean_score=mean_score,
        scale=scale,
        as_of=as_of,
    )


def _only(comparisons: tuple[QualityComparisonView, ...]) -> QualityComparisonView:
    assert len(comparisons) == 1
    return comparisons[0]


def test_same_cohort_and_scale_with_enough_samples_compares_score_means() -> None:
    left = _cell(mean_score=0.5, scale={"min": 0.0, "max": 1.0})
    right = _cell(mean_score=0.8, scale={"min": 0.0, "max": 1.0})

    comparison = _only(compare_release_quality([left], [right], min_samples=5, unexplained_loss=False))

    assert comparison.dimension == "correctness"
    assert comparison.cohort_key == "ansich-regression@2026.08.1"
    assert comparison.comparison_status == "comparable"
    assert comparison.reason is None
    assert comparison.observed_delta == pytest.approx(0.3)
    assert (comparison.left_sample_count, comparison.right_sample_count) == (10, 10)
    assert comparison.resolver == _RESOLVER
    assert comparison.coverage["min_samples"] == 5
    assert comparison.coverage["left"]["assessed_count"] == 10
    assert comparison.coverage["right"]["present"] is True


def test_verdict_only_cohorts_compare_pass_rates() -> None:
    left = _cell(assessed_count=10, pass_count=4, fail_count=6)
    right = _cell(assessed_count=10, pass_count=9, fail_count=1)

    comparison = _only(compare_release_quality([left], [right], min_samples=5, unexplained_loss=False))

    assert comparison.comparison_status == "comparable"
    assert comparison.observed_delta == pytest.approx(0.5)


def test_a_cohort_present_on_only_one_side_is_not_comparable() -> None:
    left = _cell(cohort_key="ansich-regression@2026.08.1", mean_score=0.5, scale={"min": 0.0, "max": 1.0})
    right = _cell(cohort_key="ansich-regression@2026.09.1", mean_score=0.9, scale={"min": 0.0, "max": 1.0})

    comparisons = compare_release_quality([left], [right], min_samples=5, unexplained_loss=False)

    assert [item.cohort_key for item in comparisons] == [
        "ansich-regression@2026.08.1",
        "ansich-regression@2026.09.1",
    ]
    assert {item.reason for item in comparisons} == {"no_shared_cohort"}
    assert {item.comparison_status for item in comparisons} == {"not_comparable"}
    assert {item.observed_delta for item in comparisons} == {None}
    # Both directions: the left-only cohort has no right samples and vice versa.
    assert (comparisons[0].left_sample_count, comparisons[0].right_sample_count) == (10, 0)
    assert (comparisons[1].left_sample_count, comparisons[1].right_sample_count) == (0, 10)
    assert comparisons[0].coverage["right"]["present"] is False
    assert comparisons[1].coverage["left"]["present"] is False


def test_the_empty_cohort_sentinel_is_never_comparable() -> None:
    left = _cell(cohort_key="", mean_score=0.5, scale={"min": 0.0, "max": 1.0}, assessed_count=50)
    right = _cell(cohort_key="", mean_score=0.9, scale={"min": 0.0, "max": 1.0}, assessed_count=50)

    comparison = _only(compare_release_quality([left], [right], min_samples=5, unexplained_loss=False))

    assert comparison.comparison_status == "not_comparable"
    assert comparison.reason == "no_shared_cohort"
    assert comparison.observed_delta is None


def test_an_inverted_scale_polarity_is_not_comparable_in_either_direction() -> None:
    """Identical ranges with opposite polarity are not the same measurement.

    A 0..1 scale where higher is better and one where lower is better produce
    deltas whose sign means the opposite thing on each side, so §7's "same score
    scale" must cover polarity, not just the range.
    """

    higher_is_better = _cell(mean_score=0.5, scale={"min": 0.0, "max": 1.0, "higher_is_better": True})
    lower_is_better = _cell(mean_score=0.8, scale={"min": 0.0, "max": 1.0, "higher_is_better": False})

    forward = _only(compare_release_quality([higher_is_better], [lower_is_better], min_samples=5, unexplained_loss=False))
    reverse = _only(compare_release_quality([lower_is_better], [higher_is_better], min_samples=5, unexplained_loss=False))

    assert (forward.comparison_status, reverse.comparison_status) == ("not_comparable", "not_comparable")
    assert (forward.reason, reverse.reason) == ("scale_mismatch", "scale_mismatch")
    assert (forward.observed_delta, reverse.observed_delta) == (None, None)
    # The same polarity on both sides stays comparable.
    assert _only(compare_release_quality([higher_is_better], [higher_is_better], min_samples=5, unexplained_loss=False)).comparison_status == "comparable"


def test_a_different_score_scale_is_not_comparable_in_either_direction() -> None:
    unit = _cell(mean_score=0.5, scale={"min": 0.0, "max": 1.0})
    ten = _cell(mean_score=8.0, scale={"min": 0.0, "max": 10.0})
    verdict_only = _cell(assessed_count=10, pass_count=5, fail_count=5)

    assert _only(compare_release_quality([unit], [ten], min_samples=5, unexplained_loss=False)).reason == "scale_mismatch"
    assert _only(compare_release_quality([ten], [unit], min_samples=5, unexplained_loss=False)).reason == "scale_mismatch"
    # A scored cohort and a verdict-only cohort are not the same measurement.
    assert _only(compare_release_quality([unit], [verdict_only], min_samples=5, unexplained_loss=False)).reason == "scale_mismatch"
    assert _only(compare_release_quality([verdict_only], [unit], min_samples=5, unexplained_loss=False)).reason == "scale_mismatch"


def test_insufficient_samples_on_either_side_is_not_comparable() -> None:
    small = _cell(assessed_count=4, pass_count=2, fail_count=2)
    large = _cell(assessed_count=10, pass_count=5, fail_count=5)

    left_short = _only(compare_release_quality([small], [large], min_samples=5, unexplained_loss=False))
    right_short = _only(compare_release_quality([large], [small], min_samples=5, unexplained_loss=False))

    assert (left_short.reason, right_short.reason) == ("insufficient_samples", "insufficient_samples")
    assert (left_short.left_sample_count, left_short.right_sample_count) == (4, 10)
    assert (right_short.left_sample_count, right_short.right_sample_count) == (10, 4)
    assert left_short.observed_delta is None
    # The same pair becomes comparable once the configured minimum drops.
    assert _only(compare_release_quality([small], [large], min_samples=4, unexplained_loss=False)).comparison_status == "comparable"


def test_unexplained_observability_loss_blocks_an_otherwise_comparable_cohort() -> None:
    left = _cell(mean_score=0.5, scale={"min": 0.0, "max": 1.0})
    right = _cell(mean_score=0.8, scale={"min": 0.0, "max": 1.0})

    comparison = _only(compare_release_quality([left], [right], min_samples=5, unexplained_loss=True))

    assert comparison.comparison_status == "not_comparable"
    assert comparison.reason == "observability_loss"
    assert comparison.observed_delta is None
    assert comparison.coverage["unexplained_loss"] is True


def test_comparisons_cover_the_union_of_dimensions_in_a_stable_order() -> None:
    left = [
        _cell(dimension="safety", mean_score=0.5, scale={"min": 0.0, "max": 1.0}),
        _cell(dimension="correctness", mean_score=0.5, scale={"min": 0.0, "max": 1.0}),
    ]
    right = [
        _cell(dimension="correctness", mean_score=0.6, scale={"min": 0.0, "max": 1.0}),
        _cell(dimension="completeness", mean_score=0.6, scale={"min": 0.0, "max": 1.0}),
    ]

    comparisons = compare_release_quality(left, right, min_samples=5, unexplained_loss=False)

    assert [item.dimension for item in comparisons] == ["completeness", "correctness", "safety"]
    assert [item.comparison_status for item in comparisons] == [
        "not_comparable",
        "comparable",
        "not_comparable",
    ]


def test_release_quality_views_are_frozen_and_reject_unknown_fields() -> None:
    view = ReleaseQualityView(release_id="release-1", cohorts=(_cell(),))

    assert view.model_config["frozen"] is True
    with pytest.raises(ValidationError):
        ReleaseQualityView(release_id="release-1", cohorts=(), unexpected=1)


# ---------------------------------------------------------------------------
# Service surface (real SQLite service)
# ---------------------------------------------------------------------------


def _producer(name: str = "ansich-evaluation-api") -> Producer:
    return Producer(name=name, version="1", instance_id="gateway")


@asynccontextmanager
async def _evaluation_service(
    tmp_path: Path,
    database_name: str,
    **overrides: object,
) -> AsyncIterator[tuple[AnsichService, async_sessionmaker[AsyncSession]]]:
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / database_name}",
        connect_args={"timeout": 30},
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    settings: dict[str, object] = {
        "flush_interval_ms": 60_000,
        "terminal_flush_timeout_ms": 10_000,
        "projector_poll_interval_ms": 5,
        "operations_assessment_interval_ms": 60_000,
    }
    settings.update(overrides)
    service = create_sql_ansich_service(session_factory, **settings)
    await service.start()
    try:
        yield service, session_factory
    finally:
        await service.stop()
        await engine.dispose()


def _task_created(task_id: str, run_id: str) -> ObservationEnvelope:
    return ObservationEnvelope.task_lifecycle(
        kind="task.created",
        task_id=task_id,
        source_kind="deerflow_run",
        source_id=run_id,
        occurred_at=_OCCURRED_AT,
        source_event_id=f"run:{run_id}:task:created",
    )


def _task_completed(task_id: str, run_id: str) -> ObservationEnvelope:
    return ObservationEnvelope.task_lifecycle(
        kind="task.completed",
        task_id=task_id,
        source_kind="deerflow_run",
        source_id=run_id,
        occurred_at=_OCCURRED_AT + timedelta(minutes=1),
        source_event_id=f"run:{run_id}:task:completed",
        producer_seq=2,
    )


def _release_resolved(task_id: str, run_id: str) -> ObservationEnvelope:
    return ObservationEnvelope.agent_release_resolved(
        task_id=task_id,
        run_id=run_id,
        occurred_at=_OCCURRED_AT,
        release=build_agent_release(
            AgentRuntimeDescriptor(
                namespace="deerflow",
                agent_name="lead-agent",
                requested_model="requested-alias",
                effective_model="provider/model-v1",
                model_provider="provider",
                model_behavior_parameters={"model": "provider/model-v1"},
                rendered_base_prompt="You are DeerFlow.",
                prompt_template_id="lead-v1",
                effective_policies={"non_interactive": False},
                runtime_build=RuntimeBuildDescriptor(package_version="2.1.0"),
            )
        ),
        source_event_id=f"run:{run_id}:agent-release:resolved",
    )


def _step_started(task_id: str, step_id: str, *, step_seq: int = 1) -> ObservationEnvelope:
    return ObservationEnvelope(
        kind="step.started",
        occurred_at=_OCCURRED_AT,
        task_id=task_id,
        step_id=step_id,
        subject_type="step",
        subject_id=step_id,
        producer=_producer("ansich-step-probe"),
        source_event_id=f"step:{step_id}:started",
        correlation_id=task_id,
        payload={"step_seq": step_seq, "actor_kind": "lead_agent"},
    )


def _benchmark(task_id: str, **overrides: object) -> EvaluationRecord:
    fields: dict[str, object] = {
        "subject_type": "task",
        "subject_id": task_id,
        "task_id": task_id,
        "evaluation_kind": "benchmark_assertion",
        "dimension": "correctness",
        "verdict": "pass",
        "assessor": _BENCHMARK_ASSESSOR,
        "fidelity_class": "hard",
        "suite": "ansich-regression",
        "suite_version": "2026.08.1",
        "case_id": "case-1",
        "run_id": "bench-run-1",
        "occurred_at": _OCCURRED_AT,
    }
    fields.update(overrides)
    return EvaluationRecord(**fields)


def _annotation(task_id: str, **overrides: object) -> EvaluationRecord:
    fields: dict[str, object] = {
        "evaluation_kind": "developer_annotation",
        "assessor": _OPERATOR_ASSESSOR,
        "fidelity_class": "soft",
        "suite": None,
        "suite_version": None,
        "case_id": None,
        "run_id": None,
    }
    fields.update(overrides)
    return _benchmark(task_id, **fields)


@pytest.mark.anyio
async def test_record_evaluation_receipt_is_applied_after_a_bounded_settle(tmp_path) -> None:
    task_id, run_id = new_id(), "eval-service-applied"

    async with _evaluation_service(tmp_path, "ansich-evaluation-applied.db") as (
        service,
        session_factory,
    ):
        service.record(_task_created(task_id, run_id))
        await service.flush_task(task_id)

        receipt = await service.record_evaluation(
            _benchmark(task_id, verdict="fail", score=0.25, scale=_UNIT_SCALE),
            source_event_id=None,
            producer=_producer(),
        )

        async with session_factory() as session:
            index_row = await session.get(AnsichEvaluationIndexRow, receipt.observation_id)
        belief = await service.get_current_belief(task_id, "quality.correctness")

    assert isinstance(receipt, EvaluationRecordReceipt)
    assert receipt.projection_status == "applied"
    assert receipt.idempotent_replay is False
    assert index_row is not None
    assert belief is not None


@pytest.mark.anyio
async def test_record_evaluation_replays_a_known_source_event_id(tmp_path) -> None:
    task_id, run_id = new_id(), "eval-service-replay"
    record = _benchmark(task_id)

    async with _evaluation_service(tmp_path, "ansich-evaluation-replay.db") as (
        service,
        session_factory,
    ):
        service.record(_task_created(task_id, run_id))
        await service.flush_task(task_id)

        first = await service.record_evaluation(record, source_event_id=None, producer=_producer())
        second = await service.record_evaluation(record, source_event_id=None, producer=_producer())

        async with session_factory() as session:
            observation_count = await session.scalar(select(func.count()).select_from(AnsichObservationRow).where(AnsichObservationRow.kind == "evaluation.recorded"))
            index_count = await session.scalar(select(func.count()).select_from(AnsichEvaluationIndexRow))

    assert first.idempotent_replay is False
    assert second.idempotent_replay is True
    assert second.observation_id == first.observation_id
    assert second.projection_status == "applied"
    assert observation_count == 1
    assert index_count == 1


@pytest.mark.anyio
async def test_record_evaluation_receipt_is_pending_while_the_subject_is_missing(tmp_path) -> None:
    task_id, run_id, missing_step_id = new_id(), "eval-service-pending", new_id()

    async with _evaluation_service(
        tmp_path,
        "ansich-evaluation-pending.db",
        # The settle attempt is bounded: a dependency-pending job never settles,
        # so the receipt must report the current state instead of waiting.
        terminal_flush_timeout_ms=300,
    ) as (service, session_factory):
        service.record(_task_created(task_id, run_id))
        await service.flush_task(task_id)

        receipt = await service.record_evaluation(
            _annotation(
                task_id,
                subject_type="step",
                subject_id=missing_step_id,
                verdict="fail",
            ),
            source_event_id="evaluation:api:pending-subject",
            producer=_producer(),
        )

        async with session_factory() as session:
            job = await session.scalar(
                select(AnsichProjectionJobRow).where(
                    AnsichProjectionJobRow.obs_id == receipt.observation_id,
                )
            )
            index_row = await session.get(AnsichEvaluationIndexRow, receipt.observation_id)

    assert receipt.projection_status == "pending"
    assert receipt.idempotent_replay is False
    # "pending" is the state of a real, still-claimable job — not the absence
    # of one: the Observation is durable and waiting for its missing subject.
    assert job is not None
    assert job.status in {"pending", "processing"}
    assert index_row is None


@pytest.mark.anyio
async def test_record_evaluation_receipt_is_failed_without_durable_storage() -> None:
    task_id = new_id()
    service = create_embedded_ansich_service(AnsichConfig(enabled=True), None)
    assert service is not None
    await service.start()
    try:
        receipt = await service.record_evaluation(
            _benchmark(task_id),
            source_event_id=None,
            producer=_producer(),
        )
        health = service.get_health()
    finally:
        await service.stop()

    assert health.storage_available is False
    assert receipt.projection_status == "failed"
    assert receipt.idempotent_replay is False


class _StalledStorageBackend:
    """A storage backend whose write cannot finish inside the terminal window.

    ``persist_and_project`` is the only method the collector needs; every read is
    duck-typed and safely absent. The gate lets the test release the pending
    write before shutdown instead of leaving a coroutine parked forever.
    """

    def __init__(self) -> None:
        self.released = asyncio.Event()
        self.persist_calls = 0

    async def persist_and_project(self, observations):
        self.persist_calls += 1
        await self.released.wait()
        return len(observations)


@pytest.mark.anyio
async def test_record_evaluation_receipt_is_failed_when_the_flush_does_not_persist() -> None:
    """The intake's own write did not land, so the receipt may not say `pending`.

    A `pending` receipt is a promise that a projection job exists to poll, and
    nothing was written here — that part is F10-7's subject and is unchanged.
    What changed under RA5② is the fate of the Observation: the terminal window
    closing is not a refusal, so the row goes back on the queue for the writer
    instead of being charged as lost. The receipt is therefore *conservative*
    rather than final — the row may still land — which is the direction Task 7
    revisits when receipt terminality gets its own rules.
    """

    task_id = new_id()
    backend = _StalledStorageBackend()
    service = AnsichService(
        backend,
        flush_interval_ms=60_000,
        # The write is still in flight when the terminal window closes, so
        # flush_task returns without having persisted anything.
        terminal_flush_timeout_ms=50,
    )
    await service.start()
    try:
        receipt = await service.record_evaluation(
            _benchmark(task_id),
            source_event_id=None,
            producer=_producer(),
        )
        health = service.get_health()
    finally:
        backend.released.set()
        await service.stop()

    assert backend.persist_calls >= 1
    assert receipt.projection_status == "failed"
    assert receipt.idempotent_replay is False
    # Nothing refused the write, so nothing is charged: the Observation is in
    # the queue or in the writer's hands, never nowhere.
    assert health.loss_detected is False
    assert health.dropped_count == 0
    assert health.lost_ranges == ()
    assert health.queue_depth + health.writer.in_flight_count == 1


@pytest.mark.anyio
async def test_record_evaluation_receipt_is_failed_on_a_stopped_service(tmp_path) -> None:
    task_id, run_id = new_id(), "eval-service-stopped"

    async with _evaluation_service(tmp_path, "ansich-evaluation-stopped.db") as (
        service,
        _session_factory,
    ):
        service.record(_task_created(task_id, run_id))
        await service.flush_task(task_id)
        await service.stop()

        receipt = await service.record_evaluation(
            _benchmark(task_id),
            source_event_id=None,
            producer=_producer(),
        )

    assert receipt.projection_status == "failed"
    assert receipt.idempotent_replay is False


@pytest.mark.anyio
async def test_quality_beliefs_stay_unassessed_for_a_completed_task_without_evaluations(tmp_path) -> None:
    task_id, run_id = new_id(), "eval-service-unassessed"

    async with _evaluation_service(tmp_path, "ansich-evaluation-unassessed.db") as (
        service,
        _session_factory,
    ):
        service.record_batch((_task_created(task_id, run_id), _task_completed(task_id, run_id)))
        await service.flush_task(task_id)

        task = await service.get_task(task_id)
        beliefs = await service.get_quality_beliefs(task_id)

    assert task is not None
    assert task.control.value == "completed"
    assert [belief.dimension for belief in beliefs] == list(QUALITY_DIMENSIONS)
    assert [belief.dimension for belief in beliefs] == [
        "correctness",
        "completeness",
        "relevance",
        "safety",
        "efficiency",
    ]
    for belief in beliefs:
        assert isinstance(belief, QualityBeliefView)
        assert belief.unassessed is True
        assert belief.value == {"status": "unassessed"}
        assert belief.source == UNASSESSED_SOURCE
        assert belief.source == NamedVersion(name="none", version="1")
        assert belief.as_of is None
        assert belief.resolver is None
        assert belief.conflicting_assertion_count == 0
        # A completed Task never implies pass, so no evidence may be invented.
        assert belief.evidence_obs_ids == ()


@pytest.mark.anyio
async def test_quality_beliefs_report_the_selected_assertion_and_its_conflicts(tmp_path) -> None:
    task_id, run_id, step_id = new_id(), "eval-service-resolved", new_id()
    judged = build_evaluation_observation(
        _annotation(
            task_id,
            evaluation_kind="llm_judge",
            assessor=_JUDGE_ASSESSOR,
            verdict="fail",
        ),
        producer=_producer(),
        source_event_id="evaluation:api:judge",
    )
    annotated = build_evaluation_observation(
        _annotation(task_id, verdict="pass"),
        producer=_producer(),
        source_event_id="evaluation:api:annotation",
    )
    earliest = build_evaluation_observation(
        _annotation(
            task_id,
            dimension="earliest_erroneous_step",
            verdict="fail",
            actual=step_id,
        ),
        producer=_producer(),
        source_event_id="evaluation:api:earliest",
    )

    async with _evaluation_service(tmp_path, "ansich-evaluation-resolved.db") as (
        service,
        _session_factory,
    ):
        service.record_batch(
            (
                _task_created(task_id, run_id),
                _step_started(task_id, step_id, step_seq=3),
                judged,
                annotated,
                earliest,
            )
        )
        await service.flush_task(task_id)

        beliefs = {belief.dimension: belief for belief in await service.get_quality_beliefs(task_id)}

    # ``earliest_erroneous_step`` only appears because a Belief exists for it.
    assert list(beliefs) == [*QUALITY_DIMENSIONS, "earliest_erroneous_step"]
    correctness = beliefs["correctness"]
    assert correctness.unassessed is False
    # soft_human (developer annotation) outranks the automated LLM judge.
    assert correctness.value["verdict"] == "pass"
    assert correctness.authority_class == "soft_human"
    assert correctness.fidelity_class == "soft"
    assert correctness.source == _OPERATOR_ASSESSOR
    assert correctness.resolver == _RESOLVER
    assert correctness.conflicting_assertion_count == 1
    assert correctness.evidence_obs_ids == (annotated.obs_id,)
    assert correctness.as_of == _OCCURRED_AT
    assert beliefs["earliest_erroneous_step"].value == {"step_id": step_id, "step_seq": 3, "verdict": "fail"}
    assert beliefs["earliest_erroneous_step"].conflicting_assertion_count == 0
    assert beliefs["safety"].unassessed is True
    assert beliefs["safety"].conflicting_assertion_count == 0


@pytest.mark.anyio
async def test_list_evaluations_filters_by_subject_and_task(tmp_path) -> None:
    first_task, second_task, step_id = new_id(), new_id(), new_id()
    task_evaluation = build_evaluation_observation(
        _benchmark(first_task, case_id="case-task"),
        producer=_producer(),
    )
    step_evaluation = build_evaluation_observation(
        _annotation(
            first_task,
            subject_type="step",
            subject_id=step_id,
            dimension="relevance",
            verdict="partial",
            occurred_at=_OCCURRED_AT + timedelta(minutes=2),
        ),
        producer=_producer(),
        source_event_id="evaluation:api:step-subject",
    )
    other_task_evaluation = build_evaluation_observation(
        _benchmark(second_task, case_id="case-other", run_id="bench-run-2"),
        producer=_producer(),
    )

    async with _evaluation_service(tmp_path, "ansich-evaluation-list.db") as (
        service,
        _session_factory,
    ):
        service.record_batch(
            (
                _task_created(first_task, "eval-list-run-a"),
                _task_created(second_task, "eval-list-run-b"),
                _step_started(first_task, step_id, step_seq=1),
                task_evaluation,
                step_evaluation,
                other_task_evaluation,
            )
        )
        await service.flush_task(first_task)
        await service.flush_task(second_task)

        by_task = await service.list_evaluations(task_id=first_task)
        by_subject_type = await service.list_evaluations(subject_type="step")
        by_subject_id = await service.list_evaluations(subject_id=second_task)
        limited = await service.list_evaluations(limit=1)
        everything = await service.list_evaluations()

    assert [item.evaluation_obs_id for item in by_task] == [
        step_evaluation.obs_id,
        task_evaluation.obs_id,
    ]
    assert all(isinstance(item, EvaluationView) for item in by_task)
    assert [item.evaluation_obs_id for item in by_subject_type] == [step_evaluation.obs_id]
    assert by_subject_type[0].subject_id == step_id
    assert [item.evaluation_obs_id for item in by_subject_id] == [other_task_evaluation.obs_id]
    assert len(limited) == 1
    assert len(everything) == 3
    projected = by_task[1]
    assert projected.subject_type == "task"
    assert projected.task_id == first_task
    assert projected.evaluation_kind == "benchmark_assertion"
    assert projected.dimension == "correctness"
    assert projected.verdict == "pass"
    assert projected.assessor_name == _BENCHMARK_ASSESSOR.name
    assert projected.assessor_version == _BENCHMARK_ASSESSOR.version
    assert projected.authority_class == "deterministic"
    assert projected.fidelity_class == "hard"
    assert projected.cohort_key == "ansich-regression@2026.08.1"
    assert (projected.suite_id, projected.suite_version, projected.case_id) == (
        "ansich-regression",
        "2026.08.1",
        "case-task",
    )
    assert projected.occurred_at == _OCCURRED_AT
    with pytest.raises(ValueError, match="limit must be positive"):
        await service.list_evaluations(limit=0)


@pytest.mark.anyio
async def test_get_evaluation_subject_reports_the_entity_type(tmp_path) -> None:
    task_id, run_id, step_id = new_id(), "eval-service-subject", new_id()

    async with _evaluation_service(tmp_path, "ansich-evaluation-subject.db") as (
        service,
        _session_factory,
    ):
        service.record_batch((_task_created(task_id, run_id), _step_started(task_id, step_id)))
        await service.flush_task(task_id)

        task_type = await service.get_evaluation_subject(task_id)
        step_type = await service.get_evaluation_subject(step_id)
        unknown = await service.get_evaluation_subject(new_id())

    assert task_type == "task"
    assert step_type == "step"
    assert unknown is None


@pytest.mark.anyio
async def test_get_release_quality_derives_the_mean_score_and_filters_by_cohort(tmp_path) -> None:
    first_task, second_task = new_id(), new_id()
    passing = build_evaluation_observation(
        _benchmark(first_task, verdict="pass", score=1.0, scale=_UNIT_SCALE, case_id="case-a", run_id="bench-a"),
        producer=_producer(),
    )
    failing = build_evaluation_observation(
        _benchmark(
            second_task,
            verdict="fail",
            score=0.0,
            scale=_UNIT_SCALE,
            case_id="case-b",
            run_id="bench-b",
            occurred_at=_OCCURRED_AT + timedelta(minutes=5),
        ),
        producer=_producer(),
    )

    async with _evaluation_service(tmp_path, "ansich-evaluation-release-quality.db") as (
        service,
        session_factory,
    ):
        service.record_batch(
            (
                _task_created(first_task, "eval-quality-run-a"),
                _release_resolved(first_task, "eval-quality-run-a"),
                passing,
            )
        )
        await service.flush_task(first_task)
        service.record_batch(
            (
                _task_created(second_task, "eval-quality-run-b"),
                _release_resolved(second_task, "eval-quality-run-b"),
                failing,
            )
        )
        await service.flush_task(second_task)

        async with session_factory() as session:
            release_id = await session.scalar(select(AnsichTaskAgentReleaseRow.release_id).where(AnsichTaskAgentReleaseRow.task_id == first_task))

        quality = await service.get_release_quality(release_id)
        matching_cohort = await service.get_release_quality(release_id, cohort_key="ansich-regression@2026.08.1")
        other_cohort = await service.get_release_quality(release_id, cohort_key="ansich-regression@2026.09.1")
        unknown = await service.get_release_quality(new_id())

    assert isinstance(quality, ReleaseQualityView)
    assert quality.release_id == release_id
    assert len(quality.cohorts) == 1
    cohort = quality.cohorts[0]
    assert cohort.dimension == "correctness"
    assert cohort.cohort_key == "ansich-regression@2026.08.1"
    assert (cohort.assessed_count, cohort.pass_count, cohort.fail_count, cohort.partial_count) == (2, 1, 1, 0)
    # mean_score is derived at read time from score_sum/score_count.
    assert cohort.mean_score == pytest.approx(0.5)
    # Polarity travels with the range so the comparability gate can see it.
    assert cohort.scale == {"min": 0.0, "max": 1.0, "higher_is_better": True}
    assert cohort.as_of == _OCCURRED_AT + timedelta(minutes=5)
    assert matching_cohort is not None
    assert len(matching_cohort.cohorts) == 1
    assert other_cohort is not None
    assert other_cohort.cohorts == ()
    assert unknown is None


@pytest.mark.anyio
async def test_release_quality_without_scores_reports_no_mean(tmp_path) -> None:
    task_id, run_id = new_id(), "eval-quality-verdict-only"
    observation = build_evaluation_observation(
        _annotation(task_id, evaluation_kind="user_feedback", assessor=_JUDGE_ASSESSOR, verdict="partial"),
        producer=_producer(),
        source_event_id="evaluation:api:verdict-only",
    )

    async with _evaluation_service(tmp_path, "ansich-evaluation-verdict-only.db") as (
        service,
        session_factory,
    ):
        service.record_batch((_task_created(task_id, run_id), _release_resolved(task_id, run_id), observation))
        await service.flush_task(task_id)

        async with session_factory() as session:
            release_id = await session.scalar(select(AnsichTaskAgentReleaseRow.release_id).where(AnsichTaskAgentReleaseRow.task_id == task_id))
        quality = await service.get_release_quality(release_id)
        empty_release = await service.get_release_quality(release_id, cohort_key="unknown-cohort")

    assert quality is not None
    assert len(quality.cohorts) == 1
    cohort = quality.cohorts[0]
    assert cohort.cohort_key == ""
    assert cohort.mean_score is None
    assert cohort.scale is None
    assert (cohort.assessed_count, cohort.partial_count) == (1, 1)
    assert empty_release is not None
    assert empty_release.cohorts == ()


@pytest.mark.anyio
async def test_evaluation_reads_stay_safe_on_a_service_without_evaluation_storage() -> None:
    service = create_embedded_ansich_service(AnsichConfig(enabled=True), None)
    assert service is not None
    await service.start()
    try:
        beliefs = await service.get_quality_beliefs(new_id())
        evaluations = await service.list_evaluations(task_id=new_id())
        subject = await service.get_evaluation_subject(new_id())
        quality = await service.get_release_quality(new_id())
    finally:
        await service.stop()

    assert evaluations == []
    assert subject is None
    assert quality is None
    assert [belief.dimension for belief in beliefs] == list(QUALITY_DIMENSIONS)
    assert all(belief.unassessed for belief in beliefs)
