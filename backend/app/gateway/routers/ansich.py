import base64
import binascii
import json
from datetime import datetime

from ansich.contracts import ControlValue
from fastapi import APIRouter, HTTPException, Query, Request

from app.gateway.deps import require_admin_user

router = APIRouter(prefix="/api/ansich", tags=["ansich"])
_ADMIN_REQUIRED = "Ansich developer/operator observability requires an admin account."


def _service_or_503(request: Request):
    service = getattr(request.app.state, "ansich_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Ansich is disabled or unavailable")
    return service


def _projection_status(service) -> dict:
    return service.get_health().model_dump(mode="json")


def _ensure_queryable(service) -> None:
    health = service.get_health()
    if not health.storage_available:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Ansich storage is unavailable",
                "projection_status": health.model_dump(mode="json"),
            },
        )


def _encode_cursor(as_of: datetime, task_id: str) -> str:
    payload = json.dumps([as_of.isoformat(), task_id], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_cursor(value: str | None) -> tuple[datetime, str] | None:
    if value is None:
        return None
    try:
        padded = value + "=" * (-len(value) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(padded).decode())
        if not isinstance(decoded, list) or len(decoded) != 2 or not all(isinstance(item, str) for item in decoded):
            raise ValueError
        as_of = datetime.fromisoformat(decoded[0])
        if as_of.tzinfo is None:
            raise ValueError
        return as_of, decoded[1]
    except (binascii.Error, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail="Invalid Ansich task cursor") from exc


@router.get("/tasks")
async def list_tasks(
    request: Request,
    control: ControlValue | None = Query(default=None),
    from_time: datetime | None = Query(default=None, alias="from"),
    to_time: datetime | None = Query(default=None, alias="to"),
    limit: int = Query(default=100, ge=1, le=500),
    cursor: str | None = Query(default=None),
) -> dict:
    await require_admin_user(request, detail=_ADMIN_REQUIRED)
    service = _service_or_503(request)
    _ensure_queryable(service)
    for timestamp in (from_time, to_time):
        if timestamp is not None and timestamp.tzinfo is None:
            raise HTTPException(status_code=422, detail="Ansich time filters must include a timezone")
    try:
        tasks = await service.list_tasks(
            limit=limit + 1,
            control=control,
            from_time=from_time,
            to_time=to_time,
            cursor=_decode_cursor(cursor),
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Ansich Task query failed",
                "projection_status": _projection_status(service),
            },
        ) from exc
    page = tasks[:limit]
    next_cursor = None
    if len(tasks) > limit and page and page[-1].control.as_of is not None:
        next_cursor = _encode_cursor(page[-1].control.as_of, page[-1].task_id)
    return {
        "items": [task.model_dump(mode="json") for task in page],
        "next_cursor": next_cursor,
        "projection_status": _projection_status(service),
    }


@router.get("/tasks/{task_id}")
async def get_task(task_id: str, request: Request) -> dict:
    await require_admin_user(request, detail=_ADMIN_REQUIRED)
    service = _service_or_503(request)
    _ensure_queryable(service)
    try:
        task = await service.get_task(task_id)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={"message": "Ansich Task query failed", "projection_status": _projection_status(service)},
        ) from exc
    if task is None:
        raise HTTPException(status_code=404, detail="Ansich Task not found")
    return {
        "task": task.model_dump(mode="json"),
        "projection_status": _projection_status(service),
    }


@router.get("/tasks/{task_id}/timeline")
async def get_task_timeline(task_id: str, request: Request) -> dict:
    await require_admin_user(request, detail=_ADMIN_REQUIRED)
    service = _service_or_503(request)
    _ensure_queryable(service)
    try:
        task = await service.get_task(task_id)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={"message": "Ansich Task query failed", "projection_status": _projection_status(service)},
        ) from exc
    if task is None:
        raise HTTPException(status_code=404, detail="Ansich Task not found")
    try:
        observations = await service.list_observations(task_id)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={"message": "Ansich timeline query failed", "projection_status": _projection_status(service)},
        ) from exc
    return {
        "items": [observation.model_dump(mode="json") for observation in observations],
        "projection_status": _projection_status(service),
    }


@router.get("/health")
async def get_health(request: Request) -> dict:
    await require_admin_user(request, detail=_ADMIN_REQUIRED)
    service = _service_or_503(request)
    return service.get_health().model_dump(mode="json")
