/** The page's own strings. The host hands the surface a locale; it shares no dictionary. */

import type { HealthDiagnostic, HealthResponse } from "./contracts";

export interface DiagnosticCopy {
  title: string;
  detail: string;
  remedy: string | null;
}

export interface Messages {
  title: string;
  empty: string;
  attemptsTruncated: string;
  coverage: string;
  refresh: string;
  hint: string;
  laneSystem: string;
  laneToolSchema: string;
  laneMemory: string;
  laneSkill: string;
  laneUser: string;
  laneAssistant: string;
  laneToolResult: string;
  laneSummary: string;
  laneMiddleware: string;
  laneAttachment: string;
  laneUnknown: string;
  lowerBound: string;
  composition: string;
  compression: string;
  snapshot: string;
  retryAttempt: string;
  total: string;
  members: string;
  sortContext: string;
  sortShare: string;
  memberUnprojected: string;
  incompleteNote: string;
  unanchored: string;
  block: string;
  residence: string;
  firstSeen: string;
  lastSeen: string;
  removedBy: string;
  continuesIn: string;
  removalUnrecorded: string;
  stillPresent: string;
  preservedBy: string;
  summaryOf: string;
  positionedBefore: string;
  compressionScope: string;
  removed: string;
  preserved: string;
  summaryBlock: string;
  summaryBlockUnknown: string;
  loading: string;
  loadFailed: string;
  tasks: string;
  noTasks: string;
  threadLabel: string;
  taskLabel: string;
  load: string;
  taskKindLead: string;
  taskKindSubagent: string;
  recordingOff: string;
  dropped: (count: number) => string;
  /* composition bar: 100% is the model's context window */
  compositionWindow: (capacity: string) => string;
  compositionRequest: string;
  used: string;
  free: string;
  overflow: (percent: string) => string;
  membersOfRequest: string;
  /* console: tabs and the task index */
  lede: string;
  tabTasks: string;
  tabHealth: string;
  tabBoard: string;
  noTaskSelected: string;
  backToList: string;
  searchPlaceholder: string;
  searchNotFound: (id: string) => string;
  allKinds: string;
  allOutcomes: string;
  outcomeRunning: string;
  outcomeCompleted: string;
  outcomeFailed: string;
  outcomeAborted: string;
  range24h: string;
  range7d: string;
  rangeAll: string;
  onlyCompactions: string;
  onlyIncomplete: string;
  groupByThread: string;
  flat: string;
  colTask: string;
  colThread: string;
  colStarted: string;
  colDuration: string;
  colSteps: string;
  colCompactions: string;
  colInventory: string;
  colPeak: string;
  colOutcome: string;
  openBoard: string;
  openInChat: string;
  summaryTasks: (count: number) => string;
  summaryThreads: (count: number) => string;
  summaryRunning: (count: number) => string;
  summaryCompactions: (count: number) => string;
  summaryIncomplete: (count: number) => string;
  onThisPage: string;
  emptyList: string;
  showAllTime: string;
  pageInfo: (from: number, to: number, total: number, perPage: number) => string;
  retries: (count: number) => string;
  inventoryComplete: string;
  inventoryIncomplete: (count: number) => string;
  runningFor: (duration: string) => string;
  tasksInThread: (count: number) => string;
  latest: string;
  peakOfWindow: (percent: string) => string;
  peakStackTitle: string;
  justNow: string;
  minutesAgo: (count: number) => string;
  hoursAgo: (count: number) => string;
  daysAgo: (count: number) => string;
  seconds: (count: number) => string;
  minutes: (count: number) => string;
  hoursMinutes: (hours: number, minutes: number) => string;
  /* health */
  recording: string;
  notRecording: string;
  recordingDisabled: string;
  database: string;
  tablePrefix: string;
  lastWrite: string;
  lastEvent: string;
  uptime: string;
  never: string;
  refreshedAt: (time: string) => string;
  queueDepth: string;
  flushEvery: (ms: number) => string;
  accepted: string;
  sinceStart: string;
  written: string;
  lastBatch: (events: number, ms: number) => string;
  noBatchYet: string;
  droppedTile: string;
  lastDropAt: (time: string) => string;
  noDrops: string;
  writeFailures: string;
  writeFailuresSub: string;
  estimator: string;
  readCap: (count: number) => string;
  throughput: string;
  throughputSub: string;
  peakPerMinute: string;
  currentPerMinute: string;
  perMinute: (count: number) => string;
  storage: string;
  storageSub: string;
  rows: (count: number) => string;
  openTasks: (count: number) => string;
  avgPerTask: (value: string) => string;
  avgPerAttempt: (value: string) => string;
  databaseFile: string;
  earliestRecord: string;
  retention: string;
  retentionNone: string;
  noStorage: string;
  quality: string;
  qualitySub: string;
  qComplete: string;
  qIncomplete: string;
  qPositioned: string;
  qUnanchored: string;
  qStale: (minutes: number) => string;
  diagnostics: string;
  items: (count: number) => string;
  remedy: string;
  affectedTasks: string;
  configEcho: string;
  configEchoSub: string;
  extensionVersion: string;
  apiVersion: string;
  placements: string;
  unknownVersion: string;
  notConfigured: string;
  diagnosticCopy: (diagnostic: HealthDiagnostic, health: HealthResponse) => DiagnosticCopy;
}

function backendCopy(diagnostic: HealthDiagnostic): DiagnosticCopy {
  return { title: diagnostic.title, detail: diagnostic.detail, remedy: diagnostic.remedy };
}

const EN: Messages = {
  title: "Context residency",
  empty: "No recorded model requests for this task.",
  attemptsTruncated: "Attempt list truncated at the server cap — the earliest attempts are shown.",
  coverage:
    "Presence is derived from recorded request inventories only. Absence inside an incomplete inventory renders as unknown — never as removal — and removal causes come only from recorded compaction memberships.",
  refresh: "Refresh",
  hint: "⌘/Ctrl+wheel zoom · drag the minimap to zoom, click to reset · ←/→ attempt",
  laneSystem: "System prompt",
  laneToolSchema: "Tool schema",
  laneMemory: "Memory",
  laneSkill: "Skill",
  laneUser: "User input",
  laneAssistant: "Assistant",
  laneToolResult: "Tool result",
  laneSummary: "Summary",
  laneMiddleware: "Middleware injection",
  laneAttachment: "Attachment",
  laneUnknown: "Unknown",
  lowerBound: "lower bound",
  composition: "Composition",
  compression: "Compaction",
  snapshot: "Request",
  retryAttempt: "retry attempt",
  total: "Total",
  members: "Ordered members",
  sortContext: "Context order",
  sortShare: "By share",
  memberUnprojected: "block not recorded",
  incompleteNote: "This inventory is incomplete: members that could not be serialized are missing, so the total is a lower bound and absences here are unknown, not removals.",
  unanchored: "Not positioned on the attempt stream",
  block: "Block",
  residence: "Residence",
  firstSeen: "First seen",
  lastSeen: "Last seen",
  removedBy: "Removed by",
  continuesIn: "continues in",
  removalUnrecorded: "no recorded removal cause",
  stillPresent: "Present in the latest recorded request.",
  preservedBy: "Preserved by",
  summaryOf: "Summary of",
  positionedBefore: "positioned before",
  compressionScope: "Request totals across the boundary",
  removed: "Removed",
  preserved: "Preserved",
  summaryBlock: "Summary carrier",
  summaryBlockUnknown: "No later request declared this summary.",
  loading: "Loading…",
  loadFailed: "Could not load the recording.",
  tasks: "Recorded tasks",
  noTasks: "No recorded tasks for this conversation.",
  threadLabel: "Conversation id",
  taskLabel: "Task id",
  load: "Load",
  taskKindLead: "lead",
  taskKindSubagent: "subagent",
  recordingOff: "The extension is not recording (no database, or disabled).",
  dropped: (count) => `${count} event(s) were dropped by the recorder; some inventories may be missing.`,
  compositionWindow: (capacity) => `100% = context window ${capacity}`,
  compositionRequest: "100% = this request (window not recorded)",
  used: "Used",
  free: "Free",
  overflow: (percent) => `${percent} over the window`,
  membersOfRequest: "share of this request",
  lede: "Find the task first, then open its board. The extension's own recording state lives under Health: queue, drops, write failures and inventory completeness say whether the recording can be trusted.",
  tabTasks: "Tasks",
  tabHealth: "Health",
  tabBoard: "Board",
  noTaskSelected: "no task selected",
  backToList: "Back to the list",
  searchPlaceholder: "Find by task id, conversation id or agent name; paste a full task id to open it",
  searchNotFound: (id) => `No recorded task ${id}.`,
  allKinds: "All kinds",
  allOutcomes: "All outcomes",
  outcomeRunning: "running",
  outcomeCompleted: "completed",
  outcomeFailed: "failed",
  outcomeAborted: "aborted",
  range24h: "Last 24 hours",
  range7d: "Last 7 days",
  rangeAll: "All time",
  onlyCompactions: "With compactions",
  onlyIncomplete: "With incomplete inventories",
  groupByThread: "By conversation",
  flat: "Flat",
  colTask: "Task",
  colThread: "Conversation",
  colStarted: "Started",
  colDuration: "Duration",
  colSteps: "Steps / attempts",
  colCompactions: "Compactions",
  colInventory: "Inventory",
  colPeak: "Peak context",
  colOutcome: "Outcome",
  openBoard: "Open board",
  openInChat: "Open conversation",
  summaryTasks: (count) => `${count} task(s)`,
  summaryThreads: (count) => `${count} conversation(s)`,
  summaryRunning: (count) => `${count} running`,
  summaryCompactions: (count) => `${count} compaction(s)`,
  summaryIncomplete: (count) => `${count} task(s) with incomplete inventories`,
  onThisPage: "on this page",
  emptyList: "No matching tasks. A task that was not recorded does not appear here — that does not mean it did not happen.",
  showAllTime: "Show all time",
  pageInfo: (from, to, total, perPage) => `Showing ${from}–${to} of ${total} tasks · ${perPage} per page`,
  retries: (count) => `${count} retry attempt(s)`,
  inventoryComplete: "complete",
  inventoryIncomplete: (count) => `${count} incomplete`,
  runningFor: (duration) => `running · ${duration}`,
  tasksInThread: (count) => `${count} task(s)`,
  latest: "latest",
  peakOfWindow: (percent) => `${percent} of the window`,
  peakStackTitle: "Peak request by lane",
  justNow: "just now",
  minutesAgo: (count) => `${count} min ago`,
  hoursAgo: (count) => `${count} h ago`,
  daysAgo: (count) => `${count} d ago`,
  seconds: (count) => `${count} s`,
  minutes: (count) => `${count} min`,
  hoursMinutes: (hours, minutes) => `${hours} h ${minutes} min`,
  recording: "Recording",
  notRecording: "Not recording",
  recordingDisabled: "Disabled",
  database: "Database",
  tablePrefix: "Table prefix",
  lastWrite: "Last write",
  lastEvent: "Last event",
  uptime: "Up for",
  never: "never",
  refreshedAt: (time) => `Refreshed ${time}`,
  queueDepth: "Queue depth",
  flushEvery: (ms) => `flushed every ${ms} ms`,
  accepted: "Accepted",
  sinceStart: "events since the service started",
  written: "Written",
  lastBatch: (events, ms) => `last batch ${events} in ${ms} ms`,
  noBatchYet: "nothing written yet",
  droppedTile: "Dropped",
  lastDropAt: (time) => `last at ${time}, buffer full`,
  noDrops: "no drops",
  writeFailures: "Write failures",
  writeFailuresSub: "a failed batch is dropped whole and counted",
  estimator: "Estimator",
  readCap: (count) => `read cap ${count} attempts / task`,
  throughput: "Write throughput",
  throughputSub: "events written per minute · last 60 minutes",
  peakPerMinute: "Peak",
  currentPerMinute: "This minute",
  perMinute: (count) => `${count} / min`,
  storage: "Storage",
  storageSub: "the four tables the extension owns",
  rows: (count) => `${count} rows`,
  openTasks: (count) => `${count} open`,
  avgPerTask: (value) => `avg ${value} / task`,
  avgPerAttempt: (value) => `avg ${value} / attempt`,
  databaseFile: "Database",
  earliestRecord: "Earliest record",
  retention: "Retention",
  retentionNone: "not configured (v1 keeps everything)",
  noStorage: "No database: nothing is stored and reads answer 503.",
  quality: "Data quality",
  qualitySub: "can the recording be trusted",
  qComplete: "Attempts with a complete inventory",
  qIncomplete: "Incomplete inventories (a member could not be serialized)",
  qPositioned: "Compactions positioned on an attempt stream",
  qUnanchored: "Unanchored compactions (no task identity, or no later request)",
  qStale: (minutes) => `Tasks without a stop event for over ${minutes} min`,
  diagnostics: "Diagnostics",
  items: (count) => `${count} item(s)`,
  remedy: "What to do",
  affectedTasks: "Affected tasks",
  configEcho: "Configuration",
  configEchoSub: "the plugins record from config.yaml, read-only",
  extensionVersion: "Extension version",
  apiVersion: "Extension API",
  placements: "Probe placement",
  unknownVersion: "not installed as a package",
  notConfigured: "not set",
  diagnosticCopy: backendCopy,
};

const ZH: Messages = {
  title: "上下文留存",
  empty: "该任务没有记录到模型请求。",
  attemptsTruncated: "attempt 列表已在服务端上限截断——展示最早的 attempts。",
  coverage:
    "存在性仅由已记录的请求成员清单推导。不完整清单中的缺席渲染为未知——从不作移出断言——移出原因只来自已记录的压缩成员关系。",
  refresh: "刷新",
  hint: "⌘/Ctrl+滚轮 缩放 · minimap 拖拽圈选 / 单击复位 · ←/→ 切换 attempt",
  laneSystem: "系统提示",
  laneToolSchema: "工具 Schema",
  laneMemory: "Memory 注入",
  laneSkill: "Skill 注入",
  laneUser: "用户输入",
  laneAssistant: "助手消息",
  laneToolResult: "工具结果",
  laneSummary: "压缩摘要",
  laneMiddleware: "Middleware 注入",
  laneAttachment: "附件",
  laneUnknown: "未知",
  lowerBound: "下界",
  composition: "组成占比",
  compression: "压缩",
  snapshot: "请求",
  retryAttempt: "重试 attempt",
  total: "合计",
  members: "有序成员",
  sortContext: "上下文顺序",
  sortShare: "按占比",
  memberUnprojected: "块未记录",
  incompleteNote: "这份清单不完整：无法序列化的成员缺失，合计只是下界，这里的缺席是未知而不是移出。",
  unanchored: "未定位到 attempt 流",
  block: "块",
  residence: "留存",
  firstSeen: "首见",
  lastSeen: "末见",
  removedBy: "移出于",
  continuesIn: "延续为",
  removalUnrecorded: "移出原因未记录",
  stillPresent: "仍在最新记录的请求中。",
  preservedBy: "被保留于",
  summaryOf: "摘要自",
  positionedBefore: "定位在",
  compressionScope: "边界两侧的请求合计",
  removed: "移出",
  preserved: "保留",
  summaryBlock: "摘要承载块",
  summaryBlockUnknown: "之后的请求没有声明这条摘要。",
  loading: "加载中…",
  loadFailed: "无法加载记录。",
  tasks: "已记录的任务",
  noTasks: "该会话没有记录到任务。",
  threadLabel: "会话 id",
  taskLabel: "任务 id",
  load: "加载",
  taskKindLead: "主代理",
  taskKindSubagent: "子代理",
  recordingOff: "扩展未在记录（没有数据库，或已禁用）。",
  dropped: (count) => `记录器丢弃了 ${count} 个事件；部分清单可能缺失。`,
  compositionWindow: (capacity) => `100% = 上下文窗口 ${capacity}`,
  compositionRequest: "100% = 本次请求（未记录窗口大小）",
  used: "已用",
  free: "剩余",
  overflow: (percent) => `超出窗口 ${percent}`,
  membersOfRequest: "占本次请求",
  lede: "先找到要看的任务，再进看板。扩展自己的记录状态放在「健康度」里：队列、丢弃、写入失败、清单完整度，一眼能看出记录是否可信。",
  tabTasks: "任务列表",
  tabHealth: "健康度",
  tabBoard: "看板",
  noTaskSelected: "未选任务",
  backToList: "返回列表",
  searchPlaceholder: "按任务 id、会话 id 或 agent 名称定位；粘贴完整任务 id 直接打开",
  searchNotFound: (id) => `没有记录到任务 ${id}。`,
  allKinds: "全部类型",
  allOutcomes: "全部结果",
  outcomeRunning: "进行中",
  outcomeCompleted: "完成",
  outcomeFailed: "失败",
  outcomeAborted: "中止",
  range24h: "最近 24 小时",
  range7d: "最近 7 天",
  rangeAll: "全部",
  onlyCompactions: "只看有压缩的",
  onlyIncomplete: "只看清单不完整的",
  groupByThread: "按会话分组",
  flat: "平铺",
  colTask: "任务",
  colThread: "会话",
  colStarted: "开始",
  colDuration: "时长",
  colSteps: "步 / attempt",
  colCompactions: "压缩",
  colInventory: "清单完整度",
  colPeak: "峰值上下文",
  colOutcome: "结果",
  openBoard: "打开看板",
  openInChat: "在会话中打开",
  summaryTasks: (count) => `${count} 个任务`,
  summaryThreads: (count) => `${count} 个会话`,
  summaryRunning: (count) => `${count} 个进行中`,
  summaryCompactions: (count) => `${count} 次压缩`,
  summaryIncomplete: (count) => `${count} 个任务有不完整清单`,
  onThisPage: "本页",
  emptyList: "没有匹配的任务。没有记录的任务不会出现在这里，这不代表它没有发生。",
  showAllTime: "查看全部时间",
  pageInfo: (from, to, total, perPage) => `显示 ${from}–${to}，共 ${total} 个任务 · 每页 ${perPage}`,
  retries: (count) => `含 ${count} 个重试 attempt`,
  inventoryComplete: "完整",
  inventoryIncomplete: (count) => `${count} 不完整`,
  runningFor: (duration) => `进行中 ${duration}`,
  tasksInThread: (count) => `${count} 个任务`,
  latest: "最近",
  peakOfWindow: (percent) => `占窗口 ${percent}`,
  peakStackTitle: "峰值请求按道组成",
  justNow: "刚刚",
  minutesAgo: (count) => `${count} 分钟前`,
  hoursAgo: (count) => `${count} 小时前`,
  daysAgo: (count) => `${count} 天前`,
  seconds: (count) => `${count} 秒`,
  minutes: (count) => `${count} 分`,
  hoursMinutes: (hours, minutes) => `${hours} 小时 ${minutes} 分`,
  recording: "正在记录",
  notRecording: "未在记录",
  recordingDisabled: "已禁用",
  database: "数据库",
  tablePrefix: "表前缀",
  lastWrite: "最近写入",
  lastEvent: "最近事件",
  uptime: "服务已运行",
  never: "从未",
  refreshedAt: (time) => `已刷新 ${time}`,
  queueDepth: "队列深度",
  flushEvery: (ms) => `每 ${ms} ms 刷盘一次`,
  accepted: "已接收",
  sinceStart: "事件，自服务启动起",
  written: "已写入",
  lastBatch: (events, ms) => `最近一批 ${events} 条，耗时 ${ms} ms`,
  noBatchYet: "尚未写入",
  droppedTile: "已丢弃",
  lastDropAt: (time) => `最近一次 ${time}，队列满`,
  noDrops: "没有丢弃",
  writeFailures: "写入失败",
  writeFailuresSub: "失败会整批丢弃并计数",
  estimator: "估算器",
  readCap: (count) => `读取上限 ${count} attempt / 任务`,
  throughput: "写入吞吐",
  throughputSub: "每分钟写入的事件数 · 最近 60 分钟",
  peakPerMinute: "峰值",
  currentPerMinute: "当前",
  perMinute: (count) => `${count} / 分钟`,
  storage: "存储",
  storageSub: "扩展自建的四张表",
  rows: (count) => `${count} 行`,
  openTasks: (count) => `${count} 个进行中`,
  avgPerTask: (value) => `平均 ${value} / 任务`,
  avgPerAttempt: (value) => `平均 ${value} / attempt`,
  databaseFile: "数据库文件",
  earliestRecord: "最早记录",
  retention: "保留策略",
  retentionNone: "未配置（v1 不清理）",
  noStorage: "没有数据库：什么都没有存，读取会返回 503。",
  quality: "数据质量",
  qualitySub: "记录能不能信",
  qComplete: "清单完整的 attempt",
  qIncomplete: "不完整清单（成员序列化失败）",
  qPositioned: "已定位到 attempt 流的压缩",
  qUnanchored: "未定位压缩（事件无 task 身份或没有后续请求）",
  qStale: (minutes) => `超过 ${minutes} 分钟没有结束事件的任务`,
  diagnostics: "诊断",
  items: (count) => `${count} 项`,
  remedy: "处理",
  affectedTasks: "受影响任务",
  configEcho: "配置回显",
  configEchoSub: "来自 config.yaml 的 plugins 记录，只读",
  extensionVersion: "扩展版本",
  apiVersion: "扩展 API",
  placements: "探针放置",
  unknownVersion: "未以包形式安装",
  notConfigured: "未设置",
  diagnosticCopy: (diagnostic, health) => {
    const status = health.status;
    const quality = health.quality;
    switch (diagnostic.code) {
      case "not_recording":
        return {
          title: "未在记录",
          detail: "服务没有数据库会话工厂（database.backend 是 memory，或服务启动失败）。采集已关闭，读取会返回 503。",
          remedy: "配置 sqlite 或 postgres 数据库后端并重启 Gateway。",
        };
      case "write_failures":
        return {
          title: "写入失败",
          detail: `${status.write_failures} 个事件在数据库写入失败后丢失。失败会整批丢弃，受影响的任务会缺 attempt。`,
          remedy: "查看 Gateway 日志中的数据库错误；下一次刷盘会继续写入更新的事件。",
        };
      case "events_dropped":
        return {
          title: `缓冲区满，丢弃了 ${status.dropped} 个事件`,
          detail: `${status.last_drop_at ? `最近一次丢弃在 ${status.last_drop_at}。` : ""}缓冲区容量 ${status.queue_capacity ?? "?"} 个事件。受影响的任务读出来会缺 attempt，缺席按未知渲染，不按移出。`,
          remedy: "提高 queue_capacity，或调低 flush_interval_ms 让写入线程更快清空缓冲。",
        };
      case "queue_pressure":
        return {
          title: "缓冲区接近满载",
          detail: `${status.queue_depth} / ${status.queue_capacity ?? "?"} 个事件在等待写入。`,
          remedy: "调低 flush_interval_ms，或检查数据库是否跟得上。",
        };
      case "stale_tasks":
        return {
          title: `${quality?.tasks_stale ?? 0} 个任务超过 ${quality?.stale_after_minutes ?? 0} 分钟没有结束事件`,
          detail: "可能仍在运行，也可能宿主在 3 秒预算内跳过了生命周期通知。",
          remedy: "记录本身无需处理；结果一栏保持「进行中」，不做猜测。",
        };
      case "unanchored_compactions":
        return {
          title: "有压缩没有定位到 attempt 流",
          detail: `${quality?.compactions_unanchored ?? 0} / ${quality?.compactions_total ?? 0} 次压缩无法定位：事件没有带 task 身份（宿主早于扩展 API 0.2.5），或之后没有请求。`,
          remedy: "升级宿主，让 CompactionEvent 带上 task_id；未定位的压缩只列出，不猜到矩阵上。",
        };
      case "incomplete_inventories":
        return {
          title: "有清单不完整的 attempt",
          detail: `${quality?.attempts_incomplete ?? 0} / ${quality?.attempts_total ?? 0} 个 attempt 的清单没能完整序列化。它们的合计只是下界，缺席是未知。`,
          remedy: null,
        };
      case "contract":
        return diagnostic.level === "ok"
          ? {
              title: "宿主契约匹配",
              detail: `extension API ${health.config.api_version ?? "?"}：压缩事件带 task 身份与 kept hashes，摘要承载块声明 summary_content_hash。`,
              remedy: null,
            }
          : { title: "契约包缺失", detail: "无法导入 deerflow_extension_api。", remedy: "连同依赖重新安装扩展。" };
      default:
        return backendCopy(diagnostic);
    }
  },
};

export function messages(locale: string | undefined): Messages {
  return locale?.toLowerCase().startsWith("zh") ? ZH : EN;
}

export function formatTimestamp(value: string | null, locale: string | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(locale?.toLowerCase().startsWith("zh") ? "zh-CN" : "en-US", {
    dateStyle: "medium",
    timeStyle: "medium",
  }).format(date);
}

export function formatClock(value: string | null, locale: string | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(locale?.toLowerCase().startsWith("zh") ? "zh-CN" : "en-US", { timeStyle: "medium" }).format(date);
}

export function shortId(id: string, length = 8): string {
  return id.length <= length ? id : id.slice(0, length);
}

/** "3 min ago" from an ISO timestamp; the exact time belongs in a title attribute. */
export function relativeTime(value: string | null | undefined, now: Date, t: Messages): string {
  if (!value) return t.never;
  const then = new Date(value).getTime();
  if (Number.isNaN(then)) return value;
  const seconds = Math.max(0, Math.round((now.getTime() - then) / 1000));
  if (seconds < 60) return t.justNow;
  if (seconds < 3600) return t.minutesAgo(Math.round(seconds / 60));
  if (seconds < 86_400) return t.hoursAgo(Math.round(seconds / 3600));
  return t.daysAgo(Math.round(seconds / 86_400));
}

export function formatDuration(seconds: number, t: Messages): string {
  if (seconds < 60) return t.seconds(seconds);
  if (seconds < 3600) return t.minutes(Math.round(seconds / 60));
  return t.hoursMinutes(Math.floor(seconds / 3600), Math.round((seconds % 3600) / 60));
}
