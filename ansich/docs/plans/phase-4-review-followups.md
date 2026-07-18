# Phase 4 代码评审跟进项

来源:commit `a596a310`(Phase 4 上下文谱系与压缩)+ `28a4029c`(投影恢复加固)的代码评审(2026-07-18)。编号带 `M`(中)/`L`(低)优先级;修复一项后同步更新总览表和该项"状态"行,保留原始诊断记录。

## 状态总览

| 编号 | 摘要 | 状态 | 修复时间 | Commit |
| ---- | ---- | ---- | -------- | ------ |
| M1 | 带 `ansich_block_ref` 的块每次模型调用重复写入含正文的 `content.produced` | ⬜ 未修复 | — | — |
| M2 | 依赖未落地的投影 job 无限 250ms 重试,永不进入 failed、health 不降级 | ⬜ 未修复 | — | — |
| M3 | BFS 在 `depth == max_depth` 层丢弃两端都在结果集内的边且不标记截断 | ✅ 已修复 | 2026-07-18 | `bbc26e84` |
| L1 | freeze 的 `id()` 身份匹配对 trim 部分副本整体失败,整次压缩记录被放弃 | ⬜ 未修复 | — | — |
| L2 | Ansich 关闭或无 execution context 时内部 marker 不在 provider 调用前剥离 | ⬜ 未修复 | — | — |
| L3 | `_pending_content_derivations` 任务级只增不减;前端压缩列表只取当前 timeline 页 | ⬜ 未修复 | — | — |

## M1. 带 `ansich_block_ref` 的块每次模型调用重复写入含正文的 `content.produced`

- 状态:⬜ 未修复。
- 位置:`backend/packages/harness/deerflow/ansich/middleware.py::_record_captured_request` 的 block_ref 分支(`block_ref` 存在时跳过 `resolve_content_occurrence`,`resolution` 保持 `None`)。
- 现状:无 registry 解析就没有 `should_emit` 去重 —— 每个物理 attempt 都会为 block_ref 项 emit 一条 `content.produced`,`obs_id=new_id()`、`source_event_id=f"attempt:{attempt_id}:content:{ordinal}"`(每 attempt 唯一,collector 的 source-event 去重失效),payload 经 `**block.model_dump()` 携带完整正文。受影响块:coalesced 系统提示(**每次模型调用都存在**,且通常是上下文里最大的块 —— 完整 system prompt + skills catalog)、压缩后的 durable-context data block、跨 checkpoint 复用的 summary 消息。ContentBlock / producer / derivation 投影本身幂等(重复行 no-op),blob 层对 canonical bytes 去重,但 observation journal 每次调用新增一行完整 payload(inline 或 externalize 到 `ansich_payloads`)加一个投影 job。方向与 Phase 2 H2(快照写放大治理)相反;`derivation_sources` 也随每条重复观察重复投递。
- 方向:block_ref 项同样走确定性解析获得幂等 emit-once 语义 —— 例如用 `source_identity=f"block-ref:{block_ref}"` 调 `resolve_content_occurrence`(确定性 obs_id / source_event_id,durable 确认后 skip);或至少把 payload 正文换成 hash 引用。配一条"同一 block_ref 连续两个 attempt 只落一条观察"的回归测试。
- 归属:Phase 5 前完成(心跳/预算会提高模型调用频度,按调用线性放大)。

## M2. 依赖未落地的投影 job 无限 250ms 重试

- 状态:⬜ 未修复。
- 位置:`backend/packages/harness/deerflow/ansich/persistence/sql.py::_release_projection_job` 的 `_ProjectionDependencyPending` 分支(`job.attempts = max(0, job.attempts - 1)`、`available_at = now + 250ms`、status 回 `pending`)。
- 现状:dependency-pending 不计入 `projector_max_attempts`,永不转 `failed`。依赖**永久**缺失时该 job 每 ~250ms 空转一次:DB 查询 churn、`failed_jobs` 不增长、health 不降级、UI 的"投影不可用"提示不触发 —— 与"采集失败均以结构化状态返回,不表现为健康"的阶段完成条件冲突。永久缺失可达:① `record_batch` 部分接受 —— freeze 的某条 content 观察被有界队列丢弃而 `context.compressed` 已入队,该压缩的源块不会再被重试(freeze 观察只随该次批量提交一次),`_project_context_compression` 永久 spin;② `task.created` 丢失时整个 Task 的所有 job 同状;③ 历史坏数据(`derivation_sources` 指向从未存在的块)。注意大多数 registry 管理的源块**能**自愈(durable 确认前每次请求 re-emit),所以场景窄,但一旦发生就是静默永久空转。
- 方向:为 dependency-pending 引入独立上限(次数或时限,如超过 5 分钟仍未满足则转 `failed` 并保留 `last_error` 证据),`failed` 后由既有 `retry_failed_projections` 无损恢复;或依赖检查咨询 lost-range 记录,已确认丢失的依赖直接判定不可满足。配"依赖永不出现的 job 最终进入 failed 并计入 health"的回归测试。
- 归属:Phase 5 前完成(预算/心跳观察会增加依赖链条数量)。

## M3. BFS 在 `depth == max_depth` 层丢弃两端都在结果集内的边

- 状态:✅ 已修复(2026-07-18,commit `bbc26e84`)。按 TDD 修复:新增 diamond 图在最深层包含 cross-edge 的回归测试;深度边界在退出前保留两端均属于 `visited | unresolved` 的边,只有发现越界新邻居时才标记 `max_depth` 截断。以下为原始诊断记录。
- 位置:`backend/packages/ansich/ansich/lineage.py::traverse_content_lineage` —— `if depth >= max_depth: ... break` 发生在 `traversable` 边收集之前。
- 现状:已实证(diamond A→B/C→D 加 cross-edge D→B,`max_depth=2`):返回节点 {A,B,C,D},但 D→B 边丢失,且该情形下 `unseen_neighbors` 为空导致 `truncated=False` —— 图静默缺边。违反计划 §7"对重复路径进行节点去重,但边全部保留";对责任链审计,静默缺边比显式截断更有害。压缩谱系里"后期 summary 引用早期块"正是会在最深层出现 cross-edge 的形态。
- 方向:把最深层 `level_edges` 中两端均已在 `visited | unresolved` 内的边先记入 `edges_by_key` 再 break(此情形不算截断;仅存在越界新邻居时才标 `max_depth`)。补"最深层 cross-edge 保留"回归测试。
- 归属:立即修复(纯 core 查询逻辑,改动小)。

## L1. freeze 的 `id()` 身份匹配对 trim 部分副本整体失败

- 状态:⬜ 未修复。
- 位置:`backend/packages/harness/deerflow/ansich/compression.py::_selected_message_ordinals`(按 `id(message)` 匹配,未命中即 `raise ValueError`)+ `summarization_middleware.py::_source_messages_for_summary`(经父类 `_trim_messages_for_summary` → `trim_messages(allow_partial=True)`)。
- 现状:`trim_messages` 对 list-content 边界消息做部分保留时会构造**新对象**,该对象不在 `state["messages"]` 里 → `ValueError` → `_freeze_ansich_compression` 捕获后放弃**整次**压缩记录(仅日志)。`config.example.yaml` 默认 `trim_tokens_to_summarize: 15564`,该路径默认可达;触发条件是多段内容消息(vision 等)恰在 trim 边界。失败只损失观察(Agent fail-open 不受影响),但一旦上下文形态稳定命中,该 Task 的压缩谱系会持续整体缺失。
- 方向:匹配失败降级为"跳过未匹配消息、compression 标 `incomplete`",而非放弃全部;或对未命中的对象按 `message.id` 兜底匹配。配"部分 trim 副本不放弃整个 inventory"的回归测试。
- 归属:Phase 5 前完成。

## L2. Ansich 关闭或无 execution context 时内部 marker 不剥离

- 状态:⬜ 未修复。
- 位置:`backend/packages/harness/deerflow/ansich/middleware.py::AnsichAttemptMiddleware.wrap_model_call / awrap_model_call`(`execution is None or call is None` 时直接 `handler(request)`,跳过 `_request_without_ansich_metadata`);coalescing / durable / dynamic / skill-activation / view-image 中间件无条件写 `ansich_content_kind` / `ansich_producer_kind` / `ansich_block_ref`。
- 现状:剥离仅在 execution + call 同时存在时发生。`ansich.enabled=false` 时 marker 留在 additional_kwargs 进入 provider adapter —— 主流 adapter 对 System/Human 消息忽略 additional_kwargs,实际泄漏风险低(marker 非敏感;外部伪造已由 Gateway strip 防住),但与设计文档"attempt adapter 在 provider 调用前移除内部 marker"的承诺不一致。附带两点:① `view_image` 的 marker 经 state 更新持久化进 checkpoint(其余注入均为请求级 override);② coalescing 观察者对 list-content 系统消息用 `_flatten_content` 整体 hash,与 serializer 按 part 的 hash 不一致,多段系统消息的 `coalesced` 源边会指向不出现在任何快照的展平块(谱系断点,纯字符串系统消息不受影响)。
- 方向:marker 写入 gate 在 execution context 存在与否上,或 coalescing 等注入方自行在无 Ansich 时跳过 marker;`view_image` 改为请求级注入或接受并记录该例外;coalescing 观察者对多段内容按 part 采集。
- 归属:Phase 5 前完成(风险低,但与既有承诺不一致,拖久了会被当成契约)。

## L3. 两处小的资源/完整性遗留

- 状态:⬜ 未修复。
- 现状:
  1. `AnsichExecutionContext._pending_content_derivations` 只增不减:dynamic reminder 跨日变化、durable data block 内容变化都会产生新的 `derived_block_id` 条目,任务级生命周期内无清理路径。量级小(每模型调用至多几条),长任务缓慢累积。
  2. 前端 Task 详情页 `compressionIds` 只从**当前** timeline 分页提取(`page.tsx` 过滤 `context.compressed`),分页窗口外的压缩不会出现在 Context & Lineage 面板;长任务多次压缩时列表不完整,且无"更多"提示。
- 方向:① 为 pending derivations 设置容量上限或在 derivation 落库确认后清除;② 压缩列表改为独立 API(按 task 查询 `ansich_context_compressions`)而非 timeline 派生。
- 归属:Phase 5(①)/ Phase 6 UI 迭代(②)。

## 评审中确认无需跟进的点(留档)

- `resolve_content_occurrence` 幂等(确定性 block/obs/source-event ID),freeze 失败不污染 registry;重复 emit 由 source-event 去重收敛。
- 连续压缩仅复用 **durable** 确认的 summary block,未确认时保守走 `unknown_origin`,不伪造边 —— 符合计划 §5。
- 迁移 0014 upgrade / backfill / downgrade 幂等,backfill 有 ContextState 环防御;`retry_failed_projections` 持锁、非破坏,快照迟到成功同时修复 attempt 与已关闭 Step 指针。
- 新增 API 全部 `require_admin_user`,lineage/snapshot/compression 仅 metadata,payload 路由维持日志 + `no-store`;Gateway 剥离外部伪造 marker(`services.py`)。
- 后端 `tests/ansich` 142 项在评审机复跑通过;测试矩阵覆盖计划 §9 的 diamond/cycle、depth/nodes 截断、按层批量查询(防 N+1)、unknown gap、连续压缩、写拒绝 fail-open、SQLite 生命周期等主path。
