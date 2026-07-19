import { describe, expect, it } from "@rstest/core";

import { getAgentReleaseDiffGroups } from "@/core/ansich/release-presentation";
import type { AnsichAgentReleaseComparison } from "@/core/ansich/types";

function comparison(): AnsichAgentReleaseComparison {
  return {
    left_release_hash: "left",
    right_release_hash: "right",
    changed_components: ["model", "tools"],
    model: [{ path: "effective", left: "model-a", right: "model-b" }],
    prompt: [],
    tools: {
      added: [{ source: "builtin", name: "new_tool" }],
      removed: [],
      schema_changed: [],
      description_changed: [],
      source_changed: [
        {
          name: "search",
          left_source: "builtin",
          right_source: "mcp:web",
        },
      ],
    },
    policy: [],
    build: [],
    quality_status: "unassessed",
  };
}

describe("Agent release comparison presentation", () => {
  it("keeps typed tool source changes distinct and omits unchanged groups", () => {
    const groups = getAgentReleaseDiffGroups(comparison());

    expect(groups.map((group) => group.component)).toEqual(["model", "tools"]);
    expect(groups[1]?.items).toEqual([
      {
        kind: "added",
        path: "builtin:new_tool",
        left: null,
        right: "present",
      },
      {
        kind: "source_changed",
        path: "search",
        left: "builtin",
        right: "mcp:web",
      },
    ]);
  });
});
