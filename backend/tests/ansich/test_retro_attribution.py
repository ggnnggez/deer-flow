"""Retro validation matrix — token attribution.

Case D (#3875): the lead dispatched once (~12.5K tokens) while three subagents
burned 4.4M. Local vs inclusive usage must keep those separable, with a
breakdown that names the source task.

Case F (#3645): `by_model` attributed every run token to the lead agent's
single `model_name` column. Provider model identity must live on the attempt,
not on one run-level column.

See ansich/docs/plans/retro-validation-matrix.md.
"""

from datetime import UTC, datetime

import pytest
from ansich import ObservationEnvelope, new_id
from support.ansich_retro import RETRO_PRODUCER, close_task, open_task, retro_service


def _usage_value(values, dimension: str) -> int:
    for item in values:
        if item.dimension == dimension:
            return item.value
    return 0


@pytest.mark.anyio
async def test_case_d_child_token_burn_is_attributable_to_its_source_task(tmp_path):
    """#3875: lead dispatches once; the child burns the tokens. Both must be separable."""
    async with retro_service(tmp_path, "retro-case-d") as service:
        parent_task_id = await open_task(service, "run-case-d")
        parent_step_id = new_id()
        parent_tool_call_id = new_id()
        observed_at = datetime.now(UTC)

        service.record_batch(
            (
                ObservationEnvelope(
                    kind="step.started",
                    occurred_at=observed_at,
                    task_id=parent_task_id,
                    step_id=parent_step_id,
                    subject_type="step",
                    subject_id=parent_step_id,
                    producer=RETRO_PRODUCER,
                    source_event_id=f"step:{parent_step_id}:started",
                    correlation_id=parent_task_id,
                    payload={"step_seq": 1, "actor_kind": "lead_agent"},
                ),
                ObservationEnvelope(
                    kind="tool.issued",
                    occurred_at=observed_at,
                    task_id=parent_task_id,
                    step_id=parent_step_id,
                    subject_type="tool_call",
                    subject_id=parent_tool_call_id,
                    producer=RETRO_PRODUCER,
                    source_event_id=f"tool:{parent_tool_call_id}:issued",
                    correlation_id=parent_task_id,
                    payload={
                        "call_seq": 1,
                        "provider_call_id": "provider-task-call",
                        "tool_name": "task",
                        "args_hash": "c" * 64,
                        "args_preview": {},
                        "tool_schema_block_id": None,
                    },
                ),
            )
        )
        await service.flush_task(parent_task_id)

        child_task_id = new_id()
        service.record(
            ObservationEnvelope.task_lifecycle(
                kind="task.created",
                task_id=child_task_id,
                source_kind="deerflow_subagent",
                source_id="provider-task-call",
                occurred_at=observed_at,
                source_event_id="deerflow_subagent:provider-task-call:task:created",
                thread_id="thread-case-d",
                owner_id="operator-case-d",
                trigger_kind="subagent",
                attributes={
                    "parent_task_id": parent_task_id,
                    "spawning_step_id": parent_step_id,
                    "spawning_tool_call_id": parent_tool_call_id,
                    "subagent_name": "general-purpose",
                    "scope_inheritance_source": "parent_task",
                },
            )
        )
        await service.flush_task(child_task_id)

        child_step_id = new_id()
        child_attempt_id = new_id()
        service.record_batch(
            (
                ObservationEnvelope(
                    kind="step.started",
                    occurred_at=observed_at,
                    task_id=child_task_id,
                    step_id=child_step_id,
                    subject_type="step",
                    subject_id=child_step_id,
                    producer=RETRO_PRODUCER,
                    source_event_id=f"step:{child_step_id}:started",
                    correlation_id=child_task_id,
                    payload={"step_seq": 1, "actor_kind": "subagent"},
                ),
                ObservationEnvelope(
                    kind="llm.requested",
                    occurred_at=observed_at,
                    task_id=child_task_id,
                    step_id=child_step_id,
                    subject_type="llm_attempt",
                    subject_id=child_attempt_id,
                    producer=RETRO_PRODUCER,
                    source_event_id=f"attempt:{child_attempt_id}:requested",
                    correlation_id=child_task_id,
                    payload={"attempt_no": 1, "actor_kind": "subagent"},
                ),
                ObservationEnvelope(
                    kind="llm.responded",
                    occurred_at=observed_at,
                    task_id=child_task_id,
                    step_id=child_step_id,
                    subject_type="llm_attempt",
                    subject_id=child_attempt_id,
                    producer=RETRO_PRODUCER,
                    source_event_id=f"attempt:{child_attempt_id}:responded",
                    correlation_id=child_task_id,
                    payload={
                        "attempt_no": 1,
                        "provider_model": "child-model",
                        "usage": {"input_tokens": 4_400_000, "output_tokens": 4_500, "total_tokens": 4_404_500},
                    },
                ),
            )
        )
        await service.flush_task(child_task_id)
        await close_task(service, child_task_id, source_id="provider-task-call")
        await close_task(service, parent_task_id, source_id="run-case-d")

        local_usage = await service.get_task_usage(parent_task_id)
        breakdown = await service.get_task_usage_breakdown(parent_task_id, scope="inclusive")

    parent_local_total = _usage_value(local_usage.local, "total_tokens")
    parent_inclusive_total = _usage_value(local_usage.inclusive, "total_tokens")

    assert parent_local_total == 0, "lead 只发了一次 dispatch，local 不该包含子 Task 的消耗"
    assert parent_inclusive_total == 4_404_500, "inclusive 必须包含子 Task 的全部消耗"

    source_ids = {source.source_task_id for source in breakdown.sources}
    assert child_task_id in source_ids, "breakdown 必须能指出这些 token 来自哪个子 Task"
