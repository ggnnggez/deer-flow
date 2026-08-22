# Phase 11 — 生产韧性、重放与保留策略

## 1. 交付目标

本阶段把此前单进程可运行链路加固为生产可运维系统：bounded queue 的损失可见、BatchWriter 具备清晰原子性、projector 支持 PostgreSQL 多 worker lease、poison job 隔离、projection 可按版本重放、payload/structure 独立 retention、raw read 强审计。

Fail-open 不等于静默失败。任何不能采集、持久化或投影的区间都要进入 health/lost ranges；读取方不得把 lost range 中的 absence 解释为“没有发生”。

> **交付拆批**：本阶段分三批交付——**A**（§2 写侧加固 + F10-7，已落地）、**B**（§3/§4/§9 多 worker lease、watermark、health 合并与 Alert 主题映射）、**C**（§5–§8 replay、retention、raw read 审计与关闭顺序）。每节末尾标注了它属于哪一批。

## 2. Collector 与 BatchWriter 加固

固定进程内状态机：

```text
starting -> healthy -> degraded -> recovering -> healthy
                         \-> failed
healthy/degraded -> shutting_down -> stopped
```

Collector 每个 producer instance 维持 accepted/dropped 序号、queue high-water mark、serialization failures 和 last successful flush。`record()` 仍不可阻塞；高优先级 terminal Observation 也不允许挤掉旧项目造成不可解释重排，而是正常 drop 并标范围。v1 不实现磁盘 spool/WAL，进程 crash 前未 flush 数据明确属于 known limitation。

BatchWriter 每批原子写 payload + observation + all projector jobs。对 transient DB 异常做有界指数退避且不占 Agent 调用栈；队列持续增长到 capacity 后 drop。对 schema/serialization 永久错误直接隔离该 item 并继续后续 item，避免一个 poison envelope 阻塞整个 queue。

`flush_task` barrier 以 collector sequence 为界，不要求其他 Task 全部 drain。返回 `{persisted_through, lost_ranges, timed_out}`；terminal Run 不等待超过配置 timeout。

> **实现状态：已由 P11-A 批落地**（2026-08-20，`246964e5`..`31dc9907`，含 HOTFIX-0 `ae731b18`；零迁移）。逐条语义、刻意的偏离与遗留边界见 [README.md](README.md) 的「Phase 11-A 采集与写入韧性」条目与 `backend/AGENTS.md` 的 “P11-A write-side resilience” 段。三处必须随本节一起读的偏离/边界：其一，上面那张状态图是**标称弧**，实现的钳制集是推导真正可达的 17 边闭包，图中八条边作为被钉住的子集保留——这是显式记录的 spec 偏离；其二，`recovering` 要求**事故证据**（未上报丢失或 writer 重试积压），裸队列深度不算；其三，`persisted_through` 是**连续**已持久化的最高序号，首次丢失之后即退化为事故前的前缀，必须与 `lost_ranges` 配对读。F10-7 同批结清（回执改为按 observation 状态解析的四级阶梯）。

## 3. Projection lease 与多 worker

PostgreSQL claim transaction：

1. `SELECT ... WHERE status in (pending,retry) AND available_at<=now AND lease expired ORDER BY job_id FOR UPDATE SKIP LOCKED LIMIT N`。
2. 同事务更新 `status=leased`、lease owner/expiry、attempts。
3. 每个 job 在独立或有界 batch transaction 执行 projector + read model 更新，成功标 completed。
4. 失败写 error、next retry；达到 max attempts 标 failed 并继续其他 jobs。

SQLite 遵守现有单 Gateway worker 约束，只运行一个 projector loop，不模拟 `SKIP LOCKED`。lease 过期 job 可由新 worker 领取；projector 幂等保证旧 worker 晚提交不会双写。更新 job 完成状态时带 lease owner/version compare，stale worker 不能覆盖新 lease 结果。

poison job 写 `ansich_projection_errors`，产生 `projection_failure` Alert 并把 affected Task read model 标 failed；Collector/lost-range 事实产生 `observability_degradation` Alert。两类生产者必须先定义 process-wide/unknown scope 到 Alert subject 的稳定映射，再复用 Phase 6 episode 状态机去重与恢复；不阻塞其他 Task 或后续 ingest sequence。

> **实现状态：已由 P11-B 批落地**（2026-08-20..22，`cc80a262`..`e275372c`；迁移 `0027_ansich_lease_generation`）。逐条语义见 [README.md](README.md) 的「Phase 11-B 多 worker 投影韧性与健康面」条目与 `backend/AGENTS.md` 的三段 “P11-B …”。必须随本节一起读的四点：
> 1. **`ORDER BY job_id` 被拒绝，属记录在案的偏离**。认领仍按 `(observation.ingest_seq, projector 优先级, projector_name)`——那是文档化的「同一条 Observation 内的投影优先序」，本节字面要的确定性已由这三个键给到；按 `job_id` 认领等于用插入序换掉一个语义序。
> 2. **「lease owner/version compare」实现为 `lease_generation` 代际 CAS**，不是 owner 比较：`lease_owner` 是每进程一个 `uuid4`，租约过期后同一 worker 重认领会读回自己的 id，owner-only 的 CAS 看不见这个 ABA。
> 3. **「projector 幂等保证旧 worker 晚提交不会双写」只对投影侧成立**。assessor 的评估还推进 `ansich_assessor_watermarks`，幂等修不了一个「已判过什么」的声明，所以被丢弃的完成让整条评估事务回滚（裁决 PB4）。
> 4. **两个 Alert 生产者的主体映射是 host `Scope`**，由启动期 bootstrap 观测铸造（哨兵 `ANSICH_BOOTSTRAP_TASK_ID`），与环境观测的 host Scope 收敛到同一实体；A 批那个「写不出去的未上报桶」由新 kind `observability.lost` 落盘，**行落库成功才出桶**。`projection_failure` 只覆盖投影作业（assessor 作业没有 `obs_id`，边界登记在 F10-18）。

## 4. Watermark、lag 与 lost range

分别维护：

- process-local collector health；
- DB writer watermark（每 producer persisted sequence）；
- projector watermark（每 projector/version complete through ingest sequence）；
- failed/leased/pending job counts；
- known/unknown lost ranges。

全局 watermark 不能掩盖单 Task failure。Task API 计算与该 Task 相关的 failed jobs 和 loss intersection；无法关联的 process-wide loss 标 `scope=producer/unknown`。

`lag_ms` 使用最新待投影 Observation 的 recorded_at 与当前时间；无 pending 但有 failed 时 status 仍 failed。health endpoint 合并 app.state 进程数据和数据库数据；DB 查询失败时仍返回 process-local 结果和 `database.status=unreachable`。

> **实现状态：已由 P11-B 批落地**（同上）。A 批已经落了第一项（process-local collector health）；B 批补上 per-projector 的 `(pending, retry, processing, failed)` 计数、`complete_through`、`lag_ms` 与 health 的 DB 合并，并让活动 Task 读模型改盖**全库**的连续性标记而不是本进程的水位。两处必须随本节一起读的偏离：
> 1. **projector watermark 读时计算、不落存储列**（记录在案的偏离）。语义是每 `(projector_name, projector_version)` 上未结算作业的 `min(ingest_seq) - 1`，即**连续性**标记而非最大值——一条 durably failed 的作业把它按住，这正是「这条线以下没有欠账」这句话成立的原因；一份便宜到可以随时算出来的数字，存一份副本只会漂移。`lag_ms` 取「未结算作业里 `MIN(ingest_seq)` 那一行的 `recorded_at` 与现在之差」（`recorded_at` 无索引，按它排序或过滤就是全表扫描），即本节 §7.2 的替代式。
> 2. **「无 pending 但有 failed 时 status 仍 failed」被拒绝**（记录在案的偏离）。失败作业继续读作 `degraded`，因为采纳字面会让 `failed` 从 A 批 17 边 `LEGAL_TRANSITIONS` 闭包之外的条件可达，而那个闭包的**补集**是被钉住的合并门禁。字面背后的意图（失败不被掩盖）由三处承载：权威的 `database.failed_jobs`、`degraded` 状态本身，以及以「有 durably failed 作业」为全部条件的 `projection_failure` 告警。
> 另记：health 的 DB 合并发生在**路由层**，`get_health()` 一字未动（同步、与 `record_batch` 共享一把锁、零 IO）；DB 不可达时 `database.status="unreachable"` 且块内每个数字是 `None`——**`None` 是未知，不是零**。

## 5. Versioned replay

新增 admin CLI 或内部命令模块 `deerflow.ansich.replay`，不在普通 API 暴露任意 projector 执行。命令参数：projector name/version、task/time/ingest range、dry-run、replace read models。

Replay 流程：

1. 验证 target projector 已注册且 schema 兼容。
2. 为目标 Observation 创建新 version jobs，唯一 `(obs_id, projector, version)`。
3. 若 replace，先在 transaction/maintenance lock 下清理该 version 管理的 projection rows；Observation/Payload 不删。
4. 执行并输出 counts、errors、watermark 和 determinism digest。
5. 对同 Observation 集第二次重放，read model canonical digest 必须相同。

不同 resolver/projector version 结果可并存；Current Belief/read model 通过 active version config 选择。切换 active version 应是显式管理动作并审计，不能部署代码后静默改变历史解释。

> **归属：P11-C**，未开工。
>
> **前置提醒（2026-08-22 更正，P11-B 终审 F7）：F10-26 已在 P11-B 结清，但结清的方式把这条前置的责任交给了本节的作者，不是解除了它。** 注册表里 F10-26 现在是 ✅，读者不要就此认为「重放两次 digest 相同」这条完成条件已经有保障了：选定的语义是**显式报告、不等待**——`rebuild_projections()` 返回 `RebuildOutcome(replayed, unsettled)`，`unsettled > 0` 表示这一趟返回时仍有作业没结算（依赖延迟的作业在 250ms 退避里，认领也可能被接管）。等待被否决的理由写在 F10-26 条目里（它同时持维护锁与调用方的 `_projection_lock`）。**因此完整性搬到了调用方**：本节要的确定性重放必须自己循环调用直到 `unsettled == 0`。这个循环已经落地为 `AnsichService.rebuild_until_settled(max_rounds=5)`（P11-C 第一批，`packages/ansich/ansich/service.py`）：它逐轮重新调用 `rebuild_projections()`（两把锁在轮次之间都释放，绝不在一次调用内部等待），退出条件是 `unsettled == 0` 而不是「某一轮没重放任何东西」，返回**最后一轮**的 outcome；预算耗尽是**如实报告、不抛异常**，由调用方自己判断 `.unsettled == 0`。本节的重放命令应当复用它，而不是另写一个循环。
>
> **同一条形状在 `retry_failed_projections` 上已经补齐**（P11-C 第一批）。此前它返回一个裸 `int`，只有 `re_armed` 的语义而没有 `RebuildOutcome` 那一半的「这趟还欠多少」信息；它的 docstring 是有的，而且明确记着这笔债（说这个形状「仍然欠着」并把它带到 C 批）——现在这笔债由本批结清：它返回 `RetryOutcome(re_armed, unsettled)`，`unsettled` 在重新入队**与**其驱动的重放之后再读一次整库欠账，因此一个刚被重新入队、又立刻走回依赖等待的作业会被算进去，而不是被误读成已修复；`re_armed == 0` 的短路路径同样照读，因为「没重新入队任何行」不等于「没欠任何东西」。lower-bound 的告诫与 `RebuildOutcome` 完全一致（见 `ansich.contracts.RetryOutcome`）。凡是把 retry 当成「重试完了」的完成条件，仍然必须回读失败作业计数，而不是读这两个数里的任何一个。

> **实现状态：第 1–5 步已由 P11-C 全部落地**（`deerflow/ansich/replay.py` + `replay_cli.py`，`sql.py::_replay_observation_condition` / `_validate_replace_request` / `mint_replay_jobs` / `read_model_digest`；第 3 步 `--replace` 由 T5 补齐）。本节七处必须一起读的偏离与澄清：
> 1. **目标集过滤必须带 kind 上界**（澄清，非偏离）。时间窗走 `occurred_at` 且必须与 `_PROJECTOR_KINDS[projector]` 同用，`ix_ansich_observations_kind_occurred` 才服务得了；`recorded_at` 从不读（无索引 ⇒ 全表扫描，而 Observation 表没有 retention）。因此**没有 kind 声明的 projector 不接受时间过滤**，以新的 `ReplayTargetRefusal` 成员 `time_filter_unsupported` 拒绝——今天恰好只有 `task-spawn-reconcile` 一个（它的作业由 `_project_task_spawn` 在自己的事务里入队，不按 kind 扇出）。同一处空集也让「按过滤器铸新作业」对它变成**错误**而不只是无用，所以对它的重放只重新入队既有作业、绝不铸新。
> 2. **第 2 步的写入必须同事务删除活动 Task 读模型行，且删除范围比计划字面更宽**（记录在案的偏离，RC3 + 全局约束 4）。`_is_staler_publish` 的 docstring 点名了这个形状：在当前连续性标记之下重新入队一条作业会拉低 `min(unsettled ingest_seq)`，此后每一次运维 tick 都读作更旧而被跳过，读模型永久冻结（已停止的 Task 那一半还是**静默**的）。计划把删除范围写成「目标 Observation 的 task_id 集合」，那要在标记是 per-Task 时才成立——`_refresh_active_task_read_model` 盖的是**全库**连续性标记，所以执行器删除的是两个集合的并：目标 Task，加上任何 `projection_watermark` 已经高于本次写入后新标记的行。多删一行的代价是一个 tick 的重发，漏删一行的代价是读模型停到下一次 rebuild。
> 3. **驱动循环每轮在排空之后跑一次 `assess_operations`**（澄清）。与 `_rebuild_projections_locked` 收尾同形：被重投影的 Observation 会入队 assessor 作业，而只有这一趟会结算它们；没有它，任何重放都会报告一个永远未结算的库，从而永远拿不到 digest，第 5 步的完成条件就不可达。这一趟同时重发第 2 步删掉的读模型行。
> 4. **digest 覆盖的是「该 projector 独占拥有的读模型表」**（记录在案的偏离，与 RC4 的窄化同源）。`_PROJECTOR_OWNED_TABLES` 把 rebuild 删除列表分成三类而不是按 projector 二分：独占表、多写者共享表（`ansich_entities`、Belief 三件套、Task/Scope/Relation/AgentRelease/usage）、无 projector 拥有的表（assessor 家族、告警机、operator 审计、两张作业/错误账、运维 tick 自己的读模型）。结构测试钉住三类互斥且恰好覆盖 `_REBUILD_DELETE_ORDER`。归属取**保守**读法（只有当没有第二个 projector 的分派分支能写到它时才算独占），因为多claim 一张表会让 `--replace` 连带删掉兄弟 projector 的行。代价是 `task-structural`、`task-usage`、`task-spawn-reconcile` 三个 projector 一张表都不独占（前者因为 `_project_control` 会先调用 `_project_structural`），对它们的重放**如实报告没有 digest**，而不是拿空集的哈希冒充确定性。
>
> 5. **第 3 步的 `--replace` 是 projector 粒度的整表删除，且与任何过滤器互斥**（记录在案的 spec 字面窄化，裁决 RC4）。计划写的是「清理该 version 管理的 projection rows」，而**不存在**这样的行：读模型一张表都没有 version 列，也没有指回产出它的 Observation 的来源列（50 张表，无一按 version 键控），所以删除无法像重投影那样被过滤器收窄。落地的语义是：删掉 `_PROJECTOR_OWNED_TABLES[projector]` 的整张表（按 `_REBUILD_DELETE_ORDER` 的顺序，先子后父），在 `mint_replay_jobs` 的**同一个事务、同一把维护锁**里、在重新入队**之前**执行；`--replace` 与 task/time/ingest 过滤器同用则以新的 `ReplayTargetRefusal` 成员 `filtered_replace_unsupported` 拒绝——照字面执行会清空整表却只重新推导窗口内的行，症状只是表变小了，是最坏的一种数据丢失。共享表与无 projector 拥有的表一律不碰，因此 replace **不是**一次收窄的 rebuild：它在一个仍然站着的共享区上重推一个 projector 自己的行。
> 6. **独占拥有是 replace 的必要条件而非充分条件，因此 `--replace` 只对「已被证明能复原」的 projector 开放**（T5 新增的窄化，叠在 RC4 之上，必须被复核）。缺的那条性质是：该 projector 能**只凭 Observation 流**把删掉的行放回去。`task-control` 是把这条逼出来的反例，也是它被拒的理由：它独占 `ansich_transitions`（没有第二个分派分支写它，F1 的保守规则在这里是满足的），但 `_project_control` 的 `from_value` 取自**当前 control Belief**，而 Belief 三件套是共享表、projector 粒度的 replace 既不拥有也不清理它——删完再推导，读到的 Belief 已经带着目的地值，于是把历史上的 `unknown -> created`、`created -> running` 改写成一条 `running -> running`：行数一样，历史不同。落地为 `_REPLACE_PROVEN_PROJECTORS`（今天 `task-heartbeat`、`task-budget`、`environment-projector`），其余以 `replace_restore_unproven` 拒绝并在消息里指向 `rebuild_projections()`。这个集合是**证明义务**而不是偏好：`tests/ansich/test_replay.py::TestReplaceIsDeterministic` 直接对这个集合参数化，逐个在非空行集上跑「重放 → digest → replace 重放 → digest」并断言相等，往里加一个不具备该性质的 projector 会让它变红，而不是悄悄上线一次改写。另记一笔本批**发现但未修**的既有缺陷：`_project_control` 本身不幂等——对一条已投影的 control Observation 重新投影会撞 `ansich_transitions.evidence_obs_id` 的唯一约束，所以 `task-control` 的**普通**重放今天也是坏的（rebuild 不受影响，因为它连 Belief 一起删）。
> 7. **digest 的主键审计：被铸造（`new_id()`）的主键必须同时退出哈希载荷与排序键**（F5 另一半，T5 结清）。丢掉墙钟列只在「同一行能被找到两次」时才够；主键若是每次推导都新铸的，载荷里的值会变，而它**又是 digest 的排序键**——两次 replace 会在内容与顺序上同时不一致。对全部独占表做 AST 审计后只有两处：`ansich_transitions.transition_id` 与 `ansich_context_windows.entity_id`，都不被任何其他独占表以外键引用，所以修复是局部的。落地为 `_DIGEST_RANDOM_KEY_COLUMNS`（连同墙钟列一起从载荷里剔除）加 `_DIGEST_SURROGATE_ORDER`（改按内容推导且**唯一**的列排序：分别是 `evidence_obs_id` 与 `task_id`）；`TestOwnedPrimaryKeysAreDerived` 把声明集钉在源码的 AST 答案上，并要求每个替代排序键真有唯一约束背书。附带代价一处：replace 之后旧铸主键在 `ansich_entities` 里留下一行孤儿（共享表，不该被 replace 删），无害但每次 replace 每个 Task 累积一行。
>
> 另记（第 1 步的边界）：分派链只按 `projector_name` 分支、从不读 version，所以「target 被接受」既不证明两个 version 会产出不同读模型，也不构成两版 digest 可比的依据——要比之前得先让那个分支真的区分版本。CLI 现在带 `--replace`（整表、拒绝过滤器、只对已证明的 projector 开放，见上第 5–6 条）；退出码 `0` 干净、`1` 跑完但仍有欠账、`2` 请求本身被拒（含两种 replace 拒绝）。第 5 步的确定性验收在 SQLite 与真实 PostgreSQL 上各跑一遍：后者是 `tests/integration/test_postgres_multiworker.py::test_replay_and_replace_hold_on_postgres_with_a_second_worker_live`，它在同一个脚本里覆盖 asyncpg 方言上的 digest 计算与两次一致、第二个 worker 在 mint 事务打开期间跑 `assess_operations`、重新入队那条 `UPDATE … WHERE obs_id IN (subquery)` 与活认领者的锁序（认领**空手且及时**返回，而不是阻塞或死锁），以及 `--replace` 之后的 digest 相等。

## 6. Retention 与删除

配置分离：

```yaml
ansich:
  retention:
    raw_payload_days: 7
    observation_days: 30
    structural_days: 90
    cleanup_batch_size: 500
```

owner/thread 删除是强删除：按 Scope 找到 Tasks，删除 Observation、Payload、projections、relations、read models 和 raw-read audit 中受保护引用，遵守 FK 顺序并测试无孤儿。此路径优先于时间 retention。

时间 retention 先删 raw payload body，保留 `retention_tombstone={deleted_at,policy,sha256,byte_size}`，使 lineage 仍知道曾采集。Observation retention 到期后，任何依赖它的 projection 必须删除或标 evidence expired；不能保留看似有证据却无法解释的 Current Belief。Structural retention 最后清理 Entity/Relation。

cleanup 使用小 batch、可恢复 cursor 和 DB lease，避免长事务锁住 Run 写入。SQLite/PostgreSQL 均测试。

> **归属：P11-C**，未开工。**与 A 批回执语义的耦合（必读）**：RA6 的第 3/4 档是从「库里还有没有这条 observation / 它的 job」反推回执的，因此删除一条 observation 或它的 job，会让一条**曾经活过**的行的回执答案翻成 `failed`——retention 删除必须把这条语义算进去（见 F10-25 条目末尾）。
>
> **与 B 批单调发布守卫的耦合（必读，2026-08-22 记，P11-B 终审 F7）**：活动 Task 读模型带一道单调发布守卫（裁决 PB7），基准是全库连续性标记 `complete_through`（`sql.py::_is_staler_publish`）。守卫的正确性依赖「这个标记只会上升」，而它成立**只是因为今天没有任何路径会插入一条 `ingest_seq` 低于当前标记的未结算作业**——唯一会把它拉低的动作是 `rebuild_projections()`，而 rebuild 顺带把这些读模型行整个删掉，于是基准被清成 NULL、守卫不会被冻住。**retention 侧任何"补插"形状都会破坏这个前提**：给已删/已过期区间重新建作业、按低 `ingest_seq` 回填、或任何让 `min(未结算 ingest_seq)` 下降而**不**删读模型行的动作，都会让基准永久高于此后每一轮 tick 的标记，活动 Task 读模型从此不再更新（还会静默保留已停止 Task 的行），直到一次 rebuild。要么避免这种形状，要么在同一事务里删掉受影响的读模型行。

## 7. Raw payload read 审计

所有 raw endpoint 先验证 admin 和 subject，再在同一安全流程复用既有 `operator.action_requested/succeeded/failed` Observation，令 `action_kind=raw_payload_read`；内容包括 actor user ID、payload ID、purpose、request correlation 和时间，不记录 payload 本身。拒绝请求进入安全审计日志，但不得为了记录 denied 而先读取 payload。

与普通 collection fail-open 不同，raw read 审计是安全控制：如果无法持久化 access audit，raw payload 读取 fail-closed 返回 503；metadata/inventory API 仍可读。响应加 `Cache-Control: no-store`，前端不把 raw body 放 TanStack 长期 cache/localStorage。

bulk raw export 不在 v1 范围；单次读取有 size limit 和 content disposition 安全规则。

> **归属：P11-C**，未开工。

## 8. Shutdown 与恢复

Gateway 关闭顺序：停止新 record → stop heartbeat/assessor timers → terminal/task barriers → drain writer 有界 timeout → stop claim 新 projection → 完成/释放当前 lease → close DB。每步有独立 timeout 和 health/log 结果，总时间不超过 Gateway graceful shutdown budget。

启动时：

- 扫描过期 projector leases 并重置 retry；
- 与 RunManager orphan reconciliation 结果关联，给未终态 Ansich Task 写硬/unknown evidence，不自行宣称 completed；
- 恢复 producer health，写前次无法落库的 process crash 信息仅当有外部证据，不凭空构造 lost range；
- 验证 active projector/resolver version 存在。

> **归属：P11-C**，但**已被 A 批部分预支**：A 批给 writer 的 drain 加了 `stop_drain_timeout_ms`，且它界定的是**这次尝试本身**（通过取消），所以一个卡死的存储调用扛不住 shutdown——**这只对 writer 成立**。projector join 仍是无条件、无上界的（它不持有任何行），本节要求的「每步有独立 timeout 与 health/log 结果、总时间不超过 Gateway graceful shutdown 预算」整体仍未落地。另外两处 A 批留下的诚实边界：一个自我 shield 或同步阻塞事件循环的 backend 依然能卡住 `stop()`；预算**内**完成的排空即使记了丢失也只体现在计数器上、不发警告。
>
> **B 批新增的一条（2026-08-22 记，P11-B 终审 F7）：`stop()` 不排空「未上报的进程级丢失桶」。** B 批给那个桶配了主体和 kind（host `Scope` + `observability.lost`），行**落库成功才出桶**，排空发生在 `AnsichService._drain_unreported_global_ranges` 的两个周期调用点上。`stop()` 的关停序列只排 writer、只 join projector loop，**从不调用它**——所以关停前最后一段窗口里记下的丢失范围只活在内存里，进程一走就没了，`observability_degradation` 生产者也就永远看不到它。`service.py::_drain_unreported_global_ranges` 里那句「e.g. batch C's shutdown drain」的防御性注释指的就是本节：本节要加的排空步骤是**它的第一个真实调用者**，而那个 `live` 守卫（还在增长的区间不上报）正是为它准备的。

## 9. API 与运维 UI

扩展 `/api/ansich/health`：component status、queue depth/capacity/high-water、writer success/failure、projector jobs/lag/watermarks、lost ranges、retention last run、active versions。

Operations 页面增加 Observability Health 面板。degraded/failed 时 Task 列表顶部显示全局 banner；每个 Task 仍显示自身关联状态。提供 failed job 详情和 projector/version，但 v1 UI 不直接提供“跳过 job”破坏性按钮。Replay 通过受控 CLI 运行。

> **实现状态：本节的 B 批部分已落地**（同上）。`/api/ansich/health` 的 additive `database` 块带上了 per-projector 的作业分桶、`complete_through`、`lag_ms` 与权威的 `failed_jobs`；Operations 页新增第四个透镜 “Observability”（`AnsichObservabilityHealthPanel`），它与 System 详情抽屉的分界是硬的——抽屉是**本 worker** 的进程/采集墙，面板是**全库**的答案，两个 failed-job 数从不合并、从不共用标签。degraded/failed 的全局 banner 与 per-Task 状态自 A 批起就在；failed job 详情与 projector/version 由既有的 `GET /operations/failed-jobs*` 提供，v1 仍不提供「跳过 job」的破坏性按钮。**本节仍欠的**：`retention last run` 与 `active versions` 属 C 批（§5/§6 未开工），受控 CLI 的 replay 同理。

## 10. TDD 与故障注入

- queue：capacity、高水位、跨线程、serialization poison、terminal barrier、shutdown race。
- writer：DB disconnect、deadlock/locked、partial payload failure、retry 恢复、duplicate batch。
- projector：两 PostgreSQL worker 竞争、lease 过期/stale completion、poison isolation、SQLite single worker。
- health：DB unreachable、pending lag、failed 无 pending、known/unknown loss、Task scoped intersection。
- replay：target filter、version 并存、replace、两次 digest 一致、late Observation。
- retention：payload tombstone、Observation expiry evidence、owner/thread hard delete、batch resume、FK 无孤儿。
- raw audit：admin/普通用户、audit DB failure fail-closed、no-store、oversized payload。
- shutdown/restart：有活动 Task、writer backlog、projector transaction、orphan Run reconciliation。
- performance：目标 ingest rate 下 Agent p95 延迟增量在约定预算内，队列不会无界增长。

## 11. 完成条件

- PostgreSQL 多 Gateway worker 不会重复投影或互相覆盖 lease；SQLite 明确保持单 worker。
- poison job 不会阻塞无关 Observation，并能在 health/Alert 定位。
- 相同 Observation + projector version 重放两次得到相同 digest。
- raw/structural retention 和 owner 删除均无悬空引用；payload 缺失有 tombstone。
- raw read 在审计不可用时拒绝，普通 collection 故障仍不影响 Agent。
- 进程 crash 无 durable spool 的 loss 限制在文档和 health 中明确，不宣称绝对 lossless。
