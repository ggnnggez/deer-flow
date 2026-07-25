"""Retro validation matrix — context identity and ordering.

Case B (#3684): a memory-injection bug overwrote a message in place, so the
model re-answered the previous turn. The question this case asks is whether
Ansich's ContextSnapshot keeps a reused message id with different content
distinguishable, or silently collapses it into one occurrence.

Pre-registered prediction: UNKNOWN. See ansich/docs/plans/retro-validation-matrix.md.
"""

import pytest
from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from support.ansich_retro import PlainAnswerModel, close_task, open_task, retro_service

from deerflow.ansich.execution import ANSICH_EXECUTION_CONTEXT_KEY, AnsichExecutionContext
from deerflow.ansich.middleware import AnsichAttemptMiddleware, AnsichDecisionMiddleware


@pytest.mark.anyio
async def test_case_b_reused_message_id_with_new_content_stays_distinguishable(tmp_path):
    """#3684: a message id reused with different content must not collapse into one occurrence."""
    async with retro_service(tmp_path, "retro-case-b") as service:
        task_id = await open_task(service, "run-case-b")
        execution = AnsichExecutionContext(task_id=task_id, service=service)
        agent = create_agent(
            model=PlainAnswerModel(),
            tools=[],
            middleware=[AnsichDecisionMiddleware(), AnsichAttemptMiddleware()],
        )

        # Turn 1 and turn 2 carry the SAME message id with DIFFERENT content —
        # the in-place overwrite shape reported in #3684.
        await agent.ainvoke(
            {"messages": [HumanMessage(id="reused-human-id", content="test")]},
            context={ANSICH_EXECUTION_CONTEXT_KEY: execution},
        )
        await agent.ainvoke(
            {"messages": [HumanMessage(id="reused-human-id", content="weather in berlin next week")]},
            context={ANSICH_EXECUTION_CONTEXT_KEY: execution},
        )
        await close_task(service, task_id, source_id="run-case-b")

        steps = await service.list_steps(task_id)
        first_context = await service.get_step_context(steps[0].step_id)
        second_context = await service.get_step_context(steps[1].step_id)

    assert len(steps) == 2, "两次模型调用必须产生两个 Step"
    assert first_context is not None and second_context is not None

    first_human = next(item for item in first_context.items if item.kind == "user_input")
    second_human = next(item for item in second_context.items if item.kind == "user_input")

    # 核心断言：内容不同就必须是不同的 ContentBlock，不能因 message id 相同而被折叠。
    assert first_human.content_hash != second_human.content_hash, "内容不同却共享 content_hash — 覆盖被隐藏"
    assert first_human.block_id != second_human.block_id, "内容不同却共享 block_id — 覆盖被隐藏"
    # 顺序语义必须保留在各自快照内。
    assert first_human.ordinal == second_human.ordinal

    # id 复用确实发生了 —— 否则本用例没测到 #3684 的形状。
    assert first_human.message_id == second_human.message_id == "reused-human-id"

    # 观察到的语义：同一个 occurrence 槽位（source_identity 相同）在两次请求中承载了不同内容。
    # 这正是 #3684 的异常特征，且可通过"同 source_identity、不同 content_hash"精确检出。
    assert first_human.source_identity == second_human.source_identity
