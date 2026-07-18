from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Literal

from pydantic import BaseModel, ConfigDict

from ansich.tool import ContentDerivationView

LineageDirection = Literal["backward", "forward"]
LineageTruncationReason = Literal["max_depth", "max_nodes"]

DEFAULT_LINEAGE_MAX_DEPTH = 8
DEFAULT_LINEAGE_MAX_NODES = 500
HARD_LINEAGE_MAX_DEPTH = 32
HARD_LINEAGE_MAX_NODES = 2_000


class ContentProducerView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    producer_kind: str
    producer_entity_id: str | None
    producer_obs_id: str


class ContentBlockView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    block_id: str
    kind: str
    content_hash: str
    byte_size: int
    token_estimate: int
    sensitivity_flags: tuple[str, ...] = ()
    payload_status: Literal["available", "missing"]
    producer: ContentProducerView | None = None


class LineageNodeView(ContentBlockView):
    depth: int


class LineageGapView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    block_id: str
    depth: int
    reason: Literal["missing_content_block"]


class ContentLineageView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    semantic: Literal["provenance"] = "provenance"
    root_block_id: str
    direction: LineageDirection
    nodes: tuple[LineageNodeView, ...]
    edges: tuple[ContentDerivationView, ...]
    truncated: bool = False
    truncation_reason: LineageTruncationReason | None = None
    unknown_gaps: tuple[LineageGapView, ...] = ()


class PossibleExposureItemView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: str
    step_id: str
    step_seq: int
    snapshot_id: str
    snapshot_ordinal: int
    descendant_block_id: str
    descendant_depth: int = 0
    ordering: Literal["later", "unknown"]


class PossibleExposureView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    semantic: Literal["possible_exposure"] = "possible_exposure"
    root_block_id: str
    nodes: tuple[LineageNodeView, ...]
    edges: tuple[ContentDerivationView, ...]
    items: tuple[PossibleExposureItemView, ...]
    truncated: bool = False
    truncation_reason: LineageTruncationReason | None = None
    unknown_gaps: tuple[LineageGapView, ...] = ()


GetContentBlocks = Callable[[tuple[str, ...]], Awaitable[list[ContentBlockView]]]
GetContentDerivations = Callable[[tuple[str, ...], LineageDirection], Awaitable[list[ContentDerivationView]]]
ListSnapshotExposures = Callable[
    [str, tuple[str, ...]],
    Awaitable[list[PossibleExposureItemView]],
]


async def traverse_content_lineage(
    root_block_id: str,
    *,
    direction: LineageDirection,
    max_depth: int,
    max_nodes: int,
    get_blocks: GetContentBlocks,
    get_derivations: GetContentDerivations,
) -> ContentLineageView | None:
    """Traverse provenance breadth-first using one node and edge batch per depth."""

    if not 0 <= max_depth <= HARD_LINEAGE_MAX_DEPTH:
        raise ValueError(f"max_depth must be between 0 and {HARD_LINEAGE_MAX_DEPTH}")
    if not 1 <= max_nodes <= HARD_LINEAGE_MAX_NODES:
        raise ValueError(f"max_nodes must be between 1 and {HARD_LINEAGE_MAX_NODES}")

    roots = await get_blocks((root_block_id,))
    root = next((block for block in roots if block.block_id == root_block_id), None)
    if root is None:
        return None

    nodes = [LineageNodeView(**root.model_dump(), depth=0)]
    visited = {root_block_id}
    unresolved: set[str] = set()
    gaps: list[LineageGapView] = []
    edges_by_key: dict[tuple[str, str, str], ContentDerivationView] = {}
    frontier = [root_block_id]
    depth = 0
    truncated = False
    truncation_reason: LineageTruncationReason | None = None

    while frontier:
        level_edges = await get_derivations(tuple(frontier), direction)
        level_edges.sort(
            key=lambda edge: (
                edge.derived_block_id,
                edge.ordinal is None,
                edge.ordinal if edge.ordinal is not None else 0,
                edge.source_block_id,
                edge.transform_kind,
            )
        )
        unseen_neighbors: list[str] = []
        unseen_set: set[str] = set()
        for edge in level_edges:
            neighbor = edge.source_block_id if direction == "backward" else edge.derived_block_id
            if neighbor not in visited and neighbor not in unresolved and neighbor not in unseen_set:
                unseen_neighbors.append(neighbor)
                unseen_set.add(neighbor)

        if depth >= max_depth:
            known_block_ids = visited | unresolved
            for edge in level_edges:
                if edge.derived_block_id in known_block_ids and edge.source_block_id in known_block_ids:
                    edges_by_key.setdefault(
                        (
                            edge.derived_block_id,
                            edge.source_block_id,
                            edge.transform_kind,
                        ),
                        edge,
                    )
            if unseen_neighbors:
                truncated = True
                truncation_reason = "max_depth"
            break

        remaining = max_nodes - len(nodes)
        selected_neighbors = unseen_neighbors[:remaining]
        if len(selected_neighbors) < len(unseen_neighbors):
            truncated = True
            truncation_reason = "max_nodes"

        traversable = visited | unresolved | set(selected_neighbors)
        for edge in level_edges:
            neighbor = edge.source_block_id if direction == "backward" else edge.derived_block_id
            if neighbor in traversable:
                edges_by_key.setdefault(
                    (
                        edge.derived_block_id,
                        edge.source_block_id,
                        edge.transform_kind,
                    ),
                    edge,
                )

        if not selected_neighbors:
            break

        next_depth = depth + 1
        discovered = {block.block_id: block for block in await get_blocks(tuple(selected_neighbors))}
        next_frontier: list[str] = []
        for block_id in selected_neighbors:
            block = discovered.get(block_id)
            if block is None:
                unresolved.add(block_id)
                gaps.append(
                    LineageGapView(
                        block_id=block_id,
                        depth=next_depth,
                        reason="missing_content_block",
                    )
                )
                continue
            visited.add(block_id)
            nodes.append(LineageNodeView(**block.model_dump(), depth=next_depth))
            next_frontier.append(block_id)

        if truncated and truncation_reason == "max_nodes":
            break
        frontier = next_frontier
        depth = next_depth

    return ContentLineageView(
        root_block_id=root_block_id,
        direction=direction,
        nodes=tuple(nodes),
        edges=tuple(edges_by_key.values()),
        truncated=truncated,
        truncation_reason=truncation_reason,
        unknown_gaps=tuple(gaps),
    )


async def find_possible_exposures(
    root_block_id: str,
    *,
    max_depth: int,
    max_nodes: int,
    get_blocks: GetContentBlocks,
    get_derivations: GetContentDerivations,
    list_snapshot_exposures: ListSnapshotExposures,
) -> PossibleExposureView | None:
    """Find later or ordering-unknown Step snapshots containing descendants."""

    lineage = await traverse_content_lineage(
        root_block_id,
        direction="forward",
        max_depth=max_depth,
        max_nodes=max_nodes,
        get_blocks=get_blocks,
        get_derivations=get_derivations,
    )
    if lineage is None:
        return None
    depth_by_block = {node.block_id: node.depth for node in lineage.nodes}
    candidates = await list_snapshot_exposures(
        root_block_id,
        tuple(depth_by_block),
    )
    items = tuple(candidate.model_copy(update={"descendant_depth": depth_by_block[candidate.descendant_block_id]}) for candidate in candidates if candidate.descendant_block_id in depth_by_block)
    return PossibleExposureView(
        root_block_id=root_block_id,
        nodes=lineage.nodes,
        edges=lineage.edges,
        items=items,
        truncated=lineage.truncated,
        truncation_reason=lineage.truncation_reason,
        unknown_gaps=lineage.unknown_gaps,
    )
