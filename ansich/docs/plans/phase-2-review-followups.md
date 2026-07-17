# Phase 2 代码评审跟进项

来源:commit `22198141`(Phase 2 Step 与上下文可观测性切片)的代码评审(2026-07-17)。编号带 `H`(高)/`M`(中)/`L`(低)优先级;修复一项后同步更新总览表和该项"状态"行,保留原始诊断记录。

## 状态总览

| 编号 | 摘要 | 状态 | 修复时间 | Commit |
| ---- | ---- | ---- | -------- | ------ |
| H1 | Timeline 轮询端点泄漏原始内容体,绕过带日志的 raw 通道 | ✅ 已修复 | 2026-07-17 | `c64d8ea2` |
| H2 | 上下文快照物理全量重录，产生 O(N²) 写放大和投影队列风险 | 🟡 A-C 与 D 存储基础完成；压缩谱系留在 Phase 4 | 2026-07-17 | 待提交 |
| M1 | 新增 `inline_payload_max_bytes` 未 bump `config_version` | ✅ 已修复 | 2026-07-17 | 待提交 |
| M2 | 模型实例上的 `_ansich_call_class` 元数据无读取方 | ✅ 已修复 | 2026-07-17 | 待提交 |
| M3 | raw-payload 端点缺 `Cache-Control: no-store` | ✅ 已修复 | 2026-07-17 | 待提交 |
| M4 | LLM 错误 fallback 时 Step 记为 `final_answer` 的语义待确认 | ✅ 已修复 | 2026-07-17 | 待提交 |
| M5 | `list_system_operations` 按随机 UUID 排序 | ✅ 已修复 | 2026-07-17 | 待提交 |
| L1 | 迁移 0007 自写 `_add_column` 而非 `_helpers.safe_add_column` | ✅ 已修复 | 2026-07-17 | 待提交 |
| L2 | worker 使用字面量 `"__ansich_execution_context"` 而非常量 | ✅ 已修复 | 2026-07-17 | 待提交 |
| L3 | `usage_json` 列混存 usage 与 response_metadata,命名误导 | ✅ 已修复 | 2026-07-17 | 待提交 |
| L4 | `get_max_step_seq` 依赖投影追平的前提未标注 | ✅ 已修复 | 2026-07-17 | 待提交 |

## H1. Timeline 轮询端点泄漏原始内容体,绕过带日志的 raw 通道

- 状态:✅ 已修复(2026-07-17,commit `c64d8ea2`)。按 TDD 修复:timeline DTO 转换剥离 `content.produced` payload 的 `body` 字段,保留 hash/size 清单;新增"timeline 轮询响应不含原始 body"回归测试。raw-payload 端点仍是唯一 body 出口。以下为原始诊断记录。
- 位置:`backend/app/gateway/routers/ansich.py::get_task_timeline`(原样 `model_dump()` 观测 payload)+ `deerflow/ansich/middleware.py::_record_captured_request`(`content.produced` payload 内联完整 `body`)+ `frontend/.../observation-timeline.tsx`(渲染 `observation.payload`)。
- 现状:≤`inline_payload_max_bytes` 的原始提示词/工具输出(绝大多数)进入 5 秒轮询响应与 TanStack 缓存,且不触发 raw-payload 端点的访问日志 —— 同时违反 frontend/AGENTS.md("raw body 绝不进轮询响应或 query cache")与 backend/AGENTS.md("raw body 只经 logged 端点")。路由测试未覆盖"timeline 不含 body",因此漏网。
- 方向:timeline DTO 转换时剥离 `content.produced` payload 的 `body` 字段(保留 hash/size 摘要),或从 timeline 排除该 kind;补"timeline 响应不含原始 body"回归测试。
- 归属:立即修复。

## H2. 上下文快照物理全量重录，产生 O(N²) 写放大和投影队列风险

- 状态：🟡 分阶段修复。阶段 A、B、C 以及阶段 D 的 ContextState/Delta/物化存储基础已落地；常见 append-only 对话不再重复写历史 occurrence 和完整 snapshot inventory。阶段 D 的 `context.compressed` source/preserved/removed inventory 与 `derived_from` 边仍按原归属留在 Phase 4，不能用前后文本 diff 代替。该剩余项不阻塞 Phase 3，因为 Phase 3 前置条件是阶段 A 的长上下文队列与投影风险治理。
- 位置：`deerflow/ansich/middleware.py::_record_captured_request`、`ansich/serialization.py::serialize_model_request` / `_block`、`ansich/service.py::AnsichService.record`、`sql.py::persist_and_project` / `_project_context_snapshot`。

### H2.1 当前全量重录机制

每次 LangChain 模型 adapter 收到最终 `ModelRequest` 前，Phase 2 按以下路径捕获请求：

1. `serialize_model_request` 遍历 system message、严格有序的 messages/content parts、可见 Tool schemas、response format 和 generation settings。
2. `_block()` 为每个 snapshot item 计算 `content_hash`，但也无条件生成新的 `block_id`。即使某条历史消息在连续两个 attempt 中完全未变化，仍会得到两个 ContentBlock。
3. `_record_captured_request` 先写一条 `llm.requested`，再为 N 个 item 各写一条 `content.produced`，然后写一条携带完整 N 项 inventory 的 `context.snapshotted`，最后写 `llm.responded` 或 `llm.failed`。
4. `SqlAnsichBackend.persist_and_project` 为每条 Observation 都创建 `task-structural`、`task-control`、`task-step` 三个 projection job；前两个 projector 对 Phase 2 kinds 大多直接 no-op，但仍产生 job 行、认领和事务开销。
5. `_project_context_snapshot` 要求 inventory 引用的每个 `block_id` 已投影；缺少任一 `content.produced` 时抛错，最多重试 5 次后形成 failed projection job 并使 Ansich health 降级。

因此，含 N 个 item 的一次物理模型请求产生约 `N + 3` 条 Observation；若计入外层 `step.started` / `step.closed`，无重试 Step 约为 `N + 5` 条。含 R 次模型 attempt 的 Step 约为 `2 + R * (N + 3)` 条。以 N=100、R=1 为例，约 105 条 Observation 会进一步生成约 315 个 projection jobs。

若第 k 个 Step 的上下文大小近似 `N_k = B + c*k`，K 个 Step 的累计 item 写入量为：

```text
Σ N_k = K*B + c*K*(K+1)/2 = O(K²)
```

上下文达到窗口上限后会退化为 `O(K * max_context_items)`，但仍在每次调用反复写入近乎相同的窗口；retry 还会重复同一份物理请求。`context.snapshotted` 自身也再次保存完整的 block ID、ordinal、role、bytes 和 metadata inventory。

### H2.2 风险边界

这是“逻辑上必须全量，物理上不应全量复制”的问题。Ansich 必须能回答 adapter 在某次 attempt 实际看到了什么，因此不能只保存 delta、依赖运行时内存才能重建，也不能只保存一个 request hash。

当前实现的主要风险是：

- 存储写放大：历史消息、system prompt、Tool schema 和 retry request 被重复保存。
- 投影写放大：每条 P2 Observation 都无差别生成 3 个 projection jobs。
- fail-open 队列压力：`_record_captured_request` 在一个同步循环内连续调用 `record()`；队列满时单条 Observation 立即丢弃，单个 snapshot bundle 没有原子接收语义。
- 不完整依赖：在简单的单协程队列溢出中，位于尾部的 `context.snapshotted` 往往也会一起丢失，所以 poison 并非必然；但并发 producer、批次持久化失败或部分历史数据缺失时，snapshot 可能落库而其引用的 ContentBlock 未落库，此时固定次数重试无法自愈。

### H2.3 身份与去重不变量

原建议的 `(task_id, content_hash)` 级 ContentBlock 复用不安全，废弃该方向。设计文档 §4.6 已规定：ContentBlock 是“带 provenance 的不可变 occurrence”，`content_hash` 是比较属性而非身份。

例如，两条不同 user message 都是 `"yes"` 时，内容 hash 相同，但它们的 producer、出现时间、上下文位置和后续谱系不同，必须有不同 `block_id`。同理，copy、coalesce、sanitize、truncate、summarize 等变换即使输出文本相同，也不能仅凭 hash 合并 provenance。

H2 的目标模型分为三层：

```text
ContextSnapshotItem(snapshot_id, ordinal, block_id, ...)
    -> ContentBlock / ContentOccurrence(block_id, source identity, producer, kind, blob_key, ...)
        -> ContentBlob(blob_key, content_hash, byte_size, content_type, body/payload_ref, ...)
```

- `ContentBlob` 表示 canonical visible bytes，可按 `content_hash + byte_size + content_type/canonicalization_version` 去重物理 payload；hash 冲突防御仍需核对长度和字节。
- `ContentBlock` 继续表示带来源的内容实例。两个来源不同但正文相同的 block 可以指向同一 blob，但不能共享 block ID。
- `ContextSnapshotItem` 保留严格 ordinal，并引用 block；快照的逻辑 inventory 始终可以独立、完整地物化。

只有“同一个历史 occurrence 在后续 snapshot 中再次出现且内容未变”时，才允许复用原 `block_id`。复用判定必须同时满足稳定 source identity 和内容 hash 一致，例如：

```text
message: (task_id, message_occurrence_id, content_part_ordinal, occurrence_seq)
tool call/result: DeerFlow occurrence identity + content_part_ordinal
tool schema: promoted source identity + schema/version identity
```

registry 命中但 hash 改变表示内容发生了变换或 source identity 被错误复用，必须创建新 block 并在可知时记录 `derived_from`，不能覆盖旧 block。provider `tool_call_id` 可能在压缩后重复，不能单独作为 identity。

### H2.4 分阶段落地方案

#### 阶段 A：先降低队列和投影风险

归属：Phase 2 follow-up；在 Phase 3 前开始真实长上下文负载试用时必须先完成。

状态：✅ 已完成。Observation kind 显式路由、typed missing inventory/晚到修复、snapshot bundle 接收指标、队列最高水位与大快照/乱序/永久缺失回归测试均已落地；Operations UI 会显式显示 incomplete snapshot 和 unknown gap。

1. 为 Observation kind 建立显式 projector routing，只为真正消费该 kind 的 projector 创建 job。`task.created/started/...` 仍按依赖顺序进入 structural/control；`step.*`、`llm.*`、`content.produced`、`context.snapshotted` 只进入 task-step。不能只在 projector 内 no-op。
2. 让缺失 block 的 snapshot 进入结构化 `incomplete` 状态，保存缺失 block inventory，并允许晚到的 `content.produced` 回填后转为 `complete`；永久缺失应表现为 unknown gap，而不是反复 poison 同一 projection job。缺失引用必须使用 typed row 或等价的受约束结构，不能只塞进 JSON warning。
3. 增加 snapshot 级运行指标：`snapshot_item_count`、`snapshot_visible_bytes`、每次 request 接受/丢弃的 Observation 数、队列 high-watermark、incomplete snapshot 数和 missing block 数。指标不包含 raw body。
4. 增加大 snapshot、queue 边界、并发 producer、乱序/晚到 content 和永久缺失 content 的 TDD 用例；验证 fail-open 不影响 Agent，同时 Ansich 明确标记 loss/incomplete。

本阶段不减少 ContentBlock 数量，但先移除约 2/3 的无效 P2 projection jobs，并把“压力过大”从隐性 poison 变为可度量、可修复或可解释的降级。

#### 阶段 B：ContentBlob 物理 payload 去重

归属：Phase 4 的数据库与 retention 基础，可独立于完整谱系遍历先交付。

状态：✅ 已提前完成。`ansich_content_blobs`、block→blob 引用、并发 upsert、逐字节 hash 冲突防御、raw 授权边界、migration/backfill/downgrade 与 SQLite 回归测试已落地。

1. 新增 `ansich_content_blobs`，至少包含 `blob_key/content_hash`、`byte_size`、`content_type`、`canonicalization_version`、`payload_status` 和 `payload_ref/body`；为去重键建立唯一约束。
2. `ansich_content_blocks` 新增 `blob_key` FK。ContentBlock 的 `block_id`、producer、kind、sensitivity/provenance 仍独立保存。
3. 投影 `content.produced` 时先幂等 upsert blob，再创建 occurrence block。相同正文的不同 user message 形成两个 block、一份 blob。
4. raw payload endpoint 从 block 经 blob 读取正文，仍保留 block 级授权、访问审计、sensitivity 和 retention 语义；不能因为 blob 共享而放宽任何一个 block 的访问范围。
5. migration/backfill 必须支持既有 `payload_obs_id`，并验证 SQLite/PostgreSQL 下一致的并发 upsert、hash 冲突防御和 replay 幂等性。

本阶段主要消除 raw/canonical body 的重复字节，但 snapshot 中仍可能存在重复的 occurrence block 和 `content.produced` Observation。

#### 阶段 C：稳定 occurrence 复用

归属：Phase 4 `ContextProvenanceRegistry`。

状态：✅ 已提前完成。稳定 source identity、确定性 UUID4 block/Observation identity、持久化确认后复用、失败后幂等重发、checkpoint/restart 预加载及 typed occurrence 表已落地。

1. 把稳定的 message occurrence identity 保存在 Task-local sidecar registry 中：`source identity -> (block_id, content_hash, producer_obs_id, kind)`。不要仅依赖 message 文本、数组 ordinal、Python 对象地址或 provider ID。
2. 序列化 snapshot 时，registry 命中且 hash 一致则只在 snapshot inventory 中引用既有 `block_id`，不再发重复的 `content.produced`；未命中、hash 改变或发生 transform 时创建新 block。
3. 当前 serializer 已读取顶层 `message_id`，但 snapshot item SQL 投影没有保存该字段；落地 registry 前必须把稳定 source identity 持久化为受约束列/表，以支持 checkpoint、恢复、replay 和诊断。
4. 明确“已进入内存队列”不等于“已持久化”。复用旧 block 时必须保证引用可重放：优先使用确定性的 `block_id/source_event_id` 并允许幂等重发 `content.produced`，或提供持久化确认/repair 路径；不能让内存 registry 指向一条已经 fail-open 丢失且永远不会重发的 Observation。
5. 对相同文本不同 occurrence、同一 occurrence 跨 snapshot、message copy、coalesce/summary、retry、checkpoint 恢复和采集丢失补齐测试。

完成本阶段后，未变化的 system prompt 和历史消息只产生一次 ContentBlock；后续 snapshot 仅重复有序引用，retry 的重复写入量会显著下降。

#### 阶段 D：增量 ContextState 与快照谱系

归属：Phase 4 上下文谱系与压缩的完整方案。

状态：🟡 存储基础已完成。attempt-specific ContextSnapshot 已改为引用可复用 immutable ContextState；ordered append/remove/replace/reorder delta、确定性物化、最大链深 32 的 checkpoint、父状态/内容块晚到修复和 replay/rebuild 测试已落地。压缩 source/preserved/removed inventory 与 summary `derived_from` 边仍是 Phase 4 工作，不在本轮冒充完成。

1. 将可复用的不可变 `ContextState` 与“某次 attempt 捕获了它”的 `ContextSnapshot` 分开。当前 `ansich_context_snapshots.request_obs_id` 唯一且保存 `attempt_no`，不能直接让不同 attempts 共用同一 snapshot row。
2. `ContextState` 支持 `parent_state_id + ordered delta`，delta 至少表达 append/remove/replace/reorder，并记录产生变化的 Observation/transform；系统仍需提供确定性的 full materialization。
3. `ContextSnapshot` 保持 attempt-specific identity，引用一个 immutable ContextState，同时保存本次 adapter/model/generation settings、capture warnings 和 request causation。内容完全相同的 retries 可以共享 ContextState，但两个 attempts 和两个 snapshots 仍是不同事实。
4. 压缩必须显式保存 source/preserved/removed inventory 和 summary block 的 `derived_from` 边；不得通过前后文本 diff 猜测 provenance。
5. 读取 API 默认返回 materialized、严格有序的完整 inventory；增量链只是存储实现。链长要有上限，并支持周期性 checkpoint/materialized state，避免读取退化为无限 parent traversal。
6. replay 必须从 Observation/typed deltas 得到相同的最终 inventory；测试覆盖 append-only、删改、reorder、连续压缩、retry 共享、父状态缺失、链截断和 SQLite/PostgreSQL 查询一致性。

目标形态类似 Git：一次 ContextSnapshot 在逻辑上是完整的 commit/tree，但未变化的 ContentBlock/ContentBlob 可以被多个状态引用，不重复保存正文和 provenance occurrence。

### H2.5 完成条件

- 任一成功或失败 attempt 的 ContextSnapshot 都能按 ordinal 物化 adapter 实际看到的完整 inventory；不依赖进程内 registry 才能读取。
- 相同正文、不同 producer/occurrence 保持不同 `block_id`；同一稳定 occurrence 跨 snapshots 可复用 block；payload bytes 可经 ContentBlob 去重。
- 大上下文和 retry 的 Observation/job/byte 增长有基准测试，常见 append-only 对话不再随 Step 数产生正文和 occurrence 的平方级复制。
- 队列丢失、乱序、批次失败和永久缺块不会 poison 投影；API/UI 明确呈现 `incomplete` / `unknown_gap`。
- projector routing 不产生已知必然 no-op 的 jobs；健康指标能够定位 snapshot 写放大、队列压力与缺失引用。
- Phase 4 的 lineage、compression 和 possible exposure 查询仍以 ContentBlock occurrence 为语义节点，不能退化为 content-hash 级文本相似图。

## M1. 新增 `inline_payload_max_bytes` 未 bump `config_version`

- 状态：✅ 已修复。`config.example.yaml` 已从 27 升到 28，存量配置会进入正常 upgrade 提示/合并路径。

- 位置:`config.example.yaml`(仍为 27)。
- 现状:`make config-upgrade` 不会向存量用户合并新字段,违反仓库"改 schema 必 bump"约定。
- 方向:bump 到 28,一行修复;下次任何 config 变更时顺带处理亦可。

## M2. 模型实例上的 `_ansich_call_class` 元数据无读取方

- 状态：✅ 已修复。删除 factory 参数、私有属性 stamp 及所有调用点；Agent Step 与 system operation 分类继续由实际 Ansich middleware/observe 边界显式决定，避免死元数据泄漏到 mock 或 provider kwargs。

- 位置:`deerflow/models/factory.py::create_chat_model`(`object.__setattr__` stamp)。
- 现状:全部调用点都传了 `ansich_call_class`/`ansich_operation_kind`,但仓库内无任何读取方(仅测试断言存在)—— 死代码,或本应作为 Decision middleware 的 actor 判定来源而漏接线。
- 方向:二选一:删除 stamp 与参数,或让 `AnsichDecisionMiddleware`/`observe_system_model_*` 从模型实例读取分类作为兜底。

## M3. raw-payload 端点缺 `Cache-Control: no-store`

- 状态：✅ 已修复。成功读取响应带 `Cache-Control: no-store`，并有路由回归测试。

- 位置:`routers/ansich.py::get_content_block_payload`。
- 现状:原始提示词体可能被浏览器/中间层缓存;Phase 11 §7 明确要求 no-store,端点既然提前落地就应带上。
- 方向:响应加 `Cache-Control: no-store` 头,一行修复;Phase 11 落地 fail-closed 审计时复查。

## M4. LLM 错误 fallback 时 Step 记为 `final_answer` 的语义待确认

- 状态：✅ 已修复。Decision middleware 识别 `deerflow_error_fallback=true` 并关闭为 `model_failed`；中间件顺序测试同时断言 attempt 全失败且无 effective attempt。

- 位置:middleware 链顺序 —— `AnsichDecisionMiddleware` 在 `LLMErrorHandlingMiddleware` 外侧。
- 现状:provider 异常被转成 fallback AIMessage 后,Decision 记 `step.closed result="final_answer"`,而该 Step 的 attempts 全为 `failed`、`effective_attempt_no=None`,读数自相矛盾。
- 方向:识别 `additional_kwargs.deerflow_error_fallback` 标记并记为 `model_failed`(或在 payload 标注 fallback);先对照设计文档确认意图再改,附中间件顺序回归测试。

## M5. `list_system_operations` 按随机 UUID 排序

- 状态：✅ 已修复。SQL 查询关联 request Observation 并按 `ingest_seq, attempt_no` 排序；回归测试故意使用与摄入顺序相反的 UUID。

- 位置:`sql.py::list_system_operations` 的 `order_by(request_obs_id, attempt_no)`。
- 现状:`request_obs_id` 是 UUID,排序无业务意义,系统操作列表顺序实际随机。
- 方向:改按关联观测的 ingest_seq 或 attempt 创建时间排序。

## L1–L4(低优先级,顺带处理)

- 状态：✅ 全部修复。L1 改用 `safe_add_column/safe_drop_column`；L2 使用 `ANSICH_EXECUTION_CONTEXT_KEY`；L3 通过 0012 migration 拆为 `usage_json` 与 `response_metadata_json` 并 backfill；L4 在 worker 分配 step sequence 前 flush task，同时在 service 标注投影追平前提。

- **L1** 迁移 0007 自写 `_add_column`,应复用 `migrations/_helpers.py::safe_add_column`(行为等价,约定不符)。
- **L2** `runtime/runs/worker.py` goal-continuation 处用字面量 `"__ansich_execution_context"`,应使用已导入的 `ANSICH_EXECUTION_CONTEXT_KEY`。
- **L3** `AnsichLlmAttemptRow.usage_json` 同时存 `usage` 与 `response_metadata`,列名误导;后续迁移时拆列或改名。
- **L4** `get_max_step_seq` 假设"重建 execution context 时该 task 的 step 投影已追平";当前每 run 只建一次 context 所以安全,但任何未来 crash 恢复/run resume 路径在投影滞后时会分配重复 `step_seq` → 唯一约束冲突 → poison job。应在代码注释标注该前提。
