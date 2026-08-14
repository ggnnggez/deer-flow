import type { Message } from "@langchain/langgraph-sdk";
import { describe, expect, it } from "@rstest/core";

import { projectTrajectory } from "@/core/trajectory/projector";

describe("projectTrajectory", () => {
  it("groups a conversation turn and joins a tool result to its call", () => {
    const messages = [
      {
        id: "human-1",
        type: "human",
        content: "Inspect the repository",
      },
      {
        id: "ai-1",
        type: "ai",
        content: "I will inspect it.",
        tool_calls: [
          {
            id: "call-1",
            name: "bash",
            args: { command: "rg --files" },
          },
        ],
        usage_metadata: {
          input_tokens: 120,
          output_tokens: 30,
          total_tokens: 150,
        },
      },
      {
        id: "tool-1",
        type: "tool",
        name: "bash",
        tool_call_id: "call-1",
        content: "README.md\npackage.json",
      },
      {
        id: "ai-2",
        type: "ai",
        content: "The repository contains a README and package manifest.",
        additional_kwargs: { turn_duration: 7 },
        usage_metadata: {
          input_tokens: 180,
          output_tokens: 45,
          total_tokens: 225,
        },
      },
    ] as Message[];

    expect(projectTrajectory(messages)).toEqual([
      {
        id: "turn-1",
        number: 1,
        durationSeconds: 7,
        usage: { inputTokens: 300, outputTokens: 75, totalTokens: 375 },
        records: [
          {
            id: "message:human-1",
            kind: "user",
            label: "USER",
            content: "Inspect the repository",
            messageId: "human-1",
          },
          {
            id: "message:ai-1",
            kind: "assistant",
            label: "ASSISTANT",
            content: "I will inspect it.",
            messageId: "ai-1",
            status: "complete",
            step: 1,
            usage: { inputTokens: 120, outputTokens: 30, totalTokens: 150 },
          },
          {
            id: "tool:call-1",
            kind: "tool",
            label: "bash",
            content: "rg --files",
            result: "README.md\npackage.json",
            status: "complete",
            step: 1,
            toolCallId: "call-1",
            toolName: "bash",
          },
          {
            id: "message:ai-2",
            kind: "assistant",
            label: "ASSISTANT",
            content: "The repository contains a README and package manifest.",
            messageId: "ai-2",
            status: "complete",
            step: 2,
            usage: { inputTokens: 180, outputTokens: 45, totalTokens: 225 },
          },
        ],
      },
    ]);
  });

  it("omits messages hidden from the conversation UI", () => {
    const messages = [
      {
        id: "human-visible",
        type: "human",
        content: "Visible request",
      },
      {
        id: "human-hidden",
        type: "human",
        content: "Hidden approval response",
        additional_kwargs: { hide_from_ui: true },
      },
      {
        id: "summary-control",
        type: "human",
        name: "summary",
        content: "Internal summary control",
      },
      {
        id: "ai-visible",
        type: "ai",
        content: "Visible answer",
      },
    ] as Message[];

    expect(
      projectTrajectory(messages).flatMap((turn) =>
        turn.records.map((record) => record.content),
      ),
    ).toEqual(["Visible request", "Visible answer"]);
  });

  it("uses recorded reasoning when an assistant step has no answer text", () => {
    const messages = [
      {
        id: "human-reasoning",
        type: "human",
        content: "Investigate the failure",
      },
      {
        id: "ai-reasoning",
        type: "ai",
        content: "",
        additional_kwargs: {
          reasoning_content: "I should inspect the failing command first.",
        },
      },
    ] as Message[];

    expect(projectTrajectory(messages)[0]?.records[1]?.content).toBe(
      "I should inspect the failing command first.",
    );
  });

  it("numbers model steps and reports each tool lifecycle from recorded results", () => {
    const messages = [
      { id: "human-status", type: "human", content: "Run the checks" },
      {
        id: "ai-status-1",
        type: "ai",
        content: "I will run both checks.",
        tool_calls: [
          { id: "call-failed", name: "bash", args: { command: "pnpm lint" } },
          { id: "call-running", name: "bash", args: { command: "pnpm test" } },
        ],
      },
      {
        id: "tool-failed",
        type: "tool",
        tool_call_id: "call-failed",
        content: "ESLint found one error",
        status: "error",
      },
      {
        id: "ai-status-2",
        type: "ai",
        content: "I am checking the failure.",
      },
    ] as Message[];

    const records = projectTrajectory(messages, { isStreaming: true })[0]
      ?.records;
    expect(
      records?.map(({ kind, step, status }) => ({ kind, step, status })),
    ).toEqual([
      { kind: "user", step: undefined, status: undefined },
      { kind: "assistant", step: 1, status: "complete" },
      { kind: "tool", step: 1, status: "error" },
      { kind: "tool", step: 1, status: "running" },
      { kind: "assistant", step: 2, status: "complete" },
    ]);
  });

  it("does not describe a settled tool call without a result as running", () => {
    const messages = [
      { id: "human-incomplete", type: "human", content: "Run it" },
      {
        id: "ai-incomplete",
        type: "ai",
        content: "",
        tool_calls: [
          { id: "call-incomplete", name: "bash", args: { command: "sleep 1" } },
        ],
      },
    ] as Message[];

    expect(projectTrajectory(messages)[0]?.records[2]?.status).toBe(
      "incomplete",
    );
    expect(
      projectTrajectory(messages, { isStreaming: true })[0]?.records[2]?.status,
    ).toBe("running");
  });
});
