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
| F10-7 | 缺 per-observation 持久化信号,存在「observation 丢失但回执永远 pending」的窗口 | ⬜ 未修复 | — | — |
| F10-8 | `contracts.py` 的 scope/authorization/effect 三个 `_validate_subject` 分支缺 payload-None 守卫(既存缺陷) | ✅ 已修复 | 2026-08-18 | 本次变更待提交 |
| F10-9 | 同一组常量六处复制(suite-bound kinds ×3、五维度集合 ×3) | ⬜ 未修复 | — | — |
| F10-10 | settle 时序 flaky 未隔离:在负载下轮换命中无关测试 | ⬜ 未修复 | — | — |
| F10-11 | pass-rate 兜底未标注量表极性 | ⬜ 未修复 | — | — |
| F10-12 | feedback 桥接在请求路径上 await 一次无上界的 DB 读 | ⬜ 未修复 | — | — |
| F10-13 | `/acknowledge` 静默忽略 `semantic_override` | ⬜ 未修复 | — | — |
| F10-14 | 迁移 `0023` 的 upgrade 有守卫、downgrade 没有 | ⬜ 未修复 | — | — |
| F10-15 | `formatEvaluationVerdict` 忽略 `scaleMin` | ⬜ 未修复 | — | — |
| F10-16 | Recorded evaluations 列表静默截断在 100 条,无截断提示 | ⬜ 未修复 | — | — |
| F10-17 | Agent release 头部质量徽标是硬编码字面量,后端聚合落地后会开始说谎 | ⬜ 未修复 | — | — |
| F10-18 | 杂项(装修性/覆盖率补齐,详见该节逐条) | ⬜ 未修复 | — | — |

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

- 状态:⬜ 未修复。
- 位置:`record_evaluation` 的回执路径(`backend/packages/ansich/ansich/service.py`)与其下的批量写入器。
- 现状:Task 5 的 `FlushResult` 分支已经把"拒绝入库"和"flush 未持久化"从 `pending` 里摘出去了,但残留一个既存窗口:后台写入器取走了这条 observation,它所在的批次撞上 `storage_failure`,之后的 `flush_task` 因为没有可选的项而报 `persisted=True`——回执于是停在 `pending`,而这条 observation 其实已经丢了。轮询这个回执的调用方永远等不到终态。
- 方向:引入 per-observation 的持久化信号(每条 observation 自己的持久化结果,而不是只看批次/flush 层面的聚合),让回执能把"丢失"和"仍在排队"区分开。
- 归属:Phase 11(与 F10-6 同属韧性主题)。

## F10-8. 三个 `_validate_subject` 分支缺 payload-None 守卫

- 状态:✅ 已修复(2026-08-18,本次变更待提交)。把 `evaluation.recorded` 分支的守卫模式原样复制到 `scope.snapshotted`/`authorization.*`/`effect.*` 三个分支:subject_type 检查保持无条件,只有 payload 交叉校验挪进 `if self.payload is not None:`,payload 在手时的校验强度一字未改(`test_safety_contracts.py` 里 kind/decision、kind/phase 两条冲突拒绝用例未改动仍绿)。回归钉子:`backend/tests/ansich/test_sql_safety.py::test_externalized_scope_authorization_and_effect_payloads_read_back`——服务按 `inline_payload_max_bytes=16` 构造,让每条 payload 都走 externalize,记录 scope/authorization/effect 三条 observation 并 flush,先断言这三行在库里确实是 `payload_json IS NULL AND payload_ref_id IS NOT NULL`,再经 `service.list_timeline()` 与 `service.list_observations()` 两个公共读读回。RED 证据:读路径不是降级成空/degraded,而是直接抛 `ValidationError: Input should be a valid dictionary or instance of ScopeDescriptor [input_value=None]`(`sql.py:5574` 的 `_observation_from_row`);逐个分支补守卫时报错依次换成 `AuthorizationSnapshot`、`ToolEffect`,三个分支各自都被这一条用例钉住。附带确认:`_claim_projection_job` 同样先 `_observation_from_row` 再 hydrate payload,所以修复前这三种 kind 的 externalized observation 连投影都认领不了,job 永远 pending、`flush_task` 只能等到 `projection_settle_timeout`——"能写进去、再也读不出来"比诊断记录的还要广一层。
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

- 状态:⬜ 未修复。
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

## 评审中确认无需跟进的点(留档)

- **"完成 ≠ 正确"在每个边界上都真的被代码执行**:`get_quality_beliefs` 永远吐五个维度并把缺席维度合成为 `unassessed`(`source={"name":"none","version":"1"}`、authority/fidelity 均为 `unknown`、证据为空);TS 类型把 `unassessed` 作为一等字段;`qualityBeliefTone` 先看这个标志再看值;`TONE_STYLES` 把 `unassessed` 与 `unknown` 映射到同一套 muted 处理;e2e 断言已解析的 `fail` 与中性的 `Unassessed` 携带不同的 class。
- **fail-open 是被执行的纪律**:feedback 桥接严格排在主写之后、丢弃回执、吞掉一切,`test_a_failed_feedback_write_never_invokes_the_bridge` 钉住了禁止方向;dismiss 的 override 降级而不回撤;`_UnavailableBackend` 无需新增 stub(R7 被遵守,Protocol 与 InMemory backend 未被触碰)。
- **重放可复现性是真的且有测试**:`test_rebuild_reproduces_index_rows_stats_and_current_beliefs` 对 index 行、Belief 与统计格做快照并断言整轮 rebuild 前后相等,其中包含一次人工 override 压过 benchmark 的情形。
- **R1–R11 全部裁定被合并后的代码遵守**:被丢弃的冗余索引、端到端的量表极性、复数 query key、delta 方向文案——逐条核对无遗漏。
- **文档同步是本仓库见过最完整的一次**:concepts.md §8(含 §9 重编号与悬挂交叉引用修复)、backend/AGENTS.md 的路由行 + 约 80 行小节 + `0023` 条目、frontend/AGENTS.md 的面板/卡片规则、plans/README 的 Phase 10 段落、阶段文档的七条偏离与四条已知限制。

## 计划作者层面的系统性教训(留档)

本阶段五个 Important 级的**计划**缺陷共享同一个形状:计划规定了结构,却没有规定这些结构必须保持的不变量。对每一个读模型、每一个对外发布的数字,计划都应当写出它的不变量、在哪里被执行、在哪里被测试,而不是只列出列。文档任务的文件清单应当从上一阶段的 docs commit 推导,而不是凭记忆罗列(Task 11 的文件清单漏掉 `phase-N-review-followups.md` 这个惯例,正是 F10-1–F10-3 之外还要额外补一份本文件的原因)。
