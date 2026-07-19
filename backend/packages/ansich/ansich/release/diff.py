from __future__ import annotations

from collections import defaultdict

from pydantic import BaseModel, ConfigDict

from ansich.release.manifest import AgentRelease


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FieldChange(_FrozenModel):
    path: str
    left: object
    right: object


class ToolKey(_FrozenModel):
    source: str
    name: str


class ToolValueChange(ToolKey):
    left: object
    right: object


class ToolSourceChange(_FrozenModel):
    name: str
    left_source: str
    right_source: str


class ToolCatalogDiff(_FrozenModel):
    added: tuple[ToolKey, ...] = ()
    removed: tuple[ToolKey, ...] = ()
    schema_changed: tuple[ToolValueChange, ...] = ()
    description_changed: tuple[ToolValueChange, ...] = ()
    source_changed: tuple[ToolSourceChange, ...] = ()


class AgentReleaseComparison(_FrozenModel):
    left_release_hash: str
    right_release_hash: str
    changed_components: tuple[str, ...]
    model: tuple[FieldChange, ...]
    prompt: tuple[FieldChange, ...]
    tools: ToolCatalogDiff
    policy: tuple[FieldChange, ...]
    build: tuple[FieldChange, ...]
    quality_status: str = "unassessed"


def _field_changes(left: object, right: object, *, prefix: str = "") -> tuple[FieldChange, ...]:
    if isinstance(left, dict) and isinstance(right, dict):
        changes: list[FieldChange] = []
        for key in sorted(set(left) | set(right)):
            path = f"{prefix}.{key}" if prefix else key
            if key not in left:
                changes.append(FieldChange(path=path, left=None, right=right[key]))
            elif key not in right:
                changes.append(FieldChange(path=path, left=left[key], right=None))
            else:
                changes.extend(_field_changes(left[key], right[key], prefix=path))
        return tuple(changes)
    if left != right:
        return (FieldChange(path=prefix, left=left, right=right),)
    return ()


def _tools_diff(left: AgentRelease, right: AgentRelease) -> ToolCatalogDiff:
    left_by_key = {(tool.source, tool.name): tool for tool in left.manifest.tools}
    right_by_key = {(tool.source, tool.name): tool for tool in right.manifest.tools}
    common = set(left_by_key) & set(right_by_key)
    schema_changed = tuple(
        ToolValueChange(
            source=source,
            name=name,
            left=left_by_key[(source, name)].schema_hash,
            right=right_by_key[(source, name)].schema_hash,
        )
        for source, name in sorted(common)
        if left_by_key[(source, name)].schema_hash != right_by_key[(source, name)].schema_hash
    )
    description_changed = tuple(
        ToolValueChange(
            source=source,
            name=name,
            left=left_by_key[(source, name)].description,
            right=right_by_key[(source, name)].description,
        )
        for source, name in sorted(common)
        if left_by_key[(source, name)].description != right_by_key[(source, name)].description
    )
    unmatched_left = set(left_by_key) - common
    unmatched_right = set(right_by_key) - common
    left_by_name: dict[str, list[tuple[str, str]]] = defaultdict(list)
    right_by_name: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for key in unmatched_left:
        left_by_name[key[1]].append(key)
    for key in unmatched_right:
        right_by_name[key[1]].append(key)
    source_changed: list[ToolSourceChange] = []
    for name in sorted(set(left_by_name) & set(right_by_name)):
        left_keys = left_by_name[name]
        right_keys = right_by_name[name]
        if len(left_keys) != 1 or len(right_keys) != 1:
            continue
        left_key, right_key = left_keys[0], right_keys[0]
        source_changed.append(
            ToolSourceChange(
                name=name,
                left_source=left_key[0],
                right_source=right_key[0],
            )
        )
        unmatched_left.remove(left_key)
        unmatched_right.remove(right_key)
    return ToolCatalogDiff(
        added=tuple(ToolKey(source=source, name=name) for source, name in sorted(unmatched_right)),
        removed=tuple(ToolKey(source=source, name=name) for source, name in sorted(unmatched_left)),
        schema_changed=schema_changed,
        description_changed=description_changed,
        source_changed=tuple(source_changed),
    )


def compare_agent_releases(left: AgentRelease, right: AgentRelease) -> AgentReleaseComparison:
    left_fingerprint = left.fingerprint
    right_fingerprint = right.fingerprint
    component_pairs = (
        ("model", left_fingerprint.model_hash, right_fingerprint.model_hash),
        ("prompt", left_fingerprint.prompt_hash, right_fingerprint.prompt_hash),
        (
            "tools",
            left_fingerprint.tool_catalog_hash,
            right_fingerprint.tool_catalog_hash,
        ),
        ("policy", left_fingerprint.policy_hash, right_fingerprint.policy_hash),
        (
            "runtime_build",
            left_fingerprint.runtime_build_id,
            right_fingerprint.runtime_build_id,
        ),
    )
    return AgentReleaseComparison(
        left_release_hash=left_fingerprint.release_hash,
        right_release_hash=right_fingerprint.release_hash,
        changed_components=tuple(component for component, left_hash, right_hash in component_pairs if left_hash != right_hash),
        model=_field_changes(
            left.manifest.model.model_dump(mode="python"),
            right.manifest.model.model_dump(mode="python"),
        ),
        prompt=_field_changes(
            left.manifest.prompt.model_dump(
                mode="python",
                exclude={"rendered_base_prompt"},
            ),
            right.manifest.prompt.model_dump(
                mode="python",
                exclude={"rendered_base_prompt"},
            ),
        ),
        tools=_tools_diff(left, right),
        policy=_field_changes(
            left.manifest.policy.model_dump(mode="python"),
            right.manifest.policy.model_dump(mode="python"),
        ),
        build=_field_changes(
            left.manifest.runtime_build.model_dump(mode="python"),
            right.manifest.runtime_build.model_dump(mode="python"),
        ),
    )


__all__ = [
    "AgentReleaseComparison",
    "FieldChange",
    "ToolCatalogDiff",
    "ToolKey",
    "ToolSourceChange",
    "ToolValueChange",
    "compare_agent_releases",
]
