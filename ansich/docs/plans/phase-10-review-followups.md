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
| F10-6 | 兄弟 rollup(`_refresh_behavior_belief`、usage/budget 读模型)仍是未串行化的 read-modify-write | ✅ 已修复(**运维 tick 侧的首写者残留已由 P11-C 收口**;投影路径那半边仍是有界自愈形状,见该条) | 2026-08-21 / 2026-08-22 | `82958027` / `029c549e` / `8fbc18df` / `ade44649`(tick 侧首写者 `f1d52a79`) |
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
| F10-19 | late spawn 边与 sum 型 contribution 并发时存在**永久**丢失窗口(wall_time 可自愈,token/step/tool 不可) | ⚠️ 部分修复(窗口收窄,PB8 的 DOMAIN 残留**永久**,见该条) | 2026-08-21 | `29d832ee` / `e7c7bc8c` / `48e580cc` |
| F10-20 | `_refresh_usage_summary` 仍是未加锁的全量重算+无条件赋值——F10-6 的同族问题,就在本批加锁那一层的上面 | ✅ 已修复 | 2026-08-21 | `82958027`(PG 丢更新证伪 `562d1297`) |
| F10-21 | 生产路径的 effect 恒 `scope_id=None`,`attempted_/realized_scope_violation` 两类结论在生产上不可达 | ⚠️ 部分修复(**诚实半边已落**:Scope Effects 视图声明不可达;Scope 绑定设计仍开着) | 2026-08-23 | `89f7a55c` |
| F10-22 | `sudo`/`env`/`timeout` 等包装命令下的 effect 分类未裁定,`sudo rm -rf` 目前落回 `process_execute` | ⬜ 未修复(P11-C **明确不建**,理由入该条) | — | — |
| F10-23 | `_assess_scope_safety_at` 直接校验原始行的 `payload_json`、不 hydrate externalized payload,externalized 的 `authorization.*`/`effect.*` 证据会把 assessor job 打成 durable failed(F10-8 同一危害类的 assessor 侧兄弟,既存) | ✅ 已修复(全扫残留见该条) | 2026-08-21 | `35aece8a` |
| F10-24 | `budget_health:*` 有两个生产写者,`asserted_at` 决胜在模拟事件钟与真实 ingest 墙钟之间比较——证据序已由 `order_wall_time_evidence` 收敛(`ae731b18`),但**断言结构形状**(`as_of_known` vs `enforcement`/`shadow`)仍随决胜漂移 | ✅ 已修复(两半) | 2026-08-21 | `ae731b18`(证据序) / `c7ce07a8`(形状) |
| F10-25 | `record_evaluation` 的重放查询无守卫:存储不可用时 `OperationalError` 直接抛给调用方,RA6 回执阶梯整条不可达(既存,自 `c1349843`) | ✅ 已修复 | 2026-08-21 | `35aece8a` / `0d9aa3cb` |
| F10-26 | rebuild 完整性:`rebuild_projections()` 可能在依赖延迟的 job 尚未结算时就以「首轮空扫」宣告完成(本批四次目击) | ✅ 已修复(改为显式报告 `unsettled`) | 2026-08-21 | `d2cd58d2` / `7ad37ce7` |
| F10-27 | 装配不对称:`create_embedded_ansich_service` 的无存储分支漏传三个 knob;`operations_assessment_interval_ms` 至今没有 `AnsichConfig` 字段,生产恒为 1000ms | ✅ 已修复(两半) | 2026-08-21 | `c7ce07a8` / `625a056c` |
| F10-28 | 健康线的两处 UI 级留观:中性线态(phase/unknown)的**渲染层**零覆盖(图标三元式曾在本批被反转过);task 作用域在系统 phase 期间仍称「本任务数据完整」 | ⬜ 未修复 | — | — |
| F10-29 | 环境外部化载荷类:externalized 的 `environment.sampled` 读不回(契约分支无守卫直接抛)、认领不了(先 envelope 后 hydrate 的顺序把投影作业卡死在认领处)、history 读者守卫跳过(其"从不外部化"注释已撤回)——同一危害类三实例,收口时又扫出同类的第四、五个分支 | ✅ 已修复 | 2026-08-22 | `393a01e2` / `abefcb01` |
| F10-30 | settle-budget flake 家族(与 F10-10 分开记):`tests/ansich/` 里全部「settle 之后紧接着读投影结果」的断言的等价类(最初以为只在 `test_sql_safety.py` 里,成员 6/7/8/9 证否;共十二名成员,第十、十一、十二名由 P11-C 的 Task 1 / Task 2 / Task 11 补登),多种构造、同一机理——flush 预算输给负载,行退回队列/作业未建;F10-10 的节奏门禁管不了 flush 预算。**不限于重负载**:成员 1/5 在安静机单独跑也翻红(T6 记),故按用例名而非行号认领(合并门禁的窄口见本条收尾) | ⬜ 未修复(测试侧;十二名成员,成员 5 已结案、成员 1 部分处理——见该条) | — | — |
| F10-31 | LLM attempt 双观测的首写者 pkey 竞态:两 worker 各投影同一 attempt 的 request/response 观测,`ansich_llm_attempts_pkey` 碰撞——非破坏(输家整事务回滚→retry→收敛,和数正确),但需要第五处 lock-then-read 转换 | ✅ 已修复 | 2026-08-22 | `f1d52a79` |
| F10-32 | 活动 Task 读模型的「旧盖章」楔子:`c7ce07a8` 之前写下的行带旧语义水位,遇 durably failed 作业时被单调发布守卫永久跳过(已停 Task 那半边**静默**)。接受它的前提是「没有已部署群体」,而该前提**在此分支首次部署时失效** | ✅ 已修复(**前提被杀掉,而不是被重判**:`0028` 的数据步删空该读模型表) | 2026-08-22 | `c0cdbfa3`(链:`d1b595b9` / `1d23af18` / `32097626`) |
| F10-33 | 多 worker 下同一 host-Scope episode 并发碰撞 `uq_ansich_alert_episode`,一次碰撞丢掉**整轮** `assess_operations`(heartbeat/dwell/budget/environment 与两个生产者一起)——不腐蚀、下一轮自愈、已限速可见 | ✅ 已修复 | 2026-08-22 | `f1d52a79` |
| F10-34 | PG tier 的 `_drain_projections` 在**退避中的 `retry` 作业**面前停手,调用方把它当成「投影已完结」——同文件的 `_settle_projections` 正是为这半件事存在的,只是那个调用点没用它。**不是 F10-30**(不是 settle 预算输给负载),也**不是 F10-26**(不是重建单轮被当成完成) | ✅ 已修复(测试侧;那个调用点已改用 `_settle_projections`) | 2026-08-22 | `f1d52a79` |
| F10-35 | `ansich_current_beliefs` 首写者竞态的**整轮**爆炸半径:两 worker 的 1 Hz `assess_operations` 各自首写同一 `(task_id, "heartbeat")` 当前 Belief 行,`ansich_current_beliefs_pkey` 碰撞炸掉整个 tick 事务——与 F10-33 逐字同形,此前被 F10-31 的类型化容忍遮蔽 | ✅ 已修复 | 2026-08-22 | `f1d52a79` / `d2ca0392` |
| F10-36 | **认领处的抛永远变不成一条运维可见的失败作业**:抛回滚自己的认领事务(`attempts` 不涨、作业到不了 `failed`),`_project_pending` 的 `except Exception: return 0` 吞掉它,而认领按 `ingest_seq` 排序——毒行一旦是最低可认领作业,**全进程投影永久静默停摆**,health 仍报 `reachable`/`failed_jobs=0` | ⚠️ 部分处理(方向 (c) 已落:那句 `except` 现在按窗限速打 DEBUG+WARNING;**停摆本身未修**,且与 RC6 的「响亮」第三态互为输入,见该条) | 2026-08-23 | `f5e57238` |
| F10-37 | `_project_control` 不幂等:对一条已投影的 control 观测重放会撞 `ansich_transitions.evidence_obs_id` 唯一约束 ⇒ `retry` → `failed`,所以 `task-control` 的**普通**重放今天就是坏的(rebuild 不受影响) | ⬜ 未修复(已在 `_NON_IDEMPOTENT_PROJECTORS` 登记,CLI 两处 stderr 警告) | — | — |
| F10-38 | owner/thread 强删除的**三条** v1 已知形状:被**类型拒绝**的实体 pin、**互相 pin**(两条都被如实拒绝),以及 `blocked` 之后到恢复之前的**复活窗口**(phase 2 已提交、Observation 还在,一次 replay/rebuild 会把 Task 行与读模型重新派生出来)| ⬜ 未修复(v1 限制,前两条已诚实拒绝;第三条已写在删除路径的 docstring 上) | — | — |
| F10-39 | 保留策略下的无界增长残余:`ansich_content_blobs` 的 `inline_body`(阈值以下的正文,任何 tier 都不碰)、尚无 tier 触达的 blob 行,以及 tier 1 留下的 tombstone 空壳 | ⚠️ 部分收窄(T10 的 `_apply_plan_and_reclaim` 让三个删除者都回收自己弄成孤儿的 blob 行与正文;**不构成回收 tier**) | 2026-08-22 | `e764de4f` |
| F10-40 | tier 2 删掉一条**活认领者**正在投影的观测时,投影方的外键失败经 `_record_projection_error` 的 `job is None` 早退**完全静默**:不计数、不打日志、不重臂,`stale_completion_count` 那条先例没有被套用 | ⬜ 未修复(有界、不毒批,但零可见性) | — | — |
| F10-41 | **时间 retention 的三层没有任何调用者**:`run_retention` 只被测试调用——不在运维 tick 里、没有调度器条目、没有路由,所以 §6 测过的每一种保留状态在生产上都产不出来,`retention_last_run` 永远是 `None` | ⬜ 未修复(能力已落地、未接线;owner 强删除**不在**本条范围,它有路由) | — | — |
| F10-42 | **P11-C 的遗留小项池**(批终审 B7 的分池 1/2 收口):T9b 的七条未路由小项、T6 的 N1–N4,以及批终审自己判为「登记即可」的两条(§7 审计行没有自己的下界;`--replace` 之外的三条 LOW 已就地修掉)| ⬜ 未修复(登记项,逐条带方向与归属) | — | — |

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

- 状态:✅ 已修复(2026-08-21,P11-B 批 Task 5,`82958027`;锁**序**由 `029c549e`/`8fbc18df`/`ade44649` 三次补齐;**运维 tick 侧的首写者残留 2026-08-22 由 P11-C 批 Task 11 `f1d52a79` 收口**,见下面的残留段)。四处 rollup 全部拉到参考实现 `_recompute_release_quality_stats` 的姿势:`_refresh_behavior_belief`、`_refresh_active_task_read_model`、`_project_budget`,以及单独登记的 `_refresh_usage_summary`(F10-20)。四个细节值得记:
  - **先锁目标行、再读输入,并且是一次「调用」而不是读上的一个标志**:`_lock_rollup_targets(session, statement)` 必须由读的那段代码先调用,所以「读完再锁」在结构上写不出来(锁在读之后会留下一模一样的窗口)。`FOR UPDATE` 在 SQLite 上是 no-op,那里本来就只有一个写者。
  - **首写者是锁做不到的那一半**:`FOR UPDATE` 锁不住还不存在的行,于是每处配 `_insert_ignoring_conflict`(`INSERT … ON CONFLICT DO NOTHING`,返回「这次是不是我赢的」),输家重读赢家那行——此刻已可加锁——再收敛上去。这两个 helper 合起来就是本仓库今后所有聚合读-改-写的**既定写法**。
  - **多行 rollup 取锁前先排序**:usage 扇出、spawn backfill、environment 的 per-metric 更新都排序后再取锁,否则两个进程按 `set`/`dict` 的原生序遍历会在真 PG 上死锁(T9 的 tier 实测到 PostgreSQL 中止其中一方)。死锁自由的正面论证(serializing prefix:两条扇出路径都在拿聚合行之前先拿贡献行,并按聚合升序走)写在 `_backfill_spawn_usage` 的注释里。
  - **PG 实证**:T9 的双 worker tier 在真 PostgreSQL 上把改前的未加锁读跑成**红**(同一交错下祖先只拿到 59 tokens,正确值 107),改后同一交错绿(`562d1297`)。SQLite 侧只能钉语句顺序,那由 `tests/ansich/test_rollup_serialization.py` 负责。
- **残留(不要把本条的 ✅ 读成「首写者竞态已清零」)**:
  - ~~site-1 共享的 `_resolve_current_assessment` 的首写没有一并收口~~ —— **已由 P11-C 批 Task 11 收口(`f1d52a79`,`d2ca0392` 补锁序)**。该函数现在走 `_open_or_lock_current_belief`(`INSERT … ON CONFLICT DO NOTHING` + 赢家行 `FOR UPDATE` 重读)并改成**有界两遍**:输掉的那一遍必须**重新归约**,因为对手的 Assertion 在第一遍的 READ COMMITTED 快照里不可见,拿旧答案发布正是锁要阻止的丢更新。收口的动机不是本条原来记的「一次可重试的 attempt」——见 `F10-35`:这个碰撞真正炸掉的是**整轮** `assess_operations`,而不是一个作业事务。原来挂在 `F10-18` 的那一行随之作废。
  - **仍然开着的是另一半,不要混读**:同一张 `ansich_current_beliefs` 的两处**纯投影路径**写入(`_project_control` 的 control 场、ToolCall 终态的 execution 场)**刻意未转换**——那里一次碰撞的代价是一个作业事务加一次 `retry`,即本条一直记录的有界自愈形状。`F10-35` 的条目里写清了边界并不齐整:被转换的三处里 `_assess_budget_rows` 自己也坐在投影路径上(`_project_control` 的终态分支会调它),那条路径上的行为因此**变了**(回滚重来 → 提交并多留一条同判定 Assertion)。
  - `_refresh_active_task_read_model` 上还有一层与锁无关的残留:它的输入读在更早的**已提交**会话里,锁串行化的是写者不是计算,所以更旧的一轮 tick 可能后完成。这一层由 T10 的单调发布守卫(裁决 PB7,`c7ce07a8`;UPDATE 与 DELETE 两边都守,`625a056c`)关闭,不是本条修的。
  - LLM attempt 投影站的同型首写者竞态在本批的 PG tier 上被实测到,单列 `F10-31`。
- 原始诊断(留档):
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
    - **这条计数断言的实测结果(P11-B Task 3,2026-08-21;不改本条状态,状态归 T12)**:已补,已收敛 ToolCall 的 `ansich_scope_conclusions` 是 **8**,而 8 正是诚实值——该测试的 trigger 本身就是 settled ToolCall 的 `effect.observed`,重判有真凭据。也就是说**这条测试证伪了假设 (c) 在它自己那个形状里的可达性**,它测的是「吸收 + 评估回滚」,不是「晚到低水位」。假设 (c) 的机制在代码里为真,但要复现必须让某个 job 的 watermark 落在**已推进的 mark 之下**——载体是任何「投影被推迟、但断言仍能提交」的行:`scope.snapshotted`(不指名 ToolCall),以及**卡在 Scope 而不是 ToolCall 上**的 `authorization.*`/`effect.*`(`_project_authorization_snapshot` 先查 ToolCall 再查 Scope,所以主体 Entity 在场、跨越它的评估照常提交、mark 照常推过去)。只有卡在 **ToolCall** 上的证据行才会让跨越它的评估回滚、mark 推不过去。(本条曾一度写成「载体只能是 `scope.snapshotted`」,该排他性说法**已撤回**:复审用一条卡 Scope 的 authorization 在 seq 5、mark 推到 6 的探针证伪了它。)新增的红先回归:`test_a_dependency_deferred_job_below_the_mark_re_judges_its_band_once`(去掉恢复后 mark 由 10 退到 5)、`test_a_truncated_late_evaluation_cannot_leave_a_belief_regressed`(裁决 PB5:晚到 job 若只读到自己的低水位,会用**被截断的证据**把 `unverified_effect` 从 cleared 改回 present,而恢复了 mark 之后**再没有窗口回来修**——实测三态:修复前 present→下一轮 cleared(意外自愈)、只有恢复 present→present(永久)、恢复+PB5 cleared→cleared)。
    - **机制已根治(P11-B 批 Task 3,2026-08-21,`d2cd58d2` + `7ad37ce7`;docstring 更正 `563aeb6e`)——但状态行不改,理由见下**。落地的是本条写的候选修法加上一条裁决:`_claim_assessor_job` 记住**下调前**的 mark,`_advance_assessor_watermark` 推进到 `max(本次评估水位, pre-claim 水位)`(裁决 PB5),所以 mark 不再被一条晚到的低水位 job 永久下调。配套的 PB4 把「被接管的 assessor 完成」整条评估事务回滚(断言、告警 episode 与 mark 与作业状态同生共死),否则一次陈旧推进会把新 owner 认领时的加宽抹掉。**三条不许写错的措辞**:
      1. PB5 消掉的是「重判过宽」的**复发**,它把那一轮宽重判**搬进**了晚到 job 自己的那次评估——**不要写成「机制消失」**:那一轮里 `subjects_per_round` 仍然可以大于 1。
      2. PB4 回滚之后 PB5 会退化成**瞬态**(方向安全、自会纠正),这一点写在 `effective_watermark` 现场的注释里。
      3. 本条**第 4 项与 `[0, 2, 3, 1, 1]` 那条 flake 的因果仍未证实**:T3 的计数断言在它自己的形状里**证伪**了假设 (c)(见上一条),红先回归是另起的两条。所以「机制在代码里为真且已修」与「它就是那条 flake 的成因」是两句话,**「先抓失败文本再修」这条规矩继续有效**。修完之后争用下仍然翻红的那些,形状属于 `F10-30`(settle 预算),不是本条。
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
  - **裁决(2026-08-23,P11-C 批终,裁决 RC14):DEFERRED,并附一条本批亲自核过的确认。** P11-C 的 replay 与 retention 查询**没有一条按 JSON 内容过滤**:目标集过滤走 kind / `task_id` / `occurred_at` / `ingest_seq`(全部有索引),retention 三个 tier 走 `created_at` / `occurred_at` / `ingest_seq` / `entity_id`,§7 审计写入按 `source_event_id` 的唯一索引去重。因此本批**没有新增任何按内容过滤的消费者**,迁移的触发条件仍是原来那条——「第一个真的要对 `*_json` 列做包含查询或 GIN 索引的消费者」。在那之前,一次跨全部 JSON 列(含 Ansich 之外的 `runs`/`run_events`)的迁移换不到任何东西。
- P11-B 的 `projection_failure` 生产者(`sql.py::_assess_projection_failures`)**只覆盖投影作业**:证据链是失败作业自带的 `obs_id`,而 `ansich_projection_jobs.obs_id` 是真列、`ansich_assessor_jobs` 只有 subject 与 `evidence_watermark`,没有自己的 Observation。因此一条 durably failed 的 **assessor 作业不产生任何 Alert**,只经由共享的 failed-job 计数与 `GET /operations/failed-jobs` 到达运营者。要补上需要按 `evidence_watermark` 反查证据(可行,但那是另一套证据推导),留待需要时;边界已写在生产者 docstring 与 `ansich/process_health.py::assess_projection_failure` 里,并由 `tests/ansich/test_process_health_alerts.py::test_a_failed_assessor_job_produces_no_projection_failure` 钉住。
- ~~`_resolve_current_assessment` 的**首写者**半边没有随 F10-6 的 lock-then-read 一起收口~~ —— **已结清(2026-08-22,P11-C 批 Task 11,`f1d52a79`)**,详见 F10-6 的残留段与 F10-35。本行留档只为记两处**当时的诊断被后来的实测改正**:其一,代价不是「一次可重试的 assessor attempt」,而是**整轮** `assess_operations`(F10-35);其二,修法不是「补一处 `_insert_ignoring_conflict`」就够,还需要输家**重新归约**一遍(READ COMMITTED 下对手的 Assertion 在第一遍不可见)。「第五处 lock-then-read 转换」的编号归属(F10-31,不归本行)这一条记账更正仍然成立。
- Task 9 的 PostgreSQL tier 文档里那条 `docker run ... postgres:16` 启动一行**本身没有被执行过**——该环境里 Docker 守护进程不可用,实际验收跑在一个由 `pgserver` wheel 自带的官方 PostgreSQL 16.2 二进制 `initdb` 出来的一次性本地 cluster 上(同一份服务端软件、同一个 5433 端口与 URL)。命令是标准写法,但"照抄即可跑通"这件事没有证据,`backend/Makefile` 的注释已就地标注。

## F10-19. late spawn 与 sum 型 contribution 的永久丢失窗口

- 状态:⚠️ **部分修复**(2026-08-21,P11-B 批 Task 6,`29d832ee`;gate 与文档更正随 `e7c7bc8c`,窄口/退避钉子随 `48e580cc`)。**为什么不是 ✅**:本条的标题写的是「**永久**丢失窗口」,而裁决 PB8 明确「登记,不建」——下面那段 DOMAIN 残留(一个活得比自己租约还久、又没人重认领的 usage 事务)**仍然是永久的**,只是范围窄了一大截。一个 ✅ 挂在这样一句标题下会被读成「窗口已消失」,而本条自己的收尾句正是在防这件事;2026-08-22 的批终审(T12 遗留项 2)据此改标。**行锁关不掉这个窗口**——行锁约束的是一行既有行的写者,不是一个集合的成员资格,所以修法不是加锁而是一次对账:spawn 边投影时在**边自己的事务里**入队一条 `task-spawn-reconcile@1` 作业(幂等键 `uq_ansich_projection_job_version`),被认领后由 `_reconcile_spawn_usage` 对完整闭包重跑一遍扇出。不双计是既有的幂等性给的(`_store_usage_contribution` 对 sum 型按 `(aggregate, source, dimension, source_obs_id)` 走 `ON CONFLICT DO NOTHING`,`wall_time_ms` 走高水位 CAS),所以重跑(retry、同祖先下的第二次 spawn、`rebuild`)是免费的。
- 一次对账只**收窄**窗口,不关闭它,因此另配了一个在飞闸门:等待该子树下任何**活着**的 `task-usage` 租约结算(作为可重放的依赖等待,把 attempt 还回去)。它的可靠性压在一条不变量上——认领在自己的事务里先提交 `processing`,完成才与投影一起提交——该不变量由 `tests/ansich/test_spawn_usage_reconciliation.py::test_a_claim_is_committed_before_its_projection_work_begins` 钉住;把认领并进工作事务会**静默**地让闸门失效。
- **DOMAIN 残留(裁决 PB8:登记,不建)**,逐字保留 `_reconcile_spawn_usage` 里的那段:

  ```
  DOMAIN (what this gate does NOT cover). Only a *live* lease is waited
  on, and an expired one is NOT self-healing in general. Lease expiry
  does not invalidate anything by itself: `_complete_projection_job`'s
  compare-and-set is on `lease_generation`, which only a *re-claim*
  raises. A usage transaction that outlives its own lease with nobody
  re-claiming it therefore still commits its contribution and still
  settles its job -- landing an ancestor-less row after this pass has
  already finished. So the honest statement is not "no window": it is
  that the reconciliation turns "any interleaving loses the
  contribution permanently" into "only a usage transaction that
  outlives its lease does". Waiting on expired leases too would trade
  that residual for an unbounded wait on a worker that may be gone, and
  would still not cover it (the expired-lease worker can commit at any
  later moment). The real-interleaving proof of the remaining window
  belongs to T9's PostgreSQL two-worker scenario list.
  ```

  关闭它需要一个跨路径的串行化锚(后代 Task 行锁)并自带死锁面,而残留的范围是「一个活得比自己租约还久、又没人重认领的 usage 事务」;T9 的双 worker tier 已把闸门的 live/expired 两条分支都在真 PG 上跑过。下一次触达此处时再裁,不要把本条的 ✅ 读成「窗口已消失」。
- 来源(留档):Phase 11 前加固批 Task 3 的复审(不是 Phase 10 终审)。
- 位置:`backend/packages/harness/deerflow/ansich/persistence/sql.py::_backfill_spawn_usage`(读后代 self 行、写祖先行,刻意不加锁)与 `::_project_usage`(新贡献按当时可见的 ancestry 扇出)。
- 现状:两条路径各自读一次 ancestry / 后代贡献集合,中间没有共同的串行化点。一条后代贡献若在 `_backfill_spawn_usage` 读完之后才提交,而它自己的 `_project_usage` 又跑在 spawn 边可见之前(此时祖先集为空),这条贡献就**再也不会**到达祖先。wall_time 不受影响——它是 max 型,下一个 tick 的扇出会把水位抬平;`total_tokens`/`steps_*`/`tool_calls_executed` 这些 sum 型维度没有这种自愈,祖先的 inclusive 值会**永久偏低**。`_backfill_spawn_usage` 的 docstring 已经点明"行锁挡不住新行插入",即这个窗口结构上不是加锁能关的。
- 方向:需要一个把"spawn 边可见"与"该后代的贡献集合"串起来的点——例如 spawn 投影完成后按后代 Task 重新触发一次 fan-out 对账(幂等键已经保证不会双计),或把 inclusive 汇总改成读时按 ancestry join 而不是写时扇出。任选其一都要配"贡献与 spawn 边并发到达时 inclusive 不丢"的回归。
- 归属:Phase 11(多 worker / 生产隔离),与 F10-6/F10-20 同一批。单 worker 下投影 job 串行消化,窗口不成立,因此当前不是 active bug。

## F10-20. `_refresh_usage_summary` 仍是未串行化的读-改-写

- 状态:✅ 已修复(2026-08-21,P11-B 批 Task 5,`82958027`)。与 F10-6 同一次改动、同一个姿势:`_refresh_usage_summary` 先 `_lock_rollup_targets` 锁住 `AnsichTaskUsageRow` 目标行,再重扫该 `(aggregate, dimension)` 的 contribution;`usage is None` 的首写走 `_insert_ignoring_conflict` 后重读赢家行。**丢更新的证伪是在真 PostgreSQL 上拿到的**:T9 双 worker tier 用 monkeypatch 只在一个 worker 上还原「未加锁的读」,同一交错下祖先 summary 少算(59 vs 107),改后绿(`562d1297`)——这正是本条登记时说的「只有多 worker PostgreSQL 能证伪」。来源(留档):Task 3 复审,是 F10-6 的同族问题,登记为独立条目是因为它就在当时刚刚加锁的那一层的**上面**一层。
- 位置:`sql.py::_refresh_usage_summary`——全量重扫该 `(aggregate, dimension)` 的 contribution,再对 `AnsichTaskUsageRow` 无条件赋值;`session.get` 之前没有 `SELECT … FOR UPDATE`,`usage is None` 分支也不是 `INSERT ON CONFLICT`。
- 现状:Task 3 给 `_upsert_high_water_contribution` 加了 lock-before-read(参照 `_recompute_release_quality_stats` 的先例),所以 contribution 行本身在多 worker 下是安全的;但把 contribution 归约成 summary 的这一步没有跟着收口。READ COMMITTED 下两个 worker 交错——A 读到 {c1}、B 插入 c2 并读到 {c1,c2}、B 写 c1+c2、A 写 c1——summary 会丢更新,`as_of`/`complete_through_ingest_seq` 一并回退;`usage is None` 的首写者竞态则会直接撞主键。单 worker 下投影按 ingest_seq 串行消化,贡献集合单调增长,值单调不降,故当前无 active bug。
- 方向:与 F10-6 一并处理,统一按 `_recompute_release_quality_stats` 的 lock-then-read 姿势改写(顺带用 `INSERT … ON CONFLICT` 收口首写者竞态)。
- 归属:Phase 11(与 F10-6 合并处理)。

## F10-21. 生产 effect 恒 `scope_id=None`,两类越权结论不可达

- 状态:⚠️ 部分修复(2026-08-23,P11-C 批 Task 14,`89f7a55c`)。**只有诚实那半边落了地**,机理半边一行没动。来源:加固批 Task 5(effect class 扩充)时确认的**既存**缺口,非本批引入;phase-9-review-followups.md 的 M1 条目里已留档,在此登记为需要 owner 的独立项。
- **落地的半边(裁决 RC14):** `frontend/src/components/workspace/ansich/scope-effects-panel.tsx` 的 Scopes 卡片底部常驻一句声明(`t.ansich.scopeViolationUnreachable`,两份 locale 都有),说明生产路径上记录的 effect 一律不带 Scope 绑定,因此两类 scope-violation 结论**在那里根本产不出来**——它们的缺席是仪表的性质,不是关于这个 Task 的证据。这句话的全部作用是**不让沉默被读成体检合格**;组件里配了一段注释说明它为什么必须留着。
- **没落地的半边:** effect 的 Scope 绑定本身。下面的「方向」原样有效,归属不变。
- 位置:`backend/packages/harness/deerflow/ansich/tool_middleware.py`(记录 effect 时 `scope_id=None`,projector 原样拷贝)与 `packages/ansich/ansich/scope_safety.py`(`attempted_scope_violation`/`realized_scope_violation` 都要求 `effect.scope_id is not None`)。
- 现状:领域逻辑与测试都覆盖了这两类结论,但生产路径上没有任何 effect 携带 `scope_id`,因此它们在真实数据上**永远不会产生**。运营者看到的 scope-safety 结论实际只有 `policy_denial` 与 `unverified_effect` 两类;Task 5 新增的 `filesystem_delete`/`permission_change` 也不例外——分类更精确了,可达性没有变。
- 方向:给 effect 绑定 Scope 是独立议题:需要先确定"一次 tool 调用的目标资源属于哪个 Scope"的判定规则(路径前缀?sandbox 挂载点?MCP server 身份?),再在 intent 探针处解析并落到 `scope_id`。在那之前,不要把这两类结论的零命中读成"没有越权"。
- 归属:Phase 11(与 Scope/授权主题同轨);同时应在 UI 或文档上把"不可达"说清楚,避免被读成健康信号。

## F10-22. `sudo`/`env` 等包装命令下的 effect 分类未裁定

- 状态:⬜ 未修复。来源:加固批 Task 5。
- 位置:`tool_middleware.py::_leading_command_word` / `::_bash_effect_class`。
- 现状:首命令词取的是**第一个非环境赋值 token 的 basename**,与 `rm`/`unlink`/`rmdir`、`chmod`/`chown`/`chgrp` 两个精确集合比对。因此 `sudo rm -rf /x`、`env rm x`、`timeout 5 rm x`、`xargs rm`、`command rm` 全部落回 `process_execute` + `unknown`。这个方向是**安全的**(不越权断言),但也意味着一次提权删除在 Scope Effects 面板上与一次普通命令执行长得一样。裁决 HR2 只处理了元字符闸门与 `NAME=value` 前缀,没有对"包装器"这一类给出规则。
- 方向:需要一次独立裁决,而不是顺手加白名单——`sudo`/`env`/`nice`/`timeout`/`xargs`/`command` 各自的参数文法不同(`sudo -u user rm`、`env -i FOO=1 rm`、`timeout 5s rm`),一个"跳过 flag 及其取值"的通用规则很容易把 flag 的**取值**误当成命令词(`sudo -u rm whoami` 里的 `rm` 是用户名,不是命令)。保守可行的中间态是:只解包**无 flag** 的形式(`sudo rm …`、`env rm …`),其余仍退回 `process_execute`。任何方案都要配"包装器带 flag 时不误判"的负向用例。
- **P11-C 的裁决(2026-08-23,裁决 RC14):明确不在本批建,理由入档。** P11-C 的四节(replay / retention / raw read 审计 / 关闭顺序)一次都没有触达 `tool_middleware.py::_effect_class`,而本条自己的归属写的就是「随下次触达该函数的改动一并裁决」。在一批不碰那个文件的工作里顺手加一条包装器白名单,等于把一次需要负向用例支撑的分类裁决塞进无关的评审面——本条要的是裁决,不是补丁。归属不变。
- 归属:未定,建议随下次触达 `_effect_class` 的改动一并裁决。

## F10-23. assessor 读证据时不 hydrate externalized payload

- 状态:✅ 已修复(2026-08-21,P11-B Task 4,`35aece8a`)。取的是方向 (a):`_assess_scope_safety_at` 的两处 `model_validate` 前先过新的 `SqlAnsichBackend._hydrated_observation_payload`,它按 `_claim_projection_job` 认领时那条 payload-store 读路径的同一形状把 `ansich_payloads` 读回来。三个细节值得记:
  - **hydrate 挪到了两个 kind 分支里面**,不是循环开头。`affected` 过滤仍然读裸 `row.payload_json`(`_scope_safety_evidence_subject` 的契约就是「便宜地读、读不到返回 None」),所以 externalized 行照旧不被跳过、照旧被完整判一遍——保守方向不变,只是这一遍现在读得到证据了。PB5 的 `effective_watermark` 算术一个字没动。
  - **payload 行真的不见了就抛**,不降级成空 dict:空 payload 会校验成**另一个结论**,静默会伪造一条判断,而不是报告证据读不出来。与认领路径的 `RuntimeError("Ansich payload disappeared")` 同一取舍。**M5(代价要写明白)**:这条 `RuntimeError` 是非依赖类异常,所以它把本条修掉的那个**全 Task 停摆**原样**重新装回来**——只是触发条件从「payload 被 externalize」换成了「payload 行没了」。这直接耦合到 **batch C 的 retention 删除**:删一条 `ansich_payloads` 行(或它的 observation)不只是让那条证据读不出来,而是让该 Task 的 scope-safety 评估从此每一轮都撞同一条毒行。C 批设计删除时必须一并裁定:要么 payload 与 observation 同生共死地删,要么给这条读一个「证据已按保留策略清除」的显式降级态——而不是让它继续走 raise。(同一条耦合在 F10-25 末尾已按回执语义记过一次,这里是它在 assessor 侧的第二个面。)
  - **红先证据**:`inline_payload_max_bytes=16` 逼出 externalize 后,一次 `assess_operations` 就在 `ansich_assessor_errors` 里留下一条 `ValidationError`(非依赖类异常,`durable_failure=True`,第一次尝试就写错误行),该 ToolCall 的 `scope_safety:*` 断言为 **0** 条。修复后错误行 0 条、job 全 `completed`、断言 4 条。
- 回归钉子(两条,`backend/tests/ansich/test_sql_safety.py`):`test_externalized_authorization_and_effect_evidence_does_not_fail_the_assessor_job`(先断言四条证据行确实是 `payload_json IS NULL AND payload_ref_id IS NOT NULL`,再断言零错误行、job 全 `completed`、结论非空)与 `test_externalized_evidence_reaches_the_same_scope_safety_conclusions_as_inline`(同一份 fixture 跑两遍、只换阈值,断言 `scope_safety:*` 断言值与 `ansich_scope_conclusions` 的 kind 集合逐字相同)。**第二条是必要的**:只断言「不产失败作业」的话,一个「读不到就跳过」的守卫也能绿,而它会拿被截断的证据去判同一个 ToolCall。
- 未一并处理(明确记下,不要读成已清零):
  - **全扫残留,以及它的行数增长那一半**:`_scope_safety_evidence_subject` 仍然对 externalized 行返回 `None`,于是 `_scope_safety_tool_calls_in_window` 仍然退回全扫。判断本身是**保守且正确**的(全扫只会多判,不会少判),但代价不止「窗口失效」这么轻:scope-safety 的结论以**评估时刻**做 `as_of`/`asserted_at`,所以重判永远不会被 `_persist_assessment` 的 dedupe 吸收——只要该 Task 里还有一条 externalized 证据,**每一次 trigger 都会给每一个 ToolCall 追加一条 assertion 加一条 `ansich_scope_conclusions` 行**。这正是 PB5 在别处专门去堵的那种无界增长(见 F10-10 假设 (c)),在这里由 externalized payload 从另一个入口重新打开。要收窄就得让那个「便宜地读」的契约本身能 hydrate,那是一次独立裁决。
  - **M6(残留未被测试覆盖)**:本条两个回归都走**首次评估**路径(`window_start_exclusive is None`,两侧都是全扫),所以「已推进的 mark + externalized 证据 → 增量窗口退回全扫 → 行数增长」这条**收窄后**的路径目前**没有任何用例执行过**。登记不修:补它需要先驱动一次评估把 mark 推上去,再投一条 externalized 证据并数两轮的 `ansich_scope_conclusions` 行数。
  - **同一危害类的两条开口兄弟(F10-29 收口)**:`contracts.py` 的 `environment.sampled` 分支写的是 `if self.payload is None: raise`(无条件),externalized 的环境采样连读回来都不行;`sql.py::get_environment_history` 则是 guard-and-skip,externalized 的采样点静默从趋势序列里掉出去(那里原本还有一句「环境 payload 从不 externalize」的注释,**该说法已撤回**——没有任何东西豁免这个 kind 的 `inline_payload_max_bytes`,只是它通常小到撞不上)。两条都是安全方向(要么响、要么留一个诚实的缺口),但都还开着,归 **F10-29**。
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

- 状态:✅ 已修复(两半)。**证据序**那一半由 P11-A 批 HOTFIX-0 `ae731b18` 收敛(共享纯函数 `ansich.budget.order_wall_time_evidence`,时钟无关性已用 2026/2099 双 fixture 证明);**结构形状**那一半由 P11-B 批 Task 10 `c7ce07a8` 收敛,取的是方向 (a):终端投影写者 `_assess_budget_rows` 补齐 `enforcement`/`shadow`(从 budget 行按评估器同样的方式派生),并保留只有它才写的 `as_of_known`(只有这个写者会把 `as_of` 回落到 `asserted_at`,读者在该键缺席时自行推断)。两个写者仍在不同的钟上断言、resolver 仍按 `as_of` 再 `asserted_at` 决胜——**变的是决胜不再改变形状**:此前一个字段的**存在与否**本身是一场竞态。回归钉子:`backend/tests/ansich/test_database_health.py::test_both_budget_health_writers_store_the_same_value_shape`(两个写者交错落地后逐字段比对形状)。**跨钟决胜本身没有被消除**(那是方向 (b),范围更大,未做);本条关的是它的可观测后果。来源(留档):P11-A 批 HOTFIX-0 的根因分析(`.superpowers/sdd/2026-08-19-ansich-p11a-write-resilience/hotfix-0-report.md`)。
- 位置:`backend/packages/harness/deerflow/ansich/persistence/sql.py::_assess_absolute_limits_at`(评估器写者,`asserted_at`=模拟事件时间)与 `::_assess_budget_rows`(终端投影写者,`asserted_at`=真实 ingest 墙钟);`resolve_current_belief` 对两条同 `as_of`、同 `configured_rule` 权威的断言按 `asserted_at` 决胜。
- 现状:证据**顺序**已通过共享纯函数 `ansich.budget.order_wall_time_evidence` + `SqlAnsichBackend._budget_usage_evidence` 在两个写者间收敛(时钟无关性已用 2026/2099 双 fixture 证明)。但两个写者的 `value_json` **结构形状不同**:终端投影写者带 `as_of_known`,评估器写者带 `enforcement`/`shadow`——读者拿到哪个形状取决于同一次跨钟决胜。`get_task_budget_health` 今天用 `.get()` 容忍两种形状,但任何依赖 `enforcement`/`shadow` 字段存在性的消费者会踩中。
- 教训(测试作者规则,已在本条挂账):fixture 时间戳写「当天」会造出定时炸弹——真实时钟越过 fixture 时刻的一瞬,决胜翻转、断言由绿转红且永久。2026-08-20 的全量绿(所有 8/18-19 时间戳已成过去)证明当前无其他潜伏实例;新测试不得让 resolver 决胜落在模拟钟与真实钟之间。
- 方向:二选一——(a) 收敛两个写者的 `value_json` 形状(终端写者补齐 `enforcement`/`shadow` 或评估器改为最小共同形状);(b) 给终端写者的断言一个 resolver 可确定性排序的权威/`config_hash` 维度,使决胜不再依赖钟。任选其一都要配「两个写者交错时读者拿到的形状稳定」的回归。
- 归属:P11-B(与评估器债 F10-6/假说 (c) 同批同轨)。

## F10-25. `record_evaluation` 的重放查询无守卫

- 状态:✅ 已修复(2026-08-21,P11-B Task 4,`35aece8a`;PB6 的抓取集与路由具名子句随修复轮 `0d9aa3cb`)。照复审建议原样落地,三处:
  - **类型**:新文件 `backend/packages/ansich/ansich/errors.py::StorageUnavailableError`。零依赖(不进 pydantic、不进 SQLAlchemy)——这正是它存在的理由:适配器可以 import 驱动的异常树,但**放出包边界的**必须是每个调用方都能指名的东西。
  - **转译(裁决 PB6)**:`sql.py::find_evaluation_observation` 把 `_STORAGE_CANNOT_ANSWER` 里的四类转成它——`OperationalError`、`InterfaceError`、`sqlalchemy.exc.TimeoutError`、`DisconnectionError`。**选的是含义,不是某个顺手的基类**:前两个确实是 `DBAPIError` 子类,但连接池耗尽(`TimeoutError`——所有连接都占着、checkout 等穿 `pool_timeout`,这恰恰是生产上最可能的「答不上来」)和检测到的断连(`DisconnectionError`)是直接从 `SQLAlchemyError` 继承的,中间**没有** `DBAPIError`。本条第一版按 `DBAPIError` 抓,于是这两类原样跑出了包边界——正是本条要修的那个泄漏。反向同样是含义的一部分并且已写成断言:`ProgrammingError`/`IntegrityError`/`DataError` 也是 `DBAPIError` 子类,但它们都是**缺陷**——语句写错、约束被违反、值超出列范围;存储答了,答的是「不行」。把它们说成「不可用」等于劝调用方去重试一条永远不会成功的查询,所以**明确排除**,继续落到路由既有的兜底。**只包这一条读**:其余读路径已由路由的 `_ensure_queryable` 答 503,不在本条范围内。
  - **映射**:`app/gateway/routers/ansich.py::record_evaluation` 在既有的 `except Exception → 503` **之前**加一条显式 `except StorageUnavailableError → 503`(带 `projection_status`)。状态码没变,变的是这条 503 现在是**具名条件**而不是与任何意外故障共用一个兜底。注意 `_ensure_queryable` 抓不到它:那次健康读是进程本地的、此刻仍报 `storage_available=True`,故障只有那次读自己才发现得了。
  - **回执语义一字未改**:不答 `failed`(那是「知道它丢了」,这里是「不知道是不是重放」),不吞异常照常记录(去重被跳过会铸出幻影回执 id),也没有新增第四个 `EvaluationProjectionStatus` 取值。代价是调用方要重试一次,换掉的是一个错误答案。
- 回归钉子(三条):
  - `backend/tests/ansich/test_evaluation_service.py::test_a_storage_outage_on_the_replay_lookup_raises_a_typed_error`——新的 `_ReadOutage` 只让**下一次**开 session 失败一次(P11-A 的 `_StorageFault` 是写侧的,故意不碰读),因为 arm 是同步的、重放查询在第一个挂起点之前就抛,所以落点是确定的;它同时断言故障期间**零 Observation 落库**、痊愈后同一 intake 身份是 `idempotent_replay=False` 的首次入库(证明失败的那次查询没有铸出任何可被重放的东西)。RED 证据:修复前 `record_evaluation` 抛的是 `sqlalchemy.exc.OperationalError`,栈顶正是诊断记录的 `sql.py` 的 `async with self._session_factory() as session:` 那一行。
  - `::test_the_replay_lookup_types_the_cannot_answer_family_but_not_a_bug`——四类「答不上来」逐个转译(并断言 `__cause__` 保留原始驱动异常),三类「缺陷」逐个**原样抛出**。双向变异都验过:抓回 `DBAPIError` → 池 `TimeoutError` 逃逸,红;把三类缺陷加进抓取集 → `ProgrammingError` 被转成 `StorageUnavailableError`,红。
  - `backend/tests/ansich/test_ansich_evaluations_router.py::test_post_evaluation_answers_503_when_the_replay_lookup_hits_a_storage_outage`——HTTP 侧钉 503 + `detail["message"] == "Ansich storage is unavailable"` + `projection_status`(且 `storage_available` 仍为 `true`,把「健康读看不见这次故障」也钉住)。**那条 message 断言是这条用例的全部分量**:路由的 `except Exception → 503` 早于本次修复就存在,所以状态码、detail 形状、落库条数三项在**完全未修复**的路由上也全绿(复审实测两次)。唯一能区分具名子句与兜底的可观测量就是 `detail["message"]`(`"Ansich storage is unavailable"` vs 兜底的 `"Ansich evaluation write failed"`)。变异验证:摘掉具名子句 → 红。**本条初版只断言了前三项,因此当时是一条描述而非回归**,已更正。
- 来源:P11-A 批 Task 8(写侧故障注入验收)的**实测**,修法建议由该 task 的复审给出。经核实是**既存缺陷**——自 `c1349843` 起就是这个形状,非该批引入,该批按指令只登记不修。
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

- 状态:✅ 已修复(2026-08-21,P11-B 批 Task 3,`d2cd58d2`;PB5 与配套回归随 `7ad37ce7`,docstring 更正随 `563aeb6e`)。取的是方向里的**显式报告**那一支(裁决 RB9⑦ 选 (b)):`rebuild_projections()` 现在返回 `RebuildOutcome(replayed, unsettled)` 而不是一个裸计数。`unsettled` 数的是这一趟返回时仍处于 `pending`/`retry`/`processing` 的投影**与** assessor 作业(`failed` 行算「已结算,只是结算得很糟」,并且早已由 failed-job 计数暴露)。为什么不等:这个调用同时持着维护锁**和**调用方的 `_projection_lock`,等一个依赖最长要等 `projector_dependency_timeout_seconds`,那会把一个操作者和一条 projector loop 一起停在一个它管不着的时长上;而把一个 250ms 内就会结算的作业直接判成 durable failed 是在毁掉工作。rebuild 幂等,想要完整性的调用方再调一次即可;`AnsichService.rebuild_projections` 把仍返回裸 int 的 backend 规范化为 `unsettled=0`。
- **三条留观的收尾裁决(2026-08-23,P11-C 批终,T15)。三条**全部**结清,本条的 ✅ 因此站得住,而且现在有了它一直缺的那一半——调用方侧的完整性循环。** 三条留观(见下)记的是同一件事在三个楼层的复发:测试与调用方把**单轮**读成完整性。修法始终是本条自己在 §5 改写处开出的那一行——对 `unsettled == 0` 做**有界循环**,而不是信任单轮——而 P11-C 把它落到了每一层:
  - **留观一** → `AnsichService.rebuild_until_settled(max_rounds=5)`(Task 1,`113f244b`;文档下界告诫随 `d293b9ee`),`tests/ansich/` 里全部**八处**「单轮 `rebuild_projections()` 之后断言 `unsettled == 0`」的调用点(含具名实例与 opt-in PG tier 的一处)改成调用它。
  - **留观二** → 那次目击暴露的是 T1 的清扫**没有覆盖到的另一种形状**:「裸 `rebuild_projections()` 之后断言读模型相等」。由专门的一次机械清扫(Task 3b,`d610792d`)处理:31 处可调用的裸站点里 **23 处**转换、**8 处**因机械原因留下(全部逐条分类入档,其中五处是**结构性**不可转换的——循环只存在于 `AnsichService` 上,那几处是 backend 级)。留下的站点没有内联标记,分类表是那份记录。
  - **留观三** → 本条第一次不在 `rebuild_projections()` 上而在 `execute_replay()` 上,由 Task 11 第二轮转换(`1f5d805a`):测试侧 `_replay_until_settled` 与 `rebuild_until_settled` 逐字同型(每一趟是**独立的一次** `execute_replay`,退出条件是 `unsettled == 0` 而不是「某一轮没重放东西」,耗尽上界只报告不抛),两处调用点都改成它。
  - **仍然开着、且属于本条的一句诚实话**:没有任何结构性装置阻止有人**再写**一处裸 `rebuild_projections()` + `unsettled == 0`(Task 3b 的实施者与复审都点了这一条,建议过一条约 40 行、以 AST 钉住那 8 处机械站点的守卫测试,先例在 `test_ansich_config.py`)。在那之前本条的修法靠的是清扫加评审,不是靠机器。这条守卫属于下一次测试卫生波(与 F10-30 同批)。
- 「这一轮没认领到」与「重建完成了」自此是两句话,而且第二个理由是本批新加的:自 lease CAS 之后,一轮也可能因为**认领被别人接管**而返回零。
- 附带闭合的一条 §5 前置:PB5(见 F10-10 假说 (c) 一节)修掉的是一次**实测到的** live-vs-replay Belief 分歧——没有 PB5 时同一份流「实时读到 present、重放读到 cleared」,而本条方向里写的「两次重放 digest 相同」正以此为前提。
- 来源(留档):P11-A 批 Task 2 复审提出的机制假说(裁决 PA10 已入账),该批共四次目击。
- 位置:`backend/packages/harness/deerflow/ansich/persistence/sql.py::rebuild_projections` 的完成条件,与 `_ProjectionDependencyPending` 的延迟重排路径(带 250ms 退避的依赖等待)。
- 机制假说(复审给出,尚未用插桩证实):`rebuild_projections()` 以「这一轮没有可投影的 job」作为完成条件退出,而一个 dependency-pending 的 job 此刻**不在**可投影集合里——它在等自己的依赖。于是重建可以在仍有 job 未结算时就返回,调用方紧接着读到的是一份**不完整**的投影。这解释了为什么这一族的失败形状永远是「实时值 ≠ 重建值」或「重建结果为空」,而不是数值算错。
- 本批四次目击(单跑必过,全部在套件负载下):
  1. **Task 2(在 BASE 上)**:`test_sql_task_lifecycle.py::test_tool_call_projection_survives_restart_and_rebuild_without_usage_duplication` —— `assert rebuilt_tool_call == before_tool_call`,重建侧 `derivations=()`。
  2. **复审的机制假说**(不是一次红,是这一族第一次有了具体机制):即上面那条,由 Task 2 的复审在同一条 flake 上给出,并由裁决 PA10 归口 P11-B。
  3. **Task 4**:`test_sql_task_tree.py::test_usage_rolls_up_two_levels_and_backfills_a_late_spawn_without_double_counting` —— `assert root_usage == rebuilt`(两侧都是 `TaskUsageView`,`-q` 没给出字段级差异);单跑绿 ×4,整文件 8 passed,同一测试在该轮的另两次全量跑里也是绿的。
  4. **Task 6(文本完整)**:`test_sql_evaluations.py::test_rebuild_reproduces_index_rows_stats_and_current_beliefs` —— `assert before == after`,而 `after` 是**空的**(`'stats': ()`、`'index': ()`):**重建什么都没产出**。这一条最贴合机制假说,也是本条最强的一次证据。
- 为什么它不是 F10-10 的同一件事:F10-10 是「后台评估写者与测试自己驱动的评估赛跑」,门禁 `only_test_driven_assessments` 已经把那个写者按住;这一族的失败与评估无关,失败的是**重建自身的完整性**,而 barrier / 写侧改动只能让写入更宽、不可能更窄(`rebuild_projections()` 读的是持久流)。两族必须分开记,否则会把「等更久就好了」的错误结论套到这一族上。
- 方向:让 `rebuild_projections()` 的完成条件把 dependency-pending 的 job 算进去——要么等它们结算或越过 `projector_dependency_timeout_seconds` 转 durable failed,要么在返回值里**显式报告**「仍有 N 个未结算」,由调用方决定。任何修法都要配一条「依赖延迟 job 未结算时重建不报完成」的回归;这同时是 §5 versioned replay「两次重放 digest 相同」得以成立的前提。
- 留观(2026-08-22,批终审后的修复波目击,终审复审裁定归口本条而非 F10-30):`tests/ansich/test_spawn_usage_reconciliation.py::test_rebuild_mints_a_reconciliation_for_an_edge_that_has_none`(**2026-08-22 更正文件名**:此前这里写的是 `tests/ansich/test_sql_projection_jobs.py`,仓库里**没有**这个文件——同 RC15 那一类的悬空指针,由 P11-C Task 1 在落地本条修法时一并改掉)在「两文件并跑 + 外部负载」下红过一次——断言 `unsettled == 0`,实得 10。这不是 settle 预算输给负载(不是 F10-30 的家族形状),而正是本条修复后的**约定语义在测试侧未被消化**:`rebuild_projections()` 按本条的 (b) 支**报告而不等待**,负载下一轮返回时依赖延迟的作业就是可以有 10 条未结算,`unsettled==0` 只能靠调用方自己再驱一轮拿到。讨伐:单独 3/3 绿、同组合复跑 2/2 绿、两次全量绿。修法即 §5 改写处已开出的那一行:测试(以及任何要完整性的调用方)对 `unsettled==0` 做有界循环,而不是信任单轮。**该修法已由 P11-C Task 1 落地**(commit 见该批 task-1-report):`AnsichService.rebuild_until_settled(max_rounds=5)` 是那个有界循环,`tests/ansich/` 里全部八处「单轮 `rebuild_projections()` 之后断言 `unsettled == 0`」的调用点(含上面这条具名实例,以及 opt-in PG tier 的一处)都改成了调用它。**本条的状态翻转不在此处做**,留给控制者/T15 统一裁决。**已裁决(2026-08-23,T15):本留观结清**,见本条开头的「三条留观的收尾裁决」。
- **留观二(2026-08-22,P11-C 批 Task 3 的第三轮全量目击):T1 的转换覆盖的是 `unsettled == 0` 那一类调用点,而本条最初四次目击的形状——「单轮重建之后拿读模型对等」——一处都没被覆盖,现在又红了一次。** 目击:`tests/ansich/test_sql_heartbeat.py::test_late_spawn_backfill_carries_the_wall_time_high_water_mark`(断言在 :1227),失败全文:

  ```
  >       assert rebuilt_usage == usage
  E       AssertionError: assert TaskUsageView...s='available') == TaskUsageView...s='available')

  tests/ansich/test_sql_heartbeat.py:1227: AssertionError
  FAILED tests/ansich/test_sql_heartbeat.py::test_late_spawn_backfill_carries_the_wall_time_high_water_mark[asyncio]
  ```

  调用点是 `usage = await get_task_usage(root)` → `await service.rebuild_projections()`(**单轮**)→ `rebuilt_usage = await get_task_usage(root)` → `assert rebuilt_usage == usage`。这与本条目击 1/3/4 逐字同型(目击 3 `test_sql_task_tree.py::…_backfills_a_late_spawn_without_double_counting` 的 `assert root_usage == rebuilt` 几乎是同一个用例的另一个写法),**不是** F10-30 的家族形状(不是 settle 预算输给负载,是重建单轮被当成完成)。**这是一次分诊,不是一个新成员**:按窄口 (1) 的分诊规则,失败形状属「重建单轮后断言完整性」⇒ 归 F10-26,不进 F10-30 的成员表。讨伐:该用例单独重跑 3 次 **3/3 `1 passed`**(2.77s / 2.85s / 2.86s);同一生产树的上一轮全量(只差一条新增的纯函数用例)是 **843 passed 全绿**;Task 3 的生产改动不碰任何既存代码路径(见 F10-30 那条的 Task 3 记账)。
  **结构性缺口,值得单独看一眼再决定要不要动**:`tests/ansich/` + `tests/integration/` 里今天还有 43 处 `rebuild_projections()` 调用、只有 13 处 `rebuild_until_settled`,其中「重建后拿读模型对等」的写法在 `test_sql_heartbeat.py`(:182/:794/:1210)、`test_sql_task_tree.py`(:446)等处成片存在,全部仍是单轮。修法与留观一完全相同、也是一行:把这些调用点换成 `rebuild_until_settled()`。P11-C Task 3 **没有动它们**(超出该任务范围,且一次 flake 拿不到确定性红先),把它作为一条带证据的欠账交给控制者/T15 裁决:要么作为一次独立的测试侧扫尾,要么继续按 flake 记账。**控制者裁决取了「独立扫尾」那一支,已由 P11-C Task 3b 落地**:`backend/tests/` 里 31 处裸 `rebuild_projections()` 调用点全部分诊过——23 处「单轮之后断言读模型/投影完整性」(含本留观具名的 `test_sql_heartbeat.py:1210`,以及目击 1 的 `test_sql_task_lifecycle.py:209`、目击 3 的 `test_sql_task_tree.py:446`)改为 `rebuild_until_settled()`,8 处考的是重建自身的单轮机制(`test_lease_cas.py` 四处的 `replayed`/`unsettled`/`lease_generation` 计数、`test_task_lifecycle.py` 三处的 outcome 归一化与互斥探针、`tests/integration/test_postgres_multiworker.py:823` 的两个并发单轮重建)按其语义留原样,没有一处属于「断言与结算无关」;本条的状态翻转仍不在此处做。**已裁决(2026-08-23,T15):本留观结清**,见本条开头的「三条留观的收尾裁决」;那里同时记下了它留下的唯一残留——没有任何结构性装置阻止再写一处裸调用。
- **留观三(2026-08-22,P11-C 批 Task 11 修复轮的全量目击;本条第一次不在 `rebuild_projections()` 上、而在 `execute_replay()` 上):** 目击:`tests/ansich/test_replay.py::TestExecuteReplay::test_two_replays_of_one_observation_set_agree` 的 `assert second.unsettled == 0`,实得 **1**。这正是本条的签名,只是换了一层楼:`execute_replay` **自己**就是那个有界循环(默认 `max_rounds=5`),但它的五轮跑在**同一次调用之内、彼此紧挨**,而依赖延迟的作业被 `available_at = now + 250ms` 挡在 claim 的 `available_at <= now` 谓词之外。于是一次 pass 完全可以耗尽自己的轮次仍带着 `unsettled == 1` 返回,而调用点把这**单次 pass** 读成完整性,就是本条的错误升了一级(`RebuildOutcome` 与 `execute_replay` 的 docstring 各自的下界告诫,说的都是这件事)。**措辞更正(2026-08-23,T15)**:此前这里写的是「再紧的空转也够不着它」,那说得太绝对。准确的说法是——那五轮之间**没有任何时间感知或可用性感知的退出条件**,而每一轮都要跑一次完整的 `assess_operations`,那是要花墙钟的;所以 250ms 的退避会不会在某一轮里自己走完纯属偶然,取决于那一轮的工作恰好花了多久。这也正是该断言**通常绿、只在负载下才红**而不是恒红的原因。讨伐:该用例**单独重跑 3 次,3/3 `1 passed`**;同一门禁在批 BASE `f1d52a79` 上**全绿(1065 passed)**,故「BASE 上同样红」不成立——**减项与 F10-30 成员 12 那条相同,必须并读**:BASE 那棵树没有本修复轮新增的五条起服务用例(1065 对 1068),而本条与 F10-30 一样是负载敏感的,所以 BASE 全绿只能读作「那个负载下没红」。**该站点已由 Task 11 第二轮转换**:测试侧新增 `_replay_until_settled`(与 `rebuild_until_settled` 逐字同型——每一趟是**独立的一次** `execute_replay`,退出条件是 `unsettled == 0` 而不是「某一轮没重放东西」,耗尽上界只报告不抛),两处调用点都改成它,周围断言逐字未动;修完该用例单独 3/3 绿、整文件 133 passed 全绿。**本条的状态翻转仍不在此处做。****已裁决(2026-08-23,T15):本留观结清**,见本条开头的「三条留观的收尾裁决」。**另记一条比该转换的 docstring 自称的更强的保证**:`_replay_until_settled` 的 docstring 只举了「两趟之间释放并重取维护锁、其间做了真活」这个**基于时间**的弱理由;强的那一半是**结构性**的——新的一趟 `execute_replay` 会调 `mint_replay_jobs`,它的 re-pend 对每一条命中选择器的目标作业写 `available_at = now` **并且** `dependency_pending_since = None`,所以对**目标** `(projector, version)` 的作业,第二趟是结构上清掉退避,不是靠运气。残留也要一起读:`unsettled` 取自 `unsettled_job_count()`,那是**全库**的,所以属于**别的** projector 的未结算作业不会被下一趟 re-pend,对它们额外的趟数仍然只是在耗时间。
- 归属:P11-B(重放诚实性)。

## F10-27. 装配不对称:无存储分支漏传三个 knob

- 状态:✅ 已修复(两半,2026-08-21,P11-B 批 Task 10,`c7ce07a8`;配套修复轮 `625a056c`)。(a) 两个装配分支现在都 splat 同一份映射 `deerflow.ansich.service_knobs_from_config(config)`,不再各自拼参数表——无存储分支此前漏的正是 `terminal_flush_timeout_ms`/`projector_poll_interval_ms`/`operations_assessment_interval_ms` 三个;三条测试把它钉住(`tests/ansich/test_ansich_config.py::test_every_service_knob_is_covered_by_the_shared_assembly_mapping` 把映射钉在 `AnsichService.__init__` **自己的关键字参数**上、`::test_both_assembly_branches_receive_the_identical_service_knob_mapping` 钉两个分支收到同一份、`::test_operations_and_health_knobs_are_bounded_startup_only_fields` 钉新字段的边界与 startup-only 性),所以下一个 knob 在结构上无法只穿一个分支。(b) `operations_assessment_interval_ms` 补上了它一直没有的 `AnsichConfig` 字段(startup-only,默认 1000,与本节其余字段同姿势并同步 `config.example.yaml`),与本批新增的 `health_database_timeout_ms` 并排。因此 F10-10 里「默认档 1 Hz 不可配」那半句**已经过期**:它现在可配,默认值不变。来源(留档):P11-A 批 Task 8 复审的**具名 non-fix**(测试 task 不动生产装配)。
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

## F10-29. 环境外部化载荷类(F10-8/F10-23 的第三面)

- 状态:✅ 已修复(2026-08-22,P11-C 批 Task 2,`393a01e2`;同类的第四、五个分支由同任务修复轮 `abefcb01` 收口)。三个实例一次收口,每个配一条红先回归。
- **三个实例的落法:**
  1. `contracts.py` 的 `environment.sampled` 改成 F10-8 同款 `if self.payload is not None:` 守卫。被替掉的那句无条件 `raise` **没有丢**:envelope 末尾那条「`payload` 与 `payload_ref_id` 恰有其一」的通则对每个 kind 都成立,所以在一条已存储的行上 `payload is None` **就等于**「已外部化」——守卫因此不放过任何东西。回归:`test_contracts_environment.py::test_externalized_environment_sample_validates_on_read_back`,以及 `::test_a_sample_with_neither_a_payload_nor_a_ref_is_still_rejected`(通则仍然拦得住,守卫没有削弱契约)。
  2. `_claim_projection_job` 改成**先 hydrate 再建 envelope**:`_observation_from_row` 拆出 `_observation_envelope(row, *, payload, payload_ref_id)`,认领方把 hydrate 过的 payload 交进去、只校验一次。原来的顺序是「先按裸行建 envelope、再 `model_copy` 补 payload」,而 `model_copy` 不跑任何校验器——所以既让「校验器要求 payload 的 kind」在认领事务里就抛,也让**其它每一个 kind** 的、投影真正会读的那份 payload 从来没被校验过。`payload` 行真的不见了仍然抛(原样保留;tombstone 那一态归 T9)。回归两条(`test_lease_cas.py`):`::test_an_externalized_environment_sample_is_hydrated_before_its_envelope_is_built` 与 `::test_the_claim_validates_the_hydrated_payload_instead_of_patching_it_in`。
  3. `get_environment_history` 改成在自己的 session 里走 `_hydrated_observation_payload`(且过滤在循环**内**,不先 hydrate 整个窗口再筛),那段 RETRACTION 注释改写为描述 hydrate 与「跳过」的真实代价(大样本静默掉出趋势序列)。回归:`test_environment_projector.py::test_an_externalized_environment_sample_projects_reads_back_and_keeps_its_history` 的第 (c) 条。缺 payload 行时它现在**会抛**,但那是路由已有的 `except Exception` 包出来的结构化 **503**(不是 500),且是本类自己的规矩:读不出的证据要报告,不许伪造。
- **红先证据用的是生产默认阈值**:回归里没有任何地方调低 `inline_payload_max_bytes`,而是造一条 800 个指标、约 71 KB 的 `environment.sampled`,先断言该行确实是 `payload_json IS NULL AND payload_ref_id IS NOT NULL`,再断言三条腿:公共读回校验通过、认领+投影落地(800 条 state 行、零投影错误行)、history 带完整 `(value, limit)` 出现。
- **同一危害类在本条登记时漏掉的另外两个实例,一并收口(`abefcb01`)**:`contracts.py` 的 `task.heartbeat` 与 `budget.configured` 走的是 `payload = self.payload or {}` 再校验——同一危害类的另一种写法(伪造一个 `{}` 而不是直接抛),后果一样:externalized 的这两类 Observation 一条都读不回来。两处都改成 `and self.payload is not None:` 守卫。它们此前不可达**只是因为 payload 小**,而这正是 `environment.sampled` 在 800 指标样本出现之前一直成立的那个论证。回归三条(`tests/ansich/test_contracts.py`):两条 externalized 读回(各自红先),外加一条内联负向用例钉住「守卫没有放松存在 payload 时的校验」。收口之后,`contracts.py` 里**全部九个按 kind 校验 payload 的分支**(`observability.lost`、`operator.action_*`、`scope.snapshotted`、`environment.sampled`、`authorization.*`、`effect.*`、`evaluation.recorded`、`task.heartbeat`、`budget.configured`)都守卫在 `payload is not None` 上,`backend/AGENTS.md` 的那句断言因此是逐字为真的。(**计数更正**:本条的草稿一度写「全部十个分支」,复审复算是 8–9;逐分支点名后的准确数是**九**。)
- **登记时的措辞按实测机理更正了一句**:本条原写「认领即失败 ⇒ 作业 durable failed」。实测不是。抛发生在认领事务**内部**,`attempts` 的自增随事务一起回滚,所以那条作业**永远到不了 `failed`**,一直停在 `pending/attempts=0`;投影循环也**没有**死(复审实测:循环存活,约 1090 次空转认领)。这条通用形状本身与本条的三个实例无关,但它的暴露面被本条的修法扩大了——单列为 **F10-36**,按那条读,不要按「作业 durable failed」读本条。
- 原始诊断(留档)——三个实例,同一危害类(externalized payload 的读者不 hydrate):
  1. `packages/ansich/ansich/contracts.py` 的 `environment.sampled` 校验分支对 `payload is None` **无守卫直接抛**(F10-8 修的三个分支有守卫,这个没有)——externalized 环境样本经任何公共读(`list_timeline`/`list_observations`/告警证据)都读不回;
  2. `_claim_projection_job` 先 `_observation_from_row` 后 hydrate 的顺序使这类行**认领即失败**——`environment-projector@1` 的作业 durable failed("写得进、读不出、作业永不落地",F10-8 当年"比诊断记录的还要广一层"的同款形状);
  3. `sql.py` 环境 history 读者对 payload-ref 行守卫跳过——其"环境载荷从不外部化"的注释已在 `0d9aa3cb` 撤回(它们**可以**外部化,默认 65536 字节阈值下概率低)。
- 概率(原始记载):低(环境样本 payload 小);方向:契约分支补 F10-8 同款守卫 + history 读者走 hydrate;每实例配回归。**「概率低」这条判断本身被 800 指标样本证伪**,这也是把同类第四、五个分支一并扫掉的理由。
- 归属:已完成(P11-C 批 Task 2)。

## F10-30. settle-budget flake 家族(与 F10-10 明确分开)

- 状态:⬜ 未修复(测试侧;生产行为是 fail-open 预算语义,非 bug)。**成员 5 已由 T8 结案(上界写错,非本机理),成员 1 由 T8 部分处理(:1196 半边有条件了,:1195 半边没有)**;成员 2/3/4 未动;成员 6/7/8/9 于 P11-B 收尾与终审时补登(见下),**这四条都在 `test_sql_safety.py` 之外**;成员 10 由 P11-C Task 1 的全量目击补登,它**回到了 `test_sql_safety.py` 里**(见该成员条目);成员 11 由 P11-C Task 2 的全量目击补登,与成员 10 同文件、同构造(自造 sleep 当 settle 预算);成员 12 由 P11-C Task 11 修复轮的全量目击补登,同样回到 `test_sql_safety.py`,但构造是本族的**第三种**——它既不压预算、也不自造 sleep,而是**只驱动一轮 `assess_operations`**,预算是那一轮本身。来源:P11-B 批 T2-T4 的争用复测逐步识别,T4 修复轮定名;成员 4 由 T5 复审补登;成员 6/7 由 T10 复审目击、T12 登记,成员 8 由 T12 自己的全量目击,成员 9 由批终审全量目击、终审后的修复波登记;成员 10 由 P11-C 批 Task 1 的全量目击与同批登记;成员 11 由 P11-C 批 Task 2 的全量目击与同批登记;成员 12 由 P11-C 批 Task 11 修复轮的全量目击、Task 11 第二轮**在目击当批**登记(F10-30 收尾的窄口 (1) 要求登记在目击时发生,不是推给 T15)。
- 成员 1-3(全部 `terminal_flush_timeout_ms=100` 构造、24-hog 争用下全红——成员 1/2 两侧各 3/3 且文本一致,成员 3 一侧 3/3、另一侧存档 2 轮):
  1. `test_externalized_scope_authorization_and_effect_payloads_read_back`(:1195,`stored_payload_state == {}`——flush 预算内没写完)。**T6 修复轮把这条成员的两处描述都改宽了,两处都重要**:(a) 症状不止 :1195 那一条断言——T6 的验收里红在**下一行** :1196(`projected_scope_state is None`,scope 投影根本没落地),同一构造、同一机理,断言位置不同而已,所以不要按行号认这条成员;(b) **它在安静机、单独跑、无并发负载下也会红**——T6 单独重跑该用例 3 次即红 1 次(`task-6-evidence/f10-30-member-1-rerun-alone.txt`)。「24-hog 争用下才红」这个前提对成员 1 **不成立**,合并门禁不能靠「单独跑绿」来判定它。**并且它与本批任何改动无关**:同一用例在**批 BASE `ade44649`**(把 `sql.py` 单独 checkout 回去、其余不动)跑 6 次仍红 1 次,证据同文件。**T8 修复轮:部分处理(⚠️ 未结)。** T8 全量在该用例上翻红一次(症状是 :1196 那半边),分诊后在**同机、单独跑 24 次**量了三个状态:批 BASE `d4b43652` 的 `sql.py`/`__init__.py` **7/24 红**、T8 round-0 commit `42718363` **2/24 红**、T8 round-1 现状 **2/24 红**——BASE 更糟,故与 T8 无关,走窄口 (2)(b)。先试了本条自己排除过的手段确认它不是 F10-10:给该用例补 `only_test_driven_assessments` 后 24 次仍红 1 次,所以赛的**不是评估节奏**,是投影本身。根因随后定位:用例在 `flush_task()` 的**下一行**就读投影行,而 `flush_task` 约束的是**写**、不是投影。已改成对 `AnsichScopeRow` 的有界轮询(15s / 10ms),之后 24/24 绿。**为什么只算部分处理**:这条改动只给 :1196 那半边(scope 投影未落地)配了条件——它现在等的是一个确定性谓词(行在或不在),claim 真丢了投影仍会红。:1195 那半边(`stored_payload_state == {}`,flush 预算内没写完)**没有自己的条件**,它的 24/24 是等待窗口被拉宽后的**副作用**,不是钉子;该半边仍属本条家族,等共享 settle helper。本条「BASE 上同样红」的记录**不撤回**。
  2. `test_scope_safety_dependency_wait_crosses_deadline_into_failed_job_and_retry`(:514,`NoneType.job_id`——作业未建);
  3. `test_scope_safety_waits_for_subject_entity_then_self_heals`(同型)。成员 3 在 T5 的第一轮验收里(`tests/ansich` 与 bootstrap 组**并行**跑)再次翻红一次,单独重跑立即绿,安静机全量两轮全绿——按本条记账,未改判。
  4. `test_late_scope_evidence_reassesses_only_its_own_tool_call`(`test_sql_safety.py:1535`,T5 复审者的一次运行:`converged_after` 读到 `(8, 8, …)` 而非期望的 `(4, 4, …)`(`converged_before` 正常),即已收敛的 tool_call 被重估了一遍——正是 phase-9-review-followups.md:72 记录的**修复前**形状「从 4 涨到 8」;单独跑 3/3 绿)。**构造与前三条不同,必须一并记**:它不设 `terminal_flush_timeout_ms=100`(用默认终端预算),而是把 `flush_interval_ms`/`projector_poll_interval_ms` 都压到 60s,于是整个 settle 完全由 `flush_task()` 那一次预算承担、投影没有第二次轮询兜底——预算输给负载时两条证据落在**不同的 watermark 区间**,第二次触发就会连带重估已收敛的 subject。所以症状不是「读到空态」而是「读到多判了一轮」,机理仍是同一条:settle 预算输给负载。
- 为什么不是 F10-10:成员 2/3/4 **已上** `only_test_driven_assessments` 门禁(四条里只有成员 1 没有)、成员 4 还已把周期压到 60s——该门禁管评估**节奏**,管不了 **flush 预算**输给负载;P11-A 的屏障语义(超时退回队首)使测试在重排队中读到空态或半态。两族必须分开记,否则会把「加大门禁」的错误结论套到这一族上——成员 4 尤其是反例:F10-10 的两种手段它都已经用尽。
  5. `test_a_truncated_late_evaluation_cannot_leave_a_belief_regressed`(T5 复审者的另一次运行:`no scope-safety job at watermark 6 after 10.0s`——**第三种构造**:`terminal_flush_timeout_ms=2000` + 门禁 + 5ms 轮询 + 自带 10s 显式 settle 等待,仍超时;单独跑 3/3 绿)。T6 修复轮在安静机上**单独跑 `test_sql_safety.py` 整个文件**时它又红了一次(1 failed, 18 passed),同样无并发负载——与成员 1 一起把这条家族的「只在重负载下出现」前提证伪。**T8 修复轮:已解决(✅ 本成员结案),且原因不是「预算输给负载」。** T8 全量在该用例上翻红一次,分诊后同机单独跑 12 次量了两个状态:批 BASE `d4b43652` **5/12 红**、T8 现状 **2/12 红**——BASE 更糟,与 T8 无关,走窄口 (2)(b)。关键是**登记时记下的症状本身就是答案**:本条记的红是 `no scope-safety job at watermark N after 10.0s`,即那个「自带 10s 显式 settle 等待」**超时**。那个 10s 是错的:`tests/ansich/conftest.py` 给本套件每个 SQLite 引擎设的 `busy_timeout` 就是 **30s**,所以**一次合法等待中的 claim 就可能阻塞 30s**——10s 的上界比**单次被允许的等待**还短,于是把争用变成了红而不是慢。把 `_await_scope_safety_job` 的默认上界提到 30s(与该套件自己的 `busy_timeout` 对齐,理由写进 helper docstring)后:该用例单独 12/12 绿,`test_sql_safety.py` 整文件连跑 5 次 **19/19 全绿**。真被丢掉的作业仍会在这里红,只是多花墙钟时间才说出来——对一个「除到达时间外都确定」的条件这是正确取舍。**这条不改变本条家族的整体结论**:它是一个上界写错的实例,不是「预算输给负载」的实例,成员 1-4 仍待共享 settle helper。
  6. `test_case_e_child_success_and_parent_tool_failure_both_survive`(`tests/ansich/test_retro_terminal_judgment.py:52`)与
  7. `test_conflicting_tool_terminal_evidence_is_preserved_and_degrades_task_health`(`tests/ansich/test_sql_task_lifecycle.py:447`)——**两条在 T10 复审的一次并发负载下同时目击**(该轮机器同时在跑 PostgreSQL tier),单独跑绿、安静机全量绿,按窄口 (2)(a) 放行并在此登记为成员。机理与成员 1 那半边**完全一样**,而且是这一族最朴素的形状:用例在 `flush_task()` 的下一行就读投影出来的行,而 `flush_task` 约束的是**写**——投影 settle 只有一个预算,预算输给负载时读到的是空态或半态。**两条都不在 `test_sql_safety.py` 里**,所以本条开头那句「`test_sql_safety.py` 里全部 settle 依赖读断言的等价类」要按机理读、不要按文件读:等价类是「settle 之后紧接着读投影结果」的断言,`tests/ansich/` 里到处都是。
  8. `test_ansich_evaluations_router.py::test_plain_alert_dismissal_never_changes_quality_beliefs`(:934,`IndexError: list index out of range`——`/operations/alerts` 的 `items` 是空的)。**T12 收尾全量的一次翻红,失败文本完整**(见下方记账)。同一机理的第三种入口:`_open_tool_frequency_alert` 在 `flush_task()` 之后立刻 `assess_operations()`,评估读的是投影出来的 ToolCall 行——预算输给负载时那行还不在,tool-frequency 规则自然一条 Alert 都产不出,于是列表为空而不是断言值不对。修法同族(共享 settle helper:对持久行有界轮询),不是调大预算。
  9. `test_sql_usage_counts_one_tool_execution_across_started_and_terminal_evidence`(`tests/ansich/test_sql_usage.py:387-389`,断言在 :395)——**P11-B 批终审全量的一次翻红,失败文本完整**(见下方记账)。同一机理的**第四个入口**,也是**第二条不在 `test_sql_safety.py` 里**的成员:用例在 `await service.flush_task(task_id)` 的**下一行**就 `await service.get_task_usage(task_id)`,与成员 6/7 逐字同型、无门禁。失败文本本身把机理定死,并**排除**了「`RebuildOutcome` 之后行为变了」这一类解释:该用例断言 `usage == rebuilt`,而空的那一侧是**重建之前**那次读——

     ```
     assert usage == rebuilt
     - TaskUsageView(task_id='36e5ed56-…', local=(), inclusive=(), inclusive_status='available')
     + TaskUsageView(task_id='36e5ed56-…', local=(TaskUsageValue(dimension='steps', …, value=1,
         complete_through_ingest_seq=3), TaskUsageValue(dimension='tool_calls_issued', …
     tests/ansich/test_sql_usage.py:395
     ```

     `flush_task` 约束的是**写**、不是投影;settle 预算输给负载,那次读落在空态上,随后 `rebuild_projections()` 又把正确的行算了出来——「数据没问题,是读得太早」,这一族的签名。

  10. `test_sql_safety.py::test_a_dependency_deferred_job_below_the_mark_re_judges_its_band_once`(断言在 :2294)——**P11-C 批 Task 1 的一次全量翻红,失败文本完整**(见下方记账)。第五个入口,回到 `test_sql_safety.py` 里,但构造与成员 1-4 都不同:它既不压 `terminal_flush_timeout_ms`、也不把轮询压到 60s,而是**自造了一个 `await anyio.sleep(0.3)` 当 settle 预算**,一共三处,每处后面紧跟 `assess_operations(now=…)` 再读结论。红的形状是 `assert trigger_conclusions == 4` 实得 **0**——触发器自己的 subject 一条结论都没有,即那 0.3 秒里 ToolCall 投影/scope-safety 证据根本没落地,评估无从判起。这是本族最直白的签名(「读到空态」),只是预算这次是一个硬编码的 sleep 而不是一个 flush 超时;修法同族(共享 settle helper 对持久行有界轮询),**不是**把 0.3 调大。

  11. `test_sql_safety.py::test_absorbed_low_watermark_window_survives_an_evaluation_rollback`(断言在 :1946)——**P11-C 批 Task 2 的一次全量翻红,失败全文见下方记账**。第六个入口,与成员 10 同文件、同构造家族:它同样**自造了一个 `await anyio.sleep(0.5)` 当 settle 预算**——self-heal 那一步补投 blocking subject 的 ToolCall、`flush_task()`、`sleep(0.5)`、`assess_operations(now=…)`,然后数 `ansich_scope_conclusions` 的行。红的形状是 `assert late_conclusions == 4` 实得 **0**:那半秒里 blocking subject 的 ToolCall 投影没落地,scope-safety 的重试仍然停在依赖等待上,一条结论都没写。本族最直白的签名(「读到空态」),只是预算这次是 0.5 秒的硬编码 sleep;修法同族(共享 settle helper 对持久行有界轮询),**不是**把 0.5 调大。**P11-C 批 Task 3 的全量把这条成员又目击了一次,断言位置换了**:红在 :1905 的 `assert mark is not None and mark.evidence_watermark < late_last_seq`(`ansich_assessor_watermarks` 里那一行还不存在),即在 self-heal 之前、两个 `sleep(0.3)` 那一段就已经空了。所以成员 1 那句「**不要按行号认这条成员**」对本成员同样成立:同一用例、同一构造家族(自造 sleep 当 settle 预算)、同一机理,读到空的只是换成了 watermark 行。放行记账见下。

  12. `test_sql_safety.py::test_sql_projects_delete_and_permission_effects_as_typed_rows`(红在 `assert unverified[…] is not None`)——**P11-C 批 Task 11 修复轮的一次全量翻红,失败文本见下方记账**。第七个入口,又回到 `test_sql_safety.py` 里,但**构造是本族的第三种**:它既不压 `terminal_flush_timeout_ms`、也不自造 `anyio.sleep`,而是**只驱动一轮 `assess_operations`**——那一轮本身就是它的 settle 预算。机理已追到底,不是猜的:`flush_task` 只对**投影**作业收敛(`has_pending_for_task` 读的是 `ansich_projection_jobs`),`project_pending` 只**入队**评估作业而不跑它们,而 `scope_safety:unverified_effect` 这条 Belief 由 `_process_assessor_jobs` 写、只能从 `assess_operations` 到达——该用例只驱动**一轮**(:1015)。于是一次 replay-safe 依赖等待(主体 ToolCall Entity 尚未投影)把该评估作业交还自己的 attempt、加 250ms 退避推到下一轮,对那唯一一轮**结构上不可见**,Belief 落在该用例永远不会跑的下一轮上,读到的就是空态。修法同族、也同成员 10/11:**有界循环驱动 `assess_operations` 直到评估积压清空**(共享 settle helper 的评估侧那一半),**不是**把任何预算调大——这里也没有预算可调。**它与成员 10/11 的差别值得记下**:那两条的预算是一个可以被误当成「调大就好」的 sleep,这一条连那个诱惑都没有,单轮就是全部,所以它是本族「预算输给负载」这句话最一般形式的实例(预算 = 一次评估机会)。

- **窄口放行记账**(本条收尾规定的「命令行、轮次、全文」):
  - P11-C 批 Task 1 全量,成员 10(**本条第一次由 P11-C 登记**):`cd backend && timeout 1800 env PYTHONPATH=. uv run pytest tests/ansich -q -p no:randomly --no-header -rf`(不接截断管道,全文落 `/tmp/ansich-final-run2.txt`)→ `1 failed, 815 passed, 28 warnings in 342.77s`。失败全文:

    ```
    >       assert trigger_conclusions == 4
    E       assert 0 == 4

    tests/ansich/test_sql_safety.py:2294: AssertionError
    FAILED tests/ansich/test_sql_safety.py::test_a_dependency_deferred_job_below_the_mark_re_judges_its_band_once[asyncio] - assert 0 == 4
    ```

    讨伐,走 (2)(a):`cd backend && timeout 300 env PYTHONPATH=. uv run pytest "tests/ansich/test_sql_safety.py::test_a_dependency_deferred_job_below_the_mark_re_judges_its_band_once" -q -p no:randomly --no-header` **连跑 3 次,3/3 `1 passed`**(8.22s / 7.81s / 7.67s)。(2)(b) 无从走也不需要走:**该用例的函数体与批 BASE `dbfc9c8a` 逐字相同**(`git diff dbfc9c8a -- backend/tests/ansich/test_sql_safety.py` 只有两行,都在别的用例里),而 P11-C Task 1 的生产改动只碰 `retry_failed_projections` 的返回类型、新增 `rebuild_until_settled`、以及路由返回体——**这个用例一处都不调**(它只有 `flush_task` / `anyio.sleep(0.3)` / `assess_operations`)。同一轮之前的一次全量在同一棵树的前一个状态上是 **816 passed 全绿**,再前一轮红的是成员 4,即本族惯常的轮换。**唯一可想象的间接关联要如实写下**:同批把八处 `unsettled == 0` 的单轮断言改成了 `rebuild_until_settled()`,未结算时它最多多跑四轮重建,会给同一次全量增加墙钟与 CPU 负载——这不改变任何语义,但它正是本族赖以翻红的那个变量,所以记在这里而不是略过。
  - P11-C 批 Task 2 全量,成员 11:`cd backend && timeout 1800 env PYTHONPATH=. uv run pytest tests/ansich -q -p no:randomly --no-header -rf`(不接截断管道,全文落 `/tmp/t2-full-run2.txt`)→ `1 failed, 820 passed, 28 warnings in 340.89s`。失败全文:

    ```
    >       assert late_conclusions == 4
    E       assert 0 == 4

    tests/ansich/test_sql_safety.py:1946: AssertionError
    FAILED tests/ansich/test_sql_safety.py::test_absorbed_low_watermark_window_survives_an_evaluation_rollback[asyncio] - assert 0 == 4
    ```

    讨伐,走 (2)(a):`cd backend && timeout 300 env PYTHONPATH=. uv run pytest "tests/ansich/test_sql_safety.py::test_absorbed_low_watermark_window_survives_an_evaluation_rollback" -q -p no:randomly --no-header` **连跑 3 次,3/3 `1 passed`**(8.14s / 8.01s / 8.08s)。(2)(b) 不必走,理由是**结构性的**而不是统计性的:Task 2 的生产改动只有三处——`contracts.py` 的 `environment.sampled` 守卫(只在 `payload is None` 时改变行为)、`_claim_projection_job` 的 hydrate 顺序(对**内联** payload 逐字等价:`payload = row.payload_json`、`payload_ref_id = row.payload_ref_id`,不进 hydrate 分支)、以及 `get_environment_history`。该用例的 payload 全部远小于默认的 65536 字节、一条都不外部化,也不读环境 history,**三处一处都不经过**;同一棵树的前一个状态(只差 `contracts.py` 的一处等价重写与 AGENTS.md)那一轮全量是 **821 passed 全绿**。**唯一可想象的间接关联要如实写下**:这一轮全量是与我自己另外两批 pytest(`test_gateway_ansich_environment.py`,以及三个 persistence/feedback 文件)**并发**跑的,机器被自己压住——那正是本族赖以翻红的那个变量;此外 Task 2 新增的 800 指标外部化用例本身也给同一次全量加了墙钟与 CPU 负载。两者都不改变任何语义,但都记在这里而不是略过。
  - P11-C 批 Task 3 全量,成员 11(**同一成员的第二次目击,断言位置不同**):`cd backend && timeout 600 env PYTHONPATH=. uv run pytest tests/ansich -q`(全文落 `/tmp/claude-1000/.../blysazw2a.output`)→ `1 failed, 842 passed, 28 warnings in 323.38s`。失败全文:

    ```
    >       assert mark is not None and mark.evidence_watermark < late_last_seq
    E               assert (None is not None)

    tests/ansich/test_sql_safety.py:1905: AssertionError
    FAILED tests/ansich/test_sql_safety.py::test_absorbed_low_watermark_window_survives_an_evaluation_rollback[asyncio] - assert (None is not None)
    ```

    **这一次红在 :1905,不是登记时的 :1946**,即在 self-heal 那一段之前就已经空了:两次 `flush_task()` + 两个硬编码 `anyio.sleep(0.3)` 之后,`ansich_assessor_watermarks` 里连一行 `(task, "scope-safety", "1.0.0")` 都还没有——scope-safety 的评估在那 0.6 秒里根本没跑到。机理与登记时逐字同族(自造 sleep 当 settle 预算 → 读到空态),只是这次读的是 watermark 行而不是结论行。因此本条对成员 1 写下的那句「**不要按行号认这条成员**」对成员 11 同样成立,门禁条件 (1) 按**用例名**判定、已满足。讨伐,走 (2)(a):`cd backend && timeout 300 env PYTHONPATH=. uv run pytest "tests/ansich/test_sql_safety.py::test_absorbed_low_watermark_window_survives_an_evaluation_rollback" -q -p no:randomly --no-header` **连跑 3 次,3/3 `1 passed`**(9.15s / 8.11s / 8.09s)。(2)(b) 不必走,理由是**结构性的**:Task 3 的生产改动只有三个新模块级常量(`_REPLAYABLE_VERSIONS`、`_EXECUTABLE_PROJECTOR_NAMES`、`_KNOWN_OBSERVATION_KINDS`)、两个新纯函数(`_literal_members`、`_validate_replay_target`)、一条新异常类型,以及 `_projectors_for_kind` 的一段 docstring——**没有任何既存代码路径被改动**(`_projectors_for_kind` 的函数体逐字不变),认领、投影、评估、watermark 四条路上一行都没动,新符号在本任务之外无调用方。**同一棵树的第二轮全量(安静机,`/tmp/t3-full-run2.txt`)是 `843 passed, 28 warnings in 309.38s` 全绿**,这是本次放行能拿出的最强旁证:红的那一轮与绿的这一轮之间树没有变。**第四轮全量(`/tmp/t3-full-run4.txt`,`1 failed, 843 passed in 319.43s`)本成员又红了一次,这次是登记时那个逐字的签名**——`assert 0 == 4`,`test_sql_safety.py:1946`——即本成员在 Task 3 这台机器上两个断言位置各出现过一次;这本身就是本条「同一用例、多个断言位置、同一机理」判断的直接证据,也说明本轮机器上这一族的翻红率相当高(五轮里两轮撞上它)。**唯一可想象的间接关联要如实写下**:本任务给 `tests/ansich` 新增了 20 条用例(其中一条建 SQLite 库并写一条 Observation),给同一次全量加了少量墙钟与 CPU——不改变任何语义,但那正是本族赖以翻红的那个变量,所以记在这里而不是略过。
  - P11-C 批 Task 11 修复轮全量,成员 12(**本条第四次由 P11-C 登记,也是第一次「目击当批就登记」**):`cd backend && env PYTHONPATH=. uv run pytest tests/ansich tests/test_gateway_ansich_environment.py -q -p no:randomly`(不接截断管道)。该门禁在这棵树上**连跑两轮,每轮恰好一条红、且两轮红的不是同一条**,两轮都是 `1068 passed`;第一轮的红就是本成员。失败文本:

    ```
    >       assert unverified[…] is not None
    E       assert None is not None

    tests/ansich/test_sql_safety.py::test_sql_projects_delete_and_permission_effects_as_typed_rows[asyncio]
    ```

    讨伐,走 (2)(a):该用例**单独重跑 3 次,3/3 绿**;**整文件 `test_sql_safety.py` 连跑 3 次,3/3 绿**。(2)(b) **走过,但结论是它不成立,如实记下**:把修复轮 stash 掉、在批 BASE `f1d52a79` 上跑同一条门禁,**1065 passed 全绿**,所以「BASE 上同样红」这条路径**不成立**,本次放行只靠 (2)(a) 这一条腿站着。**并且那次 BASE 对照有一个必须写明的减项**:BASE 那棵树**没有**本修复轮新增的五条起服务的用例(1065 对 1068),而本族赖以翻红的变量正是同一次全量的墙钟与 CPU 负载——所以 BASE 全绿只能读作「BASE 那个负载下没红」,**不能**读作「本轮改动无关」这句话的证明。那句话另有一个**结构性**的论证,与统计无关:本修复轮触及的只有锁**顺序**(只读)、一条 exhaustion 日志、一处返回类型拆分、测试侧注入与文档——认领、依赖等待、作业入队、评估节奏这四条路上一行未动,而本成员的机理整个住在最后两条上。**本次没有走本条的窄口**:红出现时本用例尚未列名,按窄口 (1) 它是**阻断**的;实施者没有拿它当放行凭据,而是把证据带到这里先成为成员——上面这份记账就是它此后可走窄口 (2)(a) 的凭据本身。
  - T10 复审轮,成员 6 与成员 7:**2026-08-22 按本条自己的记录规则补齐**(此前只记了结论,已按 `task-10-review.md` 的复审段重建;凡是重建不出来的都在下面明说,不补造)。
    - 命令行:`cd backend && timeout 2400 env PYTHONPATH=. uv run pytest tests/ansich -q -p no:randomly --no-header -rf`;那一轮复审者把自己的 PostgreSQL 实验(90 万行灌库 + `EXPLAIN`)与全量**并发**跑,机器被自己压住(1056s,对照实施者的 379s)。
    - 结果:`802 passed / 2 failed`。失败文本(复审段落逐字保留的两行):成员 6 `AssertionError: 子 Task 内部确实完成了`;成员 7 `tools_executed=0 != 1`。
    - 讨伐:两条单独重跑立即**双双绿**,随后同机安静轮 `tests/ansich` 全量 **804/804 绿、零 FAILED**——走 (2)(a)。
    - **重建不出来的部分,如实记下**:(i) 单独重跑的**轮次**只留下「立即 2/2 绿」这一句,即两条用例各绿了一次,**不是**本条 (2)(a) 字面要求的「同一用例连跑 3 次 3/3」;(ii) 两份全文落盘文件(`<scratchpad>/t10fix-ansich-suite.txt`、`<scratchpad>/rerun-2.txt`)存在复审者的 scratchpad,**未随批留存**,现在取不回来。因此这两条成员的放行**在轮次这一项上不满足本条的记录规则**——保留登记(机理与失败文本都确凿),但证据强度按「一轮单独重跑 + 一轮安静机全量绿」读,不要按 3/3 读。补一次 3/3 是下次触达这两个用例时应顺带做的事。
  - P11-B 批终审全量,成员 9:调用形状是「`tests/ansich` 在一次**完整** `tests/` 全量里跑、`-p no:randomly`、不接截断管道」,那一轮 `tests/ansich` 得到 **804 passed / 1 failed**,失败就是上面成员 9 那段文本(全量整体 `14 failed, 9754 passed, 75 skipped in 785.35s`,另外 13 条红全部在 ansich 之外、属环境/实时 LLM/配置依赖,不在本批面上)。讨伐:该用例**单独重跑 3 次,3/3 `1 passed`**,并且是在**全量仍在跑**(即仍有负载)的条件下拿到的——比安静重跑更强——走 (2)(a)。**未随批留存的部分**:两份全文文件(`FINAL-pytest-ansich.txt`、`FINAL-flake-triage.txt`)在终审者的 scratchpad;逐字命令行没有进台账,只留下上面这句调用形状与全部数字。按窄口 (1),该红在被登记为成员 9 **之前**是阻断的,登记与放行是同一次修复波里做的。
  - T12 收尾全量,成员 8:`cd backend && PYTHONPATH=. uv run pytest tests/ansich -q` → `1 failed, 804 passed in 292.13s`,失败文本即上面那条 `IndexError`(完整栈已在 T12 报告里)。随后 `cd backend && PYTHONPATH=. uv run pytest "tests/ansich/test_ansich_evaluations_router.py::test_plain_alert_dismissal_never_changes_quality_beliefs" -q` 连跑 **3 次,3/3 `1 passed`**——走 (2)(a);随后同机把 `tests/ansich` 全量再跑一次,**805 passed 全绿**(第一轮 804+1 failed,第二轮多的那一条是 T12 新增的 lease-lock 钉子)。该用例在本批未被任何改动触达(T12 的树只加了两处注释与一条无关的新用例)。

- 方向(经十二名成员修正):这不是一份可枚举的成员清单,而是 `tests/ansich/` 里**所有「settle 之后紧接着读投影结果」的断言**的等价类(最先识别时以为它只住在 `test_sql_safety.py` 里,成员 6/7/8/9 证否)——多种构造、多种症状、同一机理(settle 预算输给负载)。修法应是一个**共享的确定性 settle helper**(对 flush/重排队/作业落地路径按持久行轮询,替代各测试自造的预算与等待),而非逐条加长各自的预算;成员 4 另需保证两条证据在**同一** watermark 区间内落地再断言。~~普通负载下极少翻红,合并门禁仍以安静机全绿为准。~~ **该收尾句已由 T6 撤回**:成员 1 与成员 5 都在安静机、无并发负载下翻红过(前者单独跑 3 次即红 1 次,且在批 BASE 上同样红),所以「安静机全绿」既不是这一族的稳定属性、也不能当作合并判据。在共享 settle helper 落地之前,合并门禁对本族**只开一个窄口**。放行必须同时满足 (1) 与 (2),缺任一即**阻断**:

  1. **具名成员**。翻红用例的**名字**必须已列在本条成员 1-12 之中(按用例名认领,不按行号)。**未列名的红一律阻断**,直到分诊完成;若分诊确认同机理,先带证据把它写进本条成为新成员,再走本窄口(成员 6/7/8/9/10/11/12 就是这样进来的;成员 12 是第一条**在目击那一批**就完成登记的,而不是把登记推给下一批——登记发生在目击时,是本条对未列名红的要求)。**分诊时先看失败形状**:红的形状若是「`unsettled == 0` 被当作完成 / 重建单轮后断言完整性」,那不是本族——那是 F10-26 的 report-don't-wait 语义未被调用方消化,见该条 2026-08-22 的留观;本族的签名是「settle 之后紧接着读投影结果,读到空态/半态/多判一轮」。「`tests/ansich/` 里所有『settle 之后紧接着读投影结果』的断言的等价类」是**修法的范围**,**不是**门禁的认领范围——门禁只认已列名的用例。
  2. **两条讨伐路径,至少走通一条,全文入证据**:(a) **单独重跑全绿**——该用例单独重跑 3 次 3/3 绿;或 (b) **BASE 对照复现**——在批 BASE 上以同样方式重跑,同一红在 BASE 上同样出现(⇒ 与本批改动无关)。改动重写了该路径致 BASE 对照不可行时,(a) 是唯一路径。两条都走不通(单独重跑仍红**且** BASE 上稳定全绿)⇒ **阻断**,按新回归处理。

  每一次放行都按本条记账:命令行、轮次、全文。
- 归属:下一次测试卫生波;F10-10 留观的兄弟条目。

## F10-31. LLM attempt 双观测的首写者 pkey 竞态

- 状态:✅ 已修复(2026-08-22,P11-C 批 Task 11,`f1d52a79`)。第五处 lock-then-read 转换落在 `sql.py::_lock_or_open_llm_attempt`:先对 attempt 行取锁再读,行不存在时用 `_insert_ignoring_conflict`(`attempt_id`)以 `incomplete`、**不带任何观测指针**开行,然后**无论赢输都**在锁下重读,再走同一段分支合并——插入与合并是一条路径,而不是同一套规则的两种写法。
  - **合并语义已裁定**:两个 obs 指针**各写各的**因而天然组合(已置指针永不被 `None` 覆盖);状态走 `_advance_llm_attempt_status`,取 `incomplete < requested < success` 的格上极大值;`failed` **不在**该格内,两条边显式裁定——`llm.requested` 不得把已记录的失败退回,而 `llm.responded` 落在 `failed` 行上**保留**改动前的「后写者胜」(需要同一 attempt 同时携带 `llm.failed` 与 `llm.responded`,没有生产者会发出;逐字保留是因为「重新裁决互相矛盾的终态」是另一个问题,而且没有证据支撑)。
  - 「同一指针被双方写成不同值」**由构造上不可能**:指针值就是投影方观测自身的 `obs_id`,一条观测归一个作业,列上还有 `unique=True`。
  - 顺带收口了本条未记的另一半:**既有行上**的读-改-写此前也无锁,输家的 ORM UPDATE 会带着读到的旧 `status`。
  - **同一提交移除了 PG tier 按约束名的类型化容忍**(`test_the_concurrent_usage_fan_out…` 现在对任何投影错误都翻红)。移除这条容忍**立刻暴露出同型的第二个竞态**,单列为 `F10-35`——这正是类型化容忍这条纪律存在的理由。
- 原始诊断(留档)——位置:`backend/packages/harness/deerflow/ansich/persistence/sql.py` 的 attempt 投影站(~:9499-9516 区,按符号定位):`session.get(AnsichLlmAttemptRow, …)` → 构造 → `session.add`,随后按分支**变更**该 ORM 对象(`request_obs_id`/`response_obs_id` 与 `incomplete→requested`/`→success` 状态转移)。
- 现状:同一 attempt 的 request 与 response 两条观测被两个 worker 并发投影时,首写者竞态在 `ansich_llm_attempts_pkey` 上碰撞。**非破坏**:输家的整个作业事务回滚→`retry`→下次认领读到赢家的行→收敛(tier 断言精确和数 24/36/60 与零未结算)。T9 的双 worker 用例按**约束名类型化容忍**这一形状(仅 `ansich_llm_attempts_pkey`;别的约束上的重复键仍然翻红)。
- 方向:不是一行 `ON CONFLICT` 能了——需要 T5 形状的第五处 lock-then-read 转换:`_insert_ignoring_conflict` + 赢家行的 `FOR UPDATE` 重读 + 输家字段如何合成(两个 obs 指针与 status 转移的组合语义)要一并裁定。归 attempt 投影器的下一次触达,或 P11-C。

## F10-32. 活动 Task 读模型的「旧盖章」楔子(以及那条必须被重判的前提)

- 状态:✅ 已修复(2026-08-22,P11-C 批 Task 8,`c0cdbfa3`;该迁移随修复轮 `d1b595b9` / `1d23af18` / `32097626` 继续加固,但数据步本身自 `c0cdbfa3` 起未变)。**修法不是重判那条前提,而是把前提杀掉**:迁移 `0028_ansich_retention` 带一个数据步 `DELETE FROM ansich_active_task_read_model`,即下面「方向」里点名的 (b)。
  - **为什么这样比在部署时重判更好**:那条前提(「没有已部署群体带着旧盖章」)会**静默**失效,没有任何测试会因此翻红,所以任何形式的「记得去查」都是把一次必答题挂在人的记性上。删掉行之后,问题不存在了——`ansich_active_task_read_model` 是**纯读模型**,下一轮运维 tick 全量重建(`rebuild_projections()` 本来就是这么干的),全部代价是升级后首次启动的一到两秒里 Running 透镜为空。
  - **本条的三选一因此已被回答**:选的是 (b)。(a)「去查目标环境」与 (c)「写进发布说明并接受陈旧」都不再需要。
- 原始诊断(留档;**登记为带前提的接受**,不是无条件接受)。来源:P11-B 批 T10 修复轮的控制者裁定,批终审(F11)要求给它一个编号、一个归属,以及一个能把下面那条前提**带到部署那一刻**的载体。
- 位置:`backend/packages/harness/deerflow/ansich/persistence/sql.py::_is_staler_publish` 与 `_refresh_active_task_read_model` 里的守卫站与清扫站;叙述在 `backend/AGENTS.md` 的「P11-B health database merge and the read-model stamp」段末。
- 现状:`c7ce07a8` 之前写下的 `ansich_active_task_read_model` 行,`projection_watermark` 里装的是**旧语义**(那个 worker 自己投影到的最高 `ingest_seq`),它**位于或高于**新的全库连续性标记。只要库里还有一条 durably `failed` 的作业,这种行的基准就高于此后每一轮 tick 的标记,于是被单调发布守卫(裁决 PB7)整行跳过:
  - Task 还在跑 → 每轮 tick 一条 DEBUG,**可见**;
  - Task 已经停了 → 被同一基准守着的清扫**静默保留**该行,它会一直读作 `running`,直到被清掉。
  处理办法是既有的两条运维动作:重试那条失败作业,或者跑一次 `rebuild_projections()`(rebuild 直接删掉这些行)。
- **前提(本条的全部分量都在这里,必须随本条一起读):** 当时接受它的唯一理由是「**P11-B 的所有提交都还没推,没有任何已部署的群体带着旧盖章**」。这个前提**会在这个分支第一次部署的那一刻失效**,而且是静默失效——没有任何测试会因此翻红。因此:**这个分支第一次部署之前,必须重新裁决本条**,给出三选一的结论并记下来:(a) 确认目标环境确实从未跑过 `c7ce07a8` 之前的 Ansich 读模型写入(⇒ 前提仍成立,可保持现状);(b) 上一次一次性的重铸/清空迁移(删掉旧盖章行,让它们按新语义重建);(c) 明确接受「首次部署后可能有若干活动 Task 行陈旧、若干已停 Task 行残留,直到一次 rebuild」并把它写进发布说明。**不允许的是默认第 (a) 条而不去查。**
- 方向:(b) 是最省心的一条——一次 `DELETE FROM ansich_active_task_read_model`(该表是纯读模型,下一轮 ops tick 全量重建,rebuild 本来就这么干);代价是重建前的一两秒里 Running 透镜为空。真正要做的是**在部署前把这个决定做掉**,而不是把它留成一条注释。
- 归属:**P11-C,或此分支的首次部署评审——以先到者为准**(部署评审优先:前提正是在那时死掉的)。

## F10-33. 多 worker 下同一 host-Scope episode 的并发碰撞会丢掉整轮 assess_operations

- 状态:✅ 已修复(2026-08-22,P11-C 批 Task 11,`f1d52a79`;锁序补齐见 `d2ca0392`)。采用「方向」里前一条的**变体**——不是对 Scope 主体加咨询锁,而是把 lock-then-read 姿势用在 **episode** 上:
  - `_persist_alert_episode` 以 `ON CONFLICT (alert_key, episode) DO NOTHING` 开 episode;输家撤回自己刚铸的 `ansich_entities` 行(`ansich_alerts` 没有能把它带走的入边),`_locked_alert_episode` 在 `FOR UPDATE` 下重读赢家行并水合证据,`_reconcile_opened_episode_against_winner` 用**从候选反推的 `AlertCondition`** 重新交给 `reconcile_alert_episode` 裁决——**不是**手写 `model_copy`,因为两轮之间被运维 resolve 掉的赢家应当开下一号 episode 而不是 confirm。
  - 一次碰撞的代价从**整轮** `assess_operations` 降成**一次行重读**。重试由 `_ALERT_EPISODE_FIRST_WRITER_PASSES`(3)有界,**耗尽只打 DEBUG 并留给下一轮,绝不 raise**——在那里 raise 等于把本条要消除的整轮丢失又请回来。
  - 同一调用点的 reconciliations 现在按 `(alert_key, episode)` **排序后再写**:输家的 `FOR UPDATE` 是这笔事务里的第二把行锁,而 host `Scope` 两个生产者的条件顺序本就依赖 worker 间合法不同的分区——「排序放在取锁的那一站」是本仓库既有的规矩。
  - **PG tier 的用例改严**:`test_two_workers_assessing_the_same_task_never_duplicate_an_episode` 从「发生就响」改为任何一轮都不得 raise、每一轮每个 Task 恰好一条 episode(此前允许输家整批不开的那条放宽已删除)。**要如实读它**:碰撞被吸收之后从断言上不可见,所以「没进入争用窗口」与「进入并处理了」两种跑法长得一样——它是**严格的回归守卫,不是一次现场演示**。留下的可观测物是 `SqlAnsichBackend.episode_first_writer_loss_count`(进程本地调试计数器,tier 只打印从不断言;要求一次真竞态才算数会让一次诚实的绿变 flaky)。
- 原始诊断(留档)。来源:P11-B 批 T8 实施者自报、T8 复审校正严重度(「loud」是错的:`_projector_loop` 当时是**静默**吞掉的),T9 的双 worker tier 在真 PG 上**实际provoke出来**过一次。
- 位置:`sql.py::_persist_and_reconcile_process_health` → `_reconcile_alerts_for_assessments` → `uq_ansich_alert_episode`;叙述在 `backend/AGENTS.md` 的「What this slice did **not** establish」段。
- 现状:一台主机上的每个 Gateway worker 都以**同一个** host `Scope` 为主体、各自跑自己的 1 Hz 评估,于是两个 worker 同时开同一条 episode 会在 `uq_ansich_alert_episode` 上碰撞。**不腐蚀**,而且是任何 `host` 作用域环境告警早就有的既存暴露;但代价不小:炸的是**整个** `assess_operations` 事务,那一轮的 heartbeat、dwell、budget、environment 与两个 process-subject 生产者一起被丢掉。P11-B 至少让它不再无声——`AnsichService._report_assessment_failure` 每次都带 traceback 打 DEBUG、并按 `_ASSESSMENT_WARNING_INTERVAL_SECONDS` 限速打一条 WARNING(带被压制计数),两者都 fail-open。下一轮(一秒后)重做。
- 方向:要么给 Scope 主体的对账串行化(一把按 `scope_id` 的咨询锁,或把 episode 的开启改成 `ON CONFLICT DO NOTHING` + 重读赢家行——即 T5 的 lock-then-read 姿势用在 episode 上),要么把这两个生产者从共享的 `assess_operations` 事务里拆出来,让一次碰撞只丢掉它们自己那一段而不是整轮。前者更根治,后者更便宜;两条都需要各自的死锁面/语义评估,不是一行改动。
- 归属:P11-C(与 F10-31 同一族:剩下的首写者/唯一约束竞态)。

## F10-34. PG tier 的 `_drain_projections` 在退避作业前停手,被当成「投影已完结」

- 状态:✅ 已修复(2026-08-22,P11-C 批 Task 11,`f1d52a79`)。出事的那个调用点 `test_reversing_the_lock_traversal_order_deadlocks_on_postgres` 的 setup 已从 `_drain_projections` 改为 `_settle_projections`——即本条「方向」里开出的那一行,不多不少:`_drain_projections` 自己的语义**没有**被改动(那会影响它全部调用点,本条主张过要单独评估),`rounds` 也没有被调大。Task 11 是那次触达该文件的改动,按本条的归属「任何下一次触达该文件的改动顺带处理」顺手结清。
  - **同一批里的相邻工作要一起读,但不要混为一谈**:P11-C 的 Task 3b 做的是 F10-26 的修法(把 31 处裸 `rebuild_projections()` 完整性断言转成有界循环),那是另一条的形状;本条是 `_drain_projections` 在退避作业前停手,两者的分诊在下面写得很清楚。
  - **仍然开着的是那条更彻底的一步**:让 `_drain_projections` 自己在返回前确认没有 `retry` 作业在退避。本条不主张它,归属仍是「下一次测试卫生波」。
- 原始诊断(留档;测试侧,生产行为无关,一行改法已知)。来源:P11-C 批 Task 9b 的 PostgreSQL tier 全量一次翻红。
- 位置:`backend/tests/integration/test_postgres_multiworker.py::_drain_projections`(:497)与出事的那个调用点 `test_reversing_the_lock_traversal_order_deadlocks_on_postgres`(:1204)。
- 失败全文:

  ```
  tests/integration/test_postgres_multiworker.py:1208: in test_reversing_the_lock_traversal_order_deadlocks_on_postgres
      assert len(dimensions) >= 2, f"need two lockable summary rows, got {dimensions}"
  E   AssertionError: need two lockable summary rows, got ['llm_attempts']
  E   assert 1 >= 2
  ```

- **分诊:这条红既不属于 F10-30,也不属于 F10-26,所以它必须自己立条。** 按 F10-30 窄口 (1) 的分诊规则先看失败形状:
  - **不是 F10-30**。本族的签名是「settle 预算(flush 超时 / 硬编码 sleep)输给负载」。这里的 settle 不是一个预算:`_drain_projections` 是一个**有界循环**,循环到 `project_pending()` 返回 0 才退出,**不看墙钟**。负载再重也只是让它多转几圈。
  - **不是 F10-26**。本族的签名是「`rebuild_projections()` 单轮被当成完成 / `unsettled == 0` 被当成完整性」。这里根本没有 `rebuild_projections()`,断言也不是 `unsettled == 0`。
  - **真机理,而且这个文件自己已经写下来了。**`project_pending()` 返回 0 的含义是「**当下没有可认领的作业**」,不是「没有欠着的作业」:一条被重新武装成 `retry` 的作业带着未来的 `available_at`,在退避窗口里就是不可认领的。所以一次首写者竞态(争用下的回滚 → `retry` → 退避)会让 `_drain_projections` 干净地返回,而 usage 汇总只写出了一个 dimension。`_settle_projections`(:509)的 docstring 一字不差地描述了这半件事——「A job re-armed to `retry` carries an `available_at` in the future, so a plain drain stops with it still outstanding」——它就是为此存在的,只是这个调用点用的是弱的那个 helper。
- 讨伐(走 F10-30 窄口的两条路径,两条都走通了,尽管本条不归 F10-30):
  - (a)**单独重跑 3/3 绿**:`cd backend && DEER_FLOW_TEST_POSTGRES_URL=… PYTHONPATH=. timeout 300 uv run pytest "tests/integration/test_postgres_multiworker.py::test_reversing_the_lock_traversal_order_deadlocks_on_postgres" -m integration -q -p no:randomly --no-header` 连跑 3 次,**3/3 `1 passed`**(7.09s / 7.09s / 7.42s);随后同机把整个 tier 再跑一次,**25 passed** 全绿。
  - (b)**结构性排除**:该用例的函数体与批 BASE `26e70907` 逐字相同(Task 9b 只在这个文件末尾**追加**了一条新用例,一行都没改既有内容);Task 9b 的生产改动全部在 `run_retention` 的三个 tier 与一个新的级联规划器里,认领、投影、usage 扇出四条路上一行都没动。
  - **唯一可想象的间接关联如实写下**:红的那一轮 PG tier 是与 `tests/ansich` 的 1000+ 条 SQLite 全量**并发**跑的,机器被我自己压住——争用正是首写者竞态(`F10-31` / `F10-6` 残留)赖以发生的那个变量,而这条 helper 的弱点是把那次竞态的后果从「慢」变成了「红」。
- 方向:那个调用点改用 `_settle_projections`(它做的正是「drain → 把退避的 `available_at` 拉到当下 → 再 drain」,严格更强,不会削弱该用例证明的任何东西)。更彻底的一步是让 `_drain_projections` 自己在返回前确认没有 `retry` 作业在退避——但那会改变它对**所有**调用点的语义,应当单独评估;本条只主张改这一个调用点。**不要**靠调大 `rounds`:那个界不是问题所在。
- 归属:下一次测试卫生波(与 F10-30 / F10-26 的 settle helper 工作同一批),或任何下一次触达该文件的改动顺带处理。

## F10-35. `ansich_current_beliefs` 首写者竞态的**整轮**爆炸半径

- 状态:✅ 已修复(2026-08-22,P11-C 批 Task 11,`f1d52a79`,与 F10-31/F10-33 同一提交;锁序由 `d2ca0392` 补齐)。来源:**移除 F10-31 的类型化容忍之后立刻暴露**——PG tier 3/3 稳定翻红在 `ansich_current_beliefs_pkey`,`(subject_id, field_name) = (<task>, "heartbeat")`。在批 BASE `3cd8bb44` 上该用例**是绿的**,因为它把**任何** `IntegrityError` 都当作「episode 碰撞」吞掉——那条容忍一直在遮蔽第二个同型的整轮丢失。
- 位置:`sql.py` 的 `assess_operations` heartbeat 段、`_assess_budget_rows`、`_resolve_current_assessment`(后者即 F10-6 记下并延期的那半边)。
- 机理:同一台主机上每个 Gateway worker 各跑自己的 1 Hz `assess_operations`,**整轮是一个事务**;两个 worker 同时为同一个 Task 首写 `heartbeat` 当前 Belief 行,双方都读到「没有」,双方都 insert。爆炸半径与 F10-33 逐字相同:heartbeat / dwell / budget / environment 与两个 process-subject 生产者一起被丢掉。
- 修法:三处运维轮写入统一走 `_open_or_lock_current_belief`(`INSERT … ON CONFLICT (subject_id, field_name) DO NOTHING` + 赢家行的 `FOR UPDATE` 重读),且都改为「先锁行、再读用来比较的 Assertion」。`_resolve_current_assessment` 改为**有界两遍**并在第二遍**重新归约**(它的输入是该 subject/field 的*全部* Assertion,对手那条在第一遍的 READ COMMITTED 快照里不可见);heartbeat / budget 两处的输家把赢家行指向自己这一遍的 Assertion——与「读第二」的那一轮同解。两遍的上界**对任意 W 都够**,论证写在循环处:`ON CONFLICT` 只在冲突插入**已提交**之后才报告一次失败,所以第二遍的 `FOR UPDATE` 必然找得到那行;W−1 个输家在一把非 `skip_locked` 的锁上排队,而没有任何东西会删掉这行。耗尽两遍只打 DEBUG(`ansich.current_belief.first_writer_unsettled`),不 raise。
- **已知代价(如实记账,不是遗漏)**:heartbeat / budget 两处在知道自己输掉之前就已追加了 Assertion(当前 Belief 行的外键要求 Assertion 先存在),因此一次首写碰撞会给该 subject 多留**一条同判定的 Assertion**——**每个输家一条**,W 个并发首写者就是 **W−1** 条,不是「一条」。真正值得声明的界是**每个 subject 一次性**:此后行已存在,普通的 unchanged-skip 生效。Belief Assertion 本就是只追加、保留冲突项的模型,所以这是有界的诚实代价而非腐蚀;测试对这个增量有断言。**另一半代价要一起读**:每条多出来的 Assertion 都是「保留但未选中」的,因此把该字段的 `conflicting_assertion_count` 永久加一——一条从来没有人有分歧的 `heartbeat` Belief 会读作「有 1 条冲突」。按该字段自身的定义(「保留并被搁置」,不是「有分歧」;由 `test_conflicting_assertion_count_counts_retained_non_selected_assertions` 具名钉住,前端冲突徽标也照此渲染)这不是算错,所以本批选择在 `belief/resolver.py` 的字段声明处**如实写下**而不是收窄语义。
- **争用也变了,而且不是免费的**:改前一轮什么都没变的 tick 在这张表上**一把行锁都不取**;现在每个运行中 Task 每一轮 1 Hz tick 都取一次 `FOR UPDATE` 并持到提交,于是两个 worker 的 tick 从「只在有转移时串行」变成端到端串行。这是正确的姿势,死锁自由由两处 `ORDER BY`(`assess_operations` 的运行中 Task 选择按 `task_id`;`_periodic_budget_rows_statement` 按 `(task_id, dimension, aggregation_scope)`)保证;但多 worker 下 tick 变慢从此是**预期后果而不是谜团**。恢复转移门禁需要「先无锁检查、要写再取锁并在锁下**重新**检查」两遍走 tick 最热的循环,已具名为下一步,**刻意不与正确性修复同批**。
- **不在本条范围,但边界不是「tick / 投影」那么齐整**:同一张表的两处**纯投影路径**写入(`_project_control` 的 `control`、ToolCall 终态的 `execution`)不转换——那里一次碰撞的代价是一个作业事务 + `retry`,即 F10-6 已记录的有界自愈形状,不是一整轮。**但要说清楚:被转换的三处里 `_assess_budget_rows` 本身也会从 `_project_control` 的终态分支被调用**,即它同时坐在投影路径上。在那条路径上本次改动把「回滚重来、最终收敛到一条 Assertion」换成了「提交,并多留一条同判定的 Assertion」——对可用性严格更好,但那是本条声称「未触及」的路径上的行为变化,写明而不是留给读者以为 tick / 投影是一条干净的分界线。
- 归属:已完成(P11-C 批 Task 11)。剩下的转移门禁恢复见上,归下一次触达运维 tick 的改动。

## F10-36. 认领处的抛永远变不成一条运维可见的失败作业(全局静默停摆)

- 状态:⚠️ 部分处理(2026-08-23,P11-C 批终审修复波,`f5e57238`)。**方向 (c) 已落,停摆本身仍未修。** `_project_pending` 的那句 `except` 现在把异常路由到 `_report_projection_failure`:每次都打一条带 traceback 的 DEBUG,并按自己的 60s 窗(不与评估 tick 共用,否则更快的轮询会把更慢的事故盖掉)打一条 WARNING,被压掉的条数骑在下一条上。登记在此的原因不变:F10-29 的 hydrate 提前**扩大了它的暴露面**,而按旧措辞(「作业 durable failed」)读它会把人引向错的补救方向。来源:P11-C 批 Task 2 复审实测。
- **RC6 的「响亮」第三态就是本条的输入之一**(批终审 B5)。`_hydrated_observation_payload` 刻意让 *missing*(没有 tombstone 的缺失 payload = 损坏)继续抛 `RuntimeError`,理由是「这不是策略结果,应当被看见」。但在认领路径上那一抛正好落进本条:回滚自己的认领、永远到不了 `failed`、被这句 `except` 吞掉、并按 `ingest_seq` 把全进程的投影堵死。也就是说 **RC6 唯一刻意保持响亮的状态,后果是全系统最安静的那一个**——读 RC6 的人(spec、AGENTS、计划里都有那段)会合理地以为损坏会被发现。限速日志让它至少**被报告**;要让它变成一条运维可见的失败作业,仍然要本条的 (a) 或 (b)。两处 docstring(`_hydrated_observation_payload` 的 *missing* 段、`_project_pending`)现在互相指向本条。
- 位置:`sql.py::_claim_projection_job`(抛出点)、`packages/ansich/ansich/service.py::_project_pending`(`service.py:4054-4065`,那句 `except Exception: return 0` 在 :4064-4065)、认领语句的 `ORDER BY AnsichObservationRow.ingest_seq`。
- 现状,三段连锁,每一段都被单独实测过:
  1. **抛回滚自己的认领事务**,`attempts` 的自增随之回滚,所以那条作业**永远到不了 `failed`**——观测到的稳定态是 `status='pending', attempts=0`,永远。
  2. **循环不死**:`_project_pending` 把后端调用整个包在 `try/except Exception: return 0` 里,`ValidationError`(是 `ValueError`)与 `RuntimeError` 都被吞成「本轮处理了 0 条」,循环照转、照撞同一行(复审实测:循环存活,约 1090 次空转认领)。**不要按「投影循环会死」读本条**——那会把人引向「补一个 supervision / 重启」的错方向,复审已实测证伪。
  3. **危害在第三段,而且是静默的**:认领按 `ingest_seq` 排序,一旦这条毒行成为最低的可认领作业,**每一轮 `project_pending` 都在它这里中止**,后面的作业一条都碰不到——**全进程、所有 Task 的投影就此永久停摆**。而它不吵:异常被那条 blanket `except` 吃掉,健康面又只数 `status='failed'`,于是 health 报 `reachable`、`failed_jobs=0`、`projection_failure` 告警一条都不产,只有 `lag_ms` 与 `complete_through` 会动。
- **P11-C 扩大了什么(如实写下)**:F10-29 把 hydrate 提到 envelope 构造**之前**,于是**任何**一条不再满足自身契约的 externalized payload 都会在认领处抛(改前那份 payload 根本没被校验过)。这是正确的方向——不校验就投影是更坏的选择——但它把一个此前只有畸形内联行才能触发的形状,变成了任何「契约收紧之后的旧外部化行」都能触发。
- 方向:三条候选,都不便宜,需要一次裁决而不是顺手改一行:(a) **让认领处的抛把行标成 durable failed**——需要在认领事务**之外**、用一条独立事务记 attempt/错误行,否则回滚照旧;(b) **让认领跳过毒行**(把抛的那一条移出本轮候选集,而不是中止整批),代价是要能区分「这一行有毒」与「存储暂时不可用」;(c) **至少让它不静默**:在 `_project_pending` 的 `except` 里按作业 id 限速打一条 WARNING,并给一个进程本地计数器(`stale_completion_count` 的先例)。(c) 最便宜且与 (a)/(b) 不冲突,建议先做。**不要**靠调健康面的阈值:失败作业计数在本形状里恒为 0,它不是个可以调的数。
- 归属:下一次触达认领/投影循环的改动,或 Phase 12 的运维可见性批。与 `F10-40` 是同一类缺口(投影侧的丢失没有观测面),两条应当一起裁决。

## F10-37. `_project_control` 不幂等,`task-control` 的普通重放今天就是坏的

- 状态:⬜ 未修复。**既存缺陷,由 P11-C 批 Task 5 在真库上直接观测到,刻意未修**(那是一次 projector 幂等性改动,不在 §5 的范围里,值得自己的红先用例)。
- 位置:`sql.py::_project_control` 写 `ansich_transitions` 的那一段;`evidence_obs_id` 上有唯一约束。
- 现状:对一条**已投影**的 control Observation 重新投影会撞 `ansich_transitions.evidence_obs_id` ⇒ 作业进 `retry`,耗尽 attempts 后 `failed`。直接观测:在一个已结算的库上跑 `execute_replay(projector_name="task-control")`,结束时 `unsettled=1`,`last_error` 里是 `IntegrityError`。**rebuild 不受影响**,因为它连 Belief 一起删,`should_select_control_candidate` 面对的是干净的起点。T4 的 tier 看不见它,因为那里唯一的 `task-control` 用例出于无关的理由断言 `unsettled > 0`。
- **今天怎么被挡住的(是警告,不是拒绝)**:登记在 `_NON_IDEMPOTENT_PROJECTORS`,`replay_cli` 在开跑前和「这趟还欠账」的报告旁各打一次 stderr 警告。之所以不拒绝:**同一条命令在那些 Observation 从未被投影过的库上是对的**。之所以必须警告:退出码 `1` 读起来像临时积压,而操作者顺手的两个补救(再跑一次、`retry_failed_projections`)都会撞回同一处,永远清不掉。
- 方向:给该 projector 补幂等——把 transition 的写入改成「按 `evidence_obs_id` 的 upsert / `INSERT … ON CONFLICT DO NOTHING`」,并裁定重放遇到已存在 transition 时 `from_value` 该取哪一个(这正是 `--replace` 拒绝 `task-control` 的同一条性质:它的 `from_value` 取自共享的 current control Belief)。修完之后 `task-control` 才谈得上进 `_REPLACE_PROVEN_PROJECTORS`,那是另一条独立的证明义务(见 §5 第 6 条)。
- 归属:下一次触达 `_project_control` 的改动,或任何一次要让 `task-control` 可重放的工作。

## F10-38. owner/thread 强删除的两条 v1 不可解形状

- 状态:⬜ 未修复(**v1 限制,已诚实拒绝**)。来源:P11-C 批 Task 10 的第 2/3 轮复审压力测试。**两条都不会半途留下残骸**:一条在动第一笔删除之前就被预检拒掉,另一条以 `blocked` 点名那条可移除的边并回滚本次 Task 的 Entity 删除,整次擦除保持可重跑。
- 位置:`sql.py::hard_delete_scope` → `_refuse_unsatisfiable_pins`(预检)与 `_hard_delete_protected_pin`(phase 5 的拒绝)。
- 两条形状:
  1. **被类型拒绝的 pin。** 一次擦除只删一个 Scope。当该 Scope 名下某个 Task 的一条 Observation 是**外部**某实体的 *discovery* Observation 时,那个实体以 `RESTRICT` 证据指针把该行按住。若那个实体自己的擦除是**按类型被拒**的——host `Scope`,或 `workspace`/`sandbox`/`authorization`/`external_origin` 类的 Scope,或一条 AgentRelease——那么这次擦除**永远不可能完成**。`_refuse_unsatisfiable_pins` 在取到锁之后、第一笔删除之前就以 `unsatisfiable_pin` 答复,并且它**读的是那几条拒绝自己用的同一组常量**,所以新增一条类型拒绝会自动被它跟上。
  2. **互相 pin。** 两个 `owner`/`thread` Scope 的 provenance 穿过同一个 Task:每一个单独看都是可擦除的,预检因此都过,但**谁都完不成**——各自都被对方按住,答 `blocked` 并点名那条边。
  3. **`blocked` 之后的复活窗口**(批终审 B8 补登,第三条形状)。`blocked` 是在 phase 5 的事务里抛的,所以 Scope 行作为恢复锚点留下(T10 F1 的设计,正确)——但 **phase 2 已经提交**:`ansich_tasks` 行、它的读模型与 assessor 作业都没了,而 Observation 与它们的投影作业还站着,两把锁随即释放。此时一次 `replay` 或 `rebuild_projections()` 会从幸存的 Observation 把 `ansich_tasks` 与读模型行**重新派生出来**——即一位 owner 要求擦除的数据,在「被 blocked」到「被恢复」之间被部分复活。**有界**:窗口由操作者自己的动作界定,恢复时又会从幸存的 `within_scope` 边重新走一遍。**为什么不是一行能修的**:phase 2 的提交是承重的(它解开 `ansich_content_occurrences` 的 `RESTRICT`,第二遍卫星扫描才走得动),幸存的 Scope 行按设计就是恢复句柄,两边都不能一挪了事。今天的诚实做法是「恢复那次擦除」,并且这段话写在 `_hard_delete_task` 的 docstring 上,免得下一个读代码的人以为 phase 2 的提交是随手写的。**上面三条候选修法里的 (3)(就地 tombstone 的擦除模式)同时也解掉这一条**:被 tombstone 抹掉的 payload 无法被重放派生回来。
- **v1 没有产品内补救,这一点必须写明**,否则运维会以为「再跑一次」或「先删另一个」能救。今天唯一的出路是操作者用带外手段直接移除那些外部行。
- 方向:三条,择一,`(3)` 最便宜:
  1. **多 Scope 擦除**——把一组 Scope 当作一个单位收下,`(2)` 随之消失,`(1)` 仍在。
  2. **provenance 转移**——把 `discovered_obs_id`/`created_obs_id` 重新指向一条幸存的 Observation。两条都解,但它改写证据指针,需要一次独立的语义裁决(那条指针的含义就是「这条证据发现了这个实体」)。
  3. **就地 tombstone 的擦除模式**——被 pin 的 Observation 不删行,而是把它的 payload 按 tombstone 抹掉。两条都解,而且**与既有的 tombstone 机器天然组合**(tier 1 已经在做同一件事),因此是本条推荐的一条。
- 归属:owner 擦除的下一个批次(v2),或任何一次因为合规请求撞上这两条形状的工作。

## F10-39. 保留策略下的无界增长残余(`inline_body` / blob 行 / tombstone 空壳)

- 状态:⚠️ 部分收窄(2026-08-22,P11-C 批 Task 10,`e764de4f`)。**不是修复,是把其中一条真漏收掉了。**
- 位置:`sql.py::_PAYLOAD_REFERRER_TIERS`(tier 1 的按表 aging 规则)、`_reclaim_orphaned_content_blobs` / `_apply_plan_and_reclaim`(T10 的收窄)。
- **T10 收窄了什么**:`ansich_content_blobs` 自己也是一个 payload 引用者,所以只要 blob 站着,它的正文就**不是**孤儿,tier 1 的回收正确地不碰它——于是一个删掉了最后一条指向该 blob 的 `ansich_content_blocks` 行、然后就停手的删除者,会把 blob **和**正文一起留下,而 tier 1 按设计拒绝过期孤儿,那些字节就永远躺着。三个删除者(tier 2、tier 3、owner 擦除)现在统一走 `_apply_plan_and_reclaim`:在计划落地**之前**读出 blob key,删掉不再被指向的 blob,并把它们的 payload id 折进同一次残余引用检查。**这条真漏是 tier 3 的**(以及新的擦除路径);**tier 2 从来没漏过**——它的计划根是 `ansich_observations`,而 `ansich_content_blocks` 不在那条 CASCADE 闭包里(它的 `producer_obs_id`/`payload_obs_id` 都是阻塞边),所以 tier 2 根本删不到 block。说成「修好了 tier 2 和 tier 3」是过度声称,已在 `backend/AGENTS.md` 与该任务报告里撤回。
- **仍然无界的是这三样**:
  1. **`inline_body` 字节**——阈值(`inline_payload_max_bytes`)以下的 blob 正文直接躺在 `ansich_content_blobs.inline_body` 里,**没有任何 tier 碰它**,而按条数算它是 blob 的**大多数**。tier 1 只对**外部化**的正文写 tombstone。
  2. **尚无 tier 触达的 blob 行**——blob 行只在它最后一条 `ansich_content_blocks` 被某个删除者带走时才被回收;没有哪一个 tier 以 blob 自身的年龄为条件删它。
  3. **tier 1 留下的 tombstone 空壳**——`ansich_payloads` 行本身留着(那正是 tombstone 的意义:让读者分得清 *按策略过期* 与 *丢失*),没有任何东西最终清掉它们。
- **登记时的措辞更正**:Task 9b 的原始表述是「blob 的正文被 blob 行保护住,而没有东西删 blob 行,所以去重后的正文会累积」。这句话点错了字节:tier 1 **确实**会给一条老 blob 的**外部化**正文写 tombstone(`ansich_content_blobs` 在 `_PAYLOAD_REFERRER_TIERS` 里是按 `created_at` aging 的声明成员)。真正无界的是上面那三样。
- 方向:一个**回收 tier**(第四层),以 blob 自身的 `created_at` 与「无人指向」为条件删 blob 行与 `inline_body`,并在 tombstone 超过某个远大于 `raw_payload_days` 的期限后清掉空壳。**不要**把它做成放宽 tier 1 的孤儿谓词——那条谓词的收紧(tier 1 拒绝一切孤儿)是 T9 用来关掉一次真实竞态的护栏,`backend/AGENTS.md` 的那一段专门写了「补救在删除者那一侧或一个回收 tier,**绝不**在谓词上」。
- 归属:Phase 12 的存储容量工作,或第一次有人在生产上量到 `ansich_content_blobs` 的体积。

## F10-40. tier 2 删掉活认领者的观测时,投影侧的外键失败**完全静默**

- 状态:⬜ 未修复。来源:P11-C 批 Task 9b 复审的端到端追踪(实现者自报了这条形状,复审把它追到底并确认「有界、不毒批、但零可见性」)。
- 位置:`sql.py::_run_observation_retention_tier`(tier 2 刻意没有在飞守卫)、`_record_projection_error`(`sql.py:7029` 起,`job = await session.get(...)` → `if job is None: return` 在 :7063-7065)。
- 现状:tier 2 **刻意**不为在飞的认领者让路——一个卡了一个月的作业不该把它的证据永远按住,这与 tier 1 把 `failed` 排除在 `_IN_FLIGHT_JOB_STATUSES` 之外是同一条道理。代价的一半是良性的(认领者的 settle 返回 `False`,走既有的 stale-completion 通道,`stale_completion_count` 会涨);**另一半不是**:如果那个认领者在自己的事务里已经写下了引用该 Observation 的行,PostgreSQL 会在语句处报外键失败,异常被 `project_pending` 的 blanket `except` 接住并路由到 `_record_projection_error`,而它的**第一个动作**就是 `session.get(AnsichProjectionJobRow, job_id)` 后 `if job is None: return`——作业行已经随它的 Observation 一起走了,于是这个处理器**静默返回**:不写 durable 错误行(写了反而会撞 `ansich_projection_errors.job_id` 的外键,变成第二次抛)、不重臂、不计数、不打日志。**批的其余部分活着**(`project_pending` 的 `for _ in range(limit)` 继续下一次认领),所以它有界、不毒批。
- **要不要接受这份沉默,是本条要裁决的问题。** 一边:被删的是**已过期的证据**,那次投影投的也是已过期的证据,没有任何策略没判过的**状态**因此丢失。另一边:本仓库有一条方向相反的先例没有被套用——`stale_completion_count` 存在,正是因为一次「本来就该丢」的写入丢失也被判定值得一个进程本地计数器;而本条比它**更罕见也更不可见**(settle-drop 那条路至少会让计数器涨,这条路什么都不涨)。
- **PG tier 没有覆盖这一支**:`test_observation_retention_deletes_a_claimed_job_beside_its_owner_on_postgres` 编排的是「B 认领 → A 清扫 → B 的 settle 返回 `False`」,即**友好**的那种交错——认领者从头到尾没有写过任何引用那条注定被删的 Observation 的行。真正要证的那一支只有散文,没有测试。
- 方向:(a) 在 `job is None` 的早退处加一行 DEBUG,或复用 `stale_completion_count`(最便宜,且不改变任何行为);(b) 补一条编排出来的 PG tier 用例(认领 → 投影一条 heartbeat → 清扫 → 断言投影方的事务失败且循环继续),或者在实现者那条 concern 旁边如实写一句「本支未被覆盖」。两者不冲突。与 `F10-36` 是同一类缺口(投影侧的丢失没有观测面),两条应当一起裁决。
- 归属:下一次触达 retention tier 2 或 `_record_projection_error` 的改动。

## F10-41. 时间 retention 的三层没有任何调用者

- 状态:⬜ 未修复。**这不是一个缺陷,是一段没接上电的能力**——P11-C 的 §6 把三层 retention、跨 pass 收敛、tombstone、horizon 与健康面全部落地并测到,然后没有把它接到任何会跑它的东西上。来源:P11-C 批 Task 14 的实施者顺带发现(「nothing calls `run_retention`」),批终审裁定按本文件自己的标准给它一个号——F10-38/39/40 都为更小的缺口拿了号,而这一条的后果比那三条都大。
- 位置:`packages/ansich/ansich/service.py::run_retention`(以及它转发到的 `sql.py::SqlAnsichBackend.run_retention`)。**生产侧调用者:零。** 今天所有调用点都在 `backend/tests/ansich/test_retention.py` 与 `backend/tests/integration/test_postgres_multiworker.py` 里。
- 现状,三句话:
  1. **产不出来**:tier 1 的 payload tombstone、tier 2 的 Observation 删除与 horizon 推进、tier 3 的结构解钉,一次都不会在生产上发生。于是 §6 为「读者的三种状态」写的那一整套(410 Gone、`expired_points`、按 `expired` 结算的认领、回执的 horizon 那一级)在生产上**全部是死代码**,尽管它们各自都被测到。
  2. **健康面如实但容易被读反**:`DatabaseHealth.retention_last_run` 会一直是 `None`,而 `None` 在一个可达的库上的含义是「从未跑过」——这是**正确**的答案,但一个运维看见它会以为是自己没配,而不是「产品还没接线」。
  3. **本条不含 owner 强删除**:`hard_delete_scope` 有自己的路由(`POST /api/ansich/retention/hard-delete`),它是可达的。不可达的只有**时间**那三层。
- 方向:接线,而不是改任何 §6 的代码。两条候选,建议前者:(a) 一个由 `scheduler` 驱动的周期性 pass(与 `config.yaml -> scheduler` 同一套开关),按 `RetentionPolicy` 从配置取三个 tier 年龄与 `cleanup_batch_size`,**并且必须循环**——`RetentionReport.finished` 回答的是「这一趟被上界停住了吗」而不是「库里空了」,跨 pass 收敛之下调用方无论如何都要再跑一趟(§6 的偏离 6 与 `backend/AGENTS.md` 的 `RetentionReport.finished` 段各写了一遍);(b) 一条 admin 路由,让运维手动触发一趟。无论哪条,接线的那一批都要顺带回答本文件里已经登记的两个相邻问题:`F10-39`(没有任何 tier 回收 `inline_body`/blob 行/tombstone 空壳,一旦真的开始跑,这条从「理论增长」变成「在增长」)与 `F10-40`(tier 2 撞上活认领者时那次完全静默的投影丢失,一旦真的开始跑就会真的发生)。
- **三处记录互相指向,不要只读一处**:本条、`ansich/docs/plans/11-resilience-replay-and-retention.md` §6 实现状态的偏离 6、以及 `ansich/docs/plans/README.md` 的 P11-C 条目「明确没有清零的残留」那一段。
- 归属:**下一个 retention 批次的第一件事**(接线先于任何新 tier;`F10-39` 要的回收 tier 排在它后面)。

## F10-42. P11-C 的遗留小项池(批终审 B7 的分池 1/2 收口)

- 状态:⬜ 未修复(**登记项**,不是缺陷)。来源:P11-C 批终审 B7——本批的残留纪律是「要么修、要么登记、要么点名」,绝大多数小项都做到了,只有三个子池没有被路由到任何比 SDD 目录更耐久的地方;SDD 目录一归档它们就没了。批终审修复波把其中能一行修掉的都修了,剩下的按本条登记,**逐条带方向与归属**。
- **修复波里就地修掉的(不在本条名下,列出以免有人再去找)**:T9b F2(`resumed_from_cursor` 看不见 tier 2 中途恢复,= 批终审 B6)、T11 R3(两条恢复的 `ORDER BY` 无钉子,= B7/R3)、T14 F1(`Metric` 的 tone 只到 Tailwind class ⇒ 加 `data-tone` 属性并改断言)、T10 N7(`parent_scope` 拒绝没点名子 Scope,= B11)、T10 的 `sorted()` 对可空 4 元组(= B10)、B9(过期结算可达性的 docstring 更正)。T9b F10(「未完成」被渲染成「未知」)由 T14 结清;T12 的三条措辞项与 W3 由 T15 的 `262862a7` 结清(本波复核过:no-store 的范围限定、中间件不写日志那句、`raw_read_max_bytes` 的「近似上界/度量在内层文档」描述、`get_args(OperatorAuditActionType)` 的写入值断言都在)。
- **分池 1:T9b 复审的七条**(原文在 `task-9b-review.md`,ledger:103):
  1. **F1** — 一条 `>= 0` 的空断言;以及**没有**一条 Belief 读路径的用例跑在「证据已被清空」的库上。方向:把空断言换成有判别力的等式,并补一条「tier 2 清空之后 Belief 读路径仍然自洽」的用例。归属:下一次触达 Belief 读路径或 retention 用例的改动。
  2. **F6** — auth snapshot 的回收**没有测试**。方向:补一条「删掉最后一条引用 `ansich_authorization_snapshots` 的行之后,它的 payload 行也走了」的用例。**与批终审 B1 相邻**:那正是 `--replace` 的第三条成员条件点名的同一张表(`task-safety` 拥有它),所以这条一旦补上,也是把那条允许清单往前推的一半功课。归属:下一次触达 `_apply_plan_and_reclaim` 或 `task-safety` 可重放性证明的改动。
  3. **F7** — `_plan_cascade` 把「卡在哪」的原因丢掉了:horizon 停住这件事在健康面上看得见,**为什么**停住看不见。方向:让规划器把阻塞边带回来(`hard_delete_scope` 已经有这条通道,tier 2/3 没有),至少进日志。归属:下一次触达 retention tier 2/3 的改动。
  4. **F8** — 认领者竞态的**响亮那一半**没有被记录:并发的 `RESTRICT` 插入会从 `run_retention` 里抛出来(有界,cursor 是持久的),但没有任何一处文档说过它。方向:一句话写在 `run_retention` 的 docstring 上。归属:同上。
  5. **F9** — `max_batches=0` 的不对称:`None` 是「不设界」,`0` 却是「一层都不跑」,两者从签名上分不出来。方向:要么拒绝 `0`,要么在 docstring 上写死它的含义。归属:接线批次(它是第一个真的会传这个参数的调用者)。
  6. **F11** — 没有路由级的连线用例(健康面上的 retention 块只在服务层被测过)。方向:一条走 `GET /api/ansich/health` 的用例。归属:下一次触达该路由的改动。
- **分池 2:T6 复审的 N1–N4**(ledger:86):
  1. **N1** — 守卫在重抛「与 resolver 无关的 `ValueError`」之前先打了 warning;更诚实的位置是**回退成功之后**再打。
  2. **N2** — F8 的路由改动没有测试(参数默认就是那个常量,所以回退不会被发现),而且 `get_active_resolver` 的 fail-open 分支零覆盖。
  3. **N3** — 守卫触发时,比较结果上盖的是一个**什么都没选中**的 resolver 的戳(「in force」说得过于慷慨)。
  4. **N4** — 「同一个 30s 窗口里两个 worker 的戳可以不同,但结论永远相同」这条事实没有写进过时性那两段。
  归属:下一次触达 active-version / resolver 选择的改动(四条都在同一处代码里,建议一并做)。
- **§7 审计行需要自己的下界吗**(批终审 B3 的那一半)。行为本身是刻意的、已写在三处(spec §7 边界 6、`backend/AGENTS.md` 的 §7 段、`AnsichRetentionConfig` 的 docstring):审计行是普通 Observation,按 `observation_days` 过期,所以那个 knob 同时就是访问审计的保留期,默认 30 天。**登记的是这个问题本身**:合规要求更长时,是加一个 `audit_days`(第四个 tier 年龄,tier 2 加一条 `kind` 谓词),还是把审计行搬到一张不被 retention 走的表上。方向:前者更便宜且与现有三层同构;后者才真正把「审计」与「数据」分家,但要重新回答「读一位 owner 数据的审计是否也是那位 owner 的数据」。归属:**接线批次**(`F10-41`)——那是 retention 第一次真的会在生产上删东西的时刻,在那之前这个窗口一天都没有关过。
- 归属:本条是一个池子,不是一件事;每一条自己的归属写在它那一行上。整体的 owner 是**下一个触达 Ansich 的批次**,它至少要把这份清单读一遍再决定哪些跟着自己的改动一起结掉。
