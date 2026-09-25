"""The block-anchored projection: one task's attempts, member inventories and compactions.

Presence is deliberately not precomputed here. A block absent from an
*incomplete* inventory is unknown, never a removal claim, and that three-state
judgment belongs to the reader; a precomputed first/last-seen would flatten it
to two states. Compactions are positioned against the attempt stream by the
timestamps both sides recorded on the same host — recorded order, never a
causal inference — and their removed / preserved / summary members come from
the hashes the compaction event and the summary carrier declared, never from
"it was there last time and not this time".
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from .store import attempts, compactions, members, tasks


def _task_view(row: Any) -> dict[str, Any]:
    return {
        "task_id": row["task_id"],
        "run_id": row["run_id"],
        "thread_id": row["thread_id"],
        "kind": row["kind"],
        "parent_task_id": row["parent_task_id"],
        "agent_name": row["agent_name"],
        "started_at": row["started_at"],
        "stopped_at": row["stopped_at"],
        "outcome": row["outcome"],
    }


async def thread_tasks(session_factory: Any, thread_id: str) -> list[dict[str, Any]]:
    async with session_factory() as session:
        rows = (await session.execute(select(tasks).where(tasks.c.thread_id == thread_id).order_by(tasks.c.started_at, tasks.c.task_id))).mappings().all()
    return [_task_view(row) for row in rows]


async def task_residency(session_factory: Any, task_id: str, max_attempts: int) -> dict[str, Any] | None:
    async with session_factory() as session:
        task_row = (await session.execute(select(tasks).where(tasks.c.task_id == task_id))).mappings().first()
        if task_row is None:
            return None
        attempt_rows = (await session.execute(select(attempts).where(attempts.c.task_id == task_id).order_by(attempts.c.step_seq, attempts.c.attempt_no).limit(max_attempts + 1))).mappings().all()
        truncated = len(attempt_rows) > max_attempts
        attempt_rows = attempt_rows[:max_attempts]
        attempt_ids = [row["attempt_id"] for row in attempt_rows]
        member_rows = (await session.execute(select(members).where(members.c.attempt_id.in_(attempt_ids)).order_by(members.c.attempt_id, members.c.ordinal))).mappings().all() if attempt_ids else []
        compaction_rows = (await session.execute(select(compactions).where(compactions.c.task_id == task_id).order_by(compactions.c.emitted_at, compactions.c.compaction_id))).mappings().all()

    members_by_attempt: dict[str, list[Any]] = {attempt_id: [] for attempt_id in attempt_ids}
    blocks: dict[str, dict[str, Any]] = {}
    for row in member_rows:
        members_by_attempt[row["attempt_id"]].append(row)
        # Latest occurrence wins: identity metadata is the same for every
        # occurrence of a block; sizes are per occurrence and stay on members.
        blocks[row["block_id"]] = {
            "block_id": row["block_id"],
            "kind": row["kind"],
            "role": row["role"],
            "name": row["name"],
            "channel": row["channel"],
            "content_hash": row["content_hash"],
            "source_identity": row["source_identity"],
            "summary_content_hash": row["summary_content_hash"],
            "producer_step_seq": None,
            "producer_call_seq": None,
        }

    attempt_views: list[dict[str, Any]] = []
    for row in attempt_rows:
        attempt_views.append(
            {
                "attempt_id": row["attempt_id"],
                "step_id": row["step_id"],
                "step_seq": row["step_seq"],
                "attempt_no": row["attempt_no"],
                "effective": bool(row["effective"]),
                "snapshot_id": row["attempt_id"],
                "status": row["status"],
                "outcome": row["outcome"],
                "occurred_at": row["occurred_at"],
                "finished_at": row["finished_at"],
                "model_name": row["model_name"],
                "estimated_tokens": row["estimated_tokens"],
                "visible_bytes": row["visible_bytes"],
                "message_count": row["message_count"],
                "tool_schema_count": row["tool_schema_count"],
                "estimator": f"{row['estimator_name']}@{row['estimator_version']}",
                "members": [
                    {
                        "ordinal": member["ordinal"],
                        "block_id": member["block_id"],
                        "estimated_tokens": member["estimated_tokens"],
                        "visible_bytes": member["visible_bytes"],
                        "resolution_status": "available",
                    }
                    for member in members_by_attempt[row["attempt_id"]]
                ],
            }
        )

    compaction_views: list[dict[str, Any]] = []
    for row in compaction_rows:
        positioned_index = next((index for index, attempt in enumerate(attempt_views) if attempt["occurred_at"] >= row["emitted_at"]), None)
        previous = attempt_views[positioned_index - 1] if positioned_index else None
        positioned = attempt_views[positioned_index] if positioned_index is not None else None
        source_hashes = set(row["source_hashes"] or [])
        kept_hashes = set(row["kept_hashes"] or [])
        previous_members = members_by_attempt[previous["attempt_id"]] if previous is not None else []
        positioned_members = members_by_attempt[positioned["attempt_id"]] if positioned is not None else []
        summary_block_id = next((member["block_id"] for member in positioned_members if member["summary_content_hash"] == row["output_hash"]), None)
        compaction_views.append(
            {
                "compression_id": row["compaction_id"],
                "summary_block_id": summary_block_id,
                "occurred_at": row["emitted_at"],
                "status": "positioned" if positioned is not None else "unanchored",
                "transform_kind": row["transform_kind"],
                "transform_version": row["transform_version"],
                "output_hash": row["output_hash"],
                "compacted_count": row["compacted_count"],
                "kept_count": row["kept_count"],
                # Recorded totals of the requests on either side of the boundary —
                # not the summarizer's own count, which the host does not report.
                "before_tokens": previous["estimated_tokens"] if previous is not None else 0,
                "after_tokens": positioned["estimated_tokens"] if positioned is not None else 0,
                "removed_block_ids": [member["block_id"] for member in previous_members if member["content_hash"] in source_hashes],
                "preserved_block_ids": [member["block_id"] for member in previous_members if member["content_hash"] in kept_hashes],
                "positioned_before_attempt_id": positioned["attempt_id"] if positioned is not None else None,
            }
        )

    return {
        "task_id": task_id,
        "task": _task_view(task_row),
        "attempts": attempt_views,
        "blocks": blocks,
        "compressions": compaction_views,
        "attempts_truncated": truncated,
        "projection_status": None,
    }
