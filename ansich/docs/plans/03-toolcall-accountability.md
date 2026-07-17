# Phase 3 — ToolCall 责任链

## 1. 交付目标

本阶段把 Agent 的一次 Tool 选择拆成四条独立事实流：模型发出了什么意图、授权层作了什么决定、Tool 实际执行得到什么原始结果、经过中间件后模型看到了什么结果。开发者可以从 Step 定位每个并行 ToolCall，并区分 denied、failed、timed out、cancelled 和证据不足的 unknown terminal。

Phase 3 不实现完整 Scope/AuthorizationSnapshot/副作用模型；Phase 9 会扩展它。当前阶段必须保留授权 attachment point，并且绝不把“没有执行证据”解释为“执行成功且无副作用”。

## 实施状态（2026-07-17）

本阶段的本地纵向切片已经落地：

- `AnsichDecisionMiddleware` 从最终 AIMessage 分配 UUID4 `tool_call_id`，按数组顺序写 `tool.issued`，provider ID 仅作为非唯一属性；参数经过 canonical safe serializer 后只保存 hash 与受控 preview。
- `AnsichVisibleToolMiddleware` 是 Tool wrapper 的最外层观测边界；`AnsichRawToolMiddleware` 位于 `ToolErrorHandlingMiddleware` 内侧、真实 callable 的最近可用 Agent middleware 边界。两者分别写 raw/visible ContentBlock 与 transform edge，不把 normalized error 伪装成 raw success。
- run-scoped registry 使用 provider ID、name、args hash 和 Step/call sequence 解析并行调用；持久化 ToolCall 会在新 worker execution context 中恢复，Gateway 重启后仍能继续匹配或在 Task terminal 写 `unknown_terminal`。
- `0013_ansich_tool_accountability` 新增 typed ToolCall/result/derivation 表和 Task issued/executed counters；投影支持 raw/visible 先到、重放、provider ID 重用和冲突终态。冲突 evidence 全部保留为 hard assertion，由 `tool-terminal-precedence@1` 选择当前值，并把 Task observability 标为 degraded。
- Step 只有在全部 issued ToolCall 获得 terminal/unknown-terminal evidence，且后续 Step 或 Task terminal 已观测时才从 acting 关闭。
- 管理员 API 分离 ToolCall inventory、raw result 和 visible result；后两者独立鉴权、独立审计并返回 `Cache-Control: no-store`。Operations Step 页面按 `call_seq` 展示 Issued → Authorization → Execution → Visible to model，payload 仅在明确点击后加载。

已覆盖成功、exception/error normalization、timeout、cooperative cancellation、binary payload 安全封装、short-circuit deny、missing-terminal reconciliation、worker terminal 顺序、进程恢复、并行顺序、provider ID 重用、known-secret exclusion、collector fail-open、乱序投影、冲突终态、restart/rebuild、usage 幂等、管理员/普通用户 API 边界。SQLite 和本地前端验证完成；PostgreSQL migration matrix 与生产负载演练不在本阶段本地实现结果中冒充完成。

## 2. ToolCall 身份与映射

ToolCall 主身份是 Ansich `tool_call_id`，由应用生成 UUID4；稳定序号为 `(step_id, call_seq)`。`call_seq` 按最终 AIMessage 中 ToolCalls 的数组顺序从 1 开始，多个并行调用共享 Step。

provider `tool_call_id` 仅存为 `provider_call_id` 属性。运行时 lookup key 使用 `(task_id, step_id, provider_call_id, occurrence_index)`；不能建立 provider ID 全局唯一约束，因为上下文压缩后可能重用相同 ID。

DecisionProbe 接受最终 AIMessage 时立即为所有 ToolCalls 分配 Ansich ID，并发出 `tool.issued`，即使后续 guardrail、loop detector 或 Tool middleware 短路也保留 Agent intent。Observation payload 至少包含 Tool name、secret-filtered canonical args、args hash、call_seq、provider ID 和 schema block ID。

## 3. 三个采集位置

DeerFlow adapter 新增：

```text
probes/tool_intent.py
probes/tool_raw_execution.py
probes/tool_visible_result.py
tool_context.py
reconciliation.py
```

采集位置分别为：

1. **Intent probe**：Phase 2 的有效 AIMessage 完成处，先于任何 Tool middleware。
2. **Raw execution probe**：尽可能贴近真正的 Tool callable，在调用前发 `tool.started`，对原始返回值/异常/timeout/cancellation 发 `tool.returned_raw`、`tool.failed`、`tool.timed_out` 或 `tool.cancelled`。
3. **Visible result probe**：位于 ToolErrorHandling、sanitization、output budget、externalization 和 normalization 之后，捕获最终送回 Agent state 的 ToolMessage，发 `tool.result_visible`。

现有 middleware-order characterization test 固定了 visible observer 在 output budget/sanitization 外侧、raw observer 在 ToolErrorHandling 内侧的顺序；lead/subagent 使用相同边界，关闭 Ansich 时两者均不安装。

sync Tool 在 worker thread 中通过 ToolCallRequest runtime 显式取得 run-scoped `AnsichExecutionContext`；当前调用只在 wrapper 动态范围内使用 instance-local ContextVar 关联 raw/visible 片段，身份解析和 Collector handle 不依赖 event-loop global。probe 的记录仍为非阻塞 Collector 调用。

## 4. 原始结果、可见结果与转换

`tool.returned_raw` 生成 `tool_result_raw` ContentBlock。任何中间件改变内容时生成新的 `tool_result_visible` ContentBlock，并建立 `derived_from(visible -> raw)`，边记录 `transform_kind`：

```text
unchanged | error_normalized | sanitized | truncated |
externalized | coalesced | clarification_card | unknown
```

即使 raw 和 visible 字节完全相同也使用不同 block occurrence；允许通过相同 content hash 说明 unchanged。raw Python 对象先经过安全 serializer，保留类型、artifact metadata 和受控内容；禁止调用任意 `__repr__`。二进制/大结果进入 payload store。

异常对象的 public class、受控 message、stack fingerprint 和 duration 可记录；stack trace 默认不进模型可见块，raw payload 也必须经过 secret exclusion。用户可见的 normalized error 是另一个 ContentBlock。

## 5. 状态机与终态 reconciliation

ToolCall hard control state：

```text
unknown -> issued
issued -> acting | denied | timed_out | cancelled | failed | unknown_terminal
acting -> returned | timed_out | cancelled | failed | unknown_terminal
returned + visible-result evidence -> returned（补全 visible outcome）
```

`tool.result_visible` 不是 raw execution success 的替代证据：Tool middleware 可以在未执行时直接生成 ToolMessage。因此 projection 同时保存 `execution_status` 和 `visible_result_status`，API 再通过完整 Belief 暴露，不能压成一个布尔 success。

Task terminal 时运行 reconciliation：遍历该 Task 已 issued 但无 terminal evidence 的 ToolCall。如果 interrupt causation 明确且 Tool future 被取消，发 `tool.cancelled`；如果只知道 Task 结束，发 `tool.unknown_terminal`。reconciliation Observation 使用稳定 source event ID，重复 terminal flush 不产生重复终态。

Clarification Tool 返回结构化 human-input request 时，raw/visible 流正常闭合，并在 outcome metadata 标记 `human_input_requested=true`；它不是 timeout 或 failed。

## 6. 数据库增量

新增：

- `ansich_tool_calls(entity_id, step_id, call_seq, provider_call_id, tool_name, args_hash, tool_schema_block_id, issued_obs_id, raw_terminal_obs_id, visible_result_obs_id)`；唯一 `(step_id, call_seq)`。
- `ansich_tool_call_results(tool_call_id, result_role, content_block_id, source_obs_id)`；`result_role` 为 `raw`/`visible`，唯一 `(tool_call_id, result_role, source_obs_id)`。
- `ansich_content_block_derivations(derived_block_id, source_block_id, transform_kind, transform_version, established_obs_id)`；唯一 `(derived_block_id, source_block_id, transform_kind)`。
- Phase 9 前的 `authorization_status` 不放裸列；如无授权 Observation，Current Belief 返回 `unknown`。

增加索引 `(step_id, call_seq)`、`provider_call_id` 非唯一索引、`tool_name, issued_obs_id`、derivation 的正反向索引。正反向遍历必须都走索引，不能只为 backward lineage 建边。

usage projector 从 Observation 分别维护 `tool_calls_issued` 和 `tool_calls_executed`。executed 只由 `tool.started` 或更强执行证据增加；denied/short-circuit 不能增加 executed。

## 7. 投影和乱序处理

Tool structural projector 接受任意到达顺序：

- raw result 先到 issued 时，按 observation 中的 Ansich ToolCall ID 建 incomplete row，name/args 保持 unknown；issued 晚到后补全。
- visible result 没有 raw result时，建立 visible block 并把 execution status 留在 unknown，不反推执行。
- 重复 started/returned 由 source event unique 和投影自然键去重，usage 不重复累加。
- 同一 ToolCall 出现冲突 hard terminal evidence 时全部保留为 assertions，resolver 按有效 causation、evidence time 和 terminal precedence 选择，并产生 projection error/health signal供排查。

Step control projector 只在所有 issued ToolCall 都有 terminal/unknown_terminal evidence，并且下一次 Agent decision 或 Task terminal 已观测时，把 `acting/observing` 关闭；不能因为第一个并行 Tool 返回就关闭 Step。

## 8. API 与 UI

`GET /api/ansich/steps/{step_id}` 增加 ordered `tool_calls`，每项返回：intent、args hash/受控 preview、authorization Belief、execution Belief、raw result metadata、visible result metadata、transform edge、duration 和 evidence IDs。

新增：

```text
GET /api/ansich/tool-calls/{tool_call_id}
GET /api/ansich/tool-calls/{tool_call_id}/raw-result
GET /api/ansich/tool-calls/{tool_call_id}/visible-result
```

raw 和 visible endpoint 分开授权、分开 audit，不提供一个模糊的 `result` 字段。默认 Step 页面以四段责任链展示：Issued → Authorization → Execution → Visible to model；unknown 段必须可见。并行 ToolCalls 按 call_seq 分栏/列表，不按完成时间重排。

## 9. TDD 测试矩阵

- identity：并行调用、provider ID 重用、同名同参数不同 Step、无 provider ID。
- issued durability：guardrail deny、loop hard stop、middleware short-circuit 后仍有 intent。
- raw probe：sync/async return、exception、timeout、cooperative cancellation、binary payload。
- visible probe：unchanged、sanitized、truncated、externalized、normalized error、clarification card。
- state/reconciliation：Task interrupt、Task failure、缺 terminal、并行部分完成、重复 reconciliation。
- projection：raw 先到、visible 先到、冲突终态、重放两次、usage issued/executed 不重复。
- security：Tool args/result 中已知 secret、header、DSN 不落库；redaction manifest 无原值。
- API/UI：raw/visible 分离、unknown authorization、并行顺序、普通用户拒绝、payload lazy loading。
- fail-open：Collector 满或 DB 故障时 Tool callable 的参数、返回值、异常行为与禁用 Ansich 相同。

## 10. 完成条件

- 从任一 ToolCall 可以追到发出它的 Step、原始执行结果和模型可见结果。
- provider ID 重用不会覆盖或合并 ToolCall。
- denied、未执行和未知终态不会计作 executed/success。
- 所有内容变化至少有一条 raw-to-visible derivation；缺失变换证据显示 unknown。
- 并行 ToolCall 直到全部闭合或 reconciliation 后才关闭 Step 的 acting 部分。
