# Phase 11 — 生产韧性、重放与保留策略

## 1. 交付目标

本阶段把此前单进程可运行链路加固为生产可运维系统：bounded queue 的损失可见、BatchWriter 具备清晰原子性、projector 支持 PostgreSQL 多 worker lease、poison job 隔离、projection 可按版本重放、payload/structure 独立 retention、raw read 强审计。

Fail-open 不等于静默失败。任何不能采集、持久化或投影的区间都要进入 health/lost ranges；读取方不得把 lost range 中的 absence 解释为“没有发生”。

## 2. Collector 与 BatchWriter 加固

固定进程内状态机：

```text
starting -> healthy -> degraded -> recovering -> healthy
                         \-> failed
healthy/degraded -> shutting_down -> stopped
```

Collector 每个 producer instance 维持 accepted/dropped 序号、queue high-water mark、serialization failures 和 last successful flush。`record()` 仍不可阻塞；高优先级 terminal Observation 也不允许挤掉旧项目造成不可解释重排，而是正常 drop 并标范围。v1 不实现磁盘 spool/WAL，进程 crash 前未 flush 数据明确属于 known limitation。

BatchWriter 每批原子写 payload + observation + all projector jobs。对 transient DB 异常做有界指数退避且不占 Agent 调用栈；队列持续增长到 capacity 后 drop。对 schema/serialization 永久错误直接隔离该 item 并继续后续 item，避免一个 poison envelope 阻塞整个 queue。

`flush_task` barrier 以 collector sequence 为界，不要求其他 Task 全部 drain。返回 `{persisted_through, lost_ranges, timed_out}`；terminal Run 不等待超过配置 timeout。

## 3. Projection lease 与多 worker

PostgreSQL claim transaction：

1. `SELECT ... WHERE status in (pending,retry) AND available_at<=now AND lease expired ORDER BY job_id FOR UPDATE SKIP LOCKED LIMIT N`。
2. 同事务更新 `status=leased`、lease owner/expiry、attempts。
3. 每个 job 在独立或有界 batch transaction 执行 projector + read model 更新，成功标 completed。
4. 失败写 error、next retry；达到 max attempts 标 failed 并继续其他 jobs。

SQLite 遵守现有单 Gateway worker 约束，只运行一个 projector loop，不模拟 `SKIP LOCKED`。lease 过期 job 可由新 worker 领取；projector 幂等保证旧 worker 晚提交不会双写。更新 job 完成状态时带 lease owner/version compare，stale worker 不能覆盖新 lease 结果。

poison job 写 `ansich_projection_errors`，产生 observability degradation Alert 并把 affected Task read model 标 failed；不阻塞其他 Task 或后续 ingest sequence。

## 4. Watermark、lag 与 lost range

分别维护：

- process-local collector health；
- DB writer watermark（每 producer persisted sequence）；
- projector watermark（每 projector/version complete through ingest sequence）；
- failed/leased/pending job counts；
- known/unknown lost ranges。

全局 watermark 不能掩盖单 Task failure。Task API 计算与该 Task 相关的 failed jobs 和 loss intersection；无法关联的 process-wide loss 标 `scope=producer/unknown`。

`lag_ms` 使用最新待投影 Observation 的 recorded_at 与当前时间；无 pending 但有 failed 时 status 仍 failed。health endpoint 合并 app.state 进程数据和数据库数据；DB 查询失败时仍返回 process-local 结果和 `database.status=unreachable`。

## 5. Versioned replay

新增 admin CLI 或内部命令模块 `deerflow.ansich.replay`，不在普通 API 暴露任意 projector 执行。命令参数：projector name/version、task/time/ingest range、dry-run、replace read models。

Replay 流程：

1. 验证 target projector 已注册且 schema 兼容。
2. 为目标 Observation 创建新 version jobs，唯一 `(obs_id, projector, version)`。
3. 若 replace，先在 transaction/maintenance lock 下清理该 version 管理的 projection rows；Observation/Payload 不删。
4. 执行并输出 counts、errors、watermark 和 determinism digest。
5. 对同 Observation 集第二次重放，read model canonical digest 必须相同。

不同 resolver/projector version 结果可并存；Current Belief/read model 通过 active version config 选择。切换 active version 应是显式管理动作并审计，不能部署代码后静默改变历史解释。

## 6. Retention 与删除

配置分离：

```yaml
ansich:
  retention:
    raw_payload_days: 7
    observation_days: 30
    structural_days: 90
    cleanup_batch_size: 500
```

owner/thread 删除是强删除：按 Scope 找到 Tasks，删除 Observation、Payload、projections、relations、read models 和 raw-read audit 中受保护引用，遵守 FK 顺序并测试无孤儿。此路径优先于时间 retention。

时间 retention 先删 raw payload body，保留 `retention_tombstone={deleted_at,policy,sha256,byte_size}`，使 lineage 仍知道曾采集。Observation retention 到期后，任何依赖它的 projection 必须删除或标 evidence expired；不能保留看似有证据却无法解释的 Current Belief。Structural retention 最后清理 Entity/Relation。

cleanup 使用小 batch、可恢复 cursor 和 DB lease，避免长事务锁住 Run 写入。SQLite/PostgreSQL 均测试。

## 7. Raw payload read 审计

所有 raw endpoint 先验证 admin 和 subject，再在同一安全流程复用既有 `operator.action_requested/succeeded/failed` Observation，令 `action_kind=raw_payload_read`；内容包括 actor user ID、payload ID、purpose、request correlation 和时间，不记录 payload 本身。拒绝请求进入安全审计日志，但不得为了记录 denied 而先读取 payload。

与普通 collection fail-open 不同，raw read 审计是安全控制：如果无法持久化 access audit，raw payload 读取 fail-closed 返回 503；metadata/inventory API 仍可读。响应加 `Cache-Control: no-store`，前端不把 raw body 放 TanStack 长期 cache/localStorage。

bulk raw export 不在 v1 范围；单次读取有 size limit 和 content disposition 安全规则。

## 8. Shutdown 与恢复

Gateway 关闭顺序：停止新 record → stop heartbeat/assessor timers → terminal/task barriers → drain writer 有界 timeout → stop claim 新 projection → 完成/释放当前 lease → close DB。每步有独立 timeout 和 health/log 结果，总时间不超过 Gateway graceful shutdown budget。

启动时：

- 扫描过期 projector leases 并重置 retry；
- 与 RunManager orphan reconciliation 结果关联，给未终态 Ansich Task 写硬/unknown evidence，不自行宣称 completed；
- 恢复 producer health，写前次无法落库的 process crash 信息仅当有外部证据，不凭空构造 lost range；
- 验证 active projector/resolver version 存在。

## 9. API 与运维 UI

扩展 `/api/ansich/health`：component status、queue depth/capacity/high-water、writer success/failure、projector jobs/lag/watermarks、lost ranges、retention last run、active versions。

Operations 页面增加 Observability Health 面板。degraded/failed 时 Task 列表顶部显示全局 banner；每个 Task 仍显示自身关联状态。提供 failed job 详情和 projector/version，但 v1 UI 不直接提供“跳过 job”破坏性按钮。Replay 通过受控 CLI 运行。

## 10. TDD 与故障注入

- queue：capacity、高水位、跨线程、serialization poison、terminal barrier、shutdown race。
- writer：DB disconnect、deadlock/locked、partial payload failure、retry 恢复、duplicate batch。
- projector：两 PostgreSQL worker 竞争、lease 过期/stale completion、poison isolation、SQLite single worker。
- health：DB unreachable、pending lag、failed 无 pending、known/unknown loss、Task scoped intersection。
- replay：target filter、version 并存、replace、两次 digest 一致、late Observation。
- retention：payload tombstone、Observation expiry evidence、owner/thread hard delete、batch resume、FK 无孤儿。
- raw audit：admin/普通用户、audit DB failure fail-closed、no-store、oversized payload。
- shutdown/restart：有活动 Task、writer backlog、projector transaction、orphan Run reconciliation。
- performance：目标 ingest rate 下 Agent p95 延迟增量在约定预算内，队列不会无界增长。

## 11. 完成条件

- PostgreSQL 多 Gateway worker 不会重复投影或互相覆盖 lease；SQLite 明确保持单 worker。
- poison job 不会阻塞无关 Observation，并能在 health/Alert 定位。
- 相同 Observation + projector version 重放两次得到相同 digest。
- raw/structural retention 和 owner 删除均无悬空引用；payload 缺失有 tombstone。
- raw read 在审计不可用时拒绝，普通 collection 故障仍不影响 Agent。
- 进程 crash 无 durable spool 的 loss 限制在文档和 health 中明确，不宣称绝对 lossless。
