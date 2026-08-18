from __future__ import annotations

from datetime import UTC, datetime

import pytest
from ansich import (
    EVALUATION_OBSERVATION_KIND,
    EvaluationRecord,
    NamedVersion,
    ObservationEnvelope,
    Producer,
    ScoreScale,
    benchmark_source_event_id,
    build_evaluation_observation,
    new_id,
)
from pydantic import ValidationError
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from deerflow.ansich import create_sql_ansich_service
from deerflow.ansich.persistence.models import AnsichObservationRow
from deerflow.persistence.base import Base

_ASSESSOR = NamedVersion(name="ansich-benchmark-runner", version="1.0.0")
_OCCURRED_AT = datetime(2026, 8, 18, 9, tzinfo=UTC)


def _benchmark_record(*, task_id: str, **overrides: object) -> EvaluationRecord:
    fields: dict[str, object] = {
        "subject_type": "task",
        "subject_id": task_id,
        "task_id": task_id,
        "evaluation_kind": "benchmark_assertion",
        "dimension": "correctness",
        "verdict": "pass",
        "expected": "the capital of France is Paris",
        "actual": "the capital of France is Paris",
        "assessor": _ASSESSOR,
        "fidelity_class": "hard",
        "suite": "ansich-regression",
        "suite_version": "2026.08.1",
        "case_id": "case-7",
        "run_id": "bench-run-3",
        "occurred_at": _OCCURRED_AT,
    }
    fields.update(overrides)
    return EvaluationRecord(**fields)


def _producer() -> Producer:
    return Producer(name="ansich-evaluation-intake", version="1", instance_id="test")


def test_benchmark_record_builds_an_evaluation_observation() -> None:
    task_id = new_id()
    record = _benchmark_record(
        task_id=task_id,
        score=1.0,
        scale=ScoreScale(min=0.0, max=1.0, higher_is_better=True),
    )

    observation = build_evaluation_observation(record, producer=_producer())

    assert EVALUATION_OBSERVATION_KIND == "evaluation.recorded"
    assert observation.kind == EVALUATION_OBSERVATION_KIND
    assert observation.subject_type == "task"
    assert observation.subject_id == task_id
    assert observation.task_id == task_id
    assert observation.occurred_at == _OCCURRED_AT
    assert observation.source_event_id == benchmark_source_event_id(
        suite="ansich-regression",
        suite_version="2026.08.1",
        case_id="case-7",
        run_id="bench-run-3",
        dimension="correctness",
    )
    assert observation.payload is not None
    assert EvaluationRecord.model_validate(observation.payload["evaluation"], strict=False) == record
    assert record.cohort_key == "ansich-regression@2026.08.1"


def test_explicit_obs_id_is_carried_into_the_envelope() -> None:
    task_id = new_id()
    obs_id = new_id()

    observation = build_evaluation_observation(
        _benchmark_record(task_id=task_id),
        producer=_producer(),
        obs_id=obs_id,
    )

    assert observation.obs_id == obs_id


def test_benchmark_source_event_id_is_deterministic_and_dimension_scoped() -> None:
    identity = {
        "suite": "ansich-regression",
        "suite_version": "2026.08.1",
        "case_id": "case-7",
        "run_id": "bench-run-3",
    }

    first = benchmark_source_event_id(**identity, dimension="correctness")
    second = benchmark_source_event_id(**identity, dimension="correctness")
    other = benchmark_source_event_id(**identity, dimension="safety")

    assert first == second
    assert first == "evaluation:benchmark:ansich-regression:2026.08.1:case-7:bench-run-3:correctness"
    assert first != other


def test_score_scale_requires_max_above_min() -> None:
    with pytest.raises(ValidationError, match="max must be greater than min"):
        ScoreScale(min=1.0, max=1.0, higher_is_better=True)


def test_record_requires_a_verdict_or_a_score() -> None:
    with pytest.raises(ValidationError, match="verdict or a score"):
        _benchmark_record(task_id=new_id(), verdict=None)


def test_score_without_a_scale_is_rejected() -> None:
    with pytest.raises(ValidationError, match="score requires a scale"):
        _benchmark_record(task_id=new_id(), verdict=None, score=0.8)


def test_hard_fidelity_requires_a_suite_bound_kind_and_suite_identity() -> None:
    with pytest.raises(ValidationError, match="hard fidelity requires a benchmark_assertion or unit_test"):
        _benchmark_record(task_id=new_id(), evaluation_kind="llm_judge")

    with pytest.raises(ValidationError, match="hard fidelity requires suite, suite_version, and case_id"):
        _benchmark_record(task_id=new_id(), case_id=None)


def test_suite_bound_kinds_require_suite_identity_and_default_the_cohort_key() -> None:
    with pytest.raises(ValidationError, match="benchmark and unit_test evaluations require suite, suite_version, and case_id"):
        _benchmark_record(task_id=new_id(), evaluation_kind="unit_test", fidelity_class="rule", suite=None)

    defaulted = _benchmark_record(task_id=new_id(), evaluation_kind="unit_test", fidelity_class="rule")
    explicit = _benchmark_record(task_id=new_id(), cohort_key="release-candidate")

    assert defaulted.cohort_key == "ansich-regression@2026.08.1"
    assert explicit.cohort_key == "release-candidate"


def test_human_override_requires_a_developer_annotation() -> None:
    with pytest.raises(ValidationError, match="human_override is only allowed for developer_annotation"):
        _benchmark_record(task_id=new_id(), human_override=True)

    override = _benchmark_record(
        task_id=new_id(),
        evaluation_kind="developer_annotation",
        fidelity_class="soft",
        human_override=True,
        suite=None,
        suite_version=None,
        case_id=None,
    )

    assert override.human_override is True


def test_earliest_erroneous_step_requires_a_task_subject_and_a_step_id() -> None:
    task_id = new_id()
    step_id = new_id()

    with pytest.raises(ValidationError, match="earliest_erroneous_step evaluations must target a task subject"):
        _benchmark_record(
            task_id=task_id,
            dimension="earliest_erroneous_step",
            subject_type="step",
            subject_id=step_id,
            actual=step_id,
        )

    with pytest.raises(ValidationError, match="earliest_erroneous_step evaluations must name the Step id"):
        _benchmark_record(task_id=task_id, dimension="earliest_erroneous_step", actual=None)

    with pytest.raises(ValidationError, match="earliest_erroneous_step evaluations must name the Step id"):
        _benchmark_record(task_id=task_id, dimension="earliest_erroneous_step", actual="")

    located = _benchmark_record(task_id=task_id, dimension="earliest_erroneous_step", actual=step_id)

    assert located.actual == step_id


def test_naive_occurred_at_is_rejected() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        _benchmark_record(task_id=new_id(), occurred_at=datetime(2026, 8, 18, 9))


def test_non_benchmark_evaluations_require_an_explicit_source_event_id() -> None:
    task_id = new_id()
    record = _benchmark_record(
        task_id=task_id,
        evaluation_kind="user_feedback",
        fidelity_class="soft",
        suite=None,
        suite_version=None,
        case_id=None,
        run_id=None,
    )

    with pytest.raises(ValueError, match="source_event_id is required for non-benchmark evaluations"):
        build_evaluation_observation(record, producer=_producer())

    observation = build_evaluation_observation(
        record,
        producer=_producer(),
        source_event_id="evaluation:user_feedback:thread-1:message-2",
    )

    assert observation.source_event_id == "evaluation:user_feedback:thread-1:message-2"


def test_benchmark_evaluation_without_run_id_cannot_derive_a_source_event_id() -> None:
    record = _benchmark_record(task_id=new_id(), run_id=None)

    with pytest.raises(ValueError, match="run_id"):
        build_evaluation_observation(record, producer=_producer())


def test_evaluation_observation_rejects_an_unsupported_subject_type() -> None:
    task_id = new_id()
    payload = {"evaluation": _benchmark_record(task_id=task_id).model_dump(mode="json")}

    with pytest.raises(ValidationError, match="evaluation.recorded requires a task"):
        ObservationEnvelope(
            kind="evaluation.recorded",
            occurred_at=_OCCURRED_AT,
            task_id=task_id,
            subject_type="llm_attempt",
            subject_id=new_id(),
            producer=_producer(),
            source_event_id="evaluation:benchmark:wrong-subject-type",
            correlation_id="bench-run-3",
            payload=payload,
        )


def test_evaluation_observation_rejects_subject_and_task_mismatch() -> None:
    task_id = new_id()
    payload = {"evaluation": _benchmark_record(task_id=task_id).model_dump(mode="json")}

    with pytest.raises(ValidationError, match="evaluation payload subject must match the Observation subject"):
        ObservationEnvelope(
            kind="evaluation.recorded",
            occurred_at=_OCCURRED_AT,
            task_id=task_id,
            subject_type="task",
            subject_id=new_id(),
            producer=_producer(),
            source_event_id="evaluation:benchmark:subject-mismatch",
            correlation_id="bench-run-3",
            payload=payload,
        )

    with pytest.raises(ValidationError, match="evaluation payload task must match the Observation task"):
        ObservationEnvelope(
            kind="evaluation.recorded",
            occurred_at=_OCCURRED_AT,
            task_id=new_id(),
            subject_type="task",
            subject_id=task_id,
            producer=_producer(),
            source_event_id="evaluation:benchmark:task-mismatch",
            correlation_id="bench-run-3",
            payload=payload,
        )


def test_evaluation_observation_rejects_secret_bearing_payload_fields() -> None:
    task_id = new_id()

    with pytest.raises(ValidationError, match="secret-bearing field"):
        ObservationEnvelope(
            kind="evaluation.recorded",
            occurred_at=_OCCURRED_AT,
            task_id=task_id,
            subject_type="task",
            subject_id=task_id,
            producer=_producer(),
            source_event_id="evaluation:benchmark:secret-bearing",
            correlation_id="bench-run-3",
            payload={
                "evaluation": _benchmark_record(task_id=task_id).model_dump(mode="json"),
                "harness_request": {"Authorization": "Bearer should-never-persist"},
            },
        )


def test_externalized_evaluation_payload_skips_the_subject_cross_check() -> None:
    task_id = new_id()

    observation = ObservationEnvelope(
        kind="evaluation.recorded",
        occurred_at=_OCCURRED_AT,
        task_id=task_id,
        subject_type="task",
        subject_id=task_id,
        producer=_producer(),
        source_event_id="evaluation:benchmark:externalized",
        correlation_id="bench-run-3",
        payload=None,
        payload_ref_id=new_id(),
    )

    assert observation.payload is None


@pytest.mark.anyio
async def test_duplicate_benchmark_source_event_id_is_absorbed_once(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'evaluation-intake.db'}")

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(
        session_factory,
        flush_interval_ms=60_000,
        terminal_flush_timeout_ms=100,
        projector_poll_interval_ms=5,
        operations_assessment_interval_ms=60_000,
    )
    await service.start()
    task_id = new_id()
    producer = Producer(name="evaluation-intake-test", version="1", instance_id="test")
    record = _benchmark_record(task_id=task_id)
    first = build_evaluation_observation(record, producer=producer)
    second = build_evaluation_observation(record, producer=producer)

    try:
        service.record(
            ObservationEnvelope.task_lifecycle(
                kind="task.created",
                task_id=task_id,
                source_kind="deerflow_run",
                source_id="evaluation-intake-run",
                occurred_at=_OCCURRED_AT,
                source_event_id="evaluation-intake:task:created",
            )
        )
        await service.flush_task(task_id)
        service.record(first)
        service.record(second)
        await service.flush_task(task_id)

        async with session_factory() as session:
            evaluation_rows = tuple((await session.execute(select(AnsichObservationRow).where(AnsichObservationRow.kind == "evaluation.recorded"))).scalars())
    finally:
        await service.stop()
        await engine.dispose()

    assert first.obs_id != second.obs_id
    assert first.source_event_id == second.source_event_id
    assert len(evaluation_rows) == 1
    assert evaluation_rows[0].obs_id == first.obs_id
    assert evaluation_rows[0].payload_json is not None
    assert evaluation_rows[0].payload_json["evaluation"]["case_id"] == "case-7"
