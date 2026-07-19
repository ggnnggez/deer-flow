import type {
  AnsichAgentReleaseComparison,
  AnsichReleaseFieldChange,
} from "./types";

export interface AnsichReleaseDiffItem {
  kind:
    | "changed"
    | "added"
    | "removed"
    | "schema_changed"
    | "description_changed"
    | "source_changed";
  path: string;
  left: unknown;
  right: unknown;
}

export interface AnsichReleaseDiffGroup {
  component: "model" | "prompt" | "tools" | "policy" | "runtime_build";
  items: AnsichReleaseDiffItem[];
}

function fieldItems(changes: AnsichReleaseFieldChange[]) {
  return changes.map((change) => ({ kind: "changed" as const, ...change }));
}

function toolItems(
  tools: AnsichAgentReleaseComparison["tools"],
): AnsichReleaseDiffItem[] {
  return [
    ...tools.added.map((tool) => ({
      kind: "added" as const,
      path: `${tool.source}:${tool.name}`,
      left: null,
      right: "present",
    })),
    ...tools.removed.map((tool) => ({
      kind: "removed" as const,
      path: `${tool.source}:${tool.name}`,
      left: "present",
      right: null,
    })),
    ...tools.schema_changed.map((tool) => ({
      kind: "schema_changed" as const,
      path: `${tool.source}:${tool.name}`,
      left: tool.left,
      right: tool.right,
    })),
    ...tools.description_changed.map((tool) => ({
      kind: "description_changed" as const,
      path: `${tool.source}:${tool.name}`,
      left: tool.left,
      right: tool.right,
    })),
    ...tools.source_changed.map((tool) => ({
      kind: "source_changed" as const,
      path: tool.name,
      left: tool.left_source,
      right: tool.right_source,
    })),
  ];
}

export function getAgentReleaseDiffGroups(
  comparison: AnsichAgentReleaseComparison,
): AnsichReleaseDiffGroup[] {
  const groups: AnsichReleaseDiffGroup[] = [
    { component: "model", items: fieldItems(comparison.model) },
    { component: "prompt", items: fieldItems(comparison.prompt) },
    { component: "tools", items: toolItems(comparison.tools) },
    { component: "policy", items: fieldItems(comparison.policy) },
    { component: "runtime_build", items: fieldItems(comparison.build) },
  ];
  return groups.filter((group) => group.items.length > 0);
}
