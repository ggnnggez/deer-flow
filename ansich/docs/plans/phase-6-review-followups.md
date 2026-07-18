# Phase 6 代码评审跟进项

来源:commits `565f0d01`(版本化 runaway assessor)+ `6a8b5c0a`(Alert episode 状态机)+ `3a5b4abc`(告警、干预与 Operations UI)的代码评审(2026-07-19)。编号带 `M`(中)/`L`(低)优先级;修复一项后同步更新总览表和该项"状态"行,保留原始诊断记录。

## 状态总览

| 编号 | 摘要 | 状态 | 修复时间 | Commit |
| ---- | ---- | ---- | -------- | ------ |
| M1 | assessor job 逐观察入队且每个 job 全量重扫历史,长任务评估成本 O(n²) | ⬜ 未修复 | — | — |
| L1 | 周期性 heartbeat/dwell 告警对账每秒全量加载该任务全部 episode + evidence | ⬜ 未修复 | — | — |
| L2 | operator action 卡在 `requested` 时同 Idempotency-Key 永久 409,无超时回收 | ⬜ 未修复 | — | — |
| L3 | 绝对预算评估中 heartbeat elapsed 无条件覆盖 wall_time 贡献和,终态边界可能低估 | ⬜ 未修复 | — | — |
| L4 | `observability_degradation` / `projection_failure` 告警类型已声明但无生产者 | ⬜ 未修复 | — | — |

## M1. assessor job 逐观察入队且每个 job 全量重扫历史

- 状态:⬜ 未修复。
- 位置:`backend/packages/harness/deerflow/ansich/persistence/sql.py::_assessors_after_projection`(每条相关观察各入一个 `(subject, assessor, version, ingest_seq)` job)+ `::_assess_action_repetition_at`(每 job 扫描 watermark 内全部 Step,且**每个 Step 单独发一次 tool 查询**,N+1)+ `::_assess_tool_frequency_at` / `::_assess_absolute_limits_at`(每 job 全量扫描 tool call / contribution 历史)。
- 现状:每个 `tool.issued` / `step.closed` 都为 action-repetition 和 tool-frequency 各入一个 job,每条 usage/budget/heartbeat 投影为 absolute-limit 入一个 job;每个 job 又从头重扫 ≤ watermark 的全部历史。T 次工具调用、S 个 Step 的任务,action-repetition 的累计代价约 (S+T) 个 job × (1 + S 次查询) —— 随任务活动量平方增长。中间 watermark 的评估结果会立即被更高 watermark 的评估覆盖(其存在价值只是重放确定性),但每个都被完整执行。job 逐条处理(每个独立 claim 事务 + 独立评估事务),在 1 秒 assessor 周期内以 500 个/轮消化,长任务尾部会形成持续积压。
- 方向:claim 时把同 `(subject_id, assessor_name, assessor_version)` 的更低 watermark pending job 合并/吸收进最高 watermark 的一次评估(评估语义仍严格 ≤ 最高 watermark,重放结果不变;被吸收 job 标 `superseded` 或直接完成);`_assess_action_repetition_at` 的 Step→Tool 查询改为一次 join 批量取回。配"多条 pending job 合并后单次评估、结果与逐条评估等价"与"Step/Tool 查询次数按批量而非按 Step 增长"的回归测试。
- 归属:Phase 7 前完成(Phase 7 的 release 比较会引入新 assessor,先把通道成本压平;Phase 8 子 Agent 树会放大 per-task 观察量)。

## L1. 周期性告警对账每秒全量加载 episode + evidence

- 状态:⬜ 未修复。
- 位置:`sql.py::assess_operations` 的 heartbeat 分支与 `::_assess_and_reconcile_dwell` —— 每个评估周期(1 秒)对每个 running 任务调用 `_reconcile_alerts_for_assessment` → `_load_alert_episodes`,后者加载该任务**全部** episode(含已 resolved)并逐个查询 evidence 行。
- 现状:状态未变时对账最终 no-op(`_same_alert_projection` 去重),但读代价照付:episode 数随 recurrence 累积(每个 episode 一次 evidence 查询),长任务多次 fresh↔stale 循环后,每秒的读放大随 episode 总数线性增长。与 P5-M1 修复前的"dedup 省写不省读"是同一模式,只是规模小一档。
- 方向:reconcile 只需 (a) 未 resolved 的 episode(判断 confirm/resolve)与 (b) 同 alert_key 的最大 episode 号(开新 episode 用)——改为一条聚合查询获取,而不是全量加载所有 episode 及其 evidence;evidence 行仅在实际写入时读取比较。可与 M1 的通道治理一并处理。
- 归属:Phase 7 前完成(与 M1 同批)。

## L2. operator action 卡在 `requested` 时同 key 永久 409

- 状态:⬜ 未修复。
- 位置:`sql.py::begin_operator_action` / `finish_operator_action` + `routers/ansich.py::_run_operator_action`(`existing.status == "requested"` → 409 in-progress)。
- 现状:进程在 begin(审计落库)与 finish 之间崩溃时,该 action 永久停留在 `requested`;之后携带同一 Idempotency-Key 的重试永远收到 409 "already in progress",没有 lease/超时把它判定为失败。换一个 key 可以继续操作(控制状态门槛会重新校验),所以不是功能阻断,但与"网络重试不执行两次"的设计意图相比,崩溃路径缺一个收尾:审计记录也永远缺 terminal 观察。
- 方向:给 `requested` 状态加一个保守的过期窗口(如 5 分钟,复用 projector lease 语义):过期后新请求可将其标记为 `failed`(result 注明 `stale_requested_takeover`)并允许同 key 重新执行;或在服务启动恢复时扫描孤儿 `requested` 行统一收尾。配"begin 后崩溃,重试同 key 最终可执行且审计有终态"的回归测试。
- 归属:Phase 11(生产韧性)前完成;单实例低频操作下风险有限。

## L3. 绝对预算评估中 heartbeat elapsed 无条件覆盖 wall_time 贡献和

- 状态:⬜ 未修复。
- 位置:`sql.py::_assess_absolute_limits_at`(先由 contribution 行求和得到 `wall_time_ms`,随后 `values[wall_time_key] = heartbeat.elapsed_ms` 无条件覆盖)。
- 现状:terminal 的 `budget.consumed` wall_time delta(完整 monotonic 时长)已进入 contribution 求和,但只要存在任一 heartbeat 行,该值就被最大 heartbeat elapsed **替换**而非取 max。心跳在 terminal 前停止,最后一个间隔(默认最多 10 秒)不被心跳覆盖 —— 若 wall_time 硬限恰在该窗口内被突破,terminal 后的评估会把已经 breach 的事实读回 `within`,与 usage 投影(`max` 语义)不一致,也与"terminal 后 absolute breach 事实保留"意图相悖。触发窗口窄(breach 落在最后一个心跳间隔内),但属于语义错误而非性能问题。
- 方向:改为 `values[wall_time_key] = max(contribution_sum, heartbeat.elapsed_ms)`(evidence 合并两者);配"wall_time breach 发生在最后一个心跳间隔内,terminal 后评估仍为 exceeded"的回归测试。
- 归属:立即修复(单行语义修正)。

## L4. 两个已声明的告警类型没有生产者

- 状态:⬜ 未修复。
- 位置:`backend/packages/ansich/ansich/alerts/episodes.py::AlertType`(含 `observability_degradation`、`projection_failure`)+ 前端 `types.ts` / i18n 文案。
- 现状:计划 §5 把这两类列为 Alert 类型,枚举、路由 filter 和前端文案都已就位,但没有任何 assessor 或通道产生它们 —— 投影失败与 observability 降级目前只反映在 `projection_status` / health 摘要里,不进入 Alert episode 流,operator 无法对其 ack/dismiss。属于"计划已声明、实现未闭合"的覆盖缺口,不是回归。
- 方向:二选一并留档:① 在 assessor 周期把 `health.failed_jobs > 0` / lost-range 事实转化为对应 Alert condition(经同一 episode 状态机去重);② 修订计划,明确这两类告警延后到 Phase 11 的韧性加固,同时从 filter/文案中隐藏未生产的类型,避免 operator 误以为该信号已被覆盖。
- 归属:Phase 7 前决策(不必实现,但要明确归属,避免枚举漂移)。

## 评审中确认无需跟进的点(留档)

- **签名纪律**:canonical JSON 做 NFC 归一、键排序、整值浮点折叠、-0 折叠、非有限数拒绝、NFC 冲突检测;Step 签名是排序多重集合(保留重复、忽略并行顺序);签名基于**完整**的脱敏参数体(`args_preview_json` 命名有误导,但内容是全量 secret-redacted args,红线"不含 redaction 前 secret"成立)。
- **职责分离**:tool-frequency 只开 `tool_frequency` operational Alert,绝不写 behavior;exact-repetition 与 absolute-limit 各写 `behavior_signal:*`,由 `behavior-aggregate@1.0.0` 聚合为唯一的 `Task.behavior`,避免两个 assessor 争抢同一 field。
- **Resolver**:human_override > deterministic > configured_rule > automated,同级按 `as_of`、`asserted_at`、稳定 assertion ID —— 晚 commit 的旧 `as_of` 断言不会覆盖新证据。
- **Episode 状态机**:同条件未 resolved 时 confirm 更新不新建;条件恢复 → resolved(condition_cleared);再发生 episode+1;terminal 时 `_resolve_terminal_alerts` 收尾且 terminal 任务不再开新 operational Alert;ack/dismiss 走 `workflow_version` 乐观并发(`with_for_update` + 409),workflow observation 与 event 行同事务落库。
- **Operator actions**:服务端 Ansich Task→DeerFlow Run/thread 映射校验(不信任客户端 run ID);`Idempotency-Key` 必填、前端在确认对话框会话内固定复用;requested→DeerFlow→succeeded/failed 三段审计;审计失败不阻断 runtime action 且响应返回 `audit_status=degraded`;复用既有 `RunManager.cancel(action=...)`,无新增 checkpoint 语义。
- **断言纪律保持**:P5-M2 修复未回退 —— heartbeat/dwell 断言 `value_json` 不含 age/duration,仅状态转变时新增;`_persist_assessment` 按 value/evidence/as_of 全量比较去重。
- **调度失败闭环**:assessor job 有独立 durable lease、attempt 上限、error 表;poison → `failed` 计入统一 `health.failed_jobs`,`retry_failed_projections` 同时恢复 projection 与 assessor job。
- 迁移 `0017_ansich_alerts` 幂等建表、belief assertion 列回填(legacy hash 哨兵 + fidelity→authority 映射)后再收紧 NOT NULL,downgrade 完整;`config_version` 29→30。
- `tests/ansich` 233 项在评审机复跑通过;新增告警/评估/操作测试覆盖计划 §9 矩阵的绝大部分。

## 计划测试矩阵缺口(随修复补齐)

- M1:job 合并等价性与查询次数增长率(目前无性能护栏测试)。
- L2:begin 后崩溃的孤儿 `requested` 恢复路径。
- L3:最后一个心跳间隔内的 wall_time breach 在 terminal 后保留。
- L4:决策后为所选方向补"degradation/projection 告警产生"或"未生产类型不出现在 filter/文案"测试。
