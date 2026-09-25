"""Read projections: one task's residency, the task index, and the extension's own health.

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

import importlib.metadata
import os
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import case, distinct, exists, func, select

from .store import attempts, compactions, members, tasks

_TASK_SORTS = {"started", "last", "duration", "attempts", "compactions", "incomplete", "peak"}


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


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _duration_seconds(started_at: str | None, stopped_at: str | None) -> int | None:
    start, stop = _parse(started_at), _parse(stopped_at)
    if start is None or stop is None:
        return None
    return max(0, round((stop - start).total_seconds()))


async def thread_tasks(session_factory: Any, thread_id: str) -> list[dict[str, Any]]:
    async with session_factory() as session:
        rows = (await session.execute(select(tasks).where(tasks.c.thread_id == thread_id).order_by(tasks.c.started_at, tasks.c.task_id))).mappings().all()
    return [_task_view(row) for row in rows]


async def list_tasks(
    session_factory: Any,
    *,
    query: str | None = None,
    kind: str | None = None,
    outcome: str | None = None,
    since: str | None = None,
    has_compactions: bool | None = None,
    incomplete_only: bool = False,
    sort: str = "started",
    direction: str = "desc",
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """The task index: every recorded task with the counts a reader locates it by.

    ``outcome="running"`` means no stop event was recorded, which is all the
    extension can say — a task the host never stopped notifying about looks the
    same as one still running, and the health view flags the stale ones.
    """
    if sort not in _TASK_SORTS:
        sort = "started"
    attempt_agg = (
        select(
            attempts.c.task_id.label("task_id"),
            func.count().label("attempts"),
            func.count(distinct(attempts.c.step_id)).label("steps"),
            func.sum(case((attempts.c.status == "complete", 0), else_=1)).label("incomplete"),
            func.max(attempts.c.estimated_tokens).label("peak"),
            func.max(attempts.c.occurred_at).label("last_attempt_at"),
        )
        .group_by(attempts.c.task_id)
        .subquery()
    )
    compaction_agg = select(compactions.c.task_id.label("task_id"), func.count().label("compactions")).where(compactions.c.task_id.is_not(None)).group_by(compactions.c.task_id).subquery()
    stmt = select(
        tasks,
        func.coalesce(attempt_agg.c.attempts, 0).label("attempts"),
        func.coalesce(attempt_agg.c.steps, 0).label("steps"),
        func.coalesce(attempt_agg.c.incomplete, 0).label("incomplete"),
        func.coalesce(attempt_agg.c.peak, 0).label("peak"),
        attempt_agg.c.last_attempt_at.label("last_attempt_at"),
        func.coalesce(compaction_agg.c.compactions, 0).label("compactions"),
    ).select_from(tasks.outerjoin(attempt_agg, attempt_agg.c.task_id == tasks.c.task_id).outerjoin(compaction_agg, compaction_agg.c.task_id == tasks.c.task_id))
    if query:
        needle = f"%{query.strip().lower()}%"
        stmt = stmt.where(func.lower(tasks.c.task_id).like(needle) | func.lower(tasks.c.thread_id).like(needle) | func.lower(func.coalesce(tasks.c.agent_name, "")).like(needle))
    if kind:
        stmt = stmt.where(tasks.c.kind == kind)
    if outcome == "running":
        stmt = stmt.where(tasks.c.stopped_at.is_(None))
    elif outcome:
        stmt = stmt.where(tasks.c.outcome == outcome)
    if since:
        stmt = stmt.where(tasks.c.started_at >= since)
    if has_compactions is True:
        stmt = stmt.where(func.coalesce(compaction_agg.c.compactions, 0) > 0)
    elif has_compactions is False:
        stmt = stmt.where(func.coalesce(compaction_agg.c.compactions, 0) == 0)
    if incomplete_only:
        stmt = stmt.where(func.coalesce(attempt_agg.c.incomplete, 0) > 0)

    async with session_factory() as session:
        rows = (await session.execute(stmt)).mappings().all()
        items: list[dict[str, Any]] = []
        for row in rows:
            view = _task_view(row)
            view.update(
                {
                    "steps": int(row["steps"]),
                    "attempts": int(row["attempts"]),
                    "incomplete_attempts": int(row["incomplete"]),
                    "compactions": int(row["compactions"]),
                    "peak_tokens": int(row["peak"]),
                    "last_attempt_at": row["last_attempt_at"],
                    "duration_seconds": _duration_seconds(row["started_at"], row["stopped_at"]),
                    "peak_attempt_id": None,
                    "peak_context_window": None,
                    "peak_by_kind": {},
                }
            )
            items.append(view)

        reverse = direction != "asc"

        def sort_key(item: dict[str, Any]) -> Any:
            if sort == "started":
                return item["started_at"] or ""
            if sort == "last":
                return item["last_attempt_at"] or item["started_at"] or ""
            if sort == "duration":
                if item["duration_seconds"] is not None:
                    return item["duration_seconds"]
                start = _parse(item["started_at"])
                return round((datetime.now(UTC) - start).total_seconds()) if start else 0
            return item[{"attempts": "attempts", "compactions": "compactions", "incomplete": "incomplete_attempts", "peak": "peak_tokens"}[sort]]

        items.sort(key=sort_key, reverse=reverse)
        total = len(items)
        page = items[offset : offset + limit]

        # The peak request's composition, for the page only: one small query per
        # task to find the attempt, one grouped query for all their members.
        peak_ids: dict[str, str] = {}
        for item in page:
            if item["attempts"] == 0:
                continue
            row = (
                await session.execute(select(attempts.c.attempt_id, attempts.c.context_window_tokens).where(attempts.c.task_id == item["task_id"]).order_by(attempts.c.estimated_tokens.desc(), attempts.c.occurred_at.asc()).limit(1))
            ).first()
            if row is not None:
                item["peak_attempt_id"] = row[0]
                item["peak_context_window"] = row[1]
                peak_ids[row[0]] = item["task_id"]
        if peak_ids:
            by_kind = (await session.execute(select(members.c.attempt_id, members.c.kind, func.sum(members.c.estimated_tokens)).where(members.c.attempt_id.in_(list(peak_ids))).group_by(members.c.attempt_id, members.c.kind))).all()
            by_task = {item["task_id"]: item for item in page}
            for attempt_id, kind_value, tokens in by_kind:
                by_task[peak_ids[attempt_id]]["peak_by_kind"][kind_value] = int(tokens or 0)

    return {"tasks": page, "total": total, "limit": limit, "offset": offset, "sort": sort, "direction": "asc" if not reverse else "desc"}


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
                "context_window_tokens": row["context_window_tokens"],
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


def _extension_version() -> str | None:
    try:
        return importlib.metadata.version("deerflow-extension-context-residency")
    except importlib.metadata.PackageNotFoundError:
        return None


def _api_version() -> str | None:
    try:
        from deerflow_extension_api import API_VERSION

        return API_VERSION
    except Exception:  # noqa: BLE001 - the contract package is a declared dependency; this only guards a broken install
        return None


def _config_echo(service: Any) -> dict[str, Any]:
    options = service.options
    return {
        "enabled": options.enabled,
        "max_attempts": options.max_attempts,
        "queue_capacity": options.queue_capacity,
        "flush_interval_ms": options.flush_interval_ms,
        "stale_task_after_minutes": options.stale_task_after_minutes,
        "context_windows": dict(options.context_windows),
        "default_context_window": options.default_context_window,
        "table_prefix": service.status()["table_prefix"],
        "extension_version": _extension_version(),
        "api_version": _api_version(),
        "placements": ["DecisionProbe @ model_logical", "AttemptProbe @ model_physical"],
        "scopes": ["lead", "subagent"],
    }


def _diagnostic(level: str, code: str, title: str, detail: str, remedy: str | None = None, affected: list[str] | None = None) -> dict[str, Any]:
    return {"level": level, "code": code, "title": title, "detail": detail, "remedy": remedy, "affected": affected or []}


def _diagnostics(status: dict[str, Any], quality: dict[str, Any] | None, stale_ids: list[str], stale_after_minutes: int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if not status["running"]:
        items.append(
            _diagnostic(
                "error",
                "not_recording",
                "Not recording",
                "The service has no database session factory (database.backend is memory, or the service failed to start). Capture is off and reads answer 503.",
                "Configure a sqlite or postgres database backend and restart the Gateway.",
            )
        )
    if status["write_failures"] > 0:
        items.append(
            _diagnostic(
                "error",
                "write_failures",
                "Writes failed",
                f"{status['write_failures']} event(s) were lost after a failed database write. Whole batches are dropped, so the affected tasks miss attempts.",
                "Check the Gateway log for the database error; the next flush continues with newer events.",
            )
        )
    if status["dropped"] > 0:
        when = f" Last drop at {status['last_drop_at']}." if status.get("last_drop_at") else ""
        items.append(
            _diagnostic(
                "warning",
                "events_dropped",
                "Events dropped",
                f"{status['dropped']} event(s) were dropped because the buffer was full ({status['queue_capacity']} events).{when} Affected tasks miss attempts; their absences render as unknown, not as removals.",
                "Raise queue_capacity, or lower flush_interval_ms so the writer drains faster.",
            )
        )
    capacity = status.get("queue_capacity") or 0
    if capacity and status["queue_depth"] > 0.8 * capacity:
        items.append(_diagnostic("warning", "queue_pressure", "Buffer nearly full", f"{status['queue_depth']} of {capacity} buffered events are waiting for the writer.", "Lower flush_interval_ms, or check that the database is keeping up."))
    if quality is not None:
        if quality["tasks_stale"] > 0:
            items.append(
                _diagnostic(
                    "warning",
                    "stale_tasks",
                    "Tasks without a stop event",
                    f"{quality['tasks_stale']} task(s) started more than {stale_after_minutes} minutes ago and never recorded a stop. "
                    "They may still be running, or the host skipped the lifecycle notification (the hooks share a 3 s budget).",
                    "Nothing to fix in the recording; the outcome column stays 'running' rather than guessing.",
                    stale_ids,
                )
            )
        if quality["compactions_unanchored"] > 0:
            items.append(
                _diagnostic(
                    "warning",
                    "unanchored_compactions",
                    "Compactions with no task or no later request",
                    f"{quality['compactions_unanchored']} of {quality['compactions_total']} compaction(s) could not be positioned on an attempt stream: "
                    "the event carried no task identity (host older than extension API 0.2.5) or no request followed it.",
                    "Upgrade the host so CompactionEvent carries task_id; unanchored compactions are listed, never guessed onto the matrix.",
                )
            )
        if quality["attempts_incomplete"] > 0:
            items.append(
                _diagnostic(
                    "warning",
                    "incomplete_inventories",
                    "Incomplete inventories",
                    f"{quality['attempts_incomplete']} of {quality['attempts_total']} attempt(s) have an inventory that could not be fully serialized. Their totals are lower bounds and their absences are unknown.",
                    None,
                )
            )
    api = _api_version()
    if api is None:
        items.append(_diagnostic("error", "contract", "Contract package missing", "deerflow_extension_api could not be imported.", "Reinstall the extension with its dependencies."))
    else:
        items.append(_diagnostic("ok", "contract", "Host contract", f"extension API {api}: compaction events carry task identity and kept hashes, summary carriers declare summary_content_hash.", None))
    return items


async def health(service: Any, *, stale_after_minutes: int) -> dict[str, Any]:
    """The extension's own health: is the recording running, complete, and trustworthy."""
    status = service.status()
    generated_at = datetime.now(UTC).isoformat()
    if service.session_factory is None:
        return {
            "generated_at": generated_at,
            "status": status,
            "storage": None,
            "quality": None,
            "diagnostics": _diagnostics(status, None, [], stale_after_minutes),
            "config": _config_echo(service),
            "throughput": status.get("throughput", []),
        }

    stale_before = (datetime.now(UTC) - timedelta(minutes=stale_after_minutes)).isoformat()
    async with service.session_factory() as session:
        rows = {}
        for table in (tasks, attempts, members, compactions):
            rows[table.name] = int((await session.execute(select(func.count()).select_from(table))).scalar_one())
        earliest = (await session.execute(select(func.min(tasks.c.started_at)))).scalar_one()
        tasks_open = int((await session.execute(select(func.count()).select_from(tasks).where(tasks.c.stopped_at.is_(None)))).scalar_one())
        stale_rows = (await session.execute(select(tasks.c.task_id).where(tasks.c.stopped_at.is_(None), tasks.c.started_at < stale_before).order_by(tasks.c.started_at).limit(20))).all()
        attempts_complete = int((await session.execute(select(func.count()).select_from(attempts).where(attempts.c.status == "complete"))).scalar_one())
        compactions_with_task = int((await session.execute(select(func.count()).select_from(compactions).where(compactions.c.task_id.is_not(None)))).scalar_one())
        later_attempt = exists().where(attempts.c.task_id == compactions.c.task_id, attempts.c.occurred_at >= compactions.c.emitted_at)
        compactions_positioned = int((await session.execute(select(func.count()).select_from(compactions).where(compactions.c.task_id.is_not(None), later_attempt))).scalar_one())
        engine = session.get_bind()
        dialect = getattr(getattr(engine, "dialect", None), "name", None) or "unknown"
        database = getattr(getattr(engine, "url", None), "database", None)
        file_bytes = None
        if dialect == "sqlite" and isinstance(database, str) and database and os.path.exists(database):
            file_bytes = os.path.getsize(database)

    quality = {
        "attempts_total": rows[attempts.name],
        "attempts_complete": attempts_complete,
        "attempts_incomplete": rows[attempts.name] - attempts_complete,
        "compactions_total": rows[compactions.name],
        "compactions_with_task": compactions_with_task,
        "compactions_positioned": compactions_positioned,
        "compactions_unanchored": rows[compactions.name] - compactions_positioned,
        "tasks_open": tasks_open,
        "tasks_stale": len(stale_rows),
        "stale_after_minutes": stale_after_minutes,
    }
    stale_ids = [row[0] for row in stale_rows]
    return {
        "generated_at": generated_at,
        "status": status,
        "storage": {
            "backend": dialect,
            "database": database,
            "file_bytes": file_bytes,
            "table_prefix": status["table_prefix"],
            "rows": rows,
            "earliest_task_started_at": earliest,
        },
        "quality": quality,
        "diagnostics": _diagnostics(status, quality, stale_ids, stale_after_minutes),
        "config": _config_echo(service),
        "throughput": status.get("throughput", []),
    }
