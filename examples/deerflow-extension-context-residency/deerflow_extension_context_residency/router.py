"""Admin-only read routes, mounted by the host next to its own API."""

from __future__ import annotations

from typing import Any

from deerflow_extension_api import ExtensionPrincipal, require_admin
from fastapi import APIRouter, Depends, HTTPException, Request

from .read import task_residency, thread_tasks
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
