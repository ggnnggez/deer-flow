# Phase 10 — 评估输入与语义 Belief

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
