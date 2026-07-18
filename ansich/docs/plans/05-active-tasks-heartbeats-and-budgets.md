# Phase 5 — 活动任务、心跳与预算

## 实现状态（2026-07-18）

✅ 本地纵向切片已完成。Outer Run heartbeat 已接入 graph-independent monotonic
timer、现有 Run ownership、terminal/cancellation 清理和 fail-open Collector；
`heartbeat@1` 与 dwell assessor 只生成 rule Belief，不改写 hard Task control。
Usage 已覆盖 token/attempt/Step/Tool/wall-time/child spawn，各贡献可幂等重放；活动
Task 的 wall-time 使用 heartbeat elapsed，terminal 使用 monotonic duration，缺失
provider token 维度不猜测。Task admission 会冻结实际 TokenBudgetMiddleware 与
SubagentLimitMiddleware policy 的 requested/effective/enforcement/source。

迁移 `0016_ansich_operations` 新增 heartbeat、usage contribution、budget 和
`ansich_active_task_read_model`；SQLite upgrade/rebuild 与 PostgreSQL DDL 类型语义已有
测试。管理员 API 已提供 active-task filters/cursor/ETag、local Usage 和 Budget health；
Operator Lens 展示当前 Step/Tool、dwell、heartbeat、local Usage、overshoot、lag/loss，
并实施 active 5 秒、idle 10 秒、hidden 暂停及 terminal detail 停止轮询；Operations
同时保留不自动轮询、可 cursor 分页的历史 Task 视图。真实
PostgreSQL 升级矩阵、关闭 Ansich 的基准对比和生产 paper drill 仍按总计划作为最终
生产就绪门禁，不回填为本阶段的占位成功。

## 1. 交付目标

本阶段形成第一版 Operator Lens。运维人员可以看到当前活动 Task、正在执行的 Step/ToolCall、状态停留时间、最后心跳、本地资源消耗、有效预算以及 Ansich 投影延迟。

Heartbeat 只证明 Run worker 在某个时间仍存活；缺失 heartbeat 是 rule judgment，不是 Task 已失败的 hard evidence。Budget 是约束，Usage 是测量，两者必须分表、分 Observation、分 Belief。

## 2. Outer Run heartbeat

在 `runtime/runs/worker.py::run_agent()` 最外层、Agent graph stream 之外启动 `AnsichTaskHeartbeat`。它按 monotonic clock 每 `heartbeat_interval_seconds` 生成 `task.heartbeat`，Observation 的 occurred_at 使用发出时 UTC，payload 包含 process/producer instance、worker ownership epoch 和 monotonic elapsed。

heartbeat 不依赖模型 chunk、Tool progress 或 LangGraph event，因此一个长时间 ToolCall 期间仍有证据。timer 在 Task terminal Observation 前停止；shutdown/interrupt 使用 cancellation-safe `finally`，不得留下孤儿 timer。Collector 满时 heartbeat 可丢弃但要进入 loss range。

多 worker 下只有持有 RunManager ownership/lease 的 worker 发 heartbeat。Phase 11 完成 projector lease；本阶段至少用现有 Run ownership identity 防止两个 worker对同一 run 同时发活跃证据。

配置新增：

```yaml
ansich:
  heartbeat_interval_seconds: 10
  heartbeat_stale_after_seconds: 30
  long_dwell_seconds: 120
```

校验 `stale_after >= 2 * interval`。这些 rule 配置进入 assessor version/config hash，不作为 hard Task 状态。

## 3. Usage Observation

新增 `budget.consumed`，按原始发生 Task 记录 delta，不记录父 Task rollup。维度：

```text
input_tokens
output_tokens
total_tokens
llm_attempts
steps
tool_calls_issued
tool_calls_executed
wall_time_ms
child_tasks_spawned
```

Token 从每个 `llm.responded.usage_metadata` 提取。若 provider 只给 total，则 input/output 保持 unknown，不通过相减猜测。Step/attempt/Tool 计数由相应结构 Observation 投影，不能同时由 probe 和 read model 双写。wall time 以 Task started/terminal 的 monotonic duration 为主，活动 Task 使用 heartbeat elapsed；系统时钟跳变不能产生负数。

每个 usage contribution 以 `(source_obs_id, dimension)` 唯一，projector 重试不重复累加。`as_of` 取 source Observation occurred_at，read model 同时返回 `complete_through_ingest_seq`。

## 4. TaskBudget 快照

Task admission 从实际 DeerFlow runtime policy 解析 `budget.configured`。每条 `TaskBudget` 包含：

```text
task_id
dimension
aggregation_scope        // local | inclusive
warning_limit?
hard_limit?
enforcement              // true | false
source                    // release_default | runtime_override | shadow
effective_value
requested_value?
configured_obs_id
```

只有 DeerFlow 当时真正执行的 token、turn/step、wall-time、subagent 等限制可以标 `enforcement=true`。Ansich-only 阈值必须 `enforcement=false`。如果现有 DeerFlow 没有某维度限制，明确不创建该 Budget，API 返回 `configured=false`，不能返回 limit=0。

release default 与 run override 都保留，effective 规则在一个纯函数中计算并测试。配置被 clamp 时保存 requested/effective，但 usage 与 health只比较 effective。

## 5. 数据库与投影

新增：

- `ansich_task_heartbeats(task_id, heartbeat_obs_id, occurred_at, producer_instance_id, ownership_epoch, elapsed_ms)`；唯一 `heartbeat_obs_id`，索引 `(task_id, occurred_at desc)`。
- `ansich_task_budgets(entity_id, task_id, dimension, aggregation_scope, warning_limit, hard_limit, enforcement, source_kind, requested_value, effective_value, configured_obs_id)`；唯一 `(task_id, dimension, aggregation_scope, configured_obs_id)`。
- `ansich_task_usage(task_id, dimension, aggregation_scope, value, as_of, complete_through_ingest_seq, updated_at)`；唯一 `(task_id, dimension, aggregation_scope)`。
- `ansich_usage_contributions(task_id, source_task_id, dimension, source_obs_id, delta, as_of)`；本阶段 `task_id=source_task_id`，Phase 8 用于 inclusive rollup；唯一 `(task_id, source_task_id, dimension, source_obs_id)`。
- `ansich_active_task_read_model`，物化当前 Step/Tool、dwell、heartbeat Belief、usage、budget health和 projection status。

budget health 作为完整 Current Belief：`unknown | within | warning | exceeded`。比较所需 usage 缺失或投影落后于 lost range 时为 unknown。超过 hard limit后的 `overshoot = observed_usage - hard_limit` 是观测事实，不宣称在请求前精确阻断。

heartbeat assessor `heartbeat@1` 定期扫描 running Task：最新 heartbeat 距现在超过阈值时产生 rule Belief `stale`；它不改 Task hard control state。重新收到 heartbeat 后生成新 assertion `fresh`。dwell 从 Transition evidence time 计算，clock/transition 不完整则 unknown。

## 6. Operator API

新增：

```text
GET /api/ansich/operations/active-tasks
GET /api/ansich/tasks/{task_id}/usage
GET /api/ansich/tasks/{task_id}/budgets
```

active filters 支持 owner、Agent（Phase 7 后生效）、control state、heartbeat status、budget status、duration 和 observability health。cursor 使用 `(last_evidence_at, task_id)`，排序稳定。

每个 active item 返回：Task/Run ID、owner/thread Scope、control Belief、current Step/Tool、state dwell、heartbeat Belief、local usage、已知 budget、projection lag、lost ranges。Phase 8 前 inclusive usage 返回 `status="not_available"`，不能复制 local 冒充 inclusive。

## 7. 前端 Operator Lens

`/workspace/ansich/operations` 使用 TanStack Query：页面可见且存在 running Task 时每 5 秒 poll；无 running Task 时退到 10 秒；页面 hidden 时暂停；terminal Task detail 停止自动 poll。后端 `updated_at`/ETag 未变化时保留已有对象，避免全表闪烁。

表格列包括状态 Belief、当前动作、dwell、heartbeat age、local token/Step/Tool usage、最近 budget 状态、observability health。unknown 必须显示“证据不足”，不显示绿色健康。点击 Task 进入详情的 Overview/Budgets。

预算条只在 limit 已配置且 usage 完整时计算百分比；硬限制超出可显示 overshoot。没有 limit 显示“未配置”，usage 未知显示“不可判定”。

## 8. TDD 测试矩阵

- heartbeat：长 Tool 无 stream event仍发出、terminal 后停止、interrupt、shutdown、ownership change、queue loss。
- usage：provider 完整/部分/无 usage、retry attempt、重复 response、Step/issued/executed 独立计数、clock jump。
- budget resolution：default/override/clamp、local/inclusive、shadow enforcement false、无配置。
- projection：贡献幂等、lost range 导致 unknown、晚到 token usage、terminal 后 absolute breach仍保留。
- heartbeat/dwell belief：fresh/stale/recovery、unknown transition、wall clock 边界。
- API：filters/cursor、not_available inclusive、projection lag、管理员权限。
- frontend：动态 polling、hidden page pause、unknown/未配置/overshoot、terminal detail 停 poll。
- fail-open：heartbeat/usage writer 故障不影响 Run 和现有 TokenBudgetMiddleware enforcement。

## 9. 完成条件

- 长时间无 LangGraph 输出的 ToolCall 仍能通过 outer heartbeat 证明 worker liveness。
- 所有 Usage 维度独立可查，重复 Observation 不重复计数。
- Budget 显示 effective source、scope、enforcement 和 overshoot。
- 缺 heartbeat、缺 usage 或投影有 loss 时展示 rule/unknown，不篡改 hard control state。
- Operator 页面轮询行为有界且不会对 terminal Task 永久轮询。
