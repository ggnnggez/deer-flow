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
from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from support.ansich_retro import RETRO_PRODUCER, PlainAnswerModel, close_task, open_task, retro_service

from deerflow.ansich.execution import ANSICH_EXECUTION_CONTEXT_KEY, AnsichExecutionContext
from deerflow.ansich.middleware import AnsichAttemptMiddleware, AnsichDecisionMiddleware


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


@pytest.mark.anyio
async def test_case_f_provider_model_is_recorded_per_attempt_not_per_run(tmp_path):
    """#3645: token attribution needs the provider model per attempt, not one run-level column."""
    async with retro_service(tmp_path, "retro-case-f") as service:
        lead_task_id = await open_task(service, "run-case-f-lead")
        lead_execution = AnsichExecutionContext(task_id=lead_task_id, service=service)
        lead_agent = create_agent(
            model=PlainAnswerModel(provider_model="lead-provider-model"),
            tools=[],
            middleware=[AnsichDecisionMiddleware(), AnsichAttemptMiddleware()],
        )
        await lead_agent.ainvoke(
            {"messages": [HumanMessage(content="lead turn")]},
            context={ANSICH_EXECUTION_CONTEXT_KEY: lead_execution},
        )
        await close_task(service, lead_task_id, source_id="run-case-f-lead")

        sub_task_id = await open_task(service, "run-case-f-sub")
        sub_execution = AnsichExecutionContext(task_id=sub_task_id, service=service)
        sub_agent = create_agent(
            model=PlainAnswerModel(provider_model="sub-provider-model"),
            tools=[],
            middleware=[AnsichDecisionMiddleware(), AnsichAttemptMiddleware()],
        )
        await sub_agent.ainvoke(
            {"messages": [HumanMessage(content="sub turn")]},
            context={ANSICH_EXECUTION_CONTEXT_KEY: sub_execution},
        )
        await close_task(service, sub_task_id, source_id="run-case-f-sub")

        lead_steps = await service.list_steps(lead_task_id)
        sub_steps = await service.list_steps(sub_task_id)

    lead_models = {attempt.provider_model for step in lead_steps for attempt in step.attempts}
    sub_models = {attempt.provider_model for step in sub_steps for attempt in step.attempts}

    # 证据层：每个 attempt 各自带 provider model，不共享一个 run 级列。
    assert lead_models == {"lead-provider-model"}
    assert sub_models == {"sub-provider-model"}
    assert lead_models.isdisjoint(sub_models), "两个 Task 的模型身份必须可区分"
