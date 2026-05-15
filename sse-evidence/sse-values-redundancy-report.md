# SSE values 冗余传输分析报告

## 结论

在 long task 的 SSE wire capture 中，`values` 是响应体最大的事件类型。`values` 按 LangGraph 语义携带每个 step 后的完整 graph state；在当前 state 中，`messages` 是最大字段，因此每个 `values` frame 都会重新发送完整历史消息快照。

这不是 SSE 编码层面的异常，而是当前 stream mode 组合放大出的传输问题：聊天 UI 同时订阅了实时消息流和完整 state 快照，导致 `values.messages` 重复携带历史消息。

实验移除 `values` 后，wire 层确认不再出现 `event: values`，同类 long task 的 SSE body 从 `6,560,984 bytes` 降到 `1,642,214 bytes`，减少 `4,918,770 bytes`，约 `75.0%`。两次任务输出内容不完全一致，因此该比例不能作为严格 A/B 的唯一结论；但它足以证明 `values` 是可移除的主要冗余来源。

## 证据来源

本报告使用两组 wire capture 和 gateway profile：

| 场景 | 目录 | raw SSE | summary | gateway log |
|---|---|---|---|---|
| long-task，包含 `values` | `logs/sse-evidence/long-task/` | `raw.sse` | `raw-summary.md` | `logs/sse-profile-report-long-task.log` |
| long-task-no-value，移除 `values` | `logs/sse-evidence/long-task-no-value/` | `raw.sse` | `raw-summary.md` | `logs/sse-profile-report-long-task-no-value.log` |

两组 capture 都通过真实 HTTP SSE response 获取，并且 parser 结果满足：

```text
Parsed frame bytes == File bytes
Unparsed bytes == 0
```

## long-task raw summary

long-task 原始 wire capture：

```text
Source: logs/sse-evidence/long-task/raw.sse
File bytes: 6,560,984
Parsed frame bytes: 6,560,984
Unparsed bytes: 0
Total events: 898
```

curl metrics：

```text
http_code=200
size_download=6560984
time_total=111.382837
speed_download=58904
```

事件分布：

| Event | Count | Total Frame Bytes | Share | Avg Frame | P95 Frame | Max Frame | Total Data Bytes |
|---|---:|---:|---:|---:|---:|---:|---:|
| values | 7 | 4,872,647 | 74.27% | 696,092.43 | 720,048 | 720,048 | 4,872,343 |
| messages | 863 | 962,427 | 14.67% | 1,115.21 | 1,091 | 37,549 | 922,821 |
| updates | 21 | 725,675 | 11.06% | 34,555.95 | 37,072 | 677,793 | 724,742 |
| metadata | 1 | 147 | 0.00% | 147.00 | 147 | 147 | 103 |
| heartbeat | 5 | 65 | 0.00% | 13.00 | 13 | 13 | 0 |
| end | 1 | 23 | 0.00% | 23.00 | 23 | 23 | 4 |

关键观察：

- `values` 只有 `7` 个事件，却贡献 `4,872,647 bytes`，占总响应体 `74.27%`。
- `messages` 有 `863` 个事件，只贡献 `962,427 bytes`，占 `14.67%`。
- 单个 `values` frame 最大 `720,048 bytes`，远大于常规 `messages` frame。

## values 携带的内容

对 `values` 的 JSON payload 做 top-level field 拆分：

```text
Values events: 7
Decoded values events: 7
Parse errors: 0
Message count range in values: 137 -> 140
Last values message count: 140
```

字段分布：

| Field | Count | Total Bytes | Share | Avg Bytes | Max Bytes |
|---|---:|---:|---:|---:|---:|
| messages | 7 | 4,827,569 | 99.86% | 689,652.71 | 713,541 |
| thread_data | 7 | 3,647 | 0.08% | 521.00 | 521 |
| todos | 7 | 2,394 | 0.05% | 342.00 | 342 |
| artifacts | 7 | 504 | 0.01% | 72.00 | 72 |
| viewed_images | 7 | 14 | 0.00% | 2.00 | 2 |

这说明 `values` 的体积几乎完全来自 `messages`：

```text
values.messages bytes = 4,827,569
values total top-level field bytes ~= 4,834,128
messages share in values ~= 99.86%
```

## values 内部重复证据

逐个 `values` frame 观察，`messages` 数量只从 `137` 增长到 `140`，但每次都发送完整历史消息快照：

| # | Frame No | Event ID | Messages Count | messages Bytes | Frame Bytes |
|---:|---:|---|---:|---:|---:|
| 1 | 2 | `1778842828224-1` | 137 | 671,751 | 678,124 |
| 2 | 4 | `1778842828246-3` | 137 | 671,853 | 678,229 |
| 3 | 174 | `1778842878618-170` | 138 | 673,162 | 679,586 |
| 4 | 178 | `1778842878637-174` | 138 | 673,429 | 679,871 |
| 5 | 182 | `1778842878654-178` | 139 | 710,413 | 716,873 |
| 6 | 890 | `1778842939255-884` | 140 | 713,420 | 719,916 |
| 7 | 894 | `1778842939274-888` | 140 | 713,541 | 720,048 |

连续 `values` 快照的 message id overlap：

| From -> To | Prev IDs | Current IDs | Overlap | Repeated Prev IDs |
|---|---:|---:|---:|---:|
| 1 -> 2 | 137 | 137 | 137 | 100.00% |
| 2 -> 3 | 137 | 138 | 137 | 100.00% |
| 3 -> 4 | 138 | 138 | 138 | 100.00% |
| 4 -> 5 | 138 | 139 | 138 | 100.00% |
| 5 -> 6 | 139 | 140 | 139 | 100.00% |
| 6 -> 7 | 140 | 140 | 140 | 100.00% |

首尾对比：

```text
first values messages: 137
last values messages: 140
overlap: 137
new since first: 3
```

按完整 message object 做 SHA256 指纹去重：

```text
message object occurrences across values: 969
unique exact message objects: 143
total message-object bytes across values: 4,826,593
unique exact message-object bytes: 717,964
duplicate exact message bytes: 4,108,629
duplicate exact byte share: 85.12%
```

因此，准确表述应该是：

> `values` 按完整 state 快照语义重复发送历史 `messages`。在该 long-task capture 中，`values` 的 `messages` 字段贡献了 `4.83 MB`，其中按 exact message object 计算有 `85.12%` 是跨 values frame 重复出现的历史消息对象。

## 当前项目 stream mode 策略现状

改造前，前端业务代码没有显式声明主聊天流的 stream mode。项目使用 `@langchain/langgraph-sdk/react` 的 `useStream`，SDK 会根据 UI 使用到的能力自动追踪并合并 stream mode：

- 读取 `thread.messages` 会追踪 `messages-tuple` 和 `values`。
- 注册 `onUpdateEvent` 会追踪 `updates`。
- 注册 `onCustomEvent` 会追踪 `custom`。
- 注册 `onLangChainEvent` 会追踪 `events`。

项目前端当前聊天 UI 使用了这些能力：

- `useStream<AgentThreadState>(...)` 初始化聊天流。
- `onUpdateEvent` 用于处理 summary、title 等 state update。
- `onCustomEvent` 用于处理 `task_running` 等业务事件。
- UI 读取 `thread.messages` 渲染实时消息。

因此改造前真实请求中出现：

```json
["messages-tuple", "values", "updates", "custom", "events"]
```

后端 gateway 的 worker 会将请求映射到 LangGraph `agent.astream(...)`：

- `messages-tuple` 映射为 LangGraph `messages`。
- `events` 当前 gateway 不支持，会跳过。
- `values`、`updates`、`custom` 透传。

对应 gateway profile：

```text
Run 6e225e87-8894-4ca6-96ea-357a1f41de31:
streaming with modes ['updates', 'messages', 'custom', 'values']
requested: {'events', 'updates', 'messages-tuple', 'custom', 'values'}
```

这个策略的问题是：`messages-tuple` 已经承担实时消息流职责，而 `values` 又发送完整 state，其中包含完整历史 `messages`。对于长任务，`values.messages` 会随着历史消息增长持续变大。

## 推荐策略

主聊天流应显式声明最小必要 stream mode：

```json
["messages-tuple", "updates", "custom"]
```

保留原因：

| Mode | 是否保留 | 原因 |
|---|---|---|
| messages-tuple | 保留 | 实时渲染 assistant/tool 消息，是聊天体验主通道 |
| updates | 保留 | 前端依赖 `onUpdateEvent` 处理 summary、title 和增量状态 |
| custom | 保留 | 前端依赖 `onCustomEvent` 处理业务事件，如 `task_running` |
| values | 移除 | 会发送完整 state，当前主要重复携带完整历史 `messages` |
| events | 移除 | 当前 gateway 已跳过，保留在请求里没有实际收益 |

本次实验已经将主聊天流强制为：

```text
requested: {'messages-tuple', 'custom', 'updates'}
actual LangGraph modes: ['messages', 'custom', 'updates']
```

## long-task-no-value 对比实验

long-task-no-value wire capture：

```text
Source: logs/sse-evidence/long-task-no-value/raw.sse
File bytes: 1,642,214
Parsed frame bytes: 1,642,214
Unparsed bytes: 0
Total events: 813
```

curl metrics：

```text
http_code=200
size_download=1642214
time_total=222.402071
speed_download=7383
```

响应 header 中的 run id：

```text
content-location: /api/threads/1aa43d59-cfdb-4cd9-a88a-3585086bd6fb/runs/3922f666-33ae-45e5-b1f9-1a9e86d25d09
```

gateway profile：

```text
Run 3922f666-33ae-45e5-b1f9-1a9e86d25d09:
streaming with modes ['messages', 'custom', 'updates']
requested: {'messages-tuple', 'custom', 'updates'}
```

事件分布：

| Event | Count | Total Frame Bytes | Share | Avg Frame | P95 Frame | Max Frame | Total Data Bytes |
|---|---:|---:|---:|---:|---:|---:|---:|
| messages | 776 | 836,689 | 50.95% | 1,078.21 | 1,221 | 1,726 | 801,089 |
| updates | 21 | 805,173 | 49.03% | 38,341.57 | 3,194 | 793,424 | 804,240 |
| heartbeat | 14 | 182 | 0.01% | 13.00 | 13 | 13 | 0 |
| metadata | 1 | 147 | 0.01% | 147.00 | 147 | 147 | 103 |
| end | 1 | 23 | 0.00% | 23.00 | 23 | 23 | 4 |

`values` 结果：

```text
Values events: 0
Decoded values events: 0
Parse errors: 0
```

gateway profile 与 wire parser 对齐：

```text
gateway total_bytes = 1,642,214
wire file bytes = 1,642,214
gateway total_events = 813
parser total_events = 813
values bytes = 0
values events = 0
```

## 对比结果

| 指标 | long-task with values | long-task-no-value |
|---|---:|---:|
| Requested modes | `messages-tuple, values, updates, custom, events` | `messages-tuple, updates, custom` |
| Actual modes | `updates, messages, custom, values` | `messages, custom, updates` |
| Wire bytes | 6,560,984 | 1,642,214 |
| Total events | 898 | 813 |
| values events | 7 | 0 |
| values bytes | 4,872,647 | 0 |
| messages bytes | 962,427 | 836,689 |
| updates bytes | 725,675 | 805,173 |

传输体积变化：

```text
6,560,984 - 1,642,214 = 4,918,770 bytes
4,918,770 / 6,560,984 = 75.0%
```

解释：

- 移除 `values` 后，wire 层 `event: values` 完全消失。
- 原 long-task 中 `values` 本身贡献 `4,872,647 bytes`，几乎等于两组实验的总差值。
- 这证明主聊天流不订阅 `values` 可以直接移除最大冗余来源。

注意：两次 capture 的 prompt 和模型输出不完全相同，不能把总 bytes 差异解释成严格唯一因果；但 `values bytes: 4,872,647 -> 0` 是直接由 stream mode 变化导致的确定结果。

## 新暴露的问题

移除 `values` 后，剩余主要体积来自：

| Event | Bytes | Share |
|---|---:|---:|
| messages | 836,689 | 50.95% |
| updates | 805,173 | 49.03% |

其中 `updates` 出现了单个大 frame：

```text
updates max frame = 793,424 bytes
```

这说明 `values` 问题解决后，下一步需要分析 `updates` 是否也在某些节点更新中携带了大字段或完整消息片段。当前优化优先级应为：

1. 默认主聊天流移除 `values`。
2. 保留 `messages-tuple + updates + custom` 满足现有 UI。
3. 继续拆解 `updates max frame` 的 payload 来源。

## 建议落地

主聊天流默认策略：

```ts
const CHAT_RUN_STREAM_MODES = [
  "messages-tuple",
  "updates",
  "custom",
] as const;
```

为了避免 SDK 自动追踪 `thread.messages` 时重新加入 `values`，需要在最终 `client.runs.stream(...)` 发出请求前强制覆盖 stream mode。仅在 `thread.submit(...)` 里显式传 mode 不够，因为 SDK 会把显式 mode 与内部追踪 mode 合并。

最终目标：

```text
request stream_mode: ["messages-tuple", "updates", "custom"]
worker actual modes: ["messages", "custom", "updates"]
raw SSE values events: 0
```

## 报告结论

long-task wire capture 证明：

- `values` 是原始 SSE response 的最大组成部分，占 `74.27%`。
- `values` 中 `messages` 字段占 `99.86%`。
- `values.messages` 在连续 state 快照中大量重复；按 exact message object 计算，重复字节占 `85.12%`。
- 当前聊天 UI 不需要在实时 SSE 主路径持续接收完整 `values` 快照。
- 改为显式 `messages-tuple + updates + custom` 后，wire 层 `values` 归零，总传输体积显著下降。

因此，建议将默认聊天 SSE 策略固定为 `messages-tuple + updates + custom`，把 `values` 限制在调试、状态检查或明确需要完整 state 快照的场景中。
