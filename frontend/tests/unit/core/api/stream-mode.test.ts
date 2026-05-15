import { expect, test } from "vitest";

import {
  CHAT_RUN_STREAM_MODES,
  forceChatRunStreamOptions,
  sanitizeRunStreamOptions,
} from "@/core/api/stream-mode";

test("drops unsupported stream modes from array payloads", () => {
  const sanitized = sanitizeRunStreamOptions({
    streamMode: [
      "values",
      "messages-tuple",
      "custom",
      "updates",
      "events",
      "tools",
    ],
  });

  expect(sanitized.streamMode).toEqual([
    "values",
    "messages-tuple",
    "custom",
    "updates",
    "events",
  ]);
});

test("drops unsupported stream modes from scalar payloads", () => {
  const sanitized = sanitizeRunStreamOptions({
    streamMode: "tools",
  });

  expect(sanitized.streamMode).toBeUndefined();
});

test("keeps payloads without streamMode untouched", () => {
  const options = {
    streamSubgraphs: true,
  };

  expect(sanitizeRunStreamOptions(options)).toBe(options);
});

test("forces chat stream mode to the minimal non-values strategy", () => {
  const sanitized = forceChatRunStreamOptions({
    streamMode: [
      "values",
      "messages-tuple",
      "custom",
      "updates",
      "events",
    ],
    streamSubgraphs: true,
  });

  expect(sanitized.streamMode).toEqual([...CHAT_RUN_STREAM_MODES]);
  expect(sanitized.streamSubgraphs).toBe(true);
});

test("adds explicit chat stream mode when the sdk payload omits streamMode", () => {
  const sanitized = forceChatRunStreamOptions({
    streamSubgraphs: true,
  });

  expect(sanitized.streamMode).toEqual([...CHAT_RUN_STREAM_MODES]);
});
