"""Retro validation matrix — terminal judgment cases.

Case A (#3320/#4041): a provider failure that DeerFlow records as a successful run.
Case E (#3113): a subagent that completes while the parent task tool fails.

See ansich/docs/plans/retro-validation-matrix.md for the pre-registered
predictions and the three-tier pass criteria.
"""

from datetime import UTC, datetime

import pytest
from ansich import ObservationEnvelope, new_id
from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from support.ansich_retro import RETRO_PRODUCER, ErrorFallbackModel, close_task, open_task, retro_service

from deerflow.ansich.execution import ANSICH_EXECUTION_CONTEXT_KEY, AnsichExecutionContext
from deerflow.ansich.middleware import AnsichAttemptMiddleware, AnsichDecisionMiddleware


@pytest.mark.anyio
async def test_case_a_provider_failure_contradicts_successful_task_control(tmp_path):
    """#3320/#4041: DeerFlow records success; Ansich must still show the model failed."""
    async with retro_service(tmp_path, "retro-case-a") as service:
        task_id = await open_task(service, "run-case-a")
        execution = AnsichExecutionContext(task_id=task_id, service=service)
        agent = create_agent(
            model=ErrorFallbackModel(),
            tools=[],
            middleware=[AnsichDecisionMiddleware(), AnsichAttemptMiddleware()],
        )

        await agent.ainvoke(
            {"messages": [HumanMessage(content="produce the report")]},
            context={ANSICH_EXECUTION_CONTEXT_KEY: execution},
        )
        # The run worker maps a cleanly-terminating graph to success — the #3320 bug.
        await close_task(service, task_id, source_id="run-case-a", kind="task.completed")

        task = await service.get_task(task_id)
        steps = await service.list_steps(task_id)

    assert task is not None
    assert task.control.value == "completed", "DeerFlow 的错误裁决必须被如实记录"
    assert len(steps) == 1
    assert steps[0].result == "model_failed", "Ansich 必须独立记录模型失败，构成矛盾证据"
    assert steps[0].status == "model_failed"


@pytest.mark.anyio
async def test_case_e_child_success_and_parent_tool_failure_both_survive(tmp_path):
    """#3113: subagent completes internally while the parent task tool fails. Keep both."""
    async with retro_service(tmp_path, "retro-case-e") as service:
        parent_task_id = await open_task(service, "run-case-e")
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
                        "provider_call_id": "provider-task-call-e",
                        "tool_name": "task",
                        "args_hash": "d" * 64,
                        "args_preview": {},
                        "tool_schema_block_id": None,
                    },
                ),
                # The parent-visible tool wrapper raised (TypeError in #3113).
                ObservationEnvelope(
                    kind="tool.failed",
                    occurred_at=observed_at,
                    task_id=parent_task_id,
                    step_id=parent_step_id,
                    subject_type="tool_call",
                    subject_id=parent_tool_call_id,
                    producer=RETRO_PRODUCER,
                    source_event_id=f"tool:{parent_tool_call_id}:failed",
                    correlation_id=parent_task_id,
                    payload={
                        "error_type": "TypeError",
                        "error_message": "'AsyncCallbackManager' object is not iterable",
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
                source_id="provider-task-call-e",
                occurred_at=observed_at,
                source_event_id="deerflow_subagent:provider-task-call-e:task:created",
                thread_id="thread-case-e",
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
        # The subagent finished its own work successfully.
        await close_task(service, child_task_id, source_id="provider-task-call-e", kind="task.completed")
        await close_task(service, parent_task_id, source_id="run-case-e")

        child_task = await service.get_task(child_task_id)
        parent_tool_call = await service.get_tool_call(parent_tool_call_id)

    assert child_task is not None and parent_tool_call is not None
    # 两个相反的终态同时可读 —— 单一可变 status 字段做不到这件事。
    assert child_task.control.value == "completed", "子 Task 内部确实完成了"
    assert parent_tool_call.execution.value == "failed", "父侧 ToolCall 确实失败了"
    assert parent_tool_call.execution.evidence_obs_ids, "失败判断必须带证据指针"
