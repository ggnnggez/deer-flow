# 人工发现跟进项（非评审来源）

来源：实际使用中人为发现的改进点（2026-07-20 首次登记），区别于各 Phase 代码评审产生的 `phase-*-review-followups.md`。编号按领域分组：`U`（UI）/`D`（文档）/`A`（架构），不表示优先级。每项由登记人描述现象，"归属"栏给出施工时机评估；修复一项后同步更新总览表和该项"状态"行，保留原始记录。

维护规则：人为发现的问题随时登记到本文件（先只填"现象/相关位置"，施工时机可后补评估）；每个 Phase 开工前复查本文件，把归属到该阶段的项转入对应 Phase 计划；归属到 Phase 12 的项在验收演练前必须清零或显式降级为 known gap。

## 状态总览

| 编号 | 摘要 | 状态 | 施工时机归属 | 修复时间 | Commit |
| ---- | ---- | ---- | ------------ | -------- | ------ |
| U1 | Context Lineage UI 重构：总览→细节渐进式披露，local graph 树状化 | ⬜ 未修复 | Phase 10 之后、Phase 12 之前 | — | — |
| U2 | 按来源浏览块内容（raw/model-visible 对照） | ⬜ 未修复 | Phase 11 同批（依赖 raw read 强审计） | — | — |
| U3 | 投影 Degraded 无 failed jobs 细节，无法下钻排查 | ✅ 已修复 | 可提前，建议随 Phase 9 顺带或独立小迭代 | 2026-07-21 | 5b5d03a7 |
| U4 | Context Compression 不显示执行时机（发生时间与触发 operation） | ⬜ 未修复 | 随时可做，建议与 U3 同批随 Phase 9 顺带 | — | — |
| D1 | 缺开发文档：概念词汇表（ContentBlock/Step/…） | ✅ 已修复 | 立即，不依赖任何 Phase | 2026-07-21 | `152f44c2`（Phase 10 扩写 `2dedd08a`） |
| D2 | 缺使用文档：仪表盘指标含义 | 🟡 ① 已修复 / ② 未修复 | ① 内联 tooltip 随时可做；② 正式文档归属 Phase 12 §9 | ① 2026-07-24 | ① `3425a7a1`；② — |
| A1 | ansich 与 deerflow 采集面耦合，抽象 obs layer | ⬜ 未修复 | Phase 10 后启动设计，迁移与 Phase 11 同批 | — | — |

## U1. Context Lineage UI 重构：渐进式披露 + local graph 树状化

- 状态：⬜ 未修复。
- 现象：整个 Context Lineage 的 UI 需要重构，原则是从总览到细节的渐进式披露；local graph 考虑用树状图表示。
- 相关位置：`frontend/src/components/workspace/ansich/lineage-explorer.tsx`；API 为 Phase 4 落地的 metadata-only lineage/exposure/snapshot/compression。
- 现状：当前是点击后加载的局部图，信息层级平铺，"总览→下钻"路径不清晰；谱系图与 Phase 8 的 Task tree 是两套可视化心智，使用者需要在脑中自行拼接。
- 方向：顶层先给压缩后的谱系总览（按 producer kind 聚合/计数、关键变换点标注），点击节点再展开局部 derivation 子图；local graph 在父子派生为主干时优先树状布局，多 parent/跨分支边以主边入树、次边虚线标注，保留图布局 fallback。
- 归属：**Phase 10 之后、Phase 12 之前**。Phase 9（Scope/effect）与 Phase 10（评估输入、语义 Belief）还会向谱系新增实体与边类型，现在重构总览信息架构届时要二次返工；Phase 10 后实体种类稳定，正好赶在 Phase 12 验收演练（含真实 paper drill）前完成 UX 收敛。纯前端改动，不阻塞任何后端阶段；若日常排查已明显受阻，可提前拆出"总览聚合层"独立做，树状布局仍留到 Phase 10 后。

## U2. 按来源浏览块内容

- 状态：⬜ 未修复。
- 现象：考虑做各个来源（user input / tool raw result / memory / skill / summary …）的内容浏览。
- 相关位置：Phase 4 API 明确为 metadata-only；payload 分层 Phase 2 已落地；Phase 11 计划包含 payload/structure 独立 retention 与 raw read 强审计。
- 现状：UI 只能看谱系元数据（kind/producer/边），无法浏览块内容；排查"模型到底看到了什么"只能直接查库。
- 方向：按 producer kind / snapshot membership 提供内容浏览视图，raw 与 model-visible 对照展示，payload 按既有分层脱敏。
- 归属：**Phase 11 同批**。内容浏览本质是 raw read，Phase 11 正要落地 raw read 强审计与 payload 独立 retention；在审计口径与 retention 拆分就位前开放内容浏览，读取路径将来要重写一遍，且浏览行为会绕过未来的审计点。提前做等于做两遍。

## U3. 投影 Degraded 无 failed jobs 细节

- 状态：✅ 已修复（2026-07-21）。新增 `AnsichService.list_failed_jobs`/`get_failed_job_detail`（`backend/packages/harness/deerflow/ansich/persistence/sql.py`、`backend/packages/ansich/ansich/service.py`）与三个 admin-only 路由 `GET /operations/failed-jobs`、`GET /operations/failed-jobs/{job_id}`、`POST /operations/failed-jobs/retry`（后者首次把已存在的 `retry_failed_projections` 暴露到 HTTP）；`ProjectionHealth` 的 `failed_jobs` 指标在非零时可点击，打开 `AnsichFailedJobsDialog`——Task 详情页按 taskId 过滤，Operations 页显示全局列表且按 Task 分组重试。详情展开显示 `AnsichProjectionErrorRow`/`AnsichAssessorErrorRow` 的完整 attempt 错误历史（不受重试清除影响）。重试保持按 Task 批量粒度，未做单 job 精确重试。设计文档：`docs/superpowers/specs/2026-07-21-ansich-failed-jobs-diagnostics-design.md`。
- 现象：投影出现 Degraded 时没有详细错误显示，例如存在 failed jobs 时不能查看其细节。
- 相关位置：`frontend/src/components/workspace/ansich/projection-health.tsx`（仅显示 `failed_jobs` 计数）；`backend/packages/ansich/ansich/service.py::get_health`（failed_jobs → degraded 判定）、`::retry_failed_projections`（已存在，约 line 824）；`backend/app/gateway/routers/ansich.py` 无 jobs 列表/详情端点。
- 现状：健康面板显示 degraded 与 failed_jobs 计数，Context & Lineage 页在存在失败 Job 时显示"投影不可用"提示（Phase 4 加固），但都看不到是哪个 job、哪个 projector、什么错误；排查只能查数据库。
- 方向：新增 admin-only 失败 Job 列表/详情 API（job kind、projector version、attempts、last error、关联 Task/Observation 范围）；健康面板 failed_jobs 计数支持下钻到列表；详情处提供 retry 入口，复用现有 `retry_failed_projections`。
- 归属：**可提前，建议随 Phase 9 顺带或独立小迭代**。这是纯只读诊断面加一层薄 API/UI，重试服务已存在，不依赖任何未来阶段，且是日常运维高频痛点，早做早受益。注意 DTO 字段口径先对齐 Phase 11 的 poison job 隔离设计（`ansich_projection_errors` 表 + `projection_failure` Alert），避免 Phase 11 再改 schema；若排期紧张，最小切片（列表 + 错误文本 + retry 按钮）先落地，多 worker lease 细节留给 Phase 11。

## U4. Context Compression 不显示执行时机

- 状态：⬜ 未修复。
- 现象：Context Lineage 模块的 Context Compression 面板不显示压缩的执行时机——既看不到发生时间，也看不到是执行序列中哪个位置（哪个 Step/summarization operation）触发的压缩。
- 相关位置：`frontend/src/components/workspace/ansich/lineage-explorer.tsx`（`CompressionPanel` 按钮只显示 `#1/#2` 序号，`CompressionDetail` 只显示 id/status/tokens/algorithm/summary block）；`frontend/src/app/workspace/ansich/tasks/[task_id]/page.tsx:65`（把 compressionsQuery 分页数据 flatMap 后只保留 `compression_id`）；后端 `backend/packages/ansich/ansich/compression.py` 的 `ContextCompressionView` 与 `sql.py::get_context_compression`（约 line 4367）。
- 现状（代码核实）：**数据在传输链路上被丢掉了两层**。① 发生时间：列表 view（`ContextCompressionSummaryView`）已通过 join `ansich_observations` 返回 `occurred_at`，但前端任务页 flatMap 时只取 `compression_id`，时间与 `summary_operation_id` 一并被丢弃；详情 view（`ContextCompressionView`）则连 `occurred_at` 字段本身都没有（同样的 join 在列表查询已有先例）。② 执行位置：压缩记录持有 `operation_id`（Phase 2 的 summarization system operation），Step 投影有 `actor_kind="system_operation"` + `operation_id`，step-explorer 已展示 system operations 列表——压缩→operation→Step 的链路数据上闭合，但前端未展示也未交叉引用。
- 方向：① 后端给 `ContextCompressionView` 补 `occurred_at`（复用列表的 observation join），不引入新表；② 前端压缩列表项显示时间戳（或相对时间），详情显示 `occurred_at` + summary operation（operation_kind/operation_id），并用 task 已有 system operations 列表交叉引用、链接到对应 Step；连续压缩（Phase 4 的复用上一次 summary 场景）按各自 `occurred_at` 正常显示即可，无需特殊处理。
- 归属：**随时可做，建议与 U3 同批随 Phase 9 顺带**。缺口仅为"详情 view 缺一个已有数据源的字段 + 前端丢数据"，工作量小、不依赖未来阶段；若到 U1（Lineage UI 重构，Phase 10 后）开工时仍未修，则必须并入 U1——重构后的渐进式详情面板必须把执行时机作为一级信息。

## D1. 开发文档：概念词汇表

- 状态：✅ 已修复（2026-07-21，`152f44c2`）。`ansich/docs/concepts.md` 已落地：三层心智模型（Observation / 事实读模型 / Belief）打头，逐个定义 v0.2 词汇并标注 payload 分层、投影与重放语义、实现代码路径与所属 Phase。随后按阶段持续扩写，最近一次是 `2dedd08a`（Phase 10 的评估与语义 Belief 一节，含小节重编号与悬挂交叉引用修复）——即该文档**已随实现走到 Phase 10**，不是一次性快照。配套动作（把「新增概念同步进 concepts.md」写进 plans/README 的阶段合并规则）本次一并补上。
- 现象：缺少开发文档；第一步应先创建一个文档介绍 ansich 中各个概念，比如 ContentBlock、Step 等。
- 相关位置：`ansich/docs/` 现仅有设计文档、架构 UML 与阶段计划，无面向开发者的概念导览。
- 现状：设计文档回答"为什么这么建"，阶段计划回答"怎么验收"，缺少"系统里有哪些概念、彼此什么关系"的地图；新开发者或评审者要读完 8 个阶段计划才能拼出概念全貌。
- 方向：新建 `ansich/docs/concepts.md`（开发者导览）：以 v0.2 词汇（Task / AgentRelease / Step / attempt / ToolCall / ContentBlock / ContextSnapshot / Observation / Belief / Relation / Usage / Projection / Job / Alert / Scope / effect）逐个定义，配实体关系图；每个概念标注 payload 分层、投影/重放语义，并指向实现代码路径与所属 Phase。
- 归属：**立即，不依赖任何 Phase，建议下一个可用窗口就做**。Phase 1–8 的概念已稳定，现在写不会大面积返工；Phase 9–12 仍在开发，文档对后续施工与评审都有杠杆（评审 followup 中多例"职责重叠/易被误读"本质是概念没有统一落点）；登记人亦标记此项为高优先（！！！）。配套动作：把"新增概念同步进 concepts.md"加入 plans/README 的阶段合并规则，防止文档再次腐化。

## D2. 使用文档：仪表盘指标含义

- 状态：🟡 分层结算——**① 内联层已修复**（2026-07-24，`3425a7a1`）、**② 正式使用文档仍未做**（归属 Phase 12 §9，不变）。
  - ① 已落地的范围：Operations 的 `System details` 抽屉里每个指标标签都带一个**可键盘聚焦**的 help trigger，tooltip 给出该指标的定义与诊断含义，文案已进 `en-US`/`zh-CN` 两份 locale（`systemMetricDescriptions` 共 14 项：queue/queue high-watermark/queue bytes/queue byte high-watermark、watermark、lag、failed jobs、accepted、dropped、lost、snapshot requests、snapshot items、incomplete snapshots、missing blocks），failed-job 的 help 与那个可点击下钻的数值分开以免误触；e2e 已覆盖。
  - ② 仍缺的范围：每个指标的**正常区间、异常含义与处置动作**——tooltip 回答"这是什么"，不回答"多少算不正常、然后该做什么"。这部分连同 Alert 含义、interrupt/rollback 差异、retention/replay 命令仍是 Phase 12 §9 的发布门禁项。理由不变：Phase 11 还会新增 retention/lost-range 类指标，语义冻结后再一次写到位。
- 现象：观测系统状态仪表盘中各个指标的意思没有说明。
- 相关位置：Operator Lens / active-task 仪表盘（Phase 5）、projection-health 面板；Phase 12 §9 已把"运维文档：health 字段、Alert 含义、interrupt/rollback 差异、retention/replay 命令"列为发布门禁。
- 现状：heartbeat lag、budget 消耗、usage local/inclusive、failed_jobs、watermark lag 等指标无释义，非作者无法判断什么算异常、异常后该做什么。
- 方向：分两层：① 内联层——指标 tooltip/字段说明，成本低，随做随有；② 正式使用文档——每个指标的定义、来源投影、正常区间、异常含义与处置动作。
- 归属：**内联 tooltip 随时可做，建议随 D1 同批；正式文档归属 Phase 12 §9**。Phase 9–11 还会新增 Alert 与指标（授权/副作用、语义 Belief、retention/lost range），指标语义在 Phase 11 后才冻结，正式文档一次写到位，避免反复改写。

## A1. ansich 与 deerflow 采集面耦合：抽象 obs layer

- 状态：⬜ 未修复。
- 现象：ansich 和 deerflow 耦合严重，考虑在 deerflow 中抽象出 obs layer。
- 相关位置：plans/README 的固定实现边界已规定 `deerflow -> ansich` 单向依赖与 harness 适配层；但 probe 调用点散布在 deerflow 运行时（Gateway、subagents/executor、middleware、summarization 等），运行时代码直接感知 ansich 概念，各调用点自行判空处理开关/降级。
- 现状：**包边界是干净的**（ansich core 不依赖 DeerFlow/LangGraph/FastAPI），但**采集面耦合**：新增观测点要同时理解两侧，Ansich 关闭时的行为分散在各调用点。
- 方向：在 deerflow 侧抽象统一 obs 采集层（如 `deerflow/obs/`）：定义 probe sink 接口 + no-op 默认实现，ansich adapter 注册为 sink 实现；运行时模块只对 obs 层编程，开关与 fail-open 策略在层内收敛。这也是 Phase 12 "关闭 Ansich 基准对比"门禁的天然开关点。
- 归属：**Phase 10 完成后启动设计，迁移与 Phase 11 同批**。Phase 9（授权/副作用）与 Phase 10（评估输入）还会新增语义不同的 probe 点，现在抽象只能基于 8 个阶段的样本，接口容易猜错；Phase 10 后 probe 面基本完整（Phase 11/12 以加固为主，新增 probe 很少），抽象可一次到位；Phase 11 本来就要重写 collector/queue/lease 边界，迁移 probe 调用点与 collector 加固碰同一批代码，同批做只动一次。次优可接受项：提前到 Phase 9 前做，让 9/10 的新 probe 直接长在新接口上，代价是接口在 9/10 期间仍会演化。非阻塞。

## 施工时机汇总（按时间线）

现状锚点（2026-08-19，Phase 11 前加固批收尾时复核）：Phase 1–10 已落地，Phase 11 尚未开工。因此下表第 1–3 档都已到期，第 3 档的两项是**当前唯一的欠账**。

1. ~~**立即**：D1（概念词汇表）；D2 的 tooltip 内联层同批。~~ **已完成**：D1 由 `152f44c2` 落地并扩写至 Phase 10（`2dedd08a`）；D2 的内联层由 `3425a7a1` 落地（D2 的正式文档仍在第 5 档）。
2. ~~**Phase 9 期间（可提前）**：U3（failed jobs 下钻）；U4（compression 执行时机）。~~ **半完成**：U3 已由 `5b5d03a7` 落地；**U4 仍未做**，且已过其建议窗口——按它自己的归属说明，若拖到 U1 开工仍未修，就必须并入 U1（重构后的渐进式详情面板要把执行时机作为一级信息）。
3. **Phase 10 完成后（**现已到期**）**：U1（Lineage UI 重构）与 A1（obs layer 抽象）设计**现在就该启动**——Phase 10 已完成，谱系实体种类已稳定，而 Phase 12 的验收演练是 U1 的硬期限。这两项是本文件当前的主要欠账。
4. **Phase 11 同批**：U2（依赖 raw read 强审计与 retention）；A1 的实际迁移（与 collector/queue/lease 加固碰同一批代码，同批做只动一次）。U3 已提前完成，此档不再挂它。
5. **Phase 12 前清零**：U1 完成 UX 收敛；D2 的正式使用文档随 §9 门禁交付；本文件所有剩余项要么关闭要么显式登记为 known gap。
