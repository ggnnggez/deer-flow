/** The page's own strings. The host hands the surface a locale; it shares no dictionary. */

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

export function shortId(id: string, length = 8): string {
  return id.length <= length ? id : id.slice(0, length);
}
