# Phase 2 代码评审跟进项

来源:commit `22198141`(Phase 2 Step 与上下文可观测性切片)的代码评审(2026-07-17)。编号带 `H`(高)/`M`(中)/`L`(低)优先级;修复一项后同步更新总览表和该项"状态"行,保留原始诊断记录。

## 状态总览

| 编号 | 摘要 | 状态 | 修复时间 | Commit |
| ---- | ---- | ---- | -------- | ------ |
| H1 | Timeline 轮询端点泄漏原始内容体,绕过带日志的 raw 通道 | ⬜ 未修复 | — | — |
| H2 | 上下文快照全量重录,O(N²) 写放大且无 hash 去重 | ⬜ 未修复 | — | — |
| M1 | 新增 `inline_payload_max_bytes` 未 bump `config_version` | ⬜ 未修复 | — | — |
| M2 | 模型实例上的 `_ansich_call_class` 元数据无读取方 | ⬜ 未修复 | — | — |
| M3 | raw-payload 端点缺 `Cache-Control: no-store` | ⬜ 未修复 | — | — |
| M4 | LLM 错误 fallback 时 Step 记为 `final_answer` 的语义待确认 | ⬜ 未修复 | — | — |
| M5 | `list_system_operations` 按随机 UUID 排序 | ⬜ 未修复 | — | — |
| L1 | 迁移 0007 自写 `_add_column` 而非 `_helpers.safe_add_column` | ⬜ 未修复 | — | — |
| L2 | worker 使用字面量 `"__ansich_execution_context"` 而非常量 | ⬜ 未修复 | — | — |
| L3 | `usage_json` 列混存 usage 与 response_metadata,命名误导 | ⬜ 未修复 | — | — |
| L4 | `get_max_step_seq` 依赖投影追平的前提未标注 | ⬜ 未修复 | — | — |

## H1. Timeline 轮询端点泄漏原始内容体,绕过带日志的 raw 通道

- 状态:⬜ 未修复。
- 位置:`backend/app/gateway/routers/ansich.py::get_task_timeline`(原样 `model_dump()` 观测 payload)+ `deerflow/ansich/middleware.py::_record_captured_request`(`content.produced` payload 内联完整 `body`)+ `frontend/.../observation-timeline.tsx`(渲染 `observation.payload`)。
- 现状:≤`inline_payload_max_bytes` 的原始提示词/工具输出(绝大多数)进入 5 秒轮询响应与 TanStack 缓存,且不触发 raw-payload 端点的访问日志 —— 同时违反 frontend/AGENTS.md("raw body 绝不进轮询响应或 query cache")与 backend/AGENTS.md("raw body 只经 logged 端点")。路由测试未覆盖"timeline 不含 body",因此漏网。
- 方向:timeline DTO 转换时剥离 `content.produced` payload 的 `body` 字段(保留 hash/size 摘要),或从 timeline 排除该 kind;补"timeline 响应不含原始 body"回归测试。
- 归属:立即修复。

## H2. 上下文快照全量重录,O(N²) 写放大且无 hash 去重

- 位置:`deerflow/ansich/middleware.py::_record_captured_request` + `sql.py` content-block 投影。
- 现状:每次模型调用把整个上下文逐条持久化为独立 `content.produced` 观测(N 条消息 → N+2 条观测),`block_id` 每次新生成,无跨 attempt 的 content-hash 复用(`ix_ansich_content_blocks_hash` 索引已建但未用);且每条观测生成 3 个 projection job(structural/control 对 step 观测是 no-op 仍走建行+认领)。一次长对话 run 的累计存储约为各 Step 上下文大小之和(平方级)。连锁风险:大上下文单次调用产生数百条观测,逼近 `queue_capacity` 时 `content.produced` 被丢弃 → 对应 `context.snapshotted` 投影 poison(重试 5 次后 failed,health 降级)。
- 方向:最小改进是 `(task, content_hash)` 级的 block 复用(未变化的 system prompt 与历史消息占每次快照绝大部分);完整方案(增量快照/谱系)属 Phase 4 上下文谱系与压缩的范围,实施 Phase 4 时必须吸收本条。
- 归属:Phase 4(上下文谱系与压缩);若 Phase 3 前有真实负载试用,先做最小 hash 复用。

## M1. 新增 `inline_payload_max_bytes` 未 bump `config_version`

- 位置:`config.example.yaml`(仍为 27)。
- 现状:`make config-upgrade` 不会向存量用户合并新字段,违反仓库"改 schema 必 bump"约定。
- 方向:bump 到 28,一行修复;下次任何 config 变更时顺带处理亦可。

## M2. 模型实例上的 `_ansich_call_class` 元数据无读取方

- 位置:`deerflow/models/factory.py::create_chat_model`(`object.__setattr__` stamp)。
- 现状:全部调用点都传了 `ansich_call_class`/`ansich_operation_kind`,但仓库内无任何读取方(仅测试断言存在)—— 死代码,或本应作为 Decision middleware 的 actor 判定来源而漏接线。
- 方向:二选一:删除 stamp 与参数,或让 `AnsichDecisionMiddleware`/`observe_system_model_*` 从模型实例读取分类作为兜底。

## M3. raw-payload 端点缺 `Cache-Control: no-store`

- 位置:`routers/ansich.py::get_content_block_payload`。
- 现状:原始提示词体可能被浏览器/中间层缓存;Phase 11 §7 明确要求 no-store,端点既然提前落地就应带上。
- 方向:响应加 `Cache-Control: no-store` 头,一行修复;Phase 11 落地 fail-closed 审计时复查。

## M4. LLM 错误 fallback 时 Step 记为 `final_answer` 的语义待确认

- 位置:middleware 链顺序 —— `AnsichDecisionMiddleware` 在 `LLMErrorHandlingMiddleware` 外侧。
- 现状:provider 异常被转成 fallback AIMessage 后,Decision 记 `step.closed result="final_answer"`,而该 Step 的 attempts 全为 `failed`、`effective_attempt_no=None`,读数自相矛盾。
- 方向:识别 `additional_kwargs.deerflow_error_fallback` 标记并记为 `model_failed`(或在 payload 标注 fallback);先对照设计文档确认意图再改,附中间件顺序回归测试。

## M5. `list_system_operations` 按随机 UUID 排序

- 位置:`sql.py::list_system_operations` 的 `order_by(request_obs_id, attempt_no)`。
- 现状:`request_obs_id` 是 UUID,排序无业务意义,系统操作列表顺序实际随机。
- 方向:改按关联观测的 ingest_seq 或 attempt 创建时间排序。

## L1–L4(低优先级,顺带处理)

- **L1** 迁移 0007 自写 `_add_column`,应复用 `migrations/_helpers.py::safe_add_column`(行为等价,约定不符)。
- **L2** `runtime/runs/worker.py` goal-continuation 处用字面量 `"__ansich_execution_context"`,应使用已导入的 `ANSICH_EXECUTION_CONTEXT_KEY`。
- **L3** `AnsichLlmAttemptRow.usage_json` 同时存 `usage` 与 `response_metadata`,列名误导;后续迁移时拆列或改名。
- **L4** `get_max_step_seq` 假设"重建 execution context 时该 task 的 step 投影已追平";当前每 run 只建一次 context 所以安全,但任何未来 crash 恢复/run resume 路径在投影滞后时会分配重复 `step_seq` → 唯一约束冲突 → poison job。应在代码注释标注该前提。
