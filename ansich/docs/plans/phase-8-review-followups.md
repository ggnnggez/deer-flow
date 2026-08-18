# Phase 8 代码评审跟进项

来源:commit `79cd13b1`(子 Agent Task 树与 inclusive usage)的代码评审(2026-07-20)。编号带 `M`(中)/`L`(低)优先级;修复一项后同步更新总览表和该项"状态"行,保留原始诊断记录。

## 状态总览

| 编号 | 摘要 | 状态 | 修复时间 | Commit |
| ---- | ---- | ---- | -------- | ------ |
| M1 | `wall_time_ms/local` 由 `_project_heartbeat` 与 `_project_usage` 双写者共同拥有,职责重叠 | ✅ 已修复(2026-08-19,本次变更待提交) | 2026-08-19 | 本次变更待提交 |
| M2 | heartbeat 每 tick 落一条持久 wall_time contribution,叠加 recompute-per-insert 的 summary 刷新,长任务写/读放大随 tick 平方增长 | ✅ 已修复(方向 ①,2026-08-19,本次变更待提交) | 2026-08-19 | 本次变更待提交 |
| L1 | `_aexecute` 吞掉 `asyncio.CancelledError` 且不 re-raise | ⬜ 未修复 | — | — |
| L2 | `get_task_tree` 每节点 5 查询各自开 session,大树 N+1 | ⬜ 未修复 | — | — |

## M1. `wall_time_ms/local` 有两个投影写者

- 状态:✅ 已修复(2026-08-19,本次变更待提交)。删除 `_project_heartbeat` 中更新 `AnsichTaskUsageRow(wall_time_ms, local)` 的分支(连同其不再需要的 `ingest_seq` 入参),该 projector 现在只写 `ansich_task_heartbeats` 行;`_refresh_usage_summary` 成为 wall_time summary 的唯一写者。等价性依据:`ObservationEnvelope` 对 `task.heartbeat` 的校验(`contracts.py:289-291`)与 `usage_contributions_for_observation`(`usage.py:81-84`)使用同一谓词(非 bool 的 `int` 且 `>= 0`),因此每条合法 heartbeat 必然产出一条 `wall_time_ms` contribution,被删分支的 `max` 结果恒不超过 contribution 模型的 max-per-source-then-sum,值不变。回归测试(`backend/tests/ansich/test_sql_heartbeat.py`):① `test_heartbeat_projector_alone_does_not_maintain_wall_time_summary` 用 monkeypatch 把 `task.heartbeat` 从 `_PROJECTOR_KINDS["task-usage"]` 摘除(即"关闭 usage projector"),断言 heartbeat 证据行照常写入而 summary 行不存在;② `test_wall_time_summary_is_written_only_from_usage_contributions` 让完整管线跑一条 occurred_at 晚于末次 heartbeat 的终态 `budget.consumed` wall_time,断言 summary 的 value/as_of/watermark 等于直接从 `ansich_usage_contributions` 算出的 contribution 模型结果(修复前 heartbeat 写者会把 `as_of` 回退到自己的 occurred_at)。
- 位置:`backend/packages/harness/deerflow/ansich/persistence/sql.py::_project_heartbeat`(task-heartbeat projector,conditional `usage.value = max(existing, elapsed)`)+ `::_refresh_usage_summary`(task-usage projector,`usage.value = <recompute>` 无条件赋值)。`task.heartbeat` 现同时属于 `_USAGE_PROJECTION_KINDS` 与 `task-heartbeat` 两个 projector kind 集(sql.py:220/242),因此每条 heartbeat 观察生成两个投影 job,分别写同一 `AnsichTaskUsageRow(task_id, "wall_time_ms", "local")` 行。
- 现状:Phase 8 把 wall_time 纳入 contribution/summary 模型后,`_project_heartbeat` 里那段直接更新 `AnsichTaskUsageRow` 的代码已经冗余——local wall_time 的权威来源应当只有 `_refresh_usage_summary`(它按"每 source 取 max 再跨 source 求和"计算)。当前两条路径都写这一行:单 worker 下 task-usage 优先级(索引 3)高于 task-heartbeat(索引 5),usage job 先按 ingest_seq 消化、contribution 单调累积,`_refresh_usage_summary` 看到的集合单调增长,值单调不降;`_project_heartbeat` 随后的 max 也不下降,因此**当前单 worker 收敛一致、无 active bug**。风险在于:① 两个 projector 同时"拥有"同一投影行违背本阶段"contribution 单一事实源"的设计;② `_refresh_usage_summary` 是无条件赋值而非 max,一旦多 worker(Phase 11)交错或将来有人改动其语义/顺序,两写者可能静默分歧;③ 它是易被误读的死代码。
- 方向:删除 `_project_heartbeat` 中更新 `AnsichTaskUsageRow(wall_time_ms, local)` 的分支,让 wall_time 的所有 summary 只由 `_refresh_usage_summary` 拥有;`_project_heartbeat` 只保留写 `ansich_task_heartbeats` 行。配"关闭 usage projector 后 heartbeat 不再单独维护 wall_time summary""两条路径产出同一权威值"的回归测试。
- 归属:Phase 11(多 worker/生产隔离)前完成——多 worker 落地前必须收敛到单一写者,否则交错会真的产生分歧。

## M2. heartbeat wall_time 的写/读放大

- 状态:✅ 已修复(方向 ① / 裁决 HR1,2026-08-19,本次变更待提交)。wall_time 现按 max 型高水位通道存储:heartbeat 来源的 `wall_time_ms` contribution 对每个 `(aggregate_task_id, source_task_id)` 只保留一行,新 tick 仅在抬高水位时替换该行,不再每 tick 追加。方向 ②(sum 维度的通用增量刷新)按 HR1 留待 Phase 11。
  - **存储形态决策(HR1 只固定语义、不固定存储)**:复用 `ansich_usage_contributions`,不新建水位表。理由是消费端零改动即可保持语义——`_refresh_usage_summary`、`_assess_absolute_limits_at`、`get_task_usage_breakdown`、`_assess_budget_rows`、rebuild 删除清单全部已经按"每 source 取 max 再跨 source 求和"读该表,把 N 行压成 1 行不改变任何一处的结果;新建表则要同时改这五处并做并集读,风险更大而收益为零。写入侧新增 `_store_usage_contribution`(按 `high_water` 分派)与 `_upsert_high_water_contribution`(读取该 pair 的 heartbeat 来源行,按 `(delta, as_of, source_obs_id)` 字典序比较,仅在严格增大时 delete+insert)。max 可交换、幂等,因此乱序 tick 与 `rebuild_projections()` 收敛到同一行。
  - **对 RFC 幂等键的偏离(需留档)**:RFC 的 `(source_obs_id, dimension)` 幂等键论证针对 sum 型维度——每条观察贡献一个独立增量,行不可变才不会重复计数。wall_time 是 max 型(每 tick 重报累计值),重复计数本就不成立,幂等由 max 保证而非由行不可变保证;因此该表对 `task.heartbeat` 来源的 wall_time 行不再是 append-only。主键 `(aggregate, source, dimension, source_obs_id)` 不变,被支配的历史行由迁移 `0024` 删除。语义声明集中在 `ansich/usage.py::MAX_TYPE_USAGE_DIMENSIONS` 与 `::HIGH_WATER_USAGE_KINDS`(框架无关层),而不是散落在 SQL 层的字符串比较里。
  - **终态 wall_time 不受影响**:`budget.consumed` 的终态 wall_time 每个 Task 只有一条(来自 Task 单调时钟),仍走原有的不可变 contribution 行,因此 `_assess_absolute_limits_at` 的"终态贡献与最新 heartbeat elapsed 取 max、并保留两条证据路径"语义逐字保留(`test_sql_alerts.py::test_sql_terminal_wall_time_breach_keeps_final_interval_after_last_heartbeat` 与新增的 `test_sql_heartbeat.py::test_terminal_wall_time_keeps_its_own_row_beside_the_heartbeat_high_water_mark` 双向锁定);`test_sql_budget.py` 未做任何修改且保持绿色。顺带把 `_assess_absolute_limits_at` 中"取全部 heartbeat 行再取第一条"的查询加上 `.limit(1)`(行为等价,消除同一路径上另一处 O(N) 读放大)。
  - **as_of 不变量**:summary 的 `as_of` 仍等于喂给它的最新 wall_time 证据时间(heartbeat 水位行的 as_of 与终态 contribution 的 as_of 取 max)。被支配但更晚的终态贡献保留独立行,正是为了不丢这个 provenance(见 M1 的 `test_wall_time_summary_is_written_only_from_usage_contributions`,该用例只把行数断言 3 改为 2,值/as_of/watermark 断言原样保留)。
  - **已知取舍(方向 ① 的固有代价,留档)**:不再保留 per-tick 历史,因此"某个旧 evidence watermark 时刻的 elapsed 是多少"不再可答。local 作用域无影响——`_assess_absolute_limits_at` 另有 `ansich_task_heartbeats` 全量 tick 证据路径,按 watermark 取 max 精确复原;仅 inclusive 作用域在"祖先的 assessor job watermark 低于后代水位行所属观察"的少见时序下会漏计该后代(读到 0),表现为**偏低**而非误报,且下一次更高 watermark 的 assessor job 与周期性 `_assess_budget_rows`(读 summary,精确)都会立即纠正。要做到精确需按 watermark 扫整棵子树的 heartbeat 行,那恰好会把本项要消除的读放大搬到另一张表上。
  - **退化态(承接 M1 的单一写者取舍,留档)**:usage projector 持久失败而 heartbeat projector 成功时,wall_time summary 不存在(unknown)——本次改动不改变这一点。M1 之后 `_refresh_usage_summary` 是 wall_time summary 的唯一写者,因此不再有"heartbeat 写者兜底"的第二条路径;这是"单一事实源"换来的可观测性代价,由 projection health / failed-job 面板暴露。
- 位置:`backend/packages/ansich/ansich/usage.py::usage_contributions_for_observation`(`task.heartbeat` 现返回一条 `wall_time_ms` contribution,`source_obs_id=heartbeat.obs_id` 每 tick 唯一)+ `sql.py::_project_usage`(对 `(source, *ancestors)` 每个 aggregate 各 insert 一行)+ `::_refresh_usage_summary`(每次 insert 后全量重扫该 aggregate/dimension 的所有 contribution)。
- 现状:Phase 5 的 heartbeat 只对单行 `AnsichTaskUsageRow` 做 O(1) 的 max 更新;Phase 8 改为每个 heartbeat tick 落一条持久 `ansich_usage_contributions` 行,并按 ancestry fan-out 到每个祖先。一个等待子任务的长活 parent(默认 10 秒心跳)每小时 360 tick,×(1+祖先数)条 wall_time 行;`_refresh_usage_summary` 又在每次 insert 时全量重算该 aggregate 的 wall_time(max-per-source-then-sum),于是 parent inclusive wall_time 的刷新是 O(H²)。同样的 recompute-per-insert 模式作用于 token/step/tool 维度的 fan-out:parent inclusive 每收到一条子贡献就全量重扫所有子贡献,总代价 O(N²)(N=贡献总数)。对 v1(短任务、单层树、admin-only、lazy 读)可接受,但心跳频繁、parent 可长期挂起等待子任务,这是明确的扩展性悬崖。
- 方向(择一或组合):① wall_time 不进 per-tick contribution 行——heartbeat 仍走单行 high-water-mark(把 wall_time 视为 max-型维度而非 sum-型 delta,inclusive 侧单独按 source 汇总各自的 water-mark),避免每 tick 落行;② `_refresh_usage_summary` 从"全量重算"改为增量(对 sum 维度做 `+= delta`,对 wall_time 维度维护 per-source 的当前 max 并只在超过时调整总和),消除 recompute-per-insert;两者都需配"贡献数增长时刷新工作量不呈平方"的性能护栏测试(参考 P5-M1 的 SQL 监听回归写法)。**已按 HR1 落地 ①;② 留待 Phase 11。**
- 迁移:`0024_ansich_wall_time_watermarks`(chains from `0023_ansich_evaluations`)。纯数据迁移、无 schema 变更:按与投影器同一套 `(delta, as_of, source_obs_id)` 全序,删除被严格支配的 heartbeat 来源 wall_time 行,每个 `(aggregate, source)` 只留水位行;终态 `budget.consumed` 行与所有 sum 型维度不动。因所有消费端都以 max 归约同一 `(aggregate, source)`,删除非最大行不改变任何读出值,故 `ansich_task_usage` summary 刻意不重写。upgrade 以 inspector 守卫建表缺失并可重复执行(0016/0023 先例);downgrade 结构上为 no-op——被删的是可重建的投影产物而非源事实,heartbeat 观察原样保留,`rebuild_projections()` 会按当时运行的代码版本重新生成(与 0019 downgrade 先删派生行的处理同源)。
- 归属:Phase 11 前完成(与 M1 同批治理 wall_time 通道);load test 前若发现 parent 挂起时间长可提前。

## L1. `_aexecute` 吞 `CancelledError` 不 re-raise

- 状态:⬜ 未修复。
- 位置:`backend/packages/harness/deerflow/subagents/executor.py::_aexecute` 的 `except asyncio.CancelledError:` 分支(设置 `try_set_terminal(CANCELLED)` 后正常 `return result`,不 re-raise)。
- 现状:吞掉 `CancelledError` 是 asyncio 反模式。此处**当前被架构兜住**:超时路径先 `try_set_terminal(TIMED_OUT)`(first-writer-wins),取消经 `run_coroutine_threadsafe` 的 `concurrent.futures.Future`,终态由 first-writer 决定,所以吞掉不会把 TIMED_OUT 覆盖成 CANCELLED;child Ansich 终态也据此正确映射。因此不是 active bug,但不 re-raise 会让协程被取消后仍以"正常返回"结束,后续若有人把 `_aexecute` 直接置于 `asyncio.wait_for` 或依赖取消传播的上下文,会被静默破坏。
- 方向:在设置终态并完成 Ansich 收尾后 `raise`(重新抛出 CancelledError),或在注释中显式记录"此处 deliberately 吞取消,终态由 first-writer 保护"的契约与前提。配"取消后终态为 first-writer 且资源已清理"的回归测试。
- 归属:随 subagent 执行路径下次改动顺带处理;非阻塞。

## L2. `get_task_tree` 每节点 N+1

- 状态:⬜ 未修复。
- 位置:`backend/packages/ansich/ansich/service.py::get_task_tree::load_node`(每个节点并发 `gather` 五个查询——`get_task`/`get_task_agent_release`/`get_task_heartbeat_belief`/`get_task_usage`/`list_steps`——各自 `async with self._session_factory()` 开独立 session)。
- 现状:节点数受 depth(硬上限 32)与树宽约束,admin-only、点击后 lazy 加载,当前可接受。但深/宽树下是 5×N 次查询、N 次 session 建立;与 P1-F5(`list_tasks` N+1)同类模式,规模更大时放大。
- 方向:为 tree node 增加批量装配路径(按 node_ids 一次性取回 task/release/heartbeat/usage/current-step 的批量查询),或复用 active-task read model 的物化数据;配"tree 查询次数按节点批量而非按节点线性增长"的护栏。
- 归属:Phase 6 之后的 Operations 性能迭代顺带处理;非阻塞。

## 评审中确认无需跟进的点(留档)

- **确定性 child 身份**:`task_tool.py::_ansich_child_task_id = sha256(namespace:parent_task_id:spawning_tool_call_id)`,重复 attempt(同 tool_call_id)得到同一 child_task_id;`_project_task_spawn` 对已存在且 parent 不同的 spawn 拒绝,同 parent 幂等返回——满足"重复 attempt 不产生第二个 child"。
- **单 parent 与环防御**:`ansich_task_spawns.child_task_id` 为主键(一个 child 一个 parent);`_project_task_spawn` 三重环检查(parent≠child、ancestry(child,parent) 存在、child 的后代含 parent);`ansich_task_ancestry` 有 self-free 与 depth>0 的 CHECK 约束;复合 FK 保证 spawning Step/Tool 确属 parent Task。
- **无双计的 usage fan-out**:唯一键 `(aggregate_task_id, source_task_id, dimension, source_obs_id)` + `ON CONFLICT DO NOTHING`;只有 self 行(`aggregate==source`)被 fan-out 到祖先,source 归属保留,重放/late spawn/late usage 三种顺序收敛同值;`tool_calls_executed` 的 ToolCall-subject 去重在 fan-out 前生效,重复 tool.* 观察整条跳过。
- **乱序边的传递闭包**:incremental closure 读取现有 ancestry 行,中间边后到也能正确扩展;`_backfill_spawn_usage` 只 fan-out descendant 的 self 贡献,避免指数膨胀。
- **预算评估 wall_time 无双计**:`_assess_absolute_limits_at` 对 local wall_time 取 `max(contribution 派生值, 最大 heartbeat elapsed)`(P6-L3 的 max 语义保留),inclusive 纯由 per-source max 求和,未在 heartbeat 与 contribution 间相加。
- **`both` 方向 sibling 隔离**:`list_task_tree_spawns` 用 `node_depths`(自身+在预算内的祖先/后代)双端过滤边,共同 parent 下的 sibling(既非祖先也非后代)被 `child_task_id.in_(node_ids)` 排除;service 层 node_ids 以 `{task_id}` 起始,孤立 root 仍出现;单 parent 树保证在预算内每个非 root 节点经其 parent 边被覆盖,截断边界节点出现、其被裁子节点缺席且 `truncated=True`。
- **超时/取消映射**:child terminal 由 `SubagentStatus → {success/error/timeout/interrupted}` 映射;executor 在 child ID 已分配但构造/启动失败时以 `failure_reason=executor_start_failed` 关闭 child,不残留在 created;child context 创建/写入/release 绑定失败全 fail-open,不改变委派业务结果。
- **fail-open 边界**:`_create_child_ansich_context` 与 `_record_child_ansich_degradation` 显式吞异常;parent ToolCall 在 child context 初始化失败时记 `observability.degraded`,委派照常继续。
- 迁移 `0019_ansich_task_tree_usage` 幂等建表/加唯一约束、`task_id→aggregate_task_id` 重命名、历史 local→inclusive self summary 回填、清空旧 read model 让其按新 JSON 契约重建;downgrade 先删 fan-out/inclusive 派生行再反向重命名。本阶段无新 config 字段,无需 bump config_version。
- `tests/ansich` 286 项 + `test_subagent_executor`/`test_task_tool_core_logic`/`test_sql_task_tree` 133 项在评审机复跑通过;测试矩阵覆盖计划 §9 的 context propagation、identity/relation/cycle/late relation/两层树、probes、release/scope、local/inclusive/late backfill/replay、cancellation、API/root_only、fail-open。

## 计划测试矩阵缺口(随修复补齐)

- M1:✅ 已补齐(2026-08-19)——`test_sql_heartbeat.py::test_heartbeat_projector_alone_does_not_maintain_wall_time_summary`(usage projector 关闭后 heartbeat 不单独维护 wall_time summary)与 `::test_wall_time_summary_is_written_only_from_usage_contributions`(summary 等于 contribution 模型的权威值)。
- M2:✅ 已补齐(2026-08-19)——`test_sql_heartbeat.py::test_wall_time_refresh_work_per_tick_does_not_grow_with_tick_count`(SQL 监听护栏:每 tick 触及 `ansich_usage_contributions` 的语句数恒定,且刷新扫描集恒为 1 行,累计工作量线性而非平方)、`::test_heartbeat_ticks_keep_one_wall_time_high_water_row_per_source`(N tick 后每个 `(aggregate, source)` 恰好 1 行,含 ancestry fan-out,local/inclusive 值不变)、`::test_out_of_order_heartbeats_converge_on_the_wall_time_high_water_mark`(乱序 + `rebuild_projections()` 重放同一行)、`::test_terminal_wall_time_keeps_its_own_row_beside_the_heartbeat_high_water_mark`(终态与 heartbeat 两条证据路径均保留)、`::test_wall_time_watermark_migration_collapses_historical_per_tick_rows`(历史行折叠、终态/sum 维度不动、可重复执行)。
- L1:取消后终态 first-writer 且资源清理完成。
- L2:tree 查询次数按节点批量而非线性增长。
