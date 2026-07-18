# Phase 5 代码评审跟进项

来源:commit `c6d0a2ae`(Phase 5 活动任务、心跳与预算 Operations Lens)的代码评审(2026-07-18)。编号带 `M`(中)/`L`(低)优先级;修复一项后同步更新总览表和该项"状态"行,保留原始诊断记录。

## 状态总览

| 编号 | 摘要 | 状态 | 修复时间 | Commit |
| ---- | ---- | ---- | -------- | ------ |
| M1 | `assess_operations` 每秒无过滤扫描全部历史 budget 行,开销随任务总量线性增长 | ⬜ 未修复 | — | — |
| M2 | heartbeat belief 去重键含每秒变化的 `age_ms`,断言表按 running 任务每秒 +1 行 | ⬜ 未修复 | — | — |
| M3 | Operations 页面用 active list 替换全部 Task 列表,历史 Task 失去 UI 入口 | ✅ 已修复 | 2026-07-18 | 待提交 |
| L1 | read model 每周期无条件重写 `updated_at`,ETag/304 机制几乎永不命中 | ⬜ 未修复 | — | — |
| L2 | 两个管理员 GET 在空结果时同步触发全量 assessment(读端点做重写工作) | ⬜ 未修复 | — | — |
| L3 | token 维度的 `budget.consumed` 未被排除,存在与 `llm.responded` usage 双计的潜在路径 | ⬜ 未修复 | — | — |

## M1. `assess_operations` 每秒无过滤扫描全部历史 budget 行

- 状态:✅ 已修复(2026-07-18,commit 待提交)。新增 `lifecycle_scope=terminal|active|all`,InMemory/SQLite/PostgreSQL 查询均在 limit/cursor 前应用 scope;Operations 恢复“运行中/历史任务”双视图,历史页不轮询并通过 opaque cursor“加载更多”,terminal 行继续进入原 Task detail。后端 HTTP/SQL、前端 API/polling 与 Playwright 均有回归覆盖。以下保留原始诊断记录。
- 位置:`backend/packages/harness/deerflow/ansich/persistence/sql.py::assess_operations` 的 budget 循环(`select(AnsichTaskBudgetRow)` 无任何 task/control 过滤)。
- 现状:后台 assessor 每 `operations_assessment_interval_ms`(默认 1 秒)运行一次;heartbeat 部分只扫 running 任务,但 budget 部分对**所有历史任务**的每条 budget 行各做一次 usage `session.get` + current belief `session.get` + evidence 查询。terminal 任务的 usage/budget 不再变化,dedup 能避免写入,但查询照做。随历史任务累积(每任务 1–4 条 budget 行),每秒的评估开销线性增长——一万个历史任务约等于每秒数万条 SQL。`GET /operations/active-tasks` 与 `GET /tasks/{id}/budgets` 的懒触发路径(见 L2)同样受累。计划 §5 只要求"terminal 后 absolute breach 仍保留",不要求 terminal 后反复重评。
- 方向:budget 评估 join `AnsichTaskSummaryRow.control_value == "running"` 过滤;terminal 任务在 terminal 投影时做最后一次 budget 评估并保留 breach 断言,不再进入周期扫描。配"terminal 任务不进入周期评估、breach 断言保留"的回归测试。
- 归属:Phase 6 前完成(告警评估会复用同一 assessor 通道,先治理再叠加)。

## M2. heartbeat belief 断言按 running 任务每秒 +1 行

- 状态:⬜ 未修复。
- 位置:`sql.py::assess_operations` 的 heartbeat dedup 比较(`current_assertion.value_json == {"value": belief.value, "age_ms": belief.age_ms}`)+ `ansich/operations.py::assess_heartbeat`(`age_ms` 由 `now - occurred_at` 计算)。
- 现状:`age_ms` 每个评估周期都随 `now` 前进而变化,dedup 恒不命中——每个有 heartbeat 的 running 任务,每秒新增一条 `AnsichBeliefAssertionRow` + 一条 evidence 行(仅 `unknown` 状态因 `age_ms=None` 稳定不膨胀)。一个跑 24 小时的任务约产生 8.6 万条断言;断言表是 append-only,不会自动收缩。这不是正确性问题(current belief 指针正确),而是无上限的存储/写入膨胀,并把有意义的 fresh↔stale 转变淹没在噪声断言里。
- 方向:dedup 只比较 `value` + evidence + resolver version;`age_ms` 移出 `value_json`,仅在 read model(`heartbeat_json`)里呈现实时 age。这样断言只在 fresh↔stale↔unknown 转变时产生,与"重新收到 heartbeat 后生成新 assertion fresh"的计划语义一致。配"同一状态连续两次评估不新增断言、状态转变才新增"的回归测试。
- 归属:Phase 6 前完成(告警会订阅 belief 转变,噪声断言会直接放大成噪声告警)。

## M3. Operations 页面替换列表后历史 Task 失去入口

- 状态:⬜ 未修复。
- 位置:`frontend/src/app/workspace/ansich/operations/page.tsx` 从 `useAnsichTasks`/`AnsichTaskRow` 改为仅使用 `useAnsichActiveTasks`/`AnsichActiveTaskRow`;`backend/packages/harness/deerflow/ansich/persistence/sql.py::_refresh_active_task_read_model` 只物化 `control_value == "running"` 的 Task。
- 现状:Phase 5 为了展示 heartbeat、dwell、Usage 和 Budget,把 `/workspace/ansich/operations` 原有的全部 Task 列表直接替换成 `/api/ansich/operations/active-tasks`。Task 进入 completed/failed/interrupted 后会从 active read model 消失,页面没有历史/全部 Task 标签或第二入口。历史数据并未删除:`GET /api/ansich/tasks`、`useAnsichTasks`、Task detail 和持久化投影仍然存在;这是前端信息架构回归,不是采集或 retention 故障。它阻断 dev/op 对已结束运行做事后诊断,与 Ansich 的核心使用场景冲突。
- 方向:Operations 页面拆成“运行中”和“历史任务”两个明确视图。运行中继续使用 active read model、自适应 5s/10s polling 和 P5 丰富字段;历史任务使用持久化 Task 查询、稳定 cursor、时间范围和 terminal control 过滤,默认不高频轮询。历史过滤必须在 SQL 的 `limit/cursor` 前完成,不能先取一页再由前端排除 running Task,否则会产生短页和错误 next cursor。建议为 `/api/ansich/tasks` 增加 `lifecycle_scope=terminal|active|all`(或等价的多 control 过滤),并在历史行保留现有 Task detail 链接。
- 回归测试:后端覆盖 terminal scope 同时返回 completed/failed/interrupted、排除 running、跨页 cursor 无重复/漏项;前端单测覆盖两个视图使用各自 endpoint 与 polling policy;Playwright 覆盖 running Task 只在“运行中”、terminal Task 可从“历史任务”进入完整详情,以及空 active list 不再造成“系统没有任何 Task”的误解。
- 归属:立即修复,不等待 Phase 6。Phase 6 会继续扩展 Operations 告警视图,应先恢复 Task 历史导航基线。

## L1. read model 每周期无条件重写,ETag/304 几乎永不命中

- 状态:⬜ 未修复。
- 位置:`sql.py::_refresh_active_task_read_model`(对既有行无条件 `setattr` 全部字段并置 `updated_at=now`)+ `app/gateway/routers/ansich.py::list_active_tasks`(ETag 计算包含 `projection_status` 与 `updated_at`)。
- 现状:即使任务内容完全未变,read model 行的 `updated_at` 也每秒被 bump;响应体里的 `projection_status`(lag 等)也随时间变化。因此 If-None-Match 几乎永远不等于新 ETag,304 分支形同虚设,前端"未变化时保留已有对象"实际只靠 TanStack 的 structural sharing 兜底。计划 §7 的 ETag 意图未真正达成。每秒对每个 running 任务的一次无效 UPDATE 也是纯粹的写放大(量级小)。
- 方向:refresh 时先比较序列化内容,未变则既不写行也不 bump `updated_at`;ETag 只覆盖 `items` + `next_cursor`(`projection_status` 移出 ETag 或放响应头)。配"内容未变时 304 命中"的路由测试。
- 归属:Phase 6 UI 迭代;可与 M2 一并处理(同为"未变不写")。

## L2. 管理员 GET 在空结果时同步触发全量 assessment

- 状态:⬜ 未修复。
- 位置:`routers/ansich.py::list_active_tasks`(`if not tasks and cursor is None: await service.assess_operations()`)与 `::get_task_budgets`(`if budgets.budgets and not health: await service.assess_operations()`)。
- 现状:读端点在冷启动/空结果时同步执行一次完整 `assess_operations`——含 M1 的全量 budget 扫描和整个 read model 重建。后台 assessor 周期只有 1 秒,懒触发的收益只是首个请求少等最多 1 秒;代价是 GET 延迟在 M1 恶化时不可控,且读路径产生写副作用(assertion/read model 写入)。
- 方向:随 M1 修复后重新评估;建议懒触发仅保留"read model 从未刷新过"(服务刚启动)一种情形,或完全移除依赖后台周期。
- 归属:随 M1 一并处理。

## L3. token 维度的 `budget.consumed` 存在潜在双计路径

- 状态:⬜ 未修复。
- 位置:`backend/packages/ansich/ansich/usage.py::usage_contributions_for_observation` 的 `budget.consumed` 分支(仅排除 `_STRUCTURAL_DIMENSION_BY_KIND.values()`,即 llm_attempts/steps/tool_calls_*)。
- 现状:token 维度(input/output/total_tokens)的权威来源是 `llm.responded.usage_metadata`;但若未来某个 probe 发出 dimension 为 token 的 `budget.consumed`,提取器会照单接受并与 `llm.responded` 的贡献相加(双计)。当前仓库内没有这样的 producer(wall_time_ms 是唯一的 `budget.consumed` 使用者),属 latent 风险,但契约上没有任何东西阻止它。
- 方向:在提取器排除 token 维度的 `budget.consumed`(或仅允许显式白名单 `wall_time_ms`/`child_tasks_spawned`),配一条"token 维度 budget.consumed 被忽略"的单测。
- 归属:Phase 8(inclusive usage rollup 会扩展贡献来源,先收紧契约)。

## 评审中确认无需跟进的点(留档)

- `wall_time_ms` 语义正确:heartbeat 投影与 usage 投影都取高水位(max),terminal 的全量 delta 不与 heartbeat elapsed 相加;`max(0, ...)` 防时钟回跳负数。
- `tool_calls_executed` 以 ToolCall subject 去重(SQL 端 join 查询、内存端 executed 集合),started/returned_raw/failed 对同一调用只计一次;`tool_calls_issued` 独立计数,denied 不计 executed——符合 Phase 3 的 issued/executed 分离原则。
- Budget 快照只为 DeerFlow 真实执行的政策标 `enforcement=true`(TokenBudgetMiddleware、SubagentLimitMiddleware 总量上限);无配置维度不造 `limit=0`;clamp 保留 requested/effective;`stale_after >= 2 * interval` 有 model validator;`config_version` 已 bump 到 29。
- Heartbeat 只在持有 Run ownership 的 worker 启动(`owner_worker_id == worker_id`),每 tick 复查 ownership;worker `finally` 顺序为 stop heartbeat → reconcile tool calls → terminal,满足"terminal Observation 前停止 timer";采集 fail-open,队列拒绝进入既有 loss range 通道。
- 迁移 `0016_ansich_operations` 幂等建表/索引、downgrade 完整;usage contribution 用方言原生 `ON CONFLICT DO NOTHING` + RETURNING 保证投影重试不重复累加。
- active-task cursor `(last_evidence_at DESC, task_id)` 稳定;新增 API 全部 `require_admin_user`;`inclusive_status="not_available"` 未复制 local 冒充 inclusive。
- 前端轮询符合计划:running 5 秒 / idle 10 秒 / hidden 暂停 / terminal 详情停止;`tests/ansich` 194 项在评审机复跑通过。
