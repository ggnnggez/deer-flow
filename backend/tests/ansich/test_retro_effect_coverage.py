"""Retro validation matrix — effect coverage honesty.

Case C (#4176): a run burned 50 bash calls and produced no output file, yet
finished as success. Ansich cannot know what bash did — there is no effect
instrumentation for it. This case checks that the documented limitation is
honoured: coverage must read `unknown`, never a claim of "no side effects".

Pre-registered prediction: PARTIAL FAILURE (expected).
See ansich/docs/plans/retro-validation-matrix.md.
"""

from datetime import UTC, datetime

import pytest
from ansich import ObservationEnvelope, new_id
from support.ansich_retro import RETRO_PRODUCER, close_task, open_task, retro_service


@pytest.mark.anyio
async def test_case_c_bash_without_instrumentation_reports_unknown_coverage(tmp_path):
    """#4176: a bash call with no effect evidence must report unknown, never 'no side effects'."""
    async with retro_service(tmp_path, "retro-case-c") as service:
        task_id = await open_task(service, "run-case-c")
        step_id = new_id()
        tool_call_id = new_id()
        observed_at = datetime.now(UTC)

        service.record_batch(
            (
                ObservationEnvelope(
                    kind="step.started",
                    occurred_at=observed_at,
                    task_id=task_id,
                    step_id=step_id,
                    subject_type="step",
                    subject_id=step_id,
                    producer=RETRO_PRODUCER,
                    source_event_id=f"step:{step_id}:started",
                    correlation_id=task_id,
                    payload={"step_seq": 1, "actor_kind": "lead_agent"},
                ),
                ObservationEnvelope(
                    kind="tool.issued",
                    occurred_at=observed_at,
                    task_id=task_id,
                    step_id=step_id,
                    subject_type="tool_call",
                    subject_id=tool_call_id,
                    producer=RETRO_PRODUCER,
                    source_event_id=f"tool:{tool_call_id}:issued",
                    correlation_id=task_id,
                    payload={
                        "call_seq": 1,
                        "provider_call_id": "provider-bash-call",
                        "tool_name": "bash",
                        "args_hash": "b" * 64,
                        "args_preview": {},
                        "tool_schema_block_id": None,
                    },
                ),
            )
        )
        await service.flush_task(task_id)
        await close_task(service, task_id, source_id="run-case-c")

        effects = await service.get_tool_effects(tool_call_id)

    # 没有任何 effect 观察 —— Ansich 必须诚实地说 unknown，而不是空列表配 complete。
    assert effects is not None, "ToolCall 存在就必须有 effects 视图，哪怕是空的"
    assert effects.coverage == "unknown", f"覆盖度必须是 unknown，实际是 {effects.coverage}"
    assert effects.effects == (), "没有证据就不能凭空产出 effect"
