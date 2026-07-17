# Phase 4 — 上下文谱系与压缩

## 1. 交付目标

本阶段把 Phase 2/3 的 ContextSnapshot 和 ContentBlock 扩展成可查询的有向谱系。开发者能够从一个模型可见块向后追到 user input、Agent output、Tool raw result、memory、skill 或 middleware producer，也能够向前找出哪些后续 Step 可能看见该块或其衍生物。

这里记录的是“可见/可能暴露”，不是模型注意力或真实因果依赖。所有正向 API 和 UI 都必须使用 `possible_exposure`，不得显示“导致了后续决策”。

## 2. 谱系覆盖范围

为下列 producer/transformer 增加显式 probe：

- Gateway 接收的 user input 和 hidden system input；
- lead/subagent AIMessage；
- Phase 3 的 raw/visible Tool result；
- durable/dynamic context middleware 注入；
- memory 注入和 memory extraction system operation；
- skill catalog、skill activation正文和动态 Tool schema；
- uploads/vision 转换；
- system-message coalescing；
- summarization 的 source、preserved、removed、summary；
- Tool sanitization、truncation、externalization 和 error normalization。

每个变换点必须产生 `content.produced` 或 `context.compressed` Observation，不允许只在下一次 snapshot 中通过文本相似度猜来源。

## 3. Provenance sidecar

新增 Task-local `ContextProvenanceRegistry`，键使用 message occurrence identity，而不是仅 message ID：

```text
(task_id, message_id_or_generated_id, content_part_ordinal, occurrence_seq)
    -> ContentBlockRef(block_id, producer_obs_id, kind)
```

Registry 作为 `AnsichExecutionContext` 一部分显式传播。不要把完整 provenance 写进 `BaseMessage.additional_kwargs`，避免泄漏给 provider、checkpoint、RunJournal 或前端；如果跨 checkpoint 必须保留最小引用，只允许写 `ansich_block_ref` 的非敏感 UUID，并由序列化器在发给 provider 前剥离。

message 没有稳定 ID 时，在进入 Task context 时分配 occurrence ID，并按对象生命周期/ordinal 维护 sidecar。相同 message 被复制、coalesce 或 summarize 后必须产生新 block 和 derivation，不能沿用原 block ID。

## 4. Derivation 模型

`ansich_content_block_derivations` 扩展字段：

```text
derived_block_id
source_block_id
transform_kind
transform_version
source_role          // source | preserved | removed | supporting
established_obs_id
ordinal?
```

`transform_kind` 固定枚举：`sanitized`、`truncated`、`externalized`、`coalesced`、`compressed`、`memory_injected`、`skill_injected`、`vision_converted`、`copied`、`unknown`。新增枚举需升级 Observation schema/projector version。

边方向固定为 `derived -> source`。建立两个索引 `(derived_block_id, source_block_id)` 和 `(source_block_id, derived_block_id)`；backward lineage 按边方向查询，forward exposure 走反向索引。Projection 在写边前做 self-edge 拒绝；对外查询还要有 visited set 防御历史坏数据形成环。

## 5. Summarization 的精确采集

修改 `SummarizationMiddleware` 的决策点，在调用 summary model 前冻结以下 inventory：

```text
source_blocks[]       // 参与压缩的全部 occurrence，保持原顺序
preserved_blocks[]    // 压缩后原样保留
removed_blocks[]      // 从 active context 移除
summary_operation_id
before_snapshot_stats
```

summary model response 是 system operation attempt；产生 summary ContentBlock 后发 `context.compressed`，payload 包含上述 block IDs、after stats、algorithm/version 和因果 Observation。summary block 对每个 source block 建 `compressed/source` 边；preserved/removed inventory 使用 typed membership table，而不是 JSON ID 数组作为唯一事实来源。

如果 summary LLM 成功但 provenance Observation 写入失败，Agent 仍继续，Ansich 标记 affected Task degraded。下一次 ContextSnapshot 看到无法解析来源的 summary 时保存完整块并标记 `unknown_origin=true`，不能假造 source 边。

system coalescing 同样记录输入 system blocks 的顺序和输出 block。coalescing 不能通过“相同字符串”合并 provenance。

## 6. 数据库增量

新增：

- `ansich_context_compressions(compression_id, task_id, operation_id, summary_block_id, before_tokens, after_tokens, algorithm, algorithm_version, source_obs_id)`。
- `ansich_context_compression_items(compression_id, block_id, ordinal, disposition)`，`disposition` 为 `source/preserved/removed`，唯一 `(compression_id, disposition, ordinal)`。
- `ansich_block_producers(block_id, producer_kind, producer_entity_id, producer_obs_id)`，使 producer 查询无需扫描 Observation JSON。
- 为 snapshot membership 增加 `(content_block_id, snapshot_id)` 反向索引，用于 exposure。

ContentBlock payload 删除与结构删除分离。Phase 4 只支持 `payload_status=available/missing`；Phase 11 加 retention tombstone。所有谱系响应即使 payload 不可用也返回结构、hash、kind 和 producer。

## 7. 谱系查询算法

在独立 core 实现纯 BFS traversal，repository 只提供批量邻接查询：

```text
lineage(block_id, direction, max_depth, max_nodes)
```

使用逐层批量 `WHERE id IN (...)`，兼容 SQLite/PostgreSQL，不依赖两种数据库 JSON/recursive CTE 差异。返回节点、边、depth、`truncated`、`truncation_reason` 和 `unknown_gaps`。默认 `max_depth=8`、`max_nodes=500`；配置有硬上限，客户端不能请求无限遍历。

Backward：block → sources → producer entities/observations。

Forward exposure：block → all derived blocks → `ansich_context_snapshot_items` → later Steps。只保留 snapshot evidence time 晚于或因果位于 source 之后的结果；并行/时钟不确定时保留结果并标记 `ordering=unknown`，不能据时间戳误删可能暴露。

对重复路径进行节点去重，但边全部保留；响应中列出每个 Step 看见的具体 descendant block 和 snapshot ordinal。

## 8. API 与 UI

新增：

```text
GET /api/ansich/content-blocks/{block_id}/lineage?direction=backward&depth=&nodes=
GET /api/ansich/content-blocks/{block_id}/exposures?depth=&nodes=
GET /api/ansich/context-snapshots/{snapshot_id}
GET /api/ansich/context-compressions/{compression_id}
```

lineage 响应必须显式包含 `semantic="provenance"`；exposures 包含 `semantic="possible_exposure"`。达到限制返回 200 + `truncated=true`，不是悄悄截断。起点不存在为 404；结构存在但 raw payload 已无则仍为 200。

Task 的 Context & Lineage 标签先渲染 snapshot inventory，再按用户点击加载局部图。默认不一次性下载整个 Task 图。图节点以 kind/producer/bytes/tokens 显示，edge 显示 transform kind；unknown gap 和 removed block 有独立视觉状态。提供表格 fallback，保证大图和无障碍场景仍可用。

## 9. TDD 测试矩阵

- registry：相同文本不同 occurrence、无 message ID、message copy、跨 async/thread context 隔离。
- transforms：sanitize、truncate、externalize、coalesce、memory/skill/vision 注入的边和 producer。
- compression：source/preserved/removed 严格顺序、summary failure、Observation failure、连续两次压缩。
- traversal：diamond graph、cycle 防御、depth/node limit、missing node、payload missing、正反向索引查询。
- exposure：直接可见、通过 summary 可见、多个 descendant、并行 ordering unknown、未出现在 snapshot 的 block 不返回。
- performance：500-node 上限内查询数量按 depth 批量增长，禁止 N+1 每节点 SQL。
- API/UI：truncated、unknown gap、possible_exposure 文案、lazy graph、raw payload 不被自动读取。
- replay：乱序写入 derivation 与 block，重放后边集合一致。

## 10. 完成条件

- 任一 effective ContextSnapshot 都能按 ordinal 重建 inventory。
- summary 对 source/preserved/removed 的记录是 typed、ordered、可重放的。
- raw Tool result 到 visible result、summary 及后续 exposure 的链路可双向查询。
- Forward 查询只宣称 possible exposure。
- 超限、缺失、被删除和采集失败均以结构化状态返回，不表现为空图即“无影响”。
