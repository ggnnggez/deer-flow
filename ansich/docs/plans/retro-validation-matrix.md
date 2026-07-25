# Ansich 回溯验证矩阵 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用六个故障注入用例检验"Observation → Belief"这套建模是否真的能独立判定 DeerFlow 已发生过的六类错误，把"Ansich 有没有价值"从主观感受变成可证伪的结论。

**Architecture:** 不复现历史 bug（多数已在 main 修复，回退代价过高），而是注入**故障条件**——provider 返回 error fallback、消息 id 被就地覆盖、bash 无副作用 instrumentation、子 Task 烧光 token——然后只问一个问题：Ansich 的读模型是否足以独立得出与错误结论矛盾的判断。每个用例是一个 SQLite 端到端测试，走真实的 `create_sql_ansich_service` + 真实探针中间件，不 mock Ansich 内部。

**Tech Stack:** pytest + `@pytest.mark.anyio`、`sqlite+aiosqlite`、`Base.metadata.create_all`、`deerflow.ansich.create_sql_ansich_service`、`langchain.agents.create_agent` 配合 `AnsichDecisionMiddleware` / `AnsichAttemptMiddleware` / `AnsichRawToolMiddleware` / `AnsichVisibleToolMiddleware`。

## Global Constraints

- 测试目录 `backend/tests/ansich/`，命名 `test_retro_*.py`，遵循仓库既有 Ansich 测试写法。
- SQLite 连接必须 `PRAGMA foreign_keys=ON`（生产语义；typed 子投影的 FK 顺序缺陷只在开启时暴露）。
- 每个用例必须 `await service.flush_task(task_id)` 后再读，禁止 sleep 轮询。
- 断言只允许调用 `AnsichService` 的公开读方法，禁止直接查 `ansich_*` 表——测的是"读模型能不能回答"，不是"数据在不在库里"。
- 禁止为了让用例通过而新增 assessor 或投影器。缺能力就记为弱通过/失败，**不准边测边补**。
- 每个 Task 结束必须回填本文件底部的结果表并 commit，预注册才有意义。
- 后端格式化：`cd backend && make format`；测试：`cd backend && PYTHONPATH=. uv run pytest tests/ansich/<file> -v`。
- **共享 harness 必须放在 `backend/tests/support/` 并以 `from support.ansich_retro import ...` 引入**。`backend/tests/` 没有 `__init__.py`，pytest 把 `tests/` 本身放进 `sys.path`，所以 `tests.ansich.*` 不可导入（已实测 `ModuleNotFoundError`），而 `tests/support/` 是既有的带 `__init__.py` 的共享包，仓库现有测试就是用 `from support.detectors import ...` 这种写法。**不要**通过新建 `tests/ansich/__init__.py` 来绕过：那会让顶层包名变成 `ansich`，与框架无关的真实 `ansich` 包直接冲突。

---

## 预注册预测（跑任何测试之前必须先提交本节）

预注册是这份计划的全部价值来源。没有事前落盘的预测，任何结果都能被事后解释成"符合预期"。

| 用例 | 对应 issue | 压的模型能力 | **事前预测** |
|---|---|---|---|
| A | #3320 / #4041 | Step 决策结果、attempt 分层 | **强通过**（已验证 `_decision_result` 会写 `model_failed`） |
| B | #3684 | ContextSnapshot ordinal、内容身份 | **不确定**——这是全套里唯一可能暴露采集设计缺陷的 |
| C | #4176 | ToolEffect 三相与覆盖度 | **部分失败（预期内）**：bash 无 instrumentation 应记 `unknown` |
| D | #3875 | local / inclusive usage、source breakdown | **强通过** |
| E | #3113 | 冲突两存、终态矛盾保留 | **强通过** |
| F | #3645 | per-Task release、attempt 级 provider model | **弱通过**：证据在，但无 by-model 聚合接口 |

## 判定标准（三档）

| 判定 | 含义 | 结论 |
|---|---|---|
| **强通过** | 现有读模型直接给出与错误结论矛盾的判断，不加任何代码 | 设计成立 |
| **弱通过** | 事实齐全，但需要新查询/新 assessor 才能看出 | **缺 API，不缺证据**——可接受，记账 |
| **失败** | 证据本身不足，加多少查询也答不出 | **需要改采集设计**，唯一真正的坏消息 |

Task 2（用例 B）若判定为失败，应暂停 Task 4–6，先处理采集粒度问题——后续用例的价值会随之下降。

## File Structure

- `backend/tests/support/ansich_retro.py`（新建）：共享故障注入 harness。负责 SQLite 引擎 + FK pragma + service 生命周期、`task.created` / 终态观察的记录、以及三个故障模型桩。六个用例共用，避免第 6 次复制同一段引擎装配。
- `backend/tests/ansich/test_retro_terminal_judgment.py`（新建）：用例 A、E。共同关注"终态判断是否可被证据推翻"。
- `backend/tests/ansich/test_retro_context_lineage.py`（新建）：用例 B。上下文身份与顺序。
- `backend/tests/ansich/test_retro_effect_coverage.py`（新建）：用例 C。副作用覆盖度诚实性。
- `backend/tests/ansich/test_retro_attribution.py`（新建）：用例 D、F。共同关注"token 归属到哪个 Task / 哪个模型"。
- `ansich/docs/plans/retro-validation-matrix.md`（本文件）：Task 7 回填结果表。

---

### Task 1: 共享 harness + 用例 A（provider 失败被判成功）

信息量最低但成本也最低，用它打通"注入故障 → 读 Ansich → 断言"的脚手架。

**Files:**
- Create: `backend/tests/support/ansich_retro.py`
- Create: `backend/tests/ansich/test_retro_terminal_judgment.py`

**Interfaces:**
- Produces: `retro_service(tmp_path, name)` 异步上下文管理器，产出已 `start()` 的 `AnsichService`；`open_task(service, source_id, *, source_kind="deerflow_run", occurred_at=None) -> str`；`close_task(service, task_id, *, source_id, kind="task.completed", occurred_at=None) -> None`；`ErrorFallbackModel`、`PlainAnswerModel` 两个 `BaseChatModel` 桩；常量 `RETRO_PRODUCER`。Task 2–6 全部依赖这些名字。

- [ ] **Step 1: 写 harness**

创建 `backend/tests/support/ansich_retro.py`：

```python
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from ansich import AnsichService, ObservationEnvelope, Producer, new_id
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from deerflow.ansich import create_sql_ansich_service
from deerflow.persistence.base import Base

RETRO_PRODUCER = Producer(name="ansich-retro", version="1", instance_id="retro-test")


@asynccontextmanager
async def retro_service(tmp_path, name: str) -> AsyncIterator[AnsichService]:
    """Start a SQLite-backed Ansich service with production foreign-key semantics."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / f'{name}.db'}")

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(session_factory)
    await service.start()
    try:
        yield service
    finally:
        await service.stop()
        await engine.dispose()


async def open_task(
    service: AnsichService,
    source_id: str,
    *,
    source_kind: str = "deerflow_run",
    occurred_at: datetime | None = None,
) -> str:
    """Record task.created exactly as run admission does, then settle projections."""
    task_id = new_id()
    service.record(
        ObservationEnvelope.task_lifecycle(
            kind="task.created",
            task_id=task_id,
            source_kind=source_kind,
            source_id=source_id,
            occurred_at=occurred_at or datetime.now(UTC),
            source_event_id=f"{source_kind}:{source_id}:task:created",
            producer_seq=1,
        )
    )
    await service.flush_task(task_id)
    return task_id


async def close_task(
    service: AnsichService,
    task_id: str,
    *,
    source_id: str,
    kind: str = "task.completed",
    occurred_at: datetime | None = None,
) -> None:
    """Record the terminal signal the run worker emits, then settle projections."""
    service.record(
        ObservationEnvelope.task_lifecycle(
            kind=kind,
            task_id=task_id,
            source_kind="deerflow_run",
            source_id=source_id,
            occurred_at=occurred_at or datetime.now(UTC),
            source_event_id=f"deerflow_run:{source_id}:task:{kind}",
            producer_seq=2,
        )
    )
    await service.flush_task(task_id)


class ErrorFallbackModel(BaseChatModel):
    """Reproduce what LLMErrorHandlingMiddleware emits after retry exhaustion (#3320/#4041)."""

    @property
    def _llm_type(self) -> str:
        return "ansich-retro-error-fallback"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(
            generations=[
                ChatGeneration(
                    message=AIMessage(
                        content="LLM request failed: Error code: 400 - provider unavailable",
                        additional_kwargs={"deerflow_error_fallback": True},
                        response_metadata={"finish_reason": "stop", "model_name": "retro-failing-model"},
                    )
                )
            ]
        )

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


class PlainAnswerModel(BaseChatModel):
    """A normal successful final answer, used as the control arm."""

    def __init__(self, provider_model: str = "retro-model", **kwargs):
        super().__init__(**kwargs)
        self._provider_model = provider_model

    @property
    def _llm_type(self) -> str:
        return "ansich-retro-plain"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(
            generations=[
                ChatGeneration(
                    message=AIMessage(
                        content="done",
                        usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                        response_metadata={"finish_reason": "stop", "model_name": self._provider_model},
                    )
                )
            ]
        )

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
```

只提供这两个模型桩。#4027（空终态 AIMessage）与用例 A 属于同一失败族（"图正常结束 ≠ 成功"），本轮六条不单独覆盖；等用例 A 判定出来后再决定是否值得加第七条。不要预先写一个没有用例引用的模型桩。

- [ ] **Step 2: 写用例 A 的失败测试**

创建 `backend/tests/ansich/test_retro_terminal_judgment.py`：

```python
import pytest
from langchain.agents import create_agent
from langchain_core.messages import HumanMessage

from deerflow.ansich.execution import ANSICH_EXECUTION_CONTEXT_KEY, AnsichExecutionContext
from deerflow.ansich.middleware import AnsichAttemptMiddleware, AnsichDecisionMiddleware

from support.ansich_retro import ErrorFallbackModel, close_task, open_task, retro_service


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
```

- [ ] **Step 3: 跑测试确认失败**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/ansich/test_retro_terminal_judgment.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'support.ansich_retro'`（Step 1 尚未创建文件时）或 import 错误。若 Step 1 已完成则直接进入 Step 4。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/ansich/test_retro_terminal_judgment.py -v`
Expected: PASS

若 `steps[0].result` 不是 `model_failed`，**不要修改 Ansich 让它通过**。按判定标准记为失败或弱通过，把实际值写进结果表。

- [ ] **Step 5: 回填结果表并提交**

在本文件底部结果表的用例 A 行填入实际判定与实际观测值，然后：

```bash
cd /home/nan/c_project/deer-flow
git add backend/tests/support/ansich_retro.py backend/tests/ansich/test_retro_terminal_judgment.py ansich/docs/plans/retro-validation-matrix.md
git commit -m "test(ansich): retro case A — provider failure vs successful task control"
```

---

### Task 2: 用例 B（上下文身份与顺序）

**信息量最高的一条。** 我事前无法预测结果，这正是它的价值。若判定失败，暂停 Task 4–6。

**Files:**
- Create: `backend/tests/ansich/test_retro_context_lineage.py`

**Interfaces:**
- Consumes: `retro_service`、`open_task`、`close_task`、`PlainAnswerModel`（Task 1）

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/ansich/test_retro_context_lineage.py`：

```python
import pytest
from langchain.agents import create_agent
from langchain_core.messages import HumanMessage

from deerflow.ansich.execution import ANSICH_EXECUTION_CONTEXT_KEY, AnsichExecutionContext
from deerflow.ansich.middleware import AnsichAttemptMiddleware, AnsichDecisionMiddleware

from support.ansich_retro import PlainAnswerModel, close_task, open_task, retro_service


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
```

- [ ] **Step 2: 跑测试，如实记录结果**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/ansich/test_retro_context_lineage.py -v`

三种可能，全部是有效结果：

- 全部断言通过 → **强通过**：内容身份基于 hash 而非 message id，#3684 那类就地覆盖在快照层可见。
- `content_hash` 不同但 `block_id` 相同（或反之）→ **弱通过**：证据在但身份模型有歧义，记账。
- 两者都相同 → **失败**：Ansich 会把覆盖后的消息与原消息折叠成同一 occurrence，采集粒度不足以支持 #3684 的定位。**记录后停止 Task 4–6，先处理这个问题。**

- [ ] **Step 3: 若断言与实际不符，改断言而非改实现**

把 `assert` 改成反映**实际观测到的行为**，并在测试 docstring 里写明这是"记录当前行为"而非"期望行为"，例如：

```python
    # OBSERVED (retro validation, case B): Ansich collapses same-id occurrences.
    # This is a recorded limitation, not a desired property. See结果表 case B.
    assert first_human.block_id == second_human.block_id
```

这样测试仍能锁住当前行为，未来若修复会红灯提醒。

- [ ] **Step 4: 回填结果表并提交**

```bash
cd /home/nan/c_project/deer-flow
git add backend/tests/ansich/test_retro_context_lineage.py ansich/docs/plans/retro-validation-matrix.md
git commit -m "test(ansich): retro case B — reused message id content identity"
```

---

### Task 3: 用例 C（副作用覆盖度诚实性）

这条负责提供失败。测的是"文档写的限制是否真的按文档行为"——bash 无 instrumentation 时必须记 `unknown`，绝不能显示"无副作用"。

**Files:**
- Create: `backend/tests/ansich/test_retro_effect_coverage.py`

**Interfaces:**
- Consumes: `retro_service`、`open_task`、`close_task`、`RETRO_PRODUCER`（Task 1）

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/ansich/test_retro_effect_coverage.py`：

```python
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
```

- [ ] **Step 2: 跑测试**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/ansich/test_retro_effect_coverage.py -v`

判定：

- `coverage == "unknown"` 且 `effects == ()` → **强通过**：已知限制按文档诚实呈现。
- `effects is None` → **弱通过**：视图缺失，前端需要额外分支才能区分"没查到"和"没证据"。
- `coverage == "complete"` → **失败且是真 bug**：会让运维读成"这次 bash 没有副作用"。立刻记录并提 issue。

- [ ] **Step 3: 回填结果表并提交**

```bash
cd /home/nan/c_project/deer-flow
git add backend/tests/ansich/test_retro_effect_coverage.py ansich/docs/plans/retro-validation-matrix.md
git commit -m "test(ansich): retro case C — bash effect coverage honesty"
```

---

### Task 4: 用例 D（inclusive usage 归属）

**Files:**
- Create: `backend/tests/ansich/test_retro_attribution.py`

**Interfaces:**
- Consumes: `retro_service`、`open_task`、`close_task`、`RETRO_PRODUCER`（Task 1）
- Produces: 本文件 Task 6 会追加用例 F 的测试函数

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/ansich/test_retro_attribution.py`：

```python
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
```

- [ ] **Step 2: 跑测试**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/ansich/test_retro_attribution.py::test_case_d_child_token_burn_is_attributable_to_its_source_task -v`
Expected: PASS

若 `get_task_usage_breakdown` 的 `scope` 参数名或返回结构与断言不符，先读 `backend/packages/ansich/ansich/service.py` 的实际签名再改断言，**不要改 service**。

- [ ] **Step 3: 回填结果表并提交**

```bash
cd /home/nan/c_project/deer-flow
git add backend/tests/ansich/test_retro_attribution.py ansich/docs/plans/retro-validation-matrix.md
git commit -m "test(ansich): retro case D — inclusive usage attribution to child task"
```

---

### Task 5: 用例 E（终态冲突两存）

唯一能证明"可变 status 字段做不到"的用例：两个相反的终态同时保留。

**Files:**
- Modify: `backend/tests/ansich/test_retro_terminal_judgment.py`（追加测试函数）

**Interfaces:**
- Consumes: `retro_service`、`open_task`、`close_task`、`RETRO_PRODUCER`（Task 1）

- [ ] **Step 1: 追加失败测试**

先把该文件顶部的 import 替换为下面这一组（新增 `datetime`、`ObservationEnvelope`、`new_id`、`RETRO_PRODUCER`）：

```python
from datetime import UTC, datetime

import pytest
from ansich import ObservationEnvelope, new_id
from langchain.agents import create_agent
from langchain_core.messages import HumanMessage

from deerflow.ansich.execution import ANSICH_EXECUTION_CONTEXT_KEY, AnsichExecutionContext
from deerflow.ansich.middleware import AnsichAttemptMiddleware, AnsichDecisionMiddleware

from support.ansich_retro import (
    RETRO_PRODUCER,
    ErrorFallbackModel,
    close_task,
    open_task,
    retro_service,
)
```

然后在文件末尾追加：

```python
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
                    payload={"error_type": "TypeError", "error_message": "'AsyncCallbackManager' object is not iterable"},
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
```

- [ ] **Step 2: 跑测试**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/ansich/test_retro_terminal_judgment.py -v`
Expected: 两个测试全部 PASS

若 `tool.failed` 的 payload 字段名与 `contracts.py` 的 subject contract 不符，会在 `record_batch` 时被拒（返回 `accepted=False`）而不是抛异常——此时 `get_tool_call` 会返回 `execution.value == "unknown"`。遇到这种情况先读 `backend/packages/ansich/ansich/contracts.py` 里 `ToolObservationKind` 的校验分支，修正 payload 而非修正 contracts。

- [ ] **Step 3: 回填结果表并提交**

```bash
cd /home/nan/c_project/deer-flow
git add backend/tests/ansich/test_retro_terminal_judgment.py ansich/docs/plans/retro-validation-matrix.md
git commit -m "test(ansich): retro case E — conflicting terminal states both retained"
```

---

### Task 6: 用例 F（by-model 归属）

预期弱通过：证据在，但 39 个端点里没有 by-model 聚合接口。这条负责精确暴露"证据够、查询缺"的差距。

**Files:**
- Modify: `backend/tests/ansich/test_retro_attribution.py`（追加测试函数）

**Interfaces:**
- Consumes: `retro_service`、`open_task`、`close_task`、`PlainAnswerModel`（Task 1）

- [ ] **Step 1: 追加失败测试**

先把该文件顶部的 import 替换为下面这一组（新增 `create_agent`、`HumanMessage`、执行上下文、两个中间件、`PlainAnswerModel`）：

```python
from datetime import UTC, datetime

import pytest
from ansich import ObservationEnvelope, new_id
from langchain.agents import create_agent
from langchain_core.messages import HumanMessage

from deerflow.ansich.execution import ANSICH_EXECUTION_CONTEXT_KEY, AnsichExecutionContext
from deerflow.ansich.middleware import AnsichAttemptMiddleware, AnsichDecisionMiddleware

from support.ansich_retro import (
    RETRO_PRODUCER,
    PlainAnswerModel,
    close_task,
    open_task,
    retro_service,
)
```

然后在文件末尾追加：

```python
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
```

- [ ] **Step 2: 跑测试**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/ansich/test_retro_attribution.py -v`
Expected: 两个测试全部 PASS

- [ ] **Step 3: 记录缺失的聚合能力**

用例 F 的判定必然是**弱通过**，除非发现了 by-model 聚合端点。执行以下命令确认结论，把输出写进结果表备注：

```bash
cd /home/nan/c_project/deer-flow/backend/app/gateway/routers
grep -c "@router\." ansich.py
grep -n "by_model\|by-model\|group_by_model" ansich.py || echo "NO by-model aggregation endpoint"
```

- [ ] **Step 4: 回填结果表并提交**

```bash
cd /home/nan/c_project/deer-flow
git add backend/tests/ansich/test_retro_attribution.py ansich/docs/plans/retro-validation-matrix.md
git commit -m "test(ansich): retro case F — per-attempt provider model identity"
```

---

### Task 7: 汇总结论

**Files:**
- Modify: `ansich/docs/plans/retro-validation-matrix.md`（本文件，结果表 + 结论节）
- Modify: `ansich/docs/plans/README.md`（在状态列表追加一行指向本文件）

- [ ] **Step 1: 跑全部六个用例**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/ansich/test_retro_*.py -v`
记录：通过数、失败数、每条的实际判定。

- [ ] **Step 2: 格式化并跑完整 Ansich 回归，确认没有污染既有测试**

```bash
cd /home/nan/c_project/deer-flow/backend
make format
PYTHONPATH=. uv run pytest tests/ansich/ -q
```
Expected: 全绿（除被记录为"失败"判定的用例外）

- [ ] **Step 3: 回填结果表并写结论**

补完本文件的结果表，然后在"结论"节写三段，每段不超过三句：

1. **预测命中率**：六条里事前预测与实际相符的有几条。低命中率本身是重要发现——说明对自己的设计理解不准。
2. **失败项的处置**：每个"失败"判定对应的采集设计问题，以及归属到哪个 Phase。
3. **弱通过项的账**：缺哪些查询/聚合能力，是否值得补，归属到哪。

- [ ] **Step 4: 在 plans/README.md 登记**

在 `ansich/docs/plans/README.md` 的"当前实施状态"列表末尾追加一行：

```markdown
- 回溯验证矩阵（六个故障注入用例，检验 Observation→Belief 是否足以独立判定已发生过的六类错误）登记在 [retro-validation-matrix.md](retro-validation-matrix.md)；预测与判定在跑测试前已预注册，结果表记录实际判定与差异。
```

- [ ] **Step 5: 提交**

```bash
cd /home/nan/c_project/deer-flow
git add ansich/docs/plans/retro-validation-matrix.md ansich/docs/plans/README.md
git commit -m "docs(ansich): record retro validation matrix results and conclusions"
```

---

## 结果表（Task 1–6 逐条回填，Task 7 汇总）

| 用例 | issue | 事前预测 | 实际判定 | 实际观测值 / 备注 |
|---|---|---|---|---|
| A | #3320 / #4041 | 强通过 | **强通过** ✅ 命中 | `task.control.value == "completed"`（DeerFlow 的错误裁决）与 `StepView.status == result == "model_failed"`（Ansich 的独立判断）同时可读，构成矛盾证据。无需新增任何代码。 |
| B | #3684 | 不确定 | **强通过** ✅ | 已实测确实发生 id 复用（两次快照 `message_id` 均为 `reused-human-id`）。`source_identity` 相同（`message:reused-human-id:occurrence:1:content:0`），但 `content_hash` 与 `block_id` 均不同——即内容身份基于 hash 而非 message id，覆盖没有被折叠。**副产品**：#3684 的异常特征可被精确表达为"同 `source_identity`、不同 `content_hash`"，这是一个现成的检出条件。 |
| C | #4176 | 部分失败（预期内） | _待填_ | _待填_ |
| D | #3875 | 强通过 | _待填_ | _待填_ |
| E | #3113 | 强通过 | _待填_ | _待填_ |
| F | #3645 | 弱通过 | _待填_ | _待填_ |

## 结论

_Task 7 填写。_

## 附带产出

这六个用例同时是 Ansich 的第一个**非 UI 消费者**。fail-open 约束决定了执行路径永远不能读 Ansich，因此测试与离线分析是它仅有的合法依赖方。矩阵跑完即意味着 Ansich 从"只有人在看的镜子"变成"有东西依赖它"，这正是此前一直缺席的 named consumer。
