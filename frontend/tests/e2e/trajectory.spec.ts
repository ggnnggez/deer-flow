import { expect, test } from "@playwright/test";

import { mockLangGraphAPI, MOCK_THREAD_ID } from "./utils/mock-api";

const TOOL_MESSAGES = [
  {
    id: "human-trajectory",
    type: "human",
    content: "Inspect the repository",
  },
  {
    id: "ai-tool-trajectory",
    type: "ai",
    content: "I will inspect it.",
    tool_calls: [
      {
        id: "call-trajectory",
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
    id: "tool-trajectory",
    type: "tool",
    name: "bash",
    tool_call_id: "call-trajectory",
    content: "README.md\npackage.json",
  },
  {
    id: "ai-answer-trajectory",
    type: "ai",
    content: "The repository contains a README and package manifest.",
    additional_kwargs: { turn_duration: 7 },
  },
];

test("switches from Chat to the basic trajectory ledger", async ({ page }) => {
  mockLangGraphAPI(page, {
    threads: [
      {
        thread_id: MOCK_THREAD_ID,
        title: "Trajectory conversation",
        messages: TOOL_MESSAGES,
      },
    ],
  });

  await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
  await page.getByRole("tab", { name: "Trajectory" }).click();

  const trajectory = page.getByRole("region", { name: "Trajectory" });
  await expect(trajectory).toBeVisible();
  await expect(trajectory.getByText("Turn 1", { exact: true })).toBeVisible();
  await expect(
    trajectory
      .getByRole("button", { name: /Turn 1.*150 tk/ })
      .getByText("150 tk", { exact: true }),
  ).toBeVisible();
  await expect(trajectory.getByText("7.0s", { exact: true })).toBeVisible();

  await trajectory.getByRole("button", { name: /bash/i }).click();
  const details = page.getByLabel("Record details");
  await expect(details.getByText("rg --files", { exact: true })).toBeVisible();
  await expect(details.getByText("README.md", { exact: false })).toBeVisible();

  await trajectory
    .getByRole("searchbox", { name: "Search trajectory" })
    .fill("package.json");
  await expect(trajectory.getByText("Inspect the repository")).toHaveCount(0);
  await expect(trajectory.getByRole("button", { name: /bash/i })).toBeVisible();
});

test("virtualizes a long trajectory ledger", async ({ page }) => {
  const messages = Array.from({ length: 160 }, (_, index) => [
    {
      id: `human-${index}`,
      type: "human",
      content: `Request ${index}`,
    },
    {
      id: `ai-${index}`,
      type: "ai",
      content: `Answer ${index}`,
    },
  ]).flat();
  mockLangGraphAPI(page, {
    threads: [
      {
        thread_id: MOCK_THREAD_ID,
        title: "Long trajectory",
        messages,
      },
    ],
  });

  await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
  await page.getByRole("tab", { name: "Trajectory" }).click();
  const mountedRows = page.locator(
    '[data-testid="trajectory-scroll"] [role="listitem"]',
  );
  await expect.poll(() => mountedRows.count()).toBeGreaterThan(0);
  expect(await mountedRows.count()).toBeLessThan(100);
  await expect(page.getByText("Answer 159", { exact: true })).toBeVisible();
});
