from __future__ import annotations

from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from ansich.contracts import NamedVersion, ObservationEnvelope, Producer
from ansich.ids import new_id

EVALUATION_OBSERVATION_KIND = "evaluation.recorded"

EvaluationKind = Literal[
    "user_feedback",
    "developer_annotation",
    "benchmark_assertion",
    "unit_test",
    "llm_judge",
]
EvaluationDimension = Literal[
    "correctness",
    "completeness",
    "relevance",
    "safety",
    "efficiency",
    "earliest_erroneous_step",
    "custom",
]
EvaluationVerdict = Literal["pass", "fail", "partial", "unknown"]
EvaluationSubjectType = Literal[
    "task",
    "step",
    "tool_call",
    "content_block",
    "agent_release",
]

_SUITE_BOUND_KINDS = frozenset({"benchmark_assertion", "unit_test"})


class ScoreScale(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    min: float
    max: float
    higher_is_better: bool

    @model_validator(mode="after")
    def _range_is_ordered(self) -> Self:
        if self.max <= self.min:
            raise ValueError("score scale max must be greater than min")
        return self


class EvaluationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    subject_type: EvaluationSubjectType
    subject_id: str
    task_id: str
    evaluation_kind: EvaluationKind
    dimension: EvaluationDimension
    verdict: EvaluationVerdict | None = None
    score: float | None = None
    scale: ScoreScale | None = None
    expected: str | None = None
    actual: str | None = None
    rationale: str | None = None
    assessor: NamedVersion
    fidelity_class: Literal["hard", "rule", "soft"]
    human_override: bool = False
    cohort_key: str | None = None
    suite: str | None = None
    suite_version: str | None = None
    case_id: str | None = None
    run_id: str | None = None
    occurred_at: datetime

    @model_validator(mode="before")
    @classmethod
    def _default_suite_cohort_key(cls, data: object) -> object:
        """Default the comparison cohort of a suite-bound evaluation to its suite release."""

        if not isinstance(data, dict) or data.get("cohort_key") is not None:
            return data
        if data.get("evaluation_kind") not in _SUITE_BOUND_KINDS:
            return data
        suite = data.get("suite")
        suite_version = data.get("suite_version")
        if not isinstance(suite, str) or not isinstance(suite_version, str):
            return data
        return {**data, "cohort_key": f"{suite}@{suite_version}"}

    @field_validator("occurred_at")
    @classmethod
    def _timestamp_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("evaluation timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def _validate_evaluation(self) -> Self:
        if self.verdict is None and self.score is None:
            raise ValueError("evaluation must carry a verdict or a score")
        if self.score is not None and self.scale is None:
            raise ValueError("evaluation score requires a scale")
        if self.fidelity_class == "hard":
            if self.evaluation_kind not in _SUITE_BOUND_KINDS:
                raise ValueError("hard fidelity requires a benchmark_assertion or unit_test evaluation")
            if self.suite is None or self.suite_version is None or self.case_id is None:
                raise ValueError("hard fidelity requires suite, suite_version, and case_id")
        if self.evaluation_kind in _SUITE_BOUND_KINDS and (self.suite is None or self.suite_version is None or self.case_id is None):
            raise ValueError("benchmark and unit_test evaluations require suite, suite_version, and case_id")
        if self.human_override and self.evaluation_kind != "developer_annotation":
            raise ValueError("human_override is only allowed for developer_annotation evaluations")
        if self.dimension == "earliest_erroneous_step":
            if self.subject_type != "task":
                raise ValueError("earliest_erroneous_step evaluations must target a task subject")
            if not self.actual:
                raise ValueError("earliest_erroneous_step evaluations must name the Step id in actual")
        return self


def benchmark_source_event_id(
    *,
    suite: str,
    suite_version: str,
    case_id: str,
    run_id: str,
    dimension: str,
) -> str:
    """Return the replay-stable intake identity of one benchmark evaluation."""

    return f"evaluation:benchmark:{suite}:{suite_version}:{case_id}:{run_id}:{dimension}"


def build_evaluation_observation(
    record: EvaluationRecord,
    *,
    producer: Producer,
    source_event_id: str | None = None,
    obs_id: str | None = None,
) -> ObservationEnvelope:
    """Wrap an EvaluationRecord in its `evaluation.recorded` Observation envelope."""

    if source_event_id is not None:
        resolved_source_event_id = source_event_id
    elif record.evaluation_kind in _SUITE_BOUND_KINDS:
        if record.run_id is None:
            raise ValueError("benchmark evaluations require run_id to derive a source_event_id")
        # suite/suite_version/case_id are guaranteed present for suite-bound kinds.
        resolved_source_event_id = benchmark_source_event_id(
            suite=record.suite,
            suite_version=record.suite_version,
            case_id=record.case_id,
            run_id=record.run_id,
            dimension=record.dimension,
        )
    else:
        raise ValueError("source_event_id is required for non-benchmark evaluations")
    return ObservationEnvelope(
        obs_id=obs_id if obs_id is not None else new_id(),
        kind=EVALUATION_OBSERVATION_KIND,
        occurred_at=record.occurred_at,
        task_id=record.task_id,
        subject_type=record.subject_type,
        subject_id=record.subject_id,
        producer=producer,
        source_event_id=resolved_source_event_id,
        correlation_id=record.run_id if record.run_id is not None else record.task_id,
        payload={"evaluation": record.model_dump(mode="json")},
    )
