import { describe, expect, it } from "vitest";

import type { ResidencyAttempt, ResidencyBlockMeta, ResidencyMember, ResidencyResponse } from "../src/contracts";
import { deriveContextResidency, residencyAttemptLaneSizes, residencyLane, sortResidencyMembers } from "../src/residency";

function member(blockId: string, ordinal: number, tokens = 10): ResidencyMember {
  return { ordinal, block_id: blockId, estimated_tokens: tokens, visible_bytes: tokens * 4, resolution_status: "available" };
}

function attempt(id: string, stepSeq: number, members: ResidencyMember[], status: "complete" | "incomplete" = "complete"): ResidencyAttempt {
  return {
    attempt_id: id,
    step_id: `step-${stepSeq}`,
    step_seq: stepSeq,
    attempt_no: 1,
    effective: true,
    snapshot_id: id,
    status,
    occurred_at: null,
    estimated_tokens: members.reduce((sum, item) => sum + item.estimated_tokens, 0),
    visible_bytes: members.reduce((sum, item) => sum + item.visible_bytes, 0),
    message_count: members.length,
    tool_schema_count: 0,
    members,
  };
}

function blockMeta(kind: string | null, channel: "message" | "tool_schema" = "message"): ResidencyBlockMeta {
  return { block_id: "irrelevant", kind, role: null, name: null, channel, content_hash: null, source_identity: null };
}

function response(overrides: Partial<ResidencyResponse>): ResidencyResponse {
  return {
    task_id: "task-1",
    task: { task_id: "task-1", run_id: "run-1", thread_id: "thread-1", kind: "lead", parent_task_id: null, agent_name: null, started_at: "", stopped_at: null, outcome: null },
    attempts: [],
    blocks: {},
    compressions: [],
    attempts_truncated: false,
    projection_status: null,
    ...overrides,
  };
}

describe("residencyLane", () => {
  it("maps the extension's closed kind set to lane families", () => {
    expect(residencyLane(blockMeta("system_prompt"))).toBe("system");
    expect(residencyLane(blockMeta("memory"))).toBe("memory");
    expect(residencyLane(blockMeta("skill_instruction"))).toBe("skill");
    expect(residencyLane(blockMeta("user_input"))).toBe("user");
    expect(residencyLane(blockMeta("assistant_output"))).toBe("assistant");
    expect(residencyLane(blockMeta("tool_request"))).toBe("assistant");
    expect(residencyLane(blockMeta("tool_result_visible"))).toBe("tool_result");
    expect(residencyLane(blockMeta("summary"))).toBe("summary");
    expect(residencyLane(blockMeta("middleware_injection"))).toBe("middleware");
    expect(residencyLane(blockMeta("durable_context"))).toBe("middleware");
    expect(residencyLane(blockMeta("image_or_attachment"))).toBe("attachment");
  });

  it("degrades unknown kinds, null kinds, and missing meta to the neutral lane", () => {
    expect(residencyLane(blockMeta("hologram"))).toBe("unknown");
    expect(residencyLane(blockMeta(null))).toBe("unknown");
    expect(residencyLane(null)).toBe("unknown");
  });

  it("lets the tool_schema channel win over the stored kind", () => {
    expect(residencyLane(blockMeta("user_input", "tool_schema"))).toBe("tool_schema");
  });
});

describe("deriveContextResidency", () => {
  it("derives presence, runs, and first/last seen from membership alone", () => {
    const model = deriveContextResidency(
      response({
        attempts: [
          attempt("a1", 1, [member("sys", 0), member("u1", 1)]),
          attempt("a2", 2, [member("sys", 0), member("u1", 1), member("t1", 2)]),
          attempt("a3", 3, [member("sys", 0), member("u1", 1)]),
          attempt("a4", 4, [member("sys", 0), member("u1", 1), member("t1", 2)]),
        ],
        blocks: {
          sys: { ...blockMeta("system_prompt"), block_id: "sys" },
          u1: { ...blockMeta("user_input"), block_id: "u1" },
          t1: { ...blockMeta("tool_result_visible"), block_id: "t1" },
        },
      }),
    );
    const tool = model.rows.find((row) => row.blockId === "t1")!;
    expect(tool.presence).toEqual(["absent", "present", "absent", "present"]);
    expect(tool.runs).toEqual([
      { start: 1, end: 1 },
      { start: 3, end: 3 },
    ]);
    expect(tool.firstSeen).toBe(1);
    expect(tool.lastSeen).toBe(3);
    expect(tool.presentCount).toBe(2);
    expect(model.rows.find((row) => row.blockId === "sys")!.runs).toEqual([{ start: 0, end: 3 }]);
  });

  it("marks absence inside an incomplete inventory as unknown, never absent", () => {
    const model = deriveContextResidency(
      response({
        attempts: [
          attempt("a1", 1, [member("sys", 0), member("t1", 1)]),
          attempt("a2", 2, [member("sys", 0)], "incomplete"),
          attempt("a3", 3, [member("sys", 0), member("t1", 1)]),
        ],
        blocks: { sys: { ...blockMeta("system_prompt"), block_id: "sys" }, t1: { ...blockMeta("tool_result_visible"), block_id: "t1" } },
      }),
    );
    const tool = model.rows.find((row) => row.blockId === "t1")!;
    expect(tool.presence).toEqual(["present", "unknown", "present"]);
    expect(tool.unknownAt).toEqual([1]);
    expect(tool.runs).toEqual([
      { start: 0, end: 0 },
      { start: 2, end: 2 },
    ]);
  });

  it("keeps a member with no block metadata as an unknown-lane row", () => {
    const model = deriveContextResidency(response({ attempts: [attempt("a1", 1, [member("ghost", 0)])], blocks: {} }));
    expect(model.rows).toHaveLength(1);
    expect(model.rows[0]!.meta).toBeNull();
    expect(model.rows[0]!.lane).toBe("unknown");
  });

  it("joins removal and continuation only from recorded compaction dispositions", () => {
    const model = deriveContextResidency(
      response({
        attempts: [
          attempt("a1", 1, [member("u1", 0), member("t1", 1)]),
          attempt("a2", 2, [member("u1", 0), member("sum1", 1)]),
          attempt("a3", 3, [member("u1", 0)]),
        ],
        blocks: {
          u1: { ...blockMeta("user_input"), block_id: "u1" },
          t1: { ...blockMeta("tool_result_visible"), block_id: "t1" },
          sum1: { ...blockMeta("summary"), block_id: "sum1" },
        },
        compressions: [
          {
            compression_id: "C1",
            summary_block_id: "sum1",
            occurred_at: null,
            status: "positioned",
            before_tokens: 100,
            after_tokens: 20,
            removed_block_ids: ["t1"],
            preserved_block_ids: ["u1"],
            positioned_before_attempt_id: "a2",
          },
        ],
      }),
    );
    expect(model.rows.find((row) => row.blockId === "t1")!.removedBy).toBe("C1");
    const user = model.rows.find((row) => row.blockId === "u1")!;
    expect(user.removedBy).toBeNull();
    expect(user.preservedBy).toEqual(["C1"]);
    const summary = model.rows.find((row) => row.blockId === "sum1")!;
    expect(summary.summaryOf).toBe("C1");
    expect(summary.removedBy).toBeNull();
    expect(model.compressionsBefore.get("a2")!.map((c) => c.compression_id)).toEqual(["C1"]);
    expect(model.unanchoredCompressions).toEqual([]);
  });

  it("keeps a compaction with no resolvable stream position unanchored, and tolerates a missing summary carrier", () => {
    const model = deriveContextResidency(
      response({
        attempts: [attempt("a1", 1, [member("u1", 0)])],
        blocks: { u1: { ...blockMeta("user_input"), block_id: "u1" } },
        compressions: [
          {
            compression_id: "C1",
            summary_block_id: null,
            occurred_at: null,
            status: "unanchored",
            before_tokens: 1,
            after_tokens: 1,
            removed_block_ids: [],
            preserved_block_ids: [],
            positioned_before_attempt_id: null,
          },
        ],
      }),
    );
    expect(model.unanchoredCompressions.map((c) => c.compression_id)).toEqual(["C1"]);
    expect(model.compressionsBefore.size).toBe(0);
    expect(model.rows[0]!.summaryOf).toBeNull();
  });

  it("groups rows into occurring lanes only, in taxonomy order", () => {
    const model = deriveContextResidency(
      response({
        attempts: [attempt("a1", 1, [member("t1", 0), member("sys", 1), member("schema", 2)])],
        blocks: {
          sys: { ...blockMeta("system_prompt"), block_id: "sys" },
          t1: { ...blockMeta("tool_result_visible"), block_id: "t1" },
          schema: { ...blockMeta("tool_schema"), block_id: "schema", channel: "tool_schema" },
        },
      }),
    );
    expect(model.lanes.map((group) => group.lane)).toEqual(["system", "tool_schema", "tool_result"]);
  });

  it("carries the truncation flag through — never silent", () => {
    expect(deriveContextResidency(response({ attempts_truncated: true })).attemptsTruncated).toBe(true);
  });
});

describe("residencyAttemptLaneSizes", () => {
  it("sums recorded member sizes by lane under the chosen measure", () => {
    const blocks = {
      sys: { ...blockMeta("system_prompt"), block_id: "sys" },
      u1: { ...blockMeta("user_input"), block_id: "u1" },
      u2: { ...blockMeta("user_input"), block_id: "u2" },
    };
    const one = attempt("a1", 1, [member("sys", 0, 20), member("u1", 1, 5), member("u2", 2, 7)]);
    expect(residencyAttemptLaneSizes(one, blocks, "tokens")).toEqual([
      { lane: "system", size: 20 },
      { lane: "user", size: 12 },
    ]);
    expect(residencyAttemptLaneSizes(one, blocks, "bytes")).toEqual([
      { lane: "system", size: 80 },
      { lane: "user", size: 48 },
    ]);
  });
});

describe("sortResidencyMembers", () => {
  it("keeps the recorded ordinal order under context sort", () => {
    const members = [member("a", 0, 5), member("b", 1, 50), member("c", 2, 20)];
    expect(sortResidencyMembers(members, "context", "tokens")).toBe(members);
  });

  it("orders by recorded size descending under share sort, ties keeping context order", () => {
    const members = [member("a", 0, 5), member("b", 1, 50), member("c", 2, 20), member("d", 3, 50)];
    expect(sortResidencyMembers(members, "share", "tokens").map((item) => item.block_id)).toEqual(["b", "d", "c", "a"]);
    expect(members.map((item) => item.block_id)).toEqual(["a", "b", "c", "d"]);
  });

  it("follows the chosen measure when tokens and bytes disagree", () => {
    const small = { ...member("small", 0, 10), visible_bytes: 9000 };
    const large = { ...member("large", 1, 100), visible_bytes: 10 };
    expect(sortResidencyMembers([small, large], "share", "tokens").map((item) => item.block_id)).toEqual(["large", "small"]);
    expect(sortResidencyMembers([small, large], "share", "bytes").map((item) => item.block_id)).toEqual(["small", "large"]);
  });
});
