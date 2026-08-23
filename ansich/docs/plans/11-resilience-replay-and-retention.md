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

> **归属：P11-C**（**已落地**，见本节末的「实现状态」）。
>
> **前置提醒（2026-08-22 更正，P11-B 终审 F7）：F10-26 已在 P11-B 结清，但结清的方式把这条前置的责任交给了本节的作者，不是解除了它。** 注册表里 F10-26 现在是 ✅，读者不要就此认为「重放两次 digest 相同」这条完成条件已经有保障了：选定的语义是**显式报告、不等待**——`rebuild_projections()` 返回 `RebuildOutcome(replayed, unsettled)`，`unsettled > 0` 表示这一趟返回时仍有作业没结算（依赖延迟的作业在 250ms 退避里，认领也可能被接管）。等待被否决的理由写在 F10-26 条目里（它同时持维护锁与调用方的 `_projection_lock`）。**因此完整性搬到了调用方**：本节要的确定性重放必须自己循环调用直到 `unsettled == 0`。这个循环已经落地为 `AnsichService.rebuild_until_settled(max_rounds=5)`（P11-C 第一批，`packages/ansich/ansich/service.py`）：它逐轮重新调用 `rebuild_projections()`（两把锁在轮次之间都释放，绝不在一次调用内部等待），退出条件是 `unsettled == 0` 而不是「某一轮没重放任何东西」，返回**最后一轮**的 outcome；预算耗尽是**如实报告、不抛异常**，由调用方自己判断 `.unsettled == 0`。本节的重放命令应当复用它，而不是另写一个循环。
>
> **同一条形状在 `retry_failed_projections` 上已经补齐**（P11-C 第一批）。此前它返回一个裸 `int`，只有 `re_armed` 的语义而没有 `RebuildOutcome` 那一半的「这趟还欠多少」信息；它的 docstring 是有的，而且明确记着这笔债（说这个形状「仍然欠着」并把它带到 C 批）——现在这笔债由本批结清：它返回 `RetryOutcome(re_armed, unsettled)`，`unsettled` 在重新入队**与**其驱动的重放之后再读一次整库欠账，因此一个刚被重新入队、又立刻走回依赖等待的作业会被算进去，而不是被误读成已修复；`re_armed == 0` 的短路路径同样照读，因为「没重新入队任何行」不等于「没欠任何东西」。lower-bound 的告诫与 `RebuildOutcome` 完全一致（见 `ansich.contracts.RetryOutcome`）。凡是把 retry 当成「重试完了」的完成条件，仍然必须回读失败作业计数，而不是读这两个数里的任何一个。

> **实现状态：第 1–5 步已由 P11-C 全部落地**（`deerflow/ansich/replay.py` + `replay_cli.py`，`sql.py::_replay_observation_condition` / `_validate_replace_request` / `mint_replay_jobs` / `read_model_digest`；第 3 步 `--replace` 由 T5 补齐）。本节**十处**必须一起读的偏离与澄清（第 8、9 条由批终的文档收尾补上，第 10 条由批终审修复波补上）：
> 1. **目标集过滤必须带 kind 上界**（澄清，非偏离）。时间窗走 `occurred_at` 且必须与 `_PROJECTOR_KINDS[projector]` 同用，`ix_ansich_observations_kind_occurred` 才服务得了；`recorded_at` 从不读（无索引 ⇒ 全表扫描，而 Observation 表没有 retention）。因此**没有 kind 声明的 projector 不接受时间过滤**，以新的 `ReplayTargetRefusal` 成员 `time_filter_unsupported` 拒绝——今天恰好只有 `task-spawn-reconcile` 一个（它的作业由 `_project_task_spawn` 在自己的事务里入队，不按 kind 扇出）。同一处空集也让「按过滤器铸新作业」对它变成**错误**而不只是无用，所以对它的重放只重新入队既有作业、绝不铸新。
> 2. **第 2 步的写入必须同事务删除活动 Task 读模型行，且删除范围比计划字面更宽**（记录在案的偏离，RC3 + 全局约束 4）。`_is_staler_publish` 的 docstring 点名了这个形状：在当前连续性标记之下重新入队一条作业会拉低 `min(unsettled ingest_seq)`，此后每一次运维 tick 都读作更旧而被跳过，读模型永久冻结（已停止的 Task 那一半还是**静默**的）。计划把删除范围写成「目标 Observation 的 task_id 集合」，那要在标记是 per-Task 时才成立——`_refresh_active_task_read_model` 盖的是**全库**连续性标记，所以执行器删除的是两个集合的并：目标 Task，加上任何 `projection_watermark` 已经高于本次写入后新标记的行。多删一行的代价是一个 tick 的重发，漏删一行的代价是读模型停到下一次 rebuild。
> 3. **驱动循环每轮在排空之后跑一次 `assess_operations`**（澄清）。与 `_rebuild_projections_locked` 收尾同形：被重投影的 Observation 会入队 assessor 作业，而只有这一趟会结算它们；没有它，任何重放都会报告一个永远未结算的库，从而永远拿不到 digest，第 5 步的完成条件就不可达。这一趟同时重发第 2 步删掉的读模型行。
> 4. **digest 覆盖的是「该 projector 独占拥有的读模型表」**（记录在案的偏离，与 RC4 的窄化同源）。`_PROJECTOR_OWNED_TABLES` 把 rebuild 删除列表分成三类而不是按 projector 二分：独占表、多写者共享表（`ansich_entities`、Belief 三件套、Task/Scope/Relation/AgentRelease/usage）、无 projector 拥有的表（assessor 家族、告警机、operator 审计、两张作业/错误账、运维 tick 自己的读模型）。结构测试钉住三类互斥且恰好覆盖 `_REBUILD_DELETE_ORDER`。归属取**保守**读法（只有当没有第二个 projector 的分派分支能写到它时才算独占），因为多claim 一张表会让 `--replace` 连带删掉兄弟 projector 的行。代价是 `task-structural`、`task-usage`、`task-spawn-reconcile` 三个 projector 一张表都不独占（前者因为 `_project_control` 会先调用 `_project_structural`），对它们的重放**如实报告没有 digest**，而不是拿空集的哈希冒充确定性。
>
> 5. **第 3 步的 `--replace` 是 projector 粒度的整表删除，且与任何过滤器互斥**（记录在案的 spec 字面窄化，裁决 RC4）。计划写的是「清理该 version 管理的 projection rows」，而**不存在**这样的行：读模型一张表都没有 version 列，也没有指回产出它的 Observation 的来源列（50 张表，无一按 version 键控），所以删除无法像重投影那样被过滤器收窄。落地的语义是：删掉 `_PROJECTOR_OWNED_TABLES[projector]` 的整张表（按 `_REBUILD_DELETE_ORDER` 的顺序，先子后父），在 `mint_replay_jobs` 的**同一个事务、同一把维护锁**里、在重新入队**之前**执行；`--replace` 与 task/time/ingest 过滤器同用则以新的 `ReplayTargetRefusal` 成员 `filtered_replace_unsupported` 拒绝——照字面执行会清空整表却只重新推导窗口内的行，症状只是表变小了，是最坏的一种数据丢失。这里没有任何一条 DELETE 点名共享表或无 projector 拥有的表——但「没被点名」不等于「没受影响」：入向 `ON DELETE CASCADE` 会把删除带得更远，这正是下面第 6 条把「owned 集合对级联闭合」列为入选条件之二的原因。在那个闭包之内，replace 依然**不是**一次收窄的 rebuild：它在一个仍然站着的共享区上重推一个 projector 自己的行。同时 `mint_replay_jobs` 自己也复跑一遍 `_validate_replace_request`（复核意见 F9）：校验是纯函数、代价可忽略，而漏掉一次校验的代价是整表被清、只有窗口内的行被重推，唯一症状是表变小了——这种量级的保证应当是结构性的，而不是两个文件之间的约定。
> 6. **独占拥有是 replace 的必要条件而非充分条件，因此 `--replace` 只对「已被证明能复原」的 projector 开放**（T5 新增的窄化，叠在 RC4 之上，必须被复核）。缺的那条性质是：该 projector 能**只凭 Observation 流**把删掉的行放回去。`task-control` 是把这条逼出来的反例，也是它被拒的理由：它独占 `ansich_transitions`（没有第二个分派分支写它，F1 的保守规则在这里是满足的），但 `_project_control` 的 `from_value` 取自**当前 control Belief**，而 Belief 三件套是共享表、projector 粒度的 replace 既不拥有也不清理它——删完再推导，读到的 Belief 已经带着目的地值，`should_select_control_candidate` 直接拒掉更早的候选：删掉两条（`unknown -> created`、`created -> running`），只长回来一条（`running -> running`）——**行数更少**，而且没有一条是历史记下的那几条。落地为 `_REPLACE_PROVEN_PROJECTORS`（今天 `task-heartbeat`、`task-budget`、`environment-projector`），其余以 `replace_restore_unproven` 拒绝并在消息里指向 `rebuild_projections()`。这个集合是**证明义务**而不是偏好，且入选条件有**两条**、都已机械化。其一，*可复原*：`tests/ansich/test_replay.py::TestReplaceIsDeterministic` 直接对这个集合参数化，逐个在非空行集上跑「重放 → digest → replace 重放 → digest」，断言两个 digest 相等，并断言全库逐表行数快照不变。其二，*级联封闭*：owned 集合必须对入向 `ON DELETE CASCADE` 闭合（复核意见 F3）。一条 DELETE 的影响面不是它的语句清单：`ansich_tool_calls`（`task-step` 独占）被三张 `task-safety` 独占表、被 assessor 家族的 `ansich_scope_conclusions`、被共享的 `ansich_task_spawns` 以 CASCADE 引用，并经 `ansich_authorization_snapshots` 传递到它自己的两张子表——所以 `--replace --projector task-step` 会顺着一条归属规则**看不见**的通道删掉兄弟 projector 的行（那条规则推理的是「谁写」，不是引用级联）。第一条也抓不到它：digest 只哈希目标自己的表，被清空的 `task-safety` 依然比对相等；SQLite 更是结构上看不见这一类——`tests/ansich/conftest.py` 不开 `PRAGMA foreign_keys`，级联在那里根本不触发。由 `TestReplaceCascadeIsContained` 在 `Base.metadata` 上算传递闭包钉住。因此 `task-step` 身上有**两条互相独立的否决理由**：上述级联，以及（报告 §3）它多处投影会在共享表 `ansich_steps` 的既有行上短路——两者都不是「把 fixture 补齐」能解决的。往里加一个不具备这些性质的 projector 会让相应检查变红，而不是悄悄上线一次改写。另记一笔本批**发现但未修**的既有缺陷：`_project_control` 本身不幂等——对一条已投影的 control Observation 重新投影会撞 `ansich_transitions.evidence_obs_id` 的唯一约束，所以 `task-control` 的**普通**重放今天也是坏的（rebuild 不受影响，因为它连 Belief 一起删）。它登记在 `_NON_IDEMPOTENT_PROJECTORS`，CLI 在开跑前和「这趟还欠账」的报告旁各打一次 stderr 警告：退出码 `1` 读起来像临时积压，而操作者顺手的两个补救（再跑一次、`retry_failed_projections`）都会撞回同一处，永远清不掉。是警告不是拒绝——同一条命令在那些 Observation 从未被投影过的库上是对的。
> 7. **digest 的主键审计：被铸造（`new_id()`）的主键必须同时退出哈希载荷与排序键**（F5 另一半，T5 结清）。丢掉墙钟列只在「同一行能被找到两次」时才够；主键若是每次推导都新铸的，载荷里的值会变，而它**又是 digest 的排序键**——两次 replace 会在内容与顺序上同时不一致。对全部独占表做 AST 审计后只有两处：`ansich_transitions.transition_id` 与 `ansich_context_windows.entity_id`，都不被任何其他独占表以外键引用，所以修复是局部的。落地为 `_DIGEST_RANDOM_KEY_COLUMNS`（连同墙钟列一起从载荷里剔除）加 `_DIGEST_SURROGATE_ORDER`（改按内容推导且**唯一**的列排序：分别是 `evidence_obs_id` 与 `task_id`）；`TestOwnedPrimaryKeysAreDerived` 把声明集钉在源码的 AST 答案上，并要求每个替代排序键真有唯一约束背书且 `NOT NULL`（可空的 UNIQUE 在 SQL 里不构成全序）。那次审计是**刻意的下界**，与 `TestOwnershipIsConservativeInFact` 的可达性走查同一性质：它认得本文件实际用到的两种写入形状（ORM 构造器关键字、递给 `_insert_ignoring_conflict` 的字面 dict）外加一层 `name = new_id()` 别名，因此它保证的是常见形状不会静默漂移，而不是「任何形状都溜不过去」。整套机制**今天是空转的前置保险**：两张铸键表都属于 `--replace` 拒绝的 projector，没有任何一次参数化确定性检查会走到它，真正驱动它的是 `test_a_minted_key_cannot_move_the_digest`；它存在是为了 `task-step` 将来入选那天，§11 的检查不会**按构造**就坏掉。孤儿代价一处，且**当前不可达**（复核意见 F2）：两张铸键表里只有 `ansich_context_windows` 有对应的 `ansich_entities` 行——`_project_control` 铸的是裸 `transition_id`，既不建 Entity 也没有指向该表的外键——所以只有窗口 replace 会留下孤儿，而它归 `task-step` 所有、被拒绝，因此今天的代价是**零**，只有 `task-step` 入选才会变成真的。
>
> 8. **「切换 active version 应是显式管理动作并审计」落成一行数据库记录，不是配置**（记录在案的偏离，裁决 RC5）。哪个版本是权威的写在 `ansich_active_versions`（迁移 `0028`）里：配置字段只能是 startup-only 的，那与本节要的「显式的、被审计的管理动作」直接矛盾，而且会让一次部署**静默**改写历史的解释。**没有行就意味着代码默认值**，所以这张表记的是**偏离**，空表是正常状态。每次激活写一条 `operator.action_*` 审计观测（`action_type="activate_version"`，与 §7 同一族），`audit_obs_id` 是 `ON DELETE SET NULL` 的——一个过期的审计锚点应当把证据指针降级，而不是把选择退回去、也不是把一条 Observation 按在 retention 外面；旁边的 `audit_recorded` 闩把那个 NULL 读成「过期了」而不是「从来没有过」。跨 worker 的收敛靠 30s 缓存 TTL，并由存下来的 `resolver_version` 戳记让它可见。启动期校验的三种答案（未读 / 干净 / 不可执行）落进 `AnsichHealth.active_version_mismatches`（§8/§9）。
>
> 9. **第 5 步的完整性仍然在调用方手上，`execute_replay` 并没有复用 `rebuild_until_settled`**（澄清，且是上面「前置提醒」那段话的诚实结账）。上面写的是「本节的重放命令应当复用它」，实际落地不是：`execute_replay` 有**自己**的有界轮次循环（`max_rounds`，默认 5，每轮排空 `project_pending` 再跑一次 `assess_operations`），因为它每轮要做的事和 rebuild 那一趟并不一样。**代价被实测到了**：那五轮跑在同一次调用之内、彼此紧挨，而依赖延迟的作业带着 `available_at = now + 250ms`，所以一次 pass 完全可能耗尽自己的轮次仍带着 `unsettled == 1` 返回——把**单次 pass** 读成完整性，就是 F10-26 的错误升了一层楼（该条的「留观三」记了这次目击）。因此**本节的完成条件仍然要求调用方自己循环**：测试侧的 `_replay_until_settled` 是那个循环（每一趟是**独立的一次** `execute_replay`，退出条件是 `unsettled == 0` 而不是「某一轮没重放东西」，耗尽上界只报告不抛），而它比它自己的 docstring 自称的更强——新的一趟会调 `mint_replay_jobs`，其 re-pend 把每条命中选择器的**目标**作业的 `available_at` 拉到当下并清掉 `dependency_pending_since`，所以对目标作业第二趟是**结构上**清掉退避。残留要一起读：`unsettled` 是**全库**的，属于别的 projector 的未结算作业不会被下一趟 re-pend，对它们多跑几趟仍然只是在耗时间。
> 10. **重放对「证据已被 retention 拿走」这件事不再是瞎的**（批终审 B2/B4/B1 的收口，2026-08-23）。三处，各自独立：**其一**，一条 payload 被 tier 1 打成 tombstone 之后，它的 Observation 还在，于是重放照样瞄准、建作业、重臂——然后以 `completed` 结算却一行都不派生，而 `unsettled` 与 `failed` 结构上都看不见这种作业。`ReplayReport.expired_evidence` 现在数它（从 Observation 与 payload 行读，因此 `--dry-run` 也答得出来），digest 多了**第四条 gate 子句**：它非零就不算 digest 并说明理由——否则 §11 的第 3 条完成条件会把一次策略生效报成一次确定性违反，而两份报告里都没有任何东西能把它们分开。**其二**，`--replace` 在这种目标集上**直接拒绝**（`replace_over_expired_evidence`，在 mint 事务里、第一笔 DELETE 之前抛，所以库一动不动）：普通重放只是「派生不回来」，而 replace 是先清表，丢掉的行不会回来——`environment-projector` 恰好既是已证明成员、又正是本仓库文档里最常越过 `inline_payload_max_bytes` 的那一族。**其三**，`--replace` 是**第四个**「删掉 payload 最后一个引用者」的删除者（AGENTS 的那条义务只点了三个的名），因此成员资格加了**第三条机械化条件**：拥有集的级联闭包与 payload 引用表的交集必须为空，反例是 `task-safety`（它**拥有** `ansich_authorization_snapshots`，级联闭包为空 ⇒ 第二条已经放行，只差一份可恢复性证明）。另有一条读者面的修正：目标集为空时，报告现在区分「这段范围被 retention 或 owner 擦除删掉了」与「过滤器打偏了」——两者此前都只给 `targeted: 0`，而库自己答得出来（回执阶梯早就在读同样那两个删除标记）。
>
> 另记（第 1 步的边界）：分派链只按 `projector_name` 分支、从不读 version，所以「target 被接受」既不证明两个 version 会产出不同读模型，也不构成两版 digest 可比的依据——要比之前得先让那个分支真的区分版本。CLI 现在带 `--replace`（整表、拒绝过滤器、只对已证明的 projector 开放，见上第 5–6 条）；退出码 `0` 干净、`1` 跑完但仍有欠账、`2` 请求本身被拒（含两种 replace 拒绝）。第 5 步的确定性验收在 SQLite 与真实 PostgreSQL 上各跑一遍：后者是 `tests/integration/test_postgres_multiworker.py::test_replay_and_replace_hold_on_postgres_with_a_second_worker_live`，它在同一个脚本里覆盖 asyncpg 方言上的 digest 计算与两次一致、第二个 worker 在 mint 事务打开期间**提交**自己的 `assess_operations`、重新入队那条 `UPDATE … WHERE obs_id IN (subquery)` 与活认领者的锁序，以及 `--replace` 之后的 digest 相等。两处边界是刻意的、并写在测试里（复核意见 F4/F5）：认领那一半只有在对端的谓词**匹配到一行被锁住的行**时才有意义，而 READ COMMITTED 下这要求该行「重新入队之前」的版本本身可认领——所以脚本刻意留一条 heartbeat 作业停在 `pending` 不去认领，先用一次无锁读断言对端确实看得见它，再断言认领空手且及时返回（把暂停点挪到重新入队**之前**，同一次认领就会成功，这是它有牙齿的证明）；而对端的 tick 与 A 自己的活动 Task 清理是被构造顺序串起来的——暂停点落在重新入队上，它跑在 `_clear_frozen_active_task_rows` 之前——所以这个测试**没有**展示那一处争用。

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

> **归属：P11-C**（**已落地**，见本节末的「实现状态」）。**与 A 批回执语义的耦合（必读）**：RA6 的第 3/4 档是从「库里还有没有这条 observation / 它的 job」反推回执的，因此删除一条 observation 或它的 job，会让一条**曾经活过**的行的回执答案翻成 `failed`——retention 删除必须把这条语义算进去（见 F10-25 条目末尾）。
>
> **实现状态（2026-08-22/23，P11-C 的 T8/T9/T10 落地）**：本节已实现，带七处必须一起读的偏离与边界。三层按包含顺序跑在一次 pass 里（payload → Observation → structural），整趟由 `max_batches` 统一收口；被上界耗尽的那一层**根本不跑**，它的计数留 `None`——这也是 `RetentionReport` 上 `None` 现在**唯一**的含义。owner/thread 强删除是另一条路径（`hard_delete_scope`），它**优先于**时间 retention：不看任何 cutoff、任何年龄、任何 tier，因为「这位 owner 要求被遗忘」不是一句关于证据有多老的话。
>
> 1. **tier 3 的「低于 horizon」门禁被一次控制者裁定的偏离替换掉了，因为它在本 schema 上会死锁**（记录在案的偏离）。计划的字面是：tier 3 只删「整个观测区间都**低于 horizon**」的 Task 的结构行。但 `ansich_entities.discovered_obs_id` 是 NOT NULL 且**无** `ON DELETE` 动作，`ansich_tasks.trigger_obs_id` 同样，`ansich_scopes.created_obs_id` 是 `RESTRICT`——每个实体按住自己的发现 Observation，每个 Task 按住自己的创建 Observation。于是 tier 2 的**连续前缀**停在库里第一条「创建了某个 Task」的 Observation 上，horizon 永远是 `0`，而 tier 3 以 horizon 为门禁 ⇒ 两层互等。这个死锁**无条件**成立，与三个阈值的相对大小无关。落地的语义改成按**年龄资格**开闸：一个实体在「它的 Task 的**整个** Observation 区间都已老到 tier 2 可以取走」时就被解开，**不要求已经删掉**；tier 2 的 horizon 在**下一趟** pass 才走过那段被解开的前缀。于是 retention 跨 pass 收敛，界是依赖图的深度，而安全性一点没让：只要有一条 Observation 比 Observation cutoff 年轻，整个实体就被拒——一个九十天前起、至今还在发 heartbeat 的 Task 保住它的全部结构。
> 2. **「谁删掉一个 payload 的最后一个引用者，谁就拥有那行 payload」是一条本节新立的义务**（澄清，也是一处强化）。tier 1 两个方向都**拒绝**过期孤儿（这是 T9 用来关掉一次真实竞态的护栏），所以被 tier 2/3 或强删除弄成孤儿的 payload，除非它们自己回收，否则**没有任何东西**会回收它。三个删除者因此统一走 `_apply_plan_and_reclaim`，在**同一个事务**里回收。那里回收的是**删除**而不是 tombstone：tombstone 的意义是让读者分得清「按策略过期」与「丢失」，而这里通往那行的唯一路径已经和引用者一起消失了。**这条义务还多伸出一张表**：`ansich_content_blobs` 自己也是 payload 引用者，所以一个删掉最后一条 `ansich_content_blocks`、然后就停手的删除者会把 blob 连同正文一起留下——已修（登记 F10-39，那里也写清了**仍然**无界的三样：阈值以下的 `inline_body`、尚无 tier 触达的 blob 行、tier 1 留下的 tombstone 空壳）。
> 3. **tier 2 的 horizon 就是它的 cursor，`observation_cursor` 被刻意留白，然后被强删除认领走**（澄清）。删除批次与 horizon 推进在**同一个事务**里提交——两种拆法各自会在一个方向上说谎：先推 horizon 是宣称一次没发生的删除，后推 horizon 是让已删的行留在一个仍说它们欠着的 horizon 之下（即 FC-3 的翻转）。horizon 同时也是那个持久的单调位置，所以第二个覆盖同一 keyspace 的位置只会与它无声地打架。`ansich_retention_state.observation_cursor` 因此在 tier 2 这里恒为 `None`；owner 强删除**是**那个非连续删除者，它把自己的进度记在这一列上，回执那一级两列都读。
> 4. **`POST /retention/hard-delete` 是一条路由，而 §5 禁止路由**（边界，非冲突）。§5 禁的是「按需跑**任意 projector**」的端点；强删除是一个 owner 发起、效果固定的数据动作，而「删掉我的 thread」这句话没法只从 CLI 回答。本批**刻意不给它前端**：一次不可逆的擦除应当在 API 被用过之后才拿到运维控制台的入口，而不是与它同时。
> 5. **owner 擦除有两条 v1 解不掉的形状，两条都被如实拒绝**（已知限制，登记 F10-38）。(a) 一条 Observation 是**外部**某个**按类型不可删**的实体（host/workspace/sandbox/authorization/external_origin Scope、AgentRelease）的发现证据 ⇒ 取锁之后、第一笔删除之前以 `unsatisfiable_pin` 拒绝；(b) 两个各自可擦的 `owner`/`thread` Scope 的 provenance 穿过同一个 Task ⇒ 预检都过、谁都完不成，以 `blocked` 点名那条边。**v1 没有产品内补救**，三条候选修法与推荐的那条写在 F10-38 里。
> 6. **`RetentionReport.finished` 回答的是「这一趟被上界停住了吗」，不是「库里已经没有可过期的东西了」**（读者陷阱，写在此处以免第一个调用者踩上去）。跨 pass 收敛之下调用方**无论如何都要再跑一趟**：一层在一个 pin 上停住时，它自己能做的已经做完了，于是报 `True`，而下一趟仍可能有活——因为上一趟解开了什么。今天**没有任何调用者在循环**，而且更要紧的一句是：**今天没有任何代码调用 `run_retention`**（既不在 tick 里，也没有调度器入口），所以本节测过的每一种 retention 状态在生产上都还产不出来——**这条登记为 `F10-41`**，接线是下一个 retention 批次的第一件事，而 owner 强删除**不在**它的范围里（那条有路由，是可达的）。`DatabaseHealth.retention_last_run` 把上一趟带到健康块，它的 `None` 在一个可达的库上意味着**从未跑过**——这是常态而不是异常。
> 7. **「测试无孤儿」只落了一半**（边界）。有的是：一条从 `Base.metadata` 推出来的元数据钉子（每一张能**阻塞** Observation 删除的表都在 `ansich_entities` 的级联闭包之内）、逐族的行数断言、以及 PG arm——那里外键真的生效，孤儿按构造不可能。**没有**的是 SQLite 上一次通用的引用完整性走查，而 `tests/ansich/conftest.py` 不开 `PRAGMA foreign_keys`，所以一个规划器缺陷在那里会静默留下悬空行。PG arm 是更强的那份证明且它存在，因此这是一个缺口而不是一个洞。
>
> **与 B 批单调发布守卫的耦合（必读，2026-08-22 记，P11-B 终审 F7）**：活动 Task 读模型带一道单调发布守卫（裁决 PB7），基准是全库连续性标记 `complete_through`（`sql.py::_is_staler_publish`）。守卫的正确性依赖「这个标记只会上升」，而它成立**只是因为今天没有任何路径会插入一条 `ingest_seq` 低于当前标记的未结算作业**——唯一会把它拉低的动作是 `rebuild_projections()`，而 rebuild 顺带把这些读模型行整个删掉，于是基准被清成 NULL、守卫不会被冻住。**retention 侧任何"补插"形状都会破坏这个前提**：给已删/已过期区间重新建作业、按低 `ingest_seq` 回填、或任何让 `min(未结算 ingest_seq)` 下降而**不**删读模型行的动作，都会让基准永久高于此后每一轮 tick 的标记，活动 Task 读模型从此不再更新（还会静默保留已停止 Task 的行），直到一次 rebuild。要么避免这种形状，要么在同一事务里删掉受影响的读模型行。

## 7. Raw payload read 审计

所有 raw endpoint 先验证 admin 和 subject，再在同一安全流程复用既有 `operator.action_requested/succeeded/failed` Observation，令 `action_kind=raw_payload_read`；内容包括 actor user ID、payload ID、purpose、request correlation 和时间，不记录 payload 本身。拒绝请求进入安全审计日志，但不得为了记录 denied 而先读取 payload。

与普通 collection fail-open 不同，raw read 审计是安全控制：如果无法持久化 access audit，raw payload 读取 fail-closed 返回 503；metadata/inventory API 仍可读。响应加 `Cache-Control: no-store`，前端不把 raw body 放 TanStack 长期 cache/localStorage。

bulk raw export 不在 v1 范围；单次读取有 size limit 和 content disposition 安全规则。

> **归属：P11-C**（**已落地**，见下面的「实现状态」）。
>
> **实现状态（2026-08-22，P11-C T12 落地）**：本节已实现，是本批**唯一**的 fail-closed 站点，带五处必须一起读的偏离与边界。四条返回 raw body 的 admin 路由（`GET /agent-releases/{id}/manifest`、`GET /evaluations/{obs_id}/payload`、`GET /tool-calls/{id}/raw-result` 与 `/visible-result`、`GET /content-blocks/{id}/payload`）现在一律走 **admin 闸门 → subject 解析 → 落库的 requested 审计行 → 读 → terminal 审计**；这个顺序是契约不是风格：访问记录在向存储要正文**之前**提交，所以写不下它就还能拒掉这次读。爆炸半径刻意只有这一族——审计写者坏掉的库，metadata 与 inventory 路由照答，有测试钉住。
> 1. **字段名是 `action_type`，不是本节字面的 `action_kind`**（记录在案的偏离，裁决 RC8）。`raw_payload_read` 是 `ansich.operator.OperatorAuditActionType` 的第二个成员，与 T6 的 `activate_version` 并列。同一裁决还把**主体**在整族上统一了：读的东西属于某个 Task 时取那个 Task，否则取库里的 host `Scope`，再否则取 `ANSICH_BOOTSTRAP_TASK_ID`——`contracts.py` 的 envelope 校验器为此新增了一条 Scope arm，只对这一族 Literal、且只在 `task_id` 是哨兵时接受。
> 2. **审计写入是同步的后端写，从不走 `record()`**（记录在案的偏离，裁决 RC9）。collector 队列按构造是 fail-open 的——它接收、它可能丢、它在任何东西落地之前就返回——所以它在结构上无法确认持久化。写入走 `_add_observation_row`（`activate_version` 用的同一条路），而**不是** `persist_and_project`：后者的去重是**静默跳过**，而在一条审计行上静默跳过就是一个审计缺口；裸 INSERT 撞上唯一索引会抛，于是变成一次被拒的读。
> 3. **`no-store` 覆盖的是「handler 产出的每一种答案」，不是「这四条路由能给的每一种答案」**（边界，措辞更正）。两种拒绝产生在 handler 之外因此不带 `Cache-Control`：超长 `purpose` 由 FastAPI 自己的 `RequestValidationError` 处理器答 422，未认证请求由 `AuthMiddleware.dispatch` 答 401。两者都不在 RFC 7231 §6.1 的可启发式缓存集合里，所以共享缓存不会存它们；但**不变量本身不是全称的**，而 422 的响应体会回显调用方的 `purpose`、旁边就是一个点名 payload id 的 URL。
> 4. **`ansich.raw_read_max_bytes` 界的是内层文档，因此对响应只是近似界**（边界）。度量用 `json.dumps(document, default=str, ensure_ascii=False)`，两个方向各差一点：它按非紧凑分隔符计数而 Starlette 用紧凑的（**多**算），而它不含响应信封（`{"payload": …}`、release 包装、ToolCall 路由那一整块 `{role}_result`）（**少**算）。它是「单次读的正文上界」，不是一个 Content-Length 硬顶。
> 5. **未认证的探测一条审计都不写，而且也没有任何应用级日志**（边界，与本节 spec:112 的「拒绝请求进入安全审计日志」并读）。`AuthMiddleware.dispatch` 在 `call_next` 之前就返回，路由从不运行，**没有 actor 可记**，所以把 §7 的痕迹限定在**已认证**的拒绝上是诚实的读法。代价要说准：这类尝试的唯一记录是 ASGI 访问日志，它带请求路径（因而带被探测的 payload id），但不带 actor、也不带 §7 的语义；中间件自己一行日志都不写。
> 6. **§7 的审计行按 `observation_days` 过期，所以那个 knob 同时就是访问审计的保留期**（边界，批终审 B3 补记）。审计行是**普通 Observation**，retention 的 tier 2 只按年龄筛、没有 `kind`/`action_type` 谓词，所以「谁取走了原始字节」这条唯一的记录和一条 heartbeat 一样老去（默认 30 天）。**这是刻意的，且与隐私一致**：对某位 owner 的数据的一次读，其审计本身也是关于这位 owner 的数据，把它钉在 retention 之外会让审计活得比它所描述的证据更久——spec：97 对 `activate_version` 的审计锚点已经这样裁过（`ON DELETE SET NULL` + `audit_recorded` 闩），owner 强删除把审计行列为第八个删除族也是同一条原则（那条讲的是**隐私删除**，与时间保留无关，把它读成本条的覆盖是范畴错误）。要说准的是耦合：**没有 `audit_days` 这个 knob**，所以为了存储把 `observation_days` 调到 7 天，会同时把 §7 的追溯窗口缩到 7 天，校验器不反对、也没有任何日志说过这件事。30 天在此**记录在案地接受**，「审计行需要自己的下界」登记为 `F10-42` 交接线批次，而不是默认它成立;同一句话也写在 `AnsichRetentionConfig` 的 docstring 上——运维做这个决定时看的是那里。
> 另记两条本节自己的取舍:结局是一套**封闭词表**，且只有一个意味着字节过线（`served`，唯一的 `succeeded` 行）；T9a 的 tombstone 给出的 410 审计成 `failed`/`expired` 而**不是**成功——读被尝试了、存储也答了，但什么都没披露。**terminal** 那一行降级成 WARNING（requested 那一行不降级）：到那一步访问已经durably 记下了，为它拒掉响应等于把一次已服务的读报成错误、然后照样把它服务出去。

## 8. Shutdown 与恢复

Gateway 关闭顺序：停止新 record → stop heartbeat/assessor timers → terminal/task barriers → drain writer 有界 timeout → stop claim 新 projection → 完成/释放当前 lease → close DB。每步有独立 timeout 和 health/log 结果，总时间不超过 Gateway graceful shutdown budget。

启动时：

- 扫描过期 projector leases 并重置 retry；
- 与 RunManager orphan reconciliation 结果关联，给未终态 Ansich Task 写硬/unknown evidence，不自行宣称 completed；
- 恢复 producer health，写前次无法落库的 process crash 信息仅当有外部证据，不凭空构造 lost range；
- 验证 active projector/resolver version 存在。

> **归属：P11-C**，但**已被 A 批部分预支**：A 批给 writer 的 drain 加了 `stop_drain_timeout_ms`，且它界定的是**这次尝试本身**（通过取消），所以一个卡死的存储调用扛不住 shutdown——**这只对 writer 成立**。projector join 仍是无条件、无上界的（它不持有任何行），本节要求的「每步有独立 timeout 与 health/log 结果、总时间不超过 Gateway graceful shutdown 预算」整体仍未落地。另外两处 A 批留下的诚实边界：一个自我 shield 或同步阻塞事件循环的 backend 依然能卡住 `stop()`；预算**内**完成的排空即使记了丢失也只体现在计数器上、不发警告。（**本段自 T13 起是历史记录**：「projector join 无上界」「整体未落地」两句已不成立，现状见下一段；那两处诚实边界仍然成立，且第二处现在由 `ShutdownReport` 的每步 `detail` 部分补上——排空最终 charge 了多少行会写进那一步的 `detail`。）
>
> **实现状态（2026-08-23，P11-C T13 落地）**：本节已实现，带四处记录在案的偏离。
> **(1) 第七步不是 `close DB`。** engine 属于 Gateway、被多个组件共用，collector 的关停序列跑在它们之前，所以 `close_engine` 留在 lifespan 自己的最后一步；collector 的第七步换成**进程级丢失桶的排空**（下面 B 批那条），即本节唯一没有别的调用者的关停期写入。七步为
> `stop_new_records / stop_assessor_cadence / drain_terminal_barriers / drain_writer / stop_projection_claiming / join_projector / drain_unreported_loss`，每步的结果记进 `ShutdownReport`，由 lifespan 逐步打日志。
> **(2) 关停阶段不进 lifecycle 状态词表（裁决 H8-A）。** `lifecycle.py` 未改：它的 17 条合法边的**补集**是合并门禁，为了描述关停内部阶段而加词表等于拿一条已证不变量换措辞。阶段活在报告里。
> **(3) heartbeat timer 不在 collector 手里。** `AnsichTaskHeartbeat` 由 `runtime/runs/worker.py` 按 Run 起停，在本 service 之外；第二步只停 service 自己的定时器，heartbeat 的停止是 lifespan 自己的一步——在这里声称停了它，就是报告一件本代码管不着的事。
> **(4) 第六步「完成/释放当前 lease」只落了「完成」。** join 超时时 projector 被取消，而它可能正握着一个**已提交**的 claim（`status='processing'`，租约还有 `projector_lease_seconds`）；没有任何东西去释放它。这一行会以幻影 `processing` 停留最多一个租约（30s）——正是 RC12 启动扫描要清掉的形状，但**比租约更快的重启**会看到它尚未过期而跳过（`lease_expires_at <= now`），于是它得等满 TTL 才被 claim 路径的过期分支接走。不丢数据、不重复投影（CAS 仍然守着结果），代价是那一个 job 的重投最多推迟一个租约；为关停超时分支再加一条写路径不值当，故记录而不实现。
> 预算 `ansich.shutdown_budget_ms`（**5000**，startup-only，本批不再 bump `config_version`）是整段序列的墙：每步取 `min(自己的份额, 剩余)`，提前结束的把剩余让给后面，**某一步超时绝不中止后面的步骤**（否则关停最糟时丢的正是第七步要写下来的证据）。
> **这个数字是被算出来的，不是挑出来的**：本序列跑在 `langgraph_runtime` 的 `finally` 里，而它是 lifespan 最外层的上下文管理器，所以它在**所有其他步骤之后**退出——preStop 5s + channel stop 5s + browser 5s + memory flush 30s + run drain 5s = **本步开始前已经过去 50s**，而 gateway chart 的 `terminationGracePeriodSeconds` 原本是 45（其注释只算了其中三项，也就是说这笔账在本节存在之前就已经对不上）。本批把它提到 **60**，并把整张表写进 `values.yaml`、deployment 模板、chart README 和 `app.py` 自己的注释里；50 + 5 还留 5s 缓冲。**把本键调大，就必须同时调大 pod 的 grace period**：SIGKILL 落在序列中间，丢掉的正是第七步要写下的进程级丢失桶，连同那份本该说明此事的报告。一个附带后果值得知道：5s 下 writer 的份额是 2s，**低于** `stop_drain_timeout_ms` 的 10s 默认值，即默认配置下该旋钮已被预算夹住——这是诚实的方向，编排器会杀掉的 10s 承诺不如它会兑现的 2s，何况排不掉的行会被记账并由第七步写下来，而不是随进程消失。
> 启动侧：过期 lease 扫描按 `attempts` 分桶且不动 `attempts`/`lease_generation`（裁决 RC12）；active version 校验的三种答案（未读 / 干净 / 不可执行）落进 `AnsichHealth.active_version_mismatches` 加一条 typed WARNING，不崩、不改状态；orphan Run 关联写 `observability.degraded` 证据、**绝不代宣终态**（本节第 2 条）；producer health **什么都不恢复**、不凭空构造 lost range（裁决 RC13，本节第 3 条按其字面落地）。无 spool 的丢失仍然是 P11-A 起就有的已知限制，由 `dropped_count` / `lost_ranges` / `unreported_global_lost_range_count` 三个计数在进程存活期间承载，本批不新增字段重复它。

> **B 批新增的一条（2026-08-22 记，P11-B 终审 F7）：`stop()` 不排空「未上报的进程级丢失桶」。** B 批给那个桶配了主体和 kind（host `Scope` + `observability.lost`），行**落库成功才出桶**，排空发生在 `AnsichService._drain_unreported_global_ranges` 的两个周期调用点上。`stop()` 的关停序列只排 writer、只 join projector loop，**从不调用它**——所以关停前最后一段窗口里记下的丢失范围只活在内存里，进程一走就没了，`observability_degradation` 生产者也就永远看不到它。`service.py::_drain_unreported_global_ranges` 里那句「e.g. batch C's shutdown drain」的防御性注释指的就是本节：本节要加的排空步骤是**它的第一个真实调用者**，而那个 `live` 守卫（还在增长的区间不上报）正是为它准备的。**已落地（2026-08-23，T13，裁决 FC-5）**：那就是七步里的第七步 `drain_unreported_loss`，而它确实是那个防御性注释预告的第一个真实调用者——也正因如此，「某一步超时绝不中止后面的步骤」这条规则不是风格问题：关停最糟的时候丢掉的，恰恰是第七步要写下来的那份证据。

## 9. API 与运维 UI

扩展 `/api/ansich/health`：component status、queue depth/capacity/high-water、writer success/failure、projector jobs/lag/watermarks、lost ranges、retention last run、active versions。

Operations 页面增加 Observability Health 面板。degraded/failed 时 Task 列表顶部显示全局 banner；每个 Task 仍显示自身关联状态。提供 failed job 详情和 projector/version，但 v1 UI 不直接提供“跳过 job”破坏性按钮。Replay 通过受控 CLI 运行。

> **实现状态：本节的 B 批部分已落地**（同上）。`/api/ansich/health` 的 additive `database` 块带上了 per-projector 的作业分桶、`complete_through`、`lag_ms` 与权威的 `failed_jobs`；Operations 页新增第四个透镜 “Observability”（`AnsichObservabilityHealthPanel`），它与 System 详情抽屉的分界是硬的——抽屉是**本 worker** 的进程/采集墙，面板是**全库**的答案，两个 failed-job 数从不合并、从不共用标签。degraded/failed 的全局 banner 与 per-Task 状态自 A 批起就在；failed job 详情与 projector/version 由既有的 `GET /operations/failed-jobs*` 提供，v1 仍不提供「跳过 job」的破坏性按钮。**本节的 C 批部分也已落地（2026-08-23 更正，此前这里写的是「仍欠」）**：`retention last run` 由 `DatabaseHealth.retention_last_run` 带到 health 块（`None` 在一个可达的库上意味着**从未跑过**，而不可达时块内每个数字也是 `None`，靠 `status` 分辨这两者），`active versions` 由启动期校验落进 `AnsichHealth.active_version_mismatches`（三态严格分开：`null` = 没读到，`[]` = 干净，列表 = 逐条点名，且**与存储可达性无关**），两者都在 Observability 面板上有渲染并各有 e2e 钉子。受控 CLI 的 replay 是 `python -m deerflow.ansich.replay_cli`（§5）。v1 仍不提供「跳过 job」的破坏性按钮，`POST /retention/hard-delete` 也**刻意没有**前端（§6 的偏离 4）。

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
  > **限定（批终审 B2 补记）**：这句话是关于**中间没有跑过 retention 的库**的。tier 1 把一条 Observation 的 payload 打成 tombstone 之后，那条 Observation 还在，所以重放照样瞄准它、照样建作业、照样重臂——然后以 `completed` 结算，**一行都没派生**（`_settle_expired_evidence_job`），`unsettled` 与 `failed` 都看不见它。于是同一份 Observation 集合跨过一次 retention 之后的两次 digest **本来就不相等**，而这不是确定性坏了，是策略生效了。现在这条差异**有机器可读的面**：`ReplayReport.expired_evidence` 数出目标集里已过期的证据，digest 在它非零时**拒绝计算**并说明理由（第四条 gate 子句），`--replace` 在这种目标集上**直接拒绝**（`replace_over_expired_evidence`）——因为那条路先清表，丢掉的行回不来。
- raw/structural retention 和 owner 删除均无悬空引用；payload 缺失有 tombstone。
- raw read 在审计不可用时拒绝，普通 collection 故障仍不影响 Agent。
- 进程 crash 无 durable spool 的 loss 限制在文档和 health 中明确，不宣称绝对 lossless。
