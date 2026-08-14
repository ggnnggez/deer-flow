import { describe, expect, it } from "@rstest/core";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { ConversationViewToggle } from "@/components/workspace/trajectory/conversation-view-toggle";

describe("ConversationViewToggle", () => {
  it("exposes Chat and Trajectory as an accessible controlled tab list", () => {
    const html = renderToStaticMarkup(
      createElement(ConversationViewToggle, {
        chatLabel: "Chat",
        trajectoryLabel: "Trajectory",
        value: "trajectory",
        onChange: () => undefined,
      }),
    );

    expect(html).toContain('role="tablist"');
    expect(html).toContain('role="tab"');
    expect(html).toMatch(/aria-selected="false"[^>]*>Chat/);
    expect(html).toMatch(/aria-selected="true"[^>]*>Trajectory/);
  });
});
