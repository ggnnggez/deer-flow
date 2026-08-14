import type { Message } from "@langchain/langgraph-sdk";

import { getUsageMetadata, type TokenUsage } from "@/core/messages/usage";
import {
  extractReasoningContentFromMessage,
  isHiddenFromUIMessage,
} from "@/core/messages/utils";
import { textOfMessage } from "@/core/threads/utils";

import type { TrajectoryRecord, TrajectoryTurn } from "./types";

function addUsage(current: TokenUsage | undefined, usage: TokenUsage) {
  return {
    inputTokens: (current?.inputTokens ?? 0) + usage.inputTokens,
    outputTokens: (current?.outputTokens ?? 0) + usage.outputTokens,
    totalTokens: (current?.totalTokens ?? 0) + usage.totalTokens,
  };
}

function messageId(message: Message, index: number) {
  return typeof message.id === "string" && message.id
    ? message.id
    : `anonymous-${index}`;
}

function toolCallContent(args: unknown) {
  if (typeof args !== "object" || args === null || Array.isArray(args)) {
    return typeof args === "string" ? args : JSON.stringify(args ?? {});
  }
  const values = Object.values(args);
  if (values.length === 1 && typeof values[0] === "string") {
    return values[0];
  }
  return JSON.stringify(args, null, 2);
}

function turnDuration(message: Message) {
  const value = message.additional_kwargs?.turn_duration;
  return typeof value === "number" && Number.isFinite(value) && value >= 0
    ? value
    : undefined;
}

export interface ProjectTrajectoryOptions {
  isStreaming?: boolean;
}

/** Project the message stream into user-visible Trajectory turns. */
export function projectTrajectory(
  messages: Message[],
  { isStreaming = false }: ProjectTrajectoryOptions = {},
): TrajectoryTurn[] {
  const turns: TrajectoryTurn[] = [];
  const tools = new Map<string, TrajectoryRecord>();
  let current: TrajectoryTurn | undefined;
  let currentStep = 0;

  const ensureTurn = () => {
    if (current) {
      return current;
    }
    current = {
      id: `turn-${turns.length + 1}`,
      number: turns.length + 1,
      records: [],
    };
    turns.push(current);
    return current;
  };

  for (const [index, message] of messages.entries()) {
    if (isHiddenFromUIMessage(message)) {
      continue;
    }
    if (message.type === "human" && current?.records.length) {
      current = undefined;
      currentStep = 0;
    }
    const turn = ensureTurn();
    const id = messageId(message, index);

    if (message.type === "human" || message.type === "system") {
      turn.records.push({
        id: `message:${id}`,
        kind: message.type === "human" ? "user" : "system",
        label: message.type === "human" ? "USER" : "SYSTEM",
        content: textOfMessage(message) ?? "",
        messageId: id,
      });
      continue;
    }

    if (message.type === "ai") {
      const step = ++currentStep;
      const usage = getUsageMetadata(message) ?? undefined;
      const answer = textOfMessage(message);
      const reasoning = extractReasoningContentFromMessage(message);
      turn.records.push({
        id: `message:${id}`,
        kind: "assistant",
        label: "ASSISTANT",
        content: answer?.trim() ? answer : (reasoning ?? ""),
        messageId: id,
        status: "complete",
        step,
        ...(usage ? { usage } : {}),
      });
      if (usage) {
        turn.usage = addUsage(turn.usage, usage);
      }
      const duration = turnDuration(message);
      if (duration !== undefined) {
        turn.durationSeconds = duration;
      }
      for (const call of message.tool_calls ?? []) {
        const callId = call.id ?? `${id}:${call.name}:${turn.records.length}`;
        const tool: TrajectoryRecord = {
          id: `tool:${callId}`,
          kind: "tool",
          label: call.name,
          content: toolCallContent(call.args),
          status: isStreaming ? "running" : "incomplete",
          step,
          ...(call.id ? { toolCallId: call.id } : {}),
          toolName: call.name,
        };
        turn.records.push(tool);
        if (call.id) {
          tools.set(call.id, tool);
        }
      }
      continue;
    }

    if (message.type === "tool") {
      const callId = message.tool_call_id;
      const existing =
        typeof callId === "string" ? tools.get(callId) : undefined;
      if (existing) {
        existing.result = textOfMessage(message) ?? "";
        existing.status = message.status === "error" ? "error" : "complete";
        continue;
      }
      const toolName =
        typeof message.name === "string" && message.name
          ? message.name
          : "tool";
      turn.records.push({
        id: `tool:${callId || id}`,
        kind: "tool",
        label: toolName,
        content: "",
        result: textOfMessage(message) ?? "",
        status: message.status === "error" ? "error" : "complete",
        ...(currentStep > 0 ? { step: currentStep } : {}),
        ...(callId ? { toolCallId: callId } : {}),
        toolName,
      });
    }
  }

  return turns.filter((turn) => turn.records.length > 0);
}
