# Ansich 语义轨迹(Semantic Trajectory)设计文档

状态:草案(可行性评估 + 方案骨架),2026-07-23 首次登记。
前置阅读:[concepts.md](concepts.md)(概念导览)、[ansich-design-document.md](ansich-design-document.md)(核心协议)、[plans/10-evaluation-and-semantic-beliefs.md](plans/10-evaluation-and-semantic-beliefs.md)(Phase 10 评估输入)。

## 1. 目标与定义

语义轨迹是指:给 Agent 执行序列中的每个逻辑 Step 赋予**执行语义角色**(例如 计划 plan / 行动 act / 验证 verify / 展示 present / 纠错 recover 等),使一次 Task 的执行过程可以从"有序的 Step 事实序列"升维为"可理解的语义序列",支撑:

- 运营者快速理解一个 Task "在做什么阶段的事";
- 跨 Task / 跨 AgentRelease 的行为模式比较(例如某 release 验证步骤占比骤降);
- 与 Phase 10 语义 Belief 联动的归因(例如 earliest erroneous step 落在哪类语义角色上)。

标注来源分两层:**结构启发式**(确定性规则,零成本)与 **LLM enrichment**(模型分类,高保真)。两层共存,靠 resolver precedence 裁决,不互相覆盖历史。

明确的非目标(v1):

- 不做普通用户可见的进度视图(与 Phase 10 §1 的边界一致);
- 不把语义角色当成质量判断——"这一步在验证"不等于"验证通过";
- 不在采集路径上做任何同步 LLM 调用。

## 2. 可行性结论

Ansich 现有核心概念**具备搭建语义轨迹的基础**,四个必需基础件均有现成落点,核心模型不需要改动:

| 语义轨迹需要什么 | Ansich 现有落点 | 状态 |
| ---------------- | --------------- | ---- |
| 有序的标注单元 | Step:`step_seq` 在 Task 内严格递增;`result`(`acting`/`final_answer`)与 `issued_tools` 已是最粗粒度结构语义 | ✅ 现成 |
| 标签载体(可版本化、可重放、可并存冲突) | Belief/Assertion:`subject_id + field_name + value + assessor name/version + config hash + evidence + as_of`,`unknown/unassessed` 一等值,resolver 按 precedence 选取并保留冲突 | ✅ 现成,无需改 schema |
| 分类器的输入证据 | ContextSnapshot(精确有序模型输入)、ToolCall intent/raw/visible 分层、ContentBlock 谱系 | ✅ 现成 |
| enrichment LLM 调用的自身可观测性 | system operation(`actor_kind=system_operation`),title/summarization/memory 已在用;Phase 10 已确立"自动 judge 必须作为 system operation 采集自身 prompt/release 和成本"原则 | ✅ 机制现成,组件待建 |

一条 `step.semantic_role = "verify"` 断言,带 `fidelity_class` 与 assessor 身份,今天的 `Assessment` 契约(`backend/packages/ansich/ansich/assessment/base.py`)就能表达。分类法(taxonomy)换版本时,assessor version + config hash 天然支持新旧标注并存重放——这是语义标注类系统最难自建的部分,Ansich 已经免费提供。

## 3. 缺口清单

### G1. 标注型 Observation kind(小)

Phase 10 的 `evaluation.recorded` 是 verdict/score 形状(pass/fail、score+scale),表达的是**质量裁决**;语义角色是**分类标注**,硬塞进 `dimension=custom` 会丢失 taxonomy 版本语义。需要新增:

```text
annotation.recorded v1:
  subject_ref:
    type: step            # v1 只支持 step;task/tool_call 留待需要时扩展
    id: Ansich step ID
  taxonomy:
    name                  # 例如 "execution-role"
    version               # taxonomy 自身版本,独立于 assessor version
  label                   # taxonomy 内的枚举值
  confidence?             # [0,1]
  rationale?: inline/ref  # 经 secret filter,可写 payload ref
  assessor:
    name
    version?
  fidelity_class: rule | soft
  occurred_at
```

约束沿用既有合并规则:schema version、幂等 source event ID(建议 `(task_id, step_id, taxonomy, taxonomy_version, assessor)` 派生)、payload 分层、至少一个重复/乱序测试。Observation 的 kind→subject 校验(`contracts.py::_validate_subject`)逐 kind 注册,新增一个分支即可。

### G2. 主动 enrichment 执行器(大,唯一真正的新组件)

架构上的关键约束:**projector/assessor 必须确定性、可重放;LLM 分类是非确定性的,因此 enrichment 不能做成 projector/assessor**(与 Phase 10 §3 "不能隐藏在 projector 中"同一原则)。它必须是 **producer 侧**的新组件:

```text
Step 关闭(事实)──► enrichment worker(新)
                       │ 以 system operation 身份调用分类模型
                       │ 采集自身 prompt/release/usage(现有 system operation 探针)
                       ▼
              annotation.recorded Observation
                       │ 普通投影/评估管线(确定性,可重放)
                       ▼
              step.semantic_role Belief
```

这是 Ansich 内部第一个"消费自己的数据、再产生新 Observation 的 LLM worker",需要独立设计的点:

- **触发时机**:Step 关闭即标(低延迟、成本按 Step 线性)vs Task 终态批标(一次调用标全轨迹,上下文更全、成本更低)。倾向后者作为 v1 默认,前者作为可选配置。
- **成本与预算**:enrichment 是 system operation,其 usage 自动进入采集;但需要独立开关与预算上限(`config.yaml -> ansich.enrichment.*`),默认关闭。
- **失败语义**:fail-open——enrichment 失败绝不影响 DeerFlow 运行,也不阻塞既有投影;失败进入既有 job/error 诊断面。
- **幂等**:同一 `(step, taxonomy_version, assessor_version)` 重跑产生相同 source event ID,重复写入被幂等吸收;升级 assessor/taxonomy version 产生新标注,与旧标注并存。

### G3. 轨迹级结构与读模型(中)

逐 Step 标签是平的。轨迹的两级增量:

1. **轨迹读模型(薄,v1 范围)**:有序 Step + 各自 current `semantic_role` Belief 的查询投影,例如 `ansich_step_semantics_index(task_id, step_id, step_seq, taxonomy, taxonomy_version, label, fidelity, assessor_name, as_of, projector_version)`,可删除重放。API 形如 `GET /api/ansich/tasks/{task_id}/trajectory`。
2. **语义弧线(v2,暂不实现)**:"plan 支配第 5–9 步""verify 验证第 3 步"等 Step 间关系,用既有 Relation 机制(有证据的有向边,如 `fulfills`/`verifies`)表达。边的语义与证据标准需要单独设计,v1 不做。

UI 归属:轨迹视图应并入 human-followups U1(Context Lineage UI 重构,Phase 10 后)的渐进式披露信息架构,不另起一套可视化心智。

### G4. enricher 的原文读取路径(小,但有时机约束)

分类器要读 Step 的实际内容(模型输入/输出、工具结果预览),而 raw payload 读取是强审计边界。Phase 11 才落地 raw read 强审计与 payload 独立 retention;在此之前给内部组件开原文读取路径,同一条路要修两遍(与 human-followups U2 被推迟到 Phase 11 的理由完全相同)。因此 enrichment worker 的数据读取接口必须复用 Phase 11 定义的内部审计读取通道,不得绕过。

## 4. 分层方案与 resolver

### 第一层:结构启发式(现在即可做,零 LLM 成本)

确定性规则 assessor `step-role-heuristic@1`(fidelity=`rule`),完全走现有 assessor 基础设施:

```text
result = final_answer                          → present
issued_tools 含 write_todos                    → plan
issued_tools 含 write/bash/外部写类 effect      → act
issued_tools 仅 read 类且紧跟 act 之后          → verify(低置信)
其余                                           → unassessed(不猜)
```

规则覆盖不了的一律 `unassessed`,不允许"默认 act"这类冒充。

### 第二层:LLM enrichment(G2 组件,Phase 10/11 后)

enrichment worker 产出 `annotation.recorded`(fidelity=`soft`),经 G1 投影映射为 `step.semantic_role` assertion。

### Resolver precedence

沿用 Phase 10 §5 的升级流程:若 precedence 语义新增,创建 `ansich-default@2` 并保留 v1 重放结果。语义角色维度的建议 precedence 与质量维度**相反**:

```text
explicit human override
> LLM enrichment(高置信分类)
> rule heuristic
```

质量维度里 LLM judge 排最低是因为它裁决"对不对"不可靠;语义角色是"在做什么"的描述性分类,LLM 显著优于结构规则。这正是 Phase 10 预留的"是否升级 default resolver 版本"决策的第一个真实用例。冲突的标注全部保留,API 返回 selected assertion 与 conflict count,与质量 Belief 同一套语义。

## 5. 与阶段计划的关系

- **依赖 Phase 10**:复用其 assessor identity、resolver 版本升级流程、`*_index` 查询投影模式;`earliest_erroneous_step` 归因与语义角色交叉是首个联动消费场景。
- **依赖 Phase 11(仅 G2/G4)**:enrichment worker 的原文读取必须走 Phase 11 的 raw read 审计通道;worker 的 job/lease 形态与 Phase 11 collector/queue 加固同批设计最省。
- **不阻塞也不被阻塞**:第一层规则 assessor 不依赖任何未完成阶段,可作为独立小迭代随时落地;但为避免 taxonomy 定义返工,建议至少等 Phase 10 的 evaluation 维度词汇冻结后再定 taxonomy v1。
- **UI 归属 U1**:轨迹可视化并入 Lineage UI 重构(Phase 10 后、Phase 12 前)。

建议的施工顺序:

1. Phase 10 完成后:定 taxonomy v1 + G1 `annotation.recorded` 契约 + 第一层规则 assessor + 轨迹读模型/API(一个小纵向切片);
2. Phase 11 期间:G2 enrichment worker 与 raw read 审计通道、collector 加固同批设计落地;
3. Phase 12 前:轨迹视图随 U1 收敛进 Task 详情信息架构。

## 6. 开放问题

- taxonomy v1 的枚举集合与定义(plan/act/verify/present 之外是否需要 recover/explore/idle);建议参照真实 Task 样本人工标注一批后再冻结。
- 批标模式下,一次 enrichment 调用的上下文上限与超长轨迹的分段策略。
- subagent Task 的轨迹是否独立标注(倾向是:每个 Task 独立轨迹,树状聚合留给读模型)。
- enrichment 模型选择与 configuration drift:enricher 自身的 release 变化是否需要在标注上显式区分 cohort(倾向复用 Phase 10 cohort key 机制)。

## 7. 概念同步义务

按 [concepts.md](concepts.md) §8 与 plans/README 合并规则:本设计进入实施时,`annotation.recorded`、taxonomy、`semantic_role` Belief 字段与 trajectory 读模型必须同步登记到 concepts.md、设计文档协议层、对应 Phase 计划与测试矩阵。
