# Phase 1 代码评审跟进项

来源:commit `49ae9791`(Phase 1 纵向切片)的代码评审(2026-07-17)。其中两个正确性问题已在 commit `78338909` 按 TDD 修复(`RunStatus.timeout` 终态映射缺失、投影收敛超时被记为假丢失);本文件登记其余跟进项,防止在 Phase 2+ 推进时遗失。

每一项标注建议归属阶段。归属 Phase 11 的项目不是新需求,而是把评审发现的具体代码位置挂到 Phase 11 既有条目下,实现时必须一并处理。

## F1. `flush_task` 超时会破坏性丢弃队列观测(设计决策待确认)

- 位置:`backend/packages/ansich/ansich/service.py::flush_task` 的 `TimeoutError` 分支。
- 现状:持久化开始前超时(例如 writer 正持锁处理慢批次)时,该 Task 尚在队列中的观测会被取走并记为丢失;但后台 writer 本可稍后正常持久化它们,慢 flush 被转化为真实数据丢失。
- 待决策:这是有意的确定性语义(terminal 查询一致性优先),还是应改为"记录延迟、保留队列项"。Phase 11 §2 已定义 `flush_task` barrier 以 collector sequence 为界并返回 `{persisted_through, lost_ranges, timed_out}`,实现该条目时必须显式回答本问题并写入设计文档。
- 归属:Phase 11(Collector 与 BatchWriter 加固)。

## F2. `_lost_ranges` 无上限内存增长

- 位置:`backend/packages/ansich/ansich/service.py::_record_loss`。
- 现状:存储长期不可用时,多 producer 交错会打断区间合并,每条观测生成一个 `LostRange`;列表无 cap,`get_health()` 每次全量复制返回。`AnsichHealth.range_known` 字段已预留但恒为 `True`。
- 方向:为丢失账本加 cap + 溢出计数;溢出后置 `range_known=False`,读取方按 Phase 11 §4 的 unknown lost range 语义解释。
- 归属:Phase 11 §4(Watermark、lag 与 lost range)。

## F3. 多 Gateway 实例下的写入竞态产生假丢失

- 位置:`backend/packages/harness/deerflow/ansich/persistence/sql.py::persist_and_project`。
- 现状:去重是 SELECT-then-INSERT;两个进程并发写同一 `(producer_name, instance_id, source_event_id)` 会触发唯一约束 IntegrityError → 整批回滚并被 service 记为 storage_failure/丢失(假丢失)。`AnsichProjectorVersionRow` 插入同理。另外 SQLite 上 `with_for_update(skip_locked=True)` 是 no-op,claim 互斥仅靠单进程 persist/projection lock。
- 方向:捕获 IntegrityError 按"并发已写入"处理(重查后跳过),或改用 `INSERT ... ON CONFLICT DO NOTHING`;Phase 11 §3 的 PostgreSQL 多 worker claim 事务落地时,双 worker 竞争测试必须覆盖 ingest 去重竞态,而不仅是 projection lease 竞态。
- 归属:Phase 11 §3(Projection lease 与多 worker);在此之前文档保持单实例假设。

## F4. projector 执行顺序依赖字母序巧合

- 位置:`sql.py::_claim_projection_job` 的 `order_by(ingest_seq, projector_name.desc())`。
- 现状:`"task-structural" > "task-control"` 的字符串降序恰好使 structural 先于 control 执行;`_project_control` 自带 `_project_structural` 兜底掩盖了脆弱性。新增第三个 projector(Phase 2 的 Step projector 即会触发)时这个隐式排序会悄悄失效。
- 方向:在 `_PROJECTORS` 注册表和 `ansich_projection_jobs` claim 排序中引入显式优先级(注册顺序或 priority 列),并加一条"新增 projector 不破坏既有顺序"的测试。
- 归属:Phase 2 前置(登记为 Phase 2 计划的实施前提)。

## F5. `list_tasks` N+1 查询,前端轮询放大

- 位置:`sql.py::list_tasks`(先查 summary 拿 id,再逐个 `get_task`,每个新开 session、3-4 条查询);router 允许 `limit=500`,前端 Operations 页每 5 秒轮询 `limit=100`。
- 现状:admin-only 且默认禁用,当前可接受;但 Phase 5(活动任务、心跳)会提高列表读取频率与字段量,届时线性放大。
- 方向:改为 summary/assertion/evidence 的 join 一次取回(TaskView 所需字段已全部在投影表中);顺带处理 `get_task` 对个别 id 返回 `None` 时页长短于 limit 的游标边缘情况。
- 归属:Phase 5(活动任务、心跳与预算)之前完成。

## F6. 每请求多次 `get_health()`(次要)

- 位置:`backend/app/gateway/routers/ansich.py`(`_ensure_queryable` + 响应体 `projection_status` 各调一次,部分路由三次)。
- 现状:每次调用持线程锁并复制全部 lost_ranges;与 F2 叠加时开销放大。
- 方向:每请求取一次 health 快照复用。可与 F2 或 Phase 11 §9 的 health endpoint 扩展一并处理。
- 归属:随 F2 或 Phase 11 §9 顺带处理。

## F7. `rebuild_projections` 与后台 projector 并发认领导致重建结果不确定(测试间歇失败)——已修复

> 已按 TDD 修复:重建入口上移到 `AnsichService.rebuild_projections()`,持 `_projection_lock` 后再委托 backend;新增互斥契约测试(可控 fake backend 证明重建窗口内无后台投影),SQL 重建测试改走 service 入口并连跑 12 次稳定。以下为原始诊断记录。

- 位置:`sql.py::rebuild_projections` 与 `AnsichService._projector_loop` 的交互。
- 现状:`rebuild_projections()` 直接调用 backend 自身的 `project_pending`,绕过 service 的 `_projection_lock`;服务运行中触发重建时,两个认领者并发处理同一批重置的 job(SQLite 上 `FOR UPDATE SKIP LOCKED` 是 no-op)。两者可同时读到同一 current belief 快照并各自通过 `should_select_control_candidate`,后提交者覆盖先提交者——可观测为 `completed` 被 `running` 回写。`tests/ansich/test_sql_task_lifecycle.py::test_projection_tables_can_be_rebuilt_from_durable_observations` 因此以约 30% 概率间歇失败(已在 merge 前的 commit 复现,属 Phase 1 存量问题,非合并引入)。
- 方向:重建入口上移到 service 层(新增 `AnsichService.rebuild_projections()`,持 `_projection_lock` 后再委托 backend),或 backend 内部为 claim/replay 提供互斥;修复必须附带一条"服务运行中重建仍确定性收敛"的回归测试。
- 归属:立即修复(它使 Phase 1 的重放验收项和 CI 均不可靠),与 F3 的多实例 claim 互斥同根,但单进程内即可复现。
