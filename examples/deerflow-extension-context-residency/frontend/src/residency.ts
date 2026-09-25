import type {
  ResidencyAttempt,
  ResidencyBlockMeta,
  ResidencyCompression,
  ResidencyMember,
  ResidencyResponse,
} from "./contracts";

/**
 * Pure projection layer for the residency board (zero React): the block ×
 * attempt presence model over recorded request inventories.
 *
 * The browser classifies nothing about history: presence is derived only
 * from recorded membership, and its third state is load-bearing — a block
 * not listed in an INCOMPLETE inventory is `unknown`, never `absent`, so an
 * incomplete inventory can never manufacture a removal claim. Removal
 * causes come only from recorded compaction memberships; a disappearance
 * no compaction names stays "cause unrecorded", never an inference.
 */

export type ResidencyLane =
  | "system"
  | "tool_schema"
  | "memory"
  | "skill"
  | "user"
  | "assistant"
  | "tool_result"
  | "summary"
  | "middleware"
  | "attachment"
  | "unknown";

/** Taxonomy order for lanes; empty lanes are omitted from the model. */
export const RESIDENCY_LANE_ORDER: readonly ResidencyLane[] = [
  "system",
  "tool_schema",
  "memory",
  "skill",
  "user",
  "assistant",
  "tool_result",
  "summary",
  "middleware",
  "attachment",
  "unknown",
];

export type ResidencyLaneSubject =
  | ResidencyBlockMeta
  | Pick<ResidencyBlockMeta, "kind" | "channel">;

/**
 * Classify one block's lane from its recorded identity. The tool_schema
 * channel wins over kind; the kind switch is the extension's closed set, and
 * anything else — a stamp from a newer host, a missing meta row — is the
 * neutral unknown lane, never the nearest-looking member.
 */
export function residencyLane(meta: ResidencyLaneSubject | null): ResidencyLane {
  if (meta === null) return "unknown";
  if (meta.channel === "tool_schema") return "tool_schema";
  switch (meta.kind) {
    case "system_prompt":
      return "system";
    case "tool_schema":
      return "tool_schema";
    case "memory":
      return "memory";
    case "skill_instruction":
      return "skill";
    case "user_input":
      return "user";
    case "assistant_output":
    case "assistant_reasoning":
    case "tool_request":
      return "assistant";
    case "tool_result_raw":
    case "tool_result_visible":
      return "tool_result";
    case "summary":
      return "summary";
    case "middleware_injection":
    case "durable_context":
      return "middleware";
    case "image_or_attachment":
      return "attachment";
    default:
      return "unknown";
  }
}

export type ResidencyPresence = "present" | "absent" | "unknown";

export type ResidencyMeasure = "tokens" | "bytes";

/** One contiguous present stretch, inclusive attempt indices. */
export interface ResidencyRun {
  start: number;
  end: number;
}

export interface ResidencyRow {
  blockId: string;
  meta: ResidencyBlockMeta | null;
  lane: ResidencyLane;
  /** Per attempt-index presence, three-state. */
  presence: ResidencyPresence[];
  /** Contiguous present stretches — the O(runs) render input. */
  runs: ResidencyRun[];
  /** Attempt indices whose presence is unknown (incomplete inventories). */
  unknownAt: number[];
  firstSeen: number;
  lastSeen: number;
  presentCount: number;
  /** Sizes from the block's latest recorded occurrence. */
  sizeTokens: number;
  sizeBytes: number;
  /** Compaction that lists this block removed; null = no recorded cause. */
  removedBy: string | null;
  /** Compactions that list this block preserved. */
  preservedBy: string[];
  /** The compaction this block is the summary of, when it is one. */
  summaryOf: string | null;
}

export interface ResidencyLaneGroup {
  lane: ResidencyLane;
  rows: ResidencyRow[];
}

export interface ResidencyModel {
  attempts: ResidencyAttempt[];
  rows: ResidencyRow[];
  /** Only lanes that occur, in taxonomy order. */
  lanes: ResidencyLaneGroup[];
  compressions: ResidencyCompression[];
  /** attempt_id → compactions positioned immediately before that attempt. */
  compressionsBefore: Map<string, ResidencyCompression[]>;
  /** Compactions with no recorded stream position — listed, never guessed. */
  unanchoredCompressions: ResidencyCompression[];
  attemptsTruncated: boolean;
}

/** Fold the response into the lane/row model. */
export function deriveContextResidency(response: ResidencyResponse): ResidencyModel {
  const attempts = response.attempts;
  const memberSets = attempts.map(
    (attempt) => new Map(attempt.members.map((member) => [member.block_id, member])),
  );

  const blockOrder: string[] = [];
  const seen = new Set<string>();
  for (const attempt of attempts) {
    for (const member of attempt.members) {
      if (!seen.has(member.block_id)) {
        seen.add(member.block_id);
        blockOrder.push(member.block_id);
      }
    }
  }

  const removedBy = new Map<string, string>();
  const preservedBy = new Map<string, string[]>();
  const summaryOf = new Map<string, string>();
  for (const compression of response.compressions) {
    for (const blockId of compression.removed_block_ids) {
      if (!removedBy.has(blockId)) removedBy.set(blockId, compression.compression_id);
    }
    for (const blockId of compression.preserved_block_ids) {
      const list = preservedBy.get(blockId) ?? [];
      list.push(compression.compression_id);
      preservedBy.set(blockId, list);
    }
    if (compression.summary_block_id !== null && !summaryOf.has(compression.summary_block_id)) {
      summaryOf.set(compression.summary_block_id, compression.compression_id);
    }
  }

  const rows: ResidencyRow[] = blockOrder.map((blockId) => {
    const meta = response.blocks[blockId] ?? null;
    const presence: ResidencyPresence[] = [];
    const runs: ResidencyRun[] = [];
    const unknownAt: number[] = [];
    let firstSeen = -1;
    let lastSeen = -1;
    let presentCount = 0;
    let sizeTokens = 0;
    let sizeBytes = 0;
    attempts.forEach((attempt, index) => {
      const member = memberSets[index]!.get(blockId);
      if (member !== undefined) {
        presence.push("present");
        presentCount += 1;
        sizeTokens = member.estimated_tokens;
        sizeBytes = member.visible_bytes;
        if (firstSeen === -1) firstSeen = index;
        lastSeen = index;
        const lastRun = runs[runs.length - 1];
        if (lastRun?.end === index - 1) lastRun.end = index;
        else runs.push({ start: index, end: index });
      } else if (attempt.status === "incomplete") {
        presence.push("unknown");
        unknownAt.push(index);
      } else {
        presence.push("absent");
      }
    });
    return {
      blockId,
      meta,
      lane: residencyLane(meta),
      presence,
      runs,
      unknownAt,
      firstSeen,
      lastSeen,
      presentCount,
      sizeTokens,
      sizeBytes,
      removedBy: removedBy.get(blockId) ?? null,
      preservedBy: preservedBy.get(blockId) ?? [],
      summaryOf: summaryOf.get(blockId) ?? null,
    };
  });

  const laneRows = new Map<ResidencyLane, ResidencyRow[]>();
  for (const row of rows) {
    const list = laneRows.get(row.lane) ?? [];
    list.push(row);
    laneRows.set(row.lane, list);
  }
  const lanes: ResidencyLaneGroup[] = RESIDENCY_LANE_ORDER.filter((lane) => laneRows.has(lane)).map(
    (lane) => ({ lane, rows: laneRows.get(lane)! }),
  );

  const compressionsBefore = new Map<string, ResidencyCompression[]>();
  const unanchoredCompressions: ResidencyCompression[] = [];
  for (const compression of response.compressions) {
    const anchor = compression.positioned_before_attempt_id;
    if (anchor !== null && attempts.some((attempt) => attempt.attempt_id === anchor)) {
      const list = compressionsBefore.get(anchor) ?? [];
      list.push(compression);
      compressionsBefore.set(anchor, list);
    } else {
      unanchoredCompressions.push(compression);
    }
  }

  return {
    attempts,
    rows,
    lanes,
    compressions: response.compressions,
    compressionsBefore,
    unanchoredCompressions,
    attemptsTruncated: response.attempts_truncated,
  };
}

export function residencyMemberSize(
  member: { estimated_tokens: number; visible_bytes: number },
  measure: ResidencyMeasure,
): number {
  return measure === "tokens" ? member.estimated_tokens : member.visible_bytes;
}

/** Member-list orderings: the request's own ordinal order, or share-descending. */
export type ResidencyMemberSort = "context" | "share";

/**
 * Order one attempt's members for display. `context` returns the recorded
 * ordinal order untouched; `share` orders by recorded size under the chosen
 * measure, descending, ties keeping context order (stable sort) — each row
 * still carries its original ordinal, so identity never detaches from the
 * request position.
 */
export function sortResidencyMembers(
  members: ResidencyMember[],
  sort: ResidencyMemberSort,
  measure: ResidencyMeasure,
): ResidencyMember[] {
  if (sort === "context") return members;
  return [...members].sort(
    (left, right) => residencyMemberSize(right, measure) - residencyMemberSize(left, measure),
  );
}

/** One attempt's recorded total under the chosen measure. */
export function residencyAttemptTotal(attempt: ResidencyAttempt, measure: ResidencyMeasure): number {
  return measure === "tokens" ? attempt.estimated_tokens : attempt.visible_bytes;
}

/**
 * One attempt's composition summed by lane over its recorded members, in
 * taxonomy order, empty lanes omitted. Sums recorded member sizes only — an
 * incomplete inventory's missing members contribute nothing, which is why the
 * caller renders the total as a lower bound there.
 */
export function residencyAttemptLaneSizes(
  attempt: ResidencyAttempt,
  blocks: Record<string, ResidencyBlockMeta>,
  measure: ResidencyMeasure,
): Array<{ lane: ResidencyLane; size: number }> {
  const totals = new Map<ResidencyLane, number>();
  for (const member of attempt.members) {
    const lane = residencyLane(blocks[member.block_id] ?? null);
    totals.set(lane, (totals.get(lane) ?? 0) + residencyMemberSize(member, measure));
  }
  return RESIDENCY_LANE_ORDER.filter((lane) => totals.has(lane)).map((lane) => ({
    lane,
    size: totals.get(lane)!,
  }));
}
