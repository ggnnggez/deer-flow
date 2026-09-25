"""Admin-only read routes, mounted by the host next to its own API."""

from __future__ import annotations

from typing import Any

from deerflow_extension_api import ExtensionPrincipal, require_admin
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from .read import health, list_tasks, task_residency, thread_tasks
from .service import ResidencyService


def _admin(request: Request) -> ExtensionPrincipal:
    try:
        return require_admin(request)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def build_router(service: ResidencyService) -> APIRouter:
    router = APIRouter(prefix="/api/context-residency", tags=["context-residency"])

    def _session_factory() -> Any:
        if service.session_factory is None:
            raise HTTPException(status_code=503, detail="context residency is not recording: the host has no database session factory or the service is not running")
        return service.session_factory

    @router.get("/tasks")
    async def get_tasks(
        _: ExtensionPrincipal = Depends(_admin),
        query: str | None = Query(None, max_length=200),
        kind: str | None = Query(None, pattern="^(lead|subagent)$"),
        outcome: str | None = Query(None, pattern="^(running|completed|failed|aborted)$"),
        since: str | None = Query(None, max_length=40),
        has_compactions: bool | None = Query(None),
        incomplete_only: bool = Query(False),
        sort: str = Query("started", pattern="^(started|last|duration|attempts|compactions|incomplete|peak)$"),
        direction: str = Query("desc", pattern="^(asc|desc)$"),
        limit: int = Query(50, ge=1, le=500),
        offset: int = Query(0, ge=0),
    ) -> dict[str, Any]:
        data = await list_tasks(
            _session_factory(),
            query=query,
            kind=kind,
            outcome=outcome,
            since=since,
            has_compactions=has_compactions,
            incomplete_only=incomplete_only,
            sort=sort,
            direction=direction,
            limit=limit,
            offset=offset,
        )
        data["projection_status"] = service.status()
        return data

    @router.get("/health")
    async def get_health(_: ExtensionPrincipal = Depends(_admin)) -> dict[str, Any]:
        return await health(service, stale_after_minutes=service.options.stale_task_after_minutes)

    @router.get("/tasks/{task_id}")
    async def get_task_residency(task_id: str, _: ExtensionPrincipal = Depends(_admin)) -> dict[str, Any]:
        data = await task_residency(_session_factory(), task_id, service.options.max_attempts)
        if data is None:
            raise HTTPException(status_code=404, detail="no recorded task with that id")
        data["projection_status"] = service.status()
        return data

    @router.get("/threads/{thread_id}/tasks")
    async def get_thread_tasks(thread_id: str, _: ExtensionPrincipal = Depends(_admin)) -> dict[str, Any]:
        return {"thread_id": thread_id, "tasks": await thread_tasks(_session_factory(), thread_id), "projection_status": service.status()}

    return router
