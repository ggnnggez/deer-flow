# Phase 10 代码评审跟进项

来源:Phase 10(评估输入与语义 Belief)的全分支终审,范围 `2a6c1ded..2dedd08a`(2026-08-18),结论「With fixes」,无 Critical。编号统一用 `F10-N`;`F10-1`–`F10-3` 是终审列出的合并门禁项,已随本次变更修复,其余为带修复方向与归属的登记项。修复一项后同步更新总览表和该项"状态"行,保留原始诊断记录。

本文件登记的是**需要 owner 的**项,不是终审 54 行 triage 的逐行誊抄:纯装修性、覆盖率补齐类的条目合并在 `F10-18 杂项` 里,每条一行。

## 状态总览

| 编号 | 摘要 | 状态 | 修复时间 | Commit |
| ---- | ---- | ---- | -------- | ------ |
| F10-1 | `alert_subject_is_not_a_task` 降级分支无测试:回归后 `_record_dismissal_override` 会把 `quality.<dimension>` 挂到 ToolCall id 上而全套测试仍绿 | ✅ 已修复 | 2026-08-18 | `747d79c6` |
| F10-2 | compare 的两个参数顺序未被钉住:互换即翻转每个 delta 的符号,而测试套件保持全绿 | ✅ 已修复 | 2026-08-18 | `747d79c6` |
| F10-3 | release 聚合格「成员按 cohort、取值取全局」是未记录的 §6 偏离 | ✅ 已修复 | 2026-08-18 | 本次变更(文档) |
| F10-4 | 同上的代码侧:聚合取样应按 cohort 选择 assertion(或改为 per-cohort belief) | ⬜ 未修复 | — | — |
| F10-5 | score delta 的真实分母 `score_count` 在视图边界被丢弃,门禁与展示都用 `assessed_count` | ⬜ 未修复 | — | — |
| F10-6 | 兄弟 rollup(`_refresh_behavior_belief`、usage/budget 读模型)仍是未串行化的 read-modify-write | ⬜ 未修复 | — | — |
| F10-7 | 缺 per-observation 持久化信号,存在「observation 丢失但回执永远 pending」的窗口 | ✅ 已修复 | 2026-08-20 | `6a70072a` / `6665611f` |
| F10-8 | `contracts.py` 的 scope/authorization/effect 三个 `_validate_subject` 分支缺 payload-None 守卫(既存缺陷) | ✅ 已修复 | 2026-08-19 | `d463a604` |
| F10-9 | 同一组常量六处复制(suite-bound kinds ×3、五维度集合 ×3) | ⬜ 未修复 | — | — |
| F10-10 | settle 时序 flaky 未隔离:在负载下轮换命中无关测试(**门禁充分性未证**,见下方留观标记) | ✅ 已修复 | 2026-08-19 | `04f7ce96` / `25168118` |
| F10-11 | pass-rate 兜底未标注量表极性 | ⬜ 未修复 | — | — |
| F10-12 | feedback 桥接在请求路径上 await 一次无上界的 DB 读 | ⬜ 未修复 | — | — |
| F10-13 | `/acknowledge` 静默忽略 `semantic_override` | ⬜ 未修复 | — | — |
| F10-14 | 迁移 `0023` 的 upgrade 有守卫、downgrade 没有 | ⬜ 未修复 | — | — |
| F10-15 | `formatEvaluationVerdict` 忽略 `scaleMin` | ⬜ 未修复 | — | — |
| F10-16 | Recorded evaluations 列表静默截断在 100 条,无截断提示 | ⬜ 未修复 | — | — |
| F10-17 | Agent release 头部质量徽标是硬编码字面量,后端聚合落地后会开始说谎 | ⬜ 未修复 | — | — |
| F10-18 | 杂项(装修性/覆盖率补齐,详见该节逐条) | ⬜ 未修复 | — | — |
| F10-19 | late spawn 边与 sum 型 contribution 并发时存在**永久**丢失窗口(wall_time 可自愈,token/step/tool 不可) | ⬜ 未修复 | — | — |
| F10-20 | `_refresh_usage_summary` 仍是未加锁的全量重算+无条件赋值——F10-6 的同族问题,就在本批加锁那一层的上面 | ⬜ 未修复 | — | — |
| F10-21 | 生产路径的 effect 恒 `scope_id=None`,`attempted_/realized_scope_violation` 两类结论在生产上不可达 | ⬜ 未修复 | — | — |
| F10-22 | `sudo`/`env`/`timeout` 等包装命令下的 effect 分类未裁定,`sudo rm -rf` 目前落回 `process_execute` | ⬜ 未修复 | — | — |
| F10-23 | `_assess_scope_safety_at` 直接校验原始行的 `payload_json`、不 hydrate externalized payload,externalized 的 `authorization.*`/`effect.*` 证据会把 assessor job 打成 durable failed(F10-8 同一危害类的 assessor 侧兄弟,既存) | ⬜ 未修复 | — | — |
| F10-24 | `budget_health:*` 有两个生产写者,`asserted_at` 决胜在模拟事件钟与真实 ingest 墙钟之间比较——证据序已由 `order_wall_time_evidence` 收敛(`ae731b18`),但**断言结构形状**(`as_of_known` vs `enforcement`/`shadow`)仍随决胜漂移 | ⬜ 未修复(证据序半已修) | — | `ae731b18` |
| F10-25 | `record_evaluation` 的重放查询无守卫:存储不可用时 `OperationalError` 直接抛给调用方,RA6 回执阶梯整条不可达(既存,自 `c1349843`) | ⬜ 未修复 | — | — |
| F10-26 | rebuild 完整性:`rebuild_projections()` 可能在依赖延迟的 job 尚未结算时就以「首轮空扫」宣告完成(本批四次目击) | ⬜ 未修复 | — | — |
| F10-27 | 装配不对称:`create_embedded_ansich_service` 的无存储分支漏传三个 knob;`operations_assessment_interval_ms` 至今没有 `AnsichConfig` 字段,生产恒为 1000ms | ⬜ 未修复 | — | — |
| F10-28 | 健康线的两处 UI 级留观:中性线态(phase/unknown)的**渲染层**零覆盖(图标三元式曾在本批被反转过);task 作用域在系统 phase 期间仍称「本任务数据完整」 | ⬜ 未修复 | — | — |

留观标记:F10-10 的第 4 条证据(`test_step_attempt_and_context_are_queryable_after_projection`)**未证实**——只做了排除法,没拿到原始失败文本。若它再轮换红,**先抓失败文本再修**,不要按已有的三条诊断类推。另:F10-10 的门禁只被 Task 8 的验收负载证明过(`e53cefbc` 记录了这条边界),Task 9 的更重负载下仍有 2 条已上门禁的测试翻红,详见该条的「后续观察」。

## F10-1. `alert_subject_is_not_a_task` 降级分支无测试

- 状态:✅ 已修复(2026-08-18,`747d79c6`)。新增 `backend/tests/ansich/test_ansich_evaluations_router.py::test_a_tool_call_subject_alert_degrades_its_semantic_override`:用 `effect.intended`(无 observed 对应、无授权 snapshot)产出一条 `unverified_effect` 告警,其 subject 就是 ToolCall,带 `semantic_override` 提交 dismiss,断言 200、`semantic_override == {"status":"degraded","reason":"alert_subject_is_not_a_task","evaluation":None}`,以及 `evaluation.recorded` observation 数与 `quality.*` assertion 数在 dismiss 前后都不变(均为 0)。RED 证据:把守卫取反(`!=` 改 `==`)后,override 变成 `{"status":"recorded", ..., "projection_status":"applied"}`,两个计数从 `(0,0)` 变成 `(1,1)`——即真的把一条 Task 级 quality Belief 写到了 ToolCall id 上;恢复守卫后 `tests/ansich/test_ansich_evaluations_router.py` 17 passed。守卫本身未改动,这是一条回归钉子而非新行为。
- 原始诊断(留档):
- 位置:`backend/app/gateway/routers/ansich.py::_record_dismissal_override`(ansich.py:623)的 `get_evaluation_subject(alert.subject_id) != "task"` 分支。
- 现状:该分支是生产可达的——`assess_scope_safety` 的结论一律以 `tool_call_id` 为 subject(`scope_safety.py:120`),所以三种 scope-safety 告警的 subject 全都是 ToolCall。这是 Task 6 明确裁定的行为(见 10-evaluation-and-semantic-beliefs.md 偏离 3),但没有任何测试锁定它:一旦回归,`_record_dismissal_override` 会以 `subject_type="task"`、`subject_id=<tool_call_id>` 构造 `EvaluationRecord`,projector 照写 index 行与 `quality.<dimension>` assertion,而全套测试仍然是绿的。
- 方向(已落地):补一条 router 测试,断言降级标记 + 零 evaluation 写入。
- 归属:已完成(终审合并门禁)。

## F10-2. compare 的两个参数顺序未被钉住

- 状态:✅ 已修复(2026-08-18,`747d79c6`)。`frontend/tests/e2e/ansich.spec.ts` 的 release-compare 用例本就把每次 compare 请求的 query string 收进 `compareSearches`,现在在用例末尾对**每一次**请求断言 `left=<Task 绑定的 release id>` 与 `right=<被选中的 release id>`。RED 证据:把 `agent-release-panel.tsx` 里 `useAnsichAgentReleaseComparison(currentReleaseId, rightReleaseId, ...)` 的前两个参数互换后,捕获到的是 `?left=0d695124-…&right=fc695124-…`,新断言失败,而该用例其余断言(含方向说明文案)以及另外 6 条 e2e 全部照绿——正好印证终审的判断;恢复后 `pnpm test:e2e -- ansich.spec.ts` 7 passed。
- 原始诊断(留档):
- 位置:`frontend/src/components/workspace/ansich/agent-release-panel.tsx:55` 的 compare 调用;e2e 用例 `release compare separates observed quality from the structural diff` 原本只对 `compareSearches` 断言 `cohort=`。
- 现状:后端 delta 定义为 `right - left`,Task 10 的修复又把"选中的 release 减去本 Task 的 release"写成了面向用户的方向说明。参数顺序因此是这个数字的**含义**本身,而不是实现细节:互换两个参数会让每个 delta 的符号翻转,方向说明随之变成一句错话,而测试套件不会有任何反应——比"没有方向说明"更糟。
- 方向(已落地):在既有的 `compareSearches` 捕获上加一行 `left=` 断言。
- 归属:已完成(终审合并门禁)。

## F10-3. release 聚合格的 cohort 取值偏离未记录

- 状态:✅ 已修复(2026-08-18,本次变更文档提交)。在 `10-evaluation-and-semantic-beliefs.md` 的"与本计划的偏离"补第 8 条,并在"已知限制"补对应条目:明确 v1 的 cohort 只保证"比较的是同一批 Task",不保证"比较的是这批 Task 在该 cohort 下的判断"。代码侧修复见 F10-4。
- 原始诊断(留档):
- 位置:阶段文档 `ansich/docs/plans/10-evaluation-and-semantic-beliefs.md` 的"与本计划的偏离"与"已知限制"两节。
- 现状:该阶段文档已经记录了七条偏离与四条已知限制,唯独漏掉这一条——而它是唯一一条**改变数字含义**的偏离:运营者看到的 cohort 格,成员是按 cohort 圈的,取值却不是。未记录的语义偏离一旦随分支合并,就再没有地方能让下一位读者发现它。
- 方向(已落地):补一条偏离 + 一条已知限制,并把代码侧修复登记为 F10-4。
- 归属:已完成(终审合并门禁)。

## F10-4. 聚合取样应按 cohort 选择 assertion

- 状态:⬜ 未修复。
- 位置:`backend/packages/harness/deerflow/ansich/persistence/sql.py::_recompute_release_quality_stats`,取样处 `session.get(AnsichCurrentBeliefRow, (task_id, field_name))`(sql.py:7951)。
- 现状:格的**成员**被限制为在 `(cohort, dimension)` 上持有 index 行的 Task,取样值却是这个 Task 的 cohort 无关 current Belief(R3 的 belief 键不含 cohort 的直接后果)。一个 Task 被 suite A 判 fail、又被 suite B 以更晚 `as_of` 判 pass 时,cohort A 的格里聚合进去的是 pass——suite A 从未断言过的判断。§6 的原文是统计聚合"Task 在一个明确 cohort 中的 selected/current evaluation",当前聚合的是全局选中的那一条。
- 方向:两条路线择一——(a) 取样时按选中 assertion 的 `value["cohort_key"]` 过滤,即在该 cohort 内重新做一次 resolver 选择;(b) 按偏离 7 的思路把 Current Belief 的 field 扩展成 dimension + cohort key,让 per-cohort 判断成为一等公民(需要一次显式 field 命名扩展与迁移)。任选其一都要补"同一 Task 被两个 cohort 判出相反结论时,两个格各自拿到自己的判断"的回归。
- 归属:Phase 11(与该阶段的 belief/replay 主题同轨);文档侧已在本次终审记录,不阻塞合并。

## F10-5. score delta 的真实分母在视图边界被丢弃

- 状态:⬜ 未修复。
- 位置:`backend/packages/ansich/ansich/quality.py`(视图字段 :51、可比性门禁 :162、delta 计算 :175-176)与 `backend/packages/harness/deerflow/ansich/persistence/sql.py:2963`(`mean_score = score_sum / score_count`)。
- 现状:`mean_score` 除以的是 `score_count`,而视图只带出 `assessed_count`:`min_samples` 门禁用 `assessed_count`,UI 上"12 → 15 samples"也用 `assessed_count`,唯独 delta 的分母是可能小得多的 `score_count`(重放测试自身就是 `assessed=2, score_count=1`)。运营者因此可能看到"5 → 5 samples,+0.4",而这个 `+0.4` 每侧其实只来自一条打分观测。
- 方向:把 `score_count` 带进 cell 视图与 `coverage`;随后二选一——要么让 score delta 的 `min_samples` 门禁改用 `score_count`,要么在 UI 上显式标出打分样本数,不让读者把 `assessed_count` 当成 delta 的分母。
- 归属:Phase 11(终审已明确不作为合并门禁)。

## F10-6. 兄弟 rollup 仍是未串行化的 read-modify-write

- 状态:⬜ 未修复。
- 位置:`_refresh_behavior_belief` 以及 usage/budget 读模型的重算路径(均在 `backend/packages/harness/deerflow/ansich/persistence/sql.py`)。
- 现状:Task 4 的并发修复只覆盖了 `_recompute_release_quality_stats` 这一个格:它先 `SELECT … FOR UPDATE` 锁住 cell 行、再读它的输入,注释同时说明了"先读后锁"为什么会留下同一个窗口。其余 rollup 保持着与修复前一模一样的姿势——多个 leased worker 用 `skip_locked` 认领同一个聚合目标的兄弟 job,在 READ COMMITTED 下交错读写会丢更新,表现为实时值与重放值分叉。
- 方向:按 `_recompute_release_quality_stats` 的 lock-then-read 作为参考实现,逐个梳理这几处 rollup(顺带评估 INSERT ON CONFLICT 收口 first-writer 竞态)。终审明确它是"这个分支里最好的一块工程",其余 rollup 应被拉到同一标准。
- 归属:Phase 11(生产韧性/多 worker)。

## F10-7. 缺 per-observation 持久化信号,回执可能永远 pending

- 状态:✅ 已修复(2026-08-20,`6a70072a`;cancel-mid-commit 的过报方向随 `6665611f` 写进 docstring)。P11-A 批 Task 7 把回执改成**按 observation 当前所处的状态**解析,而不是按「为它发起的那次写的结论」解析。`AnsichService._resolve_evaluation_receipt_status` 是有序阶梯,只有第一个有资格发言的档次说话:
  1. 还在队列里、或已在 writer 手上 → `pending`(它在路上);
  2. 已被记为丢失(有界 4096 条的 `_lost_observation_ids`)→ `failed`;
  3. 已落库 → 由它自己的 projection job 决定;而一个 accepted id **没有 job** 读作 `failed` 而**不是** `pending`——job 与它所属的 observation 同事务提交,所以不存在「还没出现的 job」。唯一的例外是后端根本答不出来(没有读者)时保留旧的 `pending`:读者的缺席不能说明 observation 的死活。
  4. 三处都不在 → `failed`,推定丢失(重启留下的形状:一个 accepted 的 `obs_id` 不在任何队列、不在任何 writer 手上、也不在库里,已经没有东西可轮询)。
- 原诊断那个窗口正好落在第 2 档:observation 被写入器取走、批次撞上 `storage_failure`,那条 observation 此刻已被 charge 成丢失,回执直接给 `failed`,不再停在 `pending`。
- **反向的一半同时被修正**:终端 barrier 超时**不再**读作 `failed`。RA5② 把没能落库的行退回队列头,行还活着,所以这个状态现在诚实地读作 `pending`——旧规则在这里是把一条活着的 observation 宣告为死亡。
- 前提(必须随本条一起读):第 4 档「三处都不在 ⇒ 丢失」只对**本进程拥有的 id** 成立。队列与 in-flight 是进程本地的,数据库是共享的,因此 `GATEWAY_WORKERS > 1`(每 worker 一个 collector、共用一个库)下,一条解析任意 `obs_id` 的路由会把邻居 worker 队列里活着的行报成 `failed`。今天两个调用点都满足这个前提(一个刚把 observation 记进**本** collector,另一个是从存储里读回来的 id),该前提写在 `_resolve_evaluation_receipt_status` 的 docstring 里;未来那种路由需要的是**另一个**末档,不是这一个。
- 已知的过报方向:提交落库**之后**才到达的取消会把一个 durable 批次整批 charge 成丢失(见 `_drain_writer` 的 docstring),于是第 2 档会对一条其实活着的行答 `failed`。方向是刻意选的——宁可多报一次没发生的丢失,不可漏报一次真发生的——且是进程本地的:重启后同一条 observation 走第 3 档从存储读出正确答案。
- 覆盖记账提醒(Task 8 复审):既存的 `test_a_refused_write_reports_failed_rather_than_pending` 是**第 4 档穿着第 2 档的衣服**——行从未落库时两档答案相同,把 `charged` 强制为 `False` 的变异不会让它翻红,所以它不能记作第 2 档的覆盖。生产上唯一只有第 2 档能答的状态,就是上面那个「提交后被取消」的过报窗口。
- 原始诊断(留档):
- 位置:`record_evaluation` 的回执路径(`backend/packages/ansich/ansich/service.py`)与其下的批量写入器。
- 现状:Task 5 的 `FlushResult` 分支已经把"拒绝入库"和"flush 未持久化"从 `pending` 里摘出去了,但残留一个既存窗口:后台写入器取走了这条 observation,它所在的批次撞上 `storage_failure`,之后的 `flush_task` 因为没有可选的项而报 `persisted=True`——回执于是停在 `pending`,而这条 observation 其实已经丢了。轮询这个回执的调用方永远等不到终态。
- 方向(已落地,但走的不是原方向):原方向写的是「引入 per-observation 的持久化信号」;实际落地的是「回执不再读那次写的结论,改读 observation 的状态」——同一条不变量,代价更小,且顺带修正了 barrier 超时那一半反向的错答。
- 归属:已完成(P11-A 批,与 spec §2 的写侧加固同批)。

## F10-8. 三个 `_validate_subject` 分支缺 payload-None 守卫

- 状态:✅ 已修复(2026-08-19,`d463a604`)。把 `evaluation.recorded` 分支的守卫模式原样复制到 `scope.snapshotted`/`authorization.*`/`effect.*` 三个分支:subject_type 检查保持无条件,只有 payload 交叉校验挪进 `if self.payload is not None:`,payload 在手时的校验强度一字未改(`test_safety_contracts.py` 里 kind/decision、kind/phase 两条冲突拒绝用例未改动仍绿)。回归钉子:`backend/tests/ansich/test_sql_safety.py::test_externalized_scope_authorization_and_effect_payloads_read_back`——服务按 `inline_payload_max_bytes=16` 构造,让每条 payload 都走 externalize,记录 scope/authorization/effect 三条 observation 并 flush,先断言这三行在库里确实是 `payload_json IS NULL AND payload_ref_id IS NOT NULL`,再经 `service.list_timeline()` 与 `service.list_observations()` 两个公共读读回。RED 证据:读路径不是降级成空/degraded,而是直接抛 `ValidationError: Input should be a valid dictionary or instance of ScopeDescriptor [input_value=None]`(`sql.py:5574` 的 `_observation_from_row`);逐个分支补守卫时报错依次换成 `AuthorizationSnapshot`、`ToolEffect`,三个分支各自都被这一条用例钉住。附带确认:`_claim_projection_job` 同样先 `_observation_from_row` 再 hydrate payload,所以修复前这三种 kind 的 externalized observation 连投影都认领不了,job 永远 pending、`flush_task` 只能等到 `projection_settle_timeout`——"能写进去、再也读不出来"比诊断记录的还要广一层。**该危害类并未全部关闭**:assessor 侧的兄弟(`_assess_scope_safety_at` 直接读原始行的 `payload_json`、同样不 hydrate)仍然敞开,已登记为 F10-23,不要把本条的 ✅ 读成 externalized-payload 这一类危害已经清零。
- 原始诊断(留档):
- 位置:`backend/packages/ansich/ansich/contracts.py` 的 `scope.snapshotted`/`authorization.*`/`effect.*` 分支(contracts.py:243-271);`evaluation.recorded` 分支(:273-283)是正确的参考写法。
- 现状:这三个分支无条件 `model_validate((self.payload or {}).get(...))`,payload 为 `None` 时直接抛错。externalize 的 observation 在 `_observation_from_row` 里重新校验时 payload 不在手上,于是这些 kind 一旦走 externalize 路径就是"能写进去、再也读不出来"。`evaluation.recorded` 分支用 `if self.payload is not None:` 把交叉校验包起来,是本仓库里唯一正确的样板。
- 方向:把 evaluation 分支的守卫模式复制到这三个分支,不改变 payload 在手时的校验强度;补一条 externalized payload 往返的回归。
- 归属:Phase 11 前(既存缺陷,不阻塞本阶段合并,但它与 F10-6/F10-7 同属"重放/韧性"清单)。

## F10-9. 同一组常量六处复制

- 状态:⬜ 未修复。
- 位置:suite-bound evaluation kinds 集合 ×3——`packages/ansich/ansich/evaluation.py:58` `_SUITE_BOUND_KINDS`、`packages/harness/deerflow/ansich/persistence/sql.py:340` `_EVALUATION_SUITE_BOUND_KINDS`、`app/gateway/routers/ansich.py:52` `_BENCHMARK_EVALUATION_KINDS`;五个具名 quality 维度集合 ×3——`evaluation.py:25`(与 :48)、`sql.py:337`、`ansich.py:180` 的 router `Literal`。
- 现状:六份拷贝今天完全一致,所以这是漂移风险而非缺陷。其中 `sql.py` 那份最没有理由存在——该文件已经从 `ansich.evaluation` import 了别的符号,复制纯属顺手。
- 方向:从 `ansich.evaluation` 导出 `QUALITY_DIMENSIONS` 与 suite-bound kinds 两个常量,把六处收敛到一处;先收 `sql.py` 那份。注意 router 上的 `Literal` 同时喂给 FastAPI 的 422 schema,收敛时不能让 schema 退化成 `str`。终审明确这是**一条**清理项,不是六条。
- 归属:随下次相关改动顺带处理(不单独排期)。

## F10-10. settle 时序 flaky 未隔离

- 状态:✅ 已修复(2026-08-19,`04f7ce96`;门禁挂载点的真 service 钉子与 flake 归类更正随 `25168118`,充分性边界随 `e53cefbc`)。四条证据指向同一个后台写者——`AnsichService._projector_loop` 的 `assess_operations()`,它永远用**墙钟** `now`,而这些测试自己驱动的评估传的是**模拟** `now`。但**同一个写者在两种测试形状里以不同频率登场,别把它们说成一件事**:
  - **默认档(9 条,`create_sql_ansich_service(...)` 没覆写 `operations_assessment_interval_ms`)**:默认值就是 1 Hz(`deerflow/ansich/__init__.py` 的 `operations_assessment_interval_ms=1_000`),所以整条测试体里后台每秒都在评估。8/8 复现的那条 budget 测试就在这一档——真正撞上来的是**这个周期**,不是「压不掉的第一轮」;把间隔调到 60s 对它其实有效,只是仍留下第一轮那一次,所以不是完整的修法。
  - **60s 档(20 条,显式 `operations_assessment_interval_ms=60_000`,如 alerts 的 coalescing 用例与 safety 的 rollback 用例)**:周期那一半已经被 `e91d9f1c` 的做法压掉了,**剩下的写者是第一轮迭代那次无条件评估**(`next_assessment = loop.time()`,循环第一次迭代必评估),它不受间隔控制,测试侧也没法把它调没。
  
  两种形状调大超时都治不了,因为等的是另一个写者而不是一个慢操作。修复因此不是等更久,而是让这些测试**拥有评估调度**:新增 `backend/tests/support/ansich_settle.py::only_test_driven_assessments(service)`,按发起 task 区分,把 projector loop 自己发起的 `assess_operations()` 变成 no-op(投影照跑,测试的显式调用照跑,`rebuild_projections()` 内部的 `_assess_operations_unlocked` 不受影响)——一把锁同时关掉周期和第一轮。另加 `backend/tests/ansich/conftest.py`,把本目录所有 SQLite 引擎对齐生产的并发 pragma。
- RED 证据(可复现,不是只靠推理):24 个 CPU 忙循环压着重复跑那四条测试,`test_sql_budget_health_retains_terminal_overshoot_and_evidence` **8/8 失败**,失败点与本会话记录一致——`{'source': {'name': 'absolute-limit', 'version': '1.0.0'}} != {'source': {'name': 'budget-health', 'version': '1'}}`(两次读的 `model_dump` 比对);修复后同一负载 **8/8 通过**。另用一段独立脚本把「后台评估落在两次读之间」显式重放,复现同一条不等式,并验证修复后两次读拿到同一条 assertion。**这套负载现在是可重跑的**:`backend/tests/support/ansich_contention_repro.sh`(手动诊断,不进 CI、不被任何测试导入),失败轮次整段存盘——本条「先抓失败文本」的规矩要用它来执行。
- 逐条诊断:
  1. `test_sql_budget.py::test_sql_budget_health_retains_terminal_overshoot_and_evidence`(最老的一条,`phase-9-review-followups.md` 里就记过「无关的预存 flaky」):`budget_health:total_tokens:local` 这个 field 有两个写者——终态 control 投影里的 `_assess_budget_rows`(source `budget-health@1`,`asserted_at = observation.recorded_at`,墙钟)与 `absolute-limit@1.0.0` assessor job(`asserted_at` = 评估传入的 `now`)。`ansich-default@2.0.0` 在 authority 相同时按 `(as_of, asserted_at, assertion_id)` 取最大,而测试自己的评估用的是 2026-07-18 的模拟时间,永远排在 `recorded_at` 之前,所以 budget-health 稳定胜出;projector loop 用墙钟评估写出的 absolute-limit assertion 则更晚,一旦落在两次读之间就翻转 selected source。**这条属于默认档**:服务按 `create_sql_ansich_service(session_factory)` 构造,没覆写间隔,所以撞上来的是 1 Hz 的周期评估——测试体一旦被负载拖过一秒,后台就有一次机会插进两次读之间(24 个 CPU 忙循环下每次都插得进,故 8/8)。修复:gate,并把两次读的 `source.name` 显式钉成 `budget-health`——让「等的是哪个 assessor 的断言」变成写死的期望,而不是碰巧。
  2. `test_sql_alerts.py::test_sql_assessor_jobs_coalesce_to_highest_pending_watermark`(`e91d9f1c` 修过一轮的同一条):它断言 `pending_count > 1`、`evaluated_watermarks == [highest_watermark]`、`sum(attempts) == 1`,三条都在描述「只有我这一次评估跑过」。第一轮迭代那次后台评估一旦滑到三条 action step 投影之后,就会先把 job drain 掉,三条断言一起塌。修复:gate。
  3. `test_sql_safety.py::test_absorbed_low_watermark_window_survives_an_evaluation_rollback`(本批 Task 4 新增):它手工把 `ansich_assessor_watermarks` 改成 late 证据的 ingest_seq(前置断言 `mark.evidence_watermark < late_last_seq`)再驱动三次评估;后台评估会用墙钟认领 scope-safety job 并推进这个 mark,精心安排的窗口直接不成立。同一条还观察到过一次 SQLite `database is locked`,那是另一类问题:测试引擎是裸 `create_async_engine`,`journal_mode=delete` + 驱动默认 5s `busy_timeout`,而生产 `deerflow/persistence/engine.py` 给每条 SQLite 连接设 WAL + 30s `busy_timeout`;回滚日志模式下「读事务要升级为写事务、而另一条连接持 RESERVED」会**立即**返回 SQLITE_BUSY(SQLite 故意不走 busy handler,因为重试必然死锁),于是测试直接报错而不是等待。修复:gate + conftest 的 pragma 对齐。三处 `anyio.sleep(0.3/0.5)` 保留:它们等的是 dependency-pending 的 250ms 退避,是下界等待(负载下只会睡更久),不是竞态源。
  4. `test_sql_task_lifecycle.py::test_step_attempt_and_context_are_queryable_after_projection`:**推定诊断——没拿到原始失败文本,人工负载下也没能复现**。可以排除 outcome-racing:它自己不调 `assess_operations`,断言的 `StepView`/`ContextSnapshotView` 里没有任何 assessment 派生字段,中间件是同步记录(只有 heartbeat probe 用 `create_task`,本测试不启动它),writer loop 与 `flush_task` 共用 `_persist_lock`。剩下的负载敏感面只有两处:SQLite 锁竞争(已由 conftest 消除)与 `flush_task` 的 10s 投影 settle 预算(`4e5eb0fd` 的耐心默认值,本次未动)。
- 同型清扫:按「测试自己驱动评估 ⇒ 测试拥有评估调度」这条统一规则,把 gate 补到 `tests/ansich/` 里全部 **29** 条「启动了 service 又自己调 `assess_operations`」的测试(含上面三条),分布为 `test_sql_alerts`(8)、`test_sql_safety`(8:276/438/592/810/1435/1541/1669/1768)、`test_ansich_operations_router`(3)、`test_sql_active_tasks`(3)、`test_sql_budget`(2)、`test_sql_heartbeat`(2)、`test_sql_task_tree`(2)、`test_sql_agent_releases`(1)。按上面两种形状拆:**9 条在默认 1 Hz 档**(ops_router 1、active_tasks 2、agent_releases 1、budget 2、safety 2、task_tree 1),**20 条已显式 60s**。
- 只登记不修(形状不同,不适用同一把锁):
  - 151 条「启动了 service 但不自己驱动评估」的测试:后台评估对它们是环境噪声而不是结果竞态,是否该静默要逐条判断,没有证据就不动。
  - `tests/ansich/test_task_lifecycle.py::test_background_writer_makes_running_task_queryable_without_explicit_flush`(`anyio.fail_after(0.5)`)与 `tests/ansich/test_sql_heartbeat.py::test_background_assessor_materializes_running_task_heartbeat_belief`(`asyncio.timeout(1)`):等的是确定性条件(轮询到 Task / heartbeat Belief 出现),但**期限本身**对负载敏感。它们真轮换红的话,唯一正确的改法是放宽那个期限——完成信号已经是确定性的,不需要再加 sleep。
  - `tests/ansich/test_task_lifecycle.py::test_rebuild_is_mutually_exclusive_with_background_projection` 里的 `anyio.sleep(0.05)`:那是给 projector loop「有机会」抢 job 的否定式断言窗口(`project_pending_during_rebuild == 0`),负载下只会让机会更少,方向是安全的,但它是一个时间窗而不是信号。
- 验收:`uv run pytest tests/ansich -q` 背靠背连跑三次全绿——`483 passed` / 200.87s、`483 passed` / 210.40s、`483 passed` / 287.95s;评审第一轮补钉之后再全量跑一次,`484 passed` / 250.33s(改动前 481,本次新增三条机制钉子)。三条钉子都在 `tests/ansich/test_settle_isolation.py`:gate 只放行测试自己发起的调用;gate 挂的确实是 projector loop 真正走的那个方法(用**真 service** + 1ms 评估间隔,数后端边界上的调用数,断言 loop 发起 0 次、测试发起 1 次,含 `stop()` 收尾那次);本目录的裸引擎报 `wal` / `30000`。这三个机制坏掉时都是静默的(空闲机器上照样全绿),所以必须钉住。
- 后续观察(Task 9 会话,2026-08-19,**不改状态、不是新诊断**):在 Task 9 的高并发负载下(与 dockerless PostgreSQL 集成层同机跑,`tests/ansich` 连跑 5 次),**29 条已上门禁的测试里有 2 条仍然翻红**。这不推翻本条的修复,但把验收的边界说清楚:**门禁只被 Task 8 那三次(外加复审后一次)背靠背验收跑证明过,没有被证明在更重的负载下充分。**
  - 翻红的两条(都已核对源码,确认带门禁):
    - `tests/ansich/test_sql_safety.py:1410::test_scope_safety_reassessment_work_does_not_grow_with_tool_call_count` —— `only_test_driven_assessments(service)` 在 :1435,三个间隔全是 `60_000`(正是本条"同型清扫"里点名的 safety 第 1435 行)。失败文本:`assert [0, 2, 3, 1, 1] == [1, 1, 1, 1, 1]`。
    - `tests/ansich/test_sql_alerts.py:947::test_failed_assessor_jobs_degrade_health_and_can_be_retried` —— `only_test_driven_assessments(service)` 在 :964,flush 与 ops 评估间隔均为 `60_000`。**只有测试 id,没拿到失败文本**(后台 `-q` 捕获只留了 summary),证据强度与本条第 4 项的留观标记同级。
  - 同一批还翻红了 `tests/ansich/test_summarization_lineage.py:76::test_partial_list_content_trim_records_an_incomplete_compression_inventory`(`assert None is not None`)。它**没有**门禁、用的是 `create_sql_ansich_service(session_factory)` 的默认间隔,属于本条"只登记不修"里那 151 条的形状,不在本条的修复范围内——记在这里只是为了和上面两条区分开。
  - 复现把手:**`[0, 2, 3, 1, 1]` 这个计数**。该测试每轮先清空 `assessed_subjects`、再 `await service.assess_operations(now=...)` 一次、然后记长度;五轮总和是 7(期望 5),且第 0 轮记到 0、第 1 轮记到 2 —— 同一次运行里既有缺也有多。
  - 若它再轮换红:**先抓失败文本**,然后在三个方向里做判断,不要跳过取证直接下结论——(a) 评估是否经由门禁拦不到的路径到达了这个计数器(门禁重绑的是 `service.assess_operations`,而该计数器打在 `sql_module.assess_scope_safety` 这个领域函数上,两者不是同一个入口);(b) 或者在负载下推动这些计数器的根本不是评估,而是另一个竞争者;(c) **批终审新增、目前最可信的一条**——assessor mark 在 dependency-pending 自愈路径上回退,详见下条。Task 9 没有刻意复现也没有加插桩,(c) 抬高的是先验而**不**替代取证:「先抓失败文本再修」这条不变。
  - **假设 (c):assessor mark 回退(Phase 11 前加固批的批终审登记,2026-08-19;机制经代码核实,但尚未用失败文本证实它就是这条 flake 的成因)**
    - 机制:`_claim_assessor_job` **无条件**把 mark 下调到「本次 claim 组内最低 watermark − 1」(sql.py:1432-1438),而 `_advance_assessor_watermark` 事后只把它抬回**这次 claim 自己的** watermark(调用点 sql.py:1646,`Never lower` 分支 sql.py:1757)。于是每出现一条 watermark 低于已推进 mark 的 job,mark 就被永久下调一个档。
    - 可达性是**常规自愈路径**,不是罕见竞态:`_project_safety` 在被引用的 ToolCall/Scope 尚未投影时抛 `_ProjectionDependencyPending`(sql.py:8090、8098、8221、8223),被推迟的那条 observation 的 assessor job 因此在更高 ingest_seq 的兄弟**已经**结算过 mark 之后才建出来——正是 H6 自愈用例天天走的那条路。
    - 代价:下一次触发的区间横跨整个档;而 scope-safety 用**评估时刻**盖 `as_of`,`_persist_assessment` 的去重对它无效——档内**每个**已收敛 ToolCall 都会多拿一条 assertion 和一行 `ansich_scope_conclusions`。这笔开销有界(每个晚到者一次宽重判)且安全(结论完全相同),但它正是 phase-9 M2 立项要消除的那一笔。
    - 与 `[0, 2, 3, 1, 1]` 的吻合:先缺一轮(证据被推迟,那一轮的区间里没有它),随后几轮多出来(mark 回退把窗口撑宽),同一次运行里既有缺也有多、总和 7 > 5——正是「证据推迟 → mark 回退 → 后面的窗口变宽」的形状。
    - Phase 11 候选修法:在 `_claim_assessor_job` 里记住下调**前**的 mark,`_advance_assessor_watermark` 发现「本次 claim 组的最高 watermark 低于它」时把它恢复回去,而不是停在这次 claim 的 watermark。与 F10-6 配对处理(同属 assessor 侧的串行化/水位治理)。
    - 缺的测试牙齿:`backend/tests/ansich/test_sql_safety.py::test_absorbed_low_watermark_window_survives_an_evaluation_rollback` 已经把这个场景整条驱动出来了,却只断言了安全的那一半(晚到 ToolCall 被判到),从不数已收敛 ToolCall 的 assertion / `ansich_scope_conclusions` 条数。补上这条计数断言,假设 (c) 就能被证实或证伪。
- 后续观察(P11-A 批,2026-08-20,**不改状态、不是新诊断**):
  - **门禁边界的确切位置**(来自 Task 2 fix round 的复审,本条此前只说了「充分性未证」,现在能说得更准):那两条 load-flaky 的 scope-safety 测试**本来就**调了 `only_test_driven_assessments`。所以它们再翻红**不是门禁失效**,而是门禁根本不管那一段——`only_test_driven_assessments` 覆盖的是**评估的节奏**(周期评估与第一轮那次无条件评估),不覆盖 dependency-wait / 自愈路径上的那次**读**。下一次加固要补的是**给那次等待一个 settle gate**,而不是把现有门禁调宽或再调大超时。
  - **假设 (c) 形状在本批被再次目击两次,证据强度不同,分开记**:
    - Task 6(quiet 机器第 2 轮,**失败文本完整捕获**——这一轮没有走 `tail` 管道):同一条测试 `test_sql_safety.py::test_scope_safety_reassessment_work_does_not_grow_with_tool_call_count`,`assert [0, 2, 1, 1, 1] == [1, 1, 1, 1, 1]`,"At index 0 diff: 0 != 1"。与本条记录的 `[0, 2, 3, 1, 1]` **同形但不同量**:第 0 轮缺、第 1 轮多,同一次运行里既有缺也有多;但**总和仍是 5** 而不是 7 —— 只发生了位移,没有膨胀。也就是说这一次复现的是假设 (c) 的**前半**(证据被推迟到下一轮),没有复现**后半**(mark 回退把之后的窗口撑宽)。这条差别本身就是取证价值:两半可以分别发生。
    - Task 5:同一条测试、同一个断言(`assert subjects_per_round == [1] * tool_calls`),但**失败文本被运行器自己的 `tail` 管道截断并永久丢失**,只剩断言行。按本条「先抓失败文本再修」的规矩,这次目击**不构成完整证据**——只能记作一次计数,不能用来推断分布形状。需要时用 `backend/tests/support/ansich_contention_repro.sh` 重新捕获。
- 原始诊断(留档):
- 位置:`backend/tests/ansich/` 的 SQLite 集成测试族(负载下轮换命中,每条单跑必过)。
- 现状:Task 9 期间观察到一条与被测行为无关的失败,在不同测试之间轮换出现;同族现象在 Phase 7 已经确诊为投影 settle 时序对套件级负载敏感,而不是被测代码的缺陷。它现在的代价是每次全量跑都要人工判断"这条红是不是真的"。
- 方向:沿用 Phase 7 M2 的先例(`e91d9f1c`/`4e5eb0fd`)——隔离 SQL 集成测试的 settle 时序,让等待条件不再依赖套件整体负载,而不是靠调大超时。
- 归属:Phase 11 前(与该阶段的多 worker 工作同一批治理)。

## F10-11. pass-rate 兜底未标注量表极性

- 状态:⬜ 未修复。
- 位置:`backend/packages/ansich/ansich/quality.py::_observed_delta`(quality.py:169-180)与前端 `qualityScaleDirection`。
- 现状:两侧都有 `mean_score` 时按分数算 delta,否则回落到 pass rate。但"回落"目前不看两个 cell 是否真的没有量表:一个有量表却因为别的原因缺 `mean_score` 的 cohort,会被当成纯 verdict cohort 处理,而 pass rate 的极性恒为"越高越好",与该量表声明的极性可能相反。
- 方向:只在两个 cell 的 `scale` 都是 `None` 时才回落到 pass rate;或者在回落时把量表极性一并带出来供前端标注。
- 归属:未定,建议随 F10-5(同一函数族的分母/口径问题)一并处理。

## F10-12. feedback 桥接在请求路径上 await 无上界的 DB 读

- 状态:⬜ 未修复。
- 位置:`backend/app/gateway/feedback_evaluation.py:79` 的 `await service.get_task_by_source("deerflow_run", run_id)`。
- 现状:桥接的 fail-open 语义覆盖的是"抛异常",不覆盖"阻塞"。这条索引读发生在 feedback 请求路径上,一旦存储侧卡住,feedback 接口会跟着一起挂——正是这个桥接明确不该造成的影响。
- 方向:给这次读加 `asyncio.wait_for` 上界,超时按既有 fail-open 分支处理(丢回执、不改响应)。
- 归属:未定,建议随下次触达该文件的改动顺带处理。

## F10-13. `/acknowledge` 静默忽略 `semantic_override`

- 状态:⬜ 未修复。
- 位置:`backend/app/gateway/routers/ansich.py::AlertWorkflowRequest`(ansich.py:161,acknowledge 路由的 body 模型)——只有 `AlertSemanticOverride` 声明了 `model_config = ConfigDict(extra="forbid")`,它自己没有。
- 现状:dismiss 接受 `semantic_override`,acknowledge 不接受;但 acknowledge 的模型不禁止未知字段,于是一个把 override 发到 acknowledge 上的调用方会拿到 200 且什么都没记录,没有任何提示。
- 方向:给 `AlertWorkflowRequest` 加 `extra="forbid"`(与本阶段其他新请求模型一致),让误用变成 422。
- 归属:未定,顺手清理项。

## F10-14. 迁移 `0023` 的 downgrade 没有守卫

- 状态:⬜ 未修复。
- 位置:`backend/packages/harness/deerflow/persistence/migrations/versions/0023_ansich_evaluations.py`。
- 现状:upgrade 侧按本仓库惯例做了存在性守卫(重复执行是 no-op),downgrade 侧没有,对已经不存在的对象执行降级会直接抛错。
- 方向:让 downgrade 与 upgrade 对称,复用同一组幂等 helper。
- 归属:未定,顺手清理项(`0023` 尚未发布,分支内可就地修改)。

## F10-15. `formatEvaluationVerdict` 忽略 `scaleMin`

- 状态:⬜ 未修复。
- 位置:`frontend/src/core/ansich/presentation.ts::formatEvaluationVerdict`(presentation.ts:195)。
- 现状:分数一律渲染成 `<score> / <max>`,`1-5` 量表和 `0-5` 量表因此显示成同一个 "3 / 5",而这两个 3 的含义并不相同。
- 方向:`scaleMin` 非 0 时把区间一并显示(或改用本地化的区间标签),不要让读者以为下界总是 0。
- 归属:未定,建议与前端 UI-2 的展示项一并处理。

## F10-16. Recorded evaluations 列表静默截断在 100 条

- 状态:⬜ 未修复。
- 位置:`frontend/src/components/workspace/ansich/evaluations-panel.tsx` 的 Recorded evaluations 列表;服务层 `list_evaluations` 默认 `limit=100`。
- 现状:超过 100 条时列表安静地只显示最新 100 条,没有任何截断提示——与本仓库"绝不静默截断"的既定立场相冲突。该限制已同时记录在 10-evaluation-and-semantic-beliefs.md 的"已知限制"里。
- 方向:补截断标记(以及/或者分页),让读者知道自己看到的不是全部。
- 归属:UI-2。

## F10-17. Agent release 头部质量徽标是硬编码字面量

- 状态:⬜ 未修复。
- 位置:`frontend/src/components/workspace/ansich/agent-release-panel.tsx` 的头部卡片徽标(Task 10 已在该处留下陷阱注释)。
- 现状:徽标写的是字面量 `unassessed`,不是 payload 驱动的。今天它是对的——后端 `AgentReleaseSummaryView.quality_status` 本身就被钉成 `Literal["unassessed"]`;但等 release 级聚合真正落地,这个徽标会在数据已经变了的情况下继续说 `unassessed`。Task 10 评审已裁定:结构化 diff 内那枚徽标被移除是正确的(它的主语是比较本身),留下的头部徽标描述的是尚未聚合的 release 状态,重新限定它是**跟进项**而非该 task 的缺陷。
- 方向:后端 release 级质量聚合落地时,同步把这个徽标改成 payload 驱动或直接隐藏;在那之前不要从 Phase 10 的 compare 结果反推它。
- 归属:后端聚合落地时(门禁在后端,不在前端)。

## F10-18. 杂项(装修性/覆盖率补齐)

- 状态:⬜ 未修复。以下每条都不改变行为,合并在此项下统一登记,随相关路径下次改动顺带处理。
- `backend/tests/ansich/test_sql_evaluations.py::test_evaluation_migration_upgrades_sqlite` 的索引 parity 断言在修复冗余索引时从相等弱化成了成员判断(`"ix_ansich_release_quality_cohort" not in indexes[...]`);更强的 `indexes["ansich_release_quality_stats"] == set()` 形式仍然可用,且能挡住任何新增的多余索引。
- `test_evaluation_models_compile_with_postgresql_constraints_and_indexes` 末尾的 `"ix_ansich_release_quality_cohort" not in ddl["ansich_release_quality_stats"]` 是空断言——`CreateTable` 本来就不会发出 `CREATE INDEX`,该行永远为真(同一测试里紧邻的 `__table__.indexes == set()` 才是真正的断言)。
- `_recompute_release_quality_stats` 的 delete-at-zero 分支经核实不可达,目前无覆盖;要么补一条构造性用例,要么删掉这段死代码。
- 前端 e2e 里有一条 chip 断言不具区分度(fixture 的 cohort 与 suite 取值相同,断言无法证明渲染的是哪一个)。
- 新增的 payload 路由的审计日志行没有用 `caplog` 钉住(同文件 4 行之外就有兄弟先例)。
- 新增的 payload 路由的 `payload_ref` blob 分支(externalize 后的正文)没有被测试触达。
- dismiss 的 `source_event_id` 格式(`evaluation:dismiss:{alert_id}:{workflow_version}`)没有测试锁定,重放身份可以被无声改掉。
- 前端没有消费 compare 响应里回显的 `quality.cohort`,界面因此无法确认后端实际生效的到底是哪个 cohort(输入框里的值只代表"请求过什么")。
- `compare_release_quality` 没有 `min_samples >= 1` 的下界守卫;配置成 0 时"可比"会退化成无样本也可比。
- `QualityComparisonView.resolver` 复用的是 belief resolver 的版本号,而它描述的其实是比较规则的版本——需要文档说明或独立版本号。
- benchmark 的 `source_event_id` 用冒号拼接各组件且不转义,`run_id` 里带冒号时理论上可以碰撞;候选修法是对 suite/suite_version/case_id/run_id 加"不含冒号"的约束。
- `not_comparable` 行与 unassessed 行目前只靠文案区分,加一个结构性标记会更利于扫读;e2e 也还没渲染过 unassessed 行、没断言过 delta 的中性配色。
- 迁移 id 与 `alembic_version.version_num` 的 `VARCHAR(32)` 上限已**贴边**:`0024_ansich_wall_time_watermarks` 与 `0021_ansich_summary_assertion_fk` 都正好 32 字符,余量为 0。本批已在 `tests/test_persistence_bootstrap.py::test_baseline_revision_id_is_known` 补一行 `max(len(...)) <= 32` 断言把它钉住,下一条更长的 revision id 会在测试里红,而不是在用户的 Gateway 启动时红。
- 全部 72 张表在 PostgreSQL 方言下渲染的是 `json` 而不是 `jsonb`(模型统一用泛型 `sa.JSON`,`grep JSONB` 全仓库零命中,只有 `_helpers.py` 的反射等价对与文档提到该词)。`json` 不支持 `jsonb` 的 GIN 索引与包含查询,而 Ansich 的 `*_json` 列将来若要按内容过滤就会需要它。改成 `jsonb` 是一次跨全部 JSON 列的迁移(含 Ansich 之外的 `runs`/`run_events`),**登记为 Phase 11 的待裁决项**,本批只把文档里说反的两处(`backend/AGENTS.md`、`persistence/bootstrap.py` 的 docstring)改正。
- Task 9 的 PostgreSQL tier 文档里那条 `docker run ... postgres:16` 启动一行**本身没有被执行过**——该环境里 Docker 守护进程不可用,实际验收跑在一个由 `pgserver` wheel 自带的官方 PostgreSQL 16.2 二进制 `initdb` 出来的一次性本地 cluster 上(同一份服务端软件、同一个 5433 端口与 URL)。命令是标准写法,但"照抄即可跑通"这件事没有证据,`backend/Makefile` 的注释已就地标注。

## F10-19. late spawn 与 sum 型 contribution 的永久丢失窗口

- 状态:⬜ 未修复。来源:Phase 11 前加固批 Task 3 的复审(不是 Phase 10 终审)。
- 位置:`backend/packages/harness/deerflow/ansich/persistence/sql.py::_backfill_spawn_usage`(读后代 self 行、写祖先行,刻意不加锁)与 `::_project_usage`(新贡献按当时可见的 ancestry 扇出)。
- 现状:两条路径各自读一次 ancestry / 后代贡献集合,中间没有共同的串行化点。一条后代贡献若在 `_backfill_spawn_usage` 读完之后才提交,而它自己的 `_project_usage` 又跑在 spawn 边可见之前(此时祖先集为空),这条贡献就**再也不会**到达祖先。wall_time 不受影响——它是 max 型,下一个 tick 的扇出会把水位抬平;`total_tokens`/`steps_*`/`tool_calls_executed` 这些 sum 型维度没有这种自愈,祖先的 inclusive 值会**永久偏低**。`_backfill_spawn_usage` 的 docstring 已经点明"行锁挡不住新行插入",即这个窗口结构上不是加锁能关的。
- 方向:需要一个把"spawn 边可见"与"该后代的贡献集合"串起来的点——例如 spawn 投影完成后按后代 Task 重新触发一次 fan-out 对账(幂等键已经保证不会双计),或把 inclusive 汇总改成读时按 ancestry join 而不是写时扇出。任选其一都要配"贡献与 spawn 边并发到达时 inclusive 不丢"的回归。
- 归属:Phase 11(多 worker / 生产隔离),与 F10-6/F10-20 同一批。单 worker 下投影 job 串行消化,窗口不成立,因此当前不是 active bug。

## F10-20. `_refresh_usage_summary` 仍是未串行化的读-改-写

- 状态:⬜ 未修复。来源:同上(Task 3 复审),是 F10-6 的同族问题,登记为独立条目是因为它就在本批刚刚加锁的那一层的**上面**一层。
- 位置:`sql.py::_refresh_usage_summary`——全量重扫该 `(aggregate, dimension)` 的 contribution,再对 `AnsichTaskUsageRow` 无条件赋值;`session.get` 之前没有 `SELECT … FOR UPDATE`,`usage is None` 分支也不是 `INSERT ON CONFLICT`。
- 现状:Task 3 给 `_upsert_high_water_contribution` 加了 lock-before-read(参照 `_recompute_release_quality_stats` 的先例),所以 contribution 行本身在多 worker 下是安全的;但把 contribution 归约成 summary 的这一步没有跟着收口。READ COMMITTED 下两个 worker 交错——A 读到 {c1}、B 插入 c2 并读到 {c1,c2}、B 写 c1+c2、A 写 c1——summary 会丢更新,`as_of`/`complete_through_ingest_seq` 一并回退;`usage is None` 的首写者竞态则会直接撞主键。单 worker 下投影按 ingest_seq 串行消化,贡献集合单调增长,值单调不降,故当前无 active bug。
- 方向:与 F10-6 一并处理,统一按 `_recompute_release_quality_stats` 的 lock-then-read 姿势改写(顺带用 `INSERT … ON CONFLICT` 收口首写者竞态)。
- 归属:Phase 11(与 F10-6 合并处理)。

## F10-21. 生产 effect 恒 `scope_id=None`,两类越权结论不可达

- 状态:⬜ 未修复。来源:加固批 Task 5(effect class 扩充)时确认的**既存**缺口,非本批引入;phase-9-review-followups.md 的 M1 条目里已留档,在此登记为需要 owner 的独立项。
- 位置:`backend/packages/harness/deerflow/ansich/tool_middleware.py`(记录 effect 时 `scope_id=None`,projector 原样拷贝)与 `packages/ansich/ansich/scope_safety.py`(`attempted_scope_violation`/`realized_scope_violation` 都要求 `effect.scope_id is not None`)。
- 现状:领域逻辑与测试都覆盖了这两类结论,但生产路径上没有任何 effect 携带 `scope_id`,因此它们在真实数据上**永远不会产生**。运营者看到的 scope-safety 结论实际只有 `policy_denial` 与 `unverified_effect` 两类;Task 5 新增的 `filesystem_delete`/`permission_change` 也不例外——分类更精确了,可达性没有变。
- 方向:给 effect 绑定 Scope 是独立议题:需要先确定"一次 tool 调用的目标资源属于哪个 Scope"的判定规则(路径前缀?sandbox 挂载点?MCP server 身份?),再在 intent 探针处解析并落到 `scope_id`。在那之前,不要把这两类结论的零命中读成"没有越权"。
- 归属:Phase 11(与 Scope/授权主题同轨);同时应在 UI 或文档上把"不可达"说清楚,避免被读成健康信号。

## F10-22. `sudo`/`env` 等包装命令下的 effect 分类未裁定

- 状态:⬜ 未修复。来源:加固批 Task 5。
- 位置:`tool_middleware.py::_leading_command_word` / `::_bash_effect_class`。
- 现状:首命令词取的是**第一个非环境赋值 token 的 basename**,与 `rm`/`unlink`/`rmdir`、`chmod`/`chown`/`chgrp` 两个精确集合比对。因此 `sudo rm -rf /x`、`env rm x`、`timeout 5 rm x`、`xargs rm`、`command rm` 全部落回 `process_execute` + `unknown`。这个方向是**安全的**(不越权断言),但也意味着一次提权删除在 Scope Effects 面板上与一次普通命令执行长得一样。裁决 HR2 只处理了元字符闸门与 `NAME=value` 前缀,没有对"包装器"这一类给出规则。
- 方向:需要一次独立裁决,而不是顺手加白名单——`sudo`/`env`/`nice`/`timeout`/`xargs`/`command` 各自的参数文法不同(`sudo -u user rm`、`env -i FOO=1 rm`、`timeout 5s rm`),一个"跳过 flag 及其取值"的通用规则很容易把 flag 的**取值**误当成命令词(`sudo -u rm whoami` 里的 `rm` 是用户名,不是命令)。保守可行的中间态是:只解包**无 flag** 的形式(`sudo rm …`、`env rm …`),其余仍退回 `process_execute`。任何方案都要配"包装器带 flag 时不误判"的负向用例。
- 归属:未定,建议随下次触达 `_effect_class` 的改动一并裁决。

## F10-23. assessor 读证据时不 hydrate externalized payload

- 状态:⬜ 未修复。来源:Phase 11 前加固批的**批终审**(不是 Phase 10 终审)。经核实是**既存缺陷**——在该批的基线 `38767157` 上已经是这个形状,非本批引入。
- 位置:`backend/packages/harness/deerflow/ansich/persistence/sql.py::_assess_scope_safety_at`(sql.py:1873-1884)。
- 现状:该函数直接取 observation 行的 `row.payload_json or {}`,随后 `AuthorizationSnapshot.model_validate(payload.get("snapshot"))` / `ToolEffect.model_validate(payload.get("effect"))`,**中间没有任何 `ansich_payloads` 的 hydrate 步骤**。一条走了 externalize 的 `authorization.*`/`effect.*` observation 在库里就是 `payload_json IS NULL`,于是这里拿到 `None`,`model_validate` 直接抛 `ValidationError`。F10-8 修的是**投影认领**那一侧(`contracts.py` 的 envelope 校验器,contracts.py:243-278),这条 assessor 侧的原始行读取是同一危害类下另一条独立的、仍然敞开的兄弟。
- 出错方向(诚实但吵闹的那个):assessor job 按非依赖类异常耗尽 attempts,转成 durable `failed` 并进入 failed-job 诊断面;**不会**产出被伪造的 scope-safety 结论,fail-open 也保持——业务执行不受影响。真实代价是该 ToolCall 的 safety 姿态从「unknown / 未评估」退化成一条需要运维处理的失败作业——且影响面不止这一条 ToolCall:失败的评估会回滚水位推进,`affected` 过滤器也跳不过读不出的行(`_scope_safety_evidence_subject` 对 externalized 行返回 `None`),毒行因此落进之后每一个评估窗口,该 **Task** 的 scope-safety 评估整体停摆,直到失败作业被处理。
- 概率:低。两种 payload 都很小(一个 snapshot / 一个 effect),要越过 `inline_payload_max_bytes` 才会 externalize,默认配置下几乎撞不到——F10-8 的回归用例是把阈值压到 16 字节才逼出来的。
- 方向:二选一——(a) 让这条读走 F10-8 守卫用的同一条 payload-store 读路径,把 externalized payload hydrate 回来再校验;(b) 读不到 payload 时守卫并跳过,同时给该 tool_call 留一个 `unassessed` 标记,不要静默当成「没有证据」。任选其一都要配「externalized authorization/effect 证据下 assessor 不产生失败作业」的回归。
- 归属:Phase 11(与 F10-8 同一危害类,与 F10-6/F10-7 的韧性主题同批)。

## 评审中确认无需跟进的点(留档)

- **"完成 ≠ 正确"在每个边界上都真的被代码执行**:`get_quality_beliefs` 永远吐五个维度并把缺席维度合成为 `unassessed`(`source={"name":"none","version":"1"}`、authority/fidelity 均为 `unknown`、证据为空);TS 类型把 `unassessed` 作为一等字段;`qualityBeliefTone` 先看这个标志再看值;`TONE_STYLES` 把 `unassessed` 与 `unknown` 映射到同一套 muted 处理;e2e 断言已解析的 `fail` 与中性的 `Unassessed` 携带不同的 class。
- **fail-open 是被执行的纪律**:feedback 桥接严格排在主写之后、丢弃回执、吞掉一切,`test_a_failed_feedback_write_never_invokes_the_bridge` 钉住了禁止方向;dismiss 的 override 降级而不回撤;`_UnavailableBackend` 无需新增 stub(R7 被遵守,Protocol 与 InMemory backend 未被触碰)。
- **重放可复现性是真的且有测试**:`test_rebuild_reproduces_index_rows_stats_and_current_beliefs` 对 index 行、Belief 与统计格做快照并断言整轮 rebuild 前后相等,其中包含一次人工 override 压过 benchmark 的情形。
- **R1–R11 全部裁定被合并后的代码遵守**:被丢弃的冗余索引、端到端的量表极性、复数 query key、delta 方向文案——逐条核对无遗漏。
- **文档同步是本仓库见过最完整的一次**:concepts.md §8(含 §9 重编号与悬挂交叉引用修复)、backend/AGENTS.md 的路由行 + 约 80 行小节 + `0023` 条目、frontend/AGENTS.md 的面板/卡片规则、plans/README 的 Phase 10 段落、阶段文档的七条偏离与四条已知限制。

## 计划作者层面的系统性教训(留档)

本阶段五个 Important 级的**计划**缺陷共享同一个形状:计划规定了结构,却没有规定这些结构必须保持的不变量。对每一个读模型、每一个对外发布的数字,计划都应当写出它的不变量、在哪里被执行、在哪里被测试,而不是只列出列。文档任务的文件清单应当从上一阶段的 docs commit 推导,而不是凭记忆罗列(Task 11 的文件清单漏掉 `phase-N-review-followups.md` 这个惯例,正是 F10-1–F10-3 之外还要额外补一份本文件的原因)。

## F10-24. `budget_health:*` 双写者的 `asserted_at` 跨钟决胜

- 状态:⬜ 未修复(证据序的一半已由 HOTFIX-0 `ae731b18` 收敛)。来源:P11-A 批 HOTFIX-0 的根因分析(`.superpowers/sdd/2026-08-19-ansich-p11a-write-resilience/hotfix-0-report.md`)。
- 位置:`backend/packages/harness/deerflow/ansich/persistence/sql.py::_assess_absolute_limits_at`(评估器写者,`asserted_at`=模拟事件时间)与 `::_assess_budget_rows`(终端投影写者,`asserted_at`=真实 ingest 墙钟);`resolve_current_belief` 对两条同 `as_of`、同 `configured_rule` 权威的断言按 `asserted_at` 决胜。
- 现状:证据**顺序**已通过共享纯函数 `ansich.budget.order_wall_time_evidence` + `SqlAnsichBackend._budget_usage_evidence` 在两个写者间收敛(时钟无关性已用 2026/2099 双 fixture 证明)。但两个写者的 `value_json` **结构形状不同**:终端投影写者带 `as_of_known`,评估器写者带 `enforcement`/`shadow`——读者拿到哪个形状取决于同一次跨钟决胜。`get_task_budget_health` 今天用 `.get()` 容忍两种形状,但任何依赖 `enforcement`/`shadow` 字段存在性的消费者会踩中。
- 教训(测试作者规则,已在本条挂账):fixture 时间戳写「当天」会造出定时炸弹——真实时钟越过 fixture 时刻的一瞬,决胜翻转、断言由绿转红且永久。2026-08-20 的全量绿(所有 8/18-19 时间戳已成过去)证明当前无其他潜伏实例;新测试不得让 resolver 决胜落在模拟钟与真实钟之间。
- 方向:二选一——(a) 收敛两个写者的 `value_json` 形状(终端写者补齐 `enforcement`/`shadow` 或评估器改为最小共同形状);(b) 给终端写者的断言一个 resolver 可确定性排序的权威/`config_hash` 维度,使决胜不再依赖钟。任选其一都要配「两个写者交错时读者拿到的形状稳定」的回归。
- 归属:P11-B(与评估器债 F10-6/假说 (c) 同批同轨)。

## F10-25. `record_evaluation` 的重放查询无守卫

- 状态:⬜ 未修复。来源:P11-A 批 Task 8(写侧故障注入验收)的**实测**,修法建议由该 task 的复审给出。经核实是**既存缺陷**——自 `c1349843` 起就是这个形状,非本批引入,本批也按指令只登记不修。
- 位置:`backend/packages/ansich/ansich/service.py::record_evaluation` 的第一步幂等查询 `find_evaluation_observation`,落到 `backend/packages/harness/deerflow/ansich/persistence/sql.py::find_evaluation_observation`。
- 现状:`record_evaluation` 做的第一件事是按 `source_event_id` 查重放,而这次**读**没有任何守卫。存储在那一刻不可用(一次总体故障同时覆盖读)时,异常直接沿调用栈抛给调用方,而不是由 RA6 的回执阶梯答出一个终态。实测捕获(Task 8 的 tail-drop 场景**首轮死在这里**,不是死在断言上):

  ```
  packages/ansich/ansich/service.py:744: in record_evaluation
      existing_obs_id = await find_observation(observation.source_event_id) if callable(find_observation) else None
  packages/harness/deerflow/ansich/persistence/sql.py:3060: in find_evaluation_observation
      async with self._session_factory() as session:
  E   sqlalchemy.exc.OperationalError: (sqlite3.OperationalError) database is locked
  ```

  这一行下游所有为「存储故障时也要诚实作答」设计的东西——RA6 的四级阶梯、入库被拒时的短路、barrier 的 charge——**一律不可达**。(这也是该 task 的故障注入器最终只对**写**生效的原因:注入器一旦覆盖读,场景就死在这里。)
- 严重度受限:HTTP 路由在它上面,5xx 不是静默丢数据,且这是本批之前就有的行为。但周边契约明确说的是「入库 fail-open、回执一定返回」,这里返回的是异常。
- 方向(复审的建议,逐字保留其取舍):在 **ansich 包边界**抛一个**具名的 storage-unavailable 错误**,由路由**现有的 503 路径**接住。明确**不要**的两条:(a) **不要**答 `failed`——`failed` 的含义是「知道它丢了」,而这里是「不知道它是不是一次重放」,把无知说成知情是更坏的谎;(b) **不要**吞掉异常然后照常记录——去重被跳过会铸出一个**幻影回执 id**(同一条 evaluation 记两遍、回执指向第二条),是三个选项里最坏的一个。也**不要**为它新增第四个 `EvaluationProjectionStatus` 取值。
- 优先级:P3。归属:P11-B(与 F10-7 的回执主题、B 批的丢失上报路径同一块代码)。
- 与保留策略的耦合(batch C 必读):RA6 的第 3/4 档是从「库里有没有这条 observation / 它的 job」反推回执的,所以**删除**一条 observation 或它的 job 会让一条**曾经活过**的行的回执答案翻成 `failed`。C 批的 retention 删除必须把这条语义算进去。

## F10-26. rebuild 完整性:重建可能在依赖延迟的 job 未结算时就宣告完成

- 状态:⬜ 未修复。来源:P11-A 批 Task 2 复审提出的机制假说(裁决 PA10 已入账),本批共四次目击。
- 位置:`backend/packages/harness/deerflow/ansich/persistence/sql.py::rebuild_projections` 的完成条件,与 `_ProjectionDependencyPending` 的延迟重排路径(带 250ms 退避的依赖等待)。
- 机制假说(复审给出,尚未用插桩证实):`rebuild_projections()` 以「这一轮没有可投影的 job」作为完成条件退出,而一个 dependency-pending 的 job 此刻**不在**可投影集合里——它在等自己的依赖。于是重建可以在仍有 job 未结算时就返回,调用方紧接着读到的是一份**不完整**的投影。这解释了为什么这一族的失败形状永远是「实时值 ≠ 重建值」或「重建结果为空」,而不是数值算错。
- 本批四次目击(单跑必过,全部在套件负载下):
  1. **Task 2(在 BASE 上)**:`test_sql_task_lifecycle.py::test_tool_call_projection_survives_restart_and_rebuild_without_usage_duplication` —— `assert rebuilt_tool_call == before_tool_call`,重建侧 `derivations=()`。
  2. **复审的机制假说**(不是一次红,是这一族第一次有了具体机制):即上面那条,由 Task 2 的复审在同一条 flake 上给出,并由裁决 PA10 归口 P11-B。
  3. **Task 4**:`test_sql_task_tree.py::test_usage_rolls_up_two_levels_and_backfills_a_late_spawn_without_double_counting` —— `assert root_usage == rebuilt`(两侧都是 `TaskUsageView`,`-q` 没给出字段级差异);单跑绿 ×4,整文件 8 passed,同一测试在该轮的另两次全量跑里也是绿的。
  4. **Task 6(文本完整)**:`test_sql_evaluations.py::test_rebuild_reproduces_index_rows_stats_and_current_beliefs` —— `assert before == after`,而 `after` 是**空的**(`'stats': ()`、`'index': ()`):**重建什么都没产出**。这一条最贴合机制假说,也是本条最强的一次证据。
- 为什么它不是 F10-10 的同一件事:F10-10 是「后台评估写者与测试自己驱动的评估赛跑」,门禁 `only_test_driven_assessments` 已经把那个写者按住;这一族的失败与评估无关,失败的是**重建自身的完整性**,而 barrier / 写侧改动只能让写入更宽、不可能更窄(`rebuild_projections()` 读的是持久流)。两族必须分开记,否则会把「等更久就好了」的错误结论套到这一族上。
- 方向:让 `rebuild_projections()` 的完成条件把 dependency-pending 的 job 算进去——要么等它们结算或越过 `projector_dependency_timeout_seconds` 转 durable failed,要么在返回值里**显式报告**「仍有 N 个未结算」,由调用方决定。任何修法都要配一条「依赖延迟 job 未结算时重建不报完成」的回归;这同时是 §5 versioned replay「两次重放 digest 相同」得以成立的前提。
- 归属:P11-B(重放诚实性)。

## F10-27. 装配不对称:无存储分支漏传三个 knob

- 状态:⬜ 未修复。来源:P11-A 批 Task 8 复审的**具名 non-fix**(测试 task 不动生产装配)。
- 位置:`backend/packages/harness/deerflow/ansich/__init__.py::create_embedded_ansich_service` 的 `session_factory is None` 分支。
- 现状:该分支传了五个 writer knob,却**没有**传 `terminal_flush_timeout_ms` / `projector_poll_interval_ms` / `operations_assessment_interval_ms`,于是一个无存储的服务用构造函数默认值跑这三项。今天是**惰性的**——那个服务拒绝每一条 record、也没有 projector,所以没有 active bug;但它是一处真实的不对称:下一个 knob 加进 SQL 分支时,同一个漏法会静默重演,而且正是这种漏传最不容易被发现(两个分支各自都能构造成功)。
- 侦察附注(同一处的另一半,登记在此以免再被当成新发现):`operations_assessment_interval_ms` **至今没有 `AnsichConfig` 字段**——它只是 `create_sql_ansich_service` 的一个 kwarg,生产装配从不传它,因此生产上恒为构造函数默认值 **1000ms**。读本仓库的 ansich 配置时不要以为这个间隔可配;它同时也是 F10-10 里「默认档 1 Hz」那一半的来源。
- 方向:两件事一起做——(a) 让两个分支共用一份 knob 映射(或让无存储分支复用同一个 kwargs 字典),使漏传在结构上不可能;(b) 若要让运营者能调这个间隔,给 `operations_assessment_interval_ms` 补一个 `AnsichConfig` 字段(startup-only,与本节其余字段同姿势并同步 `config.example.yaml`),否则在文档里写明它不可配。
- 归属:P11-B,或下一次触达 ansich 配置/装配的改动顺带处理。

## F10-28. 健康线的两处 UI 级留观(P11-A 批 T9 复审遗留)

- 状态:⬜ 未修复。来源:P11-A 批 Task 9 的两轮评审,批终审确认需要持久落点(此前只在 SDD 台账里)。
- 第一处——中性线态的渲染层零覆盖:`frontend/src/components/workspace/ansich/projection-health.tsx` 的图标选择是一个裸三元式(`line === "healthy" ? ActivityIcon : CircleHelpIcon`),本批(PA15)恰好**反转过一次**它的锚定条件;纯函数层(resolver 的 `line` 四态)已被突变验证充分钉住,但 JSX 分支没有任何测试执行——e2e 夹具只有 `healthy`。把它反转回去,翡翠"完整"图标会重新出现在 phase 线上,而所有现有 gate 保持全绿。
- 验收准则(评审已给定,照此写用例):**翡翠 `ActivityIcon` 只属于 `healthy`;phase 与 unknown 两种线态都必须是哑光 help 图标**。落法:一组「中性线态」e2e 用例(`starting` 夹具 + `unknown`(计数不可用)夹具),与既有 ansich e2e 同套路(路由桩)。仓库没有组件级 DOM 测试设施,e2e 是唯一载体。
- 第二处——task 作用域在系统 phase 期间的诚实性:`taskProjectionScope` 在无硬故障、无本任务 attention 时把 status 合成为 `"healthy"`,于是系统 `starting`/`shutting_down` 期间任务页仍渲染绿色「本任务数据完整」——PA15 刚在系统作用域移除的那句话,在下一层原样存在。与既定规则(任务只继承硬故障)一致,且两个 phase 在 HTTP 上近乎不可观测(lifespan 先启服务后放流量、关停先排空请求),故为 minor;但它与第一处是同一个诚实性问题,修第一处时应一并裁定(方向:phase 期间任务页也用 phase 线态,或在文档里明确接受)。
- 归属:下一次触达该组件的 UI 批(或 P11-B 若其健康面板工作触达此处)。
