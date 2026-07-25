"""Retro validation matrix — terminal judgment cases.

Case A (#3320/#4041): a provider failure that DeerFlow records as a successful run.
Case E (#3113): a subagent that completes while the parent task tool fails.

See ansich/docs/plans/retro-validation-matrix.md for the pre-registered
predictions and the three-tier pass criteria.
"""

import pytest
from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from support.ansich_retro import ErrorFallbackModel, close_task, open_task, retro_service

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
