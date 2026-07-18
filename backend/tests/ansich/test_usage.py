from datetime import UTC, datetime

import pytest
from ansich import ObservationEnvelope, Producer, new_id
from ansich.usage import (
    child_task_contribution_for_tool_started,
    usage_contributions_for_observation,
)


def _observation(*, kind: str, payload: dict[str, object]) -> ObservationEnvelope:
    task_id = new_id()
    attempt_id = new_id()
    return ObservationEnvelope(
        kind=kind,
        occurred_at=datetime(2026, 7, 18, 9, 0, tzinfo=UTC),
        task_id=task_id,
        subject_type="llm_attempt",
        subject_id=attempt_id,
        producer=Producer(name="usage-test", version="1", instance_id="test"),
        source_event_id=f"attempt:{attempt_id}:{kind}",
        correlation_id=task_id,
        payload=payload,
    )


def test_total_only_provider_usage_does_not_invent_input_or_output_tokens():
    observation = _observation(
        kind="llm.responded",
        payload={
            "attempt_no": 1,
            "latency_ms": 25,
            "usage": {"total_tokens": 41},
        },
    )

    contributions = usage_contributions_for_observation(observation)

    assert [(item.dimension, item.delta) for item in contributions] == [
        ("total_tokens", 41),
    ]
    assert contributions[0].source_obs_id == observation.obs_id
    assert contributions[0].as_of == observation.occurred_at


def test_step_started_is_the_only_source_of_the_step_usage_delta():
    task_id = new_id()
    step_id = new_id()
    observation = ObservationEnvelope(
        kind="step.started",
        occurred_at=datetime(2026, 7, 18, 9, 1, tzinfo=UTC),
        task_id=task_id,
        step_id=step_id,
        subject_type="step",
        subject_id=step_id,
        producer=Producer(name="usage-test", version="1", instance_id="test"),
        source_event_id=f"step:{step_id}:started",
        correlation_id=task_id,
        payload={"step_seq": 1, "actor_kind": "lead_agent"},
    )

    contributions = usage_contributions_for_observation(observation)

    assert [(item.dimension, item.delta) for item in contributions] == [
        ("steps", 1),
    ]
    assert contributions[0].source_obs_id == observation.obs_id


@pytest.mark.parametrize(
    ("kind", "subject_type", "dimension"),
    [
        ("llm.requested", "llm_attempt", "llm_attempts"),
        ("tool.issued", "tool_call", "tool_calls_issued"),
        ("tool.started", "tool_call", "tool_calls_executed"),
        ("tool.returned_raw", "tool_call", "tool_calls_executed"),
        ("tool.failed", "tool_call", "tool_calls_executed"),
    ],
)
def test_structural_observations_map_to_independent_usage_dimensions(
    kind: str,
    subject_type: str,
    dimension: str,
):
    task_id = new_id()
    subject_id = new_id()
    step_id = new_id()
    observation = ObservationEnvelope(
        kind=kind,
        occurred_at=datetime(2026, 7, 18, 9, 2, tzinfo=UTC),
        task_id=task_id,
        step_id=step_id,
        subject_type=subject_type,
        subject_id=subject_id,
        producer=Producer(name="usage-test", version="1", instance_id="test"),
        source_event_id=f"{kind}:{subject_id}",
        correlation_id=task_id,
        payload={"attempt_no": 1} if kind.startswith("llm.") else {"call_seq": 1},
    )

    contributions = usage_contributions_for_observation(observation)

    assert [(item.dimension, item.delta) for item in contributions] == [
        (dimension, 1),
    ]


def test_explicit_budget_consumption_maps_to_its_declared_local_dimension():
    task_id = new_id()
    observation = ObservationEnvelope.budget_consumed(
        task_id=task_id,
        run_id="run-wall-time",
        occurred_at=datetime(2026, 7, 18, 9, 3, tzinfo=UTC),
        dimension="wall_time_ms",
        delta=1234,
        source_event_id="run:run-wall-time:budget:wall-time",
    )

    contributions = usage_contributions_for_observation(observation)

    assert [(item.dimension, item.delta) for item in contributions] == [
        ("wall_time_ms", 1234),
    ]
    assert contributions[0].task_id == task_id
    assert contributions[0].source_task_id == task_id


def test_started_task_tool_counts_one_spawned_child_without_counting_other_tools():
    task_id = new_id()
    step_id = new_id()
    tool_call_id = new_id()
    started = ObservationEnvelope(
        kind="tool.started",
        occurred_at=datetime(2026, 7, 18, 9, 4, tzinfo=UTC),
        task_id=task_id,
        step_id=step_id,
        subject_type="tool_call",
        subject_id=tool_call_id,
        producer=Producer(name="usage-test", version="1", instance_id="test"),
        source_event_id=f"tool:{tool_call_id}:started",
        correlation_id=task_id,
        payload={"call_seq": 1},
    )

    contribution = child_task_contribution_for_tool_started(
        started,
        tool_name="task",
    )
    ordinary = child_task_contribution_for_tool_started(
        started,
        tool_name="bash",
    )

    assert contribution is not None
    assert contribution.dimension == "child_tasks_spawned"
    assert contribution.delta == 1
    assert ordinary is None
