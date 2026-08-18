# Phase 10 — 评估输入与语义 Belief

## 实现状态（2026-08-18）

已形成可运行的本地纵向切片：`evaluation.recorded` v1 契约由唯一的 core validator 把关（verdict/score 至少其一、score 必带 `{min,max,higher_is_better}`、`hard` fidelity 只对带 suite/suite_version/case_id 的 benchmark/unit test 开放、`earliest_erroneous_step` 必须以 Task 为 subject 并在 `actual` 指名该 Task 的 Step）；Belief resolver 升级为 `ansich-default@2.0.0`，在 `configured_rule` 与 `automated` 之间插入 `soft_human`，v1 逐字保留并可按版本重放。`evaluation-projector@1` 写入 `ansich_evaluation_index` 行、五个具名维度的 `quality.<dimension>` assertion 与 `ansich_release_quality_stats` 聚合格；缺 subject Entity 或缺 Step 是可自愈的依赖等待，Step 不属于该 Task 是硬失败。服务层的 `record_evaluation` 返回 `pending|applied|failed` 回执而不阻塞投影，`get_quality_beliefs` 永远返回五个维度并把无人断言的维度合成为 `unassessed`。Gateway 端点、compare 的 quality 区块与 cohort 参数、dismiss 的 `semantic_override`、feedback→evaluation 的 fail-open 桥接，以及 Task 详情第五个入口 `?view=evaluations` 和 release 比较的 Quality 卡片均已落地。

本地验收覆盖 SQLite 迁移/重放、后端 Ansich 回归（430 项）以及前端 lint/typecheck 与单元测试（804 项）。真实 PostgreSQL 升级矩阵、关闭 Ansich 的性能基准和生产 paper drill 仍是最终生产就绪门禁。

### 落地位置

- 契约与核心校验：`backend/packages/ansich/ansich/evaluation.py`（`EvaluationRecord`、`build_evaluation_observation`、`benchmark_source_event_id`、`unassessed_quality_belief`）；envelope 侧的 kind/subject 一致性校验在 `backend/packages/ansich/ansich/contracts.py`。
- Resolver：`backend/packages/ansich/ansich/belief/resolver.py`；`soft_human` authority class 在 `backend/packages/ansich/ansich/assessment/base.py`。
- 存储与投影：migration `backend/packages/harness/deerflow/persistence/migrations/versions/0023_ansich_evaluations.py`；ORM 行在 `backend/packages/harness/deerflow/ansich/persistence/models.py`；`evaluation-projector@1` 与 `list_evaluations`/`list_quality_beliefs`/`get_release_quality` 在 `backend/packages/harness/deerflow/ansich/persistence/sql.py`。
- 服务面与纯规则：`backend/packages/ansich/ansich/service.py`、`backend/packages/ansich/ansich/quality.py`（`compare_release_quality` 独占 cohort 可比性判断，避免规则在 HTTP 层与 UI 之间漂移）。
- HTTP 与适配器：`backend/app/gateway/routers/ansich.py`、配置快照 `backend/app/gateway/deps.py`、feedback 桥接 `backend/app/gateway/feedback_evaluation.py`。
- 配置：`ansich.evaluation_min_cohort_samples`（5）与 `ansich.evaluation_max_payload_bytes`（262144），见 `backend/packages/harness/deerflow/config/ansich_config.py` 与 `config.example.yaml`。
- 前端：`frontend/src/components/workspace/ansich/evaluations-panel.tsx`、`release-quality-section.tsx`、`agent-release-panel.tsx`；类型、hooks 与纯展示函数在 `frontend/src/core/ansich/`。
- 测试：`backend/tests/ansich/test_evaluation_contracts.py`、`test_belief_resolver.py`、`test_sql_evaluations.py`、`test_evaluation_service.py`、`test_ansich_evaluations_router.py`、`backend/tests/test_feedback_evaluation_adapter.py`；前端 `frontend/tests/unit/core/ansich/*` 与 `frontend/tests/e2e/ansich.spec.ts`。

### 与本计划的偏离

1. §6 要求的 `(release_id, cohort_key, dimension)` 索引没有单独建：这三列正是 `ansich_release_quality_stats` 的复合主键，主键唯一索引已经是该表唯一的访问路径，再建一条同构索引只剩写放大。
2. `ansich_release_quality_stats` 增加了 §6 未列出的 `scale_higher_is_better` 列：§7 的“相同 score scale”本身包含极性，只保留 `min/max` 会让两个含义相反的量表被当作同一个 scale 比较。
3. §5 的 `semantic_override` 只对 subject 解析为 Task 的告警生效。以 ToolCall 为 subject 的 scope-safety 告警会以 `alert_subject_is_not_a_task` 标记降级，而不是把 Task 级 quality Belief 挂到 ToolCall id 上；“用人工判断覆盖 hard safety 证据”是另一件事，留待后续阶段。
4. benchmark 的重放身份是 §3 的 suite 元组 `(suite, suite_version, case_id, run_id, dimension)`，刻意忽略 API 的 `Idempotency-Key`：同一条 benchmark case 无论由谁重新导入都应落到同一条 Observation。
5. 相对 §8 列出的四条端点，额外增加了 `GET /evaluations/{obs_id}/payload`。`expected`/`actual`/`rationale` 是正文，只有让它们走独立的 `no-store` 审计路由，§8 要求的“lazy payload”才是真的按需，而不是把正文塞进列表响应。
6. `ansich_evaluation_index` 的列比 §6 列出的多：`task_id`、`scale_higher_is_better`、`authority_class`、`fidelity_class`、`cohort_key`、`projector_version`，并多一条 `(task_id, occurred_at)` 索引。前四项分别支撑 Task 维度的列表读取、量表极性、R2 authority 阶梯与 payload 来源的 fidelity；索引服务于 `GET /tasks/{id}/evaluations`。
7. §5 提到“Current Belief 按 dimension + cohort key 分开”，实现的 Current Belief 仍只按 `quality.<dimension>` 一个 field 存放：cohort 保存在 assertion value 与 release 聚合格里，跨 suite 的分歧作为被保留的冲突 assertion 参与 resolver 选择并计入 `conflicting_assertion_count`，而不是拆成并行的 Current Belief。真正需要按 cohort 并列展示当前判断时，需要一次显式的 field 命名扩展与迁移。
8. release 聚合格的**成员**按 cohort 过滤，但**取值**取的是 Task 的全局 current Belief——这是偏离 7（R3 的 belief 键不含 cohort）的直接后果。`_recompute_release_quality_stats` 只把在 `(cohort, dimension)` 上有 index 行的 Task 纳入这个格，取样时却读 `session.get(AnsichCurrentBeliefRow, (task_id, field_name))`（`sql.py:7951`），即与 cohort 无关的那一条：同一个 Task 先被 suite A 判 fail、又被 suite B 以更晚的 `as_of` 判 pass 时，A 的格聚合到的是 B 选出的 pass——一个 suite A 从未断言过的判断。§6 说统计聚合的是“Task 在一个明确 cohort 中的 selected/current evaluation”，v1 实现为“population 按 cohort 过滤 + 取值取全局 selected”。per-cohort 取值（按 assertion value 里的 `cohort_key` 过滤选中的 assertion，或改为 per-cohort belief）登记为 [phase-10-review-followups.md](phase-10-review-followups.md) 的 F10-4，归属 Phase 11。

### 已知限制

- release 聚合格只在“evaluation 落在该 Task 的 `executed_by` 绑定之后”时把这个 Task 计入。绑定晚到会让格暂时保持旧值，直到同一 cohort/dimension 的下一条 evaluation 触发重算；该行为对重放是一致的。
- 聚合格的 `as_of` 会随格内最新一条 evaluation 前移，即使这条 evaluation 没有改变任何被选中的 Belief。
- 聚合格是“按 cohort 圈定成员、按全局 selected Belief 取值”（见偏离 8）：一个 Task 被多个 suite 分歧评估时，每个 cohort 的格拿到的都是同一个全局选中的判断，而不是该 cohort 自己的判断。因此 v1 的 cohort 只保证“比较的是同一批 Task”，不保证“比较的是这批 Task 在该 cohort 下的判断”。
- 前端 Recorded evaluations 列表只显示最新 100 条（服务层默认 `limit=100`）且没有截断提示，登记为 UI-2 跟进项。
- Task 详情 Agent release 头部的质量徽标仍是硬编码的 `unassessed`：后端 `AgentReleaseSummaryView.quality_status` 目前是 `Literal["unassessed"]`，真正的 release 级聚合出现前不改动该徽标。

## 1. 交付目标

本阶段允许外部评估进入 Ansich，并把“运行完成”和“语义正确”彻底分开。开发者可以记录 expected-versus-actual、人工标注、benchmark/unit test 或 LLM judge 结果；resolver 据此产生带证据的 quality/behavior Current Belief。

单次 evaluation 是 Observation，不创建 Evaluation Entity。只有未来出现多步骤、可分派、可关闭的 review workflow 时才提升为 Entity。本阶段不实现普通用户进度视图，也不把 thumbs-up/down 自动解释成完整任务正确性。

## 2. Evaluation Observation schema

新增 `evaluation.recorded` v1：

```text
subject_ref:
  type: task | step | tool_call | content_block | agent_release
  id: Ansich ID
evaluation_kind:
  user_feedback | developer_annotation | benchmark_assertion |
  unit_test | llm_judge
dimension:
  correctness | completeness | relevance | safety | efficiency |
  earliest_erroneous_step | custom
verdict_or_score:
  verdict?             // pass | fail | partial | unknown
  score?               // number
  scale?               // {min,max,higher_is_better}
expected?: inline/ref
actual?: inline/ref
rationale?: inline/ref
assessor:
  name
  version?
fidelity_class: hard | rule | soft
occurred_at
```

`expected`、`actual`、`rationale` 经过同一 secret filter 并可写 payload ref。benchmark/unit test 只有在输入带 stable suite/case/version 和可验证 oracle 时才允许 fidelity=`hard`；普通人类标注通常为 soft 或显式 human 优先级，不能仅因来自 admin 自动改为 hard。

score 必须带 scale，projector 拒绝无法比较的裸数字。`earliest_erroneous_step` 必须 subject 为 Task 且 actual 引用属于该 Task 的 Step；不能通过内容相似度自动猜 Step。

## 3. 输入适配器

建立三条入口：

1. Gateway admin API `POST /api/ansich/evaluations`，用于 developer annotation、benchmark/unit test 导入和显式 LLM judge 结果。
2. 现有 `feedback` router/repository 的适配器。在 feedback 成功写入原系统后，best-effort 发 evaluation Observation；映射不充分时只保留 `dimension=relevance/custom` 和原始 rating，不推断 correctness。
3. 内部测试/benchmark adapter，接受 stable idempotency key `(suite, suite_version, case_id, run_id, dimension)`。

这些入口都调用独立 core validator，不在路由中拼 Observation。现有 feedback 写成功而 Ansich 失败时，原 API 仍成功并在 Ansich health 记录 loss；反向不允许 Ansich 记录成功掩盖 feedback 主写失败。

本阶段只接收外部 LLM judge 结果，不自动启动 judge 模型调用。未来自动 judge 必须作为 system operation 采集自身 prompt/release 和成本，不能隐藏在 projector 中。

## 4. Semantic assertion mapping

新增 `evaluation-projector@1`：

- correctness fail/pass → subject `quality.correctness` assertion；
- safety fail/pass → `quality.safety`；
- completeness/relevance 保持各维度，不折叠成一个总分；
- explicit earliest erroneous Step → Task attribution assertion 并关联 Step；
- benchmark/unit hard evaluation 可产生 deterministic hard semantic evidence；
- developer/user/LLM judge 按配置映射 human/soft，保留 assessor identity。

Task `behavior` 与 `quality` 不同。一次 correctness fail 可以支持 `quality.correctness=failed`，但不自动支持 runaway/drifting；runaway 仍来自 Phase 6 行为规则。相反，一个高频或 runaway Task 也可能得到 correct 结果，两个 Belief 同时存在。

所有未评估维度返回完整 Belief 结构且 `value="unassessed"`、`source={name:"none",version:"1"}`、无伪造 evidence。没有评估不能从 Task completed 推断 pass。

## 5. Resolver conflict rules

扩展 `ansich-default@1` 前需确认是否升级为 v2；若 precedence 语义新增，创建 `ansich-default@2` 并保留 v1 replay 结果。建议 quality precedence：

```text
explicit human override
> deterministic benchmark/unit oracle
> configured rule evaluator
> soft human annotation / user feedback
> LLM judge
```

同一 class 内优先最新 `as_of`；不同 benchmark suite 不互相覆盖时，Current Belief 按 dimension + cohort key 分开。冲突的 pass/fail assertions 全部保留，API 返回 selected assertion 和 `conflicting_assertion_count`。

human dismissal Alert 只在 dismiss payload 明确 `semantic_override` 时产生 human assertion；普通 ack/dismiss 不改变 quality。

## 6. 数据库增量与查询投影

Observation/Payload 已经能保存 evaluation；新增 typed query projection：

- `ansich_evaluation_index(evaluation_obs_id, subject_type, subject_id, evaluation_kind, dimension, verdict, score, scale_min, scale_max, assessor_name, assessor_version, suite_id, suite_version, case_id, occurred_at)`。
- `ansich_release_quality_stats(release_id, cohort_key, dimension, assessed_count, pass_count, fail_count, partial_count, score_sum, score_count, as_of, projector_version)`。

`evaluation_index` 不是 canonical record，可删除重放。release stats 只汇总 Task 在一个明确 cohort 中的 selected/current evaluation；没有 cohort key 时允许显示样本列表，不做跨 release“提升”比较。

新增索引 `(subject_type, subject_id, dimension, occurred_at)`、`(suite_id, suite_version, case_id)`、`(release_id, cohort_key, dimension)`。Idempotency 由 producer/source_event unique 和 stable benchmark source event ID 保证。

## 7. Cohort 可比性

release comparison 只在以下条件都满足时提供质量差异：

- 相同 suite/version、case set 或显式 cohort key；
- 相同 dimension 和 score scale；
- 两边都达到配置的最小样本数；
- 没有未解释的 missing evaluation/lost range。

返回 sample count、coverage、selected resolver version 和置信限制。v1 不做统计显著性结论；只报告 observed delta。条件不满足时返回 `comparison_status="not_comparable"` 及 reason，而不是用所有生产 Task 平均分强行比较。

Operational distributions（tokens/Steps/latency）仍可独立比较，但 UI 必须和 semantic quality 分区。

## 8. API 与 UI

新增：

```text
POST /api/ansich/evaluations
GET /api/ansich/tasks/{task_id}/evaluations
GET /api/ansich/steps/{step_id}/evaluations
GET /api/ansich/agent-releases/{release_id}/quality?cohort=
```

POST 要求 admin、idempotency key 和 subject ownership/existence 校验；unknown subject 为 404，payload 过大为 413。API 响应返回 observation ID 和 `projection_status=pending|applied|failed`，不等待所有 projector 无限完成。

Task detail增加 Evaluations 标签，按 dimension 显示 Current Belief、selected evidence、conflicts 和 expected/actual lazy payload。Release compare 增加 Quality 区域：unassessed、not comparable 和 observed delta 分别展示，不能用同一绿色/红色图标混淆。

## 9. TDD 测试矩阵

- schema：verdict/score/scale、expected/actual refs、非法 fidelity、subject 关系、payload 限制。
- adapters：feedback 成功/失败、Ansich fail-open、benchmark idempotency、普通 rating 不推 correctness。
- projection：pass/fail/partial、多个 dimension、earliest Step ownership、乱序/重复 evaluation。
- resolver：benchmark vs LLM judge、人类 explicit override、同级 as_of、conflicts、unassessed。
- cohort：相同 suite 可比、版本不同、case coverage 不足、scale 不同、样本不足、lost range。
- security：admin、subject 存在、secret redaction、raw rationale lazy/audited。
- API/UI：pending projection、conflict count、unassessed/not comparable、expected/actual 展开。
- replay：resolver/projector version 变化后结果可并存并可重建。

## 10. 完成条件

- completed Task 在无 evaluation 时仍为 unassessed。
- 每条 semantic Current Belief 可追到 evaluation Observation、assessor 和 resolver version。
- correctness、safety、relevance、efficiency 等维度不被粗暴压成单一 success。
- release 质量比较只在 cohort 可比时给 observed delta，否则明确拒绝比较。
- 本阶段不偷偷执行 LLM judge，也不实现普通用户进度推断。
