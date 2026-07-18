# Phase 3 代码评审跟进项

来源:commit `6177d53d`(Phase 3 ToolCall 责任链 + ContextState 切片)的代码评审(2026-07-17)。编号带 `M`(中)/`L`(低)优先级;修复一项后同步更新总览表和该项"状态"行,保留原始诊断记录。

## 状态总览

| 编号 | 摘要 | 状态 | 修复时间 | Commit |
| ---- | ---- | ---- | -------- | ------ |
| M1 | `resolve_tool_call` 回退匹配可能把证据错绑到其他 ToolCall | ✅ 已修复 | 2026-07-17 | `8044ecfc` |
| M2 | transform 分类靠字符串嗅探,与上游中间件措辞硬耦合 | ✅ 已修复 | 2026-07-17 | `6c655ddb` |
| M3 | Collector 队列按条数而非字节 bound,大 artifact 内存上限不受控 | ✅ 已修复 | 2026-07-18 | `7c4ec498` |
| L1 | 观察开销(canonical JSON + sha256 + 锁内 delta)基准缺位 | ⬜ 未修复 | — | — |
| L2 | 已推送迁移 0007/0009 被原位修改(行为等价,记录留档) | ℹ️ 无需修复 | — | `6177d53d` |

## M1. `resolve_tool_call` 回退匹配可能把证据错绑到其他 ToolCall

- 状态:✅ 已修复(2026-07-17,commit `8044ecfc`)。按 TDD 修复:回退匹配同时要求 `tool_name` 相等;`provider_call_id is None` 且同名候选多于一个时拒绝绑定(交给 terminal reconcile 记 `unknown_terminal`);真实 provider id 的重用消歧保留 `(step_seq, -call_seq)` 选择。新增"跨工具名不回退绑定"与"无 id 歧义拒绝绑定"两条回归测试。以下为原始诊断记录。
- 位置:`backend/packages/harness/deerflow/ansich/execution.py::resolve_tool_call` 的回退分支。
- 现状:精确 `(provider_call_id, tool_name, args_hash)` 不中时,回退条件只剩 `provider_call_id` 相等。当 provider 不回传 id(`None`)且同一响应有多个未认领调用时,回退集是"所有 provider_id 为 None 的未认领调用",raw/visible 证据可能被挂到**不同工具**或**不同参数**的 ToolCall 上。责任链里错误归属比缺失更有害:缺失会被 terminal reconcile 如实标 `unknown_terminal`,错绑则是无警告的假证据。
- 方向:回退匹配至少同时要求 `tool_name` 相等;`provider_call_id is None` 且候选仍多于一个时放弃绑定(返回 None,由 reconcile 收尾)。附"不同名不回退绑定"与"无 id 歧义时拒绝绑定"两条回归测试。
- 归属:立即修复。

## M2. transform 分类靠字符串嗅探,与上游中间件措辞硬耦合

- 状态:✅ 已修复(2026-07-17,commit `6c655ddb`)。按 TDD 修复:变换中间件在 `additional_kwargs.deerflow_tool_transforms` 上追加声明式条目(budget → `truncated`/`externalized`,sanitizer → `sanitized`;`tool_transform_meta.py` 提供 append/read helper);观察者按"content-hash 相等 → raw 终态 error_normalized → 声明 trail 末项 → 措辞启发式兜底"的优先级分类,payload 新增 `classified_by` 与完整有序 `transforms` trail。四条回归测试覆盖两个中间件的声明、"措辞无关"分类与启发式降级标注。Phase 4 新增 transform 种类时只需在对应变换处 append 声明条目。以下为原始诊断记录。
- 位置:`backend/packages/harness/deerflow/ansich/tool_middleware.py::_transform_kind`。
- 现状:`"chars omitted"`→`truncated`、`"full output"+"outputs/"`→`externalized`、`"&lt;"/"&gt;"`→`sanitized`、`"human_input"`→`clarification_card` —— 与 `ToolOutputBudgetMiddleware`/`ToolResultSanitizationMiddleware`/`ClarificationMiddleware` 的输出措辞硬耦合。上游改一个提示词,分类静默退化为 `unknown`;工具输出恰好含这些子串会误分类;`coalesced` 永远不会被产生。`transform_version="1"` 已为演进预留空间。
- 方向:让实施变换的中间件在 `deerflow_tool_meta`(或专用键)上显式标注 transform 事实,观察者优先读结构化元数据,字符串启发式仅作无元数据时的兜底并在 payload 标注 `classified_by=heuristic`;每种 transform 至少一条"上游措辞变更不破坏分类"的测试。
- 归属:Phase 4 前完成(压缩谱系会引入 `coalesced`/`summarized` 等新 transform,启发式无法扩展)。

## M3. Collector 队列按条数而非字节 bound

- 状态:✅ 已修复(2026-07-18,commit `7c4ec498`)。按 TDD 修复:Collector 新增 `queue_byte_capacity`(默认 64 MiB),按 Observation 规范 JSON 的 UTF-8 字节计费,与条数容量共同执行批量全收/全拒;超限返回 `queue_bytes_full` 并进入既有 lost-range/degraded 路径。health 与 Operations UI 暴露当前字节、字节容量和最高水位;无法序列化的非规范 payload 返回 `serialization_failed` 而不向 Agent 抛错。容量注入测试覆盖 count 未满时的字节拒绝、flush 后当前水位归零及高水位保留。以下为原始诊断记录。
- 位置:`backend/packages/ansich/ansich/service.py`(`queue_capacity` 条数语义)+ `tool_middleware.py::_result_body`(携带 `message.artifact`)+ `serialization.py` bytes 分支(base64 内联)。
- 现状:单条在途观测可达 MB 级(如 base64 图片 artifact),`queue_capacity=10000` 条的内存上限不受字节控制;落库端有 `inline_payload_max_bytes` 的 blob offload,但在途队列是完整 Python 对象。
- 方向:capture 侧对超大 body 截断为摘要(保留 `content_hash`、`byte_length`、截断标记,raw 完整性经由 blob 层已不可得时如实标注),或为队列增加字节水位并纳入 health;两者择一并配容量注入测试。
- 归属:Phase 5(活动任务与预算)前完成 —— 心跳/预算负载会放大在途体量。

## L1. 观察开销基准缺位

- 状态:⬜ 未修复。
- 现状:每次模型调用在事件循环上执行全上下文 canonical JSON + sha256 + 锁内 state delta;工具两端各一次 safe serialize。开销 O(context bytes),尚无量化数据。
- 方向:README 已把"关闭 Ansich 的基准对比"列为阶段完成门禁;Phase 3 引入工具双探针后应尽早执行(目标 ingest 速率下 Agent p95 延迟增量在约定预算内,对应 Phase 11 §10 的 performance 条目)。
- 归属:Phase 12 验收前;建议随下一次真实负载试用一并采集。

## L2. 已推送迁移 0007/0009 被原位修改(记录留档)

- 状态:ℹ️ 无需修复。0007 仅把自写 `_add_column` 换为 `_helpers.safe_add_column`(行为等价、无 schema 差异);0009 只增强 downgrade(blob→观测 payload 正文还原)。分支未合入 main 且单人开发,风险可接受;留档原因:若未来有环境已按旧版执行过 downgrade,需人工核对。后续对**已合入 main**的迁移一律只做前向新增,不做原位修改。
