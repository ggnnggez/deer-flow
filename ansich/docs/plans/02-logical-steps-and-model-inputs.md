# Phase 2 — 逻辑 Step 与实际模型输入

## 1. 交付目标

本阶段把一条 Task 展开为“逻辑 Agent 决策”和“物理模型调用尝试”。开发者能够确认：一次决策属于第几个 Step、同一个 Step 是否发生重试、哪个 attempt 最终生效、模型适配器实际收到哪些有序消息/Tool schema/响应格式/生成参数。

核心语义必须通过实现保证：一个 Step 是一次逻辑 Agent 决策及其产生的全部并行 ToolCall；模型重试只增加 attempt，不增加 Step；title、summarization、memory extraction、goal evaluation 等内部 LLM 调用是 system operation，不计入 Agent Step。

## 2. 前置条件与非目标

依赖 Phase 1 的 Collector、Observation store、projection job、Task ID 和管理员 API。本阶段只建立 ToolCall 的 issued 占位信息，Tool 的执行责任链在 Phase 3 完成；完整压缩谱系在 Phase 4 完成。

实施前提（已满足，2026-07-17，commit `66b426ed`）：[Phase 1 评审跟进项 F4](phase-1-review-followups.md) 已修复——projection job 按 `_PROJECTORS` 注册顺序认领，新增 Step projector 时把它追加到注册表即可获得确定的 structural → control → step 执行顺序。

“实际模型输入”的边界是 LangChain model adapter 接收的最终结构化 request，而不是 provider HTTP wire。provider SDK 内部不可见的网络 retry 不伪装成独立 attempt；若 provider 响应暴露 retry metadata，则作为该 attempt 的属性记录。

## 3. 新增领域类型和运行上下文

在独立 `ansich` 包新增：

```text
contracts/step.py
contracts/model_attempt.py
contracts/content.py
contracts/context_snapshot.py
serialization/messages.py
serialization/tool_schema.py
```

在 DeerFlow adapter 增加 `AnsichExecutionContext`：

```text
task_id
actor_kind              // lead_agent | subagent | system_operation
operation_kind?         // title | summarization | memory | goal | other
next_step_seq
current_step_id?
current_attempt_no?
collector
provenance_registry
```

该对象通过 LangGraph runtime context 显式传递；同步执行路径用 `contextvars.copy_context()` 传播，不能用模块级“当前 Step”全局变量。Task admission 时一次性从持久化投影读取已有最大 `step_seq`，恢复后从 `max + 1` 继续；正常热路径的 Step 分配不访问数据库。

所有 Agent/内部 LLM 构造点必须显式打 `ansich_call_class`，不能通过 model name、prompt 文本或调用栈猜测。至少修改 lead agent factory、subagent executor、summarization middleware、title middleware、memory 调用和 `runtime/goal.py` 的 evaluator 构造点。未知调用分类为 `system_operation/other`，宁可不计 Step，也不能污染 Agent Step 数。

## 4. 双层模型探针

实现两个职责分离的探针：

1. `AnsichDecisionProbe` 位于逻辑 retry 外层。第一次进入 lead/subagent Agent 模型决策时分配 `step_id` 和单调 `step_seq`，发出 `step.started`；收到最终 AIMessage 或不可恢复失败时发出 `step.closed`。
2. `AnsichAttemptProbe` 位于所有 request-transform middleware 之后、model adapter 之前。每次真正调用 adapter 时递增 `attempt_no`，捕获最终 request，发出 `llm.requested`，随后发出 `llm.responded` 或 `llm.failed`。

由于 LangChain middleware 的 wrap 顺序是实现风险，编码前先写 characterization test：安装三个带序号的 fake middleware 和 fake model，固定 sync/async、成功/retry/异常时的进入退出顺序。实际插入点必须以该测试结果为准，不在计划中凭名称猜测 first/last 的包裹方向。

如果 middleware 无法保证“最靠近 adapter”的边界，则使用 `ObservedChatModel` 代理包装最终 `BaseChatModel`；代理只序列化 adapter 参数并调用原模型，不改变 bind、stream、batch、structured-output 能力。必须用 contract tests 覆盖 DeerFlow 已支持的主要 provider wrapper，证明代理不丢 Tool binding 和 streaming chunk。

`step.closed` 的输出分类：

- AIMessage 有 ToolCalls：Step 进入 `acting`，本阶段只投影 issued 数量；Phase 3 接管后续状态。
- AIMessage 无 ToolCalls：Step 从 `deciding` 直接 `closed`。
- 所有 attempt 失败：Step `closed`，结果原因 `model_failed`；Task 是否失败仍由 Run worker 决定。

## 5. ContextSnapshot 捕获格式

每个 `llm.requested` 同时创建一个 ContextSnapshot。序列化器必须保留：

- message 的严格顺序、role、name、message ID、每个 content part 的原顺序；
- text、image/attachment reference、tool request、tool result 等结构化内容；
- 本次实际 visible Tool 的 name、description、JSON argument schema 和 deferred/source metadata；
- response format/structured output schema；
- temperature、top_p、max_tokens、stop、reasoning 等实际影响行为且 adapter 可见的生成参数；
- adapter class、package/version、configured model name；
- 每个 item 的 visible bytes 和 token estimate，并标注 estimator name/version。

序列化必须是纯函数，不能调用 provider、读取环境变量或执行任意对象的自定义 repr。无法安全序列化的字段写 `{type, status:"unsupported"}`，同时记录 fidelity/serialization warning；不允许用可能包含内存地址或 secret 的 `repr(model)`。

每个消息 occurrence 产生/引用 ContentBlock。相同文本在两个位置出现时使用不同 `block_id`；`content_hash=sha256(canonical visible bytes)` 只用于比较。无法确定来源时，保存完整 visible 内容并标记 `kind=unknown`，不能丢掉该 snapshot item。

## 6. Secret 排除与 payload 分层

在 snapshot 序列化前执行结构化字段排除：authorization/cookie/header、API key、DSN、credential、runtime secret context；同时从 `deerflow.runtime.secret_context` 获取本次请求已知 secret value，进行 exact-value redaction。redaction manifest 只记录 JSON path、reason、replacement marker，不记录原值。

小内容按 Phase 1 阈值内联到 Observation；大消息、schema 或多模态内容写 `ansich_payloads`，Observation 中只保留 payload ref、SHA-256、byte size、content type。图片不复制 provider credential-bearing URL；只保存允许的 artifact ID、MIME、尺寸和受控 payload/reference。

raw payload 默认不随 Step API 返回，必须经单独的 raw endpoint 和 Phase 11 的读审计。

## 7. 数据库增量

新增迁移 `ansich_steps_and_context`，创建：

- `ansich_steps(entity_id PK/FK, task_id, step_seq, actor_kind, started_obs_id, closed_obs_id, effective_attempt_no, effective_context_snapshot_id)`；唯一 `(task_id, step_seq)`。
- `ansich_llm_attempts(attempt_id, step_id nullable, task_id, operation_kind nullable, attempt_no, request_obs_id, response_obs_id, failure_obs_id, provider_model, usage_json, latency_ms)`；Agent attempt 唯一 `(step_id, attempt_no)`，system operation 使用 `(task_id, operation_id, attempt_no)`。
- `ansich_content_blocks(entity_id, kind, content_hash, payload_obs_id, producer_obs_id, byte_size, token_estimate, sensitivity_flags)`。
- `ansich_context_windows(entity_id, task_id unique, capacity_tokens, estimator_name, estimator_version)`。
- `ansich_context_snapshots(entity_id, task_id, step_id nullable, operation_id nullable, attempt_no, request_obs_id, message_count, tool_schema_count, visible_bytes, estimated_tokens, adapter_name, adapter_version)`。
- `ansich_context_snapshot_items(snapshot_id, ordinal, channel, role, content_block_id, visible_bytes, estimated_tokens, metadata_json)`；主键/唯一 `(snapshot_id, ordinal)`。

索引至少包含 `(task_id, step_seq)`、`(step_id, attempt_no)`、`(task_id, request_obs_id)`、`(snapshot_id, ordinal)`、`content_hash`。`effective_context_snapshot_id` 只能指向同一 Step 的 successful attempt，projector 在设置前验证该不变量。

## 8. Observation 与投影规则

新增 kinds：`step.started`、`step.closed`、`llm.requested`、`llm.responded`、`llm.failed`、`content.produced`、`context.snapshotted`。一个 request snapshot 可以拆成多条 Observation，但必须用 causation chain 串联；Phase 2 推荐一个 `llm.requested` 持有 request metadata，`context.snapshotted` 持有 inventory，ContentBlock 用独立 `content.produced`。

Structural projector 的幂等键：

```text
Step: task_id + step_seq
Attempt: step_id + attempt_no
Snapshot: request_obs_id
Snapshot item: snapshot_id + ordinal
ContentBlock: producer_obs_id + occurrence_ordinal
```

`llm.responded` 只把对应 attempt 标为 success；DecisionProbe 确认该 response 被上层接受后，`step.closed` 才声明 `effective_attempt_no`。因此“provider 返回了结果但 retry middleware 丢弃它”的 attempt 仍被记录，却不会成为有效上下文。

晚到的 `llm.requested/responded` 可以补全 attempt，不允许改变一个由更新 Step close evidence 选定的 effective attempt。投影器对缺 request 的 response 创建 incomplete attempt，字段保持 unknown。

## 9. API 与开发者页面

扩展：

```text
GET /api/ansich/tasks/{task_id}/timeline
GET /api/ansich/steps/{step_id}
GET /api/ansich/steps/{step_id}/context
GET /api/ansich/content-blocks/{block_id}/payload
```

timeline 使用稳定 cursor `(occurred_at, ingest_seq)`，返回 Task lifecycle、Step 和 system operation；并行事件可有相同 occurred_at，不强制伪造因果顺序。Step detail 返回 attempts 数组、effective 标记、response metadata、issued Tool inventory 和 control Belief。

`/context` 默认只返回 item inventory、hash、bytes/tokens、origin kind 和 payload availability，不返回 raw body。payload endpoint 要求 admin；Phase 2 先记录访问日志，Phase 11 升级为强审计事务。

Task 页面增加 Timeline、Steps、Context 标签。system operation 使用独立样式和计数，禁止混入 `Step #N`。重试 attempt 折叠在单个 Step 下，默认展开 effective attempt。

## 10. TDD 测试矩阵

- middleware characterization：sync/async、retry、stream、异常顺序。
- Step allocator：从 durable max 恢复、并发 Task 隔离、system operation 不消耗 seq。
- classification：lead/subagent 产生 Step；title/summarization/memory/goal 只产生 system operation。
- adapter proxy：Tool binding、structured output、stream chunks、provider exception 不被改变。
- snapshot serializer：多模态、有序 content parts、动态 Tool schema、unsupported object、unknown origin。
- secret tests：header/DSN/request secret 不落 Observation/Payload；manifest 不含原值。
- projector：多 attempt 单 Step、晚到 response、重复 request、无 Tool final Step、all-attempt failure。
- API/UI：effective attempt、system operation 分离、raw payload lazy load、unknown block、timeline cursor 稳定。
- 回归：启用/禁用 Ansich 时 fake model 收到的 request 深度相等；模型输出和 Run 状态不变。

## 11. 完成条件

- 一次 provider/adapter retry 显示为一个 Step 下多个 attempt。
- 内部五类 LLM 调用不会增加 Agent Step 数。
- 任一 effective attempt 可重建适配器边界的有序消息、visible Tool schemas、response format 和 generation settings。
- 不可序列化或未知来源内容以 explicit unknown 保留，不会静默消失。
- 探针失败、payload 超限或序列化异常均不会中止 Agent。
