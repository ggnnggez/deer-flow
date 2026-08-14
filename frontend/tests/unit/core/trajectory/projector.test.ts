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
            usage: { inputTokens: 120, outputTokens: 30, totalTokens: 150 },
          },
          {
            id: "tool:call-1",
            kind: "tool",
            label: "bash",
            content: "rg --files",
            result: "README.md\npackage.json",
            toolCallId: "call-1",
            toolName: "bash",
          },
          {
            id: "message:ai-2",
            kind: "assistant",
            label: "ASSISTANT",
            content: "The repository contains a README and package manifest.",
            messageId: "ai-2",
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
});
